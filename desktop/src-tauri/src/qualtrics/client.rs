use std::sync::Mutex;
use std::time::Duration;

use serde_json::Value;

use crate::error::{AppError, AppResult};

/// Qualtrics throttles bursts; a small gap between writes keeps large batches under the limit.
pub const WRITE_PACING: Duration = Duration::from_millis(120);

/// Desktop has no 60-second proxy in front of the download. The body is still
/// capped at 32 MiB; this deadline is only the socket timeout.
#[allow(dead_code)]
pub const EXPORT_DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(300);

pub struct QualtricsClient {
    http: reqwest::Client,
    data_center: Mutex<String>,
    token: String,
}

impl QualtricsClient {
    pub fn new(data_center: &str, token: &str, verify_tls: bool) -> AppResult<Self> {
        let http = reqwest::Client::builder()
            .danger_accept_invalid_certs(!verify_tls)
            .timeout(Duration::from_secs(60))
            .build()?;
        Ok(Self {
            http,
            data_center: Mutex::new(data_center.trim().to_string()),
            token: token.trim().to_string(),
        })
    }

    fn data_center(&self) -> String {
        self.data_center
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone()
    }

    /// Point later calls at the host Qualtrics named. Returns whether it changed.
    fn retarget(&self, host: &str) -> bool {
        let Some(data_center) = host.strip_suffix(".qualtrics.com") else {
            return false;
        };
        if data_center.is_empty() {
            return false;
        }
        let mut current = self
            .data_center
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if *current == data_center {
            return false;
        }
        *current = data_center.to_string();
        true
    }

    pub fn url(&self, path: &str) -> String {
        format!(
            "https://{}.qualtrics.com/API/v3/{}",
            self.data_center(),
            path.trim_start_matches('/')
        )
    }

    /// Attaches the API token.
    ///
    /// Content-Type is deliberately not set here. `reqwest`'s `header` appends rather
    /// than replaces, so adding it on top of the one `.json()` already wrote sent
    /// `Content-Type` twice on every POST and PUT; Qualtrics reads the joined value and
    /// rejects the request with "Invalid Content-Type. Expected application/json".
    /// GET and DELETE carry no body and need no Content-Type at all.
    fn prepare(&self, req: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        req.header("x-api-token", &self.token)
    }

    async fn send(&self, req: reqwest::RequestBuilder) -> AppResult<Value> {
        let resp = self.prepare(req).send().await?;

        let status = resp.status();
        let text = resp.text().await?;

        if status.as_u16() == 401 || status.as_u16() == 403 {
            return Err(AppError::Unauthorized);
        }
        if status.as_u16() == 429 {
            return Err(AppError::RateLimited);
        }

        // Qualtrics returns its own error envelope with a 200-shaped body on some paths,
        // so parse first and check `meta` rather than trusting the HTTP status alone.
        let body: Value = serde_json::from_str(&text).map_err(|_| {
            AppError::Api(format!(
                "HTTP {status}: response was not JSON: {}",
                truncate(&text, 300)
            ))
        })?;

        let http_status = body
            .pointer("/meta/httpStatus")
            .and_then(Value::as_str)
            .unwrap_or("");

        if status.is_success() && (http_status.is_empty() || http_status.starts_with("200")) {
            if let Some(host) = qualtrics_host(body.pointer("/meta/notice").and_then(Value::as_str))
            {
                self.retarget(&host);
            }
            return Ok(body);
        }

        let code = body
            .pointer("/meta/error/errorCode")
            .and_then(Value::as_str)
            .and_then(machine_code);
        if code.as_deref() == Some("GRP_1") {
            return Err(AppError::Api(
                "Qualtrics refused the response export for this data center.".into(),
            ));
        }

        let msg = body
            .pointer("/meta/error/errorMessage")
            .and_then(Value::as_str)
            .map(str::to_string)
            .unwrap_or_else(|| truncate(&text, 300));

        if status.as_u16() == 404 {
            return Err(AppError::NotFound(msg));
        }
        Err(AppError::Api(msg))
    }

    pub async fn get(&self, path: &str) -> AppResult<Value> {
        self.send(self.http.get(self.url(path))).await
    }

    pub async fn get_absolute(&self, url: &str) -> AppResult<Value> {
        self.send(self.http.get(url)).await
    }

    pub async fn post(&self, path: &str, body: &Value) -> AppResult<Value> {
        self.send(self.http.post(self.url(path)).json(body)).await
    }

    pub async fn put(&self, path: &str, body: &Value) -> AppResult<Value> {
        self.send(self.http.put(self.url(path)).json(body)).await
    }

    pub async fn delete(&self, path: &str) -> AppResult<Value> {
        self.send(self.http.delete(self.url(path))).await
    }

    /// Binary download. The error text is only the HTTP status — export files can
    /// contain participant data and must not be copied into an error or a log.
    #[allow(dead_code)]
    pub async fn get_bytes(&self, path: &str) -> AppResult<Vec<u8>> {
        let mut retried = false;
        loop {
            let outcome = self.read_download(path).await?;
            match outcome {
                Download::Body(buf) => return Ok(buf),
                Download::Retry { host, .. } if !retried && self.retarget(&host) => {
                    retried = true;
                }
                Download::Retry { status, .. } | Download::Failed(status) => {
                    return Err(AppError::Api(format!(
                        "Qualtrics response export failed at download (HTTP {status})."
                    )));
                }
            }
        }
    }

    #[allow(dead_code)]
    async fn read_download(&self, path: &str) -> AppResult<Download> {
        let mut resp = self
            .prepare(
                self.http
                    .get(self.url(path))
                    .timeout(EXPORT_DOWNLOAD_TIMEOUT),
            )
            .send()
            .await?;
        let status = resp.status();
        if status.as_u16() == 401 || status.as_u16() == 403 {
            return Err(AppError::Unauthorized);
        }
        if status.as_u16() == 429 {
            return Err(AppError::RateLimited);
        }
        if !status.is_success() {
            let host = download_error_host(&mut resp).await;
            return Ok(match host {
                Some(host) => Download::Retry {
                    host,
                    status: status.as_u16(),
                },
                None => Download::Failed(status.as_u16()),
            });
        }
        let mut buf = Vec::new();
        const LIMIT: usize = 32 * 1024 * 1024;
        loop {
            match resp.chunk().await {
                Ok(Some(chunk)) => {
                    if buf.len().saturating_add(chunk.len()) > LIMIT {
                        buf.fill(0);
                        return Err(AppError::Api(
                            "Qualtrics response export failed at download (file too large).".into(),
                        ));
                    }
                    buf.extend_from_slice(&chunk);
                }
                Ok(None) => break,
                Err(_) => {
                    buf.fill(0);
                    return Err(AppError::Api(
                        "Qualtrics response export failed at download (timeout).".into(),
                    ));
                }
            }
        }
        Ok(Download::Body(buf))
    }

    /// Collect `result.elements` across every page, following the absolute
    /// `result.nextPage` cursor until it is null.
    pub async fn get_elements(&self, path: &str) -> AppResult<Vec<Value>> {
        let mut out = Vec::new();
        let mut body = self.get(path).await?;
        loop {
            if let Some(elements) = body.pointer("/result/elements").and_then(Value::as_array) {
                out.extend(elements.iter().cloned());
            }
            let next = body
                .pointer("/result/nextPage")
                .and_then(Value::as_str)
                .map(str::to_string);
            match next {
                Some(url) if !url.is_empty() => body = self.get_absolute(&url).await?,
                _ => break,
            }
        }
        Ok(out)
    }

    /// JSON call for response export. The error carries only an HTTP status and,
    /// when Qualtrics sent one, a machine `errorCode`. The error sentence is dropped.
    #[allow(dead_code)]
    pub async fn export_json(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<&Value>,
    ) -> Result<Value, RemoteReject> {
        let mut retried = false;
        loop {
            match self.export_json_once(method.clone(), path, body).await {
                Ok(value) => return Ok(value),
                Err(reject) if !retried && reject.code.as_deref() == Some("GRP_1") => {
                    let Some(host) = reject.host else {
                        return Err(reject);
                    };
                    if !self.retarget(&host) {
                        return Err(RemoteReject {
                            status: reject.status,
                            code: reject.code,
                            host: None,
                        });
                    }
                    retried = true;
                }
                Err(reject) => {
                    return Err(RemoteReject {
                        status: reject.status,
                        code: reject.code,
                        host: None,
                    });
                }
            }
        }
    }

    #[allow(dead_code)]
    async fn export_json_once(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<&Value>,
    ) -> Result<Value, RemoteReject> {
        let mut req = self.http.request(method, self.url(path));
        if let Some(body) = body {
            req = req.json(body);
        }
        let resp = match self.prepare(req).send().await {
            Ok(resp) => resp,
            Err(_) => return Err(RemoteReject { status: 504, code: None, host: None }),
        };
        let status = resp.status().as_u16();
        let text = match resp.text().await {
            Ok(text) => text,
            Err(_) => return Err(RemoteReject { status: 502, code: None, host: None }),
        };
        if status == 401 || status == 403 {
            return Err(RemoteReject { status: 401, code: None, host: None });
        }
        if status == 429 {
            return Err(RemoteReject { status: 429, code: None, host: None });
        }
        let parsed: Value = match serde_json::from_str(&text) {
            Ok(value) => value,
            Err(_) => {
                return Err(RemoteReject {
                    status: if status >= 400 { status } else { 502 },
                    code: None,
                    host: None,
                });
            }
        };
        let http_status = parsed
            .pointer("/meta/httpStatus")
            .and_then(Value::as_str)
            .unwrap_or("");
        let code = parsed
            .pointer("/meta/error/errorCode")
            .and_then(Value::as_str)
            .and_then(machine_code);
        if (200..300).contains(&status) && (http_status.is_empty() || http_status.starts_with("200"))
        {
            if let Some(host) =
                qualtrics_host(parsed.pointer("/meta/notice").and_then(Value::as_str))
            {
                self.retarget(&host);
            }
            return Ok(parsed);
        }
        let host = if code.as_deref() == Some("GRP_1") {
            qualtrics_host(
                parsed
                    .pointer("/meta/error/errorMessage")
                    .and_then(Value::as_str),
            )
        } else {
            None
        };
        Err(RemoteReject {
            status: if status >= 400 { status } else { 502 },
            code,
            host,
        })
    }

}

#[allow(dead_code)]
enum Download {
    Body(Vec<u8>),
    Retry { host: String, status: u16 },
    Failed(u16),
}

/// A download error is at most 4 KiB of JSON. The buffer is wiped. Only a GRP_1 host is kept.
#[allow(dead_code)]
async fn download_error_host(resp: &mut reqwest::Response) -> Option<String> {
    let mut raw = Vec::new();
    while raw.len() < 4096 {
        match resp.chunk().await {
            Ok(Some(chunk)) => {
                let room = 4096 - raw.len();
                let take = chunk.len().min(room);
                raw.extend_from_slice(&chunk[..take]);
                if chunk.len() > room {
                    break;
                }
            }
            _ => break,
        }
    }
    let host = grp1_host_from_bytes(&raw);
    raw.fill(0);
    host
}

#[allow(dead_code)]
fn grp1_host_from_bytes(raw: &[u8]) -> Option<String> {
    let value: Value = serde_json::from_slice(raw).ok()?;
    let code = value
        .pointer("/meta/error/errorCode")
        .and_then(Value::as_str)
        .and_then(machine_code)?;
    if code != "GRP_1" {
        return None;
    }
    qualtrics_host(
        value
            .pointer("/meta/error/errorMessage")
            .and_then(Value::as_str),
    )
}

/// Host named by a proxy notice or a GRP_1 sentence. The rest of the text is dropped.
pub fn qualtrics_host(text: Option<&str>) -> Option<String> {
    let text = text?;
    let token = belongs_to_token(text).or_else(|| notice_token(text))?;
    host_token(token)
}

fn belongs_to_token(text: &str) -> Option<&str> {
    let marker = "datacenter the API user belongs to:";
    let index = text.to_ascii_lowercase().find(&marker.to_ascii_lowercase())?;
    Some(text[index + marker.len()..].trim())
}

fn notice_token(text: &str) -> Option<&str> {
    let marker = "use this host instead:";
    let index = text.to_ascii_lowercase().find(&marker.to_ascii_lowercase())?;
    Some(text[index + marker.len()..].trim())
}

fn host_token(token: &str) -> Option<String> {
    let token = token
        .trim()
        .trim_matches(|c: char| c == '.' || c.is_whitespace())
        .to_ascii_lowercase();
    let token = token.split_whitespace().next()?.trim_matches('.');
    if token.is_empty()
        || token.contains('@')
        || token.contains('/')
        || token.contains("..")
        || token.contains('_')
    {
        return None;
    }
    if let Some(name) = token.strip_suffix(".qualtrics.com") {
        if !name.is_empty() && name.split('.').all(label_ok) {
            return Some(token.to_string());
        }
        return None;
    }
    if dc_id_ok(token) {
        return Some(format!("{token}.qualtrics.com"));
    }
    None
}

fn label_ok(label: &str) -> bool {
    let bytes = label.as_bytes();
    if bytes.is_empty() || bytes.len() > 22 {
        return false;
    }
    bytes.iter().all(|b| b.is_ascii_alphanumeric() || *b == b'-')
        && !bytes.starts_with(b"-")
        && !bytes.ends_with(b"-")
}

fn dc_id_ok(token: &str) -> bool {
    let bytes = token.as_bytes();
    if bytes.len() < 2 || bytes.len() > 13 {
        return false;
    }
    let Some(digit) = bytes.iter().position(|b| b.is_ascii_digit()) else {
        return false;
    };
    digit >= 1
        && digit <= 6
        && bytes[..digit].iter().all(|b| b.is_ascii_lowercase())
        && bytes[digit..].iter().all(|b| b.is_ascii_alphanumeric())
}

/// Qualtrics machine codes such as `RTE_2`. Sentences, column names, and ids do not match.
pub fn machine_code(value: &str) -> Option<String> {
    if (1..=32).contains(&value.len())
        && value.chars().next().is_some_and(|c| c.is_ascii_uppercase())
        && value
            .chars()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
    {
        Some(value.to_string())
    } else {
        None
    }
}

#[allow(dead_code)]
#[derive(Debug)]
pub struct RemoteReject {
    pub status: u16,
    pub code: Option<String>,
    /// Validated datacenter host from a GRP_1 sentence. Not part of the user message.
    pub host: Option<String>,
}

fn truncate(s: &str, n: usize) -> String {
    if s.len() <= n {
        s.to_string()
    } else {
        format!("{}…", &s[..n])
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::header::CONTENT_TYPE;
    use serde_json::json;

    fn client() -> QualtricsClient {
        QualtricsClient::new("yul1", "token", true).unwrap()
    }

    #[test]
    fn grp1_keeps_only_the_named_datacenter_host() {
        let sentence = "Cannot download response export file through datacenter proxing, \
            please retry using the url of the datacenter the API user belongs to: CO1";
        assert_eq!(
            qualtrics_host(Some(sentence)).as_deref(),
            Some("co1.qualtrics.com")
        );
        assert_eq!(
            qualtrics_host(Some(
                "use this host instead: iad1.qualtrics.com"
            ))
            .as_deref(),
            Some("iad1.qualtrics.com")
        );
        assert_eq!(
            qualtrics_host(Some(
                "datacenter the API user belongs to: ada@example.com"
            )),
            None
        );
        assert_eq!(
            qualtrics_host(Some("datacenter the API user belongs to: SV_example")),
            None
        );
        let body = format!(
            r#"{{"meta":{{"error":{{"errorCode":"GRP_1","errorMessage":"{sentence}"}}}}}}"#
        );
        assert_eq!(
            grp1_host_from_bytes(body.as_bytes()).as_deref(),
            Some("co1.qualtrics.com")
        );
        let leaked = br#"{"meta":{"error":{"errorCode":"GRP_1","errorMessage":"datacenter the API user belongs to: ada@example.com"}}}"#;
        assert_eq!(grp1_host_from_bytes(leaked), None);
    }

    #[test]
    fn export_download_keeps_the_long_desktop_timeout() {
        assert_eq!(EXPORT_DOWNLOAD_TIMEOUT, Duration::from_secs(300));
    }

    // A second Content-Type header made Qualtrics reject every write.
    #[test]
    fn body_requests_send_one_content_type() {
        let c = client();
        for req in [
            c.http.post(c.url("directories/x/contacts")),
            c.http.put(c.url("directories/x/contacts/y")),
        ] {
            let built = c.prepare(req.json(&json!({"a": 1}))).build().unwrap();
            let values: Vec<_> = built.headers().get_all(CONTENT_TYPE).iter().collect();
            assert_eq!(values, vec!["application/json"]);
        }
    }

    #[test]
    fn bodyless_requests_send_no_content_type() {
        let c = client();
        for req in [c.http.get(c.url("directories")), c.http.delete(c.url("x"))] {
            let built = c.prepare(req).build().unwrap();
            assert!(built.headers().get(CONTENT_TYPE).is_none());
        }
    }

    // The error envelope shape is the one contract we can pin without a live API.
    #[test]
    fn extracts_error_message_from_meta() {
        let body: Value = serde_json::from_str(
            r#"{"meta":{"httpStatus":"400 - Bad Request",
                 "error":{"errorCode":"BAD","errorMessage":"Unexpected json key provided: contactLookupId"}}}"#,
        )
        .unwrap();
        let msg = body
            .pointer("/meta/error/errorMessage")
            .and_then(Value::as_str)
            .unwrap();
        assert_eq!(msg, "Unexpected json key provided: contactLookupId");
    }

    #[test]
    fn success_envelope_has_200_status() {
        let body: Value =
            serde_json::from_str(r#"{"meta":{"httpStatus":"200 - OK"},"result":{"elements":[]}}"#)
                .unwrap();
        let st = body
            .pointer("/meta/httpStatus")
            .and_then(Value::as_str)
            .unwrap();
        assert!(st.starts_with("200"));
    }
}

