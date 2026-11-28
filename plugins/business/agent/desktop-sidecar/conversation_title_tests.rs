use std::{path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Request, StatusCode},
    response::Response,
};
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

const PROJECT_ID: &str = "local-project";
const TENANT_ID: &str = "local";
const WORKSPACE_ID: &str = "local-workspace";

struct ConversationTitleTestRuntime {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for ConversationTitleTestRuntime {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn test_runtime(credential: &str) -> ConversationTitleTestRuntime {
    let root = std::env::temp_dir().join(format!("agistack-conversation-title-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create conversation title workspace");
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.clone(),
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    ConversationTitleTestRuntime { root, state }
}

fn conversation(id: &str, tenant_id: &str, title: &str) -> LocalConversation {
    LocalConversation {
        id: id.to_string(),
        project_id: PROJECT_ID.to_string(),
        tenant_id: tenant_id.to_string(),
        title: title.to_string(),
        workspace_id: Some(WORKSPACE_ID.to_string()),
        capability_mode: ConversationCapabilityMode::Code,
        current_mode: ConversationRunMode::Plan,
        created_at: "2026-08-01T00:00:00Z".to_string(),
        updated_at: "2026-08-01T00:00:00Z".to_string(),
    }
}

fn title_request(
    credential: &str,
    conversation_id: &str,
    project_id: Option<&str>,
    body: Value,
) -> Request<Body> {
    let query = project_id
        .map(|project_id| format!("?project_id={project_id}"))
        .unwrap_or_default();
    Request::builder()
        .method("PATCH")
        .uri(format!(
            "/api/v1/agent/conversations/{conversation_id}/title{query}"
        ))
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential)
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .expect("conversation title request")
}

async fn response_json(response: Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("conversation title response body");
    serde_json::from_slice(&body).expect("conversation title response JSON")
}

#[tokio::test]
async fn patch_title_persists_the_trimmed_value_without_changing_scope() {
    let credential = "conversation-title-success-secret";
    let runtime = test_runtime(credential);
    let original = conversation("conversation-title-success", TENANT_ID, "Original title");
    runtime
        .state
        .session_store
        .insert_conversation(&original)
        .expect("insert conversation title fixture");
    let app = local_router(Arc::clone(&runtime.state));

    let response = app
        .oneshot(title_request(
            credential,
            &original.id,
            Some(PROJECT_ID),
            json!({ "title": "  Renamed locally  " }),
        ))
        .await
        .expect("conversation title response");
    let status = response.status();
    let payload = response_json(response).await;
    let persisted = runtime
        .state
        .session_store
        .conversation(&original.id)
        .expect("reload renamed conversation")
        .expect("persisted renamed conversation");

    assert_eq!(status, StatusCode::OK);
    assert_eq!(payload["id"], original.id);
    assert_eq!(payload["title"], "Renamed locally");
    assert_eq!(payload["tenant_id"], TENANT_ID);
    assert_eq!(payload["project_id"], PROJECT_ID);
    assert_eq!(payload["workspace_id"], WORKSPACE_ID);
    assert_eq!(persisted.title, "Renamed locally");
    assert_eq!(persisted.tenant_id, original.tenant_id);
    assert_eq!(persisted.project_id, original.project_id);
    assert_eq!(persisted.workspace_id, original.workspace_id);
    assert_eq!(persisted.created_at, original.created_at);
    assert_ne!(persisted.updated_at, original.updated_at);
}

#[tokio::test]
async fn patch_title_rejects_missing_or_malformed_inputs_with_stable_codes() {
    let credential = "conversation-title-validation-secret";
    let runtime = test_runtime(credential);
    let fixture = conversation("conversation-title-validation", TENANT_ID, "Original title");
    runtime
        .state
        .session_store
        .insert_conversation(&fixture)
        .expect("insert conversation title fixture");
    let app = local_router(Arc::clone(&runtime.state));

    let missing_project = app
        .clone()
        .oneshot(title_request(
            credential,
            &fixture.id,
            None,
            json!({ "title": "Rename" }),
        ))
        .await
        .expect("missing project response");
    let missing_project_status = missing_project.status();
    let missing_project_payload = response_json(missing_project).await;
    let blank_title = app
        .clone()
        .oneshot(title_request(
            credential,
            &fixture.id,
            Some(PROJECT_ID),
            json!({ "title": "   " }),
        ))
        .await
        .expect("blank title response");
    let blank_title_status = blank_title.status();
    let blank_title_payload = response_json(blank_title).await;
    let malformed_title = app
        .clone()
        .oneshot(title_request(
            credential,
            &fixture.id,
            Some(PROJECT_ID),
            json!({ "title": 42 }),
        ))
        .await
        .expect("malformed title response");
    let malformed_title_status = malformed_title.status();
    let malformed_title_payload = response_json(malformed_title).await;
    let unexpected_field = app
        .oneshot(title_request(
            credential,
            &fixture.id,
            Some(PROJECT_ID),
            json!({ "title": "Rename", "unexpected": true }),
        ))
        .await
        .expect("unexpected field response");
    let unexpected_field_status = unexpected_field.status();
    let unexpected_field_payload = response_json(unexpected_field).await;

    assert_eq!(missing_project_status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        missing_project_payload["code"],
        "local_conversation_title_query_invalid"
    );
    assert_eq!(blank_title_status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        blank_title_payload["code"],
        "local_conversation_title_required"
    );
    assert_eq!(malformed_title_status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        malformed_title_payload["code"],
        "local_conversation_title_body_invalid"
    );
    assert_eq!(unexpected_field_status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        unexpected_field_payload["code"],
        "local_conversation_title_body_invalid"
    );
    assert_eq!(
        runtime
            .state
            .session_store
            .conversation(&fixture.id)
            .expect("reload validation fixture")
            .expect("persisted validation fixture")
            .title,
        fixture.title
    );
}

#[tokio::test]
async fn patch_title_rejects_cross_project_and_cross_tenant_targets() {
    let credential = "conversation-title-scope-secret";
    let runtime = test_runtime(credential);
    let active = conversation("conversation-title-project", TENANT_ID, "Project original");
    let cross_tenant = conversation(
        "conversation-title-cross-tenant",
        "another-tenant",
        "Tenant original",
    );
    runtime
        .state
        .session_store
        .insert_conversation(&active)
        .expect("insert project scope fixture");
    runtime
        .state
        .session_store
        .insert_conversation(&cross_tenant)
        .expect("insert tenant scope fixture");
    let app = local_router(Arc::clone(&runtime.state));

    let cross_project_response = app
        .clone()
        .oneshot(title_request(
            credential,
            &active.id,
            Some("another-project"),
            json!({ "title": "Must not persist" }),
        ))
        .await
        .expect("cross-project title response");
    let cross_project_status = cross_project_response.status();
    let cross_project_payload = response_json(cross_project_response).await;
    let cross_tenant_response = app
        .oneshot(title_request(
            credential,
            &cross_tenant.id,
            Some(PROJECT_ID),
            json!({ "title": "Must not persist" }),
        ))
        .await
        .expect("cross-tenant title response");
    let cross_tenant_status = cross_tenant_response.status();
    let cross_tenant_payload = response_json(cross_tenant_response).await;

    assert_eq!(cross_project_status, StatusCode::FORBIDDEN);
    assert_eq!(
        cross_project_payload["detail"],
        "resource is outside the active workspace context"
    );
    assert_eq!(cross_tenant_status, StatusCode::FORBIDDEN);
    assert_eq!(
        cross_tenant_payload["detail"],
        "resource is outside the active workspace context"
    );
    assert_eq!(
        runtime
            .state
            .session_store
            .conversation(&active.id)
            .expect("reload project scope fixture")
            .expect("persisted project scope fixture")
            .title,
        active.title
    );
    assert_eq!(
        runtime
            .state
            .session_store
            .conversation(&cross_tenant.id)
            .expect("reload tenant scope fixture")
            .expect("persisted tenant scope fixture")
            .title,
        cross_tenant.title
    );
}

#[tokio::test]
async fn patch_title_returns_the_stable_missing_conversation_error() {
    let credential = "conversation-title-missing-secret";
    let runtime = test_runtime(credential);
    let app = local_router(Arc::clone(&runtime.state));

    let response = app
        .oneshot(title_request(
            credential,
            "missing-conversation",
            Some(PROJECT_ID),
            json!({ "title": "Rename" }),
        ))
        .await
        .expect("missing conversation response");
    let status = response.status();
    let payload = response_json(response).await;

    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(payload["detail"], "conversation not found");
}
