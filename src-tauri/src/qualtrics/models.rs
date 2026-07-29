use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Generic id/name pair backing most dropdowns.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IdName {
    pub id: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MailingListInfo {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub contact_count: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MessageInfo {
    pub id: String,
    pub description: String,
    #[serde(default)]
    pub category: Option<String>,
}

/// A contact exactly as Qualtrics returned it. Kept as the raw JSON object because the
/// update endpoint requires echoing back unknown fields it gave us.
#[derive(Debug, Clone)]
pub struct RawContact {
    pub json: Value,
}

impl RawContact {
    pub fn id(&self) -> Option<&str> {
        self.json.get("contactId").and_then(Value::as_str)
    }

    pub fn str_field(&self, key: &str) -> Option<String> {
        self.json
            .get(key)
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
    }

    /// Embedded values arrive as strings, numbers or booleans; normalize to strings
    /// since every consumer parses them anyway.
    pub fn embedded(&self) -> BTreeMap<String, String> {
        let mut out = BTreeMap::new();
        if let Some(obj) = self.json.get("embeddedData").and_then(Value::as_object) {
            for (k, v) in obj {
                out.insert(k.clone(), value_to_string(v));
            }
        }
        out
    }
}

pub fn value_to_string(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

/// Contact projected for the UI table, with scheduling eligibility already computed.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ContactView {
    pub contact_id: String,
    pub first_name: String,
    pub last_name: String,
    pub email: String,
    pub phone: String,
    pub ext_ref: String,
    pub embedded: BTreeMap<String, String>,
    pub eligible: bool,
    /// Why this contact will be skipped; `None` when eligible.
    pub skip_reason: Option<String>,
    /// How this participant is contacted, whether or not they are currently eligible.
    pub method: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Method {
    Sms,
    Email,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DistributionRow {
    pub id: String,
    pub contact_lookup_id: String,
    pub contact_name: String,
    pub send_date: String,
    /// `send_date` as wall-clock time in the recipient's own timezone, with the zone
    /// shown — the same rendering the Schedule screen uses. Empty when the recipient
    /// or their timezone could not be resolved; filled in by the command layer.
    pub send_local: String,
    pub method: Method,
    /// Derived: sendDate is still in the future, so it can be cancelled.
    pub unsent: bool,
    /// The survey this distribution was created against — the project's own or one of
    /// its copies. Cancelling an SMS row needs it, and the table shows `survey_label`
    /// ("original", "c1", ...) so a participant's day reads in order.
    pub survey_id: String,
    pub survey_label: String,
}
