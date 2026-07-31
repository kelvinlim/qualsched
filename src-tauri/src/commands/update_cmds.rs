use std::time::Duration;

use serde::Serialize;
use serde_json::Value;

use crate::error::{AppError, AppResult};

/// Where releases are published. The check is anonymous, so a fork that never
/// publishes releases just gets a 404 and the UI stays quiet.
const RELEASES_URL: &str = "https://api.github.com/repos/kelvinlim/qualsched/releases/latest";

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    pub current_version: String,
    pub latest_version: String,
    pub update_available: bool,
    /// The release body, markdown.
    pub release_notes: String,
    pub release_url: String,
}

#[tauri::command]
pub async fn check_for_update() -> AppResult<UpdateInfo> {
    // Not QualtricsClient: different host, no token, and a much shorter timeout —
    // a slow update check must not feel like the app hung at startup.
    let http = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()?;
    let resp = http
        .get(RELEASES_URL)
        // GitHub rejects requests without a User-Agent.
        .header("user-agent", "qualsched")
        .send()
        .await?;
    if !resp.status().is_success() {
        return Err(AppError::Api(format!(
            "release lookup failed (HTTP {})",
            resp.status().as_u16()
        )));
    }
    let body: Value = resp.json().await?;

    let tag = body
        .get("tag_name")
        .and_then(Value::as_str)
        .ok_or_else(|| AppError::Api("release lookup returned no tag_name".into()))?;
    let latest_version = tag.trim_start_matches('v').to_string();
    let current_version = env!("CARGO_PKG_VERSION").to_string();

    Ok(UpdateInfo {
        update_available: is_newer(&latest_version, &current_version),
        latest_version,
        current_version,
        release_notes: body
            .get("body")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        release_url: body
            .get("html_url")
            .and_then(Value::as_str)
            .unwrap_or("https://github.com/kelvinlim/qualsched/releases")
            .to_string(),
    })
}

/// Dotted-numeric version comparison. A segment that fails to parse makes the
/// candidate "not newer" — a malformed tag must never nag the user to upgrade.
fn is_newer(latest: &str, current: &str) -> bool {
    fn segments(v: &str) -> Option<Vec<u64>> {
        v.trim()
            .trim_start_matches('v')
            .split('.')
            .map(|s| s.parse::<u64>().ok())
            .collect()
    }
    match (segments(latest), segments(current)) {
        (Some(l), Some(c)) => {
            let len = l.len().max(c.len());
            for i in 0..len {
                let a = l.get(i).copied().unwrap_or(0);
                let b = c.get(i).copied().unwrap_or(0);
                if a != b {
                    return a > b;
                }
            }
            false
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::is_newer;

    #[test]
    fn equal_versions_are_not_newer() {
        assert!(!is_newer("0.1.8", "0.1.8"));
    }

    #[test]
    fn patch_minor_and_major_bumps_are_newer() {
        assert!(is_newer("0.1.9", "0.1.8"));
        assert!(is_newer("0.2.0", "0.1.9"));
        assert!(is_newer("1.0.0", "0.9.9"));
    }

    #[test]
    fn older_versions_are_not_newer() {
        assert!(!is_newer("0.1.7", "0.1.8"));
    }

    #[test]
    fn v_prefix_and_missing_segments_are_tolerated() {
        assert!(is_newer("v0.2", "0.1.8"));
        assert!(!is_newer("v0.1", "0.1.0"));
    }

    #[test]
    fn malformed_tags_never_report_an_update() {
        assert!(!is_newer("latest", "0.1.8"));
        assert!(!is_newer("0.1.9-beta", "0.1.8"));
        assert!(!is_newer("", "0.1.8"));
    }
}
