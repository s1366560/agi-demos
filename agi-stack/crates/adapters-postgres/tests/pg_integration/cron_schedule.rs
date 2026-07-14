use agistack_adapters_postgres::{
    CronOperationKind, CronOperationRecord, CronOperationStatus, CronScheduleProjection,
    CronScheduleRepositoryError, CronScheduleStatus, PgCronScheduleRepository,
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

async fn clean_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM agistack_cron_schedule_state WHERE job_id = 'cron_schedule_job'")
        .execute(pool)
        .await
        .expect("clean schedule state");
    sqlx::query("DELETE FROM cron_jobs WHERE id = 'cron_schedule_job'")
        .execute(pool)
        .await
        .expect("clean schedule job");
}
