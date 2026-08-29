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

    // QualSched's own exports carry the sender fields the CLI hardcoded; a file from the
    // CLI has no such section and still starts from the defaults.
    let email_section = root.get("email_header");
    let mut email_header = EmailHeader::default();
    if email_section.is_some() {
        if let Some(v) = str_at(email_section, "FROM_EMAIL") {
            email_header.from_email = v;
        }
        if let Some(v) = str_at(email_section, "FROM_NAME") {
            email_header.from_name = v;
        }
        if let Some(v) = str_at(email_section, "REPLY_TO_EMAIL") {
            email_header.reply_to_email = v;
        }
        if let Some(v) = str_at(email_section, "SUBJECT") {
            email_header.subject = v;
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
        // A file this app wrote names the profile outright; a CLI file has only its
        // filename to go on.
        name: str_at(project_section, "NAME").unwrap_or_else(|| suggest_project_name(source_name)),
        survey_id: str_at(project_section, "SURVEY_ID").unwrap_or_default(),
        message_id: str_at(project_section, "MESSAGE_ID").unwrap_or_default(),
        message_id_email,
        mailing_list_id: str_at(project_section, "MAILING_LIST_ID").unwrap_or_default(),
        timezone,
        minutes_expire,
        email_header,
        embedded_defaults,
        // Copies are created on demand from the profile screen, never by an import.
        survey_copies: Vec::new(),
        copies_source_survey_id: String::new(),
    };

    if project.message_id_email.is_empty() {
        warnings.push(
            "No MESSAGE_ID_EMAIL in the file. Email invitations need their own template — \
             an SMS template will not render as an email."
                .into(),
        );
    }
    if email_section.is_none() {
        warnings.push(
            "Email sender details (from address, name, subject) were hardcoded in the CLI. \
             Review them in the project editor before sending email."
                .into(),
        );
    }

    Ok(Imported {
        account,
        project,
        warnings,
    })
}

/// The CLI's YAML dialect, written back out. Field order is the order it appears in the
/// file, and the rename attributes are the file's own key names.
///
/// Typed fields rather than a `Mapping` built from `as_pairs`, so numbers and booleans
/// serialize as themselves instead of as quoted strings.
#[derive(serde::Serialize)]
struct LegacyFile<'a> {
    account: LegacyAccount<'a>,
    project: LegacyProject<'a>,
    embedded_data: LegacyEmbedded<'a>,
    email_header: LegacyEmailHeader<'a>,
}

#[derive(serde::Serialize)]
struct LegacyAccount<'a> {
    #[serde(rename = "DATA_CENTER")]
    data_center: &'a str,
    #[serde(rename = "DEFAULT_DIRECTORY")]
    default_directory: &'a str,
    #[serde(rename = "LIBRARY_ID")]
    library_id: &'a str,
    #[serde(rename = "VERIFY")]
    verify: bool,
}

#[derive(serde::Serialize)]
struct LegacyProject<'a> {
    /// Not a CLI key. The old format named the study only by its filename, which a
    /// rename or a download folder loses; carrying it means a re-import restores it.
    #[serde(rename = "NAME")]
    name: &'a str,
    #[serde(rename = "SURVEY_ID")]
    survey_id: &'a str,
    #[serde(rename = "MESSAGE_ID")]
    message_id: &'a str,
    #[serde(rename = "MESSAGE_ID_EMAIL")]
    message_id_email: &'a str,
    #[serde(rename = "MAILING_LIST_ID")]
    mailing_list_id: &'a str,
    #[serde(rename = "TIMEZONE")]
    timezone: &'a str,
    // The correct spelling, never the CLI's MINUTES_EXP.
    #[serde(rename = "MINUTES_EXPIRE")]
    minutes_expire: u32,
}

#[derive(serde::Serialize)]
struct LegacyEmbedded<'a> {
    // These are Qualtrics' own embedded-data key names; `exports_the_canonical_embedded_keys`
    // holds them to what EmbeddedDefaults::as_pairs writes.
    #[serde(rename = "StartDate")]
    start_date: &'a str,
    #[serde(rename = "SurveysScheduled")]
    surveys_scheduled: i64,
    #[serde(rename = "TimeSlots")]
    time_slots: &'a str,
    // ContactMethod, not the pre-2024 UseSMS, so a re-import needs no derivation.
    #[serde(rename = "ContactMethod")]
    contact_method: &'a str,
    #[serde(rename = "DeleteUnsent")]
    delete_unsent: i64,
    #[serde(rename = "NumDays")]
    num_days: i64,
    #[serde(rename = "ExpireMinutes")]
    expire_minutes: i64,
    #[serde(rename = "LogData")]
    log_data: &'a str,
    #[serde(rename = "TimeZone")]
    time_zone: &'a str,
}

#[derive(serde::Serialize)]
struct LegacyEmailHeader<'a> {
    #[serde(rename = "FROM_EMAIL")]
    from_email: &'a str,
    #[serde(rename = "FROM_NAME")]
    from_name: &'a str,
    #[serde(rename = "REPLY_TO_EMAIL")]
    reply_to_email: &'a str,
    #[serde(rename = "SUBJECT")]
    subject: &'a str,
}

/// Writes a profile back out in the format `parse_config` reads.
///
/// The API token is deliberately absent: it lives in the OS credential store, and the
/// CLI kept it in a separate dotenv file for the same reason.
pub fn build_legacy_yaml(account: &Account, project: &Project) -> AppResult<String> {
    let e = &project.embedded_defaults;
    let file = LegacyFile {
        account: LegacyAccount {
            data_center: &account.data_center,
            default_directory: &account.default_directory,
            library_id: &account.library_id,
            verify: account.verify_tls,
        },
        project: LegacyProject {
            name: &project.name,
            survey_id: &project.survey_id,
            message_id: &project.message_id,
            message_id_email: &project.message_id_email,
            mailing_list_id: &project.mailing_list_id,
            timezone: &project.timezone,
            minutes_expire: project.minutes_expire,
        },
        embedded_data: LegacyEmbedded {
            start_date: &e.start_date,
            surveys_scheduled: e.surveys_scheduled,
            time_slots: &e.time_slots,
            contact_method: &e.contact_method,
            delete_unsent: e.delete_unsent,
            num_days: e.num_days,
            expire_minutes: e.expire_minutes,
            log_data: &e.log_data,
            time_zone: &e.time_zone,
        },
        email_header: LegacyEmailHeader {
            from_email: &project.email_header.from_email,
            from_name: &project.email_header.from_name,
            reply_to_email: &project.email_header.reply_to_email,
            subject: &project.email_header.subject,
        },
    };

    let yaml = serde_yaml::to_string(&file)
        .map_err(|e| AppError::Import(format!("could not write the config: {e}")))?;
    Ok(format!(
        "# Exported by QualSched. Readable by Import Config and by the qualtrics_util CLI.\n\
         # The API token is not in this file; it stays in the credential store of the\n\
         # computer it was entered on.\n{yaml}"
    ))
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

/// What is left of a config file's name once the path, the extension and the
/// `config_qualtrics` prefix every one of them shares are taken off.
fn config_stem(source_name: &str) -> &str {
    source_name
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or(source_name)
        .trim_end_matches(".yaml")
        .trim_end_matches(".yml")
        .trim_start_matches("config_qualtrics")
        .trim_start_matches(['_', '-'])
}

fn suggest_account_name(source_name: &str, data_center: &str) -> String {
    let stem = config_stem(source_name);
    match (stem.is_empty(), data_center.is_empty()) {
        (false, _) => stem.to_uppercase(),
        (true, false) => data_center.to_string(),
        (true, true) => "Imported account".into(),
    }
}

/// A profile name taken from the file it came from.
///
/// Several profiles can now live in one account, and a list of rows all reading
/// "Imported project" tells the user nothing about which study is which.
fn suggest_project_name(source_name: &str) -> String {
    let stem = config_stem(source_name);
    if stem.is_empty() {
        "Imported project".into()
    } else {
        stem.replace(['_', '-'], " ")
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

    // A profile added to an account that already has others has to be identifiable, and
    // the file name is the only thing the config carries that names the study.
    #[test]
    fn profile_name_comes_from_the_file() {
        let out = parse_config(VA, "config_qualtrics_ema_pilot.yaml").unwrap();
        assert_eq!(out.project.name, "ema pilot");
        // The account name still uppercases the same stem, separators and all.
        assert_eq!(out.account.name, "EMA_PILOT");
    }

    #[test]
    fn a_plain_config_name_falls_back_to_imported_project() {
        let out = parse_config(UMN, "config_qualtrics.yaml").unwrap();
        assert_eq!(out.project.name, "Imported project");
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

    fn exportable() -> (Account, Project) {
        let account = Account {
            id: Uuid::new_v4(),
            name: "VA".into(),
            data_center: "gov1".into(),
            verify_tls: false,
            default_directory: "POOL_9zzzzzzzzzzzzzz".into(),
            library_id: "UR_9zzzzzzzzzzzzzz".into(),
            projects: Vec::new(),
        };
        let project = Project {
            id: Uuid::new_v4(),
            name: "Sleep study".into(),
            survey_id: "SV_9zzzzzzzzzzzzzz".into(),
            message_id: "MS_sms".into(),
            message_id_email: "MS_email".into(),
            mailing_list_id: "CG_9zzzzzzzzzzzzzz".into(),
            timezone: "America/New_York".into(),
            minutes_expire: 45,
            email_header: EmailHeader {
                from_email: "study@umn.edu".into(),
                from_name: "Sleep Study".into(),
                reply_to_email: "reply@umn.edu".into(),
                subject: "Your evening survey".into(),
            },
            embedded_defaults: EmbeddedDefaults {
                start_date: "2026-03-16".into(),
                surveys_scheduled: 0,
                time_slots: "800,1200,2350".into(),
                contact_method: "email".into(),
                delete_unsent: 1,
                num_days: 14,
                expire_minutes: 45,
                log_data: r#"[{"action":"init"}]"#.into(),
                time_zone: "America/New_York".into(),
            },
            survey_copies: Vec::new(),
            copies_source_survey_id: String::new(),
        };
        (account, project)
    }

    // Export exists to move a study to another machine, so everything the profile holds
    // has to survive the trip out and back.
    #[test]
    fn export_round_trips_through_the_importer() {
        let (account, project) = exportable();
        let yaml = build_legacy_yaml(&account, &project).unwrap();
        // A name the file cannot have come from, to prove NAME is what is read.
        let out = parse_config(&yaml, "config_qualtrics_downloaded_2.yaml").unwrap();

        assert_eq!(out.account.data_center, "gov1");
        assert!(!out.account.verify_tls);
        assert_eq!(out.account.default_directory, "POOL_9zzzzzzzzzzzzzz");
        assert_eq!(out.account.library_id, "UR_9zzzzzzzzzzzzzz");

        assert_eq!(out.project.name, "Sleep study");
        assert_eq!(out.project.survey_id, "SV_9zzzzzzzzzzzzzz");
        assert_eq!(out.project.message_id, "MS_sms");
        assert_eq!(out.project.message_id_email, "MS_email");
        assert_eq!(out.project.mailing_list_id, "CG_9zzzzzzzzzzzzzz");
        assert_eq!(out.project.timezone, "America/New_York");
        assert_eq!(out.project.minutes_expire, 45);
        assert_eq!(out.project.email_header, project.email_header);
        assert_eq!(out.project.embedded_defaults, project.embedded_defaults);

        // Nothing was defaulted, so neither warning applies. (TLS is off in this
        // fixture, which warns for its own good reason.)
        assert!(!out.warnings.iter().any(|w| w.contains("sender")));
        assert!(!out.warnings.iter().any(|w| w.contains("MESSAGE_ID_EMAIL")));
    }

    // The token is the one thing the old format never carried and this one must not
    // either: exports get emailed around.
    #[test]
    fn the_export_never_contains_a_token() {
        let (account, project) = exportable();
        let yaml = build_legacy_yaml(&account, &project).unwrap().to_lowercase();
        assert!(!yaml.contains("apitoken"));
        assert!(!yaml.contains("api_token"));
        assert!(!yaml.contains("token:"));
    }

    // The exporter writes these key names by hand; as_pairs is what the app actually
    // sends to Qualtrics. If one moves without the other, an exported file quietly
    // loses a field on the way back in.
    #[test]
    fn exports_the_canonical_embedded_keys() {
        let (account, project) = exportable();
        let yaml = build_legacy_yaml(&account, &project).unwrap();
        let root: Value = serde_yaml::from_str(&yaml).unwrap();
        let written: Vec<String> = root
            .get("embedded_data")
            .and_then(Value::as_mapping)
            .expect("embedded_data section")
            .keys()
            .map(scalar_to_string)
            .collect();
        let canonical: Vec<String> = project
            .embedded_defaults
            .as_pairs()
            .into_iter()
            .map(|(k, _)| k)
            .collect();
        assert_eq!(written, canonical);
    }

    // A file from the CLI has no NAME and no email_header; it must behave as it always did.
    #[test]
    fn a_cli_file_still_falls_back_to_the_filename_and_warns() {
        let out = parse_config(UMN, "config_qualtrics_ema_pilot.yaml").unwrap();
        assert_eq!(out.project.name, "ema pilot");
        assert_eq!(out.project.email_header, EmailHeader::default());
        assert!(out.warnings.iter().any(|w| w.contains("sender")));
    }

    #[test]
    fn reads_token_from_dotenv_ignoring_comments() {
        let text = "QUALTRICS_APITOKEN=abc123\nDATACENTER=ca1\n#VERIFY=False\n";
        assert_eq!(parse_token_file(text).as_deref(), Some("abc123"));
        assert_eq!(parse_token_file("#QUALTRICS_APITOKEN=x\n"), None);
        assert_eq!(parse_token_file("QUALTRICS_APITOKEN=\n"), None);
    }
}
