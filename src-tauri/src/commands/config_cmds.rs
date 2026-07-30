use serde::Serialize;
use tauri::{AppHandle, State};
use uuid::Uuid;

use crate::config::{Account, AppConfig, Project};
use crate::error::{AppError, AppResult};
use crate::keychain;
use crate::qualtrics::directories;
use crate::state::AppState;

#[tauri::command]
pub async fn get_app_config(state: State<'_, AppState>) -> AppResult<AppConfig> {
    Ok(state.config().await)
}

#[tauri::command]
pub async fn save_account(
    app: AppHandle,
    state: State<'_, AppState>,
    account: Account,
) -> AppResult<AppConfig> {
    let id = account.id;
    let cfg = state
        .update_config(&app, |cfg| {
            match cfg.accounts.iter_mut().find(|a| a.id == id) {
                // Projects are edited through their own commands; don't let a stale
                // account form overwrite them.
                Some(existing) => {
                    let projects = std::mem::take(&mut existing.projects);
                    *existing = Account { projects, ..account };
                }
                None => cfg.accounts.push(account),
            }
            Ok(())
        })
        .await?;
    state.invalidate_client(id).await;
    Ok(cfg)
}

#[tauri::command]
pub async fn delete_account(
    app: AppHandle,
    state: State<'_, AppState>,
    account_id: Uuid,
) -> AppResult<AppConfig> {
    let cfg = state
        .update_config(&app, |cfg| {
            cfg.accounts.retain(|a| a.id != account_id);
            Ok(())
        })
        .await?;
    state.invalidate_client(account_id).await;
    // A leftover keychain entry would silently resurface if the id were ever reused.
    keychain::delete_token(account_id)?;
    Ok(cfg)
}

#[tauri::command]
pub async fn save_project(
    app: AppHandle,
    state: State<'_, AppState>,
    account_id: Uuid,
    mut project: Project,
) -> AppResult<AppConfig> {
    project.reconcile_embedded_defaults();
    state
        .update_config(&app, |cfg| {
            let account = cfg
                .accounts
                .iter_mut()
                .find(|a| a.id == account_id)
                .ok_or_else(|| AppError::NotFound("that account no longer exists".into()))?;
            match account.projects.iter_mut().find(|p| p.id == project.id) {
                // 0.1.4 recorded survey clones here. Nothing writes them any more, but the
                // profile form never carried them either, so a save must not erase the
                // records that keep those clones' pending invitations cancellable.
                Some(existing) => {
                    project.survey_copies = std::mem::take(&mut existing.survey_copies);
                    project.copies_source_survey_id =
                        std::mem::take(&mut existing.copies_source_survey_id);
                    *existing = project;
                }
                None => account.projects.push(project),
            }
            Ok(())
        })
        .await
}

/// Drops the record of the clones 0.1.4 made for this profile.
///
/// The surveys themselves stay in Qualtrics — this only stops QualSched checking them, which
/// costs an API call each every time the Distributions screen loads. Anything still pending
/// on a forgotten clone can no longer be cancelled from here, so the UI confirms first.
#[tauri::command]
pub async fn forget_survey_copies(
    app: AppHandle,
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
) -> AppResult<AppConfig> {
    state
        .update_config(&app, |cfg| {
            let project = cfg
                .accounts
                .iter_mut()
                .find(|a| a.id == account_id)
                .and_then(|a| a.projects.iter_mut().find(|p| p.id == project_id))
                .ok_or_else(|| {
                    AppError::NotFound("that account or project no longer exists".into())
                })?;
            project.survey_copies.clear();
            project.copies_source_survey_id.clear();
            Ok(())
        })
        .await
}

#[tauri::command]
pub async fn delete_project(
    app: AppHandle,
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
) -> AppResult<AppConfig> {
    state
        .update_config(&app, |cfg| {
            let account = cfg
                .accounts
                .iter_mut()
                .find(|a| a.id == account_id)
                .ok_or_else(|| AppError::NotFound("that account no longer exists".into()))?;
            account.projects.retain(|p| p.id != project_id);
            Ok(())
        })
        .await
}

#[tauri::command]
pub async fn set_account_token(
    state: State<'_, AppState>,
    account_id: Uuid,
    token: String,
) -> AppResult<()> {
    let token = token.trim();
    if token.is_empty() {
        return Err(AppError::Invalid("the API token is empty".into()));
    }
    keychain::set_token(account_id, token)?;
    state.invalidate_client(account_id).await;
    Ok(())
}

#[tauri::command]
pub async fn has_account_token(account_id: Uuid) -> AppResult<bool> {
    Ok(keychain::get_token(account_id)?.is_some())
}

#[tauri::command]
pub async fn clear_account_token(
    state: State<'_, AppState>,
    account_id: Uuid,
) -> AppResult<()> {
    keychain::delete_token(account_id)?;
    state.invalidate_client(account_id).await;
    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TestResult {
    pub ok: bool,
    pub message: String,
    pub directory_count: usize,
}

/// Confirms the token, data center and TLS setting all work together, and reports how
/// many directories are visible so the user can tell a valid-but-wrong account apart
/// from a broken one.
#[tauri::command]
pub async fn test_account(state: State<'_, AppState>, account_id: Uuid) -> AppResult<TestResult> {
    let client = state.client(account_id).await?;
    let dirs = directories::list_directories(&client).await?;
    Ok(TestResult {
        ok: true,
        message: format!("Connected. {} director{} visible.", dirs.len(), if dirs.len() == 1 { "y" } else { "ies" }),
        directory_count: dirs.len(),
    })
}
