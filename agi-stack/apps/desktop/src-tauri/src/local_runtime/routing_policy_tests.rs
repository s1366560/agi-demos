use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use axum::{body::Body, http::Request};
use chrono::Utc;
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::*;

const LOCAL_ROUTING_POLICY_URI: &str =
    "/api/v1/llm-providers/routing-policy?project_id=local-project&workspace_id=local-workspace";

struct RecordingLlm {
    label: &'static str,
    succeeds: bool,
    calls: Arc<Mutex<Vec<String>>>,
}

struct PendingLlm {
    label: &'static str,
    calls: Arc<Mutex<Vec<String>>>,
}

impl PendingLlm {
    fn record(&self, operation: &str) {
        self.calls
            .lock()
            .expect("pending LLM calls")
            .push(format!("{}:{operation}", self.label));
    }
}

#[async_trait]
impl LlmPort for PendingLlm {
    async fn extract_memory(&self, _episode: &Episode) -> CoreResult<MemoryDraft> {
        self.record("extract_memory");
        std::future::pending().await
    }

    async fn decide(
        &self,
        _goal: &str,
        _round: u64,
        _transcript: &[TranscriptEntry],
        _available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        self.record("decide");
        std::future::pending().await
    }
}

impl RecordingLlm {
    fn record(&self, operation: &str) -> CoreResult<()> {
        self.calls
            .lock()
            .expect("recording LLM calls")
            .push(format!("{}:{operation}", self.label));
        if self.succeeds {
            Ok(())
        } else {
            Err(CoreError::Llm(format!("{} unavailable", self.label)))
        }
    }
}

#[async_trait]
impl LlmPort for RecordingLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        self.record("extract_memory")?;
        Ok(MemoryDraft {
            title: self.label.to_string(),
            content: episode.content.clone(),
            tags: Vec::new(),
            entities: Vec::new(),
        })
    }

    async fn decide(
        &self,
        _goal: &str,
        _round: u64,
        _transcript: &[TranscriptEntry],
        _available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        self.record("decide")?;
        Ok(AgentAction::Finish {
            answer: self.label.to_string(),
        })
    }
}

fn test_root() -> PathBuf {
    std::env::temp_dir().join(format!(
        "agistack-routing-policy-runtime-{}",
        Uuid::new_v4()
    ))
}

fn test_state(credential: &str) -> Arc<LocalRuntimeState> {
    let root = test_root();
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root,
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    state
}

fn file_state(
    store_path: &Path,
    workspace_root: &Path,
    credential: &str,
) -> Arc<LocalRuntimeState> {
    let tool_host = LocalToolHost::new(workspace_root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::open(store_path).expect("session store");
    Arc::new(
        LocalRuntimeState::new(
            workspace_root.to_path_buf(),
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    )
}

fn authenticated_json_request(
    method: &str,
    uri: &str,
    credential: &str,
    body: Value,
) -> Request<Body> {
    Request::builder()
        .method(method)
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential)
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .expect("authenticated JSON request")
}

async fn response_json(response: axum::response::Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}

fn seed_active_provider(
    state: &LocalRuntimeState,
    tenant_id: &str,
    provider_id: &str,
    model: &str,
    allowed_models: &[&str],
) -> u64 {
    let current = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            tenant_id,
            provider_id,
        )
        .expect("load provider");
    let expected_revision = current
        .as_ref()
        .and_then(|provider| provider.get("revision"))
        .and_then(Value::as_u64);
    let stored = state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            tenant_id,
            provider_id,
            "active",
            expected_revision,
            json!({
                "id": provider_id,
                "name": provider_id,
                "provider_type": "openai_compatible",
                "tenant_id": tenant_id,
                "is_active": true,
                "base_url": "http://127.0.0.1:11434/v1",
                "auth_method": "none",
                "credential_source": "none",
                "credential_configured": false,
                "llm_model": model,
                "allowed_models": allowed_models,
                "secondary_models": [],
                "health_status": "not_checked",
            }),
            Utc::now().timestamp_millis(),
        )
        .expect("seed active provider");
    stored["revision"].as_u64().expect("provider revision")
}

fn policy_body(
    expected_revision: u64,
    default_provider: &str,
    default_model: &str,
    fallbacks: Value,
) -> Value {
    json!({
        "project_id": "local-project",
        "workspace_id": "local-workspace",
        "expected_revision": expected_revision,
        "roles": {
            "default": {
                "provider_id": default_provider,
                "model_id": default_model,
            },
            "fast": null,
            "coding": null,
            "vision": null,
        },
        "fallbacks": fallbacks,
    })
}

fn switch_context(
    state: &LocalRuntimeState,
    credential: &str,
    tenant_id: &str,
    project_id: &str,
    expected_revision: u64,
    idempotency_key: &str,
) {
    let authenticated = state
        .session_store
        .validate_session_credential(credential, Utc::now().timestamp_millis())
        .expect("validate session")
        .expect("authenticated context");
    state
        .session_store
        .switch_workspace_context(
            &authenticated,
            &ContextSwitchRequest {
                tenant_id: tenant_id.to_string(),
                project_id: project_id.to_string(),
                expected_revision,
                idempotency_key: idempotency_key.to_string(),
            },
            Utc::now().timestamp_millis(),
        )
        .expect("switch workspace context");
}

#[path = "routing_policy_tests/persistence.rs"]
mod persistence;

#[path = "routing_policy_tests/execution.rs"]
mod execution;

#[path = "routing_policy_tests/mutation.rs"]
mod mutation;
