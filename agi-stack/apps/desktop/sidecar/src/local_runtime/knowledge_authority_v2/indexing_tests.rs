use super::super::{embedding_provider::EmbeddingRoute, indexing::*};
use super::*;
use agistack_core::knowledge::{
    index::*,
    processing::{audit::*, worker::*, *},
};
use axum::{
    extract::{Extension, State},
    routing::post,
    Json, Router,
};
use std::sync::atomic::{AtomicBool, Ordering};
use tokio::sync::Notify;

#[path = "embedding_configuration_tests.rs"]
mod embedding_configuration_tests;
#[path = "indexing_lifecycle_tests.rs"]
mod lifecycle;
#[path = "embedding_profile_tests.rs"]
mod profile;

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
        let operation = Arc::new(
            KnowledgeOperationV2::admit(lease.clone(), &auth, &operation_scope(&auth, &lease))
                .unwrap(),
        );
        operation.mutate("create", mutation(&auth)).await.unwrap();
        let repo = operation.authority.repository().unwrap();
        let source = apply(&repo, &operation.scope).await;
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
    fn run(
        &self,
        build: DesiredEmbeddingConfig,
        options: IndexRunOptions,
    ) -> tokio::task::JoinHandle<Result<Option<IndexRunReceipt>, KnowledgeAuthorityErrorV2>> {
        let operation = self.operation.clone();
        let state = self.state.clone();
        let auth = self.auth.clone();
        tokio::spawn(async move { operation.index_one(&state, &auth, &build, options).await })
    }
    async fn provider(&self, endpoint: &Endpoint) -> EmbeddingRoute {
        let response=crate::local_runtime::provider_management::create_llm_provider(
            State(self.state.clone()),Extension(self.auth.clone()),axum::http::HeaderMap::new(),Json(serde_json::from_value(json!({
                "name":"Explicit embedding QA","provider_type":"openai_compatible","base_url":endpoint.base,
                "auth_method":"api_key","api_key":"embedding-fixture-key","llm_model":"configured-embedding-model",
                "allowed_models":["configured-embedding-model","other-embedding-model"],"is_active":true
            })).unwrap()),
        ).await.unwrap().0;
        EmbeddingRoute {
            provider_id: response["id"].as_str().unwrap().into(),
            provider_revision: response["revision"].as_u64().unwrap(),
            model_id: "configured-embedding-model".into(),
        }
    }
}
async fn apply(repo: &SqliteKnowledgeRepository, scope: &KnowledgeScope) -> ProcessingSource {
    let lease = repo
        .claim(scope, "extract", 100, 100)
        .await
        .unwrap()
        .unwrap();
    let memory = repo
        .get(scope, &lease.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    repo.begin_processing_audit_durable(
        scope,
        &lease,
        ProcessingInvocation {
            agent_id: "extract".into(),
            provider_id: "extract-provider".into(),
            model_id: "extract-model".into(),
            tool_name: SUBMIT_PROJECTION_TOOL.into(),
            contract_version: 1,
            input: ProcessingInput {
                source: lease.source.clone(),
                title: memory.title,
                content: memory.content,
            },
        },
        100,
    )
    .unwrap();
    repo.finish_processing_audit_durable(
        scope,
        &lease,
        ProcessingAuditOutcome::Applied {
            submission: ProjectionSubmission {
                source: lease.source.clone(),
                entities: vec![],
                relationships: vec![],
                rationale: "No graph entities.".into(),
            },
        },
        101,
        1,
    )
    .unwrap();
    lease.source
}

#[derive(Clone)]
struct EndpointState {
    paused: Arc<AtomicBool>,
    entered: Arc<Notify>,
    release: Arc<Notify>,
    response: Arc<Mutex<Option<Value>>>,
    requests: Arc<Mutex<Vec<Value>>>,
    credential_seen: Arc<AtomicBool>,
}
struct Endpoint {
    state: EndpointState,
    base: String,
    task: tokio::task::JoinHandle<()>,
}
impl Endpoint {
    async fn new() -> Self {
        let state = EndpointState {
            paused: Arc::new(AtomicBool::new(false)),
            entered: Arc::new(Notify::new()),
            release: Arc::new(Notify::new()),
            response: Arc::new(Mutex::new(None)),
            requests: Arc::new(Mutex::new(Vec::new())),
            credential_seen: Arc::new(AtomicBool::new(false)),
        };
        let app=Router::new().route("/embeddings",post(|State(state):State<EndpointState>,headers:axum::http::HeaderMap,Json(body):Json<Value>|async move {
            state.credential_seen.store(headers.get("authorization").and_then(|v|v.to_str().ok())==Some("Bearer embedding-fixture-key"),Ordering::SeqCst);
            state.requests.lock().unwrap().push(body.clone());
            if state.paused.load(Ordering::SeqCst) {state.entered.notify_one();state.release.notified().await;}
            let response=state.response.lock().unwrap().clone().unwrap_or_else(||json!({"model":body["model"],"data":[{"index":0,"embedding":[1.0,0.0]}]}));
            Json(response)
        })).with_state(state.clone());
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        Self { state, base, task }
    }
    fn pause(&self) {
        self.state.paused.store(true, Ordering::SeqCst);
    }
    async fn entered(&self) {
        tokio::time::timeout(
            std::time::Duration::from_secs(3),
            self.state.entered.notified(),
        )
        .await
        .unwrap();
    }
    fn release(&self) {
        self.state.paused.store(false, Ordering::SeqCst);
        self.state.release.notify_one();
    }
}
impl Drop for Endpoint {
    fn drop(&mut self) {
        self.task.abort();
    }
}

#[tokio::test]
async fn native_provider_crud_binding_embeds_indexes_and_queries_with_separate_processing_coverage()
{
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let build = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "build")
        .await
        .unwrap();
    let config = f
        .operation
        .select_index_build(&f.state, &f.auth, &build, None)
        .unwrap();
    assert_eq!(build.profile.dimensions.get(), 2);
    let receipt = f
        .operation
        .index_one(&f.state, &f.auth, &config, IndexRunOptions::default())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(receipt.outcome, IndexRunOutcome::Indexed);
    assert_eq!(receipt.input.source, f.source);
    assert_eq!(receipt.attempt, 1);
    f.operation
        .promote_index_build(&f.state, &f.auth, &config, None)
        .unwrap();
    let mut memory = f
        .repo()
        .get(&f.operation.scope, &f.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    memory.id = "pending-source".into();
    f.repo()
        .create(&f.operation.scope, memory.clone())
        .await
        .unwrap();
    memory.id = "failed-source".into();
    f.repo().create(&f.operation.scope, memory).await.unwrap();
    let pending = f
        .repo()
        .claim(&f.operation.scope, "leave-pending", 100, 100)
        .await
        .unwrap()
        .unwrap();
    let failed = f
        .repo()
        .claim(&f.operation.scope, "fail", 100, 100)
        .await
        .unwrap()
        .unwrap();
    f.repo()
        .fail(
            &f.operation.scope,
            &failed,
            ProcessingFailure::ProviderUnavailable,
            101,
        )
        .await
        .unwrap();
    assert_ne!(pending.source, failed.source);
    let result = f
        .operation
        .semantic_query(&f.state, &f.auth, &config, "query", 10)
        .await
        .unwrap();
    assert_eq!(result.build, build);
    assert_eq!(result.hits.len(), 1);
    assert_eq!(result.hits[0].input.source, f.source);
    assert_eq!(result.hits[0].score, 1.0);
    assert!(result.index.complete());
    assert_eq!(
        result.processing,
        ProcessingCoverage {
            current_sources: 3,
            applied_sources: 1,
            pending_sources: 1,
            failed_sources: 1
        }
    );
    assert!(endpoint.state.credential_seen.load(Ordering::SeqCst));
    assert_eq!(endpoint.state.requests.lock().unwrap().len(), 3);
    let reopened = SqliteKnowledgeRepository::open(
        f.directory
            .0
            .join("knowledge/memories.db")
            .to_str()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        reopened
            .read_active_index_durable(&config, &|| Ok(200))
            .unwrap()
            .vectors
            .len(),
        1
    );
}

#[tokio::test]
async fn invalid_verified_response_is_failed_until_explicit_retry_and_query_never_falls_back() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let build = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "build")
        .await
        .unwrap();
    let config = f
        .operation
        .select_index_build(&f.state, &f.auth, &build, None)
        .unwrap();
    *endpoint.state.response.lock().unwrap() =
        Some(json!({"model":"wrong-model","data":[{"index":0,"embedding":[1.0,0.0]}]}));
    let receipt = f
        .operation
        .index_one(&f.state, &f.auth, &config, IndexRunOptions::default())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        receipt.outcome,
        IndexRunOutcome::Failed(IndexFailure::InvalidEmbedding)
    );
    assert!(f
        .operation
        .promote_index_build(&f.state, &f.auth, &config, None)
        .is_err());
    f.operation
        .retry_index(&f.state, &f.auth, &config, &receipt.input, receipt.attempt)
        .unwrap();
    *endpoint.state.response.lock().unwrap() = None;
    assert_eq!(
        f.operation
            .index_one(&f.state, &f.auth, &config, IndexRunOptions::default())
            .await
            .unwrap()
            .unwrap()
            .outcome,
        IndexRunOutcome::Indexed
    );
    f.operation
        .promote_index_build(&f.state, &f.auth, &config, None)
        .unwrap();
    *endpoint.state.response.lock().unwrap() =
        Some(json!({"model":route.model_id,"data":[{"index":0,"embedding":[1.0,0.0,1.0]}]}));
    assert!(f
        .operation
        .semantic_query(&f.state, &f.auth, &config, "query", 10)
        .await
        .is_err());
}
