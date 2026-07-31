use std::{path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Request, StatusCode},
    response::Response,
};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

struct TenantProjectsTestRuntime {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for TenantProjectsTestRuntime {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn test_runtime(launch_credential: &str) -> TenantProjectsTestRuntime {
    let root = std::env::temp_dir().join(format!("agistack-tenant-projects-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create tenant projects workspace");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.clone(),
            LocalToolHost::new(&root).expect("tool host"),
            Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints")),
            launch_credential.to_string(),
            DesktopSessionStore::in_memory().expect("session store"),
        )
        .expect("local runtime state"),
    );
    TenantProjectsTestRuntime { root, state }
}

async fn create_session(app: &Router, launch: &str) -> String {
    let response = app
        .clone()
        .oneshot(json_request(
            "POST",
            "/api/v1/auth/local-session",
            launch,
            None,
            r#"{"trusted_device":false}"#,
        ))
        .await
        .expect("create session response");
    assert_eq!(response.status(), StatusCode::OK);
    response_json(response).await["access_token"]
        .as_str()
        .expect("session access token")
        .to_string()
}

#[tokio::test]
async fn local_project_crud_is_tenant_scoped_and_returns_structured_authority() {
    let launch = "tenant-projects-launch";
    let runtime = test_runtime(launch);
    let app = local_router(Arc::clone(&runtime.state));
    let session = create_session(&app, launch).await;

    let list = app
        .clone()
        .oneshot(json_request(
            "GET",
            "/api/v1/tenant-projects?tenant_id=northstar&page=1&page_size=20",
            launch,
            Some(&session),
            "",
        ))
        .await
        .expect("list response");
    assert_eq!(list.status(), StatusCode::OK);
    let list = response_json(list).await;
    assert_eq!(list["availability"], "degraded");
    assert_eq!(list["scope"]["tenant_id"], "northstar");
    assert_eq!(
        list["allowed_actions"],
        serde_json::json!(["view", "list", "create", "update", "delete"])
    );
    assert!(list["projects"]
        .as_array()
        .is_some_and(|projects| !projects.is_empty()));

    let create = app
        .clone()
        .oneshot(mutation_request(
            "POST",
            "/api/v1/tenant-projects",
            launch,
            Some(&session),
            r#"{"tenant_id":"northstar","name":"Native Project","description":"Created locally"}"#,
            "tenant-project-create",
        ))
        .await
        .expect("create response");
    assert_eq!(create.status(), StatusCode::OK);
    let created = response_json(create).await;
    let project_id = created["id"].as_str().expect("project id").to_string();
    assert_eq!(created["tenant_id"], "northstar");
    assert_eq!(created["owner_id"], "local-user");
    assert_eq!(created["is_public"], false);

    let update = app
        .clone()
        .oneshot(mutation_request(
            "PUT",
            &format!("/api/v1/tenant-projects/{project_id}"),
            launch,
            Some(&session),
            r#"{"name":"Updated Native Project","description":"Updated locally"}"#,
            "tenant-project-update",
        ))
        .await
        .expect("update response");
    assert_eq!(update.status(), StatusCode::OK);
    assert_eq!(
        response_json(update).await["name"],
        "Updated Native Project"
    );

    let delete = app
        .clone()
        .oneshot(mutation_request(
            "POST",
            &format!("/api/v1/tenant-projects/{project_id}/archive"),
            launch,
            Some(&session),
            "",
            "tenant-project-delete",
        ))
        .await
        .expect("delete response");
    assert_eq!(delete.status(), StatusCode::OK);

    let detail = app
        .clone()
        .oneshot(json_request(
            "GET",
            &format!("/api/v1/tenant-projects/{project_id}?tenant_id=northstar"),
            launch,
            Some(&session),
            "",
        ))
        .await
        .expect("detail response");
    assert_eq!(detail.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn local_project_mutations_replay_receipts_and_reject_changed_payloads() {
    let launch = "tenant-projects-idempotency-launch";
    let runtime = test_runtime(launch);
    let app = local_router(Arc::clone(&runtime.state));
    let session = create_session(&app, launch).await;
    let create_body =
        r#"{"tenant_id":"northstar","name":"Replay Project","description":"Created once"}"#;

    let created = response_json(
        app.clone()
            .oneshot(mutation_request(
                "POST",
                "/api/v1/tenant-projects",
                launch,
                Some(&session),
                create_body,
                "tenant-project-create-replay",
            ))
            .await
            .expect("create response"),
    )
    .await;
    let project_id = created["id"].as_str().expect("project id").to_string();

    let replayed = response_json(
        local_router(Arc::clone(&runtime.state))
            .oneshot(mutation_request(
                "POST",
                "/api/v1/tenant-projects",
                launch,
                Some(&session),
                create_body,
                "tenant-project-create-replay",
            ))
            .await
            .expect("create replay response"),
    )
    .await;
    assert_eq!(replayed, created);

    let create_conflict = app
        .clone()
        .oneshot(mutation_request(
            "POST",
            "/api/v1/tenant-projects",
            launch,
            Some(&session),
            r#"{"tenant_id":"northstar","name":"Changed Replay","description":"Different"}"#,
            "tenant-project-create-replay",
        ))
        .await
        .expect("create conflict response");
    assert_eq!(create_conflict.status(), StatusCode::CONFLICT);
    assert_eq!(
        response_json(create_conflict).await["reason_code"],
        "local_project_idempotency_conflict"
    );

    let update_body = r#"{"name":"Replay Project Updated","description":"Updated once"}"#;
    let updated = response_json(
        app.clone()
            .oneshot(mutation_request(
                "PUT",
                &format!("/api/v1/tenant-projects/{project_id}"),
                launch,
                Some(&session),
                update_body,
                "tenant-project-update-replay",
            ))
            .await
            .expect("update response"),
    )
    .await;
    let update_replay = response_json(
        app.clone()
            .oneshot(mutation_request(
                "PUT",
                &format!("/api/v1/tenant-projects/{project_id}"),
                launch,
                Some(&session),
                update_body,
                "tenant-project-update-replay",
            ))
            .await
            .expect("update replay response"),
    )
    .await;
    assert_eq!(update_replay, updated);

    let deleted = response_json(
        app.clone()
            .oneshot(mutation_request(
                "POST",
                &format!("/api/v1/tenant-projects/{project_id}/archive"),
                launch,
                Some(&session),
                "",
                "tenant-project-delete-replay",
            ))
            .await
            .expect("delete response"),
    )
    .await;
    let delete_replay = response_json(
        app.clone()
            .oneshot(mutation_request(
                "POST",
                &format!("/api/v1/tenant-projects/{project_id}/archive"),
                launch,
                Some(&session),
                "",
                "tenant-project-delete-replay",
            ))
            .await
            .expect("delete replay response"),
    )
    .await;
    assert_eq!(delete_replay, deleted);
}

#[tokio::test]
async fn local_project_routes_reject_scope_drift_and_active_project_deletion() {
    let launch = "tenant-projects-scope-launch";
    let runtime = test_runtime(launch);
    let app = local_router(Arc::clone(&runtime.state));
    let session = create_session(&app, launch).await;

    let drift = app
        .clone()
        .oneshot(json_request(
            "GET",
            "/api/v1/tenant-projects?tenant_id=orbital&page=1&page_size=20",
            launch,
            Some(&session),
            "",
        ))
        .await
        .expect("scope drift response");
    assert_eq!(drift.status(), StatusCode::FORBIDDEN);

    let missing_idempotency = app
        .clone()
        .oneshot(json_request(
            "POST",
            "/api/v1/tenant-projects",
            launch,
            Some(&session),
            r#"{"tenant_id":"northstar","name":"Missing Key","description":""}"#,
        ))
        .await
        .expect("missing idempotency response");
    assert_eq!(
        missing_idempotency.status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );
    assert_eq!(
        response_json(missing_idempotency).await["reason_code"],
        "local_project_idempotency_key_invalid"
    );

    let active_delete = app
        .clone()
        .oneshot(mutation_request(
            "POST",
            "/api/v1/tenant-projects/desktop-client/archive",
            launch,
            Some(&session),
            "",
            "tenant-project-active-delete",
        ))
        .await
        .expect("active delete response");
    assert_eq!(active_delete.status(), StatusCode::CONFLICT);
    assert_eq!(
        response_json(active_delete).await["reason_code"],
        "local_active_project_delete_conflict"
    );
}

fn mutation_request(
    method: &str,
    uri: &str,
    launch: &str,
    session: Option<&str>,
    body: &str,
    idempotency_key: &str,
) -> Request<Body> {
    let mut request = json_request(method, uri, launch, session, body);
    request.headers_mut().insert(
        "idempotency-key",
        idempotency_key.parse().expect("idempotency header"),
    );
    request
}

fn json_request(
    method: &str,
    uri: &str,
    launch: &str,
    session: Option<&str>,
    body: &str,
) -> Request<Body> {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header("x-agistack-launch", launch);
    if let Some(session) = session {
        builder = builder.header("authorization", format!("Bearer {session}"));
    }
    if !body.is_empty() {
        builder = builder.header("content-type", "application/json");
    }
    builder
        .body(Body::from(body.to_string()))
        .expect("tenant projects request")
}

async fn response_json(response: Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}
