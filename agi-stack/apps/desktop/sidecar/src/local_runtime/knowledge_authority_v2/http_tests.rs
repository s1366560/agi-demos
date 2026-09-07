use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use tower::ServiceExt;

use super::*;
use crate::local_runtime::local_router_with_generation_required;

#[tokio::test]
async fn sync_link_and_outbox_use_admitted_authority_without_claiming_remote_success() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let scope = request_scope(&state);
    let status_body = json!({"scope":scope,"query":{"operation":"sync_status"}});
    let initial = request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        status_body.clone(),
        None,
        None,
        true,
    )
    .await;
    assert_eq!(initial.0, StatusCode::OK);
    assert!(initial.1["result"]["status"]["link"].is_null());
    let link_body = json!({"scope":scope,"link":{"remote_tenant_id":"remote-tenant","remote_project_id":"remote-project","remote_actor_id":"remote-actor"}});
    let linked = request(
        Arc::clone(&state),
        "/api/v1/knowledge/sync-link",
        link_body.clone(),
        None,
        None,
        true,
    )
    .await;
    assert_eq!(linked.0, StatusCode::OK);
    assert_eq!(linked.1["result"]["association_state"], "configured");
    assert_eq!(linked.1["result"]["remote_authorization"], "unverified");
    let repeated = request(
        Arc::clone(&state),
        "/api/v1/knowledge/sync-link",
        link_body.clone(),
        None,
        None,
        true,
    )
    .await;
    assert_eq!(repeated.1, linked.1);
    let mut changed = link_body.clone();
    changed["link"]["remote_project_id"] = json!("another-project");
    assert_eq!(
        request(
            Arc::clone(&state),
            "/api/v1/knowledge/sync-link",
            changed,
            None,
            None,
            true
        )
        .await
        .0,
        StatusCode::CONFLICT
    );
    let mut foreign = link_body;
    foreign["scope"]["tenant_id"] = json!("another-tenant");
    assert_eq!(
        request(
            Arc::clone(&state),
            "/api/v1/knowledge/sync-link",
            foreign,
            None,
            None,
            true
        )
        .await
        .0,
        StatusCode::FORBIDDEN
    );
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let mut viewer = authenticated(&state);
    viewer.membership_role = "viewer".into();
    let view = KnowledgeOperationV2::admit(lease, &viewer, &scope).unwrap();
    assert!(matches!(
        view.configure_sync_link(agistack_core::knowledge::sync::KnowledgeSyncLink {
            remote_tenant_id: "remote-tenant".into(),
            remote_project_id: "remote-project".into(),
            remote_actor_id: "remote-actor".into()
        })
        .await,
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    drop(view);
    let created = request(
        Arc::clone(&state),
        "/api/v1/knowledge/mutations",
        json!({"scope":scope,"mutation":mutation(&authenticated(&state))}),
        Some("sync-create"),
        None,
        true,
    )
    .await;
    assert_eq!(created.0, StatusCode::OK);
    let outbox = request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        json!({"scope":scope,"query":{"operation":"sync_outbox","after_sequence":0,"limit":20}}),
        None,
        None,
        true,
    )
    .await;
    assert_eq!(outbox.0, StatusCode::OK);
    let items = outbox.1["result"]["items"].as_array().unwrap();
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["local_change"], created.1["result"]["receipt"]);
    assert!(Uuid::parse_str(items[0]["change_id"].as_str().unwrap()).is_ok());
    let status = request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        status_body,
        None,
        None,
        true,
    )
    .await;
    assert_eq!(status.1["result"]["status"]["pending_changes"], 1);
    assert_eq!(
        status.1["result"]["status"]["replica_id"],
        initial.1["result"]["status"]["replica_id"]
    );
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn executable_catalog_negative_routes_enforce_closed_release() {
    let catalog: Value = serde_json::from_str(include_str!(
        "../../../../contracts/local-route-parity.v1.json"
    ))
    .unwrap();
    let probes = catalog["negative_routes"].as_array().unwrap();
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, false).await;
    let mut observed = std::collections::BTreeSet::new();
    for probe in probes.iter().filter(|probe| probe["authority"] == "knowledge_release_closed") {
        assert_eq!(probe["area"], "project_memories");
        assert_eq!(probe["authority"], "knowledge_release_closed");
        assert_eq!(probe["source"], "sidecar_knowledge");
        assert_eq!(probe["method"], "POST");
        assert_eq!(probe["expected_status"], 503);
        assert_eq!(probe["expected_reason_code"], "knowledge_release_closed");
        let uri = probe["uri"].as_str().unwrap();
        assert_eq!(probe["source_marker"], uri);
        assert!(include_str!("routes.rs").contains(uri));
        assert!(observed.insert(uri));
        let mut body = probe["body"].clone();
        body["scope"] = serde_json::to_value(request_scope(&state)).unwrap();
        let result = request(
            Arc::clone(&state),
            uri,
            body,
            probe["idempotency_key"].as_str(),
            Some("1"),
            true,
        )
        .await;
        assert_eq!(
            result.0.as_u16(),
            probe["expected_status"].as_u64().unwrap() as u16
        );
        assert_eq!(result.1["error"]["code"], probe["expected_reason_code"]);
    }
    assert_eq!(
        observed,
        std::collections::BTreeSet::from([
            "/api/v1/knowledge/query",
            "/api/v1/knowledge/mutations",
            "/api/v1/knowledge/sync-link",
            "/api/v1/knowledge/sync-push",
            "/api/v1/knowledge/sync-pull",
            "/api/v1/knowledge/sync-resolve-pull"
        ])
    );
    assert!(!directory.0.exists());
    state.platform_plugin_authority_v2.deactivate().await;
}

async fn request(
    state: Arc<LocalRuntimeState>,
    path: &str,
    body: Value,
    key: Option<&str>,
    revision: Option<&str>,
    authenticated_request: bool,
) -> (StatusCode, Value) {
    let mut request = Request::builder()
        .method("POST")
        .uri(path)
        .header("content-type", "application/json")
        .header("x-agistack-launch", TOKEN);
    if authenticated_request {
        request = request.header("authorization", format!("Bearer {TOKEN}"));
    }
    if let Some(key) = key {
        request = request.header("idempotency-key", key);
    }
    if let Some(revision) = revision {
        request = request.header("x-expected-revision", revision);
    }
    let response = local_router_with_generation_required(state)
        .oneshot(
            request
                .body(Body::from(serde_json::to_vec(&body).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (status, serde_json::from_slice(&bytes).unwrap())
}

fn request_scope(state: &LocalRuntimeState) -> KnowledgeOperationScopeV2 {
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    operation_scope(&authenticated(state), &lease)
}

#[tokio::test]
async fn http_routes_require_session_generation_and_joint_release() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    let missing = request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        json!({}),
        None,
        None,
        true,
    )
    .await;
    assert_eq!(missing.0, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(
        missing.1["error"]["code"],
        "plugin_generation_v2_unavailable"
    );
    publish(&state, &directory, 1, false).await;
    let body = json!({"scope": request_scope(&state), "query": {"operation":"list", "limit":20, "offset":0}});
    let unauthorized = request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        body.clone(),
        None,
        None,
        false,
    )
    .await;
    assert_eq!(unauthorized.0, StatusCode::UNAUTHORIZED);
    let closed = request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        body,
        None,
        None,
        true,
    )
    .await;
    assert_eq!(closed.0, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(closed.1["error"]["code"], "knowledge_release_closed");
    assert!(!directory.0.exists());
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn http_crud_uses_durable_receipts_revisions_and_scoped_change_queries() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let auth = authenticated(&state);
    let scope = request_scope(&state);
    let body = json!({"scope": scope, "mutation": mutation(&auth)});
    let absent_key = request(
        Arc::clone(&state),
        "/api/v1/knowledge/mutations",
        body.clone(),
        None,
        None,
        true,
    )
    .await;
    assert_eq!(absent_key.0, StatusCode::BAD_REQUEST);
    let created = request(
        Arc::clone(&state),
        "/api/v1/knowledge/mutations",
        body.clone(),
        Some("create"),
        None,
        true,
    )
    .await;
    assert_eq!(created.0, StatusCode::OK);
    assert_eq!(created.1["result"]["processing_status"], "accepted");
    let replay = request(
        Arc::clone(&state),
        "/api/v1/knowledge/mutations",
        body,
        Some("create"),
        None,
        true,
    )
    .await;
    assert_eq!(replay.1["result"]["replayed"], true);
    assert_eq!(
        created.1["result"]["receipt"],
        replay.1["result"]["receipt"]
    );
    let mut memory: Memory =
        serde_json::from_value(created.1["result"]["receipt"]["memory"].clone()).unwrap();
    memory.content = "updated content".into();
    let update =
        json!({"scope":scope, "mutation": MemoryMutation::Update { memory, expected_revision:1 }});
    assert_eq!(
        request(
            Arc::clone(&state),
            "/api/v1/knowledge/mutations",
            update.clone(),
            Some("update"),
            None,
            true
        )
        .await
        .0,
        StatusCode::PRECONDITION_REQUIRED
    );
    assert_eq!(
        request(
            Arc::clone(&state),
            "/api/v1/knowledge/mutations",
            update.clone(),
            Some("update"),
            Some("2"),
            true
        )
        .await
        .0,
        StatusCode::BAD_REQUEST
    );
    let updated = request(
        Arc::clone(&state),
        "/api/v1/knowledge/mutations",
        update.clone(),
        Some("update"),
        Some("1"),
        true,
    )
    .await;
    assert_eq!(updated.0, StatusCode::OK);
    assert_eq!(updated.1["result"]["receipt"]["memory"]["version"], 2);
    assert_eq!(
        request(
            Arc::clone(&state),
            "/api/v1/knowledge/mutations",
            update,
            Some("another-update"),
            Some("1"),
            true
        )
        .await
        .0,
        StatusCode::CONFLICT
    );
    let mut foreign = scope.clone();
    foreign.tenant_id = "foreign".into();
    let forbidden = request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        json!({"scope":foreign, "query":{"operation":"get","id":"knowledge-test-memory"}}),
        None,
        None,
        true,
    )
    .await;
    assert_eq!(forbidden.0, StatusCode::FORBIDDEN);
    let deletion = json!({"scope":scope, "mutation":MemoryMutation::Delete {id:"knowledge-test-memory".into(),expected_revision:2}});
    assert_eq!(
        request(
            Arc::clone(&state),
            "/api/v1/knowledge/mutations",
            deletion,
            Some("delete"),
            Some("2"),
            true
        )
        .await
        .0,
        StatusCode::OK
    );
    let missing = request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        json!({"scope":scope,"query":{"operation":"get","id":"knowledge-test-memory"}}),
        None,
        None,
        true,
    )
    .await;
    assert_eq!(missing.0, StatusCode::NOT_FOUND);
    let changes = request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        json!({"scope":scope,"query":{"operation":"changes","after_sequence":0,"limit":20}}),
        None,
        None,
        true,
    )
    .await;
    assert_eq!(changes.0, StatusCode::OK);
    assert_eq!(changes.1["result"]["items"].as_array().unwrap().len(), 3);
    assert_eq!(changes.1["result"]["items"][2]["deleted"], true);
    state.platform_plugin_authority_v2.deactivate().await;
}
