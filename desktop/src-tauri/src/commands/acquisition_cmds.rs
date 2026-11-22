use std::collections::BTreeMap;

use chrono::Utc;
use serde::Serialize;
use serde_json::json;
use tauri::State;
use uuid::Uuid;

use crate::acquisition::{self, load_report, AcquisitionReport};
use crate::commands::resolve;
use crate::error::{AppError, AppResult};
use crate::qualtrics::contacts;
use crate::state::AppState;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MonitorUpdate {
    pub contact_id: String,
    pub monitor: String,
}

/// Completed surveys versus invitations still listed. The result is aggregate
/// counts plus the display name already shown on Contacts. It is not stored.
#[tauri::command]
pub async fn get_acquisition(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
) -> AppResult<AcquisitionReport> {
    let (account, project) = {
        let cfg = state.config().await;
        let (account, project) = resolve(&cfg, account_id, project_id)?;
        (account.clone(), project.clone())
    };
    if account.default_directory.trim().is_empty() || project.mailing_list_id.trim().is_empty() {
        return Err(AppError::Invalid(
            "Set the contact directory and mailing list before loading acquisition.".into(),
        ));
    }
    if project.survey_id.trim().is_empty() {
        return Err(AppError::Invalid("this project has no survey selected".into()));
    }
    let client = state.client(account_id).await?;
    load_report(&client, &account, &project, Utc::now()).await
}

/// Manual active/inactive flag. Does not cancel invitations, delete responses,
/// or change whether the scheduler will send.
#[tauri::command]
pub async fn set_acquisition_status(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    contact_id: String,
    status: String,
) -> AppResult<MonitorUpdate> {
    let updates = acquisition::monitor_updates(&status)
        .map_err(|message| AppError::Invalid(message.into()))?;
    let monitor = updates
        .get(acquisition::MONITOR_FIELD)
        .cloned()
        .unwrap_or_else(|| "active".into());
    let (account, project) = {
        let cfg = state.config().await;
        let (account, project) = resolve(&cfg, account_id, project_id)?;
        (account.clone(), project.clone())
    };
    let client = state.client(account_id).await?;
    let raw = contacts::list_contacts(
        &client,
        &account.default_directory,
        &project.mailing_list_id,
    )
    .await?;
    let contact = raw
        .iter()
        .find(|item| item.id() == Some(contact_id.as_str()))
        .ok_or_else(|| AppError::NotFound(format!("contact {contact_id} is not in this list")))?;
    let before = contact.embedded().get("SurveysScheduled").cloned();
    let updated = contacts::update_contact(
        &client,
        &account.default_directory,
        &project.mailing_list_id,
        contact,
        &BTreeMap::new(),
        &[],
        &updates,
        Some(json!({"action": "qs_monitor", "value": monitor})),
    )
    .await?;
    let after = updated.embedded().get("SurveysScheduled").cloned();
    if before != after {
        return Err(AppError::Api(
            "Qualtrics changed SurveysScheduled while updating monitor status. No invitations were cancelled.".into(),
        ));
    }
    let stored = updated
        .embedded()
        .get(acquisition::MONITOR_FIELD)
        .cloned()
        .unwrap_or(monitor);
    Ok(MonitorUpdate {
        contact_id,
        monitor: acquisition::normalize_monitor(&stored).to_string(),
    })
}
