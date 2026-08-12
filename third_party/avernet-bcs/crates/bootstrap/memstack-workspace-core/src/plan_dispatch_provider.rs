//! Authenticated HTTP adapter for structured Workspace Plan runtime dispatch.

use std::time::Duration;

use async_trait::async_trait;
use bcs_route_security::OutboundUrlGuard;
use memstack_workspace_service_api::{
    WorkspacePlanDispatchPort, WorkspacePlanDispatchPortError, WorkspacePlanDispatchReceipt,
    WorkspacePlanDispatchRequest,
};
use serde::{Deserialize, Serialize};

/// Fail-closed HTTP implementation of the Plan runtime Provider boundary.
pub struct HttpWorkspacePlanDispatchPort {
    client: reqwest::Client,
    dispatch_url: String,
    token: String,
}

impl HttpWorkspacePlanDispatchPort {
    /// Construct an authenticated client for one exact internal Provider URL.
    ///
    /// # Errors
    ///
    /// Returns an error for blank credentials, an invalid URL, a zero timeout,
    /// or HTTP client initialization failure.
    pub fn new(
        dispatch_url: impl Into<String>,
        token: impl Into<String>,
        timeout: Duration,
    ) -> Result<Self, &'static str> {
        let dispatch_url = dispatch_url.into();
        if dispatch_url.trim().is_empty() {
            return Err("Workspace Plan dispatch URL must not be blank");
        }
        OutboundUrlGuard::new(false, true)
            .validate_configured_http_url(&dispatch_url)
            .map_err(|_| "Workspace Plan dispatch URL is not allowed")?;
        let token = token.into();
        if token.trim().is_empty() {
            return Err("Workspace Plan dispatch token must not be blank");
        }
        if timeout.is_zero() {
            return Err("Workspace Plan dispatch timeout must be positive");
        }
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .map_err(|_| "Workspace Plan dispatch HTTP client initialization failed")?;
        Ok(Self {
            client,
            dispatch_url,
            token,
        })
    }
}

#[derive(Serialize)]
struct PlanDispatchBody<'a> {
    tenant_id: &'a str,
    project_id: &'a str,
    workspace_id: &'a str,
    plan_id: &'a str,
    plan_node_id: Option<&'a str>,
    task_id: Option<&'a str>,
    attempt_id: Option<&'a str>,
    agent_id: Option<&'a str>,
    action: &'a str,
    outbox_id: &'a str,
    correlation_id: &'a str,
    conversation_id: &'a str,
    payload: &'a serde_json::Value,
}

impl<'a> From<&'a WorkspacePlanDispatchRequest> for PlanDispatchBody<'a> {
    fn from(request: &'a WorkspacePlanDispatchRequest) -> Self {
        Self {
            tenant_id: request.tenant_id(),
            project_id: request.project_id(),
            workspace_id: request.workspace_id(),
            plan_id: request.plan_id(),
            plan_node_id: request.plan_node_id(),
            task_id: request.task_id(),
            attempt_id: request.attempt_id(),
            agent_id: request.agent_id(),
            action: request.action().as_str(),
            outbox_id: request.outbox_id(),
            correlation_id: request.correlation_id(),
            conversation_id: request.conversation_id(),
            payload: request.payload(),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PlanDispatchResponse {
    accepted: bool,
    provider_id: String,
    provider_bot_ref: String,
    provider_run_id: String,
}

#[async_trait]
impl WorkspacePlanDispatchPort for HttpWorkspacePlanDispatchPort {
    async fn dispatch(
        &self,
        request: &WorkspacePlanDispatchRequest,
    ) -> Result<WorkspacePlanDispatchReceipt, WorkspacePlanDispatchPortError> {
        let response = self
            .client
            .post(&self.dispatch_url)
            .bearer_auth(&self.token)
            .json(&PlanDispatchBody::from(request))
            .send()
            .await
            .map_err(|_| WorkspacePlanDispatchPortError::Unavailable)?;
        if response.status().is_client_error() {
            return Err(WorkspacePlanDispatchPortError::Rejected);
        }
        if !response.status().is_success() {
            return Err(WorkspacePlanDispatchPortError::Unavailable);
        }
        let response = response
            .json::<PlanDispatchResponse>()
            .await
            .map_err(|_| WorkspacePlanDispatchPortError::Unavailable)?;
        if !response.accepted {
            return Err(WorkspacePlanDispatchPortError::Rejected);
        }
        WorkspacePlanDispatchReceipt::new(
            response.provider_id,
            response.provider_bot_ref,
            response.provider_run_id,
        )
        .map_err(|_| WorkspacePlanDispatchPortError::Unavailable)
    }
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use axum::Json;
    use axum::Router;
    use axum::http::StatusCode;
    use axum::routing::post;
    use serde_json::{Value, json};

    use super::*;
    use memstack_workspace_service_api::WorkspacePlanDispatchAction;

    fn request() -> Result<WorkspacePlanDispatchRequest, Box<dyn Error>> {
        Ok(WorkspacePlanDispatchRequest::new(
            "tenant-1".to_string(),
            "project-1".to_string(),
            "workspace-1".to_string(),
            "plan-1".to_string(),
            Some("node-1".to_string()),
            Some("task-1".to_string()),
            Some("attempt-1".to_string()),
            Some("agent-1".to_string()),
            WorkspacePlanDispatchAction::RunPipeline,
            "outbox-1".to_string(),
            "correlation-1".to_string(),
            "conversation-1".to_string(),
            json!({"reason": "contract"}),
        )?)
    }

    async fn serve(router: Router) -> Result<String, Box<dyn Error>> {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
        let address = listener.local_addr()?;
        tokio::spawn(async move {
            let _ = axum::serve(listener, router).await;
        });
        Ok(format!("http://{address}/dispatch"))
    }

    #[tokio::test]
    async fn accepted_response_returns_a_validated_provider_receipt() -> Result<(), Box<dyn Error>>
    {
        async fn handler(Json(body): Json<Value>) -> Json<Value> {
            assert_eq!(body["action"], "run_pipeline");
            assert_eq!(body["outbox_id"], "outbox-1");
            assert_eq!(body["payload"]["reason"], "contract");
            Json(json!({
                "accepted": true,
                "provider_id": "memstack-agent-runtime",
                "provider_bot_ref": "agent-1",
                "provider_run_id": "provider-run-1"
            }))
        }
        let url = serve(Router::new().route("/dispatch", post(handler))).await?;
        let port = HttpWorkspacePlanDispatchPort::new(url, "token-1", Duration::from_secs(1))?;

        let receipt = port.dispatch(&request()?).await?;

        assert_eq!(receipt.provider_id(), "memstack-agent-runtime");
        assert_eq!(receipt.provider_bot_ref(), "agent-1");
        assert_eq!(receipt.provider_run_id(), "provider-run-1");
        Ok(())
    }

    #[tokio::test]
    async fn client_rejection_and_server_failure_remain_distinct() -> Result<(), Box<dyn Error>> {
        async fn rejected() -> StatusCode {
            StatusCode::CONFLICT
        }
        async fn unavailable() -> StatusCode {
            StatusCode::SERVICE_UNAVAILABLE
        }
        let rejected_url = serve(Router::new().route("/dispatch", post(rejected))).await?;
        let unavailable_url = serve(Router::new().route("/dispatch", post(unavailable))).await?;
        let rejected_port =
            HttpWorkspacePlanDispatchPort::new(rejected_url, "token-1", Duration::from_secs(1))?;
        let unavailable_port =
            HttpWorkspacePlanDispatchPort::new(unavailable_url, "token-1", Duration::from_secs(1))?;

        assert_eq!(
            rejected_port.dispatch(&request()?).await,
            Err(WorkspacePlanDispatchPortError::Rejected)
        );
        assert_eq!(
            unavailable_port.dispatch(&request()?).await,
            Err(WorkspacePlanDispatchPortError::Unavailable)
        );
        Ok(())
    }
}
