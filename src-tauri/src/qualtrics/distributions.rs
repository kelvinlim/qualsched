use chrono::{DateTime, NaiveDateTime, Utc};
use chrono_tz::Tz;
use serde_json::{json, Value};

use super::{
    client::QualtricsClient,
    models::{DistributionRow, Method},
};
use crate::config::{EmailHeader, Project};
use crate::error::{AppError, AppResult};
use crate::scheduler::SurveyRef;

pub const QUALTRICS_TIME_FMT: &str = "%Y-%m-%dT%H:%M:%SZ";

pub fn fmt_time(t: DateTime<Utc>) -> String {
    t.format(QUALTRICS_TIME_FMT).to_string()
}

/// Renders a Qualtrics `sendDate` as wall-clock time in `timezone`.
///
/// Formatted like the Schedule screen's local column so the same invitation reads the
/// same before and after it is booked. Returns None rather than a guess when the date
/// or the zone cannot be parsed — a wrong local time is worse than none in a study that
/// spans timezones.
pub fn local_send_time(send_date: &str, timezone: &str) -> Option<String> {
    let tz: Tz = timezone.trim().parse().ok()?;
    let utc = parse_send_date(send_date)?;
    Some(
        utc.with_timezone(&tz)
            .format("%Y-%m-%d %H:%M %Z")
            .to_string(),
    )
}

/// Qualtrics sends the trailing-Z form; RFC 3339 is accepted as a fallback in case a
/// list response ever carries an offset instead.
fn parse_send_date(raw: &str) -> Option<DateTime<Utc>> {
    if let Ok(naive) = NaiveDateTime::parse_from_str(raw.trim(), QUALTRICS_TIME_FMT) {
        return Some(naive.and_utc());
    }
    DateTime::parse_from_rfc3339(raw.trim())
        .ok()
        .map(|t| t.with_timezone(&Utc))
}

pub struct SendRequest<'a> {
    pub project: &'a Project,
    /// Which survey this invitation points at. Always the project's own since 0.1.5;
    /// carried explicitly so the plan the user approved names it.
    pub survey_id: &'a str,
    pub contact_lookup_id: &'a str,
    pub message_text: &'a str,
    pub send_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
}

pub async fn send_sms(client: &QualtricsClient, req: &SendRequest<'_>) -> AppResult<String> {
    let body = json!({
        "sendDate": fmt_time(req.send_at),
        "surveyLinkExpirationDate": fmt_time(req.expires_at),
        "method": "Invite",
        "surveyId": req.survey_id,
        "name": "SMS message",
        "recipients": {
            "mailingListId": req.project.mailing_list_id,
            "contactId": req.contact_lookup_id,
        },
        "message": { "messageText": req.message_text },
    });
    let resp = client.post("distributions/sms", &body).await?;
    Ok(distribution_id(&resp))
}

pub async fn send_email(client: &QualtricsClient, req: &SendRequest<'_>) -> AppResult<String> {
    let EmailHeader {
        from_email,
        from_name,
        reply_to_email,
        subject,
    } = &req.project.email_header;

    let body = json!({
        "header": {
            "fromEmail": from_email,
            "fromName": from_name,
            "replyToEmail": reply_to_email,
            "subject": subject,
        },
        "surveyLink": {
            "surveyId": req.survey_id,
            "type": "Individual",
            "expirationDate": fmt_time(req.expires_at),
        },
        "sendDate": fmt_time(req.send_at),
        "recipients": {
            "mailingListId": req.project.mailing_list_id,
            "contactId": req.contact_lookup_id,
        },
        "message": { "messageText": req.message_text },
    });
    let resp = client.post("distributions", &body).await?;
    Ok(distribution_id(&resp))
}

fn distribution_id(resp: &Value) -> String {
    resp.pointer("/result/id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

/// Lists a project's distributions across its own survey and any clone 0.1.4 left behind,
/// so invitations already scheduled against a clone stay visible and cancellable.
/// `now` decides which rows count as still cancellable.
///
/// A clone the user has since deleted in Qualtrics 404s. That must not take the rest of the
/// table down with it — the whole screen would go empty, and contact deletion, which cancels
/// pending rows first, would start failing. Only a missing clone is tolerated: a missing
/// project survey is real news, and every other error kind (a bad token, a rate limit) still
/// propagates rather than showing a silently short list. Not unit-tested; it needs a live
/// client.
pub async fn list_distributions(
    client: &QualtricsClient,
    project: &Project,
    method: Method,
    now: DateTime<Utc>,
) -> AppResult<Vec<DistributionRow>> {
    let own_id = project.survey_id.trim();
    let mut rows = Vec::new();
    for survey in project.survey_rotation() {
        match list_for_survey(client, &project.mailing_list_id, &survey, method, now).await {
            Ok(found) => rows.extend(found),
            Err(AppError::NotFound(_)) if survey.id != own_id => continue,
            Err(e) => return Err(e),
        }
    }
    Ok(rows)
}

async fn list_for_survey(
    client: &QualtricsClient,
    mailing_list_id: &str,
    survey: &SurveyRef,
    method: Method,
    now: DateTime<Utc>,
) -> AppResult<Vec<DistributionRow>> {
    let path = match method {
        Method::Sms => format!("distributions/sms?surveyId={}", survey.id),
        Method::Email => format!(
            "distributions?mailingListId={}&surveyId={}&distributionRequestType=Invite&useNewPaginationScheme=true",
            mailing_list_id, survey.id
        ),
    };
    let elements = client.get_elements(&path).await?;
    let now_str = fmt_time(now);

    Ok(elements
        .iter()
        .filter_map(|e| {
            let send_date = e
                .get("sendDate")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            Some(DistributionRow {
                id: e.get("id").and_then(Value::as_str)?.to_string(),
                contact_lookup_id: e
                    .pointer("/recipients/contactId")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                contact_name: String::new(), // filled in by the command layer from the contact list
                send_local: String::new(),   // ditto: needs the recipient's timezone
                unsent: send_date > now_str,
                send_date,
                method,
                survey_id: survey.id.clone(),
                survey_label: survey.label.clone(),
            })
        })
        .collect())
}

/// `survey_id` must be the one the distribution was created against — a copy's row
/// cannot be cancelled with the project's own survey id.
pub async fn delete_distribution(
    client: &QualtricsClient,
    survey_id: &str,
    method: Method,
    distribution_id: &str,
) -> AppResult<()> {
    let path = match method {
        Method::Sms => format!("distributions/sms/{distribution_id}?surveyId={survey_id}"),
        Method::Email => format!("distributions/{distribution_id}"),
    };
    client.delete(&path).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renders_utc_in_the_recipients_zone() {
        // 13:30 UTC is 08:30 in Chicago during CDT.
        assert_eq!(
            local_send_time("2026-07-29T13:30:00Z", "America/Chicago").unwrap(),
            "2026-07-29 08:30 CDT"
        );
    }

    #[test]
    fn tracks_the_offset_in_effect_on_that_date() {
        // Same clock time in winter is CST, an hour further back.
        assert_eq!(
            local_send_time("2026-01-15T13:30:00Z", "America/Chicago").unwrap(),
            "2026-01-15 07:30 CST"
        );
    }

    #[test]
    fn crosses_the_date_line_where_the_zone_demands_it() {
        assert_eq!(
            local_send_time("2026-07-29T23:30:00Z", "Asia/Tokyo").unwrap(),
            "2026-07-30 08:30 JST"
        );
    }

    #[test]
    fn refuses_to_guess_on_bad_input() {
        assert!(local_send_time("2026-07-29T13:30:00Z", "Mars/Olympus").is_none());
        assert!(local_send_time("2026-07-29T13:30:00Z", "").is_none());
        assert!(local_send_time("not a date", "America/Chicago").is_none());
    }

    #[test]
    fn accepts_an_offset_form_too() {
        assert_eq!(
            local_send_time("2026-07-29T13:30:00+00:00", "America/Chicago").unwrap(),
            "2026-07-29 08:30 CDT"
        );
    }
}
