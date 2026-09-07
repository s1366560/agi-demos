use std::sync::atomic::{AtomicUsize, Ordering};

use agistack_plugin_host::{Tool, ToolAccessClass, Trust};

use super::*;

struct ReleasedTool {
    name: &'static str,
    access: ToolAccessClass,
    calls: Arc<AtomicUsize>,
}

#[async_trait]
impl Tool for ReleasedTool {
    fn name(&self) -> &str {
        self.name
    }
    fn version(&self) -> &str {
        "1"
    }
    fn trust(&self) -> Trust {
        Trust::Builtin
    }
    fn access_class(&self) -> ToolAccessClass {
        self.access
    }
    async fn invoke(&self, input: &str) -> CoreResult<String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(input.into())
    }
}

#[tokio::test]
async fn released_driver_recovery_reuses_pure_result_and_never_dispatches_scoped_tools() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed("release").await;
    let pure_calls = Arc::new(AtomicUsize::new(0));
    let denied_calls = Arc::new(AtomicUsize::new(0));
    let registry = HotPlugRegistry::new();
    for (name, access, calls) in [
        ("pure", ToolAccessClass::Pure, pure_calls.clone()),
        ("read", ToolAccessClass::ScopedRead, denied_calls.clone()),
        ("write", ToolAccessClass::Mutating, denied_calls.clone()),
    ] {
        registry.register_tool(Arc::new(ReleasedTool {
            name,
            access,
            calls,
        }));
    }
    let build = || {
        let engine = Arc::new(ReActEngine::new(
            Arc::new(ScriptedLlm::new(vec![
                AgentAction::CallTool {
                    tool: "pure".into(),
                    input_json: "{\"value\":7}".into(),
                },
                AgentAction::CallTool {
                    tool: "read".into(),
                    input_json: "{}".into(),
                },
                AgentAction::CallTool {
                    tool: "write".into(),
                    input_json: "{}".into(),
                },
                AgentAction::RequestHuman {
                    request: HitlRequest::new(
                        "release-request",
                        HitlKind::Decision,
                        "Choose a value",
                    ),
                },
                AgentAction::Finish {
                    answer: "release completed".into(),
                },
            ])),
            Arc::new(registry.clone()),
            Arc::new(InMemoryCheckpointStore::new()),
            Arc::new(SystemClock),
        ));
        PgCronSchedulerDriver::new(
            fixture.pool.clone(),
            engine,
            registry.clone(),
            CronSchedulerConfig::default(),
            Arc::new(PgCronSchedulerOwnerRepository::new(fixture.pool.clone())),
            Arc::new(UtcCronWorkerClock),
        )
    };
    let first = build();
    assert_eq!(
        first.capabilities().supported_hitl,
        vec![HitlKind::Clarification, HitlKind::Decision]
    );
    first.drive_runtime_scope(&scope()).await.unwrap();
    assert_eq!(run_state(&fixture.pool, "release").await.0, "waiting_human");
    assert_eq!(pure_calls.load(Ordering::SeqCst), 1);
    assert_eq!(denied_calls.load(Ordering::SeqCst), 0);
    drop(first);
    answer(&fixture.pool, "release-request").await;
    let restarted = build();
    restarted.drive_runtime_scope(&scope()).await.unwrap();
    assert_eq!(run_state(&fixture.pool, "release").await.0, "success");
    let checkpoint: Value =
        sqlx::query_scalar("SELECT state FROM agistack_checkpoints WHERE session_id='release'")
            .fetch_one(&fixture.pool)
            .await
            .unwrap();
    let state: SessionState = serde_json::from_value(checkpoint).unwrap();
    assert_eq!(state.answer.as_deref(), Some("release completed"));
    assert_eq!(state.hitl_responses.len(), 1);
    assert!(state.pending_hitl.is_none());
    assert_eq!(
        pure_calls.load(Ordering::SeqCst),
        1,
        "recovery must reuse completed tool output"
    );
    assert_eq!(denied_calls.load(Ordering::SeqCst), 0);
    restarted.drive_runtime_scope(&scope()).await.unwrap();
    assert_eq!(pure_calls.load(Ordering::SeqCst), 1);
    drop(restarted);
    fixture.close().await;
}
