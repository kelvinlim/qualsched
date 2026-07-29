use tauri::State;
use uuid::Uuid;

use crate::error::AppResult;
use crate::qualtrics::{
    directories,
    messages,
    models::{IdName, MailingListInfo, MessageInfo},
    surveys,
};
use crate::state::AppState;

#[tauri::command]
pub async fn list_surveys(state: State<'_, AppState>, account_id: Uuid) -> AppResult<Vec<IdName>> {
    let client = state.client(account_id).await?;
    surveys::list_surveys(&client).await
}

#[tauri::command]
pub async fn list_directories(
    state: State<'_, AppState>,
    account_id: Uuid,
) -> AppResult<Vec<IdName>> {
    let client = state.client(account_id).await?;
    directories::list_directories(&client).await
}

#[tauri::command]
pub async fn list_mailing_lists(
    state: State<'_, AppState>,
    account_id: Uuid,
    directory_id: String,
) -> AppResult<Vec<MailingListInfo>> {
    let client = state.client(account_id).await?;
    directories::list_mailing_lists(&client, &directory_id).await
}

#[tauri::command]
pub async fn list_messages(
    state: State<'_, AppState>,
    account_id: Uuid,
) -> AppResult<Vec<MessageInfo>> {
    let library_id = {
        let cfg = state.config().await;
        cfg.account(account_id)
            .map(|a| a.library_id.clone())
            .ok_or_else(|| {
                crate::error::AppError::NotFound("that account no longer exists".into())
            })?
    };
    if library_id.trim().is_empty() {
        return Err(crate::error::AppError::Invalid(
            "set the account's Library ID before loading messages".into(),
        ));
    }
    let client = state.client(account_id).await?;
    messages::list_messages(&client, &library_id).await
}

/// Powers the message preview in the project editor — the same text that gets sent.
#[tauri::command]
pub async fn get_message_text(
    state: State<'_, AppState>,
    account_id: Uuid,
    message_id: String,
) -> AppResult<String> {
    let library_id = {
        let cfg = state.config().await;
        cfg.account(account_id)
            .map(|a| a.library_id.clone())
            .ok_or_else(|| {
                crate::error::AppError::NotFound("that account no longer exists".into())
            })?
    };
    let client = state.client(account_id).await?;
    messages::get_message_text(&client, &library_id, &message_id).await
}
