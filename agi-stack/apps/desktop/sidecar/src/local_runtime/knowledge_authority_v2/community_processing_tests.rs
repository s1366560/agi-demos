use super::*;
use agistack_core::knowledge::community::{build::*, result::*, worker::*};

#[path = "community_processing_lifecycle_tests.rs"]
mod lifecycle;

struct CommunityFixture {
    base: Fixture,
    input: CommunityInput,
}

impl CommunityFixture {
    async fn new() -> Self {
        let base = Fixture::new().await;
        let mut extraction = action(&base.source);
        extraction["input_json"]["entities"] = json!([
            {"name":"Mira","kind":"Person"}, {"name":"Cedar","kind":"Project"}
        ]);
        extraction["input_json"]["relationships"] = json!([{
            "source_index":0,"target_index":1,"relation_type":"MAINTAINS",
            "fact":"Mira maintains Cedar.","score":0.9
        }]);
        let endpoint = Endpoint::new(&base, extraction).await;
        let run = base.spawn(endpoint.provider(), ProcessingRunOptions::default());
        endpoint.wait().await;
        endpoint.release.notify_one();
        assert!(matches!(
            run.await.unwrap().unwrap().unwrap().outcome,
            ProcessingAuditOutcome::Applied { .. }
        ));
        let receipt = base
            .repo()
            .create_community_build_durable(
                &base.operation.scope,
                &CommunityBuildRequest {
                    actor_id: base.auth.user.user_id.clone(),
                    idempotency_key: "community-test".into(),
                    min_community_size: 2,
                },
                &|| Ok(chrono::Utc::now().timestamp_millis()),
            )
            .unwrap();
        let build = base
            .repo()
            .community_build_durable(&base.operation.scope, &receipt.build_id)
            .unwrap()
            .unwrap();
        assert_eq!(build.candidates.len(), 1);
        let input = base
            .repo()
            .community_candidate_input_durable(
                &base.operation.scope,
                &receipt.build_id,
                &build.candidates[0].membership_digest,
            )
            .unwrap()
            .unwrap();
        Self { base, input }
    }
    fn output(&self, ready: bool) -> Value {
        let member = &self.input.candidate.members[0];
        let evidence = vec![CommunityEvidence {
            source: member.source.clone(),
            entity_index: member.entity_index,
            relationship_index: None,
        }];
        json!({"kind":"call_tool","tool":SUBMIT_COMMUNITY_TOOL,"input_json":CommunitySubmission {
            build_id:self.input.build_id.clone(), graph_digest:self.input.graph_digest.clone(),
            candidate_id:self.input.candidate.membership_digest.clone(), members:self.input.candidate.members.clone(),
            decision: if ready { CommunityDecision::Ready {
                name:"Cedar maintenance".into(),summary:"Mira maintains Cedar.".into(),
                rationale:"Source explicitly associates these entities.".into(),evidence,
            }} else { CommunityDecision::InsufficientEvidence {
                rationale:"The source is too limited to support a useful named community.".into(),evidence,
            }}
        }})
    }
    fn spawn(
        &self,
        provider: ProcessingProvider,
        options: ProcessingRunOptions,
    ) -> tokio::task::JoinHandle<Result<Option<CommunityAuditRecord>, KnowledgeAuthorityErrorV2>>
    {
        let operation = self.base.operation.clone();
        let state = self.base.state.clone();
        let auth = self.base.auth.clone();
        let build = self.input.build_id.clone();
        tokio::spawn(async move {
            operation
                .process_community_with_provider(state, auth, provider, &build, options)
                .await
        })
    }
    fn audit(&self) -> CommunityAuditRecord {
        self.base
            .repo()
            .community_audit_durable(
                &self.base.operation.scope,
                &self.input.build_id,
                &self.input.candidate.membership_digest,
                1,
            )
            .unwrap()
            .unwrap()
    }
    fn no_result(&self) {
        assert!(self
            .base
            .repo()
            .community_results_durable(&self.base.operation.scope, &self.input.build_id,)
            .unwrap()
            .is_empty());
    }
}

#[derive(Clone)]
struct CommunityEndpointState {
    entered: Arc<Notify>,
    release: Arc<Notify>,
    repository: Arc<SqliteKnowledgeRepository>,
    scope: KnowledgeScope,
    input: CommunityInput,
    output: Value,
}
struct CommunityEndpoint {
    entered: Arc<Notify>,
    release: Arc<Notify>,
    base: String,
    task: tokio::task::JoinHandle<()>,
}
impl CommunityEndpoint {
    async fn new(f: &CommunityFixture, output: Value) -> Self {
        let entered = Arc::new(Notify::new());
        let release = Arc::new(Notify::new());
        let state = CommunityEndpointState {
            entered: entered.clone(),
            release: release.clone(),
            repository: f.base.repo(),
            scope: f.base.operation.scope.clone(),
            input: f.input.clone(),
            output,
        };
        let app = Router::new()
            .route(
                "/chat/completions",
                post(
                    |State(s): State<CommunityEndpointState>, Json(body): Json<Value>| async move {
                        let audit = s
                            .repository
                            .community_audit_durable(
                                &s.scope,
                                &s.input.build_id,
                                &s.input.candidate.membership_digest,
                                1,
                            )
                            .unwrap()
                            .unwrap();
                        assert!(audit.outcome.is_none());
                        assert_eq!(audit.invocation.input, s.input);
                        assert!(body.to_string().contains(SUBMIT_COMMUNITY_TOOL));
                        s.entered.notify_one();
                        s.release.notified().await;
                        let code = if s.output.get("http_error").is_some() {
                            axum::http::StatusCode::INTERNAL_SERVER_ERROR
                        } else {
                            axum::http::StatusCode::OK
                        };
                        (
                            code,
                            Json(json!({"choices":[{"message":{"content":s.output.to_string()}}]})),
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
            base,
            task,
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
    }
}
impl Drop for CommunityEndpoint {
    fn drop(&mut self) {
        self.task.abort();
    }
}

#[tokio::test]
async fn ready_and_insufficient_outputs_are_audited_without_automatic_activation() {
    for ready in [true, false] {
        let f = CommunityFixture::new().await;
        let endpoint = CommunityEndpoint::new(&f, f.output(ready)).await;
        let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
        endpoint.wait().await;
        f.no_result();
        endpoint.release.notify_one();
        let record = run.await.unwrap().unwrap().unwrap();
        assert!(matches!(
            record.outcome,
            Some(CommunityAuditOutcome::Applied { .. })
        ));
        assert_eq!(f.audit(), record);
        assert!(record.latency_ms.is_some());
        assert!(f
            .base
            .repo()
            .active_community_build_durable(&f.base.operation.scope)
            .unwrap()
            .current
            .is_none());
        assert_eq!(
            f.base
                .operation
                .get(&f.base.source.memory_id)
                .await
                .unwrap()
                .unwrap()
                .version,
            1
        );
        assert_eq!(f.base.operation.changes(0, 20).await.unwrap().len(), 1);
    }
}

#[tokio::test]
async fn rejected_outputs_and_provider_errors_never_persist_raw_response() {
    for variant in 0..4 {
        let f = CommunityFixture::new().await;
        let mut output = f.output(true);
        match variant {
            0 => output = json!({"kind":"finish","answer":"private-rejected-text"}),
            1 => output["input_json"]["graph_digest"] = json!("0".repeat(64)),
            2 => output["input_json"]["members"][0]["source"]["revision"] = json!(99),
            _ => output = json!({"http_error":"private-rejected-text"}),
        }
        let endpoint = CommunityEndpoint::new(&f, output).await;
        let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
        endpoint.wait().await;
        endpoint.release.notify_one();
        let record = run.await.unwrap().unwrap().unwrap();
        let expected = if variant == 3 {
            CommunityAuditFailure::ProviderUnavailable
        } else {
            CommunityAuditFailure::InvalidSubmission
        };
        assert!(
            matches!(record.outcome,Some(CommunityAuditOutcome::Failed {code,..}) if code == expected)
        );
        assert!(!serde_json::to_string(&f.audit())
            .unwrap()
            .contains("private-rejected-text"));
        f.no_result();
    }
}

#[tokio::test]
async fn abort_records_cancelled_and_never_publishes() {
    let f = CommunityFixture::new().await;
    let endpoint = CommunityEndpoint::new(&f, f.output(true)).await;
    let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
    endpoint.wait().await;
    run.abort();
    assert!(run.await.unwrap_err().is_cancelled());
    assert!(matches!(
        f.audit().outcome,
        Some(CommunityAuditOutcome::Failed {
            code: CommunityAuditFailure::Cancelled,
            ..
        })
    ));
    f.no_result();
}

#[tokio::test]
async fn source_change_returns_durable_rejection_instead_of_requested_applied_result() {
    let f = CommunityFixture::new().await;
    let endpoint = CommunityEndpoint::new(&f, f.output(true)).await;
    let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
    endpoint.wait().await;
    let mut memory = f
        .base
        .operation
        .get(&f.base.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    memory.metadata.insert("edited".into(), true.into());
    f.base
        .repo()
        .update(&f.base.operation.scope, memory, 1)
        .await
        .unwrap();
    endpoint.release.notify_one();
    let record = run.await.unwrap().unwrap().unwrap();
    assert!(matches!(
        record.outcome,
        Some(CommunityAuditOutcome::Failed {
            code: CommunityAuditFailure::GraphChanged,
            ..
        })
    ));
    f.no_result();
}
