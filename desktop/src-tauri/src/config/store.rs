use std::path::{Path, PathBuf};

use tauri::{AppHandle, Manager};

use super::{AppConfig, CONFIG_VERSION};
use crate::error::{AppError, AppResult};

pub fn config_path(app: &AppHandle) -> AppResult<PathBuf> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| AppError::Config(format!("cannot resolve config dir: {e}")))?;
    Ok(dir.join("config.json"))
}

pub fn load(app: &AppHandle) -> AppResult<AppConfig> {
    let path = config_path(app)?;
    if !path.exists() {
        return Ok(AppConfig::default());
    }
    let text = std::fs::read_to_string(&path)?;
    if text.trim().is_empty() {
        return Ok(AppConfig::default());
    }
    let mut cfg: AppConfig = serde_json::from_str(&text)
        .map_err(|e| AppError::Config(format!("{} is not valid config JSON: {e}", path.display())))?;
    if cfg.version > CONFIG_VERSION {
        return Err(AppError::Config(format!(
            "config.json was written by a newer version of QualSched (v{} > v{CONFIG_VERSION})",
            cfg.version
        )));
    }
    cfg.version = CONFIG_VERSION;
    Ok(cfg)
}

/// Write via temp file + rename so a crash mid-write cannot truncate the real config.
pub fn save(app: &AppHandle, cfg: &AppConfig) -> AppResult<()> {
    let path = config_path(app)?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let json = serde_json::to_string_pretty(cfg)?;
    write_atomic(&path, json.as_bytes())
}

fn write_atomic(path: &Path, bytes: &[u8]) -> AppResult<()> {
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, bytes)?;
    std::fs::rename(&tmp, path)?;
    Ok(())
}
