use serde::{Deserialize, Serialize};
use tauri::{AppHandle, State};
use uuid::Uuid;

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
    /// When set, the profile joins this existing account instead of creating one. The
    /// file's account block is discarded, and the account's stored token is neither read
    /// nor written — importing a profile must not be able to break a working connection.
    #[serde(default)]
    pub target_account_id: Option<Uuid>,
}

/// Adds an imported profile to an account that already exists, leaving everything else
/// about that account alone.
///
/// Mirrors `config_cmds::save_project`'s find-then-push, including the replace-on-matching-id
/// case: a resubmitted preview carries the project id it was given at preview time, and a
/// blind push would leave a second copy that `iter().find()` can never reach.
fn add_project_to_account(
    cfg: &mut AppConfig,
    account_id: Uuid,
    project: Project,
) -> AppResult<()> {
    let target = cfg
        .accounts
        .iter_mut()
        .find(|a| a.id == account_id)
        .ok_or_else(|| AppError::NotFound("that account no longer exists".into()))?;
    match target.projects.iter_mut().find(|p| p.id == project.id) {
        Some(existing) => *existing = project,
        None => target.projects.push(project),
    }
    Ok(())
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
        target_account_id,
    } = request;

    // The wizard lets the time zone be edited before importing; without this the edit
    // would change only the scheduler's fallback and not what new participants are
    // stamped with.
    project.reconcile_embedded_defaults();

    // Deliberately ahead of everything below: joining an existing account must not read
    // the token file, touch the keychain, or drop that account's live client, none of
    // which have anything to do with adding a survey profile.
    if let Some(account_id) = target_account_id {
        return state
            .update_config(&app, |cfg| add_project_to_account(cfg, account_id, project))
            .await;
    }

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{EmailHeader, EmbeddedDefaults, DEFAULT_MINUTES_EXPIRE, DEFAULT_TIMEZONE};

    fn project(name: &str) -> Project {
        Project {
            id: Uuid::new_v4(),
            name: name.into(),
            survey_id: String::new(),
            message_id: String::new(),
            message_id_email: String::new(),
            mailing_list_id: String::new(),
            timezone: DEFAULT_TIMEZONE.into(),
            minutes_expire: DEFAULT_MINUTES_EXPIRE,
            email_header: EmailHeader::default(),
            embedded_defaults: EmbeddedDefaults::default(),
            survey_copies: Vec::new(),
            copies_source_survey_id: String::new(),
        }
    }

    fn config_with_one_account() -> (AppConfig, Uuid) {
        let account = Account {
            id: Uuid::new_v4(),
            name: "VA".into(),
            data_center: "gov1".into(),
            verify_tls: false,
            default_directory: "POOL_1".into(),
            library_id: "GR_1".into(),
            projects: vec![project("Already here")],
        };
        let id = account.id;
        (
            AppConfig {
                version: crate::config::CONFIG_VERSION,
                accounts: vec![account],
            },
            id,
        )
    }

    // The whole point of importing into an existing account: it gains a profile and
    // nothing else about it moves. Its token lives in the keychain and is never touched
    // on this path, which is why the command returns before the token handling.
    #[test]
    fn adding_a_profile_leaves_the_account_alone() {
        let (mut cfg, account_id) = config_with_one_account();

        add_project_to_account(&mut cfg, account_id, project("Imported")).unwrap();

        assert_eq!(cfg.accounts.len(), 1, "no second account");
        let account = &cfg.accounts[0];
        assert_eq!(account.name, "VA");
        assert_eq!(account.data_center, "gov1");
        assert_eq!(account.default_directory, "POOL_1");
        assert_eq!(account.library_id, "GR_1");
        assert!(!account.verify_tls, "the gov1 TLS setting must survive");
        let names: Vec<&str> = account.projects.iter().map(|p| p.name.as_str()).collect();
        assert_eq!(names, ["Already here", "Imported"]);
    }

    #[test]
    fn adding_to_an_unknown_account_is_not_found() {
        let (mut cfg, _) = config_with_one_account();
        let err = add_project_to_account(&mut cfg, Uuid::new_v4(), project("Imported")).unwrap_err();
        assert!(matches!(err, AppError::NotFound(_)));
    }

    // Pressing Import twice on one preview resubmits the same project id. A blind push
    // would leave a second copy that nothing can ever reach.
    #[test]
    fn re_importing_the_same_preview_replaces_rather_than_duplicates() {
        let (mut cfg, account_id) = config_with_one_account();
        let mut imported = project("Imported");

        add_project_to_account(&mut cfg, account_id, imported.clone()).unwrap();
        imported.name = "Imported, renamed".into();
        add_project_to_account(&mut cfg, account_id, imported).unwrap();

        assert_eq!(cfg.accounts[0].projects.len(), 2);
        assert_eq!(cfg.accounts[0].projects[1].name, "Imported, renamed");
    }

    // The wizard omits targetAccountId entirely when creating a new account.
    #[test]
    fn a_request_without_a_target_account_still_deserializes() {
        let json = r#"{
            "account": {
                "id": "0e6f9a1c-1f8e-4a3e-9f7a-2b3c4d5e6f70",
                "name": "VA",
                "dataCenter": "gov1",
                "defaultDirectory": "POOL_1",
                "libraryId": "GR_1"
            },
            "project": {
                "id": "0e6f9a1c-1f8e-4a3e-9f7a-2b3c4d5e6f71",
                "name": "Imported",
                "surveyId": "SV_1",
                "messageId": "MS_1",
                "mailingListId": "CG_1"
            }
        }"#;
        let request: ConfirmImport = serde_json::from_str(json).expect("should deserialize");
        assert!(request.target_account_id.is_none());
        assert!(request.token.is_none());
    }
}
