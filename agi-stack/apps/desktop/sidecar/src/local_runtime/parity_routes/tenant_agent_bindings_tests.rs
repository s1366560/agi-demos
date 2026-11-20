use std::{path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Request, StatusCode},
    response::Response,
};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

const ACTIVE_TENANT_ID: &str = "northstar";

struct AgentBindingsTestRuntime {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for AgentBindingsTestRuntime {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn test_runtime(launch_credential: &str) -> AgentBindingsTestRuntime {
    let root =
        std::env::temp_dir().join(format!("agistack-tenant-agent-bindings-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create agent bindings workspace");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.clone(),
            LocalToolHost::new(&root).expect("tool host"),
            Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints")),
            launch_credential.to_string(),
            DesktopSessionStore::in_memory().expect("session store"),
        )
        .expect("local runtime state"),
    );
    AgentBindingsTestRuntime { root, state }
}

fn create_session(state: &super::super::LocalRuntimeState) -> String {
    state
        .session_store
        .create_local_session(
            format!("parity-session-{}", uuid::Uuid::new_v4()),
            false,
            chrono::Utc::now().timestamp_millis(),
        )
        .expect("create session")
        .access_token
}

async fn response_json(response: Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}

fn request(
    method: &str,
    uri: &str,
    launch_credential: Option<&str>,
    session_credential: Option<&str>,
    body: &str,
) -> Request<Body> {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header("content-type", "application/json");
    if let Some(credential) = launch_credential {
        builder = builder.header("x-agistack-launch", credential);
    }
    if let Some(credential) = session_credential {
        builder = builder.header("authorization", format!("Bearer {credential}"));
    }
    builder
        .body(Body::from(body.to_string()))
        .expect("agent bindings request")
}

#[tokio::test]
async fn tenant_agent_bindings_read_is_authenticated_scoped_and_structured() {
    let launch = "tenant-agent-bindings-launch";
    let runtime = test_runtime(launch);
    let app = local_router(Arc::clone(&runtime.state));
    let session = create_session(&runtime.state);
    let uri = format!("/api/v1/agent/bindings?tenant_id={ACTIVE_TENANT_ID}");

    let missing_launch = app
        .clone()
        .oneshot(request("GET", &uri, None, Some(&session), ""))
        .await
        .expect("missing launch response");
    assert_eq!(missing_launch.status(), StatusCode::UNAUTHORIZED);

    let wrong_scope = app
        .clone()
        .oneshot(request(
            "GET",
            "/api/v1/agent/bindings?tenant_id=another-tenant",
            Some(launch),
            Some(&session),
            "",
        ))
        .await
        .expect("wrong scope response");
    assert_eq!(wrong_scope.status(), StatusCode::FORBIDDEN);

    let response = app
        .oneshot(request("GET", &uri, Some(launch), Some(&session), ""))
        .await
        .expect("agent bindings response");
    assert_eq!(response.status(), StatusCode::OK);
    let payload = response_json(response).await;
    assert_eq!(payload["capability"], "tenant_agent_bindings");
    assert_eq!(payload["availability"], "unavailable");
    assert_eq!(
        payload["reason_code"],
        "local_agent_binding_routing_authority_unavailable"
    );
    assert_eq!(payload["contract_version"], "3.0.0");
    assert_eq!(payload["scope"]["tenant_id"], ACTIVE_TENANT_ID);
    assert_eq!(payload["allowed_actions"], serde_json::json!([]));
    assert_eq!(payload["bindings"], serde_json::json!([]));
    assert_eq!(payload["definitions"], serde_json::json!([]));
    assert!(payload["authority_revision"].as_u64().is_some());
}

#[tokio::test]
async fn tenant_agent_binding_mutations_and_resolution_test_fail_closed() {
    let launch = "tenant-agent-bindings-mutation-launch";
    let runtime = test_runtime(launch);
    let app = local_router(Arc::clone(&runtime.state));
    let session = create_session(&runtime.state);
    let cases = [
        (
            "POST",
            format!("/api/v1/agent/bindings?tenant_id={ACTIVE_TENANT_ID}"),
            r#"{"agent_id":"agent-1","channel_type":"slack"}"#,
        ),
        (
            "DELETE",
            format!("/api/v1/agent/bindings/binding-1?tenant_id={ACTIVE_TENANT_ID}"),
            "",
        ),
        (
            "PATCH",
            format!("/api/v1/agent/bindings/binding-1/enabled?tenant_id={ACTIVE_TENANT_ID}"),
            r#"{"enabled":false}"#,
        ),
        (
            "POST",
            format!("/api/v1/agent/bindings/test?tenant_id={ACTIVE_TENANT_ID}"),
            r#"{"channel_type":"slack"}"#,
        ),
    ];

    for (method, uri, body) in cases {
        let response = app
            .clone()
            .oneshot(request(method, &uri, Some(launch), Some(&session), body))
            .await
            .expect("agent binding unavailable response");
        assert_eq!(response.status(), StatusCode::NOT_IMPLEMENTED);
        let payload = response_json(response).await;
        assert_eq!(payload["capability"], "tenant_agent_bindings");
        assert_eq!(payload["availability"], "unavailable");
        assert_eq!(
            payload["reason_code"],
            "local_agent_binding_routing_authority_unavailable"
        );
    }
}
