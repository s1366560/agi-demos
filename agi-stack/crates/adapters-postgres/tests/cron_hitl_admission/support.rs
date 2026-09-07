use std::sync::atomic::{AtomicU64, Ordering};

use agistack_adapters_postgres::{AutomationHitlAdmissionCommand, PgPool};
use agistack_core::agent::{HitlKind, HitlRequest, SessionState, SessionStatus};
use chrono::{DateTime, Duration, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;

static SEQUENCE: AtomicU64 = AtomicU64::new(0);

pub struct Fixture {
    admin: PgPool,
    pub pool: PgPool,
    schema: String,
    url: String,
}

impl Fixture {
    pub async fn open() -> Option<Self> {
        let Ok(url) = std::env::var("DATABASE_URL") else {
            eprintln!("[skip] cron HITL admission: DATABASE_URL unset");
            return None;
        };
        let admin = PgPoolOptions::new()
            .max_connections(1)
            .connect(&url)
            .await
            .unwrap();
        let schema = format!(
            "qa_cron_hitl_{}_{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        );
        sqlx::query(&format!("CREATE SCHEMA {schema}"))
            .execute(&admin)
            .await
            .unwrap();
        let pool = scoped_pool(&url, &schema).await;
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
            "CREATE TABLE hitl_requests (
                id text PRIMARY KEY, request_type text NOT NULL, tenant_id text NOT NULL,
                project_id text NOT NULL, message_id text, conversation_id text NOT NULL,
                status text NOT NULL, request_metadata json, response_metadata json,
                expires_at timestamptz NOT NULL, answered_at timestamptz)",
            "CREATE TABLE agistack_checkpoints (
                session_id text PRIMARY KEY, state jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now())",
        ] {
            sqlx::query(ddl).execute(&pool).await.unwrap();
        }
        Some(Self {
            admin,
            pool,
            schema,
            url,
        })
    }

    pub async fn independent_pool(&self) -> PgPool {
        scoped_pool(&self.url, &self.schema).await
    }

    pub fn command(&self) -> AutomationHitlAdmissionCommand {
        AutomationHitlAdmissionCommand {
            tenant_id: "tenant".into(),
            project_id: "project".into(),
            job_id: "job".into(),
            run_id: "run".into(),
            conversation_id: "conversation".into(),
            request_id: "request".into(),
            expected_runtime_revision: 7,
        }
    }

    pub async fn seed(&self) {
        sqlx::query("INSERT INTO cron_jobs VALUES ('job', 'tenant', 'project', 'actor', 'agent_turn', '{\"message\":\"test\"}', 300)")
            .execute(&self.pool).await.unwrap();
        sqlx::query("INSERT INTO cron_job_runs (id, job_id, project_id, runtime_execution_id, status, runtime_revision,
            deadline_at, conversation_id, accepted_at, runtime_lease_owner, runtime_lease_token, runtime_lease_expires_at)
            VALUES ('run', 'job', 'project', 'run', 'waiting_human', 7, $1, 'conversation', $2, 'old', 'old-token', $2)")
            .bind(now() + Duration::minutes(5)).bind(now()).execute(&self.pool).await.unwrap();
        sqlx::query("INSERT INTO agistack_cron_operations VALUES ('operation', 'run', 'execute_run', 'waiting_runtime',
            'tenant', 'project', 'job', 'actor', NULL, '{}')")
            .execute(&self.pool).await.unwrap();
        sqlx::query("INSERT INTO hitl_requests VALUES ('request', 'clarification', 'tenant', 'project', 'run', 'conversation',
            'answered', $1, $2, $3, $4)")
            .bind(json!({"automation_run_id":"run", "runtime_execution_id":"run", "checkpoint_session_id":"run"}))
            .bind(json!({"resume_answer":"confirmed", "resume_answer_encoding":"utf-8"}))
            .bind(now() + Duration::minutes(5)).bind(now()).execute(&self.pool).await.unwrap();
        let mut state = SessionState::new("run", "test", Some("project"));
        state.status = SessionStatus::AwaitingInput;
        state.pending_hitl = Some(HitlRequest::new(
            "request",
            HitlKind::Clarification,
            "Confirm?",
        ));
        let mut value = serde_json::to_value(state).unwrap();
        value["future_field"] = json!({"preserved": true});
        sqlx::query("INSERT INTO agistack_checkpoints (session_id, state) VALUES ('run', $1)")
            .bind(value)
            .execute(&self.pool)
            .await
            .unwrap();
    }

    pub async fn checkpoint(&self) -> Value {
        sqlx::query_scalar("SELECT state FROM agistack_checkpoints WHERE session_id = 'run'")
            .fetch_one(&self.pool)
            .await
            .unwrap()
    }

    pub async fn assert_resumed(&self) {
        let row: (String, i64, Option<String>, Option<String>) = sqlx::query_as(
            "SELECT status, runtime_revision, runtime_lease_owner, runtime_lease_token FROM cron_job_runs WHERE id = 'run'"
        ).fetch_one(&self.pool).await.unwrap();
        assert_eq!(row, ("queued".into(), 8, None, None));
        let value = self.checkpoint().await;
        assert_eq!(value["future_field"], json!({"preserved": true}));
        let state: SessionState = serde_json::from_value(value).unwrap();
        assert_eq!(state.status, SessionStatus::Running);
        assert_eq!(state.hitl_answer("request"), Some("confirmed"));
        assert_eq!(state.pending_hitl.unwrap().id, "request");
    }

    pub async fn close(self) {
        self.pool.close().await;
        sqlx::query(&format!("DROP SCHEMA {} CASCADE", self.schema))
            .execute(&self.admin)
            .await
            .unwrap();
        self.admin.close().await;
    }
}

async fn scoped_pool(url: &str, schema: &str) -> PgPool {
    let search_path = format!("SET search_path TO {schema}");
    PgPoolOptions::new()
        .max_connections(4)
        .after_connect(move |connection, _| {
            let query = search_path.clone();
            Box::pin(async move {
                sqlx::query(&query).execute(connection).await?;
                Ok(())
            })
        })
        .connect(url)
        .await
        .unwrap()
}

pub fn now() -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2099, 9, 7, 0, 0, 0).unwrap()
}
