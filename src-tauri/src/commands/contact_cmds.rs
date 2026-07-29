use std::collections::BTreeMap;

use tauri::State;
use uuid::Uuid;

use crate::commands::resolve;
use crate::config::Project;
use crate::error::{AppError, AppResult};
use crate::qualtrics::{
    client::WRITE_PACING,
    contacts,
    models::{ContactView, RawContact},
};
use crate::scheduler::{contact_eligibility, delivery_method, Eligibility, EligibilityDefaults, Method};
use crate::state::AppState;

/// Projects a raw Qualtrics contact into the table row the UI renders, running the same
/// eligibility rules the scheduler will so the badge cannot disagree with the plan.
pub fn to_view(contact: &RawContact, project: &Project) -> ContactView {
    let embedded = contact.embedded();
    let defaults = EligibilityDefaults {
        timezone: &project.timezone,
        minutes_expire: project.minutes_expire,
    };
    let (eligible, skip_reason) = match contact_eligibility(&embedded, &defaults) {
        Eligibility::Eligible { .. } => (true, None),
        Eligibility::Skipped(reason) => (false, Some(reason)),
    };
    // Resolved separately from eligibility: a participant who has already been scheduled
    // is not eligible, but the UI still needs to show how they are contacted.
    let method = delivery_method(&embedded).ok().map(|m| {
        match m {
            Method::Sms => "sms",
            Method::Email => "email",
        }
        .to_string()
    });

    ContactView {
        contact_id: contact.id().unwrap_or_default().to_string(),
        first_name: contact.str_field("firstName").unwrap_or_default(),
        last_name: contact.str_field("lastName").unwrap_or_default(),
        email: contact.str_field("email").unwrap_or_default(),
        phone: contact.str_field("phone").unwrap_or_default(),
        ext_ref: contact.str_field("extRef").unwrap_or_default(),
        embedded,
        eligible,
        skip_reason,
        method,
    }
}

pub fn display_name(contact: &RawContact) -> String {
    let first = contact.str_field("firstName").unwrap_or_default();
    let last = contact.str_field("lastName").unwrap_or_default();
    let name = format!("{first} {last}").trim().to_string();
    if !name.is_empty() {
        return name;
    }
    contact
        .str_field("email")
        .or_else(|| contact.str_field("phone"))
        .unwrap_or_else(|| contact.id().unwrap_or("(unnamed)").to_string())
}

#[tauri::command]
pub async fn get_contacts(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
) -> AppResult<Vec<ContactView>> {
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
    Ok(raw.iter().map(|c| to_view(c, &project)).collect())
}

/// Adds a participant to the project's mailing list, seeded with the project's
/// scheduling defaults.
#[tauri::command]
pub async fn create_contact(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    core: BTreeMap<String, String>,
    embedded: BTreeMap<String, String>,
) -> AppResult<ContactView> {
    let (account, project) = {
        let cfg = state.config().await;
        let (a, p) = resolve(&cfg, account_id, project_id)?;
        (a.clone(), p.clone())
    };
    let client = state.client(account_id).await?;
    let created = contacts::create_contact(
        &client,
        &account.default_directory,
        &project.mailing_list_id,
        &core,
        &embedded,
        &project.embedded_defaults.as_pairs(),
    )
    .await?;
    Ok(to_view(&created, &project))
}

/// Edits a participant. `core` carries identity fields, `fields` carries embedded data;
/// either may be empty.
#[tauri::command]
pub async fn update_contact(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    contact_id: String,
    core: BTreeMap<String, String>,
    fields: BTreeMap<String, String>,
) -> AppResult<ContactView> {
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
        .ok_or_else(|| AppError::NotFound(format!("contact {contact_id} is not in this list")))?;

    let mut changed: Vec<&String> = core.keys().chain(fields.keys()).collect();
    changed.sort();

    let updated = contacts::update_contact(
        &client,
        &account.default_directory,
        &project.mailing_list_id,
        contact,
        &core,
        &[],
        &fields,
        Some(serde_json::json!({ "action": "edit", "fields": changed })),
    )
    .await?;
    Ok(to_view(&updated, &project))
}

#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemovedContact {
    pub contact_name: String,
    /// Pending invitations withdrawn before the participant was removed.
    pub cancelled: usize,
}

/// Removes a participant from the project's mailing list.
///
/// Their booked-but-unsent invitations are cancelled first. If any cancellation fails
/// the removal is abandoned, because a participant deleted while invitations remain
/// booked would still be messaged with nothing left in the app identifying them.
#[tauri::command]
pub async fn delete_contact(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    contact_id: String,
) -> AppResult<RemovedContact> {
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
        .ok_or_else(|| AppError::NotFound(format!("contact {contact_id} is not in this list")))?;
    let contact_name = display_name(contact);

    let report = crate::commands::distribution_cmds::cancel_pending_for_contact(
        &client,
        &project,
        &account.default_directory,
        contact,
    )
    .await?;

    if !report.failed.is_empty() {
        return Err(AppError::Api(format!(
            "{contact_name} still has {} invitation(s) that could not be cancelled ({}). \
             They were left in the mailing list so you can retry — removing them now would \
             leave those invitations booked with no way to trace them.",
            report.failed.len(),
            report.failed[0].error
        )));
    }

    contacts::remove_from_mailing_list(
        &client,
        &account.default_directory,
        &project.mailing_list_id,
        &contact_id,
    )
    .await?;

    Ok(RemovedContact {
        contact_name,
        cancelled: report.deleted,
    })
}

/// Writes the project's embedded defaults onto the selected contacts, filling in only
/// keys the contact does not already have. Existing per-participant values survive.
#[tauri::command]
pub async fn apply_embedded_defaults(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    contact_ids: Vec<String>,
) -> AppResult<Vec<ContactView>> {
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
    let seed = project.embedded_defaults.as_pairs();

    let mut out = Vec::new();
    for contact in raw
        .iter()
        .filter(|c| c.id().is_some_and(|id| contact_ids.iter().any(|w| w == id)))
    {
        let updated = contacts::update_contact(
            &client,
            &account.default_directory,
            &project.mailing_list_id,
            contact,
            &BTreeMap::new(),
            &seed,
            &BTreeMap::new(),
            Some(serde_json::json!({ "action": "init" })),
        )
        .await?;
        out.push(to_view(&updated, &project));
        tokio::time::sleep(WRITE_PACING).await;
    }
    Ok(out)
}
