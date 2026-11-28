use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tokio::sync::OnceCell;

use agistack_core::ports::{CoreError, CoreResult};

/// Shared HTTP transport config: base URL, optional API key, model id.
#[derive(Clone)]
pub(super) struct Endpoint {
    client: Arc<OnceCell<reqwest::Client>>,
    pub(super) base_url: String,
    pub(super) api_key: Option<String>,
    pub(super) model: String,
}

impl Endpoint {
    pub(super) fn new(base_url: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            client: Arc::default(),
            base_url: base_url.into().trim_end_matches('/').to_string(),
            api_key: None,
            model: model.into(),
        }
    }

    pub(super) fn set_http_client(&mut self, client: reqwest::Client) {
        self.client = Arc::new(OnceCell::from(client));
    }

    pub(super) async fn http_client(
        &self,
        err: fn(String) -> CoreError,
    ) -> CoreResult<&reqwest::Client> {
        // TLS initialization can block. Only initialize the default transport on
        // first use, outside the executor that drives request-scoped lease renewal.
        self.client
            .get_or_try_init(|| async {
                tokio::task::spawn_blocking(|| reqwest::Client::builder().build())
                    .await
                    .map_err(|e| err(e.to_string()))?
                    .map_err(|e| err(e.to_string()))
            })
            .await
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
        let mut req = self.http_client(err).await?.post(&url).json(body);
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

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn default_transport_is_lazy_and_shared_by_endpoint_clones() {
        let endpoint = Endpoint::new("http://localhost", "model");
        let clone = endpoint.clone();
        assert!(endpoint.client.get().is_none());
        let client = endpoint.http_client(CoreError::Llm).await.unwrap();
        assert!(std::ptr::eq(
            client,
            clone.http_client(CoreError::Llm).await.unwrap()
        ));
    }
}
