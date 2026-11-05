use serde::{Deserialize, Serialize};

use agistack_core::ports::{CoreError, CoreResult};

/// Shared HTTP transport config: base URL, optional API key, model id.
#[derive(Clone)]
pub(super) struct Endpoint {
    pub(super) client: reqwest::Client,
    pub(super) base_url: String,
    pub(super) api_key: Option<String>,
    pub(super) model: String,
}

impl Endpoint {
    pub(super) fn new(base_url: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            client: reqwest::Client::new(),
            base_url: base_url.into().trim_end_matches('/').to_string(),
            api_key: None,
            model: model.into(),
        }
    }

    /// POST `body` to `{base}{path}` and deserialize the JSON response, mapping
    /// transport, non-2xx, and decode failures to `err`.
    pub(super) async fn post_json<B: Serialize, R: for<'de> Deserialize<'de>>(
        &self,
        path: &str,
        body: &B,
        err: fn(String) -> CoreError,
    ) -> CoreResult<R> {
        let url = format!("{}{}", self.base_url, path);
        let mut req = self.client.post(&url).json(body);
        if let Some(key) = &self.api_key {
            req = req.bearer_auth(key);
        }
        let resp = req.send().await.map_err(|e| err(e.to_string()))?;
        let resp = self.checked_response(resp, err).await?;
        self.decode_json(resp, err).await
    }

    pub(super) async fn checked_response(
        &self,
        mut response: reqwest::Response,
        err: fn(String) -> CoreError,
    ) -> CoreResult<reqwest::Response> {
        if response.status().is_success() {
            return Ok(response);
        }
        let status = response.status().as_u16();
        let mut bytes = Vec::new();
        while let Ok(Some(chunk)) = response.chunk().await {
            if bytes.len() + chunk.len() > crate::provider_error::MAX_ERROR_BYTES {
                return Err(err(format!("provider_http_error: HTTP {status}")));
            }
            bytes.extend_from_slice(&chunk);
        }
        let detail = serde_json::from_slice(&bytes)
            .ok()
            .and_then(|value| crate::provider_error::detail(&value, self.api_key.as_deref()));
        Err(err(format!(
            "provider_http_error: HTTP {status}{}",
            detail
                .map(|detail| format!(": {detail}"))
                .unwrap_or_default()
        )))
    }

    pub(super) async fn decode_json<R: for<'de> Deserialize<'de>>(
        &self,
        response: reqwest::Response,
        err: fn(String) -> CoreError,
    ) -> CoreResult<R> {
        let value = response
            .json::<serde_json::Value>()
            .await
            .map_err(|e| err(e.to_string()))?;
        if let Some(detail) = crate::provider_error::detail(&value, self.api_key.as_deref()) {
            return Err(err(format!("provider_response_error: {detail}")));
        }
        serde_json::from_value(value).map_err(|e| err(e.to_string()))
    }
}
