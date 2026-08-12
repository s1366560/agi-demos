//! Authenticated HTTP adapter for Agent-first Workspace Autonomy judgments.

use std::time::Duration;

use async_trait::async_trait;
use bcs_route_security::OutboundUrlGuard;
use memstack_workspace_service::{
    PublicWorkspaceAutonomyJudgePort, PublicWorkspaceAutonomyJudgePortError,
    PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgmentRequest,
    PublicWorkspaceAutonomyVerdictKind,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

const JUDGE_PATH: &str = "/internal/v1/workspace-core/autonomy-judge";
const JUDGE_TOOL_NAME: &str = "judge_workspace_autonomy";

/// Invalid external Autonomy Judge client configuration.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum HttpWorkspaceAutonomyJudgeConfigError {
    #[error("Workspace Autonomy Judge base URL must not be blank")]
    BlankBaseUrl,
    #[error("Workspace Autonomy Judge token must not be blank")]
    BlankToken,
    #[error("Workspace Autonomy Judge URL is not allowed")]
    InvalidUrl,
    #[error("Workspace Autonomy Judge timeout must be positive")]
    ZeroTimeout,
    #[error("Workspace Autonomy Judge HTTP client initialization failed: {0}")]
    Client(#[source] reqwest::Error),
}

/// Fail-closed HTTP implementation of [`PublicWorkspaceAutonomyJudgePort`].
pub struct HttpWorkspaceAutonomyJudgePort {
    client: reqwest::Client,
    judge_url: String,
    token: String,
}

impl HttpWorkspaceAutonomyJudgePort {
    /// Construct a client without exposing its bearer token through `Debug`.
    ///
    /// # Errors
    ///
    /// Returns [`HttpWorkspaceAutonomyJudgeConfigError`] for invalid configuration.
    pub fn new(
        base_url: impl Into<String>,
        token: impl Into<String>,
        timeout: Duration,
    ) -> Result<Self, HttpWorkspaceAutonomyJudgeConfigError> {
        let base_url = base_url.into();
        if base_url.trim().is_empty() {
            return Err(HttpWorkspaceAutonomyJudgeConfigError::BlankBaseUrl);
        }
        let token = token.into();
        if token.trim().is_empty() {
            return Err(HttpWorkspaceAutonomyJudgeConfigError::BlankToken);
        }
        if timeout.is_zero() {
            return Err(HttpWorkspaceAutonomyJudgeConfigError::ZeroTimeout);
        }
        let judge_url = format!("{}{}", base_url.trim_end_matches('/'), JUDGE_PATH);
        OutboundUrlGuard::new(false, true)
            .validate_configured_http_url(&judge_url)
            .map_err(|_| HttpWorkspaceAutonomyJudgeConfigError::InvalidUrl)?;
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .map_err(HttpWorkspaceAutonomyJudgeConfigError::Client)?;
        Ok(Self {
            client,
            judge_url,
            token,
        })
    }
}

#[derive(Debug, Serialize)]
struct JudgeRequest<'a> {
    tenant_id: &'a str,
    project_id: &'a str,
    workspace_id: &'a str,
    actor_id: &'a str,
    workspace_revision: u64,
    force: bool,
    candidates: Vec<CandidateRequest<'a>>,
}

#[derive(Debug, Serialize)]
struct CandidateRequest<'a> {
    root_task_id: &'a str,
    title: &'a str,
    description: Option<&'a str>,
    status: &'a str,
    metadata: &'a Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct JudgeResponse {
    verdict: PublicWorkspaceAutonomyVerdictKind,
    selected_root_task_id: Option<String>,
    rationale: String,
    agent_id: String,
    tool_name: String,
    input_json: Value,
    output_json: Value,
    latency_ms: u64,
}

impl<'a> From<&'a PublicWorkspaceAutonomyJudgmentRequest> for JudgeRequest<'a> {
    fn from(request: &'a PublicWorkspaceAutonomyJudgmentRequest) -> Self {
        let context = request.context();
        Self {
            tenant_id: context.tenant_id.as_str(),
            project_id: context.project_id.as_str(),
            workspace_id: context.workspace_id.as_str(),
            actor_id: context.user_id.as_str(),
            workspace_revision: request.workspace_revision(),
            force: request.force(),
            candidates: request
                .candidates()
                .iter()
                .map(|candidate| CandidateRequest {
                    root_task_id: candidate.root_task_id.as_str(),
                    title: candidate.title.as_str(),
                    description: candidate.description.as_deref(),
                    status: candidate.status.as_str(),
                    metadata: &candidate.metadata,
                })
                .collect(),
        }
    }
}

fn judgment_from_response(
    request: &PublicWorkspaceAutonomyJudgmentRequest,
    response: JudgeResponse,
) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
    if response.tool_name != JUDGE_TOOL_NAME {
        return Err(PublicWorkspaceAutonomyJudgePortError::Unavailable);
    }
    PublicWorkspaceAutonomyJudgment::new(
        request,
        response.verdict,
        response.selected_root_task_id,
        response.rationale,
        response.agent_id,
        response.tool_name,
        response.input_json,
        response.output_json,
        response.latency_ms,
    )
    .map_err(|_| PublicWorkspaceAutonomyJudgePortError::Unavailable)
}

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for HttpWorkspaceAutonomyJudgePort {
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        let response = self
            .client
            .post(&self.judge_url)
            .bearer_auth(&self.token)
            .json(&JudgeRequest::from(request))
            .send()
            .await
            .map_err(|_| PublicWorkspaceAutonomyJudgePortError::Unavailable)?;
        if !response.status().is_success() {
            return Err(PublicWorkspaceAutonomyJudgePortError::Unavailable);
        }
        let response = response
            .json::<JudgeResponse>()
            .await
            .map_err(|_| PublicWorkspaceAutonomyJudgePortError::Unavailable)?;
        judgment_from_response(request, response)
    }
}

/// Default dependency used until an authenticated Agent judge is configured.
pub(crate) struct UnavailableWorkspaceAutonomyJudgePort;

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for UnavailableWorkspaceAutonomyJudgePort {
    async fn judge(
        &self,
        _request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        Err(PublicWorkspaceAutonomyJudgePortError::Unavailable)
    }
}
