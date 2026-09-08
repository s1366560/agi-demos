use super::super::capabilities_generated::{READ_ACTIONS, WRITE_ACTIONS};
use super::*;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use tower::ServiceExt;

async fn request(
    state: Arc<LocalRuntimeState>,
    authorized: bool,
    path: &str,
) -> (StatusCode, Value) {
    let mut builder = Request::builder()
        .uri(path)
        .header("x-agistack-launch", TOKEN);
    if authorized {
        builder = builder.header("authorization", format!("Bearer {TOKEN}"));
    }
    let response = crate::local_runtime::local_router_with_generation_required(state)
        .oneshot(builder.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}
fn role(state: &LocalRuntimeState, auth: &AuthenticatedContext, role: &str) {
    state
        .session_store
        .connection()
        .unwrap()
        .execute(
            "UPDATE desktop_tenant_memberships SET role=?1 WHERE user_id=?2 AND tenant_id=?3",
            rusqlite::params![role, auth.user.user_id, auth.workspace.tenant_id],
        )
        .unwrap();
}

#[tokio::test]
async fn closed_release_publishes_existing_observed_entry_without_storage_or_actions() {
    let state = test_state(TOKEN);
    let directory = TestDirectory::new();
    assert_eq!(
        request(state.clone(), true, "/api/v1/knowledge/capabilities")
            .await
            .0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    publish(&state, &directory, 1, false).await;
    assert_eq!(
        request(state.clone(), false, "/api/v1/knowledge/capabilities")
            .await
            .0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        request(
            state.clone(),
            true,
            "/api/v1/knowledge/capabilities?tenant_id=foreign"
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let (status, response) = request(state.clone(), true, "/api/v1/knowledge/capabilities").await;
    assert_eq!(status, StatusCode::OK);
    let mut expected: Value = serde_json::from_str(include_str!(
        "../../../../../../../shared/fixtures/native-knowledge-capabilities.v1.json"
    ))
    .unwrap();
    let auth = authenticated(&state);
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    expected["scope"] = json!(operation_scope(&auth, &lease));
    expected["actor_id"] = json!(auth.user.user_id);
    expected["result"]["scope"]["tenant_id"] = json!(auth.workspace.tenant_id);
    expected["result"]["scope"]["project_id"] = json!(auth.workspace.project_id);
    expected["result"]["authority_revision"] = json!(auth.workspace.revision);
    assert_eq!(response, expected);
    assert!(!directory.0.exists());
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn validation_publication_uses_live_role_and_preserves_all_existing_native_actions() {
    let state = test_state(TOKEN);
    let directory = TestDirectory::new();
    publish(&state, &directory, 1, true).await;
    let auth = authenticated(&state);
    let all: std::collections::BTreeSet<_> =
        READ_ACTIONS.iter().chain(WRITE_ACTIONS).copied().collect();
    assert_eq!(all.len(), 51);
    for action in [
        "failed_processing",
        "failed_index",
        "processing_audits",
        "community_active",
        "community_build",
        "community_builds",
        "community_audit",
    ] {
        assert!(READ_ACTIONS.contains(&action));
    }
    for action in [
        "create_community_build",
        "select_community_build",
        "process_community_one",
        "retry_community",
        "activate_community_build",
    ] {
        assert!(WRITE_ACTIONS.contains(&action));
        assert!(!READ_ACTIONS.contains(&action));
    }
    for member_role in ["owner", "admin", "member", "contributor", "viewer"] {
        role(&state, &auth, member_role);
        let (status, response) =
            request(state.clone(), true, "/api/v1/knowledge/capabilities").await;
        assert_eq!(status, StatusCode::OK);
        let expected: Vec<_> = if member_role == "viewer" {
            READ_ACTIONS.to_vec()
        } else {
            all.iter().copied().collect()
        };
        assert_eq!(response["result"]["allowed_actions"], json!(expected));
        assert_eq!(response["result"]["provenance"], "observed");
        assert_eq!(response["result"]["authority_source"], "sidecar");
        assert!(
            expected.contains(&"view")
                && expected.contains(&"list")
                && expected.contains(&"get")
                && expected.contains(&"sync_status")
        );
        assert!(!directory.0.exists());
    }
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn observation_rejects_stale_actor_scope_expiry_and_generation() {
    let state = test_state(TOKEN);
    let directory = TestDirectory::new();
    publish(&state, &directory, 1, true).await;
    let auth = authenticated(&state);
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    let observe = super::super::routes::capability_routes::observe;
    let mut forged = auth.clone();
    forged.user.user_id = "foreign".into();
    assert!(matches!(
        observe(&state, &lease, &forged),
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    forged = auth.clone();
    forged.workspace.revision += 1;
    assert!(matches!(
        observe(&state, &lease, &forged),
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    role(&state, &auth, "viewer");
    assert_eq!(
        observe(&state, &lease, &auth).unwrap()["result"]["allowed_actions"],
        json!(READ_ACTIONS)
    );
    publish(&state, &directory, 2, true).await;
    assert!(matches!(
        observe(&state, &lease, &auth),
        Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
    ));
    let current = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    state
        .session_store
        .connection()
        .unwrap()
        .execute(
            "UPDATE desktop_user_sessions SET expires_at_ms=0 WHERE id=?1",
            [&auth.session_id],
        )
        .unwrap();
    assert!(matches!(
        observe(&state, &current, &auth),
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    assert!(!directory.0.exists());
    state.platform_plugin_authority_v2.deactivate().await;
}
