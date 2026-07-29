use serde::{Deserialize, Serialize};
use tauri::{AppHandle, State};

use crate::config::{Account, AppConfig, Project};
use crate::error::{AppError, AppResult};
use crate::import;
use crate::keychain;
use crate::state::AppState;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportPreview {
    pub account: Account,
    pub project: Project,
    pub warnings: Vec<String>,
    /// Whether a token was found alongside the config, so the UI knows to prompt.
    pub token_found: bool,
}

#[tauri::command]
pub async fn preview_legacy_import(
    yaml_path: String,
    token_path: Option<String>,
) -> AppResult<ImportPreview> {
    let yaml_text = std::fs::read_to_string(&yaml_path)
        .map_err(|e| AppError::Import(format!("cannot read {yaml_path}: {e}")))?;
    let mut imported = import::parse_config(&yaml_text, &yaml_path)?;

    let mut token_found = false;
    if let Some(path) = token_path.as_deref().filter(|p| !p.trim().is_empty()) {
        let text = std::fs::read_to_string(path)
            .map_err(|e| AppError::Import(format!("cannot read {path}: {e}")))?;
        match import::parse_token_file(&text) {
            Some(_) => token_found = true,
            None => imported.warnings.push(format!(
                "{path} has no QUALTRICS_APITOKEN line; enter the token by hand."
            )),
        }
    }

    Ok(ImportPreview {
        account: imported.account,
        project: imported.project,
        warnings: imported.warnings,
        token_found,
    })
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConfirmImport {
    pub account: Account,
    pub project: Project,
    /// Token typed by the user, if any.
    pub token: Option<String>,
    /// Token file to read the token from instead.
    pub token_path: Option<String>,
}

#[tauri::command]
pub async fn confirm_legacy_import(
    app: AppHandle,
    state: State<'_, AppState>,
    request: ConfirmImport,
) -> AppResult<AppConfig> {
    let ConfirmImport {
        mut account,
        mut project,
        token,
        token_path,
    } = request;

    // The wizard lets the time zone be edited before importing; without this the edit
    // would change only the scheduler's fallback and not what new participants are
    // stamped with.
    project.reconcile_embedded_defaults();

    let token = match token.filter(|t| !t.trim().is_empty()) {
        Some(t) => Some(t),
        None => match token_path.as_deref().filter(|p| !p.trim().is_empty()) {
            Some(path) => {
                let text = std::fs::read_to_string(path)
                    .map_err(|e| AppError::Import(format!("cannot read {path}: {e}")))?;
                import::parse_token_file(&text)
            }
            None => None,
        },
    };

    // Store the token first: an account saved without one looks connected but is not.
    if let Some(token) = token {
        keychain::set_token(account.id, token.trim())?;
    }

    account.projects = vec![project];
    let account_id = account.id;
    let cfg = state
        .update_config(&app, |cfg| {
            cfg.accounts.push(account);
            Ok(())
        })
        .await?;
    state.invalidate_client(account_id).await;
    Ok(cfg)
}
