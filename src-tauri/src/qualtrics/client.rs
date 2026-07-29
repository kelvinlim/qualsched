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

    /// POST with extra request headers, for endpoints that take their directives there
    /// rather than in the body — the copy-survey call names both its source and the
    /// owner of the copy that way.
    pub async fn post_with_headers(
        &self,
        path: &str,
        headers: &[(&str, &str)],
        body: &Value,
    ) -> AppResult<Value> {
        let mut req = self.http.post(self.url(path));
        for (name, value) in headers {
            req = req.header(*name, *value);
        }
        self.send(req.json(body)).await
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
    use reqwest::header::CONTENT_TYPE;
    use serde_json::json;

    fn client() -> QualtricsClient {
        QualtricsClient::new("yul1", "token", true).unwrap()
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

    // Copying a survey names its source and the copy's owner in headers, which must not
    // disturb the single-Content-Type rule above.
    #[test]
    fn extra_headers_ride_alongside_one_content_type() {
        let c = client();
        let built = c
            .prepare(
                c.http
                    .post(c.url("surveys"))
                    .header("X-COPY-SOURCE", "SV_1")
                    .header("X-COPY-DESTINATION-OWNER", "UR_1")
                    .json(&json!({"projectName": "Study-c1"})),
            )
            .build()
            .unwrap();
        let values: Vec<_> = built.headers().get_all(CONTENT_TYPE).iter().collect();
        assert_eq!(values, vec!["application/json"]);
        assert_eq!(built.headers().get("X-COPY-SOURCE").unwrap(), "SV_1");
        assert_eq!(
            built.headers().get("X-COPY-DESTINATION-OWNER").unwrap(),
            "UR_1"
        );
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

