//! Reads the CLI's `config_qualtrics*.yaml` plus its dotenv token file and maps them
//! onto an Account + Project. Quirks in the old format are surfaced as warnings rather
//! than silently normalized, so the user can see what changed.

use serde_yaml::Value;
use uuid::Uuid;

use crate::config::{
    Account, EmailHeader, EmbeddedDefaults, Project, DEFAULT_MINUTES_EXPIRE, DEFAULT_TIMEZONE,
};
use crate::error::{AppError, AppResult};

#[derive(Debug)]
pub struct Imported {
    pub account: Account,
    pub project: Project,
    pub warnings: Vec<String>,
}

pub fn parse_config(yaml_text: &str, source_name: &str) -> AppResult<Imported> {
    let mut warnings = Vec::new();
    let root = parse_yaml_tolerating_duplicates(yaml_text, source_name, &mut warnings)?;

    let account_section = root.get("account");
    let project_section = root.get("project");
    if account_section.is_none() && project_section.is_none() {
        return Err(AppError::Import(format!(
            "{source_name} has neither an 'account' nor a 'project' section — is it a \
             qualtrics_util config?"
        )));
    }

    let data_center = str_at(account_section, "DATA_CENTER").unwrap_or_default();
    if data_center.is_empty() {
        warnings.push("No DATA_CENTER in the file; set it before connecting.".into());
    }
    let verify_tls = bool_at(account_section, "VERIFY").unwrap_or(true);
    if !verify_tls {
        warnings.push(
            "VERIFY was false, so TLS certificate checking is off for this account. That \
             matches the VA/gov1 setup, which sits behind TLS interception."
                .into(),
        );
    }

    // Configs write MINUTES_EXPIRE; the CLI read MINUTES_EXP and always missed. Accept
    // both so nothing is lost on import.
    let minutes_expire = int_at(project_section, "MINUTES_EXPIRE")
        .or_else(|| {
            int_at(project_section, "MINUTES_EXP").inspect(|_| {
                warnings.push(
                    "Found MINUTES_EXP (the CLI's misspelling); imported as MINUTES_EXPIRE."
                        .to_string(),
                )
            })
        })
        .unwrap_or(DEFAULT_MINUTES_EXPIRE as i64) as u32;

    let timezone = str_at(project_section, "TIMEZONE").unwrap_or_else(|| {
        warnings.push(format!(
            "No project TIMEZONE in the file; defaulted to {DEFAULT_TIMEZONE}."
        ));
        DEFAULT_TIMEZONE.to_string()
    });

    let message_id_email = str_at(project_section, "MESSAGE_ID_EMAIL").unwrap_or_default();

    let embedded = root.get("embedded_data");
    let embedded_defaults = parse_embedded(embedded, &timezone, minutes_expire, &mut warnings);

    if embedded.is_some() && str_at(embedded, "ContactMethod").is_none() {
        if let Some(use_sms) = int_at(embedded, "UseSMS") {
            warnings.push(format!(
                "No ContactMethod in embedded_data; derived '{}' from UseSMS = {use_sms}.",
                embedded_defaults.contact_method
            ));
        }
    }

    let account = Account {
        id: Uuid::new_v4(),
        name: suggest_account_name(source_name, &data_center),
        data_center,
        verify_tls,
        default_directory: str_at(account_section, "DEFAULT_DIRECTORY").unwrap_or_default(),
        library_id: str_at(account_section, "LIBRARY_ID").unwrap_or_default(),
        projects: Vec::new(),
    };

    let project = Project {
        id: Uuid::new_v4(),
        name: "Imported project".into(),
        survey_id: str_at(project_section, "SURVEY_ID").unwrap_or_default(),
        message_id: str_at(project_section, "MESSAGE_ID").unwrap_or_default(),
        message_id_email,
        mailing_list_id: str_at(project_section, "MAILING_LIST_ID").unwrap_or_default(),
        timezone,
        minutes_expire,
        // The CLI hardcoded these in send_email; they are settings now, so start from
        // the defaults and let the user correct them.
        email_header: EmailHeader::default(),
        embedded_defaults,
    };

    if project.message_id_email.is_empty() {
        warnings.push(
            "No MESSAGE_ID_EMAIL in the file. Email invitations need their own template — \
             an SMS template will not render as an email."
                .into(),
        );
    }
    warnings.push(
        "Email sender details (from address, name, subject) were hardcoded in the CLI. \
         Review them in the project editor before sending email."
            .into(),
    );

    Ok(Imported {
        account,
        project,
        warnings,
    })
}

fn parse_embedded(
    section: Option<&Value>,
    timezone: &str,
    minutes_expire: u32,
    warnings: &mut Vec<String>,
) -> EmbeddedDefaults {
    let mut d = EmbeddedDefaults {
        time_zone: timezone.to_string(),
        expire_minutes: minutes_expire as i64,
        ..Default::default()
    };
    // `node` for direct key access, `section` for the Option-taking helpers.
    let Some(node) = section else {
        return d;
    };

    if let Some(raw) = node.get("StartDate") {
        // YAML parses an unquoted 2024-03-16 as a date, which round-trips with quotes;
        // normalize either shape to a plain YYYY-MM-DD string.
        d.start_date = scalar_to_string(raw).trim_matches('\'').trim().to_string();
    }
    if let Some(v) = int_at(section, "SurveysScheduled") {
        d.surveys_scheduled = v;
    }
    if let Some(v) = node.get("TimeSlots") {
        d.time_slots = scalar_to_string(v);
        if let Err(e) = crate::scheduler::parse_time_slots(&d.time_slots) {
            warnings.push(format!("TimeSlots {:?} will not parse: {e}", d.time_slots));
        }
    }
    if let Some(v) = int_at(section, "DeleteUnsent") {
        d.delete_unsent = v;
    }
    if let Some(v) = int_at(section, "NumDays") {
        d.num_days = v;
    }
    if let Some(v) = int_at(section, "ExpireMinutes") {
        d.expire_minutes = v;
    }
    if let Some(v) = node.get("LogData") {
        d.log_data = scalar_to_string(v);
    }
    if let Some(v) = str_at(section, "TimeZone") {
        d.time_zone = v;
    }

    d.contact_method = match str_at(section, "ContactMethod") {
        Some(m) if m.eq_ignore_ascii_case("email") => "email".into(),
        Some(m) if m.eq_ignore_ascii_case("sms") => "sms".into(),
        Some(other) => {
            warnings.push(format!(
                "ContactMethod {other:?} is not 'sms' or 'email'; defaulted to sms."
            ));
            "sms".into()
        }
        // UseSMS is the pre-ContactMethod way of saying the same thing.
        None if int_at(section, "UseSMS") == Some(1) => "sms".into(),
        None => "sms".into(),
    };

    d
}

/// Parses the config, tolerating a key that appears twice in the same block.
///
/// Real configs contain these: a setting gets commented out, a replacement added, and
/// the original left live. Python's YAML loader silently kept the last one, so the CLI
/// ran happily; a strict parse would reject the file outright and block the import.
/// Keep the last value to match what the CLI actually used, and warn — landing on the
/// wrong mailing list is not something to discover after invitations go out.
fn parse_yaml_tolerating_duplicates(
    yaml_text: &str,
    source_name: &str,
    warnings: &mut Vec<String>,
) -> AppResult<Value> {
    match serde_yaml::from_str::<Value>(yaml_text) {
        Ok(v) => Ok(v),
        Err(e) if e.to_string().contains("duplicate entry") => {
            let (cleaned, dropped) = drop_duplicate_keys(yaml_text);
            let root: Value = serde_yaml::from_str(&cleaned).map_err(|e| {
                AppError::Import(format!("{source_name} is not valid YAML: {e}"))
            })?;
            for (key, kept) in dropped {
                warnings.push(format!(
                    "{key} is set more than once in this file. Used the last value \
                     ({kept}) — the same one the command-line tool used. Confirm it is \
                     the one you want."
                ));
            }
            Ok(root)
        }
        Err(e) => Err(AppError::Import(format!(
            "{source_name} is not valid YAML: {e}"
        ))),
    }
}

/// Removes all but the last occurrence of each `KEY:` within an indentation block.
/// Returns the cleaned text and the (key, kept value) pairs that were de-duplicated.
fn drop_duplicate_keys(yaml_text: &str) -> (String, Vec<(String, String)>) {
    // (indent, key) -> line indices, in order.
    let mut seen: Vec<((usize, String), Vec<usize>)> = Vec::new();
    let lines: Vec<&str> = yaml_text.lines().collect();

    for (i, line) in lines.iter().enumerate() {
        let trimmed = line.trim_start();
        if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with('-') {
            continue;
        }
        let Some((key, _)) = trimmed.split_once(':') else {
            continue;
        };
        let key = key.trim();
        if key.is_empty() || key.contains(' ') {
            continue;
        }
        let indent = line.len() - trimmed.len();
        let slot = (indent, key.to_string());
        match seen.iter_mut().find(|(k, _)| *k == slot) {
            Some((_, idxs)) => idxs.push(i),
            None => seen.push((slot, vec![i])),
        }
    }

    let mut drop: Vec<usize> = Vec::new();
    let mut report = Vec::new();
    for ((_, key), idxs) in seen {
        if idxs.len() < 2 {
            continue;
        }
        let last = *idxs.last().expect("non-empty");
        let kept = lines[last]
            .split_once(':')
            .map(|(_, v)| v.trim().to_string())
            .unwrap_or_default();
        report.push((key, kept));
        drop.extend(idxs.iter().copied().filter(|i| *i != last));
    }

    let cleaned = lines
        .iter()
        .enumerate()
        .filter(|(i, _)| !drop.contains(i))
        .map(|(_, l)| *l)
        .collect::<Vec<_>>()
        .join("\n");
    (cleaned, report)
}

/// Extracts `QUALTRICS_APITOKEN` from the CLI's dotenv-style token file.
pub fn parse_token_file(text: &str) -> Option<String> {
    text.lines()
        .map(str::trim)
        .filter(|l| !l.starts_with('#'))
        .filter_map(|l| l.split_once('='))
        .find(|(k, _)| k.trim() == "QUALTRICS_APITOKEN")
        .map(|(_, v)| v.trim().trim_matches(['"', '\'']).to_string())
        .filter(|t| !t.is_empty())
}

fn suggest_account_name(source_name: &str, data_center: &str) -> String {
    let stem = source_name
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or(source_name)
        .trim_end_matches(".yaml")
        .trim_end_matches(".yml")
        .trim_start_matches("config_qualtrics")
        .trim_start_matches(['_', '-']);
    match (stem.is_empty(), data_center.is_empty()) {
        (false, _) => stem.to_uppercase(),
        (true, false) => data_center.to_string(),
        (true, true) => "Imported account".into(),
    }
}

fn str_at(section: Option<&Value>, key: &str) -> Option<String> {
    let v = section?.get(key)?;
    let s = scalar_to_string(v);
    (!s.is_empty() && v != &Value::Null).then_some(s)
}

fn int_at(section: Option<&Value>, key: &str) -> Option<i64> {
    let v = section?.get(key)?;
    v.as_i64()
        .or_else(|| v.as_f64().map(|f| f as i64))
        .or_else(|| v.as_str().and_then(|s| s.trim().parse().ok()))
        .or_else(|| v.as_bool().map(|b| b as i64))
}

fn bool_at(section: Option<&Value>, key: &str) -> Option<bool> {
    let v = section?.get(key)?;
    v.as_bool()
        .or_else(|| match v.as_str()?.trim().to_ascii_lowercase().as_str() {
            "true" | "yes" | "1" => Some(true),
            "false" | "no" | "0" => Some(false),
            _ => None,
        })
}

fn scalar_to_string(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => b.to_string(),
        Value::Null => String::new(),
        other => serde_yaml::to_string(other)
            .unwrap_or_default()
            .trim()
            .to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const UMN: &str = r#"
account:
  DATA_CENTER: yul1
  DEFAULT_DIRECTORY: POOL_3fAZGWRVfLKuxe3
  LIBRARY_ID: GR_1234567890abcde
  VERIFY: True
project:
  SURVEY_ID: SV_abcdefghijklmno
  MESSAGE_ID: MS_abcdefghijklmno
  MAILING_LIST_ID: CG_abcdefghijklmno
  TIMEZONE: America/Chicago
  MINUTES_EXPIRE: 90
embedded_data:
  StartDate: '2024-03-16'
  SurveysScheduled: 0
  TimeSlots: 800,1200,1600,2000
  UseSMS: 1
  DeleteUnsent: 0
  NumDays: 0
  ExpireMinutes: 60
  LogData: '[{"action":"init"}]'
  TimeZone: America/Chicago
"#;

    // The VA deployment: gov1, TLS verification off, and no TIMEZONE/MINUTES_EXPIRE keys.
    const VA: &str = r#"
account:
  DATA_CENTER: gov1
  DEFAULT_DIRECTORY: POOL_9zzzzzzzzzzzzzz
  LIBRARY_ID: UR_9zzzzzzzzzzzzzz
  VERIFY: False
project:
  SURVEY_ID: SV_9zzzzzzzzzzzzzz
  MESSAGE_ID: MS_9zzzzzzzzzzzzzz
  MAILING_LIST_ID: CG_9zzzzzzzzzzzzzz
"#;

    #[test]
    fn maps_umn_config() {
        let out = parse_config(UMN, "config_qualtrics.yaml").unwrap();
        assert_eq!(out.account.data_center, "yul1");
        assert!(out.account.verify_tls);
        assert_eq!(out.account.library_id, "GR_1234567890abcde");
        assert_eq!(out.project.survey_id, "SV_abcdefghijklmno");
        assert_eq!(out.project.timezone, "America/Chicago");
        assert_eq!(out.project.minutes_expire, 90);
        assert_eq!(out.project.embedded_defaults.start_date, "2024-03-16");
        assert_eq!(
            out.project.embedded_defaults.time_slots,
            "800,1200,1600,2000"
        );
        // UseSMS: 1 with no ContactMethod means SMS.
        assert_eq!(out.project.embedded_defaults.contact_method, "sms");
    }

    #[test]
    fn va_config_disables_tls_verification_and_warns() {
        let out = parse_config(VA, "config_qualtrics_va.yaml").unwrap();
        assert_eq!(out.account.data_center, "gov1");
        assert!(!out.account.verify_tls);
        assert!(out.warnings.iter().any(|w| w.contains("TLS")));
        // Missing keys fall back rather than failing the import.
        assert_eq!(out.project.timezone, DEFAULT_TIMEZONE);
        assert_eq!(out.project.minutes_expire, DEFAULT_MINUTES_EXPIRE);
        assert_eq!(out.account.name, "VA");
    }

    #[test]
    fn accepts_the_cli_misspelling_of_minutes_expire() {
        let yaml = "account:\n  DATA_CENTER: yul1\nproject:\n  MINUTES_EXP: 45\n";
        let out = parse_config(yaml, "c.yaml").unwrap();
        assert_eq!(out.project.minutes_expire, 45);
        assert!(out.warnings.iter().any(|w| w.contains("MINUTES_EXP")));
    }

    #[test]
    fn warns_about_unparseable_time_slots() {
        let yaml = "account:\n  DATA_CENTER: yul1\nembedded_data:\n  TimeSlots: 2366\n";
        let out = parse_config(yaml, "c.yaml").unwrap();
        assert!(out.warnings.iter().any(|w| w.contains("will not parse")));
    }

    // config_ema_test.yaml really does set MAILING_LIST_ID twice.
    #[test]
    fn duplicate_key_keeps_the_last_value_and_warns() {
        let yaml = "account:\n  DATA_CENTER: yul1\nproject:\n  \
                    MAILING_LIST_ID: CG_first\n  SURVEY_ID: SV_x\n  \
                    MAILING_LIST_ID: CG_second\n";
        let out = parse_config(yaml, "config_ema_test.yaml").unwrap();
        assert_eq!(out.project.mailing_list_id, "CG_second");
        assert_eq!(out.project.survey_id, "SV_x");
        assert!(out
            .warnings
            .iter()
            .any(|w| w.contains("MAILING_LIST_ID") && w.contains("CG_second")));
    }

    #[test]
    fn rejects_a_file_that_is_not_a_qualtrics_config() {
        let err = parse_config("some: other\nthing: here\n", "notes.yaml").unwrap_err();
        assert!(err.to_string().contains("qualtrics_util config"));
    }

    #[test]
    fn reads_token_from_dotenv_ignoring_comments() {
        let text = "QUALTRICS_APITOKEN=abc123\nDATACENTER=ca1\n#VERIFY=False\n";
        assert_eq!(parse_token_file(text).as_deref(), Some("abc123"));
        assert_eq!(parse_token_file("#QUALTRICS_APITOKEN=x\n"), None);
        assert_eq!(parse_token_file("QUALTRICS_APITOKEN=\n"), None);
    }
}
