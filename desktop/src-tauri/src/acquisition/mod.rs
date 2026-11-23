//! Participant acquisition counts from Qualtrics per-invitation stats. No IO.
//!
//! Mirrors `web/backend/app/acquisition.py`. Each invitation is joined by exact
//! `contactLookupId` (`CGC_…`) or `contactId` (`CID_…`), never by name, email,
//! phone, or external reference.

mod fetch;

use std::collections::{BTreeMap, BTreeSet, HashMap};

use chrono::{DateTime, NaiveDate, NaiveDateTime, Utc};
use chrono_tz::Tz;
use serde::Serialize;

pub use fetch::load_report;

pub const MONITOR_FIELD: &str = "QsMonitor";
const MAX_SPAN_DAYS: i64 = 370;

pub const PREREQUISITE: &str = "Completion counts come from Qualtrics' per-invitation stats.finished on each individual SMS or email distribution listed for this mailing list. No survey answers or response files are downloaded. Responses that Qualtrics auto-closed after expiry are counted as finished by Qualtrics.";

const DENOMINATOR_NOTE: &str = "Expected counts are invitations Qualtrics still lists for this mailing list, placed on the participant's local day by send time. Cancelled invitations that are no longer listed are not in the denominator. The current day counts only prompts whose send time has already passed.";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExportMode {
    DistributionStats,
}

impl ExportMode {
    pub fn as_str(self) -> &'static str {
        match self {
            ExportMode::DistributionStats => "distribution-stats",
        }
    }
}

#[derive(Debug, Clone)]
pub struct Participant {
    pub contact_id: String,
    pub lookup_id: String,
    pub display_name: String,
    pub ext_ref: String,
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
    #[allow(dead_code)]
    pub expire: Option<DateTime<Utc>>,
    pub method: String,
    pub sent: u32,
    pub started: u32,
    pub finished: u32,
    pub failed: u32,
    pub has_stats: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct PromptDetail {
    pub send_local: String,
    pub method: String,
    pub status: String,
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
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub prompts: Vec<PromptDetail>,
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
    pub ext_ref: String,
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

pub fn aggregate(
    participants: &[Participant],
    invitations: &[Invitation],
    now: DateTime<Utc>,
    profile_timezone: &str,
    export_mode: ExportMode,
) -> AcquisitionReport {
    let now = now.with_timezone(&Utc);
    let mut excluded = ExcludedCounts::default();
    let mut limitations = vec![DENOMINATOR_NOTE.to_string()];

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

    let mut attached: Vec<Vec<&Invitation>> = (0..participants.len()).map(|_| Vec::new()).collect();
    let mut unplaceable = vec![0u32; participants.len()];
    let mut unowned_invitations = 0u32;
    let mut removed_contact_invitations = 0u32;

    for invite in invitations {
        if invite.distribution_id.is_empty() || invite.lookup_id.is_empty() {
            unowned_invitations += 1;
            excluded.unjoined_invitations += 1;
            continue;
        }
        let owner = by_lookup
            .get(invite.lookup_id.as_str())
            .or_else(|| by_contact.get(invite.lookup_id.as_str()))
            .copied();
        let Some(owner) = owner else {
            removed_contact_invitations += 1;
            excluded.unjoined_invitations += 1;
            continue;
        };
        if invite.send.is_none() {
            unplaceable[owner] += 1;
            continue;
        }
        attached[owner].push(invite);
    }

    if unowned_invitations > 0 {
        limitations.push(format!(
            "{unowned_invitations} listed invitation(s) had no participant id this profile could resolve. They were not placed on a row, and expected counts were not guessed."
        ));
    }
    if removed_contact_invitations > 0 {
        limitations.push(format!(
            "{removed_contact_invitations} listed invitation(s) on this mailing list belong to contacts no longer on the list and were not shown."
        ));
    }

    let mut rows = Vec::new();
    let mut truncated = false;
    let mut scheduled_without_invites = false;
    let mut bad_start = false;
    let mut unreadable_send = false;
    let mut any_missing_stats = false;

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
                    prompts: Vec::new(),
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
            admins.sort_by(|a, b| {
                a.send
                    .unwrap_or(now)
                    .cmp(&b.send.unwrap_or(now))
                    .then(a.distribution_id.cmp(&b.distribution_id))
            });
            let admin_dates: Vec<_> = admins
                .iter()
                .filter_map(|invite| invite.send.map(|s| s.with_timezone(&zone).date_naive()))
                .collect();
            let start = parse_start(&person.start_date);
            if !person.start_date.trim().is_empty() && start.is_none() {
                bad_start = true;
            }
            let (mut dates, row_truncated) = study_dates(start, person.num_days, today, &admin_dates);
            truncated |= row_truncated;
            let mut by_day: BTreeMap<NaiveDate, Vec<&Invitation>> = BTreeMap::new();
            for day in &dates {
                by_day.insert(*day, Vec::new());
            }
            for invite in &admins {
                let Some(send) = invite.send else { continue };
                let local = send.with_timezone(&zone).date_naive();
                by_day.entry(local).or_default().push(invite);
                if !dates.contains(&local) {
                    dates.push(local);
                }
            }
            dates.sort();
            dates.dedup();
            let mut days = Vec::new();
            let mut to_completed = 0u32;
            let mut to_expected = 0u32;
            let mut row_missing_stats = false;
            for day in dates {
                let day_invites = by_day.get(&day).cloned().unwrap_or_default();
                let mut day_prompts = Vec::with_capacity(day_invites.len());
                let mut due = 0u32;
                let mut later = 0u32;
                let mut completed = 0u32;
                let mut day_unknown = false;
                for invite in day_invites {
                    let Some(send) = invite.send else { continue };
                    let send_local = send.with_timezone(&zone).format("%H:%M").to_string();
                    let status = if invite.finished > 0 {
                        "finished"
                    } else if send > now {
                        "scheduled"
                    } else if !invite.has_stats {
                        "unknown"
                    } else if invite.failed > 0 && invite.sent == 0 {
                        "failed"
                    } else if invite.started > 0 {
                        "started"
                    } else {
                        "sent"
                    };
                    day_prompts.push(PromptDetail {
                        send_local,
                        method: if invite.method == "email" {
                            "email".into()
                        } else {
                            "sms".into()
                        },
                        status: status.into(),
                    });
                    if status == "scheduled" {
                        later += 1;
                    } else {
                        due += 1;
                        if status == "finished" {
                            completed += 1;
                        } else if status == "unknown" {
                            day_unknown = true;
                            row_missing_stats = true;
                            any_missing_stats = true;
                        }
                    }
                }
                if force_unknown || day_unknown {
                    days.push(DayCell {
                        date: day.format("%Y-%m-%d").to_string(),
                        kind: "unknown".into(),
                        completed: None,
                        expected: None,
                        later: 0,
                        prompts: day_prompts,
                    });
                } else if due == 0 && later > 0 {
                    days.push(DayCell {
                        date: day.format("%Y-%m-%d").to_string(),
                        kind: "future".into(),
                        completed: None,
                        expected: None,
                        later,
                        prompts: day_prompts,
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
                        prompts: Vec::new(),
                    });
                } else {
                    days.push(DayCell {
                        date: day.format("%Y-%m-%d").to_string(),
                        kind: "ratio".into(),
                        completed: Some(completed),
                        expected: Some(due),
                        later,
                        prompts: day_prompts,
                    });
                    if day <= today {
                        to_completed += completed;
                        to_expected += due;
                    }
                }
            }
            let mut row_definitive =
                !force_unknown && !row_missing_stats && unowned_invitations == 0;
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
            (today, days, row_definitive, 0, 0, 0, to_date)
        };
        rows.push(AcquisitionRow {
            contact_id: person.contact_id.clone(),
            display_name: person.display_name.clone(),
            ext_ref: person.ext_ref.clone(),
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
    if any_missing_stats {
        limitations.push(
            "Some listed invitations did not include completion stats from Qualtrics, so those days are marked unknown."
                .into(),
        );
    }

    let definitive = if rows.is_empty() {
        unowned_invitations == 0 && excluded.unjoined_invitations == 0
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scheduler::{contact_eligibility, Eligibility, EligibilityDefaults};

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
            ext_ref: "P1".into(),
            timezone_name: "America/Chicago".into(),
            start_date: "2026-07-13".into(),
            num_days: 5,
            monitor: "active".into(),
            surveys_scheduled: 0,
        }
    }

    fn invite(
        id: &str,
        send: &str,
        expire: Option<&str>,
        method: &str,
        sent: u32,
        started: u32,
        finished: u32,
        failed: u32,
    ) -> Invitation {
        Invitation {
            distribution_id: id.into(),
            lookup_id: "CGC_ada".into(),
            send: Some(at(send)),
            expire: expire.map(at),
            method: method.into(),
            sent,
            started,
            finished,
            failed,
            has_stats: true,
        }
    }

    fn day<'a>(report: &'a AcquisitionReport, iso: &str) -> &'a DayCell {
        report.rows[0].days.iter().find(|day| day.date == iso).unwrap()
    }

    #[test]
    fn counts_finished_and_classifies_prompt_statuses() {
        let invites = vec![
            invite("D1", "2026-07-13T13:00:00Z", None, "sms", 1, 1, 1, 0),
            invite("D2", "2026-07-13T15:00:00Z", None, "email", 1, 1, 0, 0),
            invite("D3", "2026-07-13T17:00:00Z", None, "sms", 1, 0, 0, 0),
            invite("D4", "2026-07-13T19:00:00Z", None, "sms", 0, 0, 0, 1),
            invite("D5", "2026-07-15T23:00:00Z", None, "sms", 0, 0, 0, 0),
        ];
        let report = aggregate(
            &[person()],
            &invites,
            now(),
            "America/Chicago",
            ExportMode::DistributionStats,
        );
        assert_eq!(report.export_mode, "distribution-stats");
        assert!(report.definitive);
        let cell = day(&report, "2026-07-13");
        assert_eq!(cell.kind, "ratio");
        assert_eq!(cell.completed, Some(1));
        assert_eq!(cell.expected, Some(4));
        assert_eq!(
            cell.prompts,
            vec![
                PromptDetail { send_local: "08:00".into(), method: "sms".into(), status: "finished".into() },
                PromptDetail { send_local: "10:00".into(), method: "email".into(), status: "started".into() },
                PromptDetail { send_local: "12:00".into(), method: "sms".into(), status: "sent".into() },
                PromptDetail { send_local: "14:00".into(), method: "sms".into(), status: "failed".into() },
            ]
        );
        let day15 = day(&report, "2026-07-15");
        assert_eq!(day15.kind, "future");
        assert_eq!(day15.later, 1);
        assert_eq!(day15.prompts[0].status, "scheduled");
        assert_eq!(report.rows[0].to_date.completed, Some(1));
        assert_eq!(report.rows[0].to_date.expected, Some(4));
        assert!(!report.rows[0].to_date.provisional);
    }

    #[test]
    fn missing_stats_marks_day_unknown_and_provisional() {
        let mut no_stats = invite("D2", "2026-07-14T13:00:00Z", None, "sms", 0, 0, 0, 0);
        no_stats.has_stats = false;
        let report = aggregate(
            &[person()],
            &[
                invite("D1", "2026-07-13T13:00:00Z", None, "sms", 1, 1, 1, 0),
                no_stats,
            ],
            now(),
            "America/Chicago",
            ExportMode::DistributionStats,
        );
        assert_eq!(day(&report, "2026-07-13").kind, "ratio");
        assert_eq!(day(&report, "2026-07-14").kind, "unknown");
        assert_eq!(day(&report, "2026-07-14").prompts[0].status, "unknown");
        assert!(!report.rows[0].definitive);
        assert!(report.rows[0].to_date.provisional);
        assert!(report.limitations.iter().any(|n| n.contains("did not include completion stats")));
    }

    #[test]
    fn current_day_and_empty_kinds_are_distinct() {
        let invites = vec![
            invite("D1", "2026-07-14T13:00:00Z", Some("2026-07-14T14:00:00Z"), "sms", 1, 0, 0, 0),
            invite("Due", "2026-07-15T15:00:00Z", None, "sms", 1, 1, 1, 0),
            invite("Later", "2026-07-15T23:00:00Z", None, "sms", 0, 0, 0, 0),
            invite("Fut", "2026-07-16T13:00:00Z", None, "sms", 0, 0, 0, 0),
        ];
        let report = aggregate(
            &[person()],
            &invites,
            now(),
            "America/Chicago",
            ExportMode::DistributionStats,
        );
        assert_eq!(day(&report, "2026-07-12").kind, "nonStudy");
        assert_eq!(day(&report, "2026-07-14").completed, Some(0));
        assert_eq!(day(&report, "2026-07-14").expected, Some(1));
        assert_eq!(day(&report, "2026-07-15").completed, Some(1));
        assert_eq!(day(&report, "2026-07-15").expected, Some(1));
        assert_eq!(day(&report, "2026-07-15").later, 1);
        assert_eq!(day(&report, "2026-07-16").kind, "future");
        assert_eq!(day(&report, "2026-07-17").kind, "none");
        assert_eq!(report.rows[0].to_date.completed, Some(1));
        assert_eq!(report.rows[0].to_date.expected, Some(2));
    }

    #[test]
    fn removed_contact_invitations_do_not_taint_active_rows() {
        let mut gone = invite("D_gone", "2026-07-14T13:00:00Z", None, "sms", 1, 0, 0, 0);
        gone.lookup_id = "CGC_gone".into();
        let report = aggregate(
            &[person()],
            &[
                invite("D1", "2026-07-14T13:00:00Z", None, "sms", 1, 1, 1, 0),
                gone,
            ],
            now(),
            "America/Chicago",
            ExportMode::DistributionStats,
        );
        assert!(report.rows[0].definitive);
        assert!(report.definitive);
        assert_eq!(report.excluded.unjoined_invitations, 1);
        assert!(report.limitations.iter().any(|n| n.contains("no longer on the list")));
    }

    #[test]
    fn dst_unknown_zone_and_monitor_do_not_invent_or_change_eligibility() {
        let mut spring_person = person();
        spring_person.start_date.clear();
        spring_person.num_days = 0;
        let spring = aggregate(
            &[spring_person.clone()],
            &[
                invite("Before", "2026-03-08T04:30:00Z", None, "sms", 1, 0, 0, 0),
                invite("After", "2026-03-08T07:30:00Z", None, "sms", 1, 0, 0, 0),
            ],
            at("2026-03-08T18:00:00Z"),
            "America/Chicago",
            ExportMode::DistributionStats,
        );
        assert_eq!(day(&spring, "2026-03-07").kind, "ratio");
        assert_eq!(day(&spring, "2026-03-08").kind, "ratio");

        let fall = aggregate(
            &[spring_person],
            &[
                invite("Eve", "2026-11-01T04:59:00Z", None, "sms", 1, 0, 0, 0),
                invite("Morning", "2026-11-01T06:30:00Z", None, "sms", 1, 0, 0, 0),
            ],
            at("2026-11-01T18:00:00Z"),
            "America/Chicago",
            ExportMode::DistributionStats,
        );
        assert_eq!(day(&fall, "2026-10-31").expected, Some(1));
        assert_eq!(day(&fall, "2026-11-01").expected, Some(1));

        let mut bad = person();
        bad.timezone_name = "Mars/Olympus".into();
        let unknown = aggregate(
            &[bad],
            &[invite("D", "2026-07-14T13:00:00Z", None, "sms", 1, 0, 0, 0)],
            now(),
            "America/Chicago",
            ExportMode::DistributionStats,
        );
        assert_eq!(unknown.rows[0].timezone_source, "invalid");
        assert!(unknown.rows[0].days.iter().all(|day| day.kind == "unknown"));
        assert!(unknown.rows[0].to_date.expected.is_none());

        let mut scheduled = person();
        scheduled.surveys_scheduled = 4;
        let empty = aggregate(
            &[scheduled],
            &[],
            now(),
            "America/Chicago",
            ExportMode::DistributionStats,
        );
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
            now(),
            "America/Chicago",
            ExportMode::DistributionStats,
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
            now(),
            "America/Chicago",
            ExportMode::DistributionStats,
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
