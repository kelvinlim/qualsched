pub mod config_cmds;
pub mod contact_cmds;
pub mod distribution_cmds;
pub mod export_cmds;
pub mod import_cmds;
pub mod lookup_cmds;
pub mod schedule_cmds;

use uuid::Uuid;

use crate::config::{Account, AppConfig, Project};
use crate::error::{AppError, AppResult};

/// Shared lookup so every command reports a missing account/project the same way.
pub fn resolve<'a>(
    cfg: &'a AppConfig,
    account_id: Uuid,
    project_id: Uuid,
) -> AppResult<(&'a Account, &'a Project)> {
    cfg.account_project(account_id, project_id)
        .ok_or_else(|| AppError::NotFound("that account or project no longer exists".into()))
}
