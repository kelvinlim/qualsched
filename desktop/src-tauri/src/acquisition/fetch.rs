//! Qualtrics fetch for the acquisition report (contacts + per-invitation distribution stats).

use chrono::{DateTime, Utc};
use serde_json::Value;

use super::{aggregate, parse_utc, AcquisitionReport, ExportMode, Invitation, Participant};
use crate::config::{Account, Project};
use crate::error::{AppError, AppResult};
use crate::qualtrics::{contacts, models::RawContact, QualtricsClient};
use crate::scheduler::SurveyRef;

fn publish_status(on_status: &impl Fn(&str), text: &str) {
    if acceptable_status(text) {
        on_status(text);
    }
}

fn acceptable_status(text: &str) -> bool {
    matches!(
        text,
        "Connecting to Qualtrics"
            | "Loading contacts"
            | "Contacts loaded"
            | "Loading invitations"
            | "Invitations loaded"
            | "Counting completions"
    )
}

fn expiration(element: &Value) -> Option<DateTime<Utc>> {
    for key in ["surveyLinkExpirationDate", "expirationDate"] {
        if let Some(raw) = element.get(key).and_then(Value::as_str) {
            return parse_utc(raw);
        }
    }
    element
        .pointer("/surveyLink/expirationDate")
        .and_then(Value::as_str)
        .and_then(parse_utc)
}

fn lookup_of(element: &Value) -> String {
    element
        .pointer("/recipients/contactId")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string()
}

fn mailing_list_of(element: &Value) -> &str {
    element
        .pointer("/recipients/mailingListId")
        .and_then(Value::as_str)
        .map(str::trim)
        .unwrap_or("")
}

fn stat_u32(stats: &Value, key: &str) -> u32 {
    let Some(value) = stats.get(key) else {
        return 0;
    };
    if let Some(n) = value.as_u64() {
        return n.min(u32::MAX as u64) as u32;
    }
    if let Some(n) = value.as_i64() {
        return if n > 0 { n.min(u32::MAX as i64) as u32 } else { 0 };
    }
    if let Some(n) = value.as_f64() {
        return if n.is_finite() && n > 0.0 {
            n.min(u32::MAX as f64) as u32
        } else {
            0
        };
    }
    if let Some(s) = value.as_str() {
        let trimmed = s.trim();
        if let Ok(n) = trimmed.parse::<i64>() {
            return if n > 0 { n.min(u32::MAX as i64) as u32 } else { 0 };
        }
        if let Ok(n) = trimmed.parse::<f64>() {
            return if n.is_finite() && n > 0.0 {
                n.min(u32::MAX as f64) as u32
            } else {
                0
            };
        }
    }
    0
}

fn invitation_from_element(element: &Value, method: &str) -> Invitation {
    let dist_id = element
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string();
    let send = element
        .get("sendDate")
        .and_then(Value::as_str)
        .and_then(parse_utc);
    let stats = element.get("stats").filter(|v| v.is_object());
    Invitation {
        distribution_id: dist_id,
        lookup_id: lookup_of(element),
        send,
        expire: expiration(element),
        method: method.to_string(),
        sent: stats.map(|s| stat_u32(s, "sent")).unwrap_or(0),
        started: stats.map(|s| stat_u32(s, "started")).unwrap_or(0),
        finished: stats.map(|s| stat_u32(s, "finished")).unwrap_or(0),
        failed: stats.map(|s| stat_u32(s, "failed")).unwrap_or(0),
        has_stats: stats.is_some(),
    }
}

fn int_field(embedded: &std::collections::BTreeMap<String, String>, key: &str) -> i64 {
    let raw = embedded.get(key).map(|value| value.trim()).unwrap_or("");
    if raw.is_empty() {
        return 0;
    }
    raw.parse::<i64>()
        .or_else(|_| raw.parse::<f64>().map(|value| value as i64))
        .unwrap_or(0)
}

fn display_name(contact: &RawContact) -> String {
    let name = format!(
        "{} {}",
        contact.str_field("firstName").unwrap_or_default(),
        contact.str_field("lastName").unwrap_or_default()
    )
    .trim()
    .to_string();
    if !name.is_empty() {
        return name;
    }
    contact
        .str_field("email")
        .or_else(|| contact.str_field("phone"))
        .unwrap_or_else(|| "(unnamed)".to_string())
}

pub async fn load_report(
    client: &QualtricsClient,
    account: &Account,
    project: &Project,
    now: DateTime<Utc>,
    on_status: &impl Fn(&str),
) -> AppResult<AcquisitionReport> {
    publish_status(on_status, "Connecting to Qualtrics");
    publish_status(on_status, "Loading contacts");
    let raw_contacts = contacts::list_contacts(
        client,
        &account.default_directory,
        &project.mailing_list_id,
    )
    .await?;
    let mut participants = Vec::new();
    for raw in &raw_contacts {
        let Some(contact_id) = raw.id() else {
            continue;
        };
        let lookup = match contacts::resolve_contact_lookup_id(
            client,
            &account.default_directory,
            &project.mailing_list_id,
            raw,
        )
        .await
        {
            Ok(id) => id,
            Err(AppError::NotFound(_)) => String::new(),
            Err(err) => return Err(err),
        };
        let embedded = raw.embedded();
        participants.push(Participant {
            contact_id: contact_id.to_string(),
            lookup_id: lookup,
            display_name: display_name(raw),
            ext_ref: raw.str_field("extRef").unwrap_or_default(),
            email: raw.str_field("email").unwrap_or_default(),
            phone: raw.str_field("phone").unwrap_or_default(),
            timezone_name: embedded.get("TimeZone").cloned().unwrap_or_default(),
            start_date: embedded.get("StartDate").cloned().unwrap_or_default(),
            num_days: int_field(&embedded, "NumDays"),
            monitor: embedded
                .get(super::MONITOR_FIELD)
                .cloned()
                .unwrap_or_default(),
            surveys_scheduled: int_field(&embedded, "SurveysScheduled"),
        });
    }
    publish_status(on_status, "Contacts loaded");
    publish_status(on_status, "Loading invitations");

    let mut invitations = Vec::new();
    let mut sms_missing = false;
    let primary = project.survey_id.trim();
    for survey in project.survey_rotation() {
        collect_invitations(
            client,
            project,
            &survey,
            primary,
            &mut invitations,
            &mut sms_missing,
        )
        .await?;
    }
    publish_status(on_status, "Invitations loaded");
    publish_status(on_status, "Counting completions");

    let mut report = aggregate(
        &participants,
        &invitations,
        now,
        &project.timezone,
        ExportMode::DistributionStats,
    );
    if sms_missing {
        report.limitations.push(
            "SMS invitations could not be listed because Qualtrics returned not found. Expected counts include only the invitation lists that responded.".into(),
        );
    }
    Ok(report)
}

async fn collect_invitations(
    client: &QualtricsClient,
    project: &Project,
    survey: &SurveyRef,
    primary: &str,
    invitations: &mut Vec<Invitation>,
    sms_missing: &mut bool,
) -> AppResult<()> {
    let expected_ml = project.mailing_list_id.trim();
    let paths = [
        format!(
            "distributions?mailingListId={}&surveyId={}&distributionRequestType=Invite&useNewPaginationScheme=true",
            project.mailing_list_id, survey.id
        ),
        format!("distributions/sms?surveyId={}", survey.id),
    ];
    for path in paths {
        // An email-only survey can 404 the SMS collection. That must not hide
        // the email invitations. A missing primary survey still fails the email list.
        let sms = path.contains("distributions/sms");
        let elements = match client.get_elements(&path).await {
            Ok(elements) => elements,
            Err(AppError::NotFound(_)) if survey.id != primary || sms => {
                if sms {
                    *sms_missing = true;
                }
                continue;
            }
            Err(err) => return Err(err),
        };
        let method = if sms { "sms" } else { "email" };
        for element in elements {
            let ml = mailing_list_of(&element);
            if !ml.is_empty() && ml != expected_ml {
                continue;
            }
            invitations.push(invitation_from_element(&element, method));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn invitation_extracts_stats_and_filters_mailing_list() {
        let sms = json!({
            "id": "EMD_1",
            "sendDate": "2026-07-14T13:00:00Z",
            "surveyLinkExpirationDate": "2026-07-14T14:00:00Z",
            "recipients": {"contactId": "CGC_ada", "mailingListId": "CG_list"},
            "stats": {"sent": 1, "started": 1, "finished": 1, "failed": 0}
        });
        assert_eq!(mailing_list_of(&sms), "CG_list");
        let inv = invitation_from_element(&sms, "sms");
        assert_eq!(inv.distribution_id, "EMD_1");
        assert_eq!(inv.lookup_id, "CGC_ada");
        assert_eq!(inv.method, "sms");
        assert!(inv.has_stats);
        assert_eq!(inv.sent, 1);
        assert_eq!(inv.started, 1);
        assert_eq!(inv.finished, 1);
        assert_eq!(inv.failed, 0);

        let missing_stats = json!({
            "id": "EMD_2",
            "sendDate": "2026-07-14T13:00:00Z",
            "recipients": {"contactId": "CGC_ada"}
        });
        assert_eq!(mailing_list_of(&missing_stats), "");
        let inv2 = invitation_from_element(&missing_stats, "email");
        assert!(!inv2.has_stats);
        assert_eq!(inv2.method, "email");
    }

    #[test]
    fn status_lines_are_fixed_phrases() {
        assert!(acceptable_status("Loading contacts"));
        assert!(acceptable_status("Counting completions"));
        assert!(!acceptable_status("Loading contacts for ada@example.com"));
        assert!(!acceptable_status("Exporting survey SV_1 of 3"));
    }
}
