use super::push_http_tests::{install_broker, push, setup};
use super::*;
use crate::local_runtime::local_router_with_generation_required;
use agistack_core::knowledge::sync::cloud_resolution::*;
use axum::{
    body::{to_bytes, Body},
    extract::{Path, State},
    http::{Request, StatusCode},
    routing::{get, post},
    Json, Router,
};
use std::{
    collections::BTreeMap,
    sync::{
        atomic::{AtomicBool, AtomicU16, AtomicU8, Ordering},
        Mutex,
    },
    time::Duration,
};
use tokio::sync::Notify;
use tower::ServiceExt;

#[path = "cloud_resolution_http/support.rs"]
mod support;
use support::*;

#[path = "cloud_resolution_http/admission.rs"]
mod admission;
#[path = "cloud_resolution_http/recovery.rs"]
mod recovery;
#[path = "cloud_resolution_http/session.rs"]
mod session;

#[tokio::test]
async fn cloud_commit_then_ack_failure_new_local_edit_and_same_key_replay_preserves_both() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud().await;
    install_broker(&state, &directory, base);
    assert_eq!(
        push(Arc::clone(&state), json!({"scope":scope})).await.0,
        StatusCode::OK
    );
    let body = json!({"scope":scope,"resolution":command(&cloud)});
    let db = rusqlite::Connection::open(directory.0.join("knowledge/memories.db")).unwrap();
    db.execute_batch(
        "CREATE TRIGGER fail_ack BEFORE UPDATE ON knowledge_cloud_resolutions
         WHEN NEW.receipt_json IS NOT NULL
         BEGIN SELECT RAISE(ABORT,'injected'); END;",
    )
    .unwrap();
    let failed = call(
        Arc::clone(&state),
        "sync-resolve-push",
        body.clone(),
        Some("decision"),
    )
    .await;
    assert_eq!(failed.0, StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(cloud.data.lock().unwrap().receipts.len(), 1);
    db.execute_batch("DROP TRIGGER fail_ack;").unwrap();
    edit(&operation, "new local edit").await;
    let reads = cloud.data.lock().unwrap().conflict_reads;
    cloud.forbid_conflict_get.store(true, Ordering::SeqCst);
    let resumed = call(
        Arc::clone(&state),
        "sync-resolve-push",
        body,
        Some("decision"),
    )
    .await;
    assert_eq!(resumed.0, StatusCode::OK, "{}", resumed.1);
    assert_eq!(resumed.1["result"]["pending_reconciliation"], true);
    assert_eq!(
        operation
            .get("knowledge-test-memory")
            .await
            .unwrap()
            .unwrap()
            .content,
        "new local edit"
    );
    {
        let data = cloud.data.lock().unwrap();
        assert_eq!(data.requests.len(), 2);
        assert_eq!(data.requests[0], data.requests[1]);
        assert_eq!(data.receipts.len(), 1);
        assert_eq!(data.conflict_reads, reads);
        assert_eq!(data.current["revision"], 3);
    }
    let id = resumed.1["result"]["resolution_id"].as_str().unwrap();
    let ctx = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope":scope,"query":{"operation":"reconciliation_context","resolution_id":id}}),
        None,
    )
    .await;
    assert_eq!(ctx.0, StatusCode::OK);
    assert_eq!(
        ctx.1["result"]["context"]["local"]["content"],
        "new local edit"
    );
    let reconcile = json!({
        "scope":scope,
        "resolution_id":id,
        "reconciliation":{
            "guard":{
                "expected_local_revision":2,
                "expected_remote_revision":3,
                "expected_baseline_revision":3,
                "conflict_sequences":[]
            },
            "choice":{
                "decision":"keep_both"
            }
        }
    });
    let result = call(
        Arc::clone(&state),
        "sync-reconcile-resolution",
        reconcile.clone(),
        None,
    )
    .await;
    assert_eq!(result.0, StatusCode::OK, "{}", result.1);
    assert_eq!(result.1["result"]["pending_reconciliation"], false);
    assert_eq!(
        call(
            Arc::clone(&state),
            "sync-reconcile-resolution",
            reconcile,
            None
        )
        .await
        .1["result"]["replayed"],
        true
    );
    let history = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope":scope,"query":{"operation":"resolution","resolution_id":id}}),
        None,
    )
    .await;
    let copy = history.1["result"]["record"]["reconciliation"]["copy_memory_id"]
        .as_str()
        .unwrap();
    assert_eq!(
        operation.get(copy).await.unwrap().unwrap().content,
        "new local edit"
    );
    assert_eq!(cloud.data.lock().unwrap().requests.len(), 2);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}
