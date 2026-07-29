use std::time::Duration;

use serde_json::Value;

use crate::error::{AppError, AppResult};

/// Qualtrics throttles bursts; a small gap between writes keeps large batches under the limit.
pub const WRITE_PACING: Duration = Duration::from_millis(120);

pub struct QualtricsClient {
    http: reqwest::Client,
    data_center: String,
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
            data_center: data_center.trim().to_string(),
            token: token.trim().to_string(),
        })
    }

    pub fn url(&self, path: &str) -> String {
        format!(
            "https://{}.qualtrics.com/API/v3/{}",
            self.data_center,
            path.trim_start_matches('/')
        )
    }

    async fn send(&self, req: reqwest::RequestBuilder) -> AppResult<Value> {
        let resp = req
            .header("x-api-token", &self.token)
            .header("Content-Type", "application/json")
            .send()
            .await?;

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
            return Ok(body);
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
