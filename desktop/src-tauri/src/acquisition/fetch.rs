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
    models::RawContact,
    QualtricsClient,
};
use crate::scheduler::SurveyRef;

fn static_export(err: AppError) -> AppError {
    match err {
        AppError::Unauthorized | AppError::RateLimited | AppError::MissingToken => err,
        AppError::NotFound(_) => AppError::NotFound("Qualtrics response export failed (HTTP 404).".into()),
        other => {
            let status = match &other {
                AppError::Api(message) => message
                    .split("HTTP ")
                    .nth(1)
                    .and_then(|rest| rest.split(')').next())
                    .unwrap_or("502"),
                _ => "502",
            };
            AppError::Api(format!("Qualtrics response export failed (HTTP {status})."))
        }
    }
}

async fn start_export(client: &QualtricsClient, survey_id: &str) -> AppResult<(String, ExportMode)> {
    let mut last = AppError::Api("Qualtrics response export failed (HTTP 502).".into());
    for (mode, body) in super::export_request_bodies() {
        match client
            .post(&format!("surveys/{survey_id}/export-responses"), &body)
            .await
        {
            Ok(resp) => {
                if let Some(progress) = resp.pointer("/result/progressId").and_then(Value::as_str) {
                    if !progress.is_empty() {
                        return Ok((progress.to_string(), mode));
                    }
                }
                last = AppError::Api("Qualtrics response export failed (HTTP 502).".into());
            }
            Err(AppError::Unauthorized) => return Err(AppError::Unauthorized),
            Err(AppError::RateLimited) => return Err(AppError::RateLimited),
            Err(AppError::NotFound(_)) => {
                return Err(AppError::NotFound(
                    "Qualtrics response export failed (HTTP 404).".into(),
                ));
            }
            Err(err) => last = err,
        }
    }
    Err(static_export(last))
}

async fn poll_export(client: &QualtricsClient, survey_id: &str, progress_id: &str) -> AppResult<String> {
    for _ in 0..90 {
        let body = client
            .get(&format!("surveys/{survey_id}/export-responses/{progress_id}"))
            .await
            .map_err(static_export)?;
        let result = body.get("result").cloned().unwrap_or(Value::Null);
        let status = result
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_ascii_lowercase();
        if status == "failed" {
            return Err(AppError::Api("Qualtrics response export failed.".into()));
        }
        let file_id = result.get("fileId").and_then(Value::as_str).unwrap_or("");
        let percent = result.get("percentComplete").and_then(Value::as_f64);
        let finished = status == "complete"
            || status == "success"
            || percent == Some(100.0);
        if !file_id.is_empty() && finished && matches!(status.as_str(), "complete" | "success" | "") {
            return Ok(file_id.to_string());
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
    Err(AppError::Api(
        "Qualtrics response export did not finish in time.".into(),
    ))
}

async fn download_responses(
    client: &QualtricsClient,
    survey_id: &str,
) -> AppResult<(Vec<ParsedResponse>, ExportMode)> {
    let (progress_id, mode) = start_export(client, survey_id).await?;
    let file_id = poll_export(client, survey_id, &progress_id).await?;
    let mut bytes = client
        .get_bytes(&format!(
            "surveys/{survey_id}/export-responses/{file_id}/file"
        ))
        .await
        .map_err(static_export)?;
    let parsed = parse_export_bytes(&mut bytes).map_err(|_| {
        AppError::Api("Qualtrics response export could not be read.".into())
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
) -> AppResult<AcquisitionReport> {
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

    let mut invitations = Vec::new();
    let primary = project.survey_id.trim();
    for survey in project.survey_rotation() {
        collect_invitations(client, project, &survey, primary, &mut invitations).await?;
    }

    let mut responses = Vec::new();
    let mut mode = ExportMode::Restricted;
    for survey in project.survey_rotation() {
        match download_responses(client, &survey.id).await {
            Ok((found, used)) => {
                responses.extend(found);
                mode = wider(mode, used);
            }
            Err(AppError::NotFound(_)) if survey.id != primary => continue,
            Err(err) => return Err(err),
        }
    }
    let mut report = aggregate(
        &participants,
        &invitations,
        &responses,
        now,
        &project.timezone,
        mode,
    );
    if mode != ExportMode::Restricted {
        report.limitations.push(
            "Qualtrics rejected a metadata-only export filter, so a broader file was read in memory and reduced to completion fields before counting. Survey answers were not kept, and names, email, IP, and location were not requested.".into(),
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
) -> AppResult<()> {
    let paths = [
        format!(
            "distributions?mailingListId={}&surveyId={}&distributionRequestType=Invite&useNewPaginationScheme=true",
            project.mailing_list_id, survey.id
        ),
        format!("distributions/sms?surveyId={}", survey.id),
    ];
    for path in paths {
        let elements = match client.get_elements(&path).await {
            Ok(elements) => elements,
            Err(AppError::NotFound(_)) if survey.id != primary => continue,
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
