use std::{path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Request, StatusCode},
    response::Response,
    Router,
};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

const ACTIVE_TENANT_ID: &str = "northstar";
const ACTIVE_PROJECT_ID: &str = "desktop-client";
const ACTIVE_WORKSPACE_ID: &str = "local-demo-desktop-client-main";

struct WorkspaceRosterTestRuntime {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for WorkspaceRosterTestRuntime {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn test_runtime(launch_credential: &str) -> WorkspaceRosterTestRuntime {
    let root = std::env::temp_dir().join(format!("agistack-workspace-roster-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create workspace roster root");
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.clone(),
            tool_host,
            checkpoints,
            launch_credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    WorkspaceRosterTestRuntime { root, state }
}

async fn create_session(app: &Router, launch_credential: &str) -> String {
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/auth/local-session")
                .header("x-agistack-launch", launch_credential)
                .header("content-type", "application/json")
                .body(Body::from(r#"{"trusted_device":false}"#))
                .expect("create session request"),
        )
        .await
        .expect("create session response");
    assert_eq!(response.status(), StatusCode::OK);
    response_json(response).await["access_token"]
        .as_str()
        .expect("session access token")
        .to_string()
}

fn roster_request(
    uri: &str,
    launch_credential: Option<&str>,
    session_credential: Option<&str>,
) -> Request<Body> {
    let mut builder = Request::builder().uri(uri);
    if let Some(credential) = launch_credential {
        builder = builder.header("x-agistack-launch", credential);
    }
    if let Some(credential) = session_credential {
        builder = builder.header("authorization", format!("Bearer {credential}"));
    }
    builder
        .body(Body::empty())
        .expect("workspace roster request")
}

async fn response_json(response: Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}

fn roster_uri(resource: &str, query: &str) -> String {
    format!(
        "/api/v1/tenants/{ACTIVE_TENANT_ID}/projects/{ACTIVE_PROJECT_ID}/workspaces/{ACTIVE_WORKSPACE_ID}/{resource}?{query}"
    )
}

#[tokio::test]
async fn workspace_roster_requires_launch_capability_and_authenticated_session() {
    let launch_credential = "workspace-roster-auth-launch";
    let runtime = test_runtime(launch_credential);
    let app = local_router(Arc::clone(&runtime.state));
    let session_credential = create_session(&app, launch_credential).await;
    let uri = roster_uri("members", "limit=500&offset=0");

    let missing_launch = app
        .clone()
        .oneshot(roster_request(&uri, None, Some(&session_credential)))
        .await
        .expect("missing launch response");
    assert_eq!(missing_launch.status(), StatusCode::UNAUTHORIZED);

    let missing_session = app
        .oneshot(roster_request(&uri, Some(launch_credential), None))
        .await
        .expect("missing session response");
    assert_eq!(missing_session.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn workspace_member_roster_projects_the_local_owner_with_exact_scope() {
    let launch_credential = "workspace-member-roster-launch";
    let runtime = test_runtime(launch_credential);
    let app = local_router(Arc::clone(&runtime.state));
    let session_credential = create_session(&app, launch_credential).await;

    let response = app
        .oneshot(roster_request(
            &roster_uri("members", "limit=500&offset=0"),
            Some(launch_credential),
            Some(&session_credential),
        ))
        .await
        .expect("workspace members response");
    assert_eq!(response.status(), StatusCode::OK);
    let payload = response_json(response).await;
    let members = payload.as_array().expect("workspace member array");
    assert_eq!(members.len(), 1);
    assert_eq!(
        members[0]["id"],
        "local-membership:local-demo-desktop-client-main:local-user"
    );
    assert_eq!(members[0]["workspace_id"], ACTIVE_WORKSPACE_ID);
    assert_eq!(members[0]["user_id"], "local-user");
    assert_eq!(members[0]["role"], "owner");
    assert_eq!(members[0]["user_email"], "local@desktop");
}

#[tokio::test]
async fn workspace_agent_roster_returns_an_authoritative_empty_binding_page() {
    let launch_credential = "workspace-agent-roster-launch";
    let runtime = test_runtime(launch_credential);
    let app = local_router(Arc::clone(&runtime.state));
    let session_credential = create_session(&app, launch_credential).await;

    for active_only in ["false", "true"] {
        let response = app
            .clone()
            .oneshot(roster_request(
                &roster_uri(
                    "agents",
                    &format!("active_only={active_only}&limit=500&offset=0"),
                ),
                Some(launch_credential),
                Some(&session_credential),
            ))
            .await
            .expect("workspace agents response");
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response_json(response).await, Value::Array(Vec::new()));
    }
}

#[tokio::test]
async fn workspace_roster_rejects_scope_drift_and_unknown_workspaces() {
    let launch_credential = "workspace-roster-scope-launch";
    let runtime = test_runtime(launch_credential);
    let app = local_router(Arc::clone(&runtime.state));
    let session_credential = create_session(&app, launch_credential).await;

    for (uri, expected_status) in [
        (
            format!(
                "/api/v1/tenants/orbital/projects/{ACTIVE_PROJECT_ID}/workspaces/{ACTIVE_WORKSPACE_ID}/members?limit=500&offset=0"
            ),
            StatusCode::FORBIDDEN,
        ),
        (
            format!(
                "/api/v1/tenants/{ACTIVE_TENANT_ID}/projects/agent-evals/workspaces/{ACTIVE_WORKSPACE_ID}/members?limit=500&offset=0"
            ),
            StatusCode::FORBIDDEN,
        ),
        (
            format!(
                "/api/v1/tenants/{ACTIVE_TENANT_ID}/projects/{ACTIVE_PROJECT_ID}/workspaces/missing-workspace/members?limit=500&offset=0"
            ),
            StatusCode::NOT_FOUND,
        ),
    ] {
        let response = app
            .clone()
            .oneshot(roster_request(
                &uri,
                Some(launch_credential),
                Some(&session_credential),
            ))
            .await
            .expect("workspace roster scope response");
        assert_eq!(response.status(), expected_status);
    }
}

#[tokio::test]
async fn workspace_roster_rejects_invalid_pagination_and_agent_filters() {
    let launch_credential = "workspace-roster-query-launch";
    let runtime = test_runtime(launch_credential);
    let app = local_router(Arc::clone(&runtime.state));
    let session_credential = create_session(&app, launch_credential).await;

    for (resource, query) in [
        ("members", "limit=0&offset=0"),
        ("members", "limit=501&offset=0"),
        ("members", "limit=500&offset=-1"),
        ("members", "limit=500&offset=0&unknown=true"),
        ("agents", "active_only=maybe&limit=500&offset=0"),
    ] {
        let response = app
            .clone()
            .oneshot(roster_request(
                &roster_uri(resource, query),
                Some(launch_credential),
                Some(&session_credential),
            ))
            .await
            .expect("workspace roster query response");
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }
}
