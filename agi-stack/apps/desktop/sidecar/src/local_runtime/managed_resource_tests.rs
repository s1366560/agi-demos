use std::path::PathBuf;
use std::sync::Arc;

use axum::{body::Body, http::Request};
use chrono::Utc;
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::*;

fn test_root() -> PathBuf {
    std::env::temp_dir().join(format!(
        "agistack-managed-resource-runtime-{}",
        Uuid::new_v4()
    ))
}

fn test_state(credential: &str) -> Arc<LocalRuntimeState> {
    let root = test_root();
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root,
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
    state
}

fn authenticated_json_request(
    method: &str,
    uri: &str,
    credential: &str,
    body: Value,
) -> Request<Body> {
    Request::builder()
        .method(method)
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential)
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .expect("authenticated JSON request")
}

async fn response_json(response: axum::response::Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}

fn switch_to_member_project(state: &LocalRuntimeState, credential: &str) {
    let authenticated = state
        .session_store
        .validate_session_credential(credential, Utc::now().timestamp_millis())
        .expect("validate session")
        .expect("authenticated context");
    state
        .session_store
        .switch_workspace_context(
            &authenticated,
            &ContextSwitchRequest {
                tenant_id: "orbital".to_string(),
                project_id: "agent-evals".to_string(),
                expected_revision: 0,
                idempotency_key: "switch-member-resource-test".to_string(),
            },
            Utc::now().timestamp_millis(),
        )
        .expect("switch to member project");
}

fn seed_mutable_resources(state: &LocalRuntimeState, tenant_id: &str, project_id: &str) {
    let now_ms = Utc::now().timestamp_millis();
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Skill,
            "tenant",
            tenant_id,
            "custom-skill",
            "active",
            None,
            json!({
                "name": "Custom skill",
                "status": "active",
                "scope": "tenant",
                "is_system_skill": false,
            }),
            now_ms,
        )
        .expect("seed mutable skill");
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Plugin,
            "tenant",
            tenant_id,
            "custom-plugin",
            "active",
            None,
            json!({
                "name": "Custom plugin",
                "source": "local",
                "enabled": true,
                "status": "active",
            }),
            now_ms,
        )
        .expect("seed mutable plugin");
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Agent,
            "project",
            project_id,
            "custom-agent",
            "active",
            None,
            json!({
                "name": "Custom agent",
                "source": "local",
                "project_id": project_id,
                "enabled": true,
                "status": "active",
            }),
            now_ms,
        )
        .expect("seed mutable agent");
}

#[tokio::test]
async fn tenant_members_can_read_but_cannot_mutate_managed_resources() {
    let credential = "member-resource-secret";
    let state = test_state(credential);
    switch_to_member_project(&state, credential);
    seed_mutable_resources(&state, "orbital", "agent-evals");
    let app = local_router(state);

    for uri in [
        "/api/v1/skills/?tenant_id=orbital&project_id=agent-evals",
        "/api/v1/channels/tenants/orbital/plugins",
        "/api/v1/agent/definitions?tenant_id=orbital&project_id=agent-evals",
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "GET",
                uri,
                credential,
                json!({}),
            ))
            .await
            .expect("managed resource list response");
        assert_eq!(response.status(), axum::http::StatusCode::OK);
    }

    for (method, uri, body) in [
        (
            "PATCH",
            "/api/v1/skills/custom-skill/status?status=disabled&tenant_id=orbital",
            json!({}),
        ),
        (
            "POST",
            "/api/v1/channels/tenants/orbital/plugins/custom-plugin/disable",
            json!({}),
        ),
        (
            "PATCH",
            "/api/v1/agent/definitions/custom-agent/enabled?tenant_id=orbital&project_id=agent-evals",
            json!({ "enabled": false }),
        ),
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(method, uri, credential, body))
            .await
            .expect("managed resource mutation response");
        assert_eq!(response.status(), axum::http::StatusCode::FORBIDDEN);
        let payload = response_json(response).await;
        assert_eq!(payload["code"], "resource_manager_required");
    }
}

#[tokio::test]
async fn tenant_owners_can_mutate_non_builtin_managed_resources() {
    let credential = "owner-custom-resource-secret";
    let state = test_state(credential);
    seed_mutable_resources(&state, "local", "local-project");
    let app = local_router(state);

    for (method, uri, body) in [
        (
            "PATCH",
            "/api/v1/skills/custom-skill/status?status=disabled&tenant_id=local",
            json!({}),
        ),
        (
            "POST",
            "/api/v1/channels/tenants/local/plugins/custom-plugin/disable",
            json!({}),
        ),
        (
            "PATCH",
            "/api/v1/agent/definitions/custom-agent/enabled?tenant_id=local&project_id=local-project",
            json!({ "enabled": false }),
        ),
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(method, uri, credential, body))
            .await
            .expect("mutable managed resource response");
        assert_eq!(response.status(), axum::http::StatusCode::OK);
        let payload = response_json(response).await;
        let resource = payload.get("item").unwrap_or(&payload);
        assert_eq!(resource["revision"], 1);
        assert_eq!(resource["status"], "disabled");
    }
}

#[tokio::test]
async fn tenant_owners_cannot_mutate_immutable_managed_resources() {
    let credential = "owner-resource-secret";
    let state = test_state(credential);
    let app = local_router(Arc::clone(&state));

    for (method, uri, body) in [
        (
            "PATCH",
            "/api/v1/skills/implementation/status?status=disabled&tenant_id=local",
            json!({}),
        ),
        (
            "POST",
            "/api/v1/channels/tenants/local/plugins/local-workspace/disable",
            json!({}),
        ),
        (
            "PATCH",
            "/api/v1/agent/definitions/builtin%3Aall-access/enabled?tenant_id=local&project_id=local-project",
            json!({ "enabled": false }),
        ),
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(method, uri, credential, body))
            .await
            .expect("immutable managed resource response");
        assert_eq!(response.status(), axum::http::StatusCode::CONFLICT);
        let payload = response_json(response).await;
        assert_eq!(payload["code"], "immutable_resource");
    }

    for (kind, scope_kind, scope_id, id) in [
        (
            ManagedResourceKind::Skill,
            "tenant",
            "local",
            "implementation",
        ),
        (
            ManagedResourceKind::Plugin,
            "tenant",
            "local",
            "local-workspace",
        ),
        (
            ManagedResourceKind::Agent,
            "project",
            "local-project",
            "builtin:all-access",
        ),
    ] {
        let resource = state
            .session_store
            .managed_resource(kind, scope_kind, scope_id, id)
            .expect("persisted managed resource")
            .expect("managed resource");
        assert_eq!(resource["revision"], 0);
        match kind {
            ManagedResourceKind::Skill => assert_eq!(resource["status"], "active"),
            ManagedResourceKind::Plugin | ManagedResourceKind::Agent => {
                assert_eq!(resource["enabled"], true);
            }
            ManagedResourceKind::Provider => unreachable!("provider is not part of this test"),
        }
    }
}

#[tokio::test]
async fn managed_agent_mutation_rejects_a_mismatched_project_scope() {
    let credential = "project-scope-resource-secret";
    let state = test_state(credential);
    let app = local_router(Arc::clone(&state));

    let response = app
        .oneshot(authenticated_json_request(
            "PATCH",
            "/api/v1/agent/definitions/builtin%3Aall-access/enabled?tenant_id=local&project_id=desktop-client",
            credential,
            json!({ "enabled": false }),
        ))
        .await
        .expect("project-scoped managed agent response");
    assert_eq!(response.status(), axum::http::StatusCode::FORBIDDEN);
    let payload = response_json(response).await;
    assert_eq!(
        payload["detail"],
        "request is outside the active project context"
    );

    let agent = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Agent,
            "project",
            "local-project",
            "builtin:all-access",
        )
        .expect("persisted managed agent")
        .expect("managed agent");
    assert_eq!(agent["revision"], 0);
    assert_eq!(agent["enabled"], true);
}
