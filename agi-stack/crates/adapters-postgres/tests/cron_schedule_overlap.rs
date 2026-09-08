//! Scheduled overlap admission against real PostgreSQL in a private schema.

use agistack_adapters_postgres::{
    CronControlScope, CronOperationScope, CronScheduleProjection, CronScheduleStatus,
    NewCronScheduledFire, PgCronControlRepository, PgCronOperationRepository,
    PgCronScheduleFireRepository, PgCronSchedulerOwnerRepository,
};
use chrono::{Duration, TimeZone, Utc};
use sqlx::postgres::PgPoolOptions;

#[path = "support/cron_cutover_fixture.rs"]
mod cron_cutover_fixture;

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
    cron_cutover_fixture::verify_cutover_fixture(&pool).await;
    let ownership = PgCronSchedulerOwnerRepository::new(pool.clone());
    let authority = ownership
        .try_acquire_global("scheduler", 60, now)
        .await
        .unwrap()
        .unwrap();
    let renewed = ownership
        .renew(&authority, 600, now + Duration::seconds(30))
        .await
        .unwrap()
        .unwrap();
    assert!(ownership
        .is_current(&authority, now + Duration::seconds(61))
        .await
        .unwrap());
    assert!(ownership
        .renew(&authority, 600, now + Duration::seconds(31))
        .await
        .unwrap()
        .is_none());
    assert!(!ownership
        .release(&authority, now + Duration::seconds(31))
        .await
        .unwrap());
    let invalid_authorities = [
        agistack_adapters_postgres::CronSchedulerLease {
            lease_expires_at: renewed.lease_expires_at + Duration::seconds(1),
            ..authority.clone()
        },
        agistack_adapters_postgres::CronSchedulerLease {
            owner_epoch: authority.owner_epoch + 1,
            ..authority.clone()
        },
        agistack_adapters_postgres::CronSchedulerLease {
            lease_token: "different-nonce".into(),
            ..authority.clone()
        },
    ];
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
        for invalid in &invalid_authorities {
            assert!(!ownership.is_current(invalid, observed).await.unwrap());
            assert!(repository
                .commit_fire(scope, &candidate, &next, &fire, invalid, observed)
                .await
                .unwrap()
                .is_none());
        }
        sqlx::query("UPDATE agistack_cron_scheduler_owners SET cutover_phase='blocked'")
            .execute(&pool)
            .await
            .unwrap();
        assert!(
            repository
                .commit_fire(scope, &candidate, &next, &fire, &authority, observed)
                .await
                .unwrap()
                .is_none(),
            "revoked cutover cannot advance the schedule cursor"
        );
        sqlx::query("UPDATE agistack_cron_scheduler_owners SET cutover_phase='verified'")
            .execute(&pool)
            .await
            .unwrap();
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
    let control = PgCronControlRepository::new(pool.clone());
    let operations = PgCronOperationRepository::new(pool.clone());
    let control_scope = CronControlScope {
        tenant_id: "tenant".into(),
        project_id: "project".into(),
    };
    let observed = now + Duration::seconds(240);
    sqlx::query("UPDATE cron_jobs SET schedule_revision=2 WHERE id='job'")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("UPDATE agistack_cron_scheduler_owners SET cutover_phase='blocked'")
        .execute(&pool)
        .await
        .unwrap();
    assert!(control
        .list_work_scopes(&authority, None, 10, now)
        .await
        .unwrap()
        .is_empty());
    assert!(control
        .admit_reconcile_operations(&authority, &control_scope, 10, now)
        .await
        .unwrap()
        .is_empty());
    assert!(operations
        .claim_due(scope, &authority, 10, "worker", 60, observed)
        .await
        .unwrap()
        .is_empty());
    sqlx::query("UPDATE agistack_cron_scheduler_owners SET cutover_phase='verified'")
        .execute(&pool)
        .await
        .unwrap();
    for invalid in &invalid_authorities {
        assert!(control
            .list_work_scopes(invalid, None, 10, observed)
            .await
            .unwrap()
            .is_empty());
        assert!(control
            .admit_reconcile_operations(invalid, &control_scope, 10, observed)
            .await
            .unwrap()
            .is_empty());
        assert!(operations
            .claim_due(scope, invalid, 10, "worker", 60, observed)
            .await
            .unwrap()
            .is_empty());
    }
    assert_eq!(
        control
            .list_work_scopes(&authority, None, 10, observed)
            .await
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        control
            .admit_reconcile_operations(&authority, &control_scope, 10, observed)
            .await
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        operations
            .claim_due(scope, &authority, 10, "worker", 60, observed)
            .await
            .unwrap()
            .len(),
        2
    );
    // A stale application observation cannot revive an owner expired by the DB clock.
    let database_now: chrono::DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&pool)
        .await
        .unwrap();
    let stale_observed = database_now - Duration::seconds(11);
    let expired_snapshot = agistack_adapters_postgres::CronSchedulerLease {
        acquired_at: database_now - Duration::seconds(20),
        lease_expires_at: database_now - Duration::seconds(10),
        ..authority.clone()
    };
    sqlx::query("UPDATE agistack_cron_scheduler_owners SET lease_expires_at=clock_timestamp()-interval '1 second'")
        .execute(&pool).await.unwrap();
    sqlx::query("UPDATE cron_jobs SET schedule_revision=3 WHERE id='job'")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("UPDATE agistack_cron_operations SET status='pending',next_attempt_at=$1")
        .bind(stale_observed)
        .execute(&pool)
        .await
        .unwrap();
    assert!(!ownership
        .is_current(&expired_snapshot, stale_observed)
        .await
        .unwrap());
    assert!(control
        .list_work_scopes(&expired_snapshot, None, 10, stale_observed)
        .await
        .unwrap()
        .is_empty());
    assert!(control
        .admit_reconcile_operations(&expired_snapshot, &control_scope, 10, stale_observed)
        .await
        .unwrap()
        .is_empty());
    assert!(operations
        .claim_due(scope, &expired_snapshot, 10, "worker", 60, stale_observed)
        .await
        .unwrap()
        .is_empty());
    sqlx::query("UPDATE agistack_cron_schedule_state SET schedule_revision=3,next_fire_at=$1 WHERE job_id='job'")
        .bind(stale_observed).execute(&pool).await.unwrap();
    let candidate = repository
        .list_due(scope, stale_observed, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();
    let next = CronScheduleProjection {
        status: CronScheduleStatus::Active,
        schedule_fingerprint: candidate.schedule_fingerprint.clone(),
        next_fire_at: Some(stale_observed + Duration::seconds(60)),
    };
    let fire = NewCronScheduledFire {
        run_id: "expired-owner-run".into(),
        operation_id: "expired-owner-op".into(),
        idempotency_key: "expired-owner".into(),
    };
    assert!(repository
        .commit_fire(
            scope,
            &candidate,
            &next,
            &fire,
            &expired_snapshot,
            stale_observed
        )
        .await
        .unwrap()
        .is_none());
    pool.close().await;
    sqlx::query(&format!("DROP SCHEMA {schema} CASCADE"))
        .execute(&admin)
        .await
        .unwrap();
    admin.close().await;
}
