//! The fixture is serialized by the production Python auth.User schema.
use super::sync_cloud_fixture::install_unbound;
use super::*;
use crate::local_runtime::knowledge_authority_v2::sync_transport::VerifiedCloudTransport;
use agistack_core::knowledge::sync::KnowledgeSyncLink;
use axum::{routing::get, Json, Router};
use std::sync::atomic::{AtomicUsize, Ordering};

pub(super) fn auth_me_fixture() -> Value {
    serde_json::from_str(include_str!("auth_me_fixture.json")).unwrap()
}

async fn verify(user: Value, actor: &str) -> (bool, usize) {
    let project_calls = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&project_calls);
    let app = Router::new()
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/enrollment",
            get(super::sync_cloud_fixture::enrollment),
        )
        .route("/api/v1/auth/me", get(move || async move { Json(user) }))
        .route(
            "/api/v1/projects/remote-project",
            get(move || async move {
                counter.fetch_add(1, Ordering::SeqCst);
                Json(json!({"id":"remote-project","tenant_id":"remote-tenant"}))
            }),
        );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    let broker = install_unbound(&state, &directory, base);
    let result = VerifiedCloudTransport::connect(
        &broker,
        KnowledgeSyncLink {
            remote_tenant_id: "remote-tenant".into(),
            remote_project_id: "remote-project".into(),
            remote_actor_id: actor.into(),
        },
    )
    .await;
    server.abort();
    (result.is_ok(), project_calls.load(Ordering::SeqCst))
}

#[tokio::test]
async fn production_auth_schema_connects_without_id_alias() {
    let user = auth_me_fixture();
    assert!(user.get("id").is_none());
    assert_eq!(verify(user, "remote-actor").await, (true, 1));
}

#[tokio::test]
async fn invalid_auth_identity_never_reaches_project_authorization() {
    for field in ["user_id", "is_active"] {
        let mut missing = auth_me_fixture();
        missing.as_object_mut().unwrap().remove(field);
        missing["id"] = json!("remote-actor");
        assert_eq!(verify(missing, "remote-actor").await, (false, 0));
    }
    for actor in [
        json!(null),
        json!(false),
        json!(123),
        json!([]),
        json!({}),
        json!(""),
        json!(" "),
        json!("wrong"),
        json!(" remote-actor "),
    ] {
        let mut user = auth_me_fixture();
        user["user_id"] = actor;
        user["id"] = json!("remote-actor");
        assert_eq!(verify(user, "remote-actor").await, (false, 0));
    }
    for active in [
        json!(null),
        json!(false),
        json!(1),
        json!("true"),
        json!([]),
        json!({}),
    ] {
        let mut user = auth_me_fixture();
        user["is_active"] = active;
        assert_eq!(verify(user, "remote-actor").await, (false, 0));
    }
    for actor in ["", " ", " remote-actor "] {
        let mut user = auth_me_fixture();
        user["user_id"] = json!(actor);
        assert_eq!(verify(user, actor).await, (false, 0));
    }
}
