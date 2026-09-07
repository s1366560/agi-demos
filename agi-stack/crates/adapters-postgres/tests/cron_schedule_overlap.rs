//! Scheduled overlap admission against real PostgreSQL in a private schema.

use agistack_adapters_postgres::{
    CronOperationScope, CronScheduleProjection, CronScheduleStatus, NewCronScheduledFire,
    PgCronScheduleFireRepository, PgCronSchedulerOwnerRepository,
};
use chrono::{Duration, TimeZone, Utc};
use sqlx::postgres::PgPoolOptions;

#[tokio::test]
async fn scheduled_overlaps_record_skipped_history_without_queuing_operations() {
    let Ok(url) = std::env::var("DATABASE_URL") else {
        eprintln!("[skip] scheduled overlap: DATABASE_URL unset");
        return;
    };
    let admin = PgPoolOptions::new()
        .max_connections(1)
        .connect(&url)
        .await
        .unwrap();
    let schema = format!("qa_cron_fire_{}", std::process::id());
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
    for ddl in [
        "CREATE TABLE cron_jobs (
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL,
            revision bigint NOT NULL, schedule_revision bigint NOT NULL, enabled boolean NOT NULL,
            schedule_type text NOT NULL, schedule_config json NOT NULL, timezone text NOT NULL,
            stagger_seconds integer NOT NULL, created_at timestamptz NOT NULL,
            created_by text, conversation_id text, timeout_seconds integer NOT NULL,
            max_retries integer NOT NULL, delete_after_run boolean NOT NULL)",
        "CREATE TABLE cron_job_runs (
            id text PRIMARY KEY, job_id text NOT NULL REFERENCES cron_jobs(id), project_id text NOT NULL,
            status text NOT NULL, trigger_type text NOT NULL, accepted_at timestamptz NOT NULL,
            job_revision bigint NOT NULL, schedule_revision bigint, scheduled_for timestamptz,
            runtime_execution_id text, idempotency_key text, request_receipt_id text,
            started_at timestamptz, finished_at timestamptz, result_summary json,
            conversation_id text, error_message text, duration_ms integer)",
        "CREATE TABLE agistack_cron_operations (
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL,
            job_id text NOT NULL, job_revision bigint NOT NULL, schedule_revision bigint,
            operation_kind text NOT NULL, run_id text, trigger_type text, scheduled_for timestamptz,
            input_json jsonb NOT NULL, status text NOT NULL, attempt_count integer NOT NULL,
            max_attempts integer NOT NULL, next_attempt_at timestamptz, actor_user_id text,
            actor_api_key_id text, request_receipt_id text, result_json jsonb,
            created_at timestamptz, updated_at timestamptz)",
        "CREATE TABLE agistack_cron_schedule_state (
            job_id text PRIMARY KEY REFERENCES cron_jobs(id), tenant_id text NOT NULL,
            project_id text NOT NULL, schedule_revision bigint NOT NULL, status text NOT NULL,
            schedule_fingerprint text NOT NULL, next_fire_at timestamptz,
            last_fire_at timestamptz, last_error_code text, updated_at timestamptz)",
        "CREATE TABLE agistack_cron_scheduler_owners (
            scope_id text PRIMARY KEY, owner_kind text NOT NULL, owner_id text,
            owner_epoch bigint NOT NULL, lease_token text, lease_expires_at timestamptz,
            acquired_at timestamptz, updated_at timestamptz)",
    ] {
        sqlx::query(ddl).execute(&pool).await.unwrap();
    }
    sqlx::query("CREATE TABLE agistack_legacy_cron_admissions (scope_id text, status text)")
        .execute(&pool)
        .await
        .unwrap();
    let now = Utc.with_ymd_and_hms(2099, 9, 7, 0, 0, 0).unwrap();
    sqlx::query(
        "INSERT INTO cron_jobs VALUES (
        'job', 'tenant', 'project', 1, 1, true, 'every', '{\"interval_seconds\":60}',
        'UTC', 0, $1, 'actor', NULL, 300, 0, false)",
    )
    .bind(now)
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO cron_job_runs (id, job_id, project_id, status,
        trigger_type, accepted_at, job_revision) VALUES (
        'prior', 'job', 'project', 'queued', 'manual', $1, 1)",
    )
    .bind(now)
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO agistack_cron_schedule_state (
        job_id, tenant_id, project_id, schedule_revision, status, schedule_fingerprint, next_fire_at)
        VALUES ('job', 'tenant', 'project', 1, 'active', $1, $2)")
        .bind("a".repeat(64)).bind(now).execute(&pool).await.unwrap();
    sqlx::query(
        "INSERT INTO agistack_cron_scheduler_owners (scope_id, owner_kind, owner_epoch)
        VALUES ('global', 'rust', 0)",
    )
    .execute(&pool)
    .await
    .unwrap();
    let authority = PgCronSchedulerOwnerRepository::new(pool.clone())
        .try_acquire_global("scheduler", 600, now)
        .await
        .unwrap()
        .unwrap();
    let repository = PgCronScheduleFireRepository::new(pool.clone());
    let scope = CronOperationScope {
        tenant_id: "tenant",
        project_id: "project",
    };

    for (index, status) in ["queued", "running", "waiting_human", "success"]
        .iter()
        .enumerate()
    {
        sqlx::query("UPDATE cron_job_runs SET status = $1 WHERE id = 'prior'")
            .bind(status)
            .execute(&pool)
            .await
            .unwrap();
        let observed = now + Duration::seconds(index as i64 * 60);
        let candidate = repository
            .list_due(scope, observed, 1)
            .await
            .unwrap()
            .pop()
            .unwrap();
        let next = CronScheduleProjection {
            status: CronScheduleStatus::Active,
            schedule_fingerprint: candidate.schedule_fingerprint.clone(),
            next_fire_at: Some(observed + Duration::seconds(60)),
        };
        let fire = NewCronScheduledFire {
            run_id: format!("scheduled-{index}"),
            operation_id: format!("operation-{index}"),
            idempotency_key: format!("scheduled:1:{observed}"),
        };
        repository
            .commit_fire(scope, &candidate, &next, &fire, &authority, observed)
            .await
            .unwrap()
            .expect("cursor commits");
        let (run_status, reason, finished): (String, Option<String>, bool) = sqlx::query_as(
            "SELECT status, error_message, finished_at IS NOT NULL FROM cron_job_runs WHERE id = $1")
            .bind(&fire.run_id).fetch_one(&pool).await.unwrap();
        let operation_count: i64 =
            sqlx::query_scalar("SELECT count(*) FROM agistack_cron_operations WHERE run_id = $1")
                .bind(&fire.run_id)
                .fetch_one(&pool)
                .await
                .unwrap();
        if *status != "success" {
            assert_eq!(run_status, "skipped");
            assert_eq!(reason.as_deref(), Some("automation_previous_run_active"));
            assert!(finished);
            assert_eq!(operation_count, 0);
        } else {
            assert_eq!(run_status, "queued");
            assert_eq!(operation_count, 1);
        }
        assert!(
            repository
                .commit_fire(scope, &candidate, &next, &fire, &authority, observed)
                .await
                .unwrap()
                .is_none(),
            "cursor replay never duplicates history"
        );
    }
    pool.close().await;
    sqlx::query(&format!("DROP SCHEMA {schema} CASCADE"))
        .execute(&admin)
        .await
        .unwrap();
    admin.close().await;
}
