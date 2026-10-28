use super::*;
use crate::trusted_session::{
    TrustedSessionCredentialKind, TrustedSessionRecord, TrustedSessionRuntimeMode,
    TrustedSessionStore, TrustedSessionStoreError,
};
use axum::{extract::State, routing::get, Json, Router};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Mutex,
};

#[path = "runtime_tests.rs"]
mod runtime_tests;

#[derive(Default)]
struct Credentials(Mutex<Option<String>>);
impl TrustedSessionStore for Credentials {
    fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError> {
        *self.0.lock().unwrap() = Some(value.into());
        Ok(())
    }
    fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError> {
        Ok(self.0.lock().unwrap().clone())
    }
    fn clear_raw(&self) -> Result<(), TrustedSessionStoreError> {
        *self.0.lock().unwrap() = None;
        Ok(())
    }
}

#[derive(Clone)]
struct Remote {
    user: Arc<Mutex<String>>,
    project: Arc<Mutex<String>>,
    role: Arc<Mutex<String>>,
    revision: Arc<AtomicU64>,
}

struct Fixture {
    state: Arc<LocalRuntimeState>,
    broker: TrustedSessionBroker,
    remote: Remote,
    task: tokio::task::JoinHandle<()>,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.task.abort();
    }
}
impl Fixture {
    async fn new() -> Self {
        let remote = Remote {
            user: Arc::new(Mutex::new("cloud-user".into())),
            project: Arc::new(Mutex::new("cloud-project".into())),
            role: Arc::new(Mutex::new("owner".into())),
            revision: Arc::new(AtomicU64::new(4)),
        };
        async fn me(State(remote): State<Remote>) -> Json<Value> {
            Json(json!({"user_id":*remote.user.lock().unwrap()}))
        }
        async fn project() -> Json<Value> {
            Json(json!({"id":"cloud-project","tenant_id":"cloud-tenant"}))
        }
        async fn context(State(remote): State<Remote>) -> Json<Value> {
            Json(json!({"context":{"tenant_id":"cloud-tenant",
                "project_id":*remote.project.lock().unwrap(),
                "revision":remote.revision.load(Ordering::SeqCst)},
                "membership_role":*remote.role.lock().unwrap()}))
        }
        let app = Router::new()
            .route("/api/v1/auth/me", get(me))
            .route("/api/v1/projects/cloud-project", get(project))
            .route("/api/v1/workspace-context", get(context))
            .with_state(remote.clone());
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let task = tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let broker = TrustedSessionBroker::new(Arc::new(Credentials::default()));
        broker
            .save(TrustedSessionRecord {
                version: 1,
                api_base_url: base,
                runtime_mode: TrustedSessionRuntimeMode::Cloud,
                credential_kind: TrustedSessionCredentialKind::CloudBearer,
                credential: "fixture-credential".into(),
                expires_at: None,
            })
            .unwrap();
        Self {
            state: crate::local_runtime::tests::test_state("device-mcp"),
            broker,
            remote,
            task,
        }
    }
    fn input(&self, operation: Value, token: Option<&str>) -> Value {
        json!({"tenant_id":"cloud-tenant","project_id":"cloud-project",
            "context_token":token,"operation":operation})
    }
    async fn call(&self, operation: Value, token: Option<&str>) -> Result<Value, String> {
        native_operation(&self.state, &self.broker, self.input(operation, token)).await
    }
    async fn token(&self) -> String {
        self.call(json!({"action":"list"}), None).await.unwrap()["context"]["token"]
            .as_str()
            .unwrap()
            .into()
    }
    fn create(&self) -> Value {
        json!({"action":"create","body":{"project_id":"cloud-project","name":"device-only",
            "server_type":"stdio","transport_config":{"command":"/usr/bin/true"},
            "idempotency_key":"create-device-only"}})
    }
}

#[tokio::test]
async fn creates_disabled_with_public_scope_and_preserves_local_catalog() {
    let fixture = Fixture::new().await;
    let token = fixture.token().await;
    let created = fixture.call(fixture.create(), Some(&token)).await.unwrap();
    assert_eq!(created["context"]["token"], token);
    assert_eq!(created["result"]["enabled"], false);
    assert_eq!(created["result"]["tenant_id"], "cloud-tenant");
    assert_eq!(created["result"]["project_id"], "cloud-project");
    assert_eq!(created["result"]["location"], "device");
    assert_eq!(
        fixture.call(json!({"action":"list"}), None).await.unwrap()["result"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert!(fixture
        .state
        .mcp_supervisor
        .list_servers(&McpScope {
            tenant_id: "cloud-tenant".into(),
            project_id: "cloud-project".into()
        })
        .unwrap()
        .is_empty());
    let server_id = created["result"]["id"].as_str().unwrap();
    assert_eq!(
        fixture
            .call(json!({"action":"test","server_id":server_id}), Some(&token))
            .await
            .unwrap_err(),
        "local_mcp_server_disabled"
    );
    let mut enabled_create = fixture.create();
    enabled_create["body"]["enabled"] = json!(true);
    assert_eq!(
        fixture
            .call(enabled_create, Some(&token))
            .await
            .unwrap_err(),
        "device_mcp_create_must_be_disabled"
    );
}

#[tokio::test]
async fn rejects_untrusted_identity_stale_context_and_non_manager_mutation() {
    let fixture = Fixture::new().await;
    let token = fixture.token().await;
    assert_eq!(
        fixture.call(fixture.create(), None).await.unwrap_err(),
        "device_mcp_context_changed"
    );
    for field in ["credential", "user_id", "api_base_url", "mode"] {
        let mut input = fixture.input(fixture.create(), Some(&token));
        input[field] = json!("forged");
        assert_eq!(
            native_operation(&fixture.state, &fixture.broker, input)
                .await
                .unwrap_err(),
            "device_mcp_request_invalid"
        );
    }
    *fixture.remote.project.lock().unwrap() = "other-project".into();
    assert_eq!(
        fixture
            .call(fixture.create(), Some(&token))
            .await
            .unwrap_err(),
        "device_mcp_scope_mismatch"
    );
    *fixture.remote.project.lock().unwrap() = "cloud-project".into();
    fixture.remote.revision.fetch_add(1, Ordering::SeqCst);
    assert_eq!(
        fixture
            .call(fixture.create(), Some(&token))
            .await
            .unwrap_err(),
        "device_mcp_context_changed"
    );
    *fixture.remote.role.lock().unwrap() = "member".into();
    let token = fixture.token().await;
    assert_eq!(
        fixture
            .call(fixture.create(), Some(&token))
            .await
            .unwrap_err(),
        "device_mcp_manager_required"
    );
    fixture.broker.clear().unwrap();
    assert_eq!(
        fixture
            .call(json!({"action":"list"}), None)
            .await
            .unwrap_err(),
        "device_mcp_trusted_cloud_required"
    );
}

#[tokio::test]
async fn account_origin_and_epoch_changes_never_reuse_another_owner_server() {
    let fixture = Fixture::new().await;
    let token = fixture.token().await;
    let created = fixture.call(fixture.create(), Some(&token)).await.unwrap();
    let id = created["result"]["id"].as_str().unwrap();
    *fixture.remote.user.lock().unwrap() = "other-user".into();
    assert_eq!(
        fixture
            .call(json!({"action":"get","server_id":id}), Some(&token))
            .await
            .unwrap_err(),
        "device_mcp_context_changed"
    );
    let other = fixture.call(json!({"action":"list"}), None).await.unwrap();
    assert_eq!(other["result"], json!([]));
    assert_eq!(
        fixture
            .call(
                json!({"action":"get","server_id":id}),
                other["context"]["token"].as_str()
            )
            .await
            .unwrap_err(),
        "local_mcp_server_not_found"
    );
    *fixture.remote.user.lock().unwrap() = "cloud-user".into();
    let old = fixture.token().await;
    let record = fixture.broker.load().unwrap().unwrap();
    fixture.broker.save(record).unwrap();
    assert_eq!(
        fixture
            .call(fixture.create(), Some(&old))
            .await
            .unwrap_err(),
        "device_mcp_context_changed"
    );
    assert_eq!(
        fixture.call(json!({"action":"list"}), None).await.unwrap()["result"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    let other_origin = Fixture::new().await;
    fixture
        .broker
        .save(other_origin.broker.load().unwrap().unwrap())
        .unwrap();
    assert_eq!(
        fixture.call(json!({"action":"list"}), None).await.unwrap()["result"],
        json!([])
    );
}

#[tokio::test]
async fn commit_fence_rejects_logout_without_running_local_mutation() {
    let fixture = Fixture::new().await;
    let authority = authority::CloudOwner::resolve(
        &fixture.broker,
        fixture.state.session_store.installation_id(),
        "cloud-tenant",
        "cloud-project",
    )
    .await
    .unwrap();
    fixture.broker.clear().unwrap();
    let mut committed = false;
    let result = authority.fence(|| {
        committed = true;
        Ok(())
    });
    assert_eq!(result.unwrap_err(), "device_mcp_context_changed");
    assert!(!committed);
}

#[tokio::test]
async fn duplicate_revision_and_credential_validation_reuse_existing_contract() {
    let fixture = Fixture::new().await;
    let token = fixture.token().await;
    let first = fixture.call(fixture.create(), Some(&token)).await.unwrap();
    let duplicate = fixture.call(fixture.create(), Some(&token)).await.unwrap();
    assert_eq!(first["result"]["id"], duplicate["result"]["id"]);
    let id = first["result"]["id"].as_str().unwrap();
    let revision = first["result"]["runtime_metadata"]["revision"]
        .as_u64()
        .unwrap();
    let update = json!({"action":"update","server_id":id,"body":{"project_id":"cloud-project",
        "enabled":true,"expected_revision":revision,"idempotency_key":"enable-device"}});
    let enabled = fixture.call(update, Some(&token)).await.unwrap();
    assert_eq!(enabled["result"]["enabled"], true);
    let stale = json!({"action":"update","server_id":id,"body":{"project_id":"cloud-project",
        "enabled":false,"expected_revision":revision,"idempotency_key":"stale-disable"}});
    assert!(fixture.call(stale, Some(&token)).await.is_err());
    let mut plaintext = fixture.create();
    plaintext["body"]["transport_config"]["environment"] = json!({"KEY":"rejected"});
    assert_eq!(
        fixture.call(plaintext, Some(&token)).await.unwrap_err(),
        "local_mcp_plaintext_environment_rejected"
    );
}
