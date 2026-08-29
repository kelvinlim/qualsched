use std::collections::{BTreeMap, HashMap};

use chrono::Utc;
use serde::{Deserialize, Serialize};
use tauri::{Emitter, State, Window};
use uuid::Uuid;

use crate::commands::{contact_cmds::display_name, resolve};
use crate::config::Project;
use crate::error::AppResult;
use crate::qualtrics::{
    client::WRITE_PACING,
    contacts, distributions,
    models::{DistributionRow, Method, RawContact},
    QualtricsClient,
};
use crate::state::AppState;

pub const DELETE_PROGRESS_EVENT: &str = "distributions://progress";

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct Progress {
    done: usize,
    total: usize,
    ok: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DeleteReport {
    pub deleted: usize,
    pub failed: Vec<DeleteFailure>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DeleteFailure {
    pub id: String,
    pub error: String,
}

/// A row to cancel. The survey id travels with the id because a distribution created
/// against one of the project's survey copies cannot be cancelled with the project's own.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeleteTarget {
    pub id: String,
    pub survey_id: String,
}

/// Lists a project's distributions, resolving each recipient's CGC id back to a name so
/// the table is readable.
/// What the distribution table needs about a recipient, resolved once per contact.
///
/// One record rather than a map per field: every one of these is keyed by the same
/// contactLookupId and filled in the same pass.
struct Recipient {
    name: String,
    /// Each participant keeps their own TimeZone, so the local column has to be resolved
    /// per recipient rather than once for the table.
    zone: String,
    phone: String,
    email: String,
}

#[tauri::command]
pub async fn list_distributions(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    method: Method,
) -> AppResult<Vec<DistributionRow>> {
    let (account, project) = {
        let cfg = state.config().await;
        let (a, p) = resolve(&cfg, account_id, project_id)?;
        (a.clone(), p.clone())
    };
    let client = state.client(account_id).await?;
    let now = Utc::now();
    let mut rows = distributions::list_distributions(&client, &project, method, now).await?;

    let raw = contacts::list_contacts(
        &client,
        &account.default_directory,
        &project.mailing_list_id,
    )
    .await?;
    let mut recipients: HashMap<String, Recipient> = HashMap::new();
    for contact in &raw {
        if let Ok(lookup) = contacts::resolve_contact_lookup_id(
            &client,
            &account.default_directory,
            &project.mailing_list_id,
            contact,
        )
        .await
        {
            let zone = contact
                .embedded()
                .get("TimeZone")
                .map(|z| z.trim().to_string())
                .filter(|z| !z.is_empty())
                .unwrap_or_else(|| project.embedded_defaults.time_zone.clone());
            recipients.insert(
                lookup,
                Recipient {
                    name: display_name(contact),
                    zone,
                    phone: contact.str_field("phone").unwrap_or_default().to_string(),
                    email: contact.str_field("email").unwrap_or_default().to_string(),
                },
            );
        }
    }
    for row in &mut rows {
        if let Some(recipient) = recipients.get(&row.contact_lookup_id) {
            row.contact_name = recipient.name.clone();
            row.contact_phone = recipient.phone.clone();
            row.contact_email = recipient.email.clone();
            row.send_local =
                distributions::local_send_time(&row.send_date, &recipient.zone).unwrap_or_default();
        }
    }
    rows.sort_by(|a, b| a.send_date.cmp(&b.send_date));
    Ok(rows)
}

#[tauri::command]
pub async fn delete_distributions(
    window: Window,
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    method: Method,
    targets: Vec<DeleteTarget>,
) -> AppResult<DeleteReport> {
    // Resolving still validates the account/project pair before any deletes go out.
    {
        let cfg = state.config().await;
        resolve(&cfg, account_id, project_id)?;
    }
    let client = state.client(account_id).await?;

    let total = targets.len();
    let mut deleted = 0usize;
    let mut failed = Vec::new();

    for (index, target) in targets.iter().enumerate() {
        match distributions::delete_distribution(&client, &target.survey_id, method, &target.id)
            .await
        {
            Ok(()) => deleted += 1,
            Err(e) => failed.push(DeleteFailure {
                id: target.id.clone(),
                error: e.to_string(),
            }),
        }
        let _ = window.emit(
            DELETE_PROGRESS_EVENT,
            Progress {
                done: index + 1,
                total,
                ok: failed.is_empty(),
            },
        );
        tokio::time::sleep(WRITE_PACING).await;
    }

    Ok(DeleteReport { deleted, failed })
}

/// Cancels every not-yet-sent invitation booked for one contact.
///
/// Shared by the "cancel unsent" action and by contact removal, which must not leave
/// invitations booked for someone who is no longer in the study.
pub async fn cancel_pending_for_contact(
    client: &QualtricsClient,
    project: &Project,
    directory_id: &str,
    contact: &RawContact,
) -> AppResult<DeleteReport> {
    let embedded = contact.embedded();
    let method = if embedded
        .get("ContactMethod")
        .map(|m| m.eq_ignore_ascii_case("email"))
        .unwrap_or(false)
    {
        Method::Email
    } else {
        Method::Sms
    };

    let lookup_id = contacts::resolve_contact_lookup_id(
        client,
        directory_id,
        &project.mailing_list_id,
        contact,
    )
    .await?;

    let now = Utc::now();
    let rows = distributions::list_distributions(client, project, method, now).await?;
    let targets: Vec<&DistributionRow> = rows
        .iter()
        .filter(|r| r.contact_lookup_id == lookup_id && r.unsent)
        .collect();

    let mut deleted = 0usize;
    let mut failed = Vec::new();
    for row in targets {
        match distributions::delete_distribution(client, &row.survey_id, method, &row.id).await {
            Ok(()) => deleted += 1,
            Err(e) => failed.push(DeleteFailure {
                id: row.id.clone(),
                error: e.to_string(),
            }),
        }
        tokio::time::sleep(WRITE_PACING).await;
    }

    Ok(DeleteReport { deleted, failed })
}

/// Cancels every not-yet-sent invitation for one contact, then clears its DeleteUnsent
/// flag and resets SurveysScheduled so the contact can be re-scheduled cleanly.
#[tauri::command]
pub async fn delete_unsent_for_contact(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    contact_id: String,
) -> AppResult<DeleteReport> {
    let (account, project) = {
        let cfg = state.config().await;
        let (a, p) = resolve(&cfg, account_id, project_id)?;
        (a.clone(), p.clone())
    };
    let client = state.client(account_id).await?;

    let raw = contacts::list_contacts(
        &client,
        &account.default_directory,
        &project.mailing_list_id,
    )
    .await?;
    let contact = raw
        .iter()
        .find(|c| c.id() == Some(contact_id.as_str()))
        .ok_or_else(|| {
            crate::error::AppError::NotFound(format!("contact {contact_id} is not in this list"))
        })?;

    let DeleteReport { deleted, failed } =
        cancel_pending_for_contact(&client, &project, &account.default_directory, contact).await?;

    let mut updates = BTreeMap::new();
    updates.insert("DeleteUnsent".to_string(), "0".to_string());
    // Cancelled invitations are no longer scheduled; leaving the counter set would block
    // any future scheduling for this contact.
    if failed.is_empty() {
        updates.insert("SurveysScheduled".to_string(), "0".to_string());
    }
    contacts::update_contact(
        &client,
        &account.default_directory,
        &project.mailing_list_id,
        contact,
        &BTreeMap::new(),
        &[],
        &updates,
        Some(serde_json::json!({
            "action": "delete_unsent",
            "count": deleted,
            "ts": Utc::now().to_rfc3339(),
        })),
    )
    .await?;

    Ok(DeleteReport { deleted, failed })
}
