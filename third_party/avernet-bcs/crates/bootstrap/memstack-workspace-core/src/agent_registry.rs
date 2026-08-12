//! Authenticated HTTP adapter for the external MemStack Agent Registry.

use std::time::Duration;

use async_trait::async_trait;
use memstack_workspace_service_api::{
    AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

const RESOLVE_PATH: &str = "/internal/v1/workspace-core/agent-registry/resolve";

/// Invalid external Agent Registry client configuration.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum HttpAgentRegistryConfigError {
    #[error("Agent Registry base URL must not be blank")]
    BlankBaseUrl,

    #[error("Agent Registry token must not be blank")]
    BlankToken,

    #[error("Agent Registry HTTP client initialization failed: {0}")]
    Client(#[source] reqwest::Error),
}

/// Fail-closed HTTP implementation of [`AgentRegistryPort`].
pub struct HttpAgentRegistryPort {
    client: reqwest::Client,
    resolve_url: String,
    token: String,
}

impl HttpAgentRegistryPort {
    /// Construct a client without exposing its bearer token through `Debug`.
    ///
    /// # Errors
    ///
    /// Returns [`HttpAgentRegistryConfigError`] for blank credentials or an
    /// invalid HTTP client configuration.
    pub fn new(
        base_url: impl Into<String>,
        token: impl Into<String>,
        timeout: Duration,
    ) -> Result<Self, HttpAgentRegistryConfigError> {
        let base_url = base_url.into();
        if base_url.trim().is_empty() {
            return Err(HttpAgentRegistryConfigError::BlankBaseUrl);
        }
        let token = token.into();
        if token.trim().is_empty() {
            return Err(HttpAgentRegistryConfigError::BlankToken);
        }
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .map_err(HttpAgentRegistryConfigError::Client)?;
        Ok(Self {
            client,
            resolve_url: format!("{}{}", base_url.trim_end_matches('/'), RESOLVE_PATH),
            token,
        })
    }
}

#[derive(Debug, Serialize)]
struct ResolveRequest<'a> {
    tenant_id: &'a str,
    project_id: &'a str,
    agent_id: &'a str,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ResolveResponse {
    available: bool,
    agent_id: Option<String>,
    name: Option<String>,
    display_name: Option<String>,
    enabled: Option<bool>,
}

#[async_trait]
impl AgentRegistryPort for HttpAgentRegistryPort {
    async fn resolve(
        &self,
        lookup: &AgentRegistryLookup,
    ) -> Result<Option<AgentRegistryAgent>, AgentRegistryPortError> {
        let response = self
            .client
            .post(&self.resolve_url)
            .bearer_auth(&self.token)
            .json(&ResolveRequest {
                tenant_id: lookup.tenant_id().as_str(),
                project_id: lookup.project_id().as_str(),
                agent_id: lookup.agent_id().as_str(),
            })
            .send()
            .await
            .map_err(|_| AgentRegistryPortError::Unavailable)?;
        if !response.status().is_success() {
            return Err(AgentRegistryPortError::Unavailable);
        }
        let response = response
            .json::<ResolveResponse>()
            .await
            .map_err(|_| AgentRegistryPortError::Unavailable)?;
        if !response.available {
            return Ok(None);
        }
        let agent = AgentRegistryAgent::parse(
            response
                .agent_id
                .ok_or(AgentRegistryPortError::Unavailable)?,
            response.name.ok_or(AgentRegistryPortError::Unavailable)?,
            response.display_name,
            response
                .enabled
                .ok_or(AgentRegistryPortError::Unavailable)?,
        )
        .map_err(|_| AgentRegistryPortError::Unavailable)?;
        Ok(Some(agent))
    }
}

/// Default state dependency used by read-only tests and incomplete deployments.
pub(crate) struct UnavailableAgentRegistryPort;

#[async_trait]
impl AgentRegistryPort for UnavailableAgentRegistryPort {
    async fn resolve(
        &self,
        _lookup: &AgentRegistryLookup,
    ) -> Result<Option<AgentRegistryAgent>, AgentRegistryPortError> {
        Err(AgentRegistryPortError::Unavailable)
    }
}
