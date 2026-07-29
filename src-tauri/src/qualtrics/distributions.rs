use chrono::{DateTime, Utc};
use serde_json::{json, Value};

use super::{
    client::QualtricsClient,
    models::{DistributionRow, Method},
};
use crate::config::{EmailHeader, Project};
use crate::error::AppResult;

pub const QUALTRICS_TIME_FMT: &str = "%Y-%m-%dT%H:%M:%SZ";

pub fn fmt_time(t: DateTime<Utc>) -> String {
    t.format(QUALTRICS_TIME_FMT).to_string()
}

pub struct SendRequest<'a> {
    pub project: &'a Project,
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
        "surveyId": req.project.survey_id,
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
            "surveyId": req.project.survey_id,
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

/// Lists distributions for a project. `now` decides which rows count as still cancellable.
pub async fn list_distributions(
    client: &QualtricsClient,
    project: &Project,
    method: Method,
    now: DateTime<Utc>,
) -> AppResult<Vec<DistributionRow>> {
    let path = match method {
        Method::Sms => format!("distributions/sms?surveyId={}", project.survey_id),
        Method::Email => format!(
            "distributions?mailingListId={}&surveyId={}&distributionRequestType=Invite&useNewPaginationScheme=true",
            project.mailing_list_id, project.survey_id
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
                unsent: send_date > now_str,
                send_date,
                method,
            })
        })
        .collect())
}

pub async fn delete_distribution(
    client: &QualtricsClient,
    project: &Project,
    method: Method,
    distribution_id: &str,
) -> AppResult<()> {
    let path = match method {
        Method::Sms => format!(
            "distributions/sms/{distribution_id}?surveyId={}",
            project.survey_id
        ),
        Method::Email => format!("distributions/{distribution_id}"),
    };
    client.delete(&path).await?;
    Ok(())
}
