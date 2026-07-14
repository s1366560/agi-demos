use agistack_adapters_postgres::{
    AutomationRuntimeScope, AutomationTerminalOutcome, CronOperationKind, CronOperationScope,
    NewCronOperation, PgCronAutomationRuntimeRepository, PgCronOperationRepository,
    PgCronSchedulerOwnerRepository,
};
use serde_json::json;
use std::time::Duration;

use super::support::*;

#[tokio::test]
async fn cron_runtime_claim_and_terminal_projection_are_fenced_and_atomic() {
    let Some(pool) =
        pool_or_skip("cron_runtime_claim_and_terminal_projection_are_fenced_and_atomic").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_runtime_schema(&pool).await;
    clean_runtime_rows(&pool).await;
    let Some((project_id, tenant_id, user_id)) = sqlx::query_as::<_, (String, String, String)>(
        "SELECT id, tenant_id, owner_id FROM projects ORDER BY id LIMIT 1",
    )
    .fetch_optional(&pool)
    .await
    .expect("load runtime scope") else {
        return;
    };

    let now = ts(2026, 7, 14, 15, 0, 0);
    let authority = acquire_runtime_scheduler_authority(&pool, now).await;
    let job_id = "cron_runtime_job_success";
    let run_id = "cron_runtime_run_success";
    insert_job_and_run(
        &pool,
        &tenant_id,
        &project_id,
        &user_id,
        job_id,
        run_id,
        true,
        now,
    )
    .await;
    let operation_repo = PgCronOperationRepository::new(pool.clone());
    let operation = operation_repo
        .enqueue(NewCronOperation {
            id: "cron_runtime_operation_success".to_string(),
            tenant_id: tenant_id.clone(),
            project_id: project_id.clone(),
            job_id: job_id.to_string(),
            job_revision: 1,
            schedule_revision: None,
            kind: CronOperationKind::ExecuteRun,
            run_id: Some(run_id.to_string()),
            trigger_type: Some("manual".to_string()),
            scheduled_for: None,
            input_json: json!({
                "runtime_execution_id": run_id,
                "timeout_seconds": 300,
                "delete_after_run": true,
                "one_shot": false,
                "max_retries": 3
            }),
            actor_user_id: Some(user_id.clone()),
            actor_api_key_id: None,
            request_receipt_id: None,
            max_attempts: 3,
            next_attempt_at: Some(now),
            created_at: now,
        })
        .await
        .expect("enqueue runtime operation");
    let operation_scope = CronOperationScope {
        tenant_id: &tenant_id,
        project_id: &project_id,
    };
    let claim = operation_repo
        .claim_due(operation_scope, &authority, 1, "operation-worker", 30, now)
        .await
        .expect("claim runtime operation")
        .pop()
        .expect("runtime operation claimed");
    let runtime_repo = PgCronAutomationRuntimeRepository::new(pool.clone());
    let prepared = runtime_repo
        .prepare_dispatch(&claim, "cron_runtime_conversation_success", now)
        .await
        .expect("prepare durable dispatch");
    assert_eq!(prepared.run_id, run_id);
    assert_eq!(
        prepared.conversation_id,
        "cron_runtime_conversation_success"
    );

    operation_repo
        .mark_waiting_runtime(
            operation_scope,
            &operation.id,
            "operation-worker",
            claim.lease_token.as_deref().expect("operation lease token"),
            &json!({"runtime_execution_id": run_id}),
            now + Duration::from_secs(1),
        )
        .await
        .expect("accept runtime dispatch")
        .expect("operation lease remains active");

    let runtime_scope = AutomationRuntimeScope {
        tenant_id: tenant_id.clone(),
        project_id: project_id.clone(),
    };
    let lease = runtime_repo
        .claim_due(
            &runtime_scope,
            1,
            "runtime-worker",
            30,
            now + Duration::from_secs(2),
        )
        .await
        .expect("claim durable runtime")
        .pop()
        .expect("queued runtime is claimable");
    assert_eq!(lease.context.runtime_execution_id, run_id);
    assert!(lease.deadline_at > now);

    let terminal = runtime_repo
        .project_terminal(
            &lease,
            AutomationTerminalOutcome::Success,
            None,
            4,
            125,
            now + Duration::from_secs(3),
        )
        .await
        .expect("project first terminal result");
    assert!(!terminal.duplicate);
    assert_eq!(terminal.operation_status.as_deref(), Some("completed"));

    let duplicate = runtime_repo
        .project_terminal(
            &lease,
            AutomationTerminalOutcome::Success,
            None,
            4,
            125,
            now + Duration::from_secs(4),
        )
        .await
        .expect("same terminal result is idempotent");
    assert!(duplicate.duplicate);

    let (run_status, operation_status, enabled, state) =
        sqlx::query_as::<_, (String, String, bool, serde_json::Value)>(
            "SELECT run.status, operation.status, job.enabled, job.state \
             FROM cron_job_runs AS run \
             JOIN cron_jobs AS job ON job.id = run.job_id \
             JOIN agistack_cron_operations AS operation ON operation.run_id = run.id \
             WHERE run.id = $1",
        )
        .bind(run_id)
        .fetch_one(&pool)
        .await
        .expect("load projected runtime");
    assert_eq!(run_status, "success");
    assert_eq!(operation_status, "completed");
    assert!(!enabled);
    assert_eq!(state["retired_reason"], "delete_after_run");

    clean_runtime_rows(&pool).await;
}

#[tokio::test]
async fn cron_runtime_timeout_recovery_is_idempotent() {
    let Some(pool) = pool_or_skip("cron_runtime_timeout_recovery_is_idempotent").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_runtime_schema(&pool).await;
    clean_runtime_rows(&pool).await;
    let Some((project_id, tenant_id, user_id)) = sqlx::query_as::<_, (String, String, String)>(
        "SELECT id, tenant_id, owner_id FROM projects ORDER BY id LIMIT 1",
    )
    .fetch_optional(&pool)
    .await
    .expect("load runtime scope") else {
        return;
    };
    let now = ts(2026, 7, 14, 16, 0, 0);
    let job_id = "cron_runtime_job_timeout";
    let run_id = "cron_runtime_run_timeout";
    insert_job_and_run(
        &pool,
        &tenant_id,
        &project_id,
        &user_id,
        job_id,
        run_id,
        false,
        now,
    )
    .await;
    let conversation_id = "cron_runtime_conversation_timeout";
    sqlx::query(
        "INSERT INTO conversations ( \
            id, project_id, tenant_id, user_id, title, status, agent_config, meta, \
            message_count, current_mode, merge_strategy, created_at, updated_at \
         ) VALUES ( \
            $1, $2, $3, $4, 'Runtime timeout test', 'active', '{}'::json, '{}'::json, \
            0, 'build', 'result_only', $5, $5 \
         )",
    )
    .bind(conversation_id)
    .bind(&project_id)
    .bind(&tenant_id)
    .bind(&user_id)
    .bind(now)
    .execute(&pool)
    .await
    .expect("insert timeout runtime conversation");
    sqlx::query(
        "UPDATE cron_job_runs SET status = 'running', deadline_at = $2, \
         runtime_revision = 1, conversation_id = $3 WHERE id = $1",
    )
    .bind(run_id)
    .bind(now - Duration::from_secs(1))
    .bind(conversation_id)
    .execute(&pool)
    .await
    .expect("expire runtime deadline");
    sqlx::query(
        "INSERT INTO agistack_cron_operations ( \
            id, tenant_id, project_id, job_id, job_revision, operation_kind, run_id, \
            input_json, status, attempt_count, max_attempts, actor_user_id, result_json, \
            created_at, updated_at \
         ) VALUES ( \
            'cron_runtime_operation_timeout', $1, $2, $3, 1, 'execute_run', $4, \
            '{\"timeout_seconds\":300,\"max_retries\":3}'::jsonb, 'waiting_runtime', \
            1, 3, $5, '{}'::jsonb, $6, $6 \
         )",
    )
    .bind(&tenant_id)
    .bind(&project_id)
    .bind(job_id)
    .bind(run_id)
    .bind(&user_id)
    .bind(now)
    .execute(&pool)
    .await
    .expect("insert waiting runtime operation");

    let repo = PgCronAutomationRuntimeRepository::new(pool.clone());
    let scope = AutomationRuntimeScope {
        tenant_id,
        project_id,
    };
    assert_eq!(repo.recover_expired(&scope, 10, now).await.unwrap(), 1);
    assert_eq!(repo.recover_expired(&scope, 10, now).await.unwrap(), 0);
    let (status, consecutive_errors) = sqlx::query_as::<_, (String, i64)>(
        "SELECT run.status, COALESCE((job.state->>'consecutive_errors')::bigint, 0) \
         FROM cron_job_runs AS run JOIN cron_jobs AS job ON job.id = run.job_id \
         WHERE run.id = $1",
    )
    .bind(run_id)
    .fetch_one(&pool)
    .await
    .expect("load timed out runtime");
    assert_eq!(status, "timeout");
    assert_eq!(consecutive_errors, 1);

    clean_runtime_rows(&pool).await;
}

#[allow(clippy::too_many_arguments)]
async fn insert_job_and_run(
    pool: &PgPool,
    tenant_id: &str,
    project_id: &str,
    user_id: &str,
    job_id: &str,
    run_id: &str,
    delete_after_run: bool,
    now: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO cron_jobs ( \
            id, project_id, tenant_id, name, enabled, delete_after_run, revision, \
            schedule_revision, schedule_type, schedule_config, payload_type, payload_config, \
            delivery_type, delivery_config, conversation_mode, timezone, stagger_seconds, \
            timeout_seconds, max_retries, state, created_by, created_at \
         ) VALUES ( \
            $1, $2, $3, 'Runtime test', true, $4, 1, 1, 'every', '{}'::json, \
            'agent_turn', '{\"message\":\"Run the durable task\"}'::json, 'none', \
            '{}'::json, 'fresh', 'UTC', 0, 300, 3, '{}'::json, $5, $6 \
         )",
    )
    .bind(job_id)
    .bind(project_id)
    .bind(tenant_id)
    .bind(delete_after_run)
    .bind(user_id)
    .bind(now)
    .execute(pool)
    .await
    .expect("insert runtime job");
    sqlx::query(
        "INSERT INTO cron_job_runs ( \
            id, job_id, project_id, status, trigger_type, accepted_at, job_revision, \
            schedule_revision, runtime_execution_id, runtime_revision, started_at, result_summary \
         ) VALUES ($1, $2, $3, 'queued', 'manual', $4, 1, 1, $1, 0, $4, '{}'::json)",
    )
    .bind(run_id)
    .bind(job_id)
    .bind(project_id)
    .bind(now)
    .execute(pool)
    .await
    .expect("insert runtime run");
}

async fn ensure_runtime_schema(pool: &PgPool) {
    for ddl in [
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS accepted_at timestamptz DEFAULT now() NOT NULL",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS job_revision bigint DEFAULT 1 NOT NULL",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS schedule_revision bigint",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS runtime_execution_id text",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS runtime_revision bigint DEFAULT 0 NOT NULL",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS runtime_lease_owner varchar(255)",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS runtime_lease_token varchar(255)",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS runtime_lease_expires_at timestamptz",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS deadline_at timestamptz",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS last_heartbeat_at timestamptz",
        "CREATE TABLE IF NOT EXISTS agistack_cron_operations ( \
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL, \
            job_id text NOT NULL, job_revision bigint NOT NULL, schedule_revision bigint, \
            operation_kind varchar(40) NOT NULL, run_id text, trigger_type varchar(40), \
            scheduled_for timestamptz, input_json jsonb NOT NULL DEFAULT '{}'::jsonb, \
            status varchar(32) NOT NULL DEFAULT 'pending', attempt_count integer NOT NULL DEFAULT 0, \
            max_attempts integer NOT NULL DEFAULT 5, next_attempt_at timestamptz, \
            lease_owner varchar(255), lease_token varchar(255), lease_expires_at timestamptz, \
            actor_user_id text, actor_api_key_id text, request_receipt_id text, \
            result_json jsonb NOT NULL DEFAULT '{}'::jsonb, last_error_code varchar(100), \
            last_error_redacted text, created_at timestamptz NOT NULL DEFAULT now(), \
            updated_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, \
            completed_at timestamptz, cancel_requested_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS agistack_cron_scheduler_owners ( \
            scope_id varchar(100) PRIMARY KEY, owner_kind varchar(20) NOT NULL DEFAULT 'off', \
            owner_id varchar(255), owner_epoch bigint NOT NULL DEFAULT 0, \
            lease_token varchar(255), lease_expires_at timestamptz, acquired_at timestamptz, \
            updated_at timestamptz NOT NULL DEFAULT now())",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|error| panic!("runtime ddl failed: {ddl}\n{error}"));
    }
}

async fn acquire_runtime_scheduler_authority(
    pool: &PgPool,
    now: DateTime<Utc>,
) -> agistack_adapters_postgres::CronSchedulerLease {
    sqlx::query(
        "INSERT INTO agistack_cron_scheduler_owners ( \
            scope_id, owner_kind, owner_epoch, updated_at \
         ) VALUES ('global', 'rust', 0, $1) \
         ON CONFLICT (scope_id) DO UPDATE SET owner_kind = 'rust', owner_id = NULL, \
            lease_token = NULL, lease_expires_at = NULL, updated_at = EXCLUDED.updated_at",
    )
    .bind(now)
    .execute(pool)
    .await
    .expect("delegate runtime scheduler ownership to Rust");
    PgCronSchedulerOwnerRepository::new(pool.clone())
        .try_acquire_global("cron-runtime-operation-worker", 300, now)
        .await
        .expect("acquire runtime scheduler authority")
        .expect("Rust cutover grants runtime scheduler authority")
}

async fn clean_runtime_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM agistack_cron_operations WHERE id LIKE 'cron_runtime_%'")
        .execute(pool)
        .await
        .expect("clean runtime operations");
    sqlx::query("DELETE FROM cron_job_runs WHERE id LIKE 'cron_runtime_%'")
        .execute(pool)
        .await
        .expect("clean runtime runs");
    sqlx::query("DELETE FROM conversations WHERE id LIKE 'cron_runtime_%'")
        .execute(pool)
        .await
        .expect("clean runtime conversations");
    sqlx::query("DELETE FROM cron_jobs WHERE id LIKE 'cron_runtime_%'")
        .execute(pool)
        .await
        .expect("clean runtime jobs");
    sqlx::query("DELETE FROM agistack_cron_scheduler_owners WHERE scope_id = 'global'")
        .execute(pool)
        .await
        .expect("clean runtime scheduler owner");
}
