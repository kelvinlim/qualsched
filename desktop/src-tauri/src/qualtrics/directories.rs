use serde_json::Value;

use super::{
    client::QualtricsClient,
    models::{IdName, MailingListInfo},
};
use crate::error::AppResult;

pub async fn list_directories(client: &QualtricsClient) -> AppResult<Vec<IdName>> {
    let elements = client.get_elements("directories").await?;
    Ok(elements
        .iter()
        .filter_map(|e| {
            Some(IdName {
                id: e.get("directoryId").and_then(Value::as_str)?.to_string(),
                name: e
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("(unnamed)")
                    .to_string(),
            })
        })
        .collect())
}

pub async fn list_mailing_lists(
    client: &QualtricsClient,
    directory_id: &str,
) -> AppResult<Vec<MailingListInfo>> {
    let elements = client
        .get_elements(&format!(
            "directories/{directory_id}/mailinglists?includeCount=true"
        ))
        .await?;
    Ok(elements
        .iter()
        .filter_map(|e| {
            Some(MailingListInfo {
                id: e.get("mailingListId").and_then(Value::as_str)?.to_string(),
                name: e
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("(unnamed)")
                    .to_string(),
                contact_count: e.get("contactCount").and_then(Value::as_u64),
            })
        })
        .collect())
}
