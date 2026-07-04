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
        let resp = resp.error_for_status().map_err(|e| err(e.to_string()))?;
        resp.json::<R>().await.map_err(|e| err(e.to_string()))
    }
}
