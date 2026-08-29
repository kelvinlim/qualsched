use tauri::State;
use uuid::Uuid;

use crate::commands::resolve;
use crate::error::{AppError, AppResult};
use crate::import;
use crate::state::AppState;

/// Writes one survey profile out as a `config_qualtrics` YAML.
///
/// The path comes from the frontend's save dialog; the write happens here because no
/// filesystem plugin is enabled in the webview, the same split the import path uses.
#[tauri::command]
pub async fn export_project_config(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    path: String,
) -> AppResult<()> {
    let yaml = {
        let cfg = state.config().await;
        let (account, project) = resolve(&cfg, account_id, project_id)?;
        import::build_legacy_yaml(account, project)?
    };
    // The path is named in the error: a failed write is usually a permission or a
    // no-longer-existing folder, and neither is diagnosable without it.
    std::fs::write(&path, yaml)
        .map_err(|e| AppError::Import(format!("cannot write {path}: {e}")))?;
    Ok(())
}
