use serde_json::Value;

use super::{client::QualtricsClient, models::IdName};
use crate::error::AppResult;

/// GET /API/v3/libraries — paginated `result.elements` with `libraryId`/`libraryName`.
pub async fn list_libraries(client: &QualtricsClient) -> AppResult<Vec<IdName>> {
    let elements = client.get_elements("libraries").await?;
    Ok(elements
        .iter()
        .filter_map(|e| {
            Some(IdName {
                id: e
                    .get("libraryId")
                    .or_else(|| e.get("id"))
                    .and_then(Value::as_str)?
                    .to_string(),
                name: e
                    .get("libraryName")
                    .or_else(|| e.get("name"))
                    .and_then(Value::as_str)
                    .unwrap_or("(unnamed)")
                    .to_string(),
            })
        })
        .collect())
}
