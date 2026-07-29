use serde_json::{json, Value};

use super::{client::QualtricsClient, models::IdName};
use crate::error::{AppError, AppResult};

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

/// Name of one survey. Copy names are derived from the live Qualtrics title rather than
/// the profile name, so `-c1` always reads as a sibling of what it was copied from.
pub async fn get_survey_name(client: &QualtricsClient, survey_id: &str) -> AppResult<String> {
    let resp = client.get(&format!("surveys/{survey_id}")).await?;
    resp.pointer("/result/name")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| AppError::Api(format!("survey {survey_id} returned no name")))
}

/// The user the API token belongs to. Copying a survey has to name an owner for the
/// copy, and it is always whoever is making the call.
pub async fn current_user_id(client: &QualtricsClient) -> AppResult<String> {
    let resp = client.get("whoami").await?;
    resp.pointer("/result/userId")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| AppError::Api("could not read the API token's user id".into()))
}

/// Copies `source_survey_id` into a new survey called `project_name`, returning its id.
///
/// Both the source and the owner of the copy travel as headers; the body carries only
/// the new name. Omitting the owner header fails with "Missing X-COPY-DESTINATION-OWNER"
/// rather than defaulting to the caller.
pub async fn copy_survey(
    client: &QualtricsClient,
    source_survey_id: &str,
    owner_id: &str,
    project_name: &str,
) -> AppResult<String> {
    let body = json!({ "projectName": project_name });
    let resp = client
        .post_with_headers(
            "surveys",
            &[
                ("X-COPY-SOURCE", source_survey_id),
                ("X-COPY-DESTINATION-OWNER", owner_id),
            ],
            &body,
        )
        .await?;
    resp.pointer("/result/id")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| AppError::Api("copying the survey returned no new survey id".into()))
}

/// Turns a survey on. Copies arrive inactive, and a distribution for an inactive survey
/// is accepted but yields a dead link.
pub async fn activate_survey(client: &QualtricsClient, survey_id: &str) -> AppResult<()> {
    client
        .put(&format!("surveys/{survey_id}"), &json!({ "isActive": true }))
        .await?;
    Ok(())
}
