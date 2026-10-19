use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Mutex,
};

use async_trait::async_trait;
use axum::{
    body::{to_bytes, Body},
    extract::State,
    http::{Request, StatusCode},
    middleware::{self, Next},
    response::Response,
    routing::{get, post},
    Extension, Router,
};
use serde_json::{json, Value};
use tower::ServiceExt;

use super::*;
use crate::{
    auth::Identity, feature_operation_http_v2::guard_with_admission,
    feature_operation_owners_v2::owner,
};

#[derive(Default)]
struct Repository {
    snapshots: Mutex<BTreeMap<String, Value>>,
    denied: AtomicBool,
    unavailable: AtomicBool,
    reads: AtomicUsize,
}

fn scope_key(scope: &ScopeV2) -> String {
    scope
        .project_id
        .clone()
        .or_else(|| scope.tenant_id.clone())
        .unwrap_or_else(|| "root".into())
}

#[async_trait]
impl FeatureOperationRepositoryV2 for Repository {
    async fn support_tenants(
        &self,
        _: &str,
        status: Option<&str>,
    ) -> Result<Vec<Option<String>>, FeatureAdmissionErrorV2> {
        if status == Some("open") {
            return Ok(vec![Some("tenant".into())]);
        }
        Ok(vec![
            Some("tenant".into()),
            Some("other-tenant".into()),
            None,
        ])
    }
    async fn resource_scope(
        &self,
        kind: &str,
        id: &str,
    ) -> Result<Option<ScopeIdentifiersV2>, FeatureAdmissionErrorV2> {
        let project_id = match (kind, id) {
            ("project", "p1" | "p2") => Some(id.into()),
            ("memory", "m1") | ("skill", "s1") => Some("p1".into()),
            _ => return Ok(None),
        };
        Ok(Some(ScopeIdentifiersV2 {
            tenant_id: Some("tenant".into()),
            project_id,
        }))
    }
    async fn default_tenant(&self, _: &str) -> Result<Option<String>, FeatureAdmissionErrorV2> {
        Ok(Some("tenant".into()))
    }
    async fn accessible_projects(
        &self,
        _: &str,
        _: Option<&str>,
    ) -> Result<Vec<ScopeIdentifiersV2>, FeatureAdmissionErrorV2> {
        Ok(vec![ScopeIdentifiersV2 {
            tenant_id: Some("tenant".into()),
            project_id: Some("p1".into()),
        }])
    }
    async fn authorize(&self, _: &str, _: &ScopeV2) -> Result<bool, FeatureAdmissionErrorV2> {
        Ok(!self.denied.load(Ordering::SeqCst))
    }
    async fn accepted(
        &self,
        scope: &ScopeV2,
    ) -> Result<AcceptedFeatureConfigurationV2, FeatureAdmissionErrorV2> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        if self.unavailable.load(Ordering::SeqCst) {
            return Err(FeatureAdmissionErrorV2::unavailable());
        }
        self.snapshots
            .lock()
            .unwrap()
            .get(&scope_key(scope))
            .cloned()
            .map(AcceptedFeatureConfigurationV2::Snapshot)
            .ok_or_else(FeatureAdmissionErrorV2::unavailable)
    }
}

fn snapshot(disabled: &[&str]) -> Value {
    let mut entries = bootstrap_entries().unwrap();
    for feature in disabled {
        entries
            .get_mut(&format!("builtin-web-feature-{feature}"))
            .expect("declared feature")
            .enabled = false;
    }
    json!({"entries": entries.into_values().collect::<Vec<_>>()})
}

fn setup() -> (Arc<Repository>, FeatureOperationAdmissionV2) {
    let repository = Arc::new(Repository::default());
    for key in ["root", "tenant", "p1", "p2"] {
        repository
            .snapshots
            .lock()
            .unwrap()
            .insert(key.into(), snapshot(&[]));
    }
    let admission = FeatureOperationAdmissionV2 {
        repository: Some(repository.clone()),
    };
    (repository, admission)
}

#[tokio::test]
async fn missing_private_project_requires_initialization_and_does_not_follow_parent_changes() {
    let (repository, admission) = setup();
    repository.snapshots.lock().unwrap().remove("p1");
    repository
        .snapshots
        .lock()
        .unwrap()
        .insert("tenant".into(), snapshot(&["tenant-skills"]));
    let check = || admission.admit_project("user", "tenant", "p1", &["tenant-skills"]);
    assert_eq!(
        check().await.unwrap_err().code,
        "feature_configuration_unavailable"
    );
    repository
        .snapshots
        .lock()
        .unwrap()
        .insert("p1".into(), snapshot(&[]));
    check().await.unwrap();
    // The private accepted state remains authoritative after parent changes.
    repository
        .snapshots
        .lock()
        .unwrap()
        .insert("root".into(), snapshot(&["tenant-skills"]));
    check().await.unwrap();
}

#[tokio::test]
async fn resource_ancestry_rejects_conflicting_hints_and_authorizes_before_configuration() {
    let (repository, admission) = setup();
    let ownership = owner("GET", "/api/v1/skills/:skill_id").unwrap();
    let arguments = BTreeMap::from([
        ("skill_id".into(), "s1".into()),
        ("project_id".into(), "p2".into()),
    ]);
    assert_eq!(
        admission
            .admit("user", &ownership, &arguments, ownership.feature_ids)
            .await
            .unwrap_err()
            .status,
        StatusCode::NOT_FOUND
    );
    assert_eq!(repository.reads.load(Ordering::SeqCst), 0);
    repository.denied.store(true, Ordering::SeqCst);
    assert_eq!(
        admission
            .admit_project("user", "tenant", "p1", &["tenant-skills"])
            .await
            .unwrap_err()
            .code,
        "scope_read_forbidden"
    );
    assert_eq!(repository.reads.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn unavailable_accepted_store_fails_closed_and_new_websocket_turn_reads_current_state() {
    let (repository, admission) = setup();
    admission
        .admit_project("user", "tenant", "p1", &["tenant-agent-workspace"])
        .await
        .unwrap();
    repository
        .snapshots
        .lock()
        .unwrap()
        .insert("p1".into(), snapshot(&["tenant-agent-workspace"]));
    assert_eq!(
        admission
            .admit_project("user", "tenant", "p1", &["tenant-agent-workspace"])
            .await
            .unwrap_err()
            .code,
        "feature_disabled"
    );
    repository.unavailable.store(true, Ordering::SeqCst);
    assert_eq!(
        admission
            .admit_project("user", "tenant", "p1", &["tenant-agent-workspace"])
            .await
            .unwrap_err()
            .status,
        StatusCode::SERVICE_UNAVAILABLE
    );
}

async fn test_guard(
    State(admission): State<FeatureOperationAdmissionV2>,
    request: Request<Body>,
    next: Next,
) -> Response {
    guard_with_admission(&admission, request, next).await
}

fn router(admission: FeatureOperationAdmissionV2, invocations: Arc<AtomicUsize>) -> Router {
    Router::new()
        .route("/api/v1/support/tickets", get(|| async { "tickets" }))
        .route(
            "/api/v1/maintenance/status",
            get(|| async { "maintenance" }),
        )
        .route(
            "/api/v1/skills",
            post({
                let invocations = invocations.clone();
                move |body: String| async move {
                    invocations.fetch_add(1, Ordering::SeqCst);
                    body
                }
            }),
        )
        .route(
            "/api/v1/skills/import/zip",
            post({
                let invocations = invocations.clone();
                move |body: String| async move {
                    invocations.fetch_add(1, Ordering::SeqCst);
                    body
                }
            }),
        )
        .route(
            "/api/v1/memories/:id",
            get({
                let invocations = invocations.clone();
                move || async move {
                    invocations.fetch_add(1, Ordering::SeqCst);
                    "memory"
                }
            }),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/messages",
            get(|| async { "saved history" }),
        )
        .layer(middleware::from_fn_with_state(admission, test_guard))
        .layer(Extension(Identity {
            user_id: "user".into(),
            _api_key_id: "test".into(),
        }))
}

#[tokio::test]
async fn aggregates_admit_all_returned_project_and_ticket_tenant_scopes() {
    let (repository, admission) = setup();
    repository
        .snapshots
        .lock()
        .unwrap()
        .insert("p1".into(), snapshot(&["project-maintenance"]));
    repository
        .snapshots
        .lock()
        .unwrap()
        .insert("other-tenant".into(), snapshot(&["project-support"]));
    let app = router(admission, Arc::new(AtomicUsize::new(0)));
    for (uri, expected) in [
        ("/api/v1/maintenance/status", StatusCode::FORBIDDEN),
        ("/api/v1/maintenance/status?project_id=p2", StatusCode::OK),
        ("/api/v1/support/tickets", StatusCode::FORBIDDEN),
        ("/api/v1/support/tickets?tenant_id=tenant", StatusCode::OK),
        ("/api/v1/support/tickets?status=open", StatusCode::OK),
        ("/api/v1/support/tickets?status=", StatusCode::FORBIDDEN),
    ] {
        let response = app
            .clone()
            .oneshot(Request::builder().uri(uri).body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), expected, "{uri}");
    }
}

#[tokio::test]
async fn direct_http_json_and_multipart_block_before_handler_and_preserve_allowed_body() {
    let (repository, admission) = setup();
    repository
        .snapshots
        .lock()
        .unwrap()
        .insert("p1".into(), snapshot(&["tenant-skills"]));
    let invocations = Arc::new(AtomicUsize::new(0));
    let app = router(admission, invocations.clone());
    for (content_type, body, uri) in [
        ("application/json", "{\"project_id\":\"p1\"}", "/api/v1/skills"),
        ("multipart/form-data; boundary=scope", "--scope\r\nContent-Disposition: form-data; name=\"project_id\"\r\n\r\np1\r\n--scope--\r\n", "/api/v1/skills/import/zip"),
    ] {
        let response = app.clone().oneshot(Request::builder().method("POST").uri(uri).header("content-type", content_type).body(Body::from(body)).unwrap()).await.unwrap();
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
    }
    assert_eq!(invocations.load(Ordering::SeqCst), 0);
    let body = "{\"project_id\":\"p2\",\"name\":\"allowed\"}";
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/skills")
                .header("content-type", "application/json")
                .body(Body::from(body))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(to_bytes(response.into_body(), 4096).await.unwrap(), body);
    assert_eq!(invocations.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn direct_resource_ignores_undeclared_query_hints_and_replay_remains_available() {
    let (repository, admission) = setup();
    repository.snapshots.lock().unwrap().insert(
        "p1".into(),
        snapshot(&["project-memories", "tenant-agent-workspace"]),
    );
    let invocations = Arc::new(AtomicUsize::new(0));
    let app = router(admission, invocations.clone());
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/v1/memories/m1?project_id=p2")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    assert_eq!(invocations.load(Ordering::SeqCst), 0);
    repository.unavailable.store(true, Ordering::SeqCst);
    let response = app
        .oneshot(
            Request::builder()
                .uri("/api/v1/agent/conversations/c1/messages")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
}

#[tokio::test]
async fn accepted_operation_finishes_after_disable_while_next_operation_is_blocked() {
    let (repository, admission) = setup();
    let started = Arc::new(tokio::sync::Notify::new());
    let finish = Arc::new(tokio::sync::Notify::new());
    let app = Router::new()
        .route(
            "/api/v1/skills",
            post({
                let started = started.clone();
                let finish = finish.clone();
                move || {
                    let started = started.clone();
                    let finish = finish.clone();
                    async move {
                        started.notify_one();
                        finish.notified().await;
                        "finished"
                    }
                }
            }),
        )
        .layer(middleware::from_fn_with_state(admission, test_guard))
        .layer(Extension(Identity {
            user_id: "user".into(),
            _api_key_id: "test".into(),
        }));
    let request = || {
        Request::builder()
            .method("POST")
            .uri("/api/v1/skills")
            .header("content-type", "application/json")
            .body(Body::from("{\"project_id\":\"p1\"}"))
            .unwrap()
    };
    let active = tokio::spawn(app.clone().oneshot(request()));
    started.notified().await;
    repository
        .snapshots
        .lock()
        .unwrap()
        .insert("p1".into(), snapshot(&["tenant-skills"]));
    assert_eq!(
        app.oneshot(request()).await.unwrap().status(),
        StatusCode::FORBIDDEN
    );
    finish.notify_one();
    assert_eq!(active.await.unwrap().unwrap().status(), StatusCode::OK);
}
