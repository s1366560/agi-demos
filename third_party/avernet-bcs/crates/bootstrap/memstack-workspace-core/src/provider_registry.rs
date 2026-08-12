//! Authenticated HTTP adapter for the external MemStack Provider Registry.

use std::time::Duration;

use async_trait::async_trait;
use memstack_workspace_service_api::{
    ProviderRegistryLookup, ProviderRegistryPort, ProviderRegistryPortError, ProviderRegistryRoute,
    TenantId,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

const RESOLVE_PATH: &str = "/internal/v1/workspace-core/provider-registry/resolve";
const DEFAULT_PATH: &str = "/internal/v1/workspace-core/provider-registry/default";

/// Invalid external Provider Registry client configuration.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum HttpProviderRegistryConfigError {
    #[error("Provider Registry base URL must not be blank")]
    BlankBaseUrl,

    #[error("Provider Registry token must not be blank")]
    BlankToken,

    #[error("Provider Registry HTTP client initialization failed: {0}")]
    Client(#[source] reqwest::Error),
}

/// Fail-closed HTTP implementation of [`ProviderRegistryPort`].
pub struct HttpProviderRegistryPort {
    client: reqwest::Client,
    resolve_url: String,
    default_url: String,
    token: String,
}

impl HttpProviderRegistryPort {
    /// Construct a client without exposing its bearer token through `Debug`.
    ///
    /// # Errors
    ///
    /// Returns [`HttpProviderRegistryConfigError`] for blank credentials or
    /// an invalid HTTP client configuration.
    pub fn new(
        base_url: impl Into<String>,
        token: impl Into<String>,
        timeout: Duration,
    ) -> Result<Self, HttpProviderRegistryConfigError> {
        let base_url = base_url.into();
        if base_url.trim().is_empty() {
            return Err(HttpProviderRegistryConfigError::BlankBaseUrl);
        }
        let token = token.into();
        if token.trim().is_empty() {
            return Err(HttpProviderRegistryConfigError::BlankToken);
        }
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .map_err(HttpProviderRegistryConfigError::Client)?;
        let base_url = base_url.trim_end_matches('/');
        Ok(Self {
            client,
            resolve_url: format!("{base_url}{RESOLVE_PATH}"),
            default_url: format!("{base_url}{DEFAULT_PATH}"),
            token,
        })
    }

    async fn request(
        &self,
        url: &str,
        request: &RegistryRequest<'_>,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        let response = self
            .client
            .post(url)
            .bearer_auth(&self.token)
            .json(request)
            .send()
            .await
            .map_err(|_| ProviderRegistryPortError::Unavailable)?;
        if !response.status().is_success() {
            return Err(ProviderRegistryPortError::Unavailable);
        }
        let response = response
            .json::<RegistryResponse>()
            .await
            .map_err(|_| ProviderRegistryPortError::Unavailable)?;
        if !response.available {
            return Ok(None);
        }
        let route = ProviderRegistryRoute::parse(
            response
                .provider_id
                .ok_or(ProviderRegistryPortError::Unavailable)?,
            response
                .model_id
                .ok_or(ProviderRegistryPortError::Unavailable)?,
        )
        .map_err(|_| ProviderRegistryPortError::Unavailable)?;
        Ok(Some(route))
    }
}

#[derive(Debug, Serialize)]
struct RegistryRequest<'a> {
    tenant_id: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    provider_id: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    model_id: Option<&'a str>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RegistryResponse {
    available: bool,
    provider_id: Option<String>,
    model_id: Option<String>,
}

#[async_trait]
impl ProviderRegistryPort for HttpProviderRegistryPort {
    async fn resolve(
        &self,
        lookup: &ProviderRegistryLookup,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        let resolved = self
            .request(
                &self.resolve_url,
                &RegistryRequest {
                    tenant_id: lookup.tenant_id().as_str(),
                    provider_id: Some(lookup.provider_id().as_str()),
                    model_id: Some(lookup.model_id().as_str()),
                },
            )
            .await?;
        if resolved.as_ref().is_some_and(|route| {
            route.provider_id() != lookup.provider_id() || route.model_id() != lookup.model_id()
        }) {
            return Err(ProviderRegistryPortError::Unavailable);
        }
        Ok(resolved)
    }

    async fn tenant_default(
        &self,
        tenant_id: &TenantId,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        self.request(
            &self.default_url,
            &RegistryRequest {
                tenant_id: tenant_id.as_str(),
                provider_id: None,
                model_id: None,
            },
        )
        .await
    }
}

/// Default state dependency used by incomplete deployments and focused tests.
pub(crate) struct UnavailableProviderRegistryPort;

#[async_trait]
impl ProviderRegistryPort for UnavailableProviderRegistryPort {
    async fn resolve(
        &self,
        _lookup: &ProviderRegistryLookup,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        Err(ProviderRegistryPortError::Unavailable)
    }

    async fn tenant_default(
        &self,
        _tenant_id: &TenantId,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        Err(ProviderRegistryPortError::Unavailable)
    }
}
