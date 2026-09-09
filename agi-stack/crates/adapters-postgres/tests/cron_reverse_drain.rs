//! Reverse drain (Rust to Python): the revoked barrier fails every Rust admission
//! closed, still allows exact lease cleanup, and leaves no stale-worker write path.
//! Synthetic protocol fixtures exercise fencing; they are not deployment evidence.

use agistack_adapters_postgres::{
    AutomationPayload, AutomationRunContext, AutomationRunLease, AutomationRunStatus,
    AutomationTerminalOutcome, CronControlScope, CronOperationScope, CronScheduleProjection,
    CronScheduleStatus, NewCronScheduledFire, PgAutomationRunPersistence,
    PgCronAutomationRuntimeRepository, PgCronControlRepository, PgCronOperationRepository,
    PgCronScheduleFireRepository, PgCronSchedulerOwnerRepository, PgPool,
};
use agistack_core::agent::SessionState;
use agistack_core::ports::CheckpointStore;
use chrono::{Duration, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;

#[path = "support/cron_cutover_fixture.rs"]
mod cron_cutover_fixture;

const DDL: &[&str] = &[
    "CREATE TABLE cron_jobs (
        id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL,
        revision bigint NOT NULL, schedule_revision bigint NOT NULL, enabled boolean NOT NULL,
        schedule_type text NOT NULL, schedule_config json NOT NULL, timezone text NOT NULL,
        stagger_seconds integer NOT NULL, created_at timestamptz NOT NULL,
        created_by text, conversation_id text, timeout_seconds integer NOT NULL,
        max_retries integer NOT NULL, delete_after_run boolean NOT NULL,
        state json NOT NULL DEFAULT '{}')",
    "CREATE TABLE cron_job_runs (
        id text PRIMARY KEY, job_id text NOT NULL REFERENCES cron_jobs(id), project_id text NOT NULL,
        status text NOT NULL, trigger_type text NOT NULL, accepted_at timestamptz NOT NULL,
        job_revision bigint NOT NULL, schedule_revision bigint, scheduled_for timestamptz,
        runtime_execution_id text, idempotency_key text, request_receipt_id text,
        started_at timestamptz, finished_at timestamptz, result_summary json,
        conversation_id text, error_message text, duration_ms integer,
        runtime_revision bigint NOT NULL DEFAULT 0, runtime_lease_owner text,
        runtime_lease_token text, runtime_lease_expires_at timestamptz,
        deadline_at timestamptz, last_heartbeat_at timestamptz)",
    "CREATE TABLE agistack_cron_operations (
        id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL,
        job_id text NOT NULL, job_revision bigint NOT NULL, schedule_revision bigint,
        operation_kind text NOT NULL, run_id text, trigger_type text, scheduled_for timestamptz,
        input_json jsonb NOT NULL, status text NOT NULL, attempt_count integer NOT NULL,
        max_attempts integer NOT NULL, next_attempt_at timestamptz, actor_user_id text,
        actor_api_key_id text, request_receipt_id text, result_json jsonb,
        created_at timestamptz, updated_at timestamptz, lease_owner text, lease_token text,
        lease_expires_at timestamptz, last_error_code text, last_error_redacted text,
        started_at timestamptz, completed_at timestamptz)",
    "CREATE UNIQUE INDEX reconcile_revision ON agistack_cron_operations
        (job_id, operation_kind, schedule_revision) WHERE operation_kind='reconcile_schedule'",
    "CREATE TABLE agistack_cron_schedule_state (
        job_id text PRIMARY KEY REFERENCES cron_jobs(id), tenant_id text NOT NULL,
        project_id text NOT NULL, schedule_revision bigint NOT NULL, status text NOT NULL,
        schedule_fingerprint text NOT NULL, next_fire_at timestamptz,
        last_fire_at timestamptz, last_error_code text, updated_at timestamptz)",
    "CREATE TABLE agistack_cron_scheduler_owners (
        scope_id text PRIMARY KEY, owner_kind text NOT NULL, owner_id text,
        owner_epoch bigint NOT NULL, lease_token text, lease_expires_at timestamptz,
        acquired_at timestamptz, updated_at timestamptz)",
    "CREATE TABLE agistack_legacy_cron_admissions (scope_id text, status text)",
    "CREATE TABLE agistack_checkpoints (
        session_id text PRIMARY KEY, state jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now())",
];

async fn open_schema() -> Option<(PgPool, PgPool, String)> {
    let Ok(url) = std::env::var("DATABASE_URL") else {
        eprintln!("[skip] cron reverse drain: DATABASE_URL unset");
        return None;
    };
    let admin = PgPoolOptions::new()
        .max_connections(1)
        .connect(&url)
        .await
        .unwrap();
    let schema = format!(
        "qa_cron_reverse_{}_{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    sqlx::query(&format!("CREATE SCHEMA {schema}"))
        .execute(&admin)
        .await
        .unwrap();
    let search_path = format!("SET search_path TO {schema}");
    let pool = PgPoolOptions::new()
        .max_connections(3)
        .after_connect(move |connection, _| {
            let query = search_path.clone();
            Box::pin(async move {
                sqlx::query(&query).execute(connection).await?;
                Ok(())
            })
        })
        .connect(&url)
        .await
        .unwrap();
    for ddl in DDL {
        sqlx::query(ddl).execute(&pool).await.unwrap();
    }
    Some((pool, admin, schema))
}

async fn close_schema(pool: PgPool, admin: PgPool, schema: &str) {
    pool.close().await;
    sqlx::query(&format!("DROP SCHEMA {schema} CASCADE"))
        .execute(&admin)
        .await
        .unwrap();
    admin.close().await;
}

fn now() -> chrono::DateTime<Utc> {
    Utc.with_ymd_and_hms(2099, 9, 9, 0, 0, 0).unwrap()
}

fn reverse_evidence() -> Value {
    json!({
        "protocol": "cron-cutover-evidence.v1",
        "manifest": {"deployment_id": "fixture-deployment"},
        "verification": {
            "protocol": "cron-deployment-verification.v1",
            "deployment_id": "fixture-deployment",
            "cutover_revision": 1,
            "receipt_id": "fixture-only-receipt", "verifier_id": "fixture-only-verifier",
            "inventory_sha256": "a".repeat(64), "evidence_sha256": "b".repeat(64)
        },
        "reverse": {
            "protocol": "cron-reverse-drain.v1",
            "deployment_id": "fixture-deployment",
            "source_owner_kind": "rust", "target_owner_kind": "python",
            "prepared_at": "2099-09-09T00:00:00+00:00",
            "observations_recorded": 0, "observation": null,
            "blockers": ["reverse_drain_unobserved"]
        }
    })
}

async fn seed_verified_rust_owner(pool: &PgPool) {
    sqlx::query(
        "INSERT INTO cron_jobs VALUES (
        'job', 'tenant', 'project', 1, 1, true, 'every', '{\"interval_seconds\":60}',
        'UTC', 0, $1, 'actor', NULL, 300, 0, false, '{}')",
    )
    .bind(now())
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO agistack_cron_schedule_state (
        job_id, tenant_id, project_id, schedule_revision, status, schedule_fingerprint, next_fire_at)
        VALUES ('job', 'tenant', 'project', 1, 'active', $1, $2)",
    )
    .bind("a".repeat(64))
    .bind(now())
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO agistack_cron_scheduler_owners (scope_id, owner_kind, owner_epoch)
        VALUES ('global', 'rust', 0)",
    )
    .execute(pool)
    .await
    .unwrap();
    cron_cutover_fixture::verify_cutover_fixture(pool).await;
}

#[tokio::test]
async fn reverse_preparation_fails_all_rust_admission_closed_but_allows_exact_release() {
    let Some((pool, admin, schema)) = open_schema().await else {
        return;
    };
    seed_verified_rust_owner(&pool).await;
    let ownership = PgCronSchedulerOwnerRepository::new(pool.clone());
    let authority = ownership
        .try_acquire_global("scheduler", 600, now())
        .await
        .unwrap()
        .unwrap();
    // Operator prepare-reverse: the barrier leaves `verified` in one transaction.
    sqlx::query(
        "UPDATE agistack_cron_scheduler_owners SET cutover_phase='prepared',
        cutover_revision=2, cutover_evidence=$1",
    )
    .bind(reverse_evidence())
    .execute(&pool)
    .await
    .unwrap();

    assert!(
        ownership
            .renew(&authority, 600, now() + Duration::seconds(30))
            .await
            .unwrap()
            .is_none(),
        "reverse preparation revokes owner renewal"
    );
    assert!(!ownership
        .is_current(&authority, now() + Duration::seconds(30))
        .await
        .unwrap());
    assert!(ownership
        .try_acquire_global("second-scheduler", 600, now())
        .await
        .unwrap()
        .is_none());
    let control = PgCronControlRepository::new(pool.clone());
    let scope = CronControlScope {
        tenant_id: "tenant".into(),
        project_id: "project".into(),
    };
    assert!(control
        .list_work_scopes(&authority, None, 10, now())
        .await
        .unwrap()
        .is_empty());
    assert!(control
        .admit_reconcile_operations(&authority, &scope, 10, now())
        .await
        .unwrap()
        .is_empty());
    let operations = PgCronOperationRepository::new(pool.clone());
    let operation_scope = CronOperationScope {
        tenant_id: "tenant",
        project_id: "project",
    };
    assert!(operations
        .claim_due(operation_scope, &authority, 10, "worker", 60, now())
        .await
        .unwrap()
        .is_empty());
    let fire = PgCronScheduleFireRepository::new(pool.clone());
    let candidate = fire
        .list_due(operation_scope, now(), 1)
        .await
        .unwrap()
        .pop()
        .unwrap();
    let next = CronScheduleProjection {
        status: CronScheduleStatus::Active,
        schedule_fingerprint: candidate.schedule_fingerprint.clone(),
        next_fire_at: Some(now() + Duration::seconds(60)),
    };
    let scheduled = NewCronScheduledFire {
        run_id: "reverse-blocked-run".into(),
        operation_id: "reverse-blocked-operation".into(),
        idempotency_key: "reverse-blocked".into(),
    };
    assert!(
        fire.commit_fire(
            operation_scope,
            &candidate,
            &next,
            &scheduled,
            &authority,
            now()
        )
        .await
        .unwrap()
        .is_none(),
        "reverse preparation closes new scheduled fires"
    );
    assert!(
        ownership.release(&authority, now()).await.unwrap(),
        "exact lease cleanup stays available after revocation"
    );
    assert!(
        !ownership.release(&authority, now()).await.unwrap(),
        "release is a one-shot compare-and-swap"
    );
    close_schema(pool, admin, &schema).await;
}

#[tokio::test]
async fn rollback_completion_leaves_no_rust_admission_or_stale_lease_mutation() {
    let Some((pool, admin, schema)) = open_schema().await else {
        return;
    };
    seed_verified_rust_owner(&pool).await;
    let ownership = PgCronSchedulerOwnerRepository::new(pool.clone());
    let authority = ownership
        .try_acquire_global("scheduler", 600, now())
        .await
        .unwrap()
        .unwrap();
    sqlx::query(
        "UPDATE agistack_cron_scheduler_owners SET cutover_phase='prepared',
        cutover_revision=2, cutover_evidence=$1",
    )
    .bind(reverse_evidence())
    .execute(&pool)
    .await
    .unwrap();
    assert!(ownership.release(&authority, now()).await.unwrap());
    // Operator complete-reverse: Python re-admits; stale lease fields may remain
    // from a worker that never released, fenced by owner_kind.
    sqlx::query(
        "UPDATE agistack_cron_scheduler_owners SET owner_kind='python',
        cutover_phase='unverified', cutover_revision=3,
        owner_id='gone-worker', lease_token='gone-token', lease_expires_at=$1",
    )
    .bind(now() + Duration::seconds(600))
    .execute(&pool)
    .await
    .unwrap();

    assert!(ownership
        .try_acquire_global("scheduler", 600, now())
        .await
        .unwrap()
        .is_none());
    assert!(!ownership.is_current(&authority, now()).await.unwrap());
    assert!(ownership
        .renew(&authority, 600, now())
        .await
        .unwrap()
        .is_none());
    assert!(
        !ownership.release(&authority, now()).await.unwrap(),
        "a stale worker cannot mutate the rolled-back row; its release is a harmless no-op"
    );
    let owner_kind: String =
        sqlx::query_scalar("SELECT owner_kind FROM agistack_cron_scheduler_owners")
            .fetch_one(&pool)
            .await
            .unwrap();
    assert_eq!(owner_kind, "python", "Python admission reopens only now");
    close_schema(pool, admin, &schema).await;
}

#[tokio::test]
async fn stale_worker_write_back_is_rejected_once_the_run_lease_is_lost() {
    let Some((pool, admin, schema)) = open_schema().await else {
        return;
    };
    seed_verified_rust_owner(&pool).await;
    // A crash-interrupted run whose runtime lease already expired: the reverse
    // drain records it as resumable, and the stale worker that wakes later must
    // fail closed on every write path. The expiry predates the database clock.
    let expired = Utc.with_ymd_and_hms(2000, 1, 1, 0, 0, 0).unwrap();
    sqlx::query(
        "INSERT INTO cron_job_runs (id, job_id, project_id, status, trigger_type, accepted_at,
        job_revision, runtime_execution_id, conversation_id, runtime_revision,
        runtime_lease_owner, runtime_lease_token, runtime_lease_expires_at, deadline_at)
        VALUES ('run', 'job', 'project', 'running', 'scheduled', $1, 1, 'run', 'conversation', 7,
        'stale-worker', 'stale-token', $2, $3)",
    )
    .bind(now() - Duration::seconds(120))
    .bind(expired)
    .bind(now() + Duration::minutes(5))
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO agistack_cron_operations (id, tenant_id, project_id, job_id, job_revision,
        operation_kind, run_id, input_json, status, attempt_count, max_attempts, actor_user_id)
        VALUES ('operation', 'tenant', 'project', 'job', 1, 'execute_run', 'run', '{}',
        'waiting_runtime', 0, 5, 'actor')",
    )
    .execute(&pool)
    .await
    .unwrap();
    let lease = AutomationRunLease {
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
        lease_owner: "stale-worker".into(),
        lease_token: "stale-token".into(),
        lease_expires_at: expired,
        deadline_at: now() + Duration::minutes(5),
    };
    let persistence = PgAutomationRunPersistence::new(pool.clone(), lease.clone());
    let mut state = SessionState::new("run", "test", Some("project"));
    state.status = agistack_core::agent::SessionStatus::Running;
    assert!(
        persistence.save(&state).await.is_err(),
        "checkpoint write-back fails closed with a lost run lease"
    );
    assert!(
        persistence.load("run").await.is_err(),
        "checkpoint reads are fenced by the same authority"
    );
    assert!(
        !persistence.mark_waiting_human(now()).await.unwrap(),
        "a stale worker cannot park the run for HITL"
    );
    let runtime = PgCronAutomationRuntimeRepository::new(pool.clone());
    assert!(
        runtime
            .project_terminal(
                &lease,
                AutomationTerminalOutcome::Success,
                None,
                0,
                0,
                now()
            )
            .await
            .is_err(),
        "terminal write-back from a stale worker is rejected"
    );
    let status: String = sqlx::query_scalar("SELECT status FROM cron_job_runs WHERE id = 'run'")
        .fetch_one(&pool)
        .await
        .unwrap();
    assert_eq!(
        status, "running",
        "the resumable run is never abandoned mid-flight"
    );
    close_schema(pool, admin, &schema).await;
}
