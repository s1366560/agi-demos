//! Fail-closed Workspace ACL adapter backed only by Avernet Workspace Core.

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

const AUTHORITY_QUERY_PATH: &str = "/internal/v1/workspace-authority/query";

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct WorkspaceAuthorityScope {
    pub(crate) tenant_id: String,
    pub(crate) project_id: String,
    pub(crate) workspace_id: String,
    pub(crate) is_archived: bool,
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum WorkspaceAuthorityError {
    #[error("Workspace Core is unavailable")]
    Unavailable,
}

#[async_trait]
pub(crate) trait WorkspaceAuthority: Send + Sync {
    async fn authorize(
        &self,
        user_id: &str,
        workspace_id: &str,
    ) -> Result<Option<WorkspaceAuthorityScope>, WorkspaceAuthorityError>;
}

pub(crate) type SharedWorkspaceAuthority = Arc<dyn WorkspaceAuthority>;

pub(crate) struct CoreWorkspaceAuthority {
    base_url: String,
    service_token: String,
    client: reqwest::Client,
}

impl CoreWorkspaceAuthority {
    pub(crate) fn from_env() -> Result<Self, WorkspaceAuthorityError> {
        let base_url = required_env("WORKSPACE_CORE_BASE_URL")?;
        let service_token = required_env("WORKSPACE_CORE_SERVICE_TOKEN")?;
        let timeout = std::env::var("WORKSPACE_CORE_REQUEST_TIMEOUT_SECONDS")
            .ok()
            .and_then(|value| value.parse::<f64>().ok())
            .filter(|value| value.is_finite() && *value > 0.0 && *value <= 60.0)
            .unwrap_or(5.0);
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs_f64(timeout))
            .build()
            .map_err(|_| WorkspaceAuthorityError::Unavailable)?;
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            service_token,
            client,
        })
    }
}

#[async_trait]
impl WorkspaceAuthority for CoreWorkspaceAuthority {
    async fn authorize(
        &self,
        user_id: &str,
        workspace_id: &str,
    ) -> Result<Option<WorkspaceAuthorityScope>, WorkspaceAuthorityError> {
        let response = self
            .client
            .post(format!("{}{}", self.base_url, AUTHORITY_QUERY_PATH))
            .bearer_auth(&self.service_token)
            .json(&AuthorityQueryRequest {
                actor: AuthorityActor { user_id },
                workspace_ids: [workspace_id],
            })
            .send()
            .await
            .map_err(|_| WorkspaceAuthorityError::Unavailable)?;
        if !response.status().is_success() {
            return Err(WorkspaceAuthorityError::Unavailable);
        }
        let response = response
            .json::<AuthorityQueryResponse>()
            .await
            .map_err(|_| WorkspaceAuthorityError::Unavailable)?;
        let Some(profile) = response.profiles.into_iter().next() else {
            return Ok(None);
        };
        if profile.workspace_id != workspace_id {
            return Err(WorkspaceAuthorityError::Unavailable);
        }
        Ok(Some(WorkspaceAuthorityScope {
            tenant_id: profile.tenant_id,
            project_id: profile.project_id,
            workspace_id: profile.workspace_id,
            is_archived: profile.is_archived,
        }))
    }
}

#[derive(Serialize)]
struct AuthorityQueryRequest<'a> {
    actor: AuthorityActor<'a>,
    workspace_ids: [&'a str; 1],
}

#[derive(Serialize)]
struct AuthorityActor<'a> {
    user_id: &'a str,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthorityQueryResponse {
    profiles: Vec<AuthorityProfile>,
}

#[derive(Deserialize)]
struct AuthorityProfile {
    workspace_id: String,
    tenant_id: String,
    project_id: String,
    is_archived: bool,
}

fn required_env(name: &'static str) -> Result<String, WorkspaceAuthorityError> {
    std::env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .ok_or(WorkspaceAuthorityError::Unavailable)
}

#[cfg(test)]
pub(crate) struct UnavailableWorkspaceAuthority;

#[cfg(test)]
#[async_trait]
impl WorkspaceAuthority for UnavailableWorkspaceAuthority {
    async fn authorize(
        &self,
        _user_id: &str,
        _workspace_id: &str,
    ) -> Result<Option<WorkspaceAuthorityScope>, WorkspaceAuthorityError> {
        Err(WorkspaceAuthorityError::Unavailable)
    }
}
