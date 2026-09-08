use super::*;
use crate::trusted_session::TrustedSessionBroker;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use std::sync::atomic::Ordering;
use tower::ServiceExt;

#[path = "sync_connection_tests/support.rs"]
mod support;
use support::*;
#[path = "sync_connection_tests/admission.rs"]
mod admission;
#[path = "sync_connection_tests/lifecycle.rs"]
mod lifecycle;

async fn rpc(state: Arc<LocalRuntimeState>, path: &str, body: Value) -> (StatusCode, Value) {
    let response = crate::local_runtime::local_router_with_generation_required(state)
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(format!("/api/v1/knowledge/{path}"))
                .header("content-type", "application/json")
                .header("x-agistack-launch", TOKEN)
                .header("authorization", format!("Bearer {TOKEN}"))
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (status, serde_json::from_slice(&body).unwrap_or(Value::Null))
}

#[tokio::test]
async fn real_catalog_enrollment_and_atomic_binding_preserve_local_and_cloud_sessions() {
    let f = Fixture::new().await;
    let local = authenticated(&f.state);
    let cloud_record = f.broker.load().unwrap();
    let revision = f.observation().await;
    assert_eq!(revision.len(), 64);
    let (status, tenants) = f
        .request(
            "sync-tenants",
            json!({"scope":f.scope,"expected_connection_revision":revision}),
        )
        .await;
    assert_eq!(status, StatusCode::OK, "{tenants}");
    assert_eq!(tenants["result"]["items"][0]["name"], "Remote tenant");
    let (status,projects)=f.request("sync-projects",json!({"scope":f.scope,"expected_connection_revision":revision,"tenant_id":"remote-tenant"})).await;
    assert_eq!(status, StatusCode::OK, "{projects}");
    assert_eq!(projects["result"]["items"][0]["id"], "remote-project");
    let mut observation = f.target(&revision);
    observation
        .as_object_mut()
        .unwrap()
        .remove("expected_generation");
    let (status, enrollment) = f.request("sync-enrollment", observation).await;
    assert_eq!(status, StatusCode::OK, "{enrollment}");
    assert_eq!(enrollment["result"]["enrollment"]["enabled"], false);
    assert_eq!(
        enrollment["result"]["enrollment"]["generation"],
        f.cloud.generation()
    );
    assert_eq!(
        f.request("sync-bind", f.target(&revision)).await.0,
        StatusCode::CONFLICT
    );
    assert!(f.operation().sync_status().await.unwrap().link.is_none());
    let (status, enrolled) = f.request("sync-enroll", f.target(&revision)).await;
    assert_eq!(status, StatusCode::OK, "{enrolled}");
    assert!(enrolled["result"]["enrollment"]["enabled"]
        .as_bool()
        .unwrap());
    let (status, bound) = f.request("sync-bind", f.target(&revision)).await;
    assert_eq!(status, StatusCode::OK, "{bound}");
    assert_eq!(bound["result"]["association_state"], "verified");
    assert_eq!(
        bound["result"]["status"]["link"]["remote_actor_id"],
        "remote-actor"
    );
    assert_eq!(
        bound["result"]["connection"]["authority"],
        format!("{}/api/v1", f.base)
    );
    assert!(!bound.to_string().contains("cloud-test-credential"));
    assert_eq!(
        f.request("sync-bind", f.target(&revision)).await.1["result"]["status"]["replica_id"],
        bound["result"]["status"]["replica_id"]
    );
    let operation = f.operation();
    operation
        .mutate("local-create", mutation(&local))
        .await
        .unwrap();
    let (status, pushed) = f.request("sync-push", json!({"scope":f.scope})).await;
    assert_eq!(status, StatusCode::OK, "{pushed}");
    assert_eq!(f.cloud.posts.load(Ordering::SeqCst), 2);
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 0);
    assert_eq!(authenticated(&f.state).session_id, local.session_id);
    assert_eq!(
        authenticated(&f.state).workspace.project_id,
        local.workspace.project_id
    );
    assert_eq!(f.broker.load().unwrap(), cloud_record);
}

#[tokio::test]
async fn full_production_pages_are_read_and_inconsistent_or_duplicate_pages_are_rejected() {
    let f = Fixture::new().await;
    let revision = f.observation().await;
    f.cloud.catalog.lock().unwrap()["tenants"]["tenants"] = json!((0..101)
        .map(|id| json!({"id":format!("tenant-{id}"),"name":format!("Tenant {id}")}))
        .collect::<Vec<_>>());
    let request = json!({"scope":f.scope,"expected_connection_revision":revision});
    let (status, result) = f.request("sync-tenants", request.clone()).await;
    assert_eq!(status, StatusCode::OK, "{result}");
    assert_eq!(result["result"]["items"].as_array().unwrap().len(), 101);
    assert_eq!(
        f.cloud
            .calls
            .lock()
            .unwrap()
            .iter()
            .filter(|phase| **phase == Phase::Tenants)
            .count(),
        2
    );
    for invalid in [
        json!({"tenants":[{"id":"tenant-100","name":"T"}],"total":102,"page":2,"page_size":100}),
        json!({"tenants":[{"id":"tenant-0","name":"T"}],"total":101,"page":2,"page_size":100}),
        json!({"tenants":[],"total":101,"page":2,"page_size":100}),
        json!({"tenants":[{"id":"tenant-100","name":"T"}],"total":101,"page":1,"page_size":100}),
    ] {
        f.cloud
            .overrides
            .lock()
            .unwrap()
            .insert(("tenants".into(), 2), invalid);
        assert_eq!(
            f.request("sync-tenants", request.clone()).await.0,
            StatusCode::BAD_GATEWAY
        );
    }
}

#[tokio::test]
async fn enrollment_lost_response_is_observed_without_automatic_retry_or_local_binding() {
    let f = Fixture::new().await;
    let revision = f.observation().await;
    f.cloud.fail_enroll_response.store(true, Ordering::SeqCst);
    assert_eq!(
        f.request("sync-enroll", f.target(&revision)).await.0,
        StatusCode::BAD_GATEWAY
    );
    assert_eq!(f.cloud.posts.load(Ordering::SeqCst), 1);
    assert!(f.operation().sync_status().await.unwrap().link.is_none());
    let mut observation = f.target(&revision);
    observation
        .as_object_mut()
        .unwrap()
        .remove("expected_generation");
    assert_eq!(
        f.request("sync-enrollment", observation).await.1["result"]["enrollment"]["enabled"],
        true
    );
    assert_eq!(f.cloud.posts.load(Ordering::SeqCst), 1);
    assert_eq!(
        f.request("sync-bind", f.target(&revision)).await.0,
        StatusCode::OK
    );
}

#[tokio::test]
async fn unverified_legacy_link_does_not_allow_implicit_origin_binding_on_first_push() {
    let f = Fixture::new().await;
    let operation = f.operation();
    operation
        .configure_sync_link(agistack_core::knowledge::sync::KnowledgeSyncLink {
            remote_tenant_id: "remote-tenant".into(),
            remote_project_id: "remote-project".into(),
            remote_actor_id: "remote-actor".into(),
        })
        .await
        .unwrap();
    operation
        .mutate("create", mutation(&authenticated(&f.state)))
        .await
        .unwrap();
    f.cloud.enabled.store(true, Ordering::SeqCst);
    assert_eq!(
        f.request("sync-push", json!({"scope":f.scope})).await.0,
        StatusCode::CONFLICT
    );
    assert_eq!(f.cloud.posts.load(Ordering::SeqCst), 0);
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
    let revision = f.observation().await;
    assert_eq!(
        f.request("sync-bind", f.target(&revision)).await.0,
        StatusCode::OK
    );
    assert_eq!(
        f.request("sync-push", json!({"scope":f.scope})).await.0,
        StatusCode::OK
    );
}
