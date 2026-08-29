use keyring::Entry;
use uuid::Uuid;

use crate::error::{AppError, AppResult};

const SERVICE: &str = "com.lnpi.qualsched";

fn entry(account_id: Uuid) -> AppResult<Entry> {
    Entry::new(SERVICE, &account_id.to_string()).map_err(|e| AppError::Keychain(e.to_string()))
}

pub fn get_token(account_id: Uuid) -> AppResult<Option<String>> {
    match entry(account_id)?.get_password() {
        Ok(t) => Ok(Some(t)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(AppError::Keychain(e.to_string())),
    }
}

pub fn set_token(account_id: Uuid, token: &str) -> AppResult<()> {
    entry(account_id)?
        .set_password(token)
        .map_err(|e| AppError::Keychain(e.to_string()))
}

/// Deleting a token that was never stored is a no-op, not an error.
pub fn delete_token(account_id: Uuid) -> AppResult<()> {
    match entry(account_id)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(AppError::Keychain(e.to_string())),
    }
}

pub fn require_token(account_id: Uuid) -> AppResult<String> {
    get_token(account_id)?.ok_or(AppError::MissingToken)
}
