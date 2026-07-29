use std::collections::{BTreeMap, HashMap};

use chrono::Utc;
use serde::{Deserialize, Serialize};
use tauri::{Emitter, State, Window};
use uuid::Uuid;

use rand::{rngs::StdRng, SeedableRng};

use crate::commands::{contact_cmds::display_name, resolve};
use crate::error::{AppError, AppResult};
use crate::qualtrics::{
    client::WRITE_PACING,
    contacts,
    distributions::{self, SendRequest},
    messages,
    models::RawContact,
    QualtricsClient,
};
use crate::scheduler::{
    build_contact_plan, contact_eligibility, decorate_message, Eligibility, EligibilityDefaults,
    Method, PlanInputs, PlanItem, Skipped,
};
use crate::state::AppState;

pub const PROGRESS_EVENT: &str = "schedule://progress";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SchedulePreview {
    pub items: Vec<PlanItem>,
    /// Contacts that will get nothing, and why.
    pub skipped_contacts: Vec<Skipped>,
    /// Individual slots dropped from otherwise-eligible contacts (usually already past).
    pub skipped_slots: Vec<Skipped>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct Progress {
    done: usize,
    total: usize,
    contact_name: String,
    ok: bool,
    error: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ItemFailure {
    pub contact_name: String,
    pub destination: String,
    pub send_local: String,
    pub error: String,
    pub retryable: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SendReport {
    pub scheduled: usize,
    pub failed: Vec<ItemFailure>,
    /// Contacts whose distributions went out but whose SurveysScheduled write-back failed.
    /// These need attention: a re-run would double-schedule them.
    pub bookkeeping_failures: Vec<ItemFailure>,
}

/// Computes exactly what would be sent, without sending anything.
///
/// Random time windows are resolved here, so the preview the user approves is the plan
/// that executes — not a fresh draw with different times.
#[tauri::command]
pub async fn preview_schedule(
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
) -> AppResult<SchedulePreview> {
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

    let now = Utc::now();
    let mut rng = StdRng::from_entropy();
    let mut items = Vec::new();
    let mut skipped_contacts = Vec::new();
    let mut skipped_slots = Vec::new();

    for contact in &raw {
        let name = display_name(contact);
        let contact_id = contact.id().unwrap_or_default().to_string();
        let embedded = contact.embedded();
        let defaults = EligibilityDefaults {
            timezone: &project.timezone,
            minutes_expire: project.minutes_expire,
        };

        match contact_eligibility(&embedded, &defaults) {
            Eligibility::Skipped(reason) => skipped_contacts.push(Skipped {
                contact_id,
                contact_name: name,
                reason,
            }),
            Eligibility::Eligible {
                method,
                slots,
                num_days,
                start_date,
                timezone,
                expire_minutes,
            } => {
                let destination = match method {
                    Method::Sms => contact.str_field("phone").unwrap_or_default(),
                    Method::Email => contact.str_field("email").unwrap_or_default(),
                };
                if destination.is_empty() {
                    skipped_contacts.push(Skipped {
                        contact_id,
                        contact_name: name,
                        reason: format!(
                            "no {} on record",
                            if method == Method::Sms { "phone number" } else { "email address" }
                        ),
                    });
                    continue;
                }

                let input = PlanInputs {
                    contact_id: &contact_id,
                    contact_name: &name,
                    destination: &destination,
                    method,
                    slots: &slots,
                    num_days,
                    start_date: &start_date,
                    timezone: &timezone,
                    expire_minutes,
                };
                let (mut plan, dropped) = build_contact_plan(&input, now, &mut rng);
                if plan.is_empty() && !dropped.is_empty() {
                    // Every slot fell away — report it as a skipped contact so it does
                    // not vanish from the summary entirely.
                    skipped_contacts.push(Skipped {
                        contact_id,
                        contact_name: name,
                        reason: format!(
                            "all {} slots dropped ({})",
                            dropped.len(),
                            dropped[0].reason
                        ),
                    });
                    continue;
                }
                items.append(&mut plan);
                skipped_slots.extend(dropped);
            }
        }
    }

    items.sort_by_key(|i| i.send_utc);
    Ok(SchedulePreview {
        items,
        skipped_contacts,
        skipped_slots,
    })
}

/// Sends the approved plan.
///
/// One failed POST no longer stops the run — the CLI called sys.exit here, leaving a
/// participant half-scheduled with no record of how far it got. Failures are collected
/// and reported; every remaining item still goes out.
#[tauri::command]
pub async fn execute_schedule(
    window: Window,
    state: State<'_, AppState>,
    account_id: Uuid,
    project_id: Uuid,
    plan: SchedulePreview,
) -> AppResult<SendReport> {
    let (account, project) = {
        let cfg = state.config().await;
        let (a, p) = resolve(&cfg, account_id, project_id)?;
        (a.clone(), p.clone())
    };
    if project.message_id.trim().is_empty() {
        return Err(AppError::Invalid(
            "this project has no SMS message selected".into(),
        ));
    }
    let client = state.client(account_id).await?;

    let raw = contacts::list_contacts(
        &client,
        &account.default_directory,
        &project.mailing_list_id,
    )
    .await?;
    let by_id: HashMap<&str, &RawContact> = raw
        .iter()
        .filter_map(|c| c.id().map(|id| (id, c)))
        .collect();

    let total = plan.items.len();
    let mut done = 0usize;
    let mut failed: Vec<ItemFailure> = Vec::new();
    let mut bookkeeping_failures: Vec<ItemFailure> = Vec::new();
    let mut lookup_cache: HashMap<String, String> = HashMap::new();
    let mut message_cache: HashMap<String, String> = HashMap::new();
    let mut sent_per_contact: HashMap<String, usize> = HashMap::new();

    let now = Utc::now();
    let mut rng = StdRng::from_entropy();

    for item in &plan.items {
        done += 1;

        let fail = |error: String, retryable: bool| ItemFailure {
            contact_name: item.contact_name.clone(),
            destination: item.destination.clone(),
            send_local: item.send_local.clone(),
            error,
            retryable,
        };

        // The preview may have been sitting on screen a while.
        if item.send_utc <= now {
            failed.push(fail(
                "send time passed while the preview was open; re-run the preview".into(),
                false,
            ));
            emit(&window, done, total, &item.contact_name, false);
            continue;
        }

        let Some(contact) = by_id.get(item.contact_id.as_str()) else {
            failed.push(fail(
                "this participant is no longer in the mailing list".into(),
                false,
            ));
            emit(&window, done, total, &item.contact_name, false);
            continue;
        };

        let lookup_id = match resolve_lookup_id(
            &client,
            &account.default_directory,
            &project.mailing_list_id,
            contact,
            &mut lookup_cache,
        )
        .await
        {
            Ok(id) => id,
            Err(e) => {
                let retryable = e.retryable();
                failed.push(fail(e.to_string(), retryable));
                emit(&window, done, total, &item.contact_name, false);
                continue;
            }
        };

        let message_id = match item.method {
            Method::Sms => project.message_id.clone(),
            Method::Email => {
                if project.message_id_email.trim().is_empty() {
                    failed.push(fail(
                        "this project has no email message selected".into(),
                        false,
                    ));
                    emit(&window, done, total, &item.contact_name, false);
                    continue;
                }
                project.message_id_email.clone()
            }
        };

        let body = match resolve_message(
            &client,
            &account.library_id,
            &message_id,
            &mut message_cache,
        )
        .await
        {
            Ok(b) => b,
            Err(e) => {
                let retryable = e.retryable();
                failed.push(fail(e.to_string(), retryable));
                emit(&window, done, total, &item.contact_name, false);
                continue;
            }
        };

        // Fresh suffix per message, so two invitations on one day stay distinct.
        let text = decorate_message(&body, &mut rng);
        let req = SendRequest {
            project: &project,
            contact_lookup_id: &lookup_id,
            message_text: &text,
            send_at: item.send_utc,
            expires_at: item.expire_utc,
        };

        let result = match item.method {
            Method::Sms => distributions::send_sms(&client, &req).await,
            Method::Email => distributions::send_email(&client, &req).await,
        };

        match result {
            Ok(_) => {
                *sent_per_contact.entry(item.contact_id.clone()).or_default() += 1;
                emit(&window, done, total, &item.contact_name, true);
            }
            Err(e) => {
                let retryable = e.retryable();
                failed.push(fail(e.to_string(), retryable));
                emit(&window, done, total, &item.contact_name, false);
            }
        }
        tokio::time::sleep(WRITE_PACING).await;
    }

    // Write SurveysScheduled once per contact rather than after every send: it is the
    // guard that stops a re-run from double-scheduling, and it must reflect the real count.
    let mut scheduled = 0usize;
    for (contact_id, count) in &sent_per_contact {
        scheduled += count;
        let Some(contact) = by_id.get(contact_id.as_str()) else {
            continue;
        };
        let mut updates = BTreeMap::new();
        updates.insert("SurveysScheduled".to_string(), count.to_string());
        let log = serde_json::json!({
            "action": "send",
            "count": count,
            "ts": Utc::now().to_rfc3339(),
        });
        if let Err(e) = contacts::update_contact(
            &client,
            &account.default_directory,
            &project.mailing_list_id,
            contact,
            &BTreeMap::new(),
            &[],
            &updates,
            Some(log),
        )
        .await
        {
            bookkeeping_failures.push(ItemFailure {
                contact_name: display_name(contact),
                destination: String::new(),
                send_local: String::new(),
                error: format!(
                    "{count} invitations were scheduled but SurveysScheduled could not be \
                     updated ({e}). Set it to {count} manually, or a re-run will schedule \
                     this contact again."
                ),
                retryable: true,
            });
        }
        tokio::time::sleep(WRITE_PACING).await;
    }

    Ok(SendReport {
        scheduled,
        failed,
        bookkeeping_failures,
    })
}

async fn resolve_lookup_id(
    client: &QualtricsClient,
    directory_id: &str,
    mailing_list_id: &str,
    contact: &RawContact,
    cache: &mut HashMap<String, String>,
) -> AppResult<String> {
    let contact_id = contact.id().unwrap_or_default().to_string();
    if let Some(hit) = cache.get(&contact_id) {
        return Ok(hit.clone());
    }
    let id =
        contacts::resolve_contact_lookup_id(client, directory_id, mailing_list_id, contact).await?;
    cache.insert(contact_id, id.clone());
    Ok(id)
}

async fn resolve_message(
    client: &QualtricsClient,
    library_id: &str,
    message_id: &str,
    cache: &mut HashMap<String, String>,
) -> AppResult<String> {
    if let Some(hit) = cache.get(message_id) {
        return Ok(hit.clone());
    }
    let text = messages::get_message_text(client, library_id, message_id).await?;
    cache.insert(message_id.to_string(), text.clone());
    Ok(text)
}

fn emit(window: &Window, done: usize, total: usize, contact_name: &str, ok: bool) {
    let _ = window.emit(
        PROGRESS_EVENT,
        Progress {
            done,
            total,
            contact_name: contact_name.to_string(),
            ok,
            error: None,
        },
    );
}
