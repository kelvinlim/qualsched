use serde_json::Value;

use super::{
    client::QualtricsClient,
    models::{IdName, MailingListInfo},
};
use crate::error::{AppError, AppResult};

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

pub async fn list_mailing_lists_in(
    client: &QualtricsClient,
    directory_id: &str,
    directory_name: &str,
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
                directory_id: directory_id.to_string(),
                directory_name: directory_name.to_string(),
            })
        })
        .collect())
}

pub async fn list_mailing_lists(
    client: &QualtricsClient,
    directory_id: &str,
) -> AppResult<Vec<MailingListInfo>> {
    list_mailing_lists_in(client, directory_id, "").await
}

pub async fn list_mailing_lists_all(client: &QualtricsClient) -> AppResult<Vec<MailingListInfo>> {
    let dirs = list_directories(client).await?;
    let mut out = Vec::new();
    for dir in dirs {
        let did = dir.id.trim();
        if did.is_empty() {
            continue;
        }
        match list_mailing_lists_in(client, did, dir.name.trim()).await {
            Ok(items) => out.extend(items),
            Err(AppError::Unauthorized | AppError::NotFound(_)) => continue,
            Err(err) => return Err(err),
        }
    }
    Ok(out)
}
