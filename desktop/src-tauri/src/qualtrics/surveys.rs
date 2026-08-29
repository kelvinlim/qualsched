use serde_json::Value;

use super::{client::QualtricsClient, models::IdName};
use crate::error::AppResult;

pub async fn list_surveys(client: &QualtricsClient) -> AppResult<Vec<IdName>> {
    let elements = client.get_elements("surveys").await?;
    Ok(elements
        .iter()
        .filter_map(|e| {
            Some(IdName {
                id: e.get("id").and_then(Value::as_str)?.to_string(),
                name: e
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("(unnamed)")
                    .to_string(),
            })
        })
        .collect())
}
