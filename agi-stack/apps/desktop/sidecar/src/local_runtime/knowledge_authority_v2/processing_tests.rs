use super::super::{processing::*, processing_provider::ProcessingProvider};
use super::*;
use agistack_adapters_http_llm::HttpLlm;
use agistack_core::knowledge::processing::{
    audit::*, worker::*, ProcessingRepository, ProcessingSource,
};
use axum::{extract::State, routing::post, Json, Router};
use std::sync::atomic::{AtomicBool, Ordering};
use tokio::sync::Notify;

#[path = "community_processing_tests.rs"]
mod community;
#[path = "processing_lifecycle_tests.rs"]
mod lifecycle;
#[path = "processing_rpc_entry_tests.rs"]
mod rpc;

struct Fixture {
    directory: TestDirectory,
    state: Arc<LocalRuntimeState>,
    auth: AuthenticatedContext,
    operation: Arc<KnowledgeOperationV2>,
    source: ProcessingSource,
}
impl Fixture {
    async fn new() -> Self {
        let directory = TestDirectory::new();
        let state = test_state(TOKEN);
        publish(&state, &directory, 1, true).await;
        let auth = authenticated(&state);
        let lease = Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        );
        let scope = operation_scope(&auth, &lease);
        let operation = Arc::new(KnowledgeOperationV2::admit(lease, &auth, &scope).unwrap());
        let result = operation.mutate("create", mutation(&auth)).await.unwrap();
        let source = ProcessingSource {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: auth.workspace.project_id.clone(),
            memory_id: result.receipt.memory.id,
            revision: 1,
            change_sequence: result.receipt.sequence,
        };
        Self {
            directory,
            state,
            auth,
            operation,
            source,
        }
    }
    fn repo(&self) -> Arc<SqliteKnowledgeRepository> {
        self.operation.authority.repository().unwrap()
    }
    fn audit(&self) -> ProcessingAuditRecord {
        self.repo()
            .processing_audit_durable(&self.operation.scope, &self.source, 1)
            .unwrap()
            .unwrap()
    }
    fn spawn(
        &self,
        provider: ProcessingProvider,
        options: ProcessingRunOptions,
    ) -> tokio::task::JoinHandle<Result<Option<ProcessingRunReceipt>, KnowledgeAuthorityErrorV2>>
    {
        let operation = self.operation.clone();
        let state = self.state.clone();
        let auth = self.auth.clone();
        tokio::spawn(async move {
            operation
                .process_one_with_provider(state, auth, provider, options)
                .await
        })
    }
    async fn no_projection(&self) {
        assert!(self
            .repo()
            .projection(&self.operation.scope, &self.source.memory_id)
            .await
            .unwrap()
            .is_none());
    }
}

struct Endpoint {
    entered: Arc<Notify>,
    release: Arc<Notify>,
    saw_audit: Arc<AtomicBool>,
    task: tokio::task::JoinHandle<()>,
    base: String,
}
#[derive(Clone)]
struct EndpointState {
    entered: Arc<Notify>,
    release: Arc<Notify>,
    saw_audit: Arc<AtomicBool>,
    repository: Arc<SqliteKnowledgeRepository>,
    scope: KnowledgeScope,
    source: ProcessingSource,
    action: Value,
}
impl Endpoint {
    async fn new(f: &Fixture, action: Value) -> Self {
        let entered = Arc::new(Notify::new());
        let release = Arc::new(Notify::new());
        let saw_audit = Arc::new(AtomicBool::new(false));
        let state = EndpointState {
            entered: entered.clone(),
            release: release.clone(),
            saw_audit: saw_audit.clone(),
            repository: f.repo(),
            scope: f.operation.scope.clone(),
            source: f.source.clone(),
            action,
        };
        let app = Router::new()
            .route(
                "/chat/completions",
                post(
                    |State(s): State<EndpointState>, Json(body): Json<Value>| async move {
                        let audit = s
                            .repository
                            .processing_audit_durable(&s.scope, &s.source, 1)
                            .unwrap()
                            .unwrap();
                        assert!(audit.outcome.is_none());
                        assert!(["fixture-provider", "local-runtime"]
                            .contains(&audit.invocation.provider_id.as_str()));
                        assert_eq!(audit.invocation.model_id, "fixture-model");
                        assert!(body.to_string().contains(SUBMIT_PROJECTION_TOOL));
                        s.saw_audit.store(true, Ordering::SeqCst);
                        s.entered.notify_one();
                        s.release.notified().await;
                        let status = if s.action.get("fixture_http_error").is_some() {
                            axum::http::StatusCode::INTERNAL_SERVER_ERROR
                        } else {
                            axum::http::StatusCode::OK
                        };
                        (
                            status,
                            Json(json!({"choices":[{"message":{"content":s.action.to_string()}}]})),
                        )
                    },
                ),
            )
            .with_state(state);
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let task = tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        Self {
            entered,
            release,
            saw_audit,
            task,
            base,
        }
    }
    fn provider(&self) -> ProcessingProvider {
        ProcessingProvider {
            llm: Arc::new(HttpLlm::new(&self.base, "fixture-model")),
            provider_id: "fixture-provider".into(),
            model_id: "fixture-model".into(),
        }
    }
    async fn wait(&self) {
        tokio::time::timeout(std::time::Duration::from_secs(5), self.entered.notified())
            .await
            .unwrap();
        assert!(self.saw_audit.load(Ordering::SeqCst));
    }
}
impl Drop for Endpoint {
    fn drop(&mut self) {
        self.task.abort();
    }
}
fn action(source: &ProcessingSource) -> Value {
    json!({"kind":"call_tool","tool":SUBMIT_PROJECTION_TOOL,"input_json":ProjectionSubmission {source:source.clone(),entities:vec![ExtractedEntity {name:"Knowledge".into(),kind:"Concept".into()}],relationships:vec![],rationale:"The source names this concept.".into()}})
}
fn assert_failure(outcome: &ProcessingAuditOutcome, expected: ProcessingAuditFailure) {
    assert!(matches!(outcome,ProcessingAuditOutcome::Failed {code,..} if *code==expected));
}

#[tokio::test]
async fn model_result_publishes_only_after_durable_audit_without_source_mutation() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new(&f, action(&f.source)).await;
    let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
    endpoint.wait().await;
    f.no_projection().await;
    endpoint.release.notify_one();
    let receipt = run.await.unwrap().unwrap().unwrap();
    assert_eq!(receipt.source, f.source);
    assert_eq!(receipt.attempt, 1);
    assert!(matches!(
        receipt.outcome,
        ProcessingAuditOutcome::Applied { .. }
    ));
    assert_eq!(f.audit().outcome, Some(receipt.outcome));
    assert!(f.audit().finished_at_ms.is_some());
    assert!(f.audit().latency_ms.is_some());
    assert!(f
        .repo()
        .projection(&f.operation.scope, &f.source.memory_id)
        .await
        .unwrap()
        .is_some());
    let source = f.operation.get(&f.source.memory_id).await.unwrap().unwrap();
    assert_eq!(source.version, 1);
    assert_eq!(source.content, "generation-owned content");
    assert_eq!(f.operation.changes(0, 20).await.unwrap().len(), 1);
}

#[tokio::test]
async fn non_tool_and_wrong_source_results_fail_without_persisting_rejected_text() {
    for variant in 0..3 {
        let f = Fixture::new().await;
        let mut output = action(&f.source);
        match variant {
            0 => output = json!({"kind":"finish","answer":"rejected-secret-text"}),
            1 => output["tool"] = json!("other"),
            _ => output["input_json"]["source"]["revision"] = json!(2),
        }
        let endpoint = Endpoint::new(&f, output).await;
        let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
        endpoint.wait().await;
        endpoint.release.notify_one();
        let receipt = run.await.unwrap().unwrap().unwrap();
        assert_failure(&receipt.outcome, ProcessingAuditFailure::InvalidExtraction);
        let audit = f.audit();
        let serialized = serde_json::to_string(&audit.outcome).unwrap();
        assert!(!serialized.contains("rejected-secret-text"));
        assert!(
            matches!(audit.outcome,Some(ProcessingAuditOutcome::Failed {response_digest:Some(digest),..}) if digest.len()==64)
        );
        f.no_projection().await;
    }
}

#[tokio::test]
async fn provider_errors_store_only_a_typed_failure_code() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new(
        &f,
        json!({"fixture_http_error":"private-provider-error-text"}),
    )
    .await;
    let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
    endpoint.wait().await;
    endpoint.release.notify_one();
    let outcome = run.await.unwrap().unwrap().unwrap().outcome;
    assert_failure(&outcome, ProcessingAuditFailure::ProviderUnavailable);
    assert!(!serde_json::to_string(&f.audit().outcome)
        .unwrap()
        .contains("private-provider-error-text"));
    f.no_projection().await;
}

#[tokio::test]
async fn audit_storage_failure_prevents_network_start_or_atomic_result_publication() {
    for phase in ["INSERT", "UPDATE"] {
        let f = Fixture::new().await;
        let endpoint = Endpoint::new(&f, action(&f.source)).await;
        let db = rusqlite::Connection::open(f.directory.0.join("knowledge/memories.db")).unwrap();
        db.execute_batch(&format!("CREATE TRIGGER fail_audit BEFORE {phase} ON knowledge_processing_audits BEGIN SELECT RAISE(ABORT,'injected'); END;")).unwrap();
        let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
        if phase == "UPDATE" {
            endpoint.wait().await;
            endpoint.release.notify_one();
        }
        assert!(run.await.unwrap().is_err());
        f.no_projection().await;
        if phase == "INSERT" {
            assert!(!endpoint.saw_audit.load(Ordering::SeqCst));
        } else {
            assert!(f.audit().outcome.is_none());
        }
    }
}
