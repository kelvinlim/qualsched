use tauri::State;
use uuid::Uuid;

use crate::error::AppResult;
use crate::qualtrics::{
    directories,
    libraries,
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
pub async fn list_libraries(
    state: State<'_, AppState>,
    account_id: Uuid,
) -> AppResult<Vec<IdName>> {
    let client = state.client(account_id).await?;
    libraries::list_libraries(&client).await
}

#[tauri::command]
pub async fn list_mailing_lists(
    state: State<'_, AppState>,
    account_id: Uuid,
    directory_id: String,
) -> AppResult<Vec<MailingListInfo>> {
    let trimmed = directory_id.trim().to_string();
    if trimmed == "*" {
        let client = state.client(account_id).await?;
        return directories::list_mailing_lists_all(&client).await;
    }
    let resolved = if trimmed.is_empty() {
        let cfg = state.config().await;
        cfg.account(account_id)
            .map(|a| a.default_directory.trim().to_string())
            .ok_or_else(|| {
                crate::error::AppError::NotFound("that account no longer exists".into())
            })?
    } else {
        trimmed
    };
    if resolved.is_empty() {
        return Err(crate::error::AppError::Invalid(
            "set the account's Contact Directory before loading mailing lists".into(),
        ));
    }
    let client = state.client(account_id).await?;
    directories::list_mailing_lists(&client, &resolved).await
}

#[tauri::command]
pub async fn list_messages(
    state: State<'_, AppState>,
    account_id: Uuid,
    library_id: Option<String>,
) -> AppResult<Vec<MessageInfo>> {
    let requested = library_id.as_deref().map(str::trim).unwrap_or("").to_string();
    if requested == "*" {
        let client = state.client(account_id).await?;
        return messages::list_messages_all(&client).await;
    }
    let library_id = if !requested.is_empty() {
        requested
    } else {
        let cfg = state.config().await;
        cfg.account(account_id)
            .map(|a| a.library_id.trim().to_string())
            .ok_or_else(|| {
                crate::error::AppError::NotFound("that account no longer exists".into())
            })?
    };
    if library_id.is_empty() {
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
    library_id: Option<String>,
) -> AppResult<String> {
    let requested = library_id.as_deref().map(str::trim).unwrap_or("").to_string();
    let library_id = if !requested.is_empty() {
        requested
    } else {
        let cfg = state.config().await;
        cfg.account(account_id)
            .map(|a| a.library_id.trim().to_string())
            .ok_or_else(|| {
                crate::error::AppError::NotFound("that account no longer exists".into())
            })?
    };
    if library_id.is_empty() {
        return Err(crate::error::AppError::Invalid(
            "set a Library ID before previewing messages".into(),
        ));
    }
    let client = state.client(account_id).await?;
    messages::get_message_text(&client, &library_id, &message_id).await
}
