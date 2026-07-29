use serde::Serialize;
use tauri::{AppHandle, Emitter, State, Window};
use uuid::Uuid;

use crate::commands::resolve;
use crate::config::{AppConfig, SurveyCopy};
use crate::error::{AppError, AppResult};
use crate::qualtrics::{client::WRITE_PACING, surveys};
use crate::scheduler::parse_time_slots;
use crate::state::AppState;

pub const COPY_PROGRESS_EVENT: &str = "surveys://progress";

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct Progress {
    done: usize,
    total: usize,
    name: String,
    ok: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CopyReport {
    pub created: Vec<SurveyCopy>,
    /// At most one entry: the loop stops at the first failure so the c1..cN numbering
    /// never ends up with a hole in it.
    pub failed: Vec<CopyFailure>,
    /// The whole updated config, so the frontend replaces its copy the same way it does
    /// after any other config-mutating command.
    pub config: AppConfig,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CopyFailure {
    pub name: String,
    pub error: String,
}

/// Creates the survey copies a profile is missing, named `<original>-c1`, `-c2`, ...
///
/// Qualtrics delivers only the first invitation for a given survey to a given contact
/// each day, so a profile whose participants get N invitations a day needs N-1 copies to
/// send through. The count comes from the profile's own TimeSlots rather than the caller,
/// so the number that gets created always matches the number the scheduler will rotate
/// through. Existing copies are kept as-is; this only ever adds the missing ones.
#[tauri::command]
pub async fn create_survey_copies(
    app: AppHandle,
    window: Window,
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
) -> AppResult<CopyReport> {
    let project = {
        let cfg = state.config().await;
        resolve(&cfg, account_id, project_id)?.1.clone()
    };

    if project.survey_id.trim().is_empty() {
        return Err(AppError::Api(
            "this profile has no survey selected yet".into(),
        ));
    }

    let slots = parse_time_slots(&project.embedded_defaults.time_slots).map_err(AppError::Api)?;
    let needed = slots.len().saturating_sub(1);
    let existing = project.survey_copies.len();

    if existing >= needed {
        return Ok(CopyReport {
            created: Vec::new(),
            failed: Vec::new(),
            config: state.config().await,
        });
    }

    let client = state.client(account_id).await?;
    let original_name = surveys::get_survey_name(&client, &project.survey_id).await?;
    let owner_id = surveys::current_user_id(&client).await?;

    let total = needed - existing;
    let mut created: Vec<SurveyCopy> = Vec::new();
    let mut failed = Vec::new();

    for index in existing + 1..=needed {
        let name = format!("{original_name}-c{index}");
        match copy_and_activate(&client, &project.survey_id, &owner_id, &name).await {
            Ok(id) => created.push(SurveyCopy {
                id,
                name: name.clone(),
            }),
            Err(e) => {
                failed.push(CopyFailure {
                    name: name.clone(),
                    error: e.to_string(),
                });
                let _ = window.emit(
                    COPY_PROGRESS_EVENT,
                    Progress {
                        done: created.len(),
                        total,
                        name,
                        ok: false,
                    },
                );
                break;
            }
        }
        let _ = window.emit(
            COPY_PROGRESS_EVENT,
            Progress {
                done: created.len(),
                total,
                name,
                ok: true,
            },
        );
        tokio::time::sleep(WRITE_PACING).await;
    }

    // Whatever was created exists in Qualtrics whether or not a later copy failed, so it
    // is recorded either way; a re-run then creates only what is still missing.
    let source_survey_id = project.survey_id.clone();
    let to_store = created.clone();
    let config = state
        .update_config(&app, move |cfg| {
            let account = cfg
                .accounts
                .iter_mut()
                .find(|a| a.id == account_id)
                .ok_or_else(|| AppError::NotFound("that account no longer exists".into()))?;
            let project = account
                .projects
                .iter_mut()
                .find(|p| p.id == project_id)
                .ok_or_else(|| AppError::NotFound("that project no longer exists".into()))?;
            project.survey_copies.extend(to_store);
            project.copies_source_survey_id = source_survey_id;
            Ok(())
        })
        .await?;

    Ok(CopyReport {
        created,
        failed,
        config,
    })
}

/// A copy arrives inactive, and an invitation for an inactive survey produces a dead
/// link rather than an error, so activation is part of creating one.
async fn copy_and_activate(
    client: &crate::qualtrics::QualtricsClient,
    source_survey_id: &str,
    owner_id: &str,
    name: &str,
) -> AppResult<String> {
    let id = surveys::copy_survey(client, source_survey_id, owner_id, name).await?;
    tokio::time::sleep(WRITE_PACING).await;
    surveys::activate_survey(client, &id).await?;
    Ok(id)
}
