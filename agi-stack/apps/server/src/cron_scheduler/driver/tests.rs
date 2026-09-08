use agistack_adapters_mem::{InMemoryCheckpointStore, ScriptedLlm, SystemClock};
use agistack_core::agent::{AgentAction, HitlKind, HitlRequest, SessionState, SessionStatus};
use serde_json::Value;

use super::*;
#[path = "test_fixture.rs"]
mod test_fixture;
use test_fixture::Fixture;

fn driver(pool: PgPool, kind: HitlKind, request: &str) -> PgCronSchedulerDriver {
    let registry = HotPlugRegistry::new();
    let mut human_request = HitlRequest::new(request, kind, "Choose a value");
    if kind == HitlKind::A2uiAction {
        human_request = human_request.with_a2ui_action(agistack_core::agent::A2uiActionAuthority {
            surface_id: "surface".into(),
            block_id: "block".into(),
            title: None,
            timeout_seconds: Some(300),
            allowed_actions: vec![agistack_core::agent::A2uiAllowedAction {
                source_component_id: "button".into(),
                action_name: "approve".into(),
            }],
        });
    }
    let engine = Arc::new(ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![
            AgentAction::RequestHuman {
                request: human_request,
            },
            AgentAction::Finish {
                answer: "driver resume completed".into(),
            },
        ])),
        Arc::new(registry.clone()),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(SystemClock),
    ));
    PgCronSchedulerDriver::new(
        pool.clone(),
        engine,
        registry,
        CronSchedulerConfig::default(),
        Arc::new(PgCronSchedulerOwnerRepository::new(pool)),
        Arc::new(UtcCronWorkerClock),
    )
}

fn scope() -> CronControlScope {
    CronControlScope {
        tenant_id: "tenant".into(),
        project_id: "project".into(),
    }
}

async fn run_state(pool: &PgPool, id: &str) -> (String, i64) {
    sqlx::query_as("SELECT status,runtime_revision FROM cron_job_runs WHERE id=$1")
        .bind(id)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn answer(pool: &PgPool, request: &str) {
    sqlx::query(
        "UPDATE hitl_requests SET status='answered',response='chosen',
        response_metadata='{\"resume_answer\":\"chosen\"}',answered_at=now() WHERE id=$1",
    )
    .bind(request)
    .execute(pool)
    .await
    .unwrap();
}

#[tokio::test]
async fn postgres_driver_pauses_then_atomically_admits_claims_and_projects_ordinary_answers() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    for (id, kind) in [
        ("clarification", HitlKind::Clarification),
        ("decision", HitlKind::Decision),
    ] {
        fixture.seed(id).await;
        let driver = driver(fixture.pool.clone(), kind, id);
        driver.drive_runtime_scope(&scope()).await.unwrap();
        let waiting = run_state(&fixture.pool, id).await;
        assert_eq!(waiting.0, "waiting_human");
        driver.drive_runtime_scope(&scope()).await.unwrap();
        assert_eq!(
            run_state(&fixture.pool, id).await,
            waiting,
            "unanswered request stays suspended"
        );
        answer(&fixture.pool, id).await;
        // A fresh driver/engine proves the answer and checkpoint survive replacement.
        let restarted = self::driver(fixture.pool.clone(), kind, id);
        restarted.drive_runtime_scope(&scope()).await.unwrap();
        assert_eq!(
            run_state(&fixture.pool, id).await,
            ("success".into(), waiting.1 + 2),
            "one admission revision followed by one runtime claim"
        );
        let state: Value =
            sqlx::query_scalar("SELECT state FROM agistack_checkpoints WHERE session_id=$1")
                .bind(id)
                .fetch_one(&fixture.pool)
                .await
                .unwrap();
        let state: SessionState = serde_json::from_value(state).unwrap();
        assert_eq!(state.status, SessionStatus::Finished);
        assert_eq!(state.hitl_responses.len(), 1);
        assert_eq!(state.hitl_responses[0].answer, "chosen");
        assert!(state.pending_hitl.is_none());
        assert_eq!(state.answer.as_deref(), Some("driver resume completed"));
        let operation: String =
            sqlx::query_scalar("SELECT status FROM agistack_cron_operations WHERE id=$1")
                .bind(id)
                .fetch_one(&fixture.pool)
                .await
                .unwrap();
        assert_eq!(operation, "completed");
        let before: Value = sqlx::query_scalar("SELECT state FROM cron_jobs WHERE id=$1")
            .bind(id)
            .fetch_one(&fixture.pool)
            .await
            .unwrap();
        driver.drive_runtime_scope(&scope()).await.unwrap();
        let after: Value = sqlx::query_scalar("SELECT state FROM cron_jobs WHERE id=$1")
            .bind(id)
            .fetch_one(&fixture.pool)
            .await
            .unwrap();
        assert_eq!(before, after, "completed run replay never recounts the job");
    }
    fixture.close().await;
}

#[tokio::test]
async fn postgres_driver_excludes_permission_before_the_candidate_limit() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed("permission").await;
    let mut permission = driver(
        fixture.pool.clone(),
        HitlKind::Permission,
        "permission-request",
    );
    // Reproduce an already-existing unsupported request from the internal
    // composition. Released execution cannot create this pending state.
    let registry = HotPlugRegistry::new();
    let engine = Arc::new(ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::RequestHuman {
            request: HitlRequest::new("permission-request", HitlKind::Permission, "Approve?"),
        }])),
        Arc::new(registry.clone()),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(SystemClock),
    ));
    let executor = ReActAutomationRunExecutor::new(engine)
        .with_run_persistence_factory(Arc::new(PgAutomationRunPersistenceFactory::new(
            fixture.pool.clone(),
        )))
        .with_tool_host_factory(Arc::new(RegistryAutomationToolHostFactory::new(registry)));
    permission.runtime = Arc::new(CronAutomationRuntimeWorker::new(
        Arc::new(PgCronAutomationRuntimeRepository::new(fixture.pool.clone())),
        Arc::new(executor),
        CronSchedulerConfig::default().runtime_worker_config(),
    ));
    permission.drive_runtime_scope(&scope()).await.unwrap();
    answer(&fixture.pool, "permission-request").await;
    let waiting = run_state(&fixture.pool, "permission").await;
    fixture.seed("ordinary").await;
    let ordinary = driver(
        fixture.pool.clone(),
        HitlKind::Clarification,
        "ordinary-request",
    );
    ordinary.drive_runtime_scope(&scope()).await.unwrap();
    answer(&fixture.pool, "ordinary-request").await;
    // runtime_batch_size=1; the older permission must not consume that candidate slot.
    ordinary.drive_runtime_scope(&scope()).await.unwrap();
    assert_eq!(run_state(&fixture.pool, "ordinary").await.0, "success");
    assert_eq!(run_state(&fixture.pool, "permission").await, waiting);
    fixture.close().await;
}

#[tokio::test]
async fn postgres_driver_does_not_claim_when_resume_admission_storage_is_unavailable() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed("unclaimed").await;
    let driver = driver(fixture.pool.clone(), HitlKind::Clarification, "request");
    sqlx::query("DROP TABLE hitl_requests")
        .execute(&fixture.pool)
        .await
        .unwrap();
    let error = driver.drive_runtime_scope(&scope()).await.unwrap_err();
    assert!(error
        .to_string()
        .contains("cron automation resume admission failed"));
    assert_eq!(
        run_state(&fixture.pool, "unclaimed").await,
        ("queued".into(), 0)
    );
    fixture.close().await;
}

#[path = "permission_tests.rs"]
mod permission_tests;

#[path = "release_tests.rs"]
mod release_tests;

#[path = "ordinary_http_tests.rs"]
mod ordinary_http_tests;

#[path = "owner_lifecycle_tests.rs"]
mod owner_lifecycle_tests;

#[tokio::test]
async fn released_driver_rejects_unsupported_hitl_before_durable_pending() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    for (id, kind) in [
        ("unsupported-permission", HitlKind::Permission),
        ("unsupported-env", HitlKind::EnvVar),
        ("unsupported-a2ui", HitlKind::A2uiAction),
    ] {
        fixture.seed(id).await;
        driver(fixture.pool.clone(), kind, id)
            .drive_runtime_scope(&scope())
            .await
            .unwrap();
        assert_eq!(run_state(&fixture.pool, id).await.0, "failed");
        let pending: i64 = sqlx::query_scalar("SELECT count(*) FROM hitl_requests WHERE id=$1")
            .bind(id)
            .fetch_one(&fixture.pool)
            .await
            .unwrap();
        assert_eq!(pending, 0, "unsupported request must never become durable");
        let checkpoints: i64 = sqlx::query_scalar("SELECT count(*) FROM agistack_checkpoints WHERE session_id=$1 AND state->'pending_hitl' IS NOT NULL AND state->'pending_hitl' <> 'null'::jsonb")
            .bind(id).fetch_one(&fixture.pool).await.unwrap();
        assert_eq!(checkpoints, 0);
    }
    fixture.close().await;
}
