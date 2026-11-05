use super::*;
use crate::trusted_session::{
    TrustedSessionCredentialKind, TrustedSessionRecord, TrustedSessionStore,
    TrustedSessionStoreError,
};
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    routing::get,
    Json, Router,
};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};
use tokio::sync::Semaphore;

#[derive(Default)]
struct MemoryCredential(Mutex<Option<String>>);
impl TrustedSessionStore for MemoryCredential {
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
fn broker() -> TrustedSessionBroker {
    TrustedSessionBroker::new(Arc::new(MemoryCredential::default()))
}
fn runtime() -> LocalRuntimeService {
    LocalRuntimeService {
        state: crate::local_runtime::tests::test_state("browser-login"),
        api_base_url: "http://localhost".into(),
    }
}
fn request(mode: &str) -> Value {
    json!({"conversation_id":"chat", "mode":mode, "credential":"browser-login", "tenant_id":"local", "project_id":"local-project"})
}

#[tokio::test]
async fn local_context_requires_current_session_and_existing_scoped_conversation() {
    let runtime = runtime();
    let broker = broker();
    crate::local_runtime::tests::seed_plan_conversation(&runtime.state, "chat");
    assert_eq!(
        runtime
            .browser_context(&broker, request("local"))
            .await
            .unwrap(),
        json!({"session_id":"chat"})
    );
    for (field, value) in [
        ("credential", "launch-token"),
        ("conversation_id", "missing"),
        ("project_id", "foreign"),
        ("tenant_id", "foreign"),
    ] {
        let mut input = request("local");
        input[field] = json!(value);
        assert!(
            runtime.browser_context(&broker, input).await.is_err(),
            "{field}"
        );
    }
    let mut foreign = runtime
        .state
        .session_store
        .conversation("chat")
        .unwrap()
        .unwrap();
    foreign.id = "foreign-chat".into();
    foreign.tenant_id = "foreign".into();
    runtime
        .state
        .session_store
        .insert_conversation(&foreign)
        .unwrap();
    let mut input = request("local");
    input["conversation_id"] = json!(foreign.id);
    assert!(runtime.browser_context(&broker, input).await.is_err());
    let mut forged = request("local");
    forged["caller_id"] = json!("agent");
    assert!(runtime.browser_context(&broker, forged).await.is_err());
    runtime
        .state
        .session_store
        .revoke_session("browser-login", chrono::Utc::now().timestamp_millis())
        .unwrap();
    assert!(runtime
        .browser_context(&broker, request("local"))
        .await
        .is_err());
}

#[derive(Clone)]
struct Cloud {
    response: Arc<Mutex<Value>>,
    requests: Arc<Mutex<Vec<(String, String)>>>,
    entered: Arc<Semaphore>,
    release: Arc<Semaphore>,
}
struct CloudFixture {
    state: Cloud,
    broker: TrustedSessionBroker,
    task: tokio::task::JoinHandle<()>,
}
impl Drop for CloudFixture {
    fn drop(&mut self) {
        self.task.abort();
    }
}
impl CloudFixture {
    async fn new() -> Self {
        async fn conversation(
            State(state): State<Cloud>,
            headers: HeaderMap,
            Query(query): Query<HashMap<String, String>>,
        ) -> Result<Json<Value>, StatusCode> {
            let auth = headers
                .get("authorization")
                .and_then(|value| value.to_str().ok())
                .unwrap_or_default()
                .to_string();
            let project = query.get("project_id").cloned().unwrap_or_default();
            state
                .requests
                .lock()
                .unwrap()
                .push((auth.clone(), project.clone()));
            if auth != "Bearer native-fixture" || project != "local-project" {
                return Err(StatusCode::FORBIDDEN);
            }
            state.entered.add_permits(1);
            state.release.acquire().await.unwrap().forget();
            Ok(Json(state.response.lock().unwrap().clone()))
        }
        let state = Cloud {
            response: Arc::new(Mutex::new(
                json!({"id":"chat", "tenant_id":"local", "project_id":"local-project"}),
            )),
            requests: Arc::new(Mutex::new(Vec::new())),
            entered: Arc::new(Semaphore::new(0)),
            release: Arc::new(Semaphore::new(10)),
        };
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}/api/v1", listener.local_addr().unwrap());
        let app = Router::new()
            .route("/api/v1/agent/conversations/chat", get(conversation))
            .with_state(state.clone());
        let task = tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let broker = broker();
        broker
            .save(TrustedSessionRecord {
                version: 1,
                api_base_url: base,
                runtime_mode: TrustedSessionRuntimeMode::Cloud,
                credential_kind: TrustedSessionCredentialKind::CloudBearer,
                credential: "native-fixture".into(),
                expires_at: None,
            })
            .unwrap();
        Self {
            state,
            broker,
            task,
        }
    }
}

#[tokio::test]
async fn cloud_context_uses_native_credential_and_project_query_and_rejects_wrong_scope() {
    let runtime = runtime();
    let cloud = CloudFixture::new().await;
    assert_eq!(
        runtime
            .browser_context(&cloud.broker, request("cloud"))
            .await
            .unwrap(),
        json!({"session_id":"chat"})
    );
    assert_eq!(
        cloud.state.requests.lock().unwrap()[0],
        ("Bearer native-fixture".into(), "local-project".into())
    );
    for field in ["id", "project_id", "tenant_id"] {
        let previous = cloud.state.response.lock().unwrap()[field].clone();
        cloud.state.response.lock().unwrap()[field] = json!("foreign");
        assert!(
            runtime
                .browser_context(&cloud.broker, request("cloud"))
                .await
                .is_err(),
            "{field}"
        );
        cloud.state.response.lock().unwrap()[field] = previous;
    }
    let mut input = request("cloud");
    input["project_id"] = json!("foreign");
    assert!(runtime.browser_context(&cloud.broker, input).await.is_err());
}

#[tokio::test]
async fn cloud_context_rejects_identity_rotation_during_conversation_lookup() {
    let runtime = runtime();
    let cloud = CloudFixture::new().await;
    cloud.state.release.forget_permits(10);
    let pending = runtime.browser_context(&cloud.broker, request("cloud"));
    let rotate = async {
        cloud.state.entered.acquire().await.unwrap().forget();
        cloud.broker.clear().unwrap();
        cloud.state.release.add_permits(1);
    };
    let (result, ()) = tokio::join!(pending, rotate);
    assert_eq!(result.unwrap_err(), "browser_context_changed");
}
