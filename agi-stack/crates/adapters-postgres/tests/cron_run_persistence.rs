//! Run lease fencing for checkpoint and HITL writes across database connections.

#[path = "cron_hitl_admission/support.rs"]
mod support;

use agistack_adapters_postgres::{
    AutomationHitlAdmissionOutcome, AutomationPayload, AutomationRunContext, AutomationRunLease,
    AutomationRunStatus, AutomationRuntimeScope, NewHitlRequestRecord, PgAutomationHitlAdmission,
    PgAutomationRunPersistence, PgCronAutomationRuntimeRepository, PgHitlRequestRepository,
};
use agistack_core::agent::SessionStatus;
use agistack_core::ports::CheckpointStore;
use chrono::Duration;
use support::Fixture;

fn lease() -> AutomationRunLease {
    AutomationRunLease {
        context: AutomationRunContext {
            tenant_id: "tenant".into(),
            project_id: "project".into(),
            job_id: "job".into(),
            run_id: "run".into(),
            runtime_execution_id: "run".into(),
            conversation_id: "conversation".into(),
            actor_user_id: "actor".into(),
            actor_api_key_id: None,
            payload: AutomationPayload::AgentTurn {
                message: "test".into(),
            },
            timeout_seconds: 300,
            status: AutomationRunStatus::Running,
        },
        runtime_revision: 7,
        lease_owner: "old".into(),
        lease_token: "old-token".into(),
        lease_expires_at: support::now() + Duration::seconds(30),
        deadline_at: support::now() + Duration::minutes(5),
    }
}

async fn running_fixture() -> Option<Fixture> {
    let fixture = Fixture::open().await?;
    fixture.seed().await;
    sqlx::query("ALTER TABLE hitl_requests ADD COLUMN user_id text, ADD COLUMN question text NOT NULL DEFAULT '',
        ADD COLUMN options json, ADD COLUMN context json, ADD COLUMN response text")
        .execute(&fixture.pool).await.unwrap();
    sqlx::query("UPDATE cron_job_runs SET status = 'running', runtime_lease_expires_at = $1")
        .bind(lease().lease_expires_at)
        .execute(&fixture.pool)
        .await
        .unwrap();
    Some(fixture)
}

fn pending(id: &str) -> NewHitlRequestRecord {
    NewHitlRequestRecord {
        id: id.into(),
        request_type: "clarification".into(),
        conversation_id: "conversation".into(),
        message_id: Some("run".into()),
        tenant_id: "tenant".into(),
        project_id: "project".into(),
        user_id: Some("actor".into()),
        question: "Confirm?".into(),
        options: None,
        context: None,
        request_metadata: Some(
            serde_json::json!({"automation_run_id":"run", "runtime_execution_id":"run", "checkpoint_session_id":"run"}),
        ),
        expires_at: lease().deadline_at,
    }
}

#[tokio::test]
async fn replaced_worker_cannot_insert_a_late_hitl_or_overwrite_after_new_worker_resume() {
    let Some(fixture) = running_fixture().await else {
        return;
    };
    let old = PgAutomationRunPersistence::new(fixture.pool.clone(), lease());
    let stale = old.load("run").await.unwrap().unwrap();
    let other_pool = fixture.independent_pool().await;
    sqlx::query("UPDATE cron_job_runs SET runtime_lease_expires_at = '2000-01-01'")
        .execute(&other_pool)
        .await
        .unwrap();
    let new_lease = PgCronAutomationRuntimeRepository::new(other_pool.clone())
        .claim_due(
            &AutomationRuntimeScope {
                tenant_id: "tenant".into(),
                project_id: "project".into(),
            },
            1,
            "replacement-worker",
            30,
            support::now(),
        )
        .await
        .unwrap()
        .remove(0);
    assert_eq!(new_lease.runtime_revision, 8);
    let current = PgAutomationRunPersistence::new(other_pool.clone(), new_lease);
    current.save(&stale).await.unwrap();
    assert!(current.mark_waiting_human(support::now()).await.unwrap());
    let candidates = PgHitlRequestRepository::new(other_pool.clone())
        .list_automation_resume_candidates("tenant", "project", 10, support::now())
        .await
        .unwrap();
    assert_eq!(candidates.len(), 1);
    assert_eq!(candidates[0].job_id, "job");
    assert_eq!(candidates[0].runtime_revision, 8);
    let mut command = fixture.command();
    command.expected_runtime_revision = 8;
    assert_eq!(
        PgAutomationHitlAdmission::new(other_pool.clone())
            .admit(&command, support::now())
            .await
            .unwrap(),
        AutomationHitlAdmissionOutcome::Applied {
            runtime_revision: 9
        }
    );
    let before = fixture.checkpoint().await;
    assert!(old.save(&stale).await.is_err());
    assert!(old.insert_pending(&pending("late-request")).await.is_err());
    assert!(!old.mark_waiting_human(support::now()).await.unwrap());
    assert_eq!(fixture.checkpoint().await, before);
    let count: i64 =
        sqlx::query_scalar("SELECT count(*) FROM hitl_requests WHERE id = 'late-request'")
            .fetch_one(&other_pool)
            .await
            .unwrap();
    assert_eq!(count, 0);
    other_pool.close().await;
    fixture.close().await;
}

#[tokio::test]
async fn pending_hitl_replay_is_idempotent_but_expired_lease_and_foreign_actor_are_rejected() {
    let Some(fixture) = running_fixture().await else {
        return;
    };
    let writer = PgAutomationRunPersistence::new(fixture.pool.clone(), lease());
    let request = pending("fresh-request");
    assert!(writer.insert_pending(&request).await.unwrap());
    assert!(!writer.insert_pending(&request).await.unwrap());
    sqlx::query("UPDATE hitl_requests SET status = 'answered' WHERE id = 'fresh-request'")
        .execute(&fixture.pool)
        .await
        .unwrap();
    assert!(!writer.insert_pending(&request).await.unwrap());
    let mut foreign = pending("foreign-request");
    foreign.user_id = Some("other-actor".into());
    assert!(writer.insert_pending(&foreign).await.is_err());
    sqlx::query("UPDATE cron_job_runs SET runtime_lease_expires_at = '2000-01-01'")
        .execute(&fixture.pool)
        .await
        .unwrap();
    assert!(writer
        .insert_pending(&pending("expired-request"))
        .await
        .is_err());
    let rows: Vec<(String, String)> =
        sqlx::query_as("SELECT id, status FROM hitl_requests WHERE id <> 'request'")
            .fetch_all(&fixture.pool)
            .await
            .unwrap();
    assert_eq!(rows, vec![("fresh-request".into(), "answered".into())]);
    fixture.close().await;
}

#[tokio::test]
async fn checkpoint_uses_current_database_expiry_and_denies_foreign_state_or_deletion() {
    let Some(fixture) = running_fixture().await else {
        return;
    };
    let mut captured = lease();
    captured.lease_expires_at = chrono::Utc::now() - Duration::minutes(1);
    let writer = PgAutomationRunPersistence::new(fixture.pool.clone(), captured);
    let mut state = writer.load("run").await.unwrap().unwrap();
    state.status = SessionStatus::Running;
    writer.save(&state).await.unwrap();
    let before = fixture.checkpoint().await;
    state.project_id = Some("another-project".into());
    assert!(writer.save(&state).await.is_err());
    assert!(writer.load("another-session").await.is_err());
    assert!(writer.delete("run").await.is_err());
    let mut forged = lease();
    forged.context.actor_user_id = "another-actor".into();
    assert!(
        PgAutomationRunPersistence::new(fixture.pool.clone(), forged)
            .load("run")
            .await
            .is_err()
    );
    assert_eq!(fixture.checkpoint().await, before);
    fixture.close().await;
}

#[tokio::test]
async fn expiry_after_checkpoint_write_rolls_back_the_entire_write() {
    let Some(fixture) = running_fixture().await else {
        return;
    };
    let writer = PgAutomationRunPersistence::new(fixture.pool.clone(), lease());
    let mut state = writer.load("run").await.unwrap().unwrap();
    state.round += 1;
    let before = fixture.checkpoint().await;
    sqlx::query("CREATE FUNCTION expire_writer() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE cron_job_runs SET runtime_lease_expires_at = '2000-01-01'; RETURN NEW; END; $$")
        .execute(&fixture.pool).await.unwrap();
    sqlx::query(
        "CREATE TRIGGER expire_writer BEFORE UPDATE ON agistack_checkpoints
        FOR EACH ROW EXECUTE FUNCTION expire_writer()",
    )
    .execute(&fixture.pool)
    .await
    .unwrap();
    assert!(writer.save(&state).await.is_err());
    assert_eq!(fixture.checkpoint().await, before);
    fixture.close().await;
}

#[tokio::test]
async fn checkpoint_writer_already_waiting_for_the_run_lock_cannot_cross_human_suspension() {
    let Some(fixture) = running_fixture().await else {
        return;
    };
    let old = PgAutomationRunPersistence::new(fixture.pool.clone(), lease());
    let stale = old.load("run").await.unwrap().unwrap();
    let other_pool = fixture.independent_pool().await;
    let mut suspension = other_pool.begin().await.unwrap();
    let pid: i32 = sqlx::query_scalar("SELECT pg_backend_pid()")
        .fetch_one(&mut *suspension)
        .await
        .unwrap();
    sqlx::query(
        "UPDATE cron_job_runs SET status = 'waiting_human', runtime_lease_owner = NULL,
        runtime_lease_token = NULL, runtime_lease_expires_at = NULL",
    )
    .execute(&mut *suspension)
    .await
    .unwrap();
    let writer = tokio::spawn(async move { old.save(&stale).await });
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let blocked: bool = sqlx::query_scalar(
                "SELECT EXISTS (
                SELECT 1 FROM pg_stat_activity WHERE $1 = ANY(pg_blocking_pids(pid)))",
            )
            .bind(pid)
            .fetch_one(&other_pool)
            .await
            .unwrap();
            if blocked {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    suspension.commit().await.unwrap();
    let admission = PgAutomationHitlAdmission::new(other_pool.clone());
    let command = fixture.command();
    let (write, admission) = tokio::join!(writer, admission.admit(&command, support::now()));
    assert!(write.unwrap().is_err());
    assert!(matches!(
        admission.unwrap(),
        AutomationHitlAdmissionOutcome::Applied { .. }
    ));
    fixture.assert_resumed().await;
    other_pool.close().await;
    fixture.close().await;
}

#[tokio::test]
async fn old_worker_cannot_overwrite_an_atomically_resumed_checkpoint_from_another_pool() {
    let Some(fixture) = running_fixture().await else {
        return;
    };
    let old = PgAutomationRunPersistence::new(fixture.pool.clone(), lease());
    let stale = old.load("run").await.unwrap().unwrap();
    let second_pool = fixture.independent_pool().await;
    let current = PgAutomationRunPersistence::new(second_pool.clone(), lease());
    assert!(current.mark_waiting_human(support::now()).await.unwrap());
    assert_eq!(
        PgAutomationHitlAdmission::new(second_pool.clone())
            .admit(&fixture.command(), support::now())
            .await
            .unwrap(),
        AutomationHitlAdmissionOutcome::Applied {
            runtime_revision: 8
        }
    );
    assert!(old.save(&stale).await.is_err());
    assert!(old.load("run").await.is_err());
    fixture.assert_resumed().await;
    second_pool.close().await;
    fixture.close().await;
}

#[tokio::test]
async fn lease_expiry_and_deadline_are_checked_by_checkpoint_and_waiting_human_writes() {
    for update in [
        "UPDATE cron_job_runs SET runtime_lease_expires_at = '2000-01-01'",
        "UPDATE cron_job_runs SET deadline_at = '2000-01-01'",
        "UPDATE cron_job_runs SET runtime_revision = 8",
        "UPDATE cron_job_runs SET runtime_lease_token = 'replacement'",
        "UPDATE cron_job_runs SET runtime_lease_owner = 'replacement'",
    ] {
        let Some(fixture) = running_fixture().await else {
            return;
        };
        let writer = PgAutomationRunPersistence::new(fixture.pool.clone(), lease());
        let stale = writer.load("run").await.unwrap().unwrap();
        let before = fixture.checkpoint().await;
        sqlx::query(update).execute(&fixture.pool).await.unwrap();
        assert!(writer.save(&stale).await.is_err(), "{update}");
        assert!(
            !writer.mark_waiting_human(support::now()).await.unwrap(),
            "{update}"
        );
        assert_eq!(fixture.checkpoint().await, before);
        fixture.close().await;
    }
}
