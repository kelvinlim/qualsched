use serde_json::Value;

use super::{client::QualtricsClient, libraries, models::MessageInfo};
use crate::error::{AppError, AppResult};

pub async fn list_messages_in(
    client: &QualtricsClient,
    library_id: &str,
    library_name: &str,
) -> AppResult<Vec<MessageInfo>> {
    let elements = client
        .get_elements(&format!("libraries/{library_id}/messages"))
        .await?;
    Ok(elements
        .iter()
        .filter_map(|e| {
            Some(MessageInfo {
                id: e.get("id").and_then(Value::as_str)?.to_string(),
                description: e
                    .get("description")
                    .and_then(Value::as_str)
                    .unwrap_or("(no description)")
                    .to_string(),
                category: e
                    .get("category")
                    .and_then(Value::as_str)
                    .map(str::to_string),
                library_id: library_id.to_string(),
                library_name: library_name.to_string(),
            })
        })
        .collect())
}

pub async fn list_messages(
    client: &QualtricsClient,
    library_id: &str,
) -> AppResult<Vec<MessageInfo>> {
    list_messages_in(client, library_id, "").await
}

pub async fn list_messages_all(client: &QualtricsClient) -> AppResult<Vec<MessageInfo>> {
    let libs = libraries::list_libraries(client).await?;
    let mut out = Vec::new();
    for lib in libs {
        let lid = lib.id.trim();
        if lid.is_empty() {
            continue;
        }
        match list_messages_in(client, lid, lib.name.trim()).await {
            Ok(items) => out.extend(items),
            Err(AppError::Unauthorized | AppError::NotFound(_)) => continue,
            Err(err) => return Err(err),
        }
    }
    Ok(out)
}

/// Returns the English body of a library message.
///
/// The distribution payloads inline this text rather than referencing `messageId`:
/// Qualtrics refuses a second send with identical content on the same day, so each
/// invitation gets a unique tag (before the survey-link piped text for SMS).
pub async fn get_message_text(
    client: &QualtricsClient,
    library_id: &str,
    message_id: &str,
) -> AppResult<String> {
    let body = client
        .get(&format!("libraries/{library_id}/messages/{message_id}"))
        .await?;
    body.pointer("/result/messages/en")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| {
            AppError::NotFound(format!(
                "message {message_id} in library {library_id} has no 'en' text"
            ))
        })
}
