use agistack_adapters_postgres::{
    CronControlScope, PgCronControlRepository, PgCronSchedulerOwnerRepository,
};

use super::support::*;

#[tokio::test]
async fn cron_control_discovers_scope_and_admits_each_schedule_revision_once() {
    let Some(pool) =
        pool_or_skip("cron_control_discovers_scope_and_admits_each_schedule_revision_once").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_control_tables(&pool).await;
    clean_rows(&pool).await;
    let Some((project_id, tenant_id, user_id)) = sqlx::query_as::<_, (String, String, String)>(
        "SELECT project.id, project.tenant_id, project.owner_id \
         FROM projects AS project \
         WHERE NOT EXISTS (SELECT 1 FROM cron_jobs AS job WHERE job.project_id = project.id) \
         ORDER BY project.tenant_id, project.id LIMIT 1",
    )
    .fetch_optional(&pool)
    .await
    .expect("load isolated cron control scope") else {
        return;
    };
    let scope = CronControlScope {
        tenant_id: tenant_id.clone(),
        project_id: project_id.clone(),
    };
    let now = ts(2026, 7, 14, 17, 0, 0);
    insert_job(&pool, &scope, &user_id, now).await;
    let stale_authority = acquire_authority(&pool, now).await;
    let repo = PgCronControlRepository::new(pool.clone());

    let scopes = repo
        .list_work_scopes(&stale_authority, None, 1_000, now)
        .await
        .expect("discover cron work scopes");
    assert!(scopes.contains(&scope));
    let after = repo
        .list_work_scopes(&stale_authority, Some(&scope), 1_000, now)
        .await
        .expect("advance cron work scope cursor");
    assert!(!after.contains(&scope));

    let first = repo
        .admit_reconcile_operations(&stale_authority, &scope, 10, now)
        .await
        .expect("admit first schedule revision");
    assert_eq!(first.len(), 1);
    assert_eq!(first[0].job_id, "cron_control_job");
    assert_eq!(first[0].schedule_revision, 2);
    assert!(repo
        .admit_reconcile_operations(&stale_authority, &scope, 10, now)
        .await
        .expect("replay first schedule revision")
        .is_empty());

    sqlx::query(
        "UPDATE cron_jobs SET schedule_config = '{\"interval_seconds\":120}'::json \
         WHERE id = 'cron_control_job'",
    )
    .execute(&pool)
    .await
    .expect("advance cron schedule revision through trigger");
    let authority = PgCronSchedulerOwnerRepository::new(pool.clone())
        .renew(&stale_authority, 300, now)
        .await
        .expect("renew cron control authority")
        .expect("current authority renews");
    assert!(repo
        .admit_reconcile_operations(&stale_authority, &scope, 10, now)
        .await
        .expect("stale authority is fenced")
        .is_empty());
    let second = repo
        .admit_reconcile_operations(&authority, &scope, 10, now)
        .await
        .expect("admit next schedule revision");
    assert_eq!(second.len(), 1);
    assert_eq!(second[0].schedule_revision, 3);

    let revisions = sqlx::query_scalar::<_, i64>(
        "SELECT schedule_revision FROM agistack_cron_operations \
         WHERE job_id = 'cron_control_job' ORDER BY schedule_revision",
    )
    .fetch_all(&pool)
    .await
    .expect("load admitted schedule revisions");
    assert_eq!(revisions, vec![2, 3]);
    clean_rows(&pool).await;
}

async fn insert_job(pool: &PgPool, scope: &CronControlScope, user_id: &str, now: DateTime<Utc>) {
    sqlx::query(
        "INSERT INTO cron_jobs ( \
            id, project_id, tenant_id, name, enabled, delete_after_run, revision, \
            schedule_revision, schedule_type, schedule_config, payload_type, payload_config, \
            delivery_type, delivery_config, conversation_mode, timezone, stagger_seconds, \
            timeout_seconds, max_retries, state, created_by, created_at \
         ) VALUES ( \
            'cron_control_job', $1, $2, 'Control admission', true, false, 4, 2, 'every', \
            '{\"interval_seconds\":60}'::json, 'agent_turn', '{\"message\":\"run\"}'::json, \
            'none', '{}'::json, 'fresh', 'UTC', 0, 300, 3, '{}'::json, $3, $4)",
    )
    .bind(&scope.project_id)
    .bind(&scope.tenant_id)
    .bind(user_id)
    .bind(now)
    .execute(pool)
    .await
    .expect("insert cron control job");
}

async fn acquire_authority(
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
    .expect("delegate cron control ownership to Rust");
    PgCronSchedulerOwnerRepository::new(pool.clone())
        .try_acquire_global("cron-control-test", 60, now)
        .await
        .expect("acquire cron control authority")
        .expect("Rust cutover grants cron control authority")
}

async fn ensure_control_tables(pool: &PgPool) {
    for ddl in [
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
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agistack_cron_operations_reconcile \
            ON agistack_cron_operations (job_id, operation_kind, schedule_revision) \
            WHERE operation_kind = 'reconcile_schedule'",
        "CREATE TABLE IF NOT EXISTS agistack_cron_scheduler_owners ( \
            scope_id varchar(100) PRIMARY KEY, owner_kind varchar(20) NOT NULL DEFAULT 'off', \
            owner_id varchar(255), owner_epoch bigint NOT NULL DEFAULT 0, \
            lease_token varchar(255), lease_expires_at timestamptz, acquired_at timestamptz, \
            updated_at timestamptz NOT NULL DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS agistack_cron_schedule_state ( \
            job_id text PRIMARY KEY REFERENCES cron_jobs(id) ON DELETE CASCADE, \
            tenant_id text NOT NULL, project_id text NOT NULL, schedule_revision bigint NOT NULL, \
            status varchar(32) NOT NULL DEFAULT 'active', schedule_fingerprint varchar(128) NOT NULL, \
            next_fire_at timestamptz, last_fire_at timestamptz, last_error_code varchar(100), \
            updated_at timestamptz NOT NULL DEFAULT now())",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|error| panic!("cron control ddl failed: {ddl}\n{error}"));
    }
}

async fn clean_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM agistack_cron_schedule_state WHERE job_id = 'cron_control_job'")
        .execute(pool)
        .await
        .expect("clean cron control state");
    sqlx::query("DELETE FROM agistack_cron_operations WHERE job_id = 'cron_control_job'")
        .execute(pool)
        .await
        .expect("clean cron control operations");
    sqlx::query("DELETE FROM cron_job_runs WHERE job_id = 'cron_control_job'")
        .execute(pool)
        .await
        .expect("clean cron control runs");
    sqlx::query("DELETE FROM cron_jobs WHERE id = 'cron_control_job'")
        .execute(pool)
        .await
        .expect("clean cron control job");
    sqlx::query("DELETE FROM agistack_cron_scheduler_owners WHERE scope_id = 'global'")
        .execute(pool)
        .await
        .expect("clean cron control owner");
}
