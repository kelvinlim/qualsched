use std::collections::BTreeMap;

use serde_json::{json, Map, Value};

use super::{client::QualtricsClient, models::RawContact};
use crate::error::{AppError, AppResult};

/// Cap on retained LogData entries. Qualtrics limits embedded-data field size, and an
/// unbounded audit array eventually breaks the contact update.
const LOG_DATA_MAX: usize = 50;

pub async fn list_contacts(
    client: &QualtricsClient,
    directory_id: &str,
    mailing_list_id: &str,
) -> AppResult<Vec<RawContact>> {
    let elements = client
        .get_elements(&format!(
            "directories/{directory_id}/mailinglists/{mailing_list_id}/contacts?includeEmbedded=true"
        ))
        .await?;
    Ok(elements.into_iter().map(|json| RawContact { json }).collect())
}

/// Resolves the `CGC_…` contactLookupId required as the recipient of a distribution.
///
/// The mailing-list response usually carries it already; falling back to a per-contact
/// request only when it doesn't turns N requests into zero for the common case.
pub async fn resolve_contact_lookup_id(
    client: &QualtricsClient,
    directory_id: &str,
    mailing_list_id: &str,
    contact: &RawContact,
) -> AppResult<String> {
    if let Some(id) = contact.str_field("contactLookupId") {
        return Ok(id);
    }
    let contact_id = contact
        .id()
        .ok_or_else(|| AppError::Invalid("contact has no contactId".into()))?;
    get_contact_lookup_id(client, directory_id, mailing_list_id, contact_id).await
}

/// Fetches the `CGC_…` contactLookupId for one contact.
///
/// Deliberately queries the directory-level contact rather than the mailing-list one:
/// the mailing-list path returns 404 for contacts that are in the list (observed in
/// qualtrics_util, see its getContactLookupId notes).
pub async fn get_contact_lookup_id(
    client: &QualtricsClient,
    directory_id: &str,
    mailing_list_id: &str,
    contact_id: &str,
) -> AppResult<String> {
    let body = client
        .get(&format!("directories/{directory_id}/contacts/{contact_id}"))
        .await?;
    body.pointer("/result/mailingListMembership")
        .and_then(|m| m.get(mailing_list_id))
        .and_then(|m| m.get("contactLookupId"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| {
            AppError::NotFound(format!(
                "contact {contact_id} has no membership in mailing list {mailing_list_id}"
            ))
        })
}

/// Identity fields Qualtrics accepts on a mailing-list contact. Anything outside this
/// set is embedded data.
pub const CORE_FIELDS: [&str; 5] = ["firstName", "lastName", "email", "phone", "extRef"];

/// Creates a contact in the mailing list and returns it as Qualtrics stored it.
///
/// `seed` supplies the project's embedded defaults so a new participant starts with the
/// study's scheduling values rather than an empty record.
pub async fn create_contact(
    client: &QualtricsClient,
    directory_id: &str,
    mailing_list_id: &str,
    core: &BTreeMap<String, String>,
    embedded: &BTreeMap<String, String>,
    seed: &[(String, String)],
) -> AppResult<RawContact> {
    let mut fields = Map::new();
    for key in CORE_FIELDS {
        // Sending an empty string where Qualtrics wants a real value is rejected;
        // leaving the key out is fine.
        if let Some(value) = core.get(key).map(|v| v.trim()).filter(|v| !v.is_empty()) {
            fields.insert(key.to_string(), Value::String(value.to_string()));
        }
    }
    if fields.is_empty() {
        return Err(AppError::Invalid(
            "a new participant needs at least a name, email address or phone number".into(),
        ));
    }
    fields.insert("language".into(), json!("en"));

    let mut embedded_map = Map::new();
    for (key, value) in seed {
        embedded_map.insert(key.clone(), Value::String(value.clone()));
    }
    for (key, value) in embedded {
        embedded_map.insert(key.clone(), Value::String(value.clone()));
    }
    embedded_map.insert(
        "LogData".into(),
        Value::String(append_log_data(None, json!({ "action": "created" }))?),
    );
    fields.insert("embeddedData".into(), Value::Object(embedded_map));

    let resp = client
        .post(
            &format!("directories/{directory_id}/mailinglists/{mailing_list_id}/contacts"),
            &Value::Object(fields),
        )
        .await?;

    // The create response carries only the new id, so read the contact back in full.
    let contact_id = resp
        .pointer("/result/id")
        .or_else(|| resp.pointer("/result/contactId"))
        .and_then(Value::as_str)
        .ok_or_else(|| {
            AppError::Api("Qualtrics did not return an id for the new participant".into())
        })?;

    fetch_contact(client, directory_id, mailing_list_id, contact_id).await
}

async fn fetch_contact(
    client: &QualtricsClient,
    directory_id: &str,
    mailing_list_id: &str,
    contact_id: &str,
) -> AppResult<RawContact> {
    let body = client
        .get(&format!(
            "directories/{directory_id}/mailinglists/{mailing_list_id}/contacts/{contact_id}"
        ))
        .await?;
    let json = body
        .get("result")
        .cloned()
        .ok_or_else(|| AppError::NotFound(format!("contact {contact_id} could not be read back")))?;
    Ok(RawContact { json })
}

/// Removes a contact from the mailing list.
///
/// This ends their membership in this study's list only. The person stays in the
/// directory, along with any response data and their membership in other lists —
/// deleting them outright is a directory-level operation this app does not perform.
pub async fn remove_from_mailing_list(
    client: &QualtricsClient,
    directory_id: &str,
    mailing_list_id: &str,
    contact_id: &str,
) -> AppResult<()> {
    client
        .delete(&format!(
            "directories/{directory_id}/mailinglists/{mailing_list_id}/contacts/{contact_id}"
        ))
        .await?;
    Ok(())
}

/// Applies changes to a contact and PUTs the whole record back.
///
/// `core` names identity fields (see [`CORE_FIELDS`]); `updates` names embedded-data
/// keys. `seed` holds project defaults: keys absent from the contact are initialized
/// from it, keys already present are left alone unless named in `updates`. This mirrors
/// the CLI's behavior of never clobbering per-participant values with template values.
#[allow(clippy::too_many_arguments)]
pub async fn update_contact(
    client: &QualtricsClient,
    directory_id: &str,
    mailing_list_id: &str,
    contact: &RawContact,
    core: &BTreeMap<String, String>,
    seed: &[(String, String)],
    updates: &BTreeMap<String, String>,
    log_entry: Option<Value>,
) -> AppResult<RawContact> {
    let contact_id = contact
        .id()
        .ok_or_else(|| AppError::Invalid("contact has no contactId".into()))?
        .to_string();

    let mut data = contact
        .json
        .as_object()
        .cloned()
        .ok_or_else(|| AppError::Invalid("contact is not a JSON object".into()))?;

    for (key, value) in core {
        if !CORE_FIELDS.contains(&key.as_str()) {
            return Err(AppError::Invalid(format!("{key} is not an editable field")));
        }
        let value = value.trim();
        if value.is_empty() {
            data.remove(key);
        } else {
            data.insert(key.clone(), Value::String(value.to_string()));
        }
    }

    let mut embedded: Map<String, Value> = data
        .get("embeddedData")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();

    for (key, value) in seed {
        embedded
            .entry(key.clone())
            .or_insert_with(|| Value::String(value.clone()));
    }
    for (key, value) in updates {
        embedded.insert(key.clone(), Value::String(value.clone()));
    }
    if let Some(entry) = log_entry {
        let appended = append_log_data(embedded.get("LogData"), entry)?;
        embedded.insert("LogData".into(), Value::String(appended));
    }
    data.insert("embeddedData".into(), Value::Object(embedded));

    // Qualtrics rejects these on the way back in even though it sends them out.
    data.remove("contactId");
    data.remove("contactLookupId");
    data.remove("mailingListUnsubscribed");
    // "email cannot be empty" — omitting the key entirely is accepted, sending null is not.
    if data.get("email").map_or(true, Value::is_null) {
        data.remove("email");
    }
    if data.get("language").map_or(true, Value::is_null) {
        data.insert("language".into(), json!("en"));
    }

    let payload = Value::Object(data);
    client
        .put(
            &format!(
                "directories/{directory_id}/mailinglists/{mailing_list_id}/contacts/{contact_id}"
            ),
            &payload,
        )
        .await?;

    // Re-read so the UI reflects exactly what Qualtrics stored.
    fetch_contact(client, directory_id, mailing_list_id, &contact_id).await
}

/// LogData is a JSON array of audit entries. Older records stored a bare object;
/// those are promoted to a single-element array rather than discarded.
fn append_log_data(existing: Option<&Value>, entry: Value) -> AppResult<String> {
    let mut list: Vec<Value> = match existing {
        Some(Value::String(s)) if !s.trim().is_empty() => match serde_json::from_str(s) {
            Ok(Value::Array(a)) => a,
            Ok(obj @ Value::Object(_)) => vec![obj],
            _ => Vec::new(),
        },
        Some(Value::Array(a)) => a.clone(),
        _ => Vec::new(),
    };
    list.push(entry);
    if list.len() > LOG_DATA_MAX {
        list.drain(0..list.len() - LOG_DATA_MAX);
    }
    Ok(serde_json::to_string(&list)?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn appends_to_existing_array() {
        let existing = Value::String(r#"[{"action":"init"}]"#.into());
        let out = append_log_data(Some(&existing), json!({"action":"send"})).unwrap();
        let parsed: Vec<Value> = serde_json::from_str(&out).unwrap();
        assert_eq!(parsed.len(), 2);
        assert_eq!(parsed[1]["action"], "send");
    }

    #[test]
    fn promotes_legacy_object_to_array() {
        let existing = Value::String(r#"{"action":"init"}"#.into());
        let out = append_log_data(Some(&existing), json!({"action":"send"})).unwrap();
        let parsed: Vec<Value> = serde_json::from_str(&out).unwrap();
        assert_eq!(parsed.len(), 2);
        assert_eq!(parsed[0]["action"], "init");
    }

    #[test]
    fn starts_fresh_when_absent_or_garbage() {
        for existing in [None, Some(Value::String("not json".into()))] {
            let out = append_log_data(existing.as_ref(), json!({"action":"send"})).unwrap();
            let parsed: Vec<Value> = serde_json::from_str(&out).unwrap();
            assert_eq!(parsed.len(), 1);
        }
    }

    #[test]
    fn caps_length_dropping_oldest() {
        let seed: Vec<Value> = (0..LOG_DATA_MAX + 10).map(|i| json!({ "n": i })).collect();
        let existing = Value::String(serde_json::to_string(&seed).unwrap());
        let out = append_log_data(Some(&existing), json!({"n": "last"})).unwrap();
        let parsed: Vec<Value> = serde_json::from_str(&out).unwrap();
        assert_eq!(parsed.len(), LOG_DATA_MAX);
        assert_eq!(parsed[LOG_DATA_MAX - 1]["n"], "last");
    }
}
