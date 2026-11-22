//! In-memory Qualtrics fetch for the acquisition report.
//!
//! Export bytes stay in a `Vec`, are reduced to completion fields, then overwritten.
//! Nothing is written to disk. This does not clear memory the OS has already paged
//! out, or a crash dump taken while the buffer is live.

use std::time::Duration;

use chrono::{DateTime, Utc};
use serde_json::Value;

use super::{
    wider, wipe, AcquisitionReport, ExportMode, Invitation, ParsedResponse, Participant,
    aggregate, parse_export_bytes, parse_utc,
};
use crate::config::{Account, Project};
use crate::error::{AppError, AppResult};
use crate::qualtrics::{
    contacts,
    machine_code,
    models::RawContact,
    QualtricsClient, RemoteReject,
};
use crate::scheduler::SurveyRef;

const POLL_LIMIT_PER_SURVEY: u32 = 160;
const POLL_LIMIT_TOTAL: u32 = 240;

fn export_failure(
    stage: &str,
    status: Option<u16>,
    code: Option<&str>,
    detail: Option<&str>,
) -> AppError {
    let stage = match stage {
        "start" | "poll" | "download" | "parse" | "timeout" => stage,
        _ => "start",
    };
    let safe = code.and_then(machine_code);
    let note = if let Some(status) = status {
        Some(format!("HTTP {status}"))
    } else if matches!(
        detail,
        Some("timeout" | "export status failed" | "file too large" | "could not be read")
    ) {
        detail.map(str::to_string)
    } else {
        None
    };
    let mut message = format!("Qualtrics response export failed at {stage}");
    if let Some(note) = note {
        message.push_str(&format!(" ({note})"));
    }
    if let Some(code) = safe.as_deref() {
        message.push_str(&format!(" [{code}]"));
    }
    message.push('.');
    let http = status
        .filter(|value| *value >= 400)
        .unwrap_or(if detail == Some("timeout") || stage == "timeout" {
            504
        } else {
            502
        });
    match http {
        401 | 403 => AppError::Unauthorized,
        429 => AppError::RateLimited,
        404 => AppError::NotFound(message),
        _ => AppError::Api(message),
    }
}

fn from_reject(stage: &str, reject: RemoteReject) -> AppError {
    export_failure(stage, Some(reject.status), reject.code.as_deref(), None)
}

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
    ) || progress_status(text, "Exporting survey ")
        || progress_status(text, "Waiting for export ")
        || progress_status(text, "Downloading export ")
}

fn progress_status(text: &str, prefix: &str) -> bool {
    let Some(rest) = text.strip_prefix(prefix) else {
        return false;
    };
    let Some((left, right)) = rest.split_once(" of ") else {
        return false;
    };
    count_token(left) && count_token(right)
}

fn count_token(token: &str) -> bool {
    let Ok(value) = token.parse::<u32>() else {
        return false;
    };
    (1..=999).contains(&value) && !token.starts_with('0')
}

/// One progress body. `percentComplete` is not enough: the file id is usable
/// only when Qualtrics reports `status: complete`.
pub fn progress_view(body: &Value) -> AppResult<Option<String>> {
    let result = match body.get("result") {
        Some(Value::Object(_)) => body.get("result").unwrap(),
        _ => return Err(export_failure("poll", Some(502), None, None)),
    };
    let status = result
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_ascii_lowercase();
    if status == "failed" {
        let code = result
            .pointer("/error/code")
            .and_then(Value::as_str)
            .or_else(|| body.pointer("/meta/error/errorCode").and_then(Value::as_str));
        return Err(export_failure("poll", None, code, Some("export status failed")));
    }
    if status == "complete" {
        if let Some(file_id) = result.get("fileId").and_then(Value::as_str) {
            if !file_id.is_empty() {
                return Ok(Some(file_id.to_string()));
            }
        }
    }
    Ok(None)
}

async fn start_export(client: &QualtricsClient, survey_id: &str) -> AppResult<(String, ExportMode)> {
    let mut last = export_failure("start", Some(502), None, None);
    for (mode, body) in super::export_request_bodies() {
        match client
            .export_json(
                reqwest::Method::POST,
                &format!("surveys/{survey_id}/export-responses"),
                Some(&body),
            )
            .await
        {
            Ok(resp) => {
                if let Some(progress) = resp.pointer("/result/progressId").and_then(Value::as_str) {
                    if !progress.is_empty() {
                        return Ok((progress.to_string(), mode));
                    }
                }
                last = export_failure("start", Some(502), None, None);
            }
            Err(reject) if reject.status == 401 || reject.status == 403 || reject.status == 429 || reject.status == 404 => {
                return Err(from_reject("start", reject));
            }
            Err(reject) => last = from_reject("start", reject),
        }
    }
    Err(last)
}

async fn download_one(
    client: &QualtricsClient,
    survey_id: &str,
    polls_total: &mut u32,
    index: u32,
    total: u32,
    on_status: &impl Fn(&str),
) -> AppResult<(Vec<ParsedResponse>, ExportMode)> {
    publish_status(
        on_status,
        &format!("Exporting survey {index} of {total}"),
    );
    let (progress_id, mode) = start_export(client, survey_id).await?;
    publish_status(
        on_status,
        &format!("Waiting for export {index} of {total}"),
    );
    let mut polls_survey = 0u32;
    let file_id = loop {
        let body = client
            .export_json(
                reqwest::Method::GET,
                &format!("surveys/{survey_id}/export-responses/{progress_id}"),
                None,
            )
            .await
            .map_err(|reject| from_reject("poll", reject))?;
        if let Some(file_id) = progress_view(&body)? {
            break file_id;
        }
        *polls_total += 1;
        polls_survey += 1;
        if polls_survey > POLL_LIMIT_PER_SURVEY || *polls_total > POLL_LIMIT_TOTAL {
            return Err(export_failure("poll", None, None, Some("timeout")));
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    };
    publish_status(
        on_status,
        &format!("Downloading export {index} of {total}"),
    );
    let mut bytes = client
        .get_bytes(&format!(
            "surveys/{survey_id}/export-responses/{file_id}/file"
        ))
        .await?;
    let parsed = parse_export_bytes(&mut bytes).map_err(|_| {
        export_failure("parse", None, None, Some("could not be read"))
    });
    wipe(&mut bytes);
    Ok((parsed?, mode))
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

    let mut responses = Vec::new();
    let mut mode = ExportMode::Columns;
    let mut copy_export_failed = false;
    let mut polls_total = 0u32;
    let surveys = project.survey_rotation();
    let total = surveys.len() as u32;
    for (offset, survey) in surveys.iter().enumerate() {
        match download_one(
            client,
            &survey.id,
            &mut polls_total,
            offset as u32 + 1,
            total,
            on_status,
        )
        .await
        {
            Ok((found, used)) => {
                responses.extend(found);
                mode = wider(mode, used);
            }
            // A leftover copy that Qualtrics rejects must not hide the profile survey.
            // A copy that uses up the poll budget stops there and keeps what the
            // profile survey already contributed.
            Err(_) if survey.id != primary => {
                copy_export_failed = true;
                if polls_total > POLL_LIMIT_TOTAL {
                    break;
                }
            }
            Err(err) => return Err(err),
        }
    }
    publish_status(on_status, "Counting completions");
    let mut report = aggregate(
        &participants,
        &invitations,
        &responses,
        now,
        &project.timezone,
        mode,
    );
    if mode != ExportMode::Columns {
        report.limitations.push(
            "Qualtrics rejected a filtered response export, so a broader file was read in memory and reduced to completion fields before counting. Survey answers were not kept, and names, email, IP, and location were not requested.".into(),
        );
    }
    if copy_export_failed {
        report.limitations.push(
            "A leftover survey copy could not be exported. Completions recorded only on that copy are not in these counts.".into(),
        );
    }
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
        for element in elements {
            let dist_id = element
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .trim()
                .to_string();
            let send = element.get("sendDate").and_then(Value::as_str).and_then(parse_utc);
            invitations.push(Invitation {
                distribution_id: dist_id,
                lookup_id: lookup_of(&element),
                send,
                expire: expiration(&element),
            });
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn progress_waits_for_complete_and_keeps_only_a_machine_code() {
        let pending = progress_view(&json!({
            "result": {
                "status": "inProgress",
                "percentComplete": 100.0,
                "fileId": "FILE1",
                "error": {"message": "ada@example.com", "code": "not a code"}
            }
        }))
        .unwrap();
        assert!(pending.is_none());

        let ready = progress_view(&json!({
            "result": {"status": "complete", "percentComplete": 100, "fileId": "FILE1"}
        }))
        .unwrap();
        assert_eq!(ready.as_deref(), Some("FILE1"));

        let err = progress_view(&json!({
            "result": {
                "status": "failed",
                "error": {"code": "QE_9", "message": "ada@example.com", "context": {"column": "RecipientID"}}
            }
        }))
        .unwrap_err();
        let text = err.to_string();
        assert!(text.contains("at poll (export status failed) [QE_9]."));
        assert!(!text.contains("ada@example.com"));
        assert!(!text.contains("RecipientID"));
    }

    #[test]
    fn status_lines_are_fixed_phrases() {
        assert!(acceptable_status("Loading contacts"));
        assert!(acceptable_status("Exporting survey 1 of 3"));
        assert!(acceptable_status("Waiting for export 2 of 2"));
        assert!(acceptable_status("Downloading export 10 of 12"));
        assert!(!acceptable_status("Exporting survey SV_1 of 3"));
        assert!(!acceptable_status("Loading contacts for ada@example.com"));
        assert!(!acceptable_status("Exporting survey 0 of 1"));
    }

    #[test]
    fn unsafe_error_code_is_omitted() {
        let err = export_failure("start", Some(400), Some("RecipientID missing"), None);
        let text = err.to_string();
        assert!(text.contains("at start (HTTP 400)."));
        assert!(!text.contains("RecipientID"));
    }
}
