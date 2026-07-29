//! Pure scheduling logic: no IO, no globals, injected clock and RNG so every rule here
//! is unit-testable. Ported from qualtrics_util's check_for_send / schedule_multiple_*,
//! with the bugs listed in each section fixed rather than reproduced.

use std::collections::BTreeMap;

use chrono::{DateTime, Duration, LocalResult, NaiveDate, TimeZone, Utc};
use chrono_tz::Tz;
use rand::Rng;
use serde::{Deserialize, Serialize};

pub const DEFAULT_TIMEZONE: &str = "America/Chicago";
const MINUTES_PER_DAY: u32 = 1440;
/// A slot this close to now is treated as already past — the POST would land after it.
const PAST_MARGIN_SECONDS: i64 = 60;

// ---------------------------------------------------------------------------
// Time slots
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Slot {
    /// A literal HHMM time, e.g. 800 -> 08:00.
    Fixed(u16),
    /// A window sampled uniformly, e.g. [800,900]. Anti-habituation for EMA studies.
    Window(u16, u16),
}

/// Parses the `TimeSlots` embedded field, e.g. `"800,[1200,1300],2000"`.
///
/// Replaces the CLI's `eval("[...]")`, which executed arbitrary participant-editable
/// text and accepted nonsense times like 2366.
pub fn parse_time_slots(raw: &str) -> Result<Vec<Slot>, String> {
    let mut slots = Vec::new();
    let mut rest = raw.trim();

    while !rest.is_empty() {
        rest = rest.trim_start_matches([',', ' ', '\t']);
        if rest.is_empty() {
            break;
        }
        if let Some(after) = rest.strip_prefix('[') {
            let (inner, tail) = after
                .split_once(']')
                .ok_or_else(|| format!("unclosed '[' in time slots: {raw:?}"))?;
            let parts: Vec<&str> = inner.split(',').map(str::trim).collect();
            if parts.len() != 2 {
                return Err(format!(
                    "a time window needs exactly two times, got {:?}",
                    inner.trim()
                ));
            }
            slots.push(Slot::Window(parse_hhmm(parts[0])?, parse_hhmm(parts[1])?));
            rest = tail;
        } else {
            let end = rest.find(',').unwrap_or(rest.len());
            let (token, tail) = rest.split_at(end);
            slots.push(Slot::Fixed(parse_hhmm(token)?));
            rest = tail;
        }
    }
    Ok(slots)
}

fn parse_hhmm(token: &str) -> Result<u16, String> {
    let token = token.trim();
    if token.is_empty() {
        return Err("empty time value".into());
    }
    let n: u16 = token
        .parse()
        .map_err(|_| format!("{token:?} is not a whole number time like 800 or 1430"))?;
    let (h, m) = (n / 100, n % 100);
    if h > 23 {
        return Err(format!("{token:?} has an hour above 23"));
    }
    if m > 59 {
        return Err(format!("{token:?} has a minute above 59"));
    }
    Ok(n)
}

/// Fallback for studies whose contacts carry `Time1`, `Time2`, … integers instead of a
/// `TimeSlots` list — the Qualtrics web UI cannot author list-valued embedded data.
pub fn slots_from_time_n(embedded: &BTreeMap<String, String>) -> Result<Vec<Slot>, String> {
    let mut keys: Vec<&String> = embedded
        .keys()
        .filter(|k| k.starts_with("Time") && !k.contains("TimeZone") && !k.contains("TimeSlots"))
        .collect();
    keys.sort();

    keys.iter()
        .map(|k| {
            let raw = &embedded[*k];
            parse_hhmm(raw).map(Slot::Fixed).map_err(|e| format!("{k}: {e}"))
        })
        .collect()
}

fn hhmm_to_minutes(hhmm: u16) -> u32 {
    (hhmm / 100) as u32 * 60 + (hhmm % 100) as u32
}

/// Resolved offset from the start of the target day. `extra_days` is 1 when a window
/// crossed midnight, which the CLI's `get_time` produced garbage for (its TODO at
/// scheduler.py:80 about `[2350,0010]`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ResolvedTime {
    pub minutes: u32,
    pub extra_days: i64,
}

pub fn resolve_slot<R: Rng + ?Sized>(slot: Slot, rng: &mut R) -> ResolvedTime {
    match slot {
        Slot::Fixed(hhmm) => ResolvedTime {
            minutes: hhmm_to_minutes(hhmm),
            extra_days: 0,
        },
        Slot::Window(start, end) => {
            let start_m = hhmm_to_minutes(start);
            let end_m = hhmm_to_minutes(end);
            // A window whose end is before its start wraps past midnight; sample on the
            // unwrapped line, then fold back and carry the day.
            let span_end = if end_m >= start_m {
                end_m
            } else {
                end_m + MINUTES_PER_DAY
            };
            let picked = if span_end == start_m {
                start_m
            } else {
                rng.gen_range(start_m..=span_end)
            };
            ResolvedTime {
                minutes: picked % MINUTES_PER_DAY,
                extra_days: (picked / MINUTES_PER_DAY) as i64,
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Eligibility
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Method {
    Sms,
    Email,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Eligibility {
    Eligible {
        method: Method,
        slots: Vec<Slot>,
        num_days: i64,
        start_date: String,
        timezone: String,
        expire_minutes: i64,
    },
    Skipped(String),
}

pub struct EligibilityDefaults<'a> {
    pub timezone: &'a str,
    pub minutes_expire: u32,
}

/// Resolves how a participant is contacted, independent of whether they are currently
/// eligible to be scheduled.
///
/// Kept separate from [`contact_eligibility`] because the UI needs to show a delivery
/// channel for everyone, including participants who have already been scheduled and so
/// are not eligible. `Err` explains why no channel could be determined.
pub fn delivery_method(embedded: &BTreeMap<String, String>) -> Result<Method, String> {
    let contact_method = embedded
        .get("ContactMethod")
        .map(|s| s.trim().to_ascii_uppercase())
        .unwrap_or_default();
    let use_sms = int_field(embedded, "UseSMS").unwrap_or(0);
    // ContactMethod wins when set; UseSMS is the legacy fallback.
    match contact_method.as_str() {
        "EMAIL" => Ok(Method::Email),
        "SMS" => Ok(Method::Sms),
        _ if use_sms == 1 => Ok(Method::Sms),
        "" => Err("no ContactMethod and UseSMS is not 1".into()),
        other => Err(format!("ContactMethod {other:?} is not 'sms' or 'email'")),
    }
}

/// Decides whether a contact should be scheduled, and with what parameters.
///
/// A malformed field yields `Skipped` with a human-readable reason — never an abort.
/// One bad participant record must not stop the rest of the batch.
pub fn contact_eligibility(
    embedded: &BTreeMap<String, String>,
    defaults: &EligibilityDefaults,
) -> Eligibility {
    let surveys_scheduled = int_field(embedded, "SurveysScheduled").unwrap_or(0);
    if surveys_scheduled != 0 {
        return Eligibility::Skipped(format!(
            "already scheduled (SurveysScheduled = {surveys_scheduled})"
        ));
    }

    let num_days = int_field(embedded, "NumDays").unwrap_or(0);
    if num_days <= 0 {
        return Eligibility::Skipped("NumDays is 0 or unset".into());
    }

    let method = match delivery_method(embedded) {
        Ok(m) => m,
        Err(reason) => return Eligibility::Skipped(reason),
    };

    let slots = match embedded.get("TimeSlots") {
        Some(raw) => match parse_time_slots(raw) {
            Ok(s) => s,
            Err(e) => return Eligibility::Skipped(format!("TimeSlots invalid: {e}")),
        },
        None => match slots_from_time_n(embedded) {
            Ok(s) => s,
            Err(e) => return Eligibility::Skipped(format!("TimeN fields invalid: {e}")),
        },
    };
    if slots.is_empty() {
        return Eligibility::Skipped("no time slots set".into());
    }

    let start_date = embedded
        .get("StartDate")
        .map(|s| s.trim().to_string())
        .unwrap_or_default();
    if start_date.is_empty() {
        return Eligibility::Skipped("StartDate is not set".into());
    }

    let timezone = embedded
        .get("TimeZone")
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .unwrap_or(defaults.timezone)
        .to_string();

    // Reads ExpireMinutes, the key every config actually writes. The CLI looked up
    // MINUTES_EXP, which never matched MINUTES_EXPIRE and silently fell back to 60.
    let expire_minutes =
        int_field(embedded, "ExpireMinutes").unwrap_or(defaults.minutes_expire as i64);

    Eligibility::Eligible {
        method,
        slots,
        num_days,
        start_date,
        timezone,
        expire_minutes,
    }
}

fn int_field(embedded: &BTreeMap<String, String>, key: &str) -> Option<i64> {
    let raw = embedded.get(key)?.trim();
    if raw.is_empty() {
        return None;
    }
    raw.parse::<i64>()
        .ok()
        .or_else(|| raw.parse::<f64>().ok().map(|f| f as i64))
}

// ---------------------------------------------------------------------------
// Plan building
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PlanItem {
    pub contact_id: String,
    pub contact_name: String,
    /// Phone number or email address the invitation goes to.
    pub destination: String,
    pub method: Method,
    pub day_index: i64,
    pub slot_label: String,
    /// Local wall-clock time in the recipient's timezone, with the zone shown.
    pub send_local: String,
    pub send_utc: DateTime<Utc>,
    pub expire_utc: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Skipped {
    pub contact_id: String,
    pub contact_name: String,
    pub reason: String,
}

pub struct PlanInputs<'a> {
    pub contact_id: &'a str,
    pub contact_name: &'a str,
    pub destination: &'a str,
    pub method: Method,
    pub slots: &'a [Slot],
    pub num_days: i64,
    pub start_date: &'a str,
    pub timezone: &'a str,
    pub expire_minutes: i64,
}

/// Expands one contact into its individual future distributions.
///
/// Returns the sendable items plus a reason for each slot that was dropped, so the
/// preview can explain a short plan instead of silently producing fewer invitations.
pub fn build_contact_plan<R: Rng + ?Sized>(
    input: &PlanInputs,
    now: DateTime<Utc>,
    rng: &mut R,
) -> (Vec<PlanItem>, Vec<Skipped>) {
    let mut items = Vec::new();
    let mut skipped = Vec::new();

    let skip = |reason: String| Skipped {
        contact_id: input.contact_id.to_string(),
        contact_name: input.contact_name.to_string(),
        reason,
    };

    let tz: Tz = match input.timezone.parse() {
        Ok(tz) => tz,
        Err(_) => {
            return (
                items,
                vec![skip(format!(
                    "unknown timezone {:?} (expected an IANA name like America/Chicago)",
                    input.timezone
                ))],
            )
        }
    };

    let start = match parse_start_date(input.start_date) {
        Some(d) => d,
        None => {
            return (
                items,
                vec![skip(format!(
                    "StartDate {:?} is not a YYYY-MM-DD date",
                    input.start_date
                ))],
            )
        }
    };

    let cutoff = now + Duration::seconds(PAST_MARGIN_SECONDS);

    for day in 0..input.num_days {
        for slot in input.slots {
            let resolved = resolve_slot(*slot, rng);
            let date = match start.checked_add_signed(Duration::days(day + resolved.extra_days)) {
                Some(d) => d,
                None => {
                    skipped.push(skip("date arithmetic overflowed".into()));
                    continue;
                }
            };

            let send_utc = match local_to_utc(&tz, date, resolved.minutes) {
                Some(t) => t,
                None => {
                    skipped.push(skip(format!(
                        "{date} {} has no valid time in {}",
                        fmt_minutes(resolved.minutes),
                        input.timezone
                    )));
                    continue;
                }
            };

            // The CLI POSTed past-dated slots; Qualtrics accepts them and they never fire.
            if send_utc <= cutoff {
                skipped.push(skip(format!(
                    "{} {} is in the past",
                    date,
                    fmt_minutes(resolved.minutes)
                )));
                continue;
            }

            let local = send_utc.with_timezone(&tz);
            items.push(PlanItem {
                contact_id: input.contact_id.to_string(),
                contact_name: input.contact_name.to_string(),
                destination: input.destination.to_string(),
                method: input.method,
                day_index: day,
                slot_label: slot_label(*slot),
                send_local: local.format("%Y-%m-%d %H:%M %Z").to_string(),
                send_utc,
                expire_utc: send_utc + Duration::minutes(input.expire_minutes),
            });
        }
    }

    (items, skipped)
}

fn parse_start_date(raw: &str) -> Option<NaiveDate> {
    let raw = raw.trim();
    // Tolerate a full timestamp; only the date part is meaningful.
    let date_part = raw.split(['T', ' ']).next().unwrap_or(raw);
    NaiveDate::parse_from_str(date_part, "%Y-%m-%d").ok()
}

/// Converts a local wall-clock time to UTC, resolving DST transitions:
/// - fall-back (time occurs twice) picks the earlier instant
/// - spring-forward (time does not exist) advances to the first valid minute
fn local_to_utc(tz: &Tz, date: NaiveDate, minutes: u32) -> Option<DateTime<Utc>> {
    for offset in 0..=120u32 {
        let total = minutes + offset;
        let (day_shift, wrapped) = (total / MINUTES_PER_DAY, total % MINUTES_PER_DAY);
        let d = date.checked_add_signed(Duration::days(day_shift as i64))?;
        let naive = d.and_hms_opt(wrapped / 60, wrapped % 60, 0)?;
        match tz.from_local_datetime(&naive) {
            LocalResult::Single(t) => return Some(t.with_timezone(&Utc)),
            LocalResult::Ambiguous(earlier, _) => return Some(earlier.with_timezone(&Utc)),
            LocalResult::None => continue,
        }
    }
    None
}

fn fmt_minutes(minutes: u32) -> String {
    format!("{:02}:{:02}", minutes / 60, minutes % 60)
}

fn slot_label(slot: Slot) -> String {
    match slot {
        Slot::Fixed(t) => format!("{t:04}"),
        Slot::Window(a, b) => format!("[{a:04},{b:04}]"),
    }
}

// ---------------------------------------------------------------------------
// Message suffix
// ---------------------------------------------------------------------------

/// Qualtrics refuses a second invitation with identical content on the same day, so
/// each message body gets a unique tag appended. Format matches the CLI's so existing
/// participants see nothing new.
pub fn decorate_message<R: Rng + ?Sized>(body: &str, rng: &mut R) -> String {
    format!("{body}\n&nbsp;\n{}\n", random_tag(rng))
}

fn random_tag<R: Rng + ?Sized>(rng: &mut R) -> String {
    const LETTERS: &[u8] = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
    const DIGITS: &[u8] = b"0123456789";
    // Two letters, a digit, two letters, a digit, two letters — as the CLI built it.
    let pattern = [false, false, true, false, false, true, false, false];
    let mut s = String::with_capacity(11);
    s.push_str("\n[");
    for is_digit in pattern {
        let pool = if is_digit { DIGITS } else { LETTERS };
        s.push(pool[rng.gen_range(0..pool.len())] as char);
    }
    s.push(']');
    s
}

#[cfg(test)]
mod tests;
