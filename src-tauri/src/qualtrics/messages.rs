use serde_json::Value;

use super::{client::QualtricsClient, models::MessageInfo};
use crate::error::{AppError, AppResult};

pub async fn list_messages(
    client: &QualtricsClient,
    library_id: &str,
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
            })
        })
        .collect())
}

/// Returns the English body of a library message.
///
/// The distribution payloads inline this text rather than referencing `messageId`:
/// Qualtrics refuses a second send with identical content on the same day, so each
/// invitation gets the body plus a fresh random suffix.
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
