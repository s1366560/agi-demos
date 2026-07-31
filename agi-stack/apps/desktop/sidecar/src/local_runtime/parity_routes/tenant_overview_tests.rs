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
use super::tenant_overview::{is_new_this_week, PROJECT_MEMORY_REASON, PROJECT_OWNER_REASON};
use crate::local_runtime::auth_context::DesktopProject;

const ACTIVE_TENANT_ID: &str = "northstar";

struct TenantOverviewTestRuntime {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for TenantOverviewTestRuntime {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn test_runtime(launch_credential: &str) -> TenantOverviewTestRuntime {
    let root = std::env::temp_dir().join(format!("agistack-tenant-overview-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create tenant overview workspace");
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
    TenantOverviewTestRuntime { root, state }
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

async fn response_json(response: Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}

fn request(
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
        .expect("tenant overview request")
}

#[test]
fn tenant_overview_projects_do_not_fabricate_owner_or_memory_authority() {
    assert_eq!(
        PROJECT_OWNER_REASON,
        "local_project_owner_projection_unavailable"
    );
    assert_eq!(
        PROJECT_MEMORY_REASON,
        "local_project_memory_projection_unavailable"
    );
}

#[test]
fn tenant_overview_new_project_window_uses_structured_creation_time() {
    let recent = DesktopProject {
        id: "recent".to_string(),
        tenant_id: "tenant".to_string(),
        name: "Recent".to_string(),
        description: None,
        owner_id: "owner".to_string(),
        member_ids: vec!["owner".to_string()],
        memory_rules: serde_json::json!({}),
        graph_config: serde_json::json!({}),
        graph_store_id: None,
        retrieval_store_id: None,
        is_public: false,
        agent_conversation_mode: "shared".to_string(),
        created_at: chrono::Utc::now().to_rfc3339(),
        updated_at: None,
        stats: serde_json::json!({}),
    };
    let old = DesktopProject {
        created_at: (chrono::Utc::now() - chrono::Duration::days(8)).to_rfc3339(),
        ..recent.clone()
    };
    assert!(is_new_this_week(&&recent));
    assert!(!is_new_this_week(&&old));
}

#[tokio::test]
async fn tenant_overview_route_returns_degraded_local_authority() {
    let launch = "tenant-overview-launch";
    let runtime = test_runtime(launch);
    let app = local_router(Arc::clone(&runtime.state));
    let session = create_session(&app, launch).await;
    let uri = format!("/api/v1/tenants/{ACTIVE_TENANT_ID}/stats");

    let missing_launch = app
        .clone()
        .oneshot(request(&uri, None, Some(&session)))
        .await
        .expect("missing launch response");
    assert_eq!(missing_launch.status(), StatusCode::UNAUTHORIZED);

    let response = app
        .clone()
        .oneshot(request(&uri, Some(launch), Some(&session)))
        .await
        .expect("tenant overview response");
    assert_eq!(response.status(), StatusCode::OK);
    let payload = response_json(response).await;
    assert_eq!(payload["capability"], "tenant_overview");
    assert_eq!(payload["availability"], "degraded");
    assert_eq!(payload["scope"]["tenant_id"], ACTIVE_TENANT_ID);
    assert!(payload["projects"]["active"]
        .as_u64()
        .is_some_and(|active| active >= 1));
    assert_eq!(payload["members"]["total"], 1);
    assert_eq!(
        payload["storage"]["reason_code"],
        "local_tenant_memory_projection_unavailable"
    );
    assert_eq!(
        payload["projects"]["list"][0]["owner"]["reason_code"],
        "local_project_owner_projection_unavailable"
    );

    let invalid_query = app
        .oneshot(request(
            &format!("{uri}?unexpected=true"),
            Some(launch),
            Some(&session),
        ))
        .await
        .expect("invalid query response");
    assert_eq!(invalid_query.status(), StatusCode::UNPROCESSABLE_ENTITY);
}
