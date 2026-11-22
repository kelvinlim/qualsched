//! Completed-response acquisition counts. No IO.
//!
//! Mirrors `web/backend/app/acquisition.py`. A response counts only when its
//! recipient id exactly equals a contact's `contactId` or `contactLookupId`.
//! Name, email, phone, and external reference are not join keys.

mod fetch;

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::io::Read;
use std::sync::atomic::{compiler_fence, Ordering};

use chrono::{DateTime, NaiveDate, NaiveDateTime, Utc};
use chrono_tz::Tz;
use serde::Serialize;
use serde_json::{json, Map, Value};

pub use fetch::load_report;

pub const MONITOR_FIELD: &str = "QsMonitor";
const MAX_SPAN_DAYS: i64 = 370;

const SAFE_METADATA: &[&str] = &[
    "endDate",
    "status",
    "finished",
    "recordedDate",
    "_recordId",
    "distributionChannel",
    "startDate",
];
const EMBEDDED_IDS: &[&str] = &[
    "RecipientID",
    "recipientId",
    "ContactID",
    "contactId",
    "DistributionID",
    "distributionId",
    "Q_DL",
];

pub const PREREQUISITE: &str = "A completion is counted only when the response is finished, its status is a real response (IP Address, Imported, or Offline — not preview, test, synthetic, or spam), and RecipientID or contactId exactly equals that participant's Qualtrics contactId (CID_…) or contactLookupId (CGC_…). Name, email, phone, and external data reference are not used. Qualtrics adds RecipientID for invitations sent to directory contacts; if the export has no such field, completions stay unmatched instead of being guessed.";

const DENOMINATOR_NOTE: &str = "Expected counts are invitations Qualtrics still lists, placed on the participant's local day by send time. The scheduler is not re-run, so changed or random windows follow the booked invitation. A cancelled invitation that is no longer listed is not in the denominator. The current day counts only prompts whose send time has already passed.";

#[derive(Debug)]
pub struct ParseError;

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Qualtrics response export could not be read.")
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExportMode {
    Restricted,
    Embedded,
    Metadata,
}

impl ExportMode {
    fn as_str(self) -> &'static str {
        match self {
            ExportMode::Restricted => "restricted",
            ExportMode::Embedded => "embedded",
            ExportMode::Metadata => "metadata",
        }
    }

    fn rank(self) -> u8 {
        match self {
            ExportMode::Restricted => 0,
            ExportMode::Embedded => 1,
            ExportMode::Metadata => 2,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Participant {
    pub contact_id: String,
    pub lookup_id: String,
    pub display_name: String,
    pub timezone_name: String,
    pub start_date: String,
    pub num_days: i64,
    pub monitor: String,
    pub surveys_scheduled: i64,
}

#[derive(Debug, Clone)]
pub struct Invitation {
    pub distribution_id: String,
    pub lookup_id: String,
    pub send: Option<DateTime<Utc>>,
    pub expire: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct ParsedResponse {
    pub response_id: String,
    pub finished: Option<bool>,
    pub status: Option<i64>,
    pub channel: String,
    pub recipient_id: Option<String>,
    pub distribution_token: Option<String>,
    pub q_dl: Option<String>,
    pub completed_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DayCell {
    pub date: String,
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completed: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expected: Option<u32>,
    pub later: u32,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ToDate {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completed: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expected: Option<u32>,
    pub provisional: bool,
}

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExcludedCounts {
    pub preview: u32,
    pub test: u32,
    pub synthetic: u32,
    pub spam: u32,
    pub unfinished: u32,
    pub other_status: u32,
    pub anonymous: u32,
    pub unmatched_recipient: u32,
    pub conflict: u32,
    pub duplicate_ids: u32,
    pub unjoined_invitations: u32,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AcquisitionRow {
    pub contact_id: String,
    pub display_name: String,
    pub monitor: String,
    pub timezone: String,
    pub timezone_source: String,
    pub today: String,
    pub definitive: bool,
    pub ambiguous: u32,
    pub unmatched_completions: u32,
    pub duplicate_completions: u32,
    pub days: Vec<DayCell>,
    pub to_date: ToDate,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AcquisitionReport {
    pub generated_at: String,
    pub definitive: bool,
    pub prerequisite: String,
    pub limitations: Vec<String>,
    pub export_mode: String,
    pub excluded: ExcludedCounts,
    pub rows: Vec<AcquisitionRow>,
}

/// Status writes. Only `QsMonitor` — never a schedule field.
pub fn monitor_updates(status: &str) -> Result<BTreeMap<String, String>, &'static str> {
    let monitor = match status.trim().to_ascii_lowercase().as_str() {
        "active" => "active",
        "inactive" => "inactive",
        _ => return Err("status must be active or inactive"),
    };
    let mut map = BTreeMap::new();
    map.insert(MONITOR_FIELD.to_string(), monitor.to_string());
    Ok(map)
}

pub fn normalize_monitor(value: &str) -> &'static str {
    if value.trim().eq_ignore_ascii_case("inactive") {
        "inactive"
    } else {
        "active"
    }
}

pub fn export_request_bodies() -> Vec<(ExportMode, Value)> {
    let base = json!({
        "format": "ndjson",
        "compress": true,
        "exportResponsesInProgress": false,
        "surveyMetadataIds": SAFE_METADATA,
    });
    let mut restricted = base.clone();
    restricted["embeddedDataIds"] = json!(EMBEDDED_IDS);
    restricted["questionIds"] = json!([]);
    let mut embedded = base.clone();
    embedded["embeddedDataIds"] = json!(EMBEDDED_IDS);
    vec![
        (ExportMode::Restricted, restricted),
        (ExportMode::Embedded, embedded),
        (ExportMode::Metadata, base),
    ]
}

pub fn wipe(buf: &mut [u8]) {
    for byte in buf {
        unsafe { std::ptr::write_volatile(byte, 0) };
    }
    compiler_fence(Ordering::SeqCst);
}

pub fn parse_utc(raw: &str) -> Option<DateTime<Utc>> {
    let raw = raw.trim();
    if raw.is_empty() {
        return None;
    }
    if let Ok(naive) = NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%SZ") {
        return Some(naive.and_utc());
    }
    DateTime::parse_from_rfc3339(raw)
        .ok()
        .map(|t| t.with_timezone(&Utc))
}

fn as_str(value: &Value) -> Option<String> {
    match value {
        Value::String(text) => {
            let trimmed = text.trim();
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            }
        }
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}

fn pick<'a>(sources: &[&'a Map<String, Value>], keys: &[&str]) -> Option<&'a Value> {
    for source in sources {
        for key in keys {
            if let Some(value) = source.get(*key) {
                if value.is_null() {
                    continue;
                }
                if value.as_str().is_some_and(|text| text.trim().is_empty()) {
                    continue;
                }
                return Some(value);
            }
        }
    }
    None
}

pub fn parse_status(value: &Value) -> Option<i64> {
    match value {
        Value::Bool(_) | Value::Null => None,
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        Value::String(text) => {
            let labels = [
                ("ip address", 0),
                ("survey preview", 1),
                ("survey test", 2),
                ("imported", 4),
                ("spam", 8),
                ("offline", 16),
                ("offline preview", 17),
                ("synthetic", 256),
            ];
            let lower = text.trim().to_ascii_lowercase();
            for (label, code) in labels {
                if lower == label {
                    return Some(code);
                }
            }
            lower.parse().ok()
        }
        _ => None,
    }
}

pub fn parse_finished(value: &Value) -> Option<bool> {
    match value {
        Value::Bool(flag) => Some(*flag),
        Value::Number(n) => {
            let n = n.as_i64().or_else(|| n.as_f64().map(|f| f as i64))?;
            match n {
                1 => Some(true),
                0 => Some(false),
                _ => None,
            }
        }
        Value::String(text) => match text.trim().to_ascii_lowercase().as_str() {
            "1" | "true" => Some(true),
            "0" | "false" => Some(false),
            _ => None,
        },
        _ => None,
    }
}

fn sources(obj: &Map<String, Value>) -> Vec<&Map<String, Value>> {
    let mut found = Vec::new();
    if let Some(values) = obj.get("values").and_then(Value::as_object) {
        found.push(values);
    }
    if let Some(embedded) = obj.get("embeddedData").and_then(Value::as_object) {
        found.push(embedded);
    }
    found.push(obj);
    found
}

pub fn extract_response(obj: &Map<String, Value>, fallback_id: &str) -> ParsedResponse {
    let owned = sources(obj);
    let response_id = pick(&owned, &["responseId", "responseID", "_recordId", "ResponseID"])
        .and_then(as_str)
        .unwrap_or_else(|| fallback_id.to_string());
    let recipient = pick(
        &owned,
        &["RecipientID", "recipientId", "recipientID", "ContactID", "contactId"],
    )
    .and_then(as_str);
    let token = pick(&owned, &["DistributionID", "distributionId", "distributionID"]).and_then(as_str);
    let q_dl = pick(&owned, &["Q_DL", "q_dl"]).and_then(as_str);
    let completed_raw = pick(&owned, &["endDate", "recordedDate", "EndDate", "startDate"]).and_then(as_str);
    let channel = pick(&owned, &["distributionChannel", "DistributionChannel"])
        .and_then(as_str)
        .unwrap_or_default()
        .to_ascii_lowercase();
    ParsedResponse {
        response_id,
        finished: pick(&owned, &["finished", "Finished"]).and_then(parse_finished),
        status: pick(&owned, &["status", "Status"]).and_then(parse_status),
        channel,
        recipient_id: recipient,
        distribution_token: token,
        q_dl,
        completed_at: completed_raw.as_deref().and_then(parse_utc),
    }
}

fn parse_payload(payload: &[u8]) -> Result<Vec<ParsedResponse>, ParseError> {
    let text = std::str::from_utf8(payload).map_err(|_| ParseError)?;
    let stripped = text.trim_start_matches('\u{feff}').trim();
    if stripped.is_empty() {
        return Ok(Vec::new());
    }
    let objects: Vec<Value> = if stripped.starts_with('[') || stripped.starts_with('{') {
        let data: Value = serde_json::from_str(stripped).map_err(|_| ParseError)?;
        if let Some(list) = data.as_array() {
            list.clone()
        } else if let Some(list) = data.get("responses").and_then(Value::as_array) {
            list.clone()
        } else {
            vec![data]
        }
    } else {
        let mut rows = Vec::new();
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            rows.push(serde_json::from_str(line).map_err(|_| ParseError)?);
        }
        rows
    };
    let mut facts = Vec::new();
    for (index, obj) in objects.iter().enumerate() {
        let map = obj.as_object().ok_or(ParseError)?;
        facts.push(extract_response(map, &format!("missing-{index}")));
    }
    Ok(facts)
}

fn read_u16(data: &[u8], at: usize) -> Result<usize, ParseError> {
    let bytes: [u8; 2] = data.get(at..at + 2).ok_or(ParseError)?.try_into().unwrap();
    Ok(u16::from_le_bytes(bytes) as usize)
}

fn read_u32(data: &[u8], at: usize) -> Result<usize, ParseError> {
    let bytes: [u8; 4] = data.get(at..at + 4).ok_or(ParseError)?.try_into().unwrap();
    Ok(u32::from_le_bytes(bytes) as usize)
}

fn find_eocd(data: &[u8]) -> Result<usize, ParseError> {
    if data.len() < 22 {
        return Err(ParseError);
    }
    let start = data.len().saturating_sub(22 + 65_535);
    let mut pos = data.len() - 22;
    loop {
        if data.get(pos..pos + 4) == Some(&b"PK\x05\x06"[..]) {
            return Ok(pos);
        }
        if pos == start {
            break;
        }
        pos -= 1;
    }
    Err(ParseError)
}

/// Read a Qualtrics export archive from memory. Supports stored and deflate
/// entries. ZIP64 (sizes of 0xFFFFFFFF) is refused rather than guessed.
fn unzip_entries(data: &[u8]) -> Result<Vec<Vec<u8>>, ParseError> {
    let eocd = find_eocd(data)?;
    let mut pos = read_u32(data, eocd + 16)?;
    let mut out = Vec::new();
    while data.get(pos..pos + 4) == Some(&b"PK\x01\x02"[..]) {
        let method = read_u16(data, pos + 10)?;
        let comp_size = read_u32(data, pos + 20)?;
        if comp_size == u32::MAX as usize {
            return Err(ParseError);
        }
        let name_len = read_u16(data, pos + 28)?;
        let extra_len = read_u16(data, pos + 30)?;
        let comment_len = read_u16(data, pos + 32)?;
        let local_off = read_u32(data, pos + 42)?;
        let local_name = read_u16(data, local_off + 26)?;
        let local_extra = read_u16(data, local_off + 28)?;
        let data_start = local_off + 30 + local_name + local_extra;
        let compressed = data.get(data_start..data_start + comp_size).ok_or(ParseError)?;
        let payload = match method {
            0 => compressed.to_vec(),
            8 => {
                let mut decoder = flate2::read::DeflateDecoder::new(compressed);
                let mut inflated = Vec::new();
                decoder.read_to_end(&mut inflated).map_err(|_| ParseError)?;
                inflated
            }
            _ => return Err(ParseError),
        };
        out.push(payload);
        pos += 46 + name_len + extra_len + comment_len;
    }
    if out.is_empty() {
        return Err(ParseError);
    }
    Ok(out)
}

pub fn parse_export_bytes(data: &mut [u8]) -> Result<Vec<ParsedResponse>, ParseError> {
    let result = (|| {
        if data.starts_with(b"PK") {
            let entries = unzip_entries(data)?;
            let mut facts = Vec::new();
            for mut payload in entries {
                let parsed = parse_payload(&payload);
                wipe(&mut payload);
                facts.extend(parsed?);
            }
            Ok(facts)
        } else {
            parse_payload(data)
        }
    })();
    wipe(data);
    result
}

fn classify(fact: &ParsedResponse) -> &'static str {
    let channel = fact.channel.as_str();
    let status = fact.status;
    if matches!(status, Some(1 | 17))
        || matches!(channel, "preview" | "surveypreview" | "offlinepreview")
    {
        return "preview";
    }
    if status == Some(2) || channel == "test" {
        return "test";
    }
    if status == Some(256) || channel == "synthetic" {
        return "synthetic";
    }
    if matches!(status, Some(6 | 8 | 9 | 12)) || channel == "spam" {
        return "spam";
    }
    if fact.finished != Some(true) {
        return "unfinished";
    }
    if !matches!(status, Some(0 | 4 | 16)) {
        return "other";
    }
    if fact.recipient_id.as_deref().unwrap_or("").is_empty() {
        return "anonymous";
    }
    "ok"
}

fn resolve_zone(name: &str, profile_timezone: &str) -> (Option<Tz>, &'static str) {
    let raw = name.trim();
    if !raw.is_empty() {
        return match raw.parse::<Tz>() {
            Ok(tz) => (Some(tz), "contact"),
            Err(_) => (None, "invalid"),
        };
    }
    let fallback = profile_timezone.trim();
    if !fallback.is_empty() {
        return match fallback.parse::<Tz>() {
            Ok(tz) => (Some(tz), "profile"),
            Err(_) => (None, "invalid"),
        };
    }
    (None, "missing")
}

fn parse_start(raw: &str) -> Option<NaiveDate> {
    let text = raw.trim();
    if text.is_empty() {
        return None;
    }
    // Char indices, not bytes: a multibyte character on the boundary must not panic.
    let end = text
        .char_indices()
        .nth(10)
        .map(|(index, _)| index)
        .unwrap_or(text.len());
    NaiveDate::parse_from_str(&text[..end], "%Y-%m-%d").ok()
}

/// Add days without panicking. `Duration::days` multiplies into milliseconds and
/// panics when that product overflows; a date past the calendar is `None`.
fn try_shift(day: NaiveDate, days: i64) -> Option<NaiveDate> {
    if days >= 0 {
        day.checked_add_days(chrono::Days::new(days as u64))
    } else {
        let magnitude = days.checked_neg()?;
        day.checked_sub_days(chrono::Days::new(magnitude as u64))
    }
}

fn shift(day: NaiveDate, days: i64) -> NaiveDate {
    try_shift(day, days).unwrap_or(day)
}

fn link_distribution(token: Option<&str>, q_dl: Option<&str>, known: &HashSet<String>) -> Option<String> {
    if let Some(token) = token {
        if !token.is_empty() {
            return Some(token.to_string());
        }
    }
    let Some(q_dl) = q_dl.filter(|value| !value.is_empty()) else {
        return None;
    };
    if known.contains(q_dl) {
        return Some(q_dl.to_string());
    }
    let matches: Vec<_> = known
        .iter()
        .filter(|id| q_dl.starts_with(&format!("{id}_")))
        .cloned()
        .collect();
    if matches.len() == 1 {
        return Some(matches[0].clone());
    }
    Some(String::new())
}

/// `(first offset from start, how many days, whether NumDays was clamped)`.
fn study_window(start: NaiveDate, num_days: i64, today: NaiveDate) -> (i64, i64, bool) {
    if num_days <= MAX_SPAN_DAYS {
        return (0, num_days, false);
    }
    let elapsed = today.signed_duration_since(start).num_days();
    if elapsed < 0 {
        return (0, MAX_SPAN_DAYS, true);
    }
    let offset0 = (elapsed - MAX_SPAN_DAYS + 8).clamp(0, num_days - MAX_SPAN_DAYS);
    (offset0, MAX_SPAN_DAYS, true)
}

fn study_dates(
    start: Option<NaiveDate>,
    num_days: i64,
    today: NaiveDate,
    admin_dates: &[NaiveDate],
) -> (Vec<NaiveDate>, bool) {
    let mut found = BTreeSet::new();
    let mut truncated = false;
    for offset in 0..7 {
        found.insert(shift(today, offset - 6));
    }
    if let Some(start) = start {
        if num_days > 0 {
            // Never walk a corrupt NumDays. Keep at most MAX_SPAN_DAYS of the
            // study, preferring the portion that includes today.
            let (offset0, count, clamped) = study_window(start, num_days, today);
            if clamped {
                truncated = true;
            }
            for offset in 0..count {
                found.insert(shift(start, offset0 + offset));
            }
        }
    }
    for day in admin_dates {
        found.insert(*day);
    }
    let mut ordered: Vec<_> = found.into_iter().collect();
    if let (Some(first), Some(last)) = (ordered.first().copied(), ordered.last().copied()) {
        if last.signed_duration_since(first).num_days() > MAX_SPAN_DAYS {
            let cutoff = shift(last, -MAX_SPAN_DAYS);
            let keep: BTreeSet<_> = (0..7).map(|offset| shift(today, offset - 6)).collect();
            ordered.retain(|day| *day >= cutoff || keep.contains(day));
            truncated = true;
        }
    }
    (ordered, truncated)
}

fn outside_study(day: NaiveDate, start: Option<NaiveDate>, num_days: i64) -> bool {
    let Some(start) = start else {
        return false;
    };
    if num_days <= 0 {
        return false;
    }
    if day < start {
        return true;
    }
    // An end date past the calendar means the study still covers this day.
    match try_shift(start, num_days.saturating_sub(1)) {
        Some(end) => day > end,
        None => false,
    }
}

struct Admin {
    distribution_id: String,
    send: DateTime<Utc>,
    expire: Option<DateTime<Utc>>,
}

fn match_contact(
    admins: &[Admin],
    completions: &[(ParsedResponse, Option<String>)],
) -> (HashMap<usize, ParsedResponse>, u32, u32, u32) {
    let mut assigned: HashMap<usize, ParsedResponse> = HashMap::new();
    let mut by_id: HashMap<&str, usize> = HashMap::new();
    for (index, admin) in admins.iter().enumerate() {
        if !admin.distribution_id.is_empty() {
            by_id.insert(admin.distribution_id.as_str(), index);
        }
    }
    let mut ambiguous = 0u32;
    let mut unmatched = 0u32;
    let mut duplicates = 0u32;
    let mut pending = Vec::new();
    for (fact, dist_id) in completions {
        if let Some(dist_id) = dist_id {
            match by_id.get(dist_id.as_str()) {
                Some(index) => {
                    if assigned.contains_key(index) {
                        duplicates += 1;
                    } else {
                        assigned.insert(*index, fact.clone());
                    }
                }
                None => unmatched += 1,
            }
            continue;
        }
        pending.push(fact);
    }
    pending.sort_by_key(|fact| {
        fact.completed_at
            .unwrap_or_else(|| DateTime::parse_from_rfc3339("1970-01-01T00:00:00Z").unwrap().with_timezone(&Utc))
    });
    let mut open: Vec<usize> = (0..admins.len()).filter(|index| !assigned.contains_key(index)).collect();
    for fact in pending {
        let Some(when) = fact.completed_at else {
            unmatched += 1;
            continue;
        };
        let in_window: Vec<usize> = open
            .iter()
            .copied()
            .filter(|index| {
                let admin = &admins[*index];
                admin.send <= when && admin.expire.map(|expire| when <= expire).unwrap_or(true)
            })
            .collect();
        if in_window.len() == 1 {
            assigned.insert(in_window[0], fact.clone());
            open.retain(|index| *index != in_window[0]);
            continue;
        }
        if in_window.len() > 1 {
            ambiguous += 1;
            continue;
        }
        let late: Vec<usize> = open
            .iter()
            .copied()
            .filter(|index| admins[*index].send <= when)
            .collect();
        if late.len() == 1 {
            assigned.insert(late[0], fact.clone());
            open.retain(|index| *index != late[0]);
            continue;
        }
        unmatched += 1;
    }
    (assigned, ambiguous, unmatched, duplicates)
}

pub fn aggregate(
    participants: &[Participant],
    invitations: &[Invitation],
    responses: &[ParsedResponse],
    now: DateTime<Utc>,
    profile_timezone: &str,
    export_mode: ExportMode,
) -> AcquisitionReport {
    let now = now.with_timezone(&Utc);
    let mut excluded = ExcludedCounts::default();
    let mut limitations = vec![DENOMINATOR_NOTE.to_string()];
    let mut usable = Vec::new();
    let mut seen = HashSet::new();
    for fact in responses {
        if !seen.insert(fact.response_id.clone()) {
            excluded.duplicate_ids += 1;
            continue;
        }
        match classify(fact) {
            "preview" => excluded.preview += 1,
            "test" => excluded.test += 1,
            "synthetic" => excluded.synthetic += 1,
            "spam" => excluded.spam += 1,
            "unfinished" => excluded.unfinished += 1,
            "other" => excluded.other_status += 1,
            "anonymous" => excluded.anonymous += 1,
            _ => usable.push(fact.clone()),
        }
    }

    let mut by_contact: HashMap<&str, usize> = HashMap::new();
    let mut by_lookup: HashMap<&str, usize> = HashMap::new();
    for (index, person) in participants.iter().enumerate() {
        if !person.contact_id.is_empty() {
            by_contact.insert(person.contact_id.as_str(), index);
        }
        if !person.lookup_id.is_empty() {
            by_lookup.insert(person.lookup_id.as_str(), index);
        }
    }

    let mut attached: Vec<Vec<Admin>> = (0..participants.len()).map(|_| Vec::new()).collect();
    let mut unplaceable = vec![0u32; participants.len()];
    let mut known_ids = HashSet::new();
    let mut dist_owner: HashMap<String, usize> = HashMap::new();
    for invite in invitations {
        if invite.distribution_id.is_empty() {
            excluded.unjoined_invitations += 1;
            continue;
        }
        let Some(&owner) = by_lookup.get(invite.lookup_id.as_str()) else {
            excluded.unjoined_invitations += 1;
            continue;
        };
        known_ids.insert(invite.distribution_id.clone());
        dist_owner.insert(invite.distribution_id.clone(), owner);
        let Some(send) = invite.send else {
            unplaceable[owner] += 1;
            continue;
        };
        attached[owner].push(Admin {
            distribution_id: invite.distribution_id.clone(),
            send,
            expire: invite.expire,
        });
    }

    let mut grouped: Vec<Vec<(ParsedResponse, Option<String>)>> =
        (0..participants.len()).map(|_| Vec::new()).collect();
    for fact in &usable {
        let recipient = fact.recipient_id.as_deref().unwrap_or("");
        let owner = by_contact
            .get(recipient)
            .or_else(|| by_lookup.get(recipient))
            .copied();
        let Some(owner) = owner else {
            excluded.unmatched_recipient += 1;
            continue;
        };
        let dist_id = link_distribution(
            fact.distribution_token.as_deref(),
            fact.q_dl.as_deref(),
            &known_ids,
        );
        if let Some(dist_id) = dist_id.as_ref().filter(|id| !id.is_empty()) {
            if let Some(other) = dist_owner.get(dist_id) {
                if *other != owner {
                    excluded.conflict += 1;
                    grouped[owner].push((fact.clone(), Some(String::new())));
                    continue;
                }
            }
        }
        grouped[owner].push((fact.clone(), dist_id));
    }

    if excluded.anonymous > 0 {
        limitations.push(format!(
            "{} finished response(s) had no recipient id and were not applied to any row. Matched counts can be low. {PREREQUISITE}",
            excluded.anonymous
        ));
    }
    if excluded.unmatched_recipient > 0 {
        limitations.push(format!(
            "{} finished response(s) named a recipient id that is not on this mailing list. They were not applied to a row.",
            excluded.unmatched_recipient
        ));
    }
    if excluded.conflict > 0 {
        limitations.push(format!(
            "{} response(s) named both a participant and a different participant's invitation. They were not applied to either row.",
            excluded.conflict
        ));
    }
    if excluded.unjoined_invitations > 0 {
        limitations.push(format!(
            "{} listed invitation(s) had no participant id this profile could resolve. They were not placed on a row, and expected counts were not guessed.",
            excluded.unjoined_invitations
        ));
    }

    let mut rows = Vec::new();
    let mut truncated = false;
    let mut scheduled_without_invites = false;
    let mut bad_start = false;
    let mut unreadable_send = false;
    for (index, person) in participants.iter().enumerate() {
        let (zone, source) = resolve_zone(&person.timezone_name, profile_timezone);
        let monitor = normalize_monitor(&person.monitor);
        let mut force_unknown = matches!(source, "invalid" | "missing");
        if person.lookup_id.is_empty() && excluded.unjoined_invitations > 0 {
            force_unknown = true;
        }
        if unplaceable[index] > 0 {
            force_unknown = true;
            unreadable_send = true;
        }
        let (today, days, row_definitive, ambiguous, unmatched, duplicates, to_date) = if zone.is_none()
        {
            let today = now.date_naive();
            let days = (0..7)
                .map(|offset| DayCell {
                    date: shift(today, offset - 6).format("%Y-%m-%d").to_string(),
                    kind: "unknown".into(),
                    completed: None,
                    expected: None,
                    later: 0,
                })
                .collect();
            (
                today,
                days,
                false,
                0,
                0,
                0,
                ToDate {
                    completed: None,
                    expected: None,
                    provisional: true,
                },
            )
        } else {
            let zone = zone.expect("zone");
            let today = now.with_timezone(&zone).date_naive();
            let mut admins = std::mem::take(&mut attached[index]);
            admins.sort_by(|a, b| a.send.cmp(&b.send).then(a.distribution_id.cmp(&b.distribution_id)));
            let (assigned, ambiguous, unmatched, duplicates) = match_contact(&admins, &grouped[index]);
            let admin_dates: Vec<_> = admins
                .iter()
                .map(|admin| admin.send.with_timezone(&zone).date_naive())
                .collect();
            let start = parse_start(&person.start_date);
            if !person.start_date.trim().is_empty() && start.is_none() {
                bad_start = true;
            }
            let (mut dates, row_truncated) = study_dates(start, person.num_days, today, &admin_dates);
            truncated |= row_truncated;
            let mut by_day: BTreeMap<NaiveDate, Vec<usize>> = BTreeMap::new();
            for day in &dates {
                by_day.insert(*day, Vec::new());
            }
            for (admin_index, admin) in admins.iter().enumerate() {
                let local = admin.send.with_timezone(&zone).date_naive();
                by_day.entry(local).or_default().push(admin_index);
                if !dates.contains(&local) {
                    dates.push(local);
                }
            }
            dates.sort();
            dates.dedup();
            let mut days = Vec::new();
            let mut to_completed = 0u32;
            let mut to_expected = 0u32;
            for day in dates {
                let indexes = by_day.get(&day).cloned().unwrap_or_default();
                if force_unknown {
                    days.push(DayCell {
                        date: day.format("%Y-%m-%d").to_string(),
                        kind: "unknown".into(),
                        completed: None,
                        expected: None,
                        later: 0,
                    });
                    continue;
                }
                let mut due = 0u32;
                let mut later = 0u32;
                let mut completed = 0u32;
                for admin_index in indexes {
                    let admin = &admins[admin_index];
                    let matched = assigned.contains_key(&admin_index);
                    if admin.send <= now || matched {
                        due += 1;
                        if matched {
                            completed += 1;
                        }
                    } else {
                        later += 1;
                    }
                }
                if due == 0 && later > 0 {
                    days.push(DayCell {
                        date: day.format("%Y-%m-%d").to_string(),
                        kind: "future".into(),
                        completed: None,
                        expected: None,
                        later,
                    });
                } else if due == 0 {
                    let kind = if outside_study(day, start, person.num_days) {
                        "nonStudy"
                    } else {
                        "none"
                    };
                    days.push(DayCell {
                        date: day.format("%Y-%m-%d").to_string(),
                        kind: kind.into(),
                        completed: None,
                        expected: None,
                        later: 0,
                    });
                } else {
                    days.push(DayCell {
                        date: day.format("%Y-%m-%d").to_string(),
                        kind: "ratio".into(),
                        completed: Some(completed),
                        expected: Some(due),
                        later,
                    });
                    if day <= today {
                        to_completed += completed;
                        to_expected += due;
                    }
                }
            }
            let mut row_definitive = !force_unknown
                && ambiguous == 0
                && unmatched == 0
                && excluded.anonymous == 0
                && excluded.conflict == 0
                && excluded.unjoined_invitations == 0;
            if person.surveys_scheduled != 0
                && admins.is_empty()
                && unplaceable[index] == 0
                && !person.lookup_id.is_empty()
                && !force_unknown
            {
                scheduled_without_invites = true;
            }
            let to_date = if force_unknown {
                row_definitive = false;
                ToDate {
                    completed: None,
                    expected: None,
                    provisional: true,
                }
            } else {
                ToDate {
                    completed: Some(to_completed),
                    expected: Some(to_expected),
                    provisional: !row_definitive,
                }
            };
            (today, days, row_definitive, ambiguous, unmatched, duplicates, to_date)
        };
        rows.push(AcquisitionRow {
            contact_id: person.contact_id.clone(),
            display_name: person.display_name.clone(),
            monitor: monitor.to_string(),
            timezone: zone.map(|tz| tz.to_string()).unwrap_or_default(),
            timezone_source: source.to_string(),
            today: today.format("%Y-%m-%d").to_string(),
            definitive: row_definitive,
            ambiguous,
            unmatched_completions: unmatched,
            duplicate_completions: duplicates,
            days,
            to_date,
        });
    }

    if unreadable_send {
        limitations.push(
            "An invitation had no readable send time, so that participant's expected total is unknown."
                .into(),
        );
    }
    if truncated {
        limitations.push(format!(
            "A study window longer than {MAX_SPAN_DAYS} days was shortened to the most recent days."
        ));
    }
    if scheduled_without_invites {
        limitations.push(
            "Some participants have SurveysScheduled set but no invitations still listed. Their expected counts stay at the listed invitations rather than a redrawn schedule."
                .into(),
        );
    }
    if bad_start {
        limitations.push(
            "A StartDate could not be read, so days outside the study were not marked for that participant."
                .into(),
        );
    }
    if rows.iter().any(|row| row.ambiguous > 0 || row.unmatched_completions > 0) {
        limitations.push(
            "Some finished responses matched a participant but not a single invitation (more than one open prompt, a late response with several unmatched prompts, or an invitation id this profile does not list). Those responses were not added to a day."
                .into(),
        );
    }
    let definitive = if rows.is_empty() {
        excluded.anonymous == 0 && excluded.unjoined_invitations == 0 && excluded.conflict == 0
    } else {
        rows.iter().all(|row| row.definitive)
    };
    AcquisitionReport {
        generated_at: now.format("%Y-%m-%dT%H:%M:%SZ").to_string(),
        definitive,
        prerequisite: PREREQUISITE.to_string(),
        limitations,
        export_mode: export_mode.as_str().to_string(),
        excluded,
        rows,
    }
}

pub fn wider(a: ExportMode, b: ExportMode) -> ExportMode {
    if a.rank() >= b.rank() {
        a
    } else {
        b
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scheduler::{contact_eligibility, Eligibility, EligibilityDefaults};
    use flate2::write::DeflateEncoder;
    use flate2::Compression;
    use serde_json::json;
    use std::io::Write;

    fn at(raw: &str) -> DateTime<Utc> {
        parse_utc(raw).unwrap()
    }

    fn now() -> DateTime<Utc> {
        at("2026-07-15T18:00:00Z")
    }

    fn person() -> Participant {
        Participant {
            contact_id: "CID_ada".into(),
            lookup_id: "CGC_ada".into(),
            display_name: "Ada Lovelace".into(),
            timezone_name: "America/Chicago".into(),
            start_date: "2026-07-13".into(),
            num_days: 5,
            monitor: "active".into(),
            surveys_scheduled: 0,
        }
    }

    fn invite(id: &str, send: &str, expire: Option<&str>) -> Invitation {
        Invitation {
            distribution_id: id.into(),
            lookup_id: "CGC_ada".into(),
            send: Some(at(send)),
            expire: expire.map(at),
        }
    }

    fn response(id: &str, extra: Value) -> ParsedResponse {
        let mut values = json!({
            "QID1": "secret-symptom",
            "recipientEmail": "ada@example.com",
            "ipAddress": "203.0.113.9"
        });
        for (key, value) in extra.as_object().unwrap() {
            values[key] = value.clone();
        }
        let obj = json!({"responseId": id, "values": values});
        extract_response(obj.as_object().unwrap(), "missing")
    }

    fn day<'a>(report: &'a AcquisitionReport, iso: &str) -> &'a DayCell {
        report.rows[0].days.iter().find(|day| day.date == iso).unwrap()
    }

    fn zip_with(method: u16, stored_len: usize, payload: &[u8]) -> Vec<u8> {
        let name = b"responses.ndjson";
        let mut out = Vec::new();
        out.extend_from_slice(b"PK\x03\x04");
        out.extend_from_slice(&20u16.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&method.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&0u32.to_le_bytes());
        out.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        out.extend_from_slice(&(stored_len as u32).to_le_bytes());
        out.extend_from_slice(&(name.len() as u16).to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(name);
        out.extend_from_slice(payload);
        let local_len = out.len();
        out.extend_from_slice(b"PK\x01\x02");
        out.extend_from_slice(&20u16.to_le_bytes());
        out.extend_from_slice(&20u16.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&method.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&0u32.to_le_bytes());
        out.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        out.extend_from_slice(&(stored_len as u32).to_le_bytes());
        out.extend_from_slice(&(name.len() as u16).to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&0u32.to_le_bytes());
        out.extend_from_slice(&0u32.to_le_bytes());
        out.extend_from_slice(name);
        let cd_len = out.len() - local_len;
        out.extend_from_slice(b"PK\x05\x06");
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(&1u16.to_le_bytes());
        out.extend_from_slice(&1u16.to_le_bytes());
        out.extend_from_slice(&(cd_len as u32).to_le_bytes());
        out.extend_from_slice(&(local_len as u32).to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out
    }

    #[test]
    fn export_request_omits_identity_and_answers() {
        let bodies = export_request_bodies();
        assert_eq!(bodies.len(), 3);
        let first = bodies[0].1.to_string();
        assert!(!first.contains("recipientEmail"));
        assert!(!first.contains("ipAddress"));
        assert!(!first.contains("externalDataReference"));
        assert_eq!(bodies[0].1["questionIds"], json!([]));
        assert_eq!(bodies[0].1["exportResponsesInProgress"], json!(false));
        for (_, body) in &bodies {
            let text = body.to_string();
            assert!(!text.contains("recipientEmail"));
            assert!(!text.contains("ipAddress"));
        }
    }

    #[test]
    fn parser_drops_answers_wipes_buffer_and_errors_do_not_echo() {
        let line = json!({
            "responseId": "R_1",
            "values": {
                "finished": 1,
                "status": 0,
                "endDate": "2026-07-13T13:30:00Z",
                "RecipientID": "CID_ada",
                "QID1": "secret-symptom",
                "recipientEmail": "ada@example.com"
            }
        })
        .to_string();
        let mut raw = zip_with(0, line.len(), line.as_bytes());
        let facts = parse_export_bytes(&mut raw).unwrap();
        assert!(raw.iter().all(|byte| *byte == 0));
        let dumped = format!("{facts:?}");
        assert!(facts[0].recipient_id.as_deref() == Some("CID_ada"));
        assert!(!dumped.contains("secret-symptom"));
        assert!(!dumped.contains("ada@example.com"));

        let mut bad = b"not-an-export secret-symptom".to_vec();
        let err = parse_export_bytes(&mut bad).unwrap_err();
        assert!(!err.to_string().contains("secret-symptom"));
        assert!(bad.iter().all(|byte| *byte == 0));

        let mut encoder = DeflateEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(line.as_bytes()).unwrap();
        let compressed = encoder.finish().unwrap();
        let mut deflated = zip_with(8, line.len(), &compressed);
        let inflated = parse_export_bytes(&mut deflated).unwrap();
        assert_eq!(inflated[0].recipient_id.as_deref(), Some("CID_ada"));
        assert!(deflated.iter().all(|byte| *byte == 0));
    }

    #[test]
    fn completed_only_and_exact_id_rules() {
        let invites = vec![
            invite("D1", "2026-07-13T13:00:00Z", Some("2026-07-13T14:00:00Z")),
            invite("D2", "2026-07-13T15:00:00Z", Some("2026-07-13T16:00:00Z")),
            invite("D3", "2026-07-13T17:00:00Z", Some("2026-07-13T18:00:00Z")),
        ];
        let responses = vec![
            response("R_ok", json!({"finished": 1, "status": 0, "RecipientID": "CID_ada", "DistributionID": "D1", "endDate": "2026-07-13T13:20:00Z"})),
            response("R_preview", json!({"finished": 1, "status": 1, "RecipientID": "CID_ada", "DistributionID": "D1", "endDate": "2026-07-13T13:20:00Z"})),
            response("R_test", json!({"finished": 1, "status": 2, "RecipientID": "CID_ada", "endDate": "2026-07-13T13:20:00Z"})),
            response("R_synthetic", json!({"finished": 1, "status": 256, "RecipientID": "CID_ada", "endDate": "2026-07-13T13:20:00Z"})),
            response("R_spam", json!({"finished": 1, "status": 8, "RecipientID": "CID_ada", "endDate": "2026-07-13T13:20:00Z"})),
            response("R_partial", json!({"finished": 0, "status": 0, "RecipientID": "CID_ada", "endDate": "2026-07-13T13:20:00Z"})),
            response("R_label", json!({"finished": "True", "status": "Survey Preview", "RecipientID": "CID_ada", "endDate": "2026-07-13T13:20:00Z"})),
            response("R_import", json!({"finished": 1, "status": 4, "RecipientID": "CID_ada", "DistributionID": "D2", "endDate": "2026-07-13T15:25:00Z"})),
            response("R_offline", json!({"finished": 1, "status": 16, "RecipientID": "CID_ada", "DistributionID": "D3", "endDate": "2026-07-13T17:10:00Z"})),
            response("R_email", json!({"finished": 1, "status": 0, "endDate": "2026-07-13T13:40:00Z", "recipientEmail": "ada@example.com"})),
        ];
        let report = aggregate(&vec![person()], &invites, &responses, now(), "America/Chicago", ExportMode::Restricted);
        let cell = day(&report, "2026-07-13");
        assert_eq!(cell.completed, Some(3));
        assert_eq!(cell.expected, Some(3));
        assert_eq!(report.excluded.preview, 2);
        assert_eq!(report.excluded.test, 1);
        assert_eq!(report.excluded.synthetic, 1);
        assert_eq!(report.excluded.spam, 1);
        assert_eq!(report.excluded.unfinished, 1);
        assert_eq!(report.excluded.anonymous, 1);
        let dumped = serde_json::to_string(&report).unwrap();
        assert!(!dumped.contains("secret-symptom"));
        assert!(!dumped.contains("ada@example.com"));
        assert!(!report.rows[0].definitive);
    }

    #[test]
    fn dedup_late_current_day_and_distinct_empty_days() {
        let invites = vec![
            invite("D1", "2026-07-13T13:00:00Z", Some("2026-07-13T14:00:00Z")),
            invite("D2", "2026-07-13T17:00:00Z", Some("2026-07-13T18:00:00Z")),
            invite("D3", "2026-07-14T13:00:00Z", Some("2026-07-14T14:00:00Z")),
            invite("D4", "2026-07-15T15:00:00Z", Some("2026-07-15T16:00:00Z")),
            invite("D5", "2026-07-15T23:00:00Z", Some("2026-07-15T23:30:00Z")),
            invite("D6", "2026-07-16T13:00:00Z", Some("2026-07-16T14:00:00Z")),
        ];
        let responses = vec![
            response("R1", json!({"finished": 1, "status": 0, "RecipientID": "CID_ada", "DistributionID": "D1", "endDate": "2026-07-13T13:30:00Z"})),
            response("R1", json!({"finished": 1, "status": 0, "RecipientID": "CID_ada", "DistributionID": "D1", "endDate": "2026-07-13T13:31:00Z"})),
            response("R2", json!({"finished": 1, "status": 0, "RecipientID": "CID_ada", "endDate": "2026-07-13T17:30:00Z"})),
            response("R3", json!({"finished": 1, "status": 0, "RecipientID": "CID_ada", "endDate": "2026-07-15T15:40:00Z"})),
            response("R5", json!({"finished": 1, "status": 0, "RecipientID": "CID_ada", "DistributionID": "D1", "endDate": "2026-07-13T13:50:00Z"})),
            response("Rlate", json!({"finished": 1, "status": 0, "RecipientID": "CID_ada", "endDate": "2026-07-14T20:00:00Z"})),
        ];
        let report = aggregate(&[person()], &invites, &responses, now(), "America/Chicago", ExportMode::Restricted);
        assert_eq!(report.excluded.duplicate_ids, 1);
        assert_eq!(day(&report, "2026-07-13").completed, Some(2));
        assert_eq!(day(&report, "2026-07-14").completed, Some(1));
        assert_eq!(day(&report, "2026-07-15").completed, Some(1));
        assert_eq!(day(&report, "2026-07-15").expected, Some(1));
        assert_eq!(day(&report, "2026-07-15").later, 1);
        assert_eq!(day(&report, "2026-07-16").kind, "future");
        assert_eq!(day(&report, "2026-07-17").kind, "none");
        assert_eq!(day(&report, "2026-07-12").kind, "nonStudy");
        assert_eq!(report.rows[0].duplicate_completions, 1);
        assert_eq!(report.rows[0].to_date.completed, Some(4));
        assert_eq!(report.rows[0].to_date.expected, Some(4));
        assert!(report.rows[0].definitive);

        let zero = aggregate(
            &[person()],
            &[invite("D", "2026-07-14T13:00:00Z", Some("2026-07-14T14:00:00Z"))],
            &[],
            now(),
            "America/Chicago",
            ExportMode::Restricted,
        );
        assert_eq!(day(&zero, "2026-07-14").completed, Some(0));
        assert_eq!(day(&zero, "2026-07-14").expected, Some(1));
        assert_eq!(day(&zero, "2026-07-14").kind, "ratio");

        let odd = aggregate(
            &[person()],
            &[invite("Odd", "2026-07-14T15:17:00Z", Some("2026-07-14T16:17:00Z"))],
            &[],
            now(),
            "America/Chicago",
            ExportMode::Restricted,
        );
        assert_eq!(day(&odd, "2026-07-14").expected, Some(1));
    }

    #[test]
    fn ambiguous_overlap_is_not_attributed() {
        let invites = vec![
            invite("A", "2026-07-13T15:00:00Z", Some("2026-07-13T19:00:00Z")),
            invite("B", "2026-07-13T16:00:00Z", Some("2026-07-13T20:00:00Z")),
        ];
        let responses = vec![response(
            "R",
            json!({"finished": 1, "status": 0, "RecipientID": "CID_ada", "endDate": "2026-07-13T17:00:00Z"}),
        )];
        let report = aggregate(&[person()], &invites, &responses, now(), "America/Chicago", ExportMode::Restricted);
        assert_eq!(day(&report, "2026-07-13").completed, Some(0));
        assert_eq!(day(&report, "2026-07-13").expected, Some(2));
        assert_eq!(report.rows[0].ambiguous, 1);
        assert!(!report.rows[0].definitive);
        assert!(report.rows[0].to_date.provisional);
    }

    #[test]
    fn dst_unknown_zone_and_monitor_do_not_invent_or_change_eligibility() {
        let mut spring_person = person();
        spring_person.start_date.clear();
        spring_person.num_days = 0;
        let spring = aggregate(
            &[spring_person.clone()],
            &[
                invite("Before", "2026-03-08T04:30:00Z", None),
                invite("After", "2026-03-08T07:30:00Z", None),
            ],
            &[],
            at("2026-03-08T18:00:00Z"),
            "America/Chicago",
            ExportMode::Restricted,
        );
        assert_eq!(day(&spring, "2026-03-07").kind, "ratio");
        assert_eq!(day(&spring, "2026-03-08").kind, "ratio");

        let fall = aggregate(
            &[spring_person],
            &[
                invite("Eve", "2026-11-01T04:59:00Z", None),
                invite("Morning", "2026-11-01T06:30:00Z", None),
            ],
            &[],
            at("2026-11-01T18:00:00Z"),
            "America/Chicago",
            ExportMode::Restricted,
        );
        assert_eq!(day(&fall, "2026-10-31").expected, Some(1));
        assert_eq!(day(&fall, "2026-11-01").expected, Some(1));

        let mut bad = person();
        bad.timezone_name = "Mars/Olympus".into();
        let unknown = aggregate(
            &[bad],
            &[invite("D", "2026-07-14T13:00:00Z", None)],
            &[],
            now(),
            "America/Chicago",
            ExportMode::Restricted,
        );
        assert_eq!(unknown.rows[0].timezone_source, "invalid");
        assert!(unknown.rows[0].days.iter().all(|day| day.kind == "unknown"));
        assert!(unknown.rows[0].to_date.expected.is_none());

        let mut scheduled = person();
        scheduled.surveys_scheduled = 4;
        let empty = aggregate(&[scheduled], &[], &[], now(), "America/Chicago", ExportMode::Restricted);
        assert_eq!(day(&empty, "2026-07-14").kind, "none");
        assert_eq!(empty.rows[0].to_date.expected, Some(0));
        assert!(empty.limitations.iter().any(|item| item.contains("SurveysScheduled")));

        let defaults = EligibilityDefaults {
            timezone: "America/Chicago",
            minutes_expire: 60,
        };
        let mut embedded = BTreeMap::from([
            ("StartDate".into(), "2026-07-13".into()),
            ("NumDays".into(), "5".into()),
            ("TimeSlots".into(), "800,1200".into()),
            ("TimeZone".into(), "America/Chicago".into()),
            ("ContactMethod".into(), "sms".into()),
            ("SurveysScheduled".into(), "0".into()),
        ]);
        assert!(matches!(
            contact_eligibility(&embedded, &defaults),
            Eligibility::Eligible { .. }
        ));
        embedded.insert(MONITOR_FIELD.into(), "inactive".into());
        assert!(matches!(
            contact_eligibility(&embedded, &defaults),
            Eligibility::Eligible { .. }
        ));
        let patch = monitor_updates("inactive").unwrap();
        assert_eq!(patch.get(MONITOR_FIELD).map(String::as_str), Some("inactive"));
        assert!(!patch.contains_key("SurveysScheduled"));
        assert!(monitor_updates("deleted").is_err());
    }

    #[test]
    fn multibyte_start_date_does_not_panic() {
        assert!(parse_start("ééééééééééé").is_none());
        assert_eq!(
            parse_start("2026-07-15 and more").unwrap(),
            NaiveDate::from_ymd_opt(2026, 7, 15).unwrap()
        );
    }

    #[test]
    fn huge_num_days_stays_bounded() {
        let mut participant = person();
        participant.num_days = 10_000_000;
        participant.start_date = "2020-01-01".into();
        let report = aggregate(
            &[participant],
            &[],
            &[],
            now(),
            "America/Chicago",
            ExportMode::Restricted,
        );
        assert!(report.rows[0].days.len() <= (MAX_SPAN_DAYS as usize) + 14);
        assert!(report.limitations.iter().any(|item| item.contains("370")));
        assert!(report.rows[0].days.iter().any(|day| day.date == "2026-07-15"));
    }

    #[test]
    fn enormous_num_days_does_not_panic_or_mark_today_outside_the_study() {
        let mut participant = person();
        participant.num_days = i64::MAX;
        participant.start_date = "2020-01-01".into();
        let report = aggregate(
            &[participant],
            &[],
            &[],
            now(),
            "America/Chicago",
            ExportMode::Restricted,
        );
        let today = report
            .rows[0]
            .days
            .iter()
            .find(|day| day.date == "2026-07-15")
            .unwrap();
        assert_ne!(today.kind, "nonStudy");
        assert!(try_shift(NaiveDate::from_ymd_opt(2020, 1, 1).unwrap(), i64::MAX).is_none());
    }
}
