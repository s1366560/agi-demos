use agistack_adapters_postgres::{
    CronOperationKind, CronOperationRecord, CronOperationScope, CronOperationStatus,
    CronScheduleProjection, CronScheduleRepositoryError, CronScheduleStatus, NewCronScheduledFire,
    PgCronScheduleFireRepository, PgCronScheduleRepository,
};
use serde_json::json;

use super::support::*;

#[tokio::test]
async fn cron_schedule_projection_is_scope_and_schedule_revision_fenced() {
    let Some(pool) =
        pool_or_skip("cron_schedule_projection_is_scope_and_schedule_revision_fenced").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_schedule_state_table(&pool).await;
    ensure_scheduled_fire_tables(&pool).await;
    clean_rows(&pool).await;
    let Some((project_id, tenant_id, user_id)) = sqlx::query_as::<_, (String, String, String)>(
        "SELECT id, tenant_id, owner_id FROM projects ORDER BY id LIMIT 1",
    )
    .fetch_optional(&pool)
    .await
    .expect("load project scope") else {
        return;
    };
    let now = ts(2026, 7, 14, 10, 0, 0);
    sqlx::query(
        "INSERT INTO cron_jobs ( \
            id, project_id, tenant_id, name, enabled, revision, schedule_revision, \
            schedule_type, schedule_config, payload_type, payload_config, timezone, \
            stagger_seconds, created_by, created_at \
         ) VALUES ( \
            'cron_schedule_job', $1, $2, 'Schedule projection', true, 4, 1, 'every', \
            '{\"interval_seconds\":60}'::json, 'agent_turn', \
            '{\"message\":\"run\"}'::json, 'UTC', 0, $3, $4 \
         )",
    )
    .bind(&project_id)
    .bind(&tenant_id)
    .bind(&user_id)
    .bind(now)
    .execute(&pool)
    .await
    .expect("insert schedule job");

    let repo = PgCronScheduleRepository::new(pool.clone());
    let operation = operation(&tenant_id, &project_id, now);
    let snapshot = repo
        .load_target(&operation)
        .await
        .expect("load exact target");
    assert_eq!(snapshot.schedule_revision, 1);
    assert_eq!(snapshot.schedule_config["interval_seconds"], 60);

    let projection = CronScheduleProjection {
        status: CronScheduleStatus::Active,
        schedule_fingerprint: "a".repeat(64),
        next_fire_at: Some(now + std::time::Duration::from_secs(60)),
    };
    let materialized = repo
        .apply_projection(&operation, &projection, now)
        .await
        .expect("apply exact projection")
        .expect("exact projection materializes");
    assert_eq!(materialized.next_fire_at, projection.next_fire_at);
    let (revision, status, next_fire_at) =
        sqlx::query_as::<_, (i64, String, Option<DateTime<Utc>>)>(
            "SELECT schedule_revision, status, next_fire_at \
         FROM agistack_cron_schedule_state WHERE job_id = 'cron_schedule_job'",
        )
        .fetch_one(&pool)
        .await
        .expect("load schedule state");
    assert_eq!(revision, 1);
    assert_eq!(status, "active");
    assert_eq!(next_fire_at, projection.next_fire_at);

    let replay_projection = CronScheduleProjection {
        next_fire_at: Some(now + std::time::Duration::from_secs(120)),
        ..projection.clone()
    };
    let replayed = repo
        .apply_projection(
            &operation,
            &replay_projection,
            now + std::time::Duration::from_secs(30),
        )
        .await
        .expect("replay same revision")
        .expect("same fingerprint is idempotent");
    assert_eq!(replayed.next_fire_at, projection.next_fire_at);

    sqlx::query("UPDATE cron_jobs SET schedule_revision = 2 WHERE id = 'cron_schedule_job'")
        .execute(&pool)
        .await
        .expect("advance source revision");
    assert!(repo
        .apply_projection(&operation, &projection, now)
        .await
        .expect("stale projection is a closed compare-and-set")
        .is_none());
    assert_eq!(
        repo.load_target(&operation).await,
        Err(CronScheduleRepositoryError::StaleRevision)
    );

    let mut wrong_scope = operation.clone();
    wrong_scope.tenant_id = "another-tenant".to_string();
    assert_eq!(
        repo.load_target(&wrong_scope).await,
        Err(CronScheduleRepositoryError::NotFound)
    );
    clean_rows(&pool).await;
}

#[tokio::test]
async fn due_schedule_fire_atomically_creates_run_operation_and_advances_cursor() {
    let Some(pool) =
        pool_or_skip("due_schedule_fire_atomically_creates_run_operation_and_advances_cursor")
            .await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_schedule_state_table(&pool).await;
    ensure_scheduled_fire_tables(&pool).await;
    clean_rows(&pool).await;
    let Some((project_id, tenant_id, user_id)) = sqlx::query_as::<_, (String, String, String)>(
        "SELECT id, tenant_id, owner_id FROM projects ORDER BY id LIMIT 1",
    )
    .fetch_optional(&pool)
    .await
    .expect("load project scope") else {
        return;
    };
    let now = ts(2026, 7, 14, 11, 0, 0);
    sqlx::query(
        "INSERT INTO cron_jobs ( \
            id, project_id, tenant_id, name, enabled, revision, schedule_revision, \
            schedule_type, schedule_config, payload_type, payload_config, timezone, \
            stagger_seconds, timeout_seconds, max_retries, created_by, created_at \
         ) VALUES ( \
            'cron_schedule_fire_job', $1, $2, 'Scheduled fire', true, 5, 2, 'every', \
            '{\"interval_seconds\":60}'::json, 'agent_turn', \
            '{\"message\":\"run\"}'::json, 'UTC', 0, 300, 3, $3, $4)",
    )
    .bind(&project_id)
    .bind(&tenant_id)
    .bind(&user_id)
    .bind(now - std::time::Duration::from_secs(60))
    .execute(&pool)
    .await
    .expect("insert fire job");
    sqlx::query(
        "INSERT INTO agistack_cron_schedule_state ( \
            job_id, tenant_id, project_id, schedule_revision, status, \
            schedule_fingerprint, next_fire_at, updated_at \
         ) VALUES ('cron_schedule_fire_job', $1, $2, 2, 'active', $3, $4, $4)",
    )
    .bind(&tenant_id)
    .bind(&project_id)
    .bind("a".repeat(64))
    .bind(now)
    .execute(&pool)
    .await
    .expect("insert due cursor");

    let scope = CronOperationScope {
        tenant_id: &tenant_id,
        project_id: &project_id,
    };
    let repo = PgCronScheduleFireRepository::new(pool.clone());
    let candidate = repo
        .list_due(scope, now, 10)
        .await
        .expect("list due cursors")
        .pop()
        .expect("due cursor");
    let next = CronScheduleProjection {
        status: CronScheduleStatus::Active,
        schedule_fingerprint: "a".repeat(64),
        next_fire_at: Some(now + std::time::Duration::from_secs(60)),
    };
    let fire = NewCronScheduledFire {
        run_id: "cron_schedule_fire_run".to_string(),
        operation_id: "cron_schedule_fire_operation".to_string(),
        idempotency_key: "scheduled:2:2026-07-14T11:00:00Z".to_string(),
    };

    let competing_repo = repo.clone();
    let (left, right) = tokio::join!(
        repo.commit_fire(scope, &candidate, &next, &fire, now),
        competing_repo.commit_fire(scope, &candidate, &next, &fire, now),
    );
    let left = left.expect("first competing scheduler query");
    let right = right.expect("second competing scheduler query");
    assert_eq!(
        usize::from(left.is_some()) + usize::from(right.is_some()),
        1
    );
    let committed = left
        .or(right)
        .expect("one exact cursor wins compare-and-set");
    assert_eq!(committed.scheduled_for, now);
    assert!(repo
        .commit_fire(scope, &candidate, &next, &fire, now)
        .await
        .expect("replay is a closed compare-and-set")
        .is_none());

    let (run_status, scheduled_for, runtime_execution_id) =
        sqlx::query_as::<_, (String, Option<DateTime<Utc>>, Option<String>)>(
            "SELECT status, scheduled_for, runtime_execution_id \
             FROM cron_job_runs WHERE id = 'cron_schedule_fire_run'",
        )
        .fetch_one(&pool)
        .await
        .expect("load scheduled run");
    assert_eq!(run_status, "queued");
    assert_eq!(scheduled_for, Some(now));
    assert_eq!(
        runtime_execution_id.as_deref(),
        Some("cron_schedule_fire_run")
    );
    let (operation_status, operation_run_id, actor_user_id, input_json) =
        sqlx::query_as::<_, (String, Option<String>, Option<String>, serde_json::Value)>(
            "SELECT status, run_id, actor_user_id, input_json \
             FROM agistack_cron_operations WHERE id = 'cron_schedule_fire_operation'",
        )
        .fetch_one(&pool)
        .await
        .expect("load scheduled operation");
    assert_eq!(operation_status, "pending");
    assert_eq!(operation_run_id.as_deref(), Some("cron_schedule_fire_run"));
    assert_eq!(actor_user_id.as_deref(), Some(user_id.as_str()));
    assert_eq!(input_json["runtime_execution_id"], "cron_schedule_fire_run");
    let (last_fire_at, next_fire_at) =
        sqlx::query_as::<_, (Option<DateTime<Utc>>, Option<DateTime<Utc>>)>(
            "SELECT last_fire_at, next_fire_at FROM agistack_cron_schedule_state \
             WHERE job_id = 'cron_schedule_fire_job'",
        )
        .fetch_one(&pool)
        .await
        .expect("load advanced cursor");
    assert_eq!(last_fire_at, Some(now));
    assert_eq!(next_fire_at, next.next_fire_at);
    clean_rows(&pool).await;
}

fn operation(tenant_id: &str, project_id: &str, now: DateTime<Utc>) -> CronOperationRecord {
    CronOperationRecord {
        id: "cron_schedule_operation".to_string(),
        tenant_id: tenant_id.to_string(),
        project_id: project_id.to_string(),
        job_id: "cron_schedule_job".to_string(),
        job_revision: 4,
        schedule_revision: Some(1),
        kind: CronOperationKind::ReconcileSchedule,
        run_id: None,
        trigger_type: None,
        scheduled_for: None,
        input_json: json!({}),
        status: CronOperationStatus::Processing,
        attempt_count: 1,
        max_attempts: 3,
        next_attempt_at: None,
        lease_owner: Some("worker-1".to_string()),
        lease_token: Some("lease-1".to_string()),
        lease_expires_at: Some(now + std::time::Duration::from_secs(30)),
        actor_user_id: None,
        actor_api_key_id: None,
        request_receipt_id: None,
        last_error_code: None,
        last_error_redacted: None,
        result_json: json!({}),
        created_at: now,
        updated_at: now,
        started_at: Some(now),
        completed_at: None,
    }
}

async fn ensure_schedule_state_table(pool: &PgPool) {
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_cron_schedule_state ( \
            job_id text PRIMARY KEY REFERENCES cron_jobs(id) ON DELETE CASCADE, \
            tenant_id text NOT NULL, project_id text NOT NULL, schedule_revision bigint NOT NULL, \
            status varchar(32) NOT NULL DEFAULT 'active', schedule_fingerprint varchar(128) NOT NULL, \
            next_fire_at timestamptz, last_fire_at timestamptz, last_error_code varchar(100), \
            updated_at timestamptz NOT NULL DEFAULT now())",
    )
    .execute(pool)
    .await
    .expect("ensure cron schedule state table");
}

async fn ensure_scheduled_fire_tables(pool: &PgPool) {
    for ddl in [
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS accepted_at timestamptz DEFAULT now() NOT NULL",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS job_revision bigint DEFAULT 1 NOT NULL",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS schedule_revision bigint",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS scheduled_for timestamptz",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS runtime_execution_id text",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS idempotency_key varchar(255)",
        "ALTER TABLE cron_job_runs ADD COLUMN IF NOT EXISTS request_receipt_id text",
        "CREATE TABLE IF NOT EXISTS agistack_cron_operations ( \
            id varchar PRIMARY KEY, tenant_id varchar NOT NULL, project_id varchar NOT NULL, \
            job_id varchar NOT NULL, job_revision bigint NOT NULL, schedule_revision bigint, \
            operation_kind varchar(40) NOT NULL, run_id varchar, trigger_type varchar(40), \
            scheduled_for timestamptz, input_json jsonb NOT NULL DEFAULT '{}'::jsonb, \
            status varchar(32) NOT NULL DEFAULT 'pending', attempt_count integer NOT NULL DEFAULT 0, \
            max_attempts integer NOT NULL DEFAULT 5, next_attempt_at timestamptz, \
            lease_owner varchar(255), lease_token varchar(255), lease_expires_at timestamptz, \
            actor_user_id varchar, actor_api_key_id varchar, request_receipt_id varchar, \
            result_json jsonb NOT NULL DEFAULT '{}'::jsonb, last_error_code varchar(100), \
            last_error_redacted text, created_at timestamptz NOT NULL DEFAULT now(), \
            updated_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, \
            completed_at timestamptz, cancel_requested_at timestamptz)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .expect("ensure scheduled fire table shape");
    }
}

async fn clean_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM agistack_cron_schedule_state WHERE job_id LIKE 'cron_schedule_%'")
        .execute(pool)
        .await
        .expect("clean schedule state");
    sqlx::query("DELETE FROM agistack_cron_operations WHERE id LIKE 'cron_schedule_%'")
        .execute(pool)
        .await
        .expect("clean schedule operations");
    sqlx::query("DELETE FROM cron_job_runs WHERE id LIKE 'cron_schedule_%'")
        .execute(pool)
        .await
        .expect("clean schedule runs");
    sqlx::query("DELETE FROM cron_jobs WHERE id LIKE 'cron_schedule_%'")
        .execute(pool)
        .await
        .expect("clean schedule job");
}
