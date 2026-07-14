use axum::http::StatusCode;
use serde_json::json;

use super::*;

#[test]
fn query_defaults_match_python() {
    // serde defaults: page=1, page_size=20, search=None.
    let q: TenantListQuery =
        serde_urlencoded::from_str("").expect("empty tenant query must deserialize");
    assert_eq!(q.page, 1);
    assert_eq!(q.page_size, 20);
    assert!(q.search.is_none());
    let q2: TenantListQuery = serde_urlencoded::from_str("page=3&page_size=50&search=acme")
        .expect("populated tenant query must deserialize");
    assert_eq!(q2.page, 3);
    assert_eq!(q2.page_size, 50);
    assert_eq!(q2.search.as_deref(), Some("acme"));
}

#[test]
fn project_query_defaults_match_python() {
    let q: ProjectListQuery =
        serde_urlencoded::from_str("").expect("empty project query must deserialize");
    assert!(q.tenant_id.is_none());
    assert_eq!(q.page, 1);
    assert_eq!(q.page_size, 20);
    assert!(q.search.is_none());
    assert_eq!(q.visibility, "all");
    assert!(q.owner_id.is_none());

    let q2: ProjectListQuery = serde_urlencoded::from_str(
        "tenant_id=t1&page=2&page_size=10&search=ai&visibility=private&owner_id=u1",
    )
    .expect("populated project query must deserialize");
    assert_eq!(q2.tenant_id.as_deref(), Some("t1"));
    assert_eq!(q2.page, 2);
    assert_eq!(q2.page_size, 10);
    assert_eq!(q2.search.as_deref(), Some("ai"));
    assert_eq!(q2.visibility, "private");
    assert_eq!(q2.owner_id.as_deref(), Some("u1"));
}

#[test]
fn login_form_ignores_extra_grant_fields() {
    // OAuth2 form may carry grant_type/scope; only username+password bind.
    let f: LoginForm =
        serde_urlencoded::from_str("grant_type=password&username=a%40b.co&password=pw&scope=")
            .expect("oauth password grant form must deserialize");
    assert_eq!(f.username, "a@b.co");
    assert_eq!(f.password, "pw");
}

#[test]
fn tenant_update_patch_preserves_explicit_null_and_known_fields() {
    let patch = tenant_update_patch_from_value(json!({
        "name": "Acme 2",
        "description": null,
        "plan": "enterprise",
        "max_projects": 20,
        "max_users": 50,
        "max_storage": 2147483648i64,
        "ignored": "kept out"
    }))
    .expect("tenant update object must produce a patch");
    assert_eq!(patch.name.as_deref(), Some("Acme 2"));
    assert_eq!(patch.description, Some(None));
    assert_eq!(patch.plan.as_deref(), Some("enterprise"));
    assert_eq!(patch.max_projects, Some(20));
    assert_eq!(patch.max_users, Some(50));
    assert_eq!(patch.max_storage, Some(2_147_483_648));
    assert!(!patch.is_empty());

    let invalid = tenant_update_patch_from_value(json!("not an object"))
        .expect_err("non-object tenant update must be rejected");
    assert_eq!(invalid.status, StatusCode::UNPROCESSABLE_ENTITY);
}

#[test]
fn project_update_patch_preserves_explicit_null_and_known_fields() {
    let patch = project_update_patch_from_value(json!({
        "name": "Project 2",
        "description": null,
        "memory_rules": {"max_episodes": 2000},
        "graph_config": {"max_nodes": 5000},
        "graph_store_id": "__env_neo4j__",
        "retrieval_store_id": null,
        "sandbox_config": {"sandbox_type": "local", "local_config": {"host": "localhost"}},
        "is_public": true,
        "agent_conversation_mode": "multi_agent_shared",
        "ignored": "kept out"
    }))
    .expect("project update object must produce a patch");
    assert_eq!(patch.name.as_deref(), Some("Project 2"));
    assert_eq!(patch.description, Some(None));
    assert_eq!(
        patch
            .memory_rules
            .as_ref()
            .expect("memory rules should be present")["max_episodes"],
        2000
    );
    assert_eq!(
        patch
            .graph_config
            .as_ref()
            .expect("graph config should be present")["max_nodes"],
        5000
    );
    assert_eq!(
        patch.graph_store_id.as_ref().and_then(|v| v.as_deref()),
        Some("__env_neo4j__")
    );
    assert_eq!(patch.retrieval_store_id, Some(None));
    assert_eq!(
        patch
            .sandbox_config
            .as_ref()
            .expect("sandbox config should be present")["sandbox_type"],
        "local"
    );
    assert_eq!(patch.is_public, Some(true));
    assert_eq!(
        patch.agent_conversation_mode.as_deref(),
        Some("multi_agent_shared")
    );
    assert!(!patch.is_empty());

    let invalid = project_update_patch_from_value(json!("not an object"))
        .expect_err("non-object project update must be rejected");
    assert_eq!(invalid.status, StatusCode::UNPROCESSABLE_ENTITY);
}

#[test]
fn device_requests_default_missing_fields_like_python_dict_get() {
    let approve: DeviceApproveRequest =
        serde_json::from_str("{}").expect("empty approve body must deserialize");
    assert!(approve.user_code.is_empty());
    let token: DeviceTokenRequest =
        serde_json::from_str("{}").expect("empty device token body must deserialize");
    assert!(token.device_code.is_empty());
    let code: DeviceCodeRequest = serde_json::from_str(r#"{"client_id":"cli","scope":"read"}"#)
        .expect("device code body must deserialize");
    assert_eq!(code._client_id.as_deref(), Some("cli"));
    assert_eq!(code._scope.as_deref(), Some("read"));
}

#[test]
fn workspace_context_switch_request_requires_revision_and_idempotency() {
    let request: WorkspaceContextSwitchRequest = serde_json::from_value(json!({
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "expected_revision": 7,
        "idempotency_key": "context-switch-1"
    }))
    .expect("workspace context switch request must deserialize");
    assert_eq!(request.tenant_id, "tenant-1");
    assert_eq!(request.project_id, "project-1");
    assert_eq!(request.expected_revision, 7);
    assert_eq!(request.idempotency_key, "context-switch-1");

    assert!(
        serde_json::from_value::<WorkspaceContextSwitchRequest>(json!({
            "tenant_id": "tenant-1",
            "project_id": "project-1"
        }))
        .is_err()
    );
}

#[test]
fn invitation_query_defaults_match_python() {
    let q: InvitationListQuery =
        serde_urlencoded::from_str("").expect("empty invitation query must deserialize");
    assert_eq!(q.limit, 50);
    assert_eq!(q.offset, 0);
    let q2: InvitationListQuery = serde_urlencoded::from_str("limit=25&offset=10")
        .expect("populated invitation query must deserialize");
    assert_eq!(q2.limit, 25);
    assert_eq!(q2.offset, 10);
}
