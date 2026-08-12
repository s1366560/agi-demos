//! Authenticated HTTP adapter for the external Agent-first Workspace Context judge.

use std::time::Duration;

use async_trait::async_trait;
use memstack_workspace_service_api::{
    WorkspaceContextCandidate, WorkspaceContextJudgePort, WorkspaceContextJudgePortError,
    WorkspaceContextJudgment, WorkspaceContextJudgmentRequest,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

const JUDGE_PATH: &str = "/internal/v1/workspace-core/context-judge";

/// Invalid external Context Judge client configuration.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum HttpWorkspaceContextJudgeConfigError {
    #[error("Workspace Context Judge base URL must not be blank")]
    BlankBaseUrl,

    #[error("Workspace Context Judge token must not be blank")]
    BlankToken,

    #[error("Workspace Context Judge HTTP client initialization failed: {0}")]
    Client(#[source] reqwest::Error),
}

/// Fail-closed HTTP implementation of [`WorkspaceContextJudgePort`].
pub struct HttpWorkspaceContextJudgePort {
    client: reqwest::Client,
    judge_url: String,
    token: String,
}

impl HttpWorkspaceContextJudgePort {
    /// Construct a client without exposing its bearer token through `Debug`.
    ///
    /// # Errors
    ///
    /// Returns [`HttpWorkspaceContextJudgeConfigError`] for blank credentials
    /// or an invalid HTTP client configuration.
    pub fn new(
        base_url: impl Into<String>,
        token: impl Into<String>,
        timeout: Duration,
    ) -> Result<Self, HttpWorkspaceContextJudgeConfigError> {
        let base_url = base_url.into();
        if base_url.trim().is_empty() {
            return Err(HttpWorkspaceContextJudgeConfigError::BlankBaseUrl);
        }
        let token = token.into();
        if token.trim().is_empty() {
            return Err(HttpWorkspaceContextJudgeConfigError::BlankToken);
        }
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .map_err(HttpWorkspaceContextJudgeConfigError::Client)?;
        Ok(Self {
            client,
            judge_url: format!("{}{}", base_url.trim_end_matches('/'), JUDGE_PATH),
            token,
        })
    }
}

#[derive(Debug, Serialize)]
struct JudgeRequest<'a> {
    user_id: &'a str,
    current: Option<CurrentRequest<'a>>,
    candidates: Vec<CandidateRequest<'a>>,
}

#[derive(Debug, Serialize)]
struct CurrentRequest<'a> {
    tenant_id: &'a str,
    project_id: &'a str,
    revision: u64,
}

#[derive(Debug, Serialize)]
struct CandidateRequest<'a> {
    tenant_id: &'a str,
    project_id: &'a str,
    membership_role: &'a str,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct JudgeResponse {
    selected: CandidateResponse,
    rationale: String,
    evidence: Vec<String>,
    agent_id: String,
    tool_name: String,
    input_json: Value,
    output_json: Value,
    latency_ms: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CandidateResponse {
    tenant_id: String,
    project_id: String,
    membership_role: String,
}

impl JudgeRequest<'_> {
    fn from_contract(request: &WorkspaceContextJudgmentRequest) -> JudgeRequest<'_> {
        JudgeRequest {
            user_id: request.user_id().as_str(),
            current: request.current().map(|current| CurrentRequest {
                tenant_id: current.tenant_id().as_str(),
                project_id: current.project_id().as_str(),
                revision: current.revision(),
            }),
            candidates: request
                .candidates()
                .iter()
                .map(|candidate| CandidateRequest {
                    tenant_id: candidate.tenant_id().as_str(),
                    project_id: candidate.project_id().as_str(),
                    membership_role: candidate.membership_role().as_str(),
                })
                .collect(),
        }
    }
}

fn judgment_from_response(
    request: &WorkspaceContextJudgmentRequest,
    response: JudgeResponse,
) -> Result<WorkspaceContextJudgment, WorkspaceContextJudgePortError> {
    let selected = WorkspaceContextCandidate::parse(
        response.selected.tenant_id,
        response.selected.project_id,
        response.selected.membership_role,
    )
    .map_err(|_| WorkspaceContextJudgePortError::Unavailable)?;
    let selected_index = request
        .candidates()
        .iter()
        .position(|candidate| candidate == &selected)
        .ok_or(WorkspaceContextJudgePortError::Unavailable)?;
    WorkspaceContextJudgment::new(
        request,
        selected_index,
        selected,
        response.rationale,
        response.evidence,
        response.agent_id,
        response.tool_name,
        response.input_json,
        response.output_json,
        response.latency_ms,
    )
    .map_err(|_| WorkspaceContextJudgePortError::Unavailable)
}

#[async_trait]
impl WorkspaceContextJudgePort for HttpWorkspaceContextJudgePort {
    async fn select(
        &self,
        request: &WorkspaceContextJudgmentRequest,
    ) -> Result<WorkspaceContextJudgment, WorkspaceContextJudgePortError> {
        let response = self
            .client
            .post(&self.judge_url)
            .bearer_auth(&self.token)
            .json(&JudgeRequest::from_contract(request))
            .send()
            .await
            .map_err(|_| WorkspaceContextJudgePortError::Unavailable)?;
        if !response.status().is_success() {
            return Err(WorkspaceContextJudgePortError::Unavailable);
        }
        let response = response
            .json::<JudgeResponse>()
            .await
            .map_err(|_| WorkspaceContextJudgePortError::Unavailable)?;
        judgment_from_response(request, response)
    }
}

/// Default dependency used until the authenticated Agent judge is configured.
pub(crate) struct UnavailableWorkspaceContextJudgePort;

#[async_trait]
impl WorkspaceContextJudgePort for UnavailableWorkspaceContextJudgePort {
    async fn select(
        &self,
        _request: &WorkspaceContextJudgmentRequest,
    ) -> Result<WorkspaceContextJudgment, WorkspaceContextJudgePortError> {
        Err(WorkspaceContextJudgePortError::Unavailable)
    }
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use memstack_workspace_service_api::UserId;
    use serde_json::json;

    use super::*;

    fn request() -> Result<WorkspaceContextJudgmentRequest, Box<dyn Error>> {
        Ok(WorkspaceContextJudgmentRequest::new(
            UserId::parse("user-1")?,
            None,
            vec![
                WorkspaceContextCandidate::parse("tenant-1", "project-1", "member")?,
                WorkspaceContextCandidate::parse("tenant-2", "project-2", "owner")?,
            ],
        )?)
    }

    #[test]
    fn response_selection_must_exactly_match_a_supplied_candidate() -> Result<(), Box<dyn Error>> {
        let result = judgment_from_response(
            &request()?,
            JudgeResponse {
                selected: CandidateResponse {
                    tenant_id: "tenant-3".to_string(),
                    project_id: "project-3".to_string(),
                    membership_role: "owner".to_string(),
                },
                rationale: "outside selection".to_string(),
                evidence: Vec::new(),
                agent_id: "judge-agent".to_string(),
                tool_name: "select_workspace_context".to_string(),
                input_json: json!({}),
                output_json: json!({"candidate_index": 7}),
                latency_ms: 2,
            },
        );

        assert_eq!(result, Err(WorkspaceContextJudgePortError::Unavailable));
        Ok(())
    }
}
