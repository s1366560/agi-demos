use std::sync::atomic::{AtomicUsize, Ordering};

use agistack_plugin_host::{Tool, ToolAccessClass, Trust};

use super::*;

struct HttpRecoveryPureTool(Arc<AtomicUsize>);

#[async_trait]
impl Tool for HttpRecoveryPureTool {
    fn name(&self) -> &str {
        "pure"
    }
    fn version(&self) -> &str {
        "1"
    }
    fn trust(&self) -> Trust {
        Trust::Builtin
    }
    fn access_class(&self) -> ToolAccessClass {
        ToolAccessClass::Pure
    }
    async fn invoke(&self, _: &str) -> CoreResult<String> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok("pure result".into())
    }
}

#[tokio::test]
async fn python_http_answer_resumes_restarted_driver_without_repeating_pure_tool() {
    let Ok(python) = std::env::var("AGISTACK_TEST_PYTHON") else {
        eprintln!("[skip] cross-language HTTP recovery: AGISTACK_TEST_PYTHON unset");
        return;
    };
    for (id, kind) in [
        ("http-clarification", HitlKind::Clarification),
        ("http-decision", HitlKind::Decision),
    ] {
        let Some(fixture) = Fixture::open().await else {
            return;
        };
        fixture.seed(id).await;
        sqlx::raw_sql("ALTER TABLE hitl_requests ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(); CREATE TABLE user_projects (id text PRIMARY KEY,user_id text,project_id text); INSERT INTO user_projects VALUES ('membership','actor','project');")
            .execute(&fixture.pool).await.unwrap();
        let calls = Arc::new(AtomicUsize::new(0));
        let registry = HotPlugRegistry::new();
        registry.register_tool(Arc::new(HttpRecoveryPureTool(calls.clone())));
        let build = || {
            let engine = Arc::new(ReActEngine::new(
                Arc::new(ScriptedLlm::new(vec![
                    AgentAction::CallTool {
                        tool: "pure".into(),
                        input_json: "{}".into(),
                    },
                    AgentAction::RequestHuman {
                        request: HitlRequest::new(id, kind, "Choose a value"),
                    },
                    AgentAction::Finish {
                        answer: "HTTP recovery completed".into(),
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
        first.drive_runtime_scope(&scope()).await.unwrap();
        assert_eq!(run_state(&fixture.pool, id).await.0, "waiting_human");
        drop(first);
        let schema: String = sqlx::query_scalar("SELECT current_schema()")
            .fetch_one(&fixture.pool)
            .await
            .unwrap();
        let repository = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let request_kind = if kind == HitlKind::Clarification {
            "clarification"
        } else {
            "decision"
        };
        let output = tokio::process::Command::new(&python)
            .env("PYTHONPATH", &repository)
            .current_dir(&repository)
            .arg("-m")
            .arg("src.tests.integration.ordinary_hitl_http_probe")
            .arg(schema)
            .arg(id)
            .arg(request_kind)
            .output()
            .await
            .unwrap();
        let restarted = build();
        restarted.drive_runtime_scope(&scope()).await.unwrap();
        let run = run_state(&fixture.pool, id).await;
        let state: Value =
            sqlx::query_scalar("SELECT state FROM agistack_checkpoints WHERE session_id=$1")
                .bind(id)
                .fetch_one(&fixture.pool)
                .await
                .unwrap();
        drop(restarted);
        fixture.close().await;
        assert!(
            output.status.success(),
            "HTTP fixture failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(
            run.0, "success",
            "Python HTTP answer must become a Rust resume candidate"
        );
        let state: SessionState = serde_json::from_value(state).unwrap();
        assert_eq!(state.hitl_responses.len(), 1);
        assert_eq!(state.hitl_responses[0].answer, "  exact 中文 answer  ");
        assert_eq!(state.answer.as_deref(), Some("HTTP recovery completed"));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}
