//! Authenticated HTTP adapter for Agent-first Workspace Plan judgments.

use std::time::Duration;

use async_trait::async_trait;
use bcs_route_security::OutboundUrlGuard;
use memstack_workspace_service_api::{
    WorkspacePlanJudgePort, WorkspacePlanJudgePortError, WorkspacePlanJudgment,
    WorkspacePlanJudgmentRequest,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

const JUDGE_PATH: &str = "/internal/v1/workspace-core/plan-judge";
const JUDGE_TOOL_NAME: &str = "judge_workspace_plan";

/// Invalid external Plan Judge client configuration.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum HttpWorkspacePlanJudgeConfigError {
    #[error("Workspace Plan Judge base URL must not be blank")]
    BlankBaseUrl,

    #[error("Workspace Plan Judge token must not be blank")]
    BlankToken,

    #[error("Workspace Plan Judge URL is not allowed")]
    InvalidUrl,

    #[error("Workspace Plan Judge timeout must be positive")]
    ZeroTimeout,

    #[error("Workspace Plan Judge HTTP client initialization failed: {0}")]
    Client(#[source] reqwest::Error),
}

/// Fail-closed HTTP implementation of [`WorkspacePlanJudgePort`].
pub struct HttpWorkspacePlanJudgePort {
    client: reqwest::Client,
    judge_url: String,
    token: String,
}

impl HttpWorkspacePlanJudgePort {
    /// Construct a client without exposing its bearer token through `Debug`.
    ///
    /// # Errors
    ///
    /// Returns [`HttpWorkspacePlanJudgeConfigError`] for invalid configuration.
    pub fn new(
        base_url: impl Into<String>,
        token: impl Into<String>,
        timeout: Duration,
    ) -> Result<Self, HttpWorkspacePlanJudgeConfigError> {
        let base_url = base_url.into();
        if base_url.trim().is_empty() {
            return Err(HttpWorkspacePlanJudgeConfigError::BlankBaseUrl);
        }
        let token = token.into();
        if token.trim().is_empty() {
            return Err(HttpWorkspacePlanJudgeConfigError::BlankToken);
        }
        if timeout.is_zero() {
            return Err(HttpWorkspacePlanJudgeConfigError::ZeroTimeout);
        }
        let judge_url = format!("{}{}", base_url.trim_end_matches('/'), JUDGE_PATH);
        OutboundUrlGuard::new(false, true)
            .validate_configured_http_url(&judge_url)
            .map_err(|_| HttpWorkspacePlanJudgeConfigError::InvalidUrl)?;
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .map_err(HttpWorkspacePlanJudgeConfigError::Client)?;
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
    plan_id: &'a str,
    plan_revision: u64,
    kind: &'static str,
    candidate_node_ids: &'a [String],
    evidence: &'a Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct JudgeResponse {
    proceed: bool,
    selected_node_id: Option<String>,
    rationale: String,
    agent_id: String,
    tool_name: String,
    input_json: Value,
    output_json: Value,
    latency_ms: u64,
}

impl<'a> From<&'a WorkspacePlanJudgmentRequest> for JudgeRequest<'a> {
    fn from(request: &'a WorkspacePlanJudgmentRequest) -> Self {
        Self {
            tenant_id: request.tenant_id(),
            project_id: request.project_id(),
            workspace_id: request.workspace_id(),
            actor_id: request.actor_id(),
            plan_id: request.plan_id(),
            plan_revision: request.plan_revision(),
            kind: request.kind().as_str(),
            candidate_node_ids: request.candidate_node_ids(),
            evidence: request.evidence(),
        }
    }
}

fn judgment_from_response(
    request: &WorkspacePlanJudgmentRequest,
    response: JudgeResponse,
) -> Result<WorkspacePlanJudgment, WorkspacePlanJudgePortError> {
    if response.tool_name != JUDGE_TOOL_NAME {
        return Err(WorkspacePlanJudgePortError::Unavailable);
    }
    WorkspacePlanJudgment::new(
        request,
        response.proceed,
        response.selected_node_id,
        response.rationale,
        response.agent_id,
        response.tool_name,
        response.input_json,
        response.output_json,
        response.latency_ms,
    )
    .map_err(|_| WorkspacePlanJudgePortError::Unavailable)
}

#[async_trait]
impl WorkspacePlanJudgePort for HttpWorkspacePlanJudgePort {
    async fn judge(
        &self,
        request: &WorkspacePlanJudgmentRequest,
    ) -> Result<WorkspacePlanJudgment, WorkspacePlanJudgePortError> {
        let response = self
            .client
            .post(&self.judge_url)
            .bearer_auth(&self.token)
            .json(&JudgeRequest::from(request))
            .send()
            .await
            .map_err(|_| WorkspacePlanJudgePortError::Unavailable)?;
        if !response.status().is_success() {
            return Err(WorkspacePlanJudgePortError::Unavailable);
        }
        let response = response
            .json::<JudgeResponse>()
            .await
            .map_err(|_| WorkspacePlanJudgePortError::Unavailable)?;
        judgment_from_response(request, response)
    }
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use axum::http::HeaderMap;
    use axum::routing::post;
    use axum::{Json, Router};
    use memstack_workspace_service_api::WorkspacePlanJudgmentKind;
    use serde_json::{Value, json};

    use super::*;

    fn request() -> Result<WorkspacePlanJudgmentRequest, Box<dyn Error>> {
        Ok(WorkspacePlanJudgmentRequest::new(
            "tenant-1".to_string(),
            "project-1".to_string(),
            "workspace-1".to_string(),
            "user-1".to_string(),
            "plan-1".to_string(),
            7,
            WorkspacePlanJudgmentKind::SelectPipelineTarget,
            vec!["node-1".to_string(), "node-2".to_string()],
            json!({"eligible_nodes": ["node-1", "node-2"]}),
        )?)
    }

    async fn serve(router: Router) -> Result<String, Box<dyn Error>> {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
        let address = listener.local_addr()?;
        tokio::spawn(async move {
            let _ = axum::serve(listener, router).await;
        });
        Ok(format!("http://{address}"))
    }

    #[tokio::test]
    async fn structured_response_returns_an_auditable_judgment() -> Result<(), Box<dyn Error>> {
        async fn handler(headers: HeaderMap, Json(body): Json<Value>) -> Json<Value> {
            assert_eq!(headers["authorization"], "Bearer registry-token");
            assert_eq!(body["kind"], "select_pipeline_target");
            assert_eq!(body["candidate_node_ids"], json!(["node-1", "node-2"]));
            Json(json!({
                "proceed": true,
                "selected_node_id": "node-2",
                "rationale": "node-2 satisfies the supplied evidence",
                "agent_id": "judge-agent",
                "tool_name": "judge_workspace_plan",
                "input_json": body,
                "output_json": {"selected_node_id": "node-2"},
                "latency_ms": 9
            }))
        }
        let url = serve(Router::new().route(JUDGE_PATH, post(handler))).await?;
        let port = HttpWorkspacePlanJudgePort::new(url, "registry-token", Duration::from_secs(1))?;

        let judgment = port.judge(&request()?).await?;

        assert!(judgment.proceed());
        assert_eq!(judgment.selected_node_id(), Some("node-2"));
        assert_eq!(judgment.agent_id(), "judge-agent");
        assert_eq!(judgment.tool_name(), JUDGE_TOOL_NAME);
        Ok(())
    }

    #[tokio::test]
    async fn selection_outside_candidates_fails_closed() -> Result<(), Box<dyn Error>> {
        async fn handler() -> Json<Value> {
            Json(json!({
                "proceed": true,
                "selected_node_id": "outside-node",
                "rationale": "invalid external selection",
                "agent_id": "judge-agent",
                "tool_name": "judge_workspace_plan",
                "input_json": {},
                "output_json": {"selected_node_id": "outside-node"},
                "latency_ms": 2
            }))
        }
        let url = serve(Router::new().route(JUDGE_PATH, post(handler))).await?;
        let port = HttpWorkspacePlanJudgePort::new(url, "registry-token", Duration::from_secs(1))?;

        assert_eq!(
            port.judge(&request()?).await,
            Err(WorkspacePlanJudgePortError::Unavailable)
        );
        Ok(())
    }
}
