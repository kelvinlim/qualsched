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
    /// `browser_download_url` of the installer for this OS/arch, or empty when
    /// the release has no matching asset (the UI then opens `release_url`).
    pub download_url: String,
    /// Short button label when `download_url` is set, e.g. "Download QualSched
    /// 0.2.3 for Windows". Empty when there is no matching asset.
    pub download_label: String,
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

    let assets = parse_assets(&body);
    let (download_url, download_label) =
        match pick_installer_asset(&assets, std::env::consts::OS, std::env::consts::ARCH) {
            Some(asset) => (
                asset.browser_download_url.clone(),
                installer_label(&latest_version, std::env::consts::OS),
            ),
            None => (String::new(), String::new()),
        };

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
        download_url,
        download_label,
    })
}

struct ReleaseAsset {
    name: String,
    browser_download_url: String,
}

fn parse_assets(body: &Value) -> Vec<ReleaseAsset> {
    body.get("assets")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|a| {
            Some(ReleaseAsset {
                name: a.get("name")?.as_str()?.to_string(),
                browser_download_url: a.get("browser_download_url")?.as_str()?.to_string(),
            })
        })
        .collect()
}

/// Filename fragment we look for in a GitHub release asset name, lowercased.
/// Match the name, not the URL — every GitHub asset URL shares the same host.
fn installer_needle(os: &str, arch: &str) -> Option<&'static str> {
    match (os, arch) {
        // NSIS per-user setup, not the MSI (admin / per-machine).
        ("windows", "x86_64") => Some("x64-setup.exe"),
        ("macos", "aarch64") => Some("aarch64.dmg"),
        // Portable AppImage, not the .deb.
        ("linux", "x86_64") => Some("amd64.appimage"),
        _ => None,
    }
}

fn pick_installer_asset<'a>(
    assets: &'a [ReleaseAsset],
    os: &str,
    arch: &str,
) -> Option<&'a ReleaseAsset> {
    let needle = installer_needle(os, arch)?;
    assets
        .iter()
        .find(|a| a.name.to_ascii_lowercase().contains(needle))
}

fn installer_label(version: &str, os: &str) -> String {
    let platform = match os {
        "windows" => "Windows",
        "macos" => "macOS",
        "linux" => "Linux",
        _ => return String::new(),
    };
    format!("Download QualSched {version} for {platform}")
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
    use super::{installer_label, is_newer, pick_installer_asset, ReleaseAsset};

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
        // GitHub /releases/latest can lag the running app (failed installer
        // workflow). An older published tag must not advertise as an update.
        assert!(!is_newer("0.1.12", "0.2.0"));
    }

    #[test]
    fn equal_and_newer_against_0_2_0() {
        assert!(!is_newer("0.2.0", "0.2.0"));
        assert!(is_newer("0.2.1", "0.2.0"));
        assert!(is_newer("v0.3.0", "0.2.0"));
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

    /// Same filenames the release workflow attaches today. A fake download URL
    /// is enough: picking is by name, not host.
    fn pick_name(names: &[&str], os: &str, arch: &str) -> Option<String> {
        let assets: Vec<ReleaseAsset> = names
            .iter()
            .map(|n| ReleaseAsset {
                name: (*n).to_string(),
                browser_download_url: format!("https://example.test/{n}"),
            })
            .collect();
        pick_installer_asset(&assets, os, arch).map(|a| a.name.clone())
    }

    #[test]
    fn picks_installer_asset_for_os_arch() {
        let names = [
            "QualSched_0.2.3_aarch64.dmg",
            "QualSched_0.2.3_amd64.AppImage",
            "QualSched_0.2.3_amd64.deb",
            "QualSched_0.2.3_x64-setup.exe",
            "QualSched_0.2.3_x64_en-US.msi",
        ];
        let cases = [
            ("windows", "x86_64", Some("QualSched_0.2.3_x64-setup.exe")),
            ("macos", "aarch64", Some("QualSched_0.2.3_aarch64.dmg")),
            ("linux", "x86_64", Some("QualSched_0.2.3_amd64.AppImage")),
            // Intel Mac / Linux ARM: we do not publish those installers.
            ("macos", "x86_64", None),
            ("linux", "aarch64", None),
        ];
        for (os, arch, expected) in cases {
            assert_eq!(
                pick_name(&names, os, arch).as_deref(),
                expected,
                "os={os} arch={arch}"
            );
        }
    }

    #[test]
    fn no_matching_asset_returns_none() {
        assert_eq!(
            pick_name(&["README.md", "checksums.txt"], "linux", "x86_64"),
            None
        );
        assert_eq!(pick_name(&[], "windows", "x86_64"), None);
    }

    #[test]
    fn installer_label_names_the_platform() {
        assert_eq!(
            installer_label("0.2.3", "windows"),
            "Download QualSched 0.2.3 for Windows"
        );
        assert_eq!(
            installer_label("0.2.3", "macos"),
            "Download QualSched 0.2.3 for macOS"
        );
        assert_eq!(
            installer_label("0.2.3", "linux"),
            "Download QualSched 0.2.3 for Linux"
        );
        assert_eq!(installer_label("0.2.3", "freebsd"), "");
    }
}
