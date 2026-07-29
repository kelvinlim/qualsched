pub mod store;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const CONFIG_VERSION: u32 = 1;
pub const DEFAULT_TIMEZONE: &str = crate::scheduler::DEFAULT_TIMEZONE;
pub const DEFAULT_MINUTES_EXPIRE: u32 = 60;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AppConfig {
    pub version: u32,
    #[serde(default)]
    pub accounts: Vec<Account>,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            version: CONFIG_VERSION,
            accounts: Vec::new(),
        }
    }
}

impl AppConfig {
    pub fn account(&self, id: Uuid) -> Option<&Account> {
        self.accounts.iter().find(|a| a.id == id)
    }

    /// Resolves an (account, project) pair in one step — nearly every command needs both.
    pub fn account_project(&self, account_id: Uuid, project_id: Uuid) -> Option<(&Account, &Project)> {
        let account = self.account(account_id)?;
        let project = account.projects.iter().find(|p| p.id == project_id)?;
        Some((account, project))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Account {
    pub id: Uuid,
    pub name: String,
    /// Qualtrics data center subdomain: yul1, ca1, gov1, iad1, ...
    pub data_center: String,
    /// gov1/VA sits behind TLS interception; that deployment needs this off.
    #[serde(default = "default_true")]
    pub verify_tls: bool,
    pub default_directory: String,
    pub library_id: String,
    #[serde(default)]
    pub projects: Vec<Project>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Project {
    pub id: Uuid,
    pub name: String,
    pub survey_id: String,
    /// Library message used for SMS invitations.
    pub message_id: String,
    /// Library message used for email invitations. An SMS template will not render as email.
    #[serde(default)]
    pub message_id_email: String,
    pub mailing_list_id: String,
    #[serde(default = "default_timezone")]
    pub timezone: String,
    #[serde(default = "default_minutes_expire")]
    pub minutes_expire: u32,
    #[serde(default)]
    pub email_header: EmailHeader,
    #[serde(default)]
    pub embedded_defaults: EmbeddedDefaults,
}

/// Was hardcoded in qualtrics_util.send_email; now per-project.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EmailHeader {
    pub from_email: String,
    pub from_name: String,
    pub reply_to_email: String,
    pub subject: String,
}

impl Default for EmailHeader {
    fn default() -> Self {
        Self {
            from_email: "noreply@qualtrics.com".into(),
            from_name: "Qualtrics".into(),
            reply_to_email: "noreply@qualtrics.com".into(),
            subject: "Survey".into(),
        }
    }
}

/// Seed values written onto a contact's embedded data when a field is absent.
/// Field names mirror the Qualtrics embedded-data keys exactly.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EmbeddedDefaults {
    pub start_date: String,
    pub surveys_scheduled: i64,
    pub time_slots: String,
    /// "sms" or "email"
    pub contact_method: String,
    pub delete_unsent: i64,
    pub num_days: i64,
    pub expire_minutes: i64,
    pub log_data: String,
    pub time_zone: String,
}

impl Default for EmbeddedDefaults {
    fn default() -> Self {
        Self {
            start_date: String::new(),
            surveys_scheduled: 0,
            time_slots: "800,1200,1600,2000".into(),
            contact_method: "sms".into(),
            delete_unsent: 0,
            num_days: 0,
            expire_minutes: DEFAULT_MINUTES_EXPIRE as i64,
            log_data: "[]".into(),
            time_zone: DEFAULT_TIMEZONE.into(),
        }
    }
}

impl EmbeddedDefaults {
    /// The embedded-data key/value pairs this default set contributes to a contact.
    pub fn as_pairs(&self) -> Vec<(String, String)> {
        vec![
            ("StartDate".into(), self.start_date.clone()),
            ("SurveysScheduled".into(), self.surveys_scheduled.to_string()),
            ("TimeSlots".into(), self.time_slots.clone()),
            ("ContactMethod".into(), self.contact_method.clone()),
            ("DeleteUnsent".into(), self.delete_unsent.to_string()),
            ("NumDays".into(), self.num_days.to_string()),
            ("ExpireMinutes".into(), self.expire_minutes.to_string()),
            ("LogData".into(), self.log_data.clone()),
            ("TimeZone".into(), self.time_zone.clone()),
        ]
    }
}

fn default_true() -> bool {
    true
}
fn default_timezone() -> String {
    DEFAULT_TIMEZONE.into()
}
fn default_minutes_expire() -> u32 {
    DEFAULT_MINUTES_EXPIRE
}
