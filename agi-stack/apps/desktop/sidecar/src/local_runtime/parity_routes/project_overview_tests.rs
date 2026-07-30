use std::{collections::BTreeSet, path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Request, StatusCode},
    response::Response,
    Router,
};
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

const ACTIVE_TENANT_ID: &str = "northstar";
const ACTIVE_PROJECT_ID: &str = "desktop-client";
const LEGACY_TENANT_ID: &str = "local";
const LEGACY_PROJECT_ID: &str = "local-project";

struct ProjectOverviewTestRuntime {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for ProjectOverviewTestRuntime {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn test_runtime(launch_credential: &str) -> ProjectOverviewTestRuntime {
    let root = std::env::temp_dir().join(format!("agistack-project-overview-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create project overview workspace");
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
    ProjectOverviewTestRuntime { root, state }
}

fn legacy_test_runtime(credential: &str) -> ProjectOverviewTestRuntime {
    let runtime = test_runtime(credential);
    runtime
        .state
        .session_store
        .seed_test_session(credential)
        .expect("legacy authenticated test session");
    runtime
}

fn overview_request(
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
        .expect("project overview request")
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

async fn load_overview(
    app: &Router,
    project_id: &str,
    launch_credential: &str,
    session_credential: &str,
) -> (StatusCode, Value) {
    let response = app
        .clone()
        .oneshot(overview_request(
            &format!("/api/v1/projects/{project_id}/overview"),
            Some(launch_credential),
            Some(session_credential),
        ))
        .await
        .expect("project overview response");
    let status = response.status();
    (status, response_json(response).await)
}

fn assert_no_memory_keys(value: &Value) {
    match value {
        Value::Object(object) => {
            for (key, value) in object {
                assert!(
                    !key.to_ascii_lowercase().contains("memory"),
                    "local timeline projection must not use Memory naming: {key}"
                );
                assert_no_memory_keys(value);
            }
        }
        Value::Array(values) => {
            for value in values {
                assert_no_memory_keys(value);
            }
        }
        _ => {}
    }
}

#[tokio::test]
async fn project_overview_requires_launch_capability_and_authenticated_session() {
    let launch_credential = "project-overview-auth-launch";
    let runtime = test_runtime(launch_credential);
    let app = local_router(Arc::clone(&runtime.state));
    let session_credential = create_session(&app, launch_credential).await;
    let uri = format!("/api/v1/projects/{ACTIVE_PROJECT_ID}/overview");

    let missing_launch = app
        .clone()
        .oneshot(overview_request(&uri, None, Some(&session_credential)))
        .await
        .expect("missing launch response");
    assert_eq!(missing_launch.status(), StatusCode::UNAUTHORIZED);

    let missing_session = app
        .oneshot(overview_request(&uri, Some(launch_credential), None))
        .await
        .expect("missing session response");
    assert_eq!(missing_session.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn project_overview_rejects_a_project_outside_the_active_scope() {
    let launch_credential = "project-overview-scope-launch";
    let runtime = test_runtime(launch_credential);
    let app = local_router(Arc::clone(&runtime.state));
    let session_credential = create_session(&app, launch_credential).await;

    let (status, payload) = load_overview(
        &app,
        LEGACY_PROJECT_ID,
        launch_credential,
        &session_credential,
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(
        payload["detail"],
        "request is outside the active workspace context"
    );
}

#[tokio::test]
async fn project_overview_exposes_only_local_authoritative_and_degraded_fields() {
    let launch_credential = "project-overview-success-launch";
    let runtime = test_runtime(launch_credential);
    let app = local_router(Arc::clone(&runtime.state));
    let session_credential = create_session(&app, launch_credential).await;
    let conversation = LocalConversation {
        id: "project-overview-success-conversation".to_string(),
        project_id: ACTIVE_PROJECT_ID.to_string(),
        tenant_id: ACTIVE_TENANT_ID.to_string(),
        title: "Project overview fixture".to_string(),
        workspace_id: Some("local-demo-desktop-client-main".to_string()),
        capability_mode: ConversationCapabilityMode::Code,
        current_mode: ConversationRunMode::Build,
        created_at: "2099-01-01T00:00:00Z".to_string(),
        updated_at: "2099-01-01T00:00:00Z".to_string(),
    };
    runtime
        .state
        .session_store
        .insert_conversation(&conversation)
        .expect("insert project overview conversation");
    runtime
        .state
        .session_store
        .append_timeline(
            &conversation.id,
            &json!({
                "id": "project-overview-recent-item",
                "type": "assistant_message",
                "title": "Local result",
                "content": "A timeline-backed knowledge projection",
                "created_at": "2099-01-01T00:00:00Z",
                "tags": ["local"],
            }),
        )
        .expect("insert project overview timeline item");

    let (status, payload) = load_overview(
        &app,
        ACTIVE_PROJECT_ID,
        launch_credential,
        &session_credential,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(payload["capability"], "project_overview");
    assert_eq!(payload["availability"], "degraded");
    assert_eq!(
        payload["reason_code"],
        "local_project_overview_timeline_projection_only"
    );
    assert_eq!(payload["contract_version"], "3.0.0");
    assert_eq!(payload["allowed_actions"], json!(["view"]));
    assert_eq!(
        payload["scope"],
        json!({
            "tenant_id": ACTIVE_TENANT_ID,
            "project_id": ACTIVE_PROJECT_ID,
            "workspace_id": null,
            "instance_id": null,
        })
    );
    assert!(payload["authority_revision"]
        .as_i64()
        .is_some_and(|value| value > 0));
    assert_eq!(payload["backfill_cursor"], Value::Null);

    assert_eq!(payload["project"]["availability"], "available");
    assert_eq!(payload["project"]["reason_code"], Value::Null);
    assert_eq!(payload["project"]["value"]["id"], ACTIVE_PROJECT_ID);
    assert_eq!(payload["project"]["value"]["tenant_id"], ACTIVE_TENANT_ID);
    assert_eq!(payload["conversation_count"]["availability"], "available");
    assert!(payload["conversation_count"]["value"]
        .as_u64()
        .is_some_and(|value| value >= 1));

    assert_eq!(
        payload["recent_knowledge_items"]["availability"],
        "degraded"
    );
    assert_eq!(
        payload["recent_knowledge_items"]["reason_code"],
        "local_project_overview_timeline_projection_only"
    );
    assert_eq!(
        payload["recent_knowledge_items"]["source"],
        "desktop_timeline"
    );
    assert_eq!(
        payload["recent_knowledge_items"]["value"][0]["id"],
        "project-overview-recent-item"
    );
    assert_eq!(
        payload["recent_knowledge_items"]["value"][0]["source"],
        "desktop_timeline"
    );

    assert_eq!(payload["active_nodes"]["availability"], "unavailable");
    assert_eq!(
        payload["active_nodes"]["reason_code"],
        "local_project_graph_projection_unavailable"
    );
    assert_eq!(payload["active_nodes"]["value"], Value::Null);
    assert_eq!(payload["storage_quota"]["availability"], "not_applicable");
    assert_eq!(
        payload["storage_quota"]["reason_code"],
        "local_project_storage_quota_not_applicable"
    );
    assert_eq!(payload["storage_quota"]["value"], Value::Null);
    assert_eq!(payload["collaborators"]["availability"], "not_applicable");
    assert_eq!(
        payload["collaborators"]["reason_code"],
        "local_project_collaboration_governance_not_applicable"
    );
    assert_eq!(payload["collaborators"]["value"], Value::Null);
    assert_no_memory_keys(&payload);
}

#[tokio::test]
async fn project_overview_preserves_empty_local_state_without_fabricated_cloud_values() {
    let credential = "project-overview-empty-secret";
    let runtime = legacy_test_runtime(credential);
    let app = local_router(Arc::clone(&runtime.state));

    let (status, payload) = load_overview(&app, LEGACY_PROJECT_ID, credential, credential).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(payload["conversation_count"]["value"], 0);
    assert_eq!(payload["recent_knowledge_items"]["total"], 0);
    assert_eq!(payload["recent_knowledge_items"]["value"], json!([]));
    assert_eq!(payload["active_nodes"]["value"], Value::Null);
    assert_eq!(payload["storage_quota"]["value"], Value::Null);
    assert_eq!(payload["collaborators"]["value"], Value::Null);
}

#[tokio::test]
async fn project_overview_authority_revision_tracks_projection_backfill() {
    let credential = "project-overview-revision-secret";
    let runtime = legacy_test_runtime(credential);
    let app = local_router(Arc::clone(&runtime.state));
    let (_, before) = load_overview(&app, LEGACY_PROJECT_ID, credential, credential).await;
    let before_revision = before["authority_revision"]
        .as_i64()
        .expect("initial authority revision");

    let conversation = LocalConversation {
        id: "project-overview-revision-conversation".to_string(),
        project_id: LEGACY_PROJECT_ID.to_string(),
        tenant_id: LEGACY_TENANT_ID.to_string(),
        title: "Revision fixture".to_string(),
        workspace_id: Some("local-workspace".to_string()),
        capability_mode: ConversationCapabilityMode::Code,
        current_mode: ConversationRunMode::Build,
        created_at: "2026-07-30T00:00:00Z".to_string(),
        updated_at: "2026-07-30T00:00:00Z".to_string(),
    };
    runtime
        .state
        .session_store
        .insert_conversation(&conversation)
        .expect("insert revision conversation");
    runtime
        .state
        .session_store
        .append_timeline(
            &conversation.id,
            &json!({
                "id": "project-overview-revision-item",
                "type": "user_message",
                "content": "Refresh the local projection",
                "created_at": "2026-07-30T00:00:00Z",
            }),
        )
        .expect("insert revision timeline item");

    let (status, after) = load_overview(&app, LEGACY_PROJECT_ID, credential, credential).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(after["authority_revision"], before_revision + 1);
    assert_eq!(after["backfill_cursor"], Value::Null);
    assert_eq!(
        after["recent_knowledge_items"]["value"][0]["id"],
        "project-overview-revision-item"
    );
}

#[tokio::test]
async fn project_overview_rejects_unknown_query_fields_and_keeps_an_exact_schema() {
    let credential = "project-overview-schema-secret";
    let runtime = legacy_test_runtime(credential);
    let app = local_router(Arc::clone(&runtime.state));

    let response = app
        .clone()
        .oneshot(overview_request(
            "/api/v1/projects/local-project/overview?unexpected=true",
            Some(credential),
            Some(credential),
        ))
        .await
        .expect("unknown query response");
    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        response_json(response).await["reason_code"],
        "local_project_overview_query_invalid"
    );

    let (_, payload) = load_overview(&app, LEGACY_PROJECT_ID, credential, credential).await;
    let actual_keys = payload
        .as_object()
        .expect("project overview object")
        .keys()
        .cloned()
        .collect::<BTreeSet<_>>();
    let expected_keys = [
        "active_nodes",
        "allowed_actions",
        "authority_revision",
        "availability",
        "backfill_cursor",
        "capability",
        "collaborators",
        "contract_version",
        "conversation_count",
        "project",
        "reason_code",
        "recent_knowledge_items",
        "scope",
        "service_version",
        "storage_quota",
    ]
    .into_iter()
    .map(ToString::to_string)
    .collect::<BTreeSet<_>>();
    assert_eq!(actual_keys, expected_keys);
}
