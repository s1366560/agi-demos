use super::*;
use agistack_core::knowledge::sync::push::KnowledgeSyncTarget;
use agistack_core::knowledge::sync::KnowledgeSyncLink;
use axum::http::StatusCode;

fn target() -> KnowledgeSyncTarget {
    KnowledgeSyncTarget {
        authority: "https://cloud.example/api/v1".into(),
        link: KnowledgeSyncLink {
            remote_tenant_id: "remote-tenant".into(),
            remote_project_id: "remote-project".into(),
            remote_actor_id: "remote-actor".into(),
        },
    }
}

fn pull_page() -> Value {
    json!({"changes":[{"sequence":1,"change_id":"00000000-0000-4000-8000-000000000001","version":{
        "memory_id":"cloud-memory","revision":1,"deleted":false,"author_id":"remote-author","created_at_ms":123,
        "content":{"title":"Remote","content":"downloaded","content_type":"text","tags":[],"metadata":{},"status":"ENABLED"}
    }}],"next_cursor":1,"has_more":false})
}

async fn unbind(
    state: Arc<LocalRuntimeState>,
    scope: &KnowledgeOperationScopeV2,
    policy: &str,
) -> (StatusCode, Value) {
    pull_http_tests::request(
        state,
        "/api/v1/knowledge/sync-unbind",
        json!({"scope":scope,"policy":policy}),
    )
    .await
}

#[tokio::test]
async fn unbind_rpc_fences_pending_outbox_and_stops_sync_without_touching_copies() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = push_http_tests::setup(&state).await;
    let result = unbind(Arc::clone(&state), &scope, "keep").await;
    assert_eq!(result.0, StatusCode::OK);
    assert_eq!(result.1["result"]["association_state"], "unbound");
    assert_eq!(result.1["result"]["policy"], "keep");
    assert_eq!(result.1["result"]["fenced_outbox"], 1);
    assert_eq!(result.1["result"]["removed_local_copies"], 0);
    assert_eq!(result.1["result"]["status"]["link"], Value::Null);
    assert_eq!(result.1["result"]["status"]["pending_changes"], 0);
    // The fenced outbox never surfaces through the RPC again.
    let outbox = pull_http_tests::request(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        json!({"scope":scope,"query":{"operation":"sync_outbox","after_sequence":0,"limit":10}}),
    )
    .await;
    assert_eq!(outbox.1["result"]["items"], json!([]));
    // A repeated unbind fails closed instead of silently succeeding.
    assert_eq!(
        unbind(Arc::clone(&state), &scope, "keep").await.0,
        StatusCode::NOT_FOUND
    );
    // The kept local copy remains an ordinary local record.
    assert!(operation
        .get("knowledge-test-memory")
        .await
        .unwrap()
        .is_some());
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn unbind_delete_choice_removes_only_cloud_origin_copies() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = push_http_tests::setup(&state).await;
    operation
        .authority
        .repository()
        .unwrap()
        .accept_pull_page_durable(&operation.scope, &target(), 0, pull_page())
        .unwrap();
    assert!(operation.get("cloud-memory").await.unwrap().is_some());
    let result = unbind(Arc::clone(&state), &scope, "delete").await;
    assert_eq!(result.0, StatusCode::OK);
    assert_eq!(result.1["result"]["policy"], "delete");
    assert_eq!(result.1["result"]["removed_local_copies"], 1);
    // The downloaded copy is out of visibility; the local-origin record stays.
    assert!(operation.get("cloud-memory").await.unwrap().is_none());
    assert!(operation
        .get("knowledge-test-memory")
        .await
        .unwrap()
        .is_some());
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn unbind_requires_a_writer_role_and_a_declared_policy() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = push_http_tests::setup(&state).await;
    let auth = authenticated(&state);
    state
        .session_store
        .connection()
        .unwrap()
        .execute(
            "UPDATE desktop_tenant_memberships SET role='viewer' WHERE user_id=?1 AND tenant_id=?2",
            rusqlite::params![auth.user.user_id, auth.workspace.tenant_id],
        )
        .unwrap();
    assert_eq!(
        unbind(Arc::clone(&state), &scope, "keep").await.0,
        StatusCode::FORBIDDEN
    );
    state
        .session_store
        .connection()
        .unwrap()
        .execute(
            "UPDATE desktop_tenant_memberships SET role='owner' WHERE user_id=?1 AND tenant_id=?2",
            rusqlite::params![auth.user.user_id, auth.workspace.tenant_id],
        )
        .unwrap();
    // An undeclared policy is rejected by the wire contract before any storage work.
    let rejected = unbind(Arc::clone(&state), &scope, "wipe").await;
    assert!(rejected.0.is_client_error());
    // The failed attempts left the binding and pending work untouched.
    assert_eq!(
        operation.sync_status().await.unwrap().link,
        Some(target().link)
    );
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
    assert_eq!(
        unbind(Arc::clone(&state), &scope, "keep").await.0,
        StatusCode::OK
    );
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
}
