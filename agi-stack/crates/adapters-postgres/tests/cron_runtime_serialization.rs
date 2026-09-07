//! Live PostgreSQL concurrency checks in a private schema, never in application tables.

use std::sync::atomic::{AtomicU64, Ordering};

use agistack_adapters_postgres::{
    AutomationRuntimeScope, PgCronAutomationRuntimeRepository, PgPool,
};
use chrono::{Duration, TimeZone, Utc};
use sqlx::postgres::PgPoolOptions;

static SCHEMA_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    admin: PgPool,
    pool: PgPool,
    schema: String,
}

impl Fixture {
    async fn open() -> Option<Self> {
        let Ok(url) = std::env::var("DATABASE_URL") else {
            eprintln!("[skip] cron runtime serialization: DATABASE_URL unset");
            return None;
        };
        let admin = PgPoolOptions::new()
            .max_connections(1)
            .connect(&url)
            .await
            .unwrap();
        let schema = format!(
            "qa_cron_serial_{}_{}",
            std::process::id(),
            SCHEMA_SEQUENCE.fetch_add(1, Ordering::Relaxed),
        );
        sqlx::query(&format!("CREATE SCHEMA {schema}"))
            .execute(&admin)
            .await
            .unwrap();
        let search_path = format!("SET search_path TO {schema}");
        let pool = PgPoolOptions::new()
            .max_connections(4)
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
        // These are the production claim's exact SQL column types. No scheduler
        // ownership row or application identity is modified by the fixture.
        for ddl in [
            "CREATE TABLE cron_jobs (
                id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL,
                created_by text, payload_type text NOT NULL, payload_config json NOT NULL,
                timeout_seconds integer NOT NULL)",
            "CREATE TABLE cron_job_runs (
                id text PRIMARY KEY, job_id text NOT NULL REFERENCES cron_jobs(id),
                project_id text NOT NULL, runtime_execution_id text, status text NOT NULL,
                runtime_revision bigint NOT NULL DEFAULT 0, deadline_at timestamptz,
                conversation_id text, accepted_at timestamptz NOT NULL,
                runtime_lease_owner text, runtime_lease_token text,
                runtime_lease_expires_at timestamptz, last_heartbeat_at timestamptz,
                started_at timestamptz)",
            "CREATE TABLE agistack_cron_operations (
                id text PRIMARY KEY, run_id text NOT NULL REFERENCES cron_job_runs(id),
                operation_kind text NOT NULL, status text NOT NULL,
                tenant_id text NOT NULL, project_id text NOT NULL, job_id text NOT NULL,
                actor_user_id text, actor_api_key_id text, input_json jsonb NOT NULL)",
        ] {
            sqlx::query(ddl).execute(&pool).await.unwrap();
        }
        Some(Self {
            admin,
            pool,
            schema,
        })
    }

    async fn seed(&self, job: &str, runs: &[&str]) {
        sqlx::query(
            "INSERT INTO cron_jobs VALUES (
            $1, 'tenant', 'project', 'actor', 'agent_turn', '{\"message\":\"test\"}', 300)",
        )
        .bind(job)
        .execute(&self.pool)
        .await
        .unwrap();
        for run in runs {
            sqlx::query(
                "INSERT INTO cron_job_runs (
                id, job_id, project_id, runtime_execution_id, status, conversation_id, accepted_at)
                VALUES ($1, $2, 'project', $1, 'queued', 'conversation', $3)",
            )
            .bind(run)
            .bind(job)
            .bind(now())
            .execute(&self.pool)
            .await
            .unwrap();
            sqlx::query(
                "INSERT INTO agistack_cron_operations VALUES (
                $1, $1, 'execute_run', 'waiting_runtime', 'tenant', 'project', $2,
                'actor', NULL, '{}')",
            )
            .bind(run)
            .bind(job)
            .execute(&self.pool)
            .await
            .unwrap();
        }
    }

    async fn close(self) {
        self.pool.close().await;
        sqlx::query(&format!("DROP SCHEMA {} CASCADE", self.schema))
            .execute(&self.admin)
            .await
            .unwrap();
        self.admin.close().await;
    }
}

fn scope() -> AutomationRuntimeScope {
    AutomationRuntimeScope {
        tenant_id: "tenant".into(),
        project_id: "project".into(),
    }
}

fn now() -> chrono::DateTime<Utc> {
    Utc.with_ymd_and_hms(2099, 9, 7, 0, 0, 0).unwrap()
}

#[tokio::test]
async fn one_batch_serializes_each_job_and_keeps_unrelated_jobs_eligible() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed("job-a", &["run-a", "run-b"]).await;
    fixture.seed("job-b", &["run-c"]).await;
    let repository = PgCronAutomationRuntimeRepository::new(fixture.pool.clone());
    let leases = repository
        .claim_due(&scope(), 10, "worker", 30, now())
        .await
        .unwrap();
    assert_eq!(leases.len(), 2, "only one run per job may be active");
    assert_ne!(leases[0].context.job_id, leases[1].context.job_id);
    assert!(repository
        .claim_due(&scope(), 10, "other", 30, now())
        .await
        .unwrap()
        .is_empty());
    fixture.close().await;
}

#[tokio::test]
async fn concurrent_workers_cannot_claim_different_runs_of_one_job() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed("job", &["run-a", "run-b"]).await;
    let repository = PgCronAutomationRuntimeRepository::new(fixture.pool.clone());
    let runtime_scope = scope();
    let (left, right) = tokio::join!(
        repository.claim_due(&runtime_scope, 1, "left", 30, now()),
        repository.claim_due(&runtime_scope, 1, "right", 30, now()),
    );
    let leases = left
        .unwrap()
        .into_iter()
        .chain(right.unwrap())
        .collect::<Vec<_>>();
    assert_eq!(leases.len(), 1);
    let first = &leases[0];
    let recovery = repository
        .claim_due(
            &runtime_scope,
            10,
            "recovery",
            30,
            now() + Duration::seconds(31),
        )
        .await
        .unwrap();
    assert_eq!(
        recovery.len(),
        1,
        "recover the prior run before admitting the queued one"
    );
    assert_eq!(recovery[0].context.run_id, first.context.run_id);
    assert!(recovery[0].runtime_revision > first.runtime_revision);
    assert!(!repository
        .renew(first, 30, now() + Duration::seconds(32))
        .await
        .unwrap());

    sqlx::query("UPDATE cron_job_runs SET status = 'waiting_human' WHERE id = $1")
        .bind(&first.context.run_id)
        .execute(&fixture.pool)
        .await
        .unwrap();
    assert!(repository
        .claim_due(&runtime_scope, 10, "waiting", 30, now())
        .await
        .unwrap()
        .is_empty());
    sqlx::query("UPDATE cron_job_runs SET status = 'success' WHERE id = $1")
        .bind(&first.context.run_id)
        .execute(&fixture.pool)
        .await
        .unwrap();
    let next = repository
        .claim_due(&runtime_scope, 10, "next", 30, now())
        .await
        .unwrap();
    assert_eq!(next.len(), 1);
    assert_ne!(next[0].context.run_id, first.context.run_id);
    fixture.close().await;
}
