use agistack_adapters_mem::{InMemoryCheckpointStore, ScriptedLlm, SystemClock};
use agistack_core::agent::{AgentAction, HitlKind, HitlRequest, SessionState, SessionStatus};
use serde_json::Value;

use super::*;
#[path = "test_fixture.rs"]
mod test_fixture;
use test_fixture::Fixture;

fn driver(pool: PgPool, kind: HitlKind, request: &str) -> PgCronSchedulerDriver {
    let registry = HotPlugRegistry::new();
    let engine = Arc::new(ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![
            AgentAction::RequestHuman {
                request: HitlRequest::new(request, kind, "Choose a value"),
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
    let permission = driver(
        fixture.pool.clone(),
        HitlKind::Permission,
        "permission-request",
    );
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
