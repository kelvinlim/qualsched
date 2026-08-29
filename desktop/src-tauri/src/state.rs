use std::collections::HashMap;
use std::sync::Arc;

use tauri::AppHandle;
use tokio::sync::RwLock;
use uuid::Uuid;

use crate::config::{store, AppConfig};
use crate::error::AppResult;
use crate::keychain;
use crate::qualtrics::QualtricsClient;

pub struct AppState {
    config: RwLock<AppConfig>,
    /// One client per account, built on first use. Dropped when the account's token or
    /// connection settings change so the next call picks up the new values.
    clients: RwLock<HashMap<Uuid, Arc<QualtricsClient>>>,
}

impl AppState {
    pub fn new(config: AppConfig) -> Self {
        Self {
            config: RwLock::new(config),
            clients: RwLock::new(HashMap::new()),
        }
    }

    pub async fn config(&self) -> AppConfig {
        self.config.read().await.clone()
    }

    /// Mutates the config and persists it, returning the updated copy for the frontend.
    pub async fn update_config<F>(&self, app: &AppHandle, f: F) -> AppResult<AppConfig>
    where
        F: FnOnce(&mut AppConfig) -> AppResult<()>,
    {
        let mut guard = self.config.write().await;
        f(&mut guard)?;
        store::save(app, &guard)?;
        Ok(guard.clone())
    }

    pub async fn invalidate_client(&self, account_id: Uuid) {
        self.clients.write().await.remove(&account_id);
    }

    pub async fn client(&self, account_id: Uuid) -> AppResult<Arc<QualtricsClient>> {
        if let Some(c) = self.clients.read().await.get(&account_id) {
            return Ok(c.clone());
        }
        let account = {
            let cfg = self.config.read().await;
            cfg.account(account_id).cloned().ok_or_else(|| {
                crate::error::AppError::NotFound("that account no longer exists".into())
            })?
        };
        let token = keychain::require_token(account_id)?;
        let client = Arc::new(QualtricsClient::new(
            &account.data_center,
            &token,
            account.verify_tls,
        )?);
        self.clients
            .write()
            .await
            .insert(account_id, client.clone());
        Ok(client)
    }
}
