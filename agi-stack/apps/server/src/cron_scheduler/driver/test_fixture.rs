use agistack_adapters_postgres::PgPool;
use sqlx::postgres::PgPoolOptions;

pub(super) struct Fixture {
    admin: PgPool,
    pub(super) pool: PgPool,
    schema: String,
}

impl Fixture {
    pub(super) async fn open() -> Option<Self> {
        let Ok(url) = std::env::var("DATABASE_URL") else {
            eprintln!("[skip] cron driver resume: DATABASE_URL unset");
            return None;
        };
        let admin = PgPoolOptions::new()
            .max_connections(1)
            .connect(&url)
            .await
            .unwrap();
        let schema = format!("qa_cron_driver_{}", uuid::Uuid::new_v4().simple());
        sqlx::query(&format!("CREATE SCHEMA {schema}"))
            .execute(&admin)
            .await
            .unwrap();
        let search_path = format!("SET search_path TO {schema}");
        let pool = PgPoolOptions::new()
            .max_connections(5)
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
        // Private compatibility tables exercise real production SQL without modifying app data.
        for ddl in [
            "CREATE TABLE cron_jobs (id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL,
              created_by text, payload_type text NOT NULL, payload_config json NOT NULL, timeout_seconds integer NOT NULL,
              state json NOT NULL DEFAULT '{}', max_retries integer NOT NULL DEFAULT 0,
              delete_after_run boolean NOT NULL DEFAULT false, schedule_type text NOT NULL DEFAULT 'every',
              enabled boolean NOT NULL DEFAULT true, updated_at timestamptz NOT NULL DEFAULT now())",
            "CREATE TABLE cron_job_runs (id text PRIMARY KEY, job_id text NOT NULL REFERENCES cron_jobs(id),
              project_id text NOT NULL, runtime_execution_id text, status text NOT NULL,
              runtime_revision bigint NOT NULL DEFAULT 0, deadline_at timestamptz, conversation_id text,
              accepted_at timestamptz NOT NULL DEFAULT now(), runtime_lease_owner text, runtime_lease_token text,
              runtime_lease_expires_at timestamptz, last_heartbeat_at timestamptz, started_at timestamptz,
              finished_at timestamptz, duration_ms integer, error_message text, result_summary json)",
            "CREATE TABLE agistack_cron_operations (id text PRIMARY KEY, run_id text NOT NULL REFERENCES cron_job_runs(id),
              operation_kind text NOT NULL, status text NOT NULL, tenant_id text NOT NULL, project_id text NOT NULL,
              job_id text NOT NULL, actor_user_id text, actor_api_key_id text, input_json jsonb NOT NULL DEFAULT '{}',
              result_json jsonb NOT NULL DEFAULT '{}', next_attempt_at timestamptz, last_error_code text,
              last_error_redacted text, completed_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now())",
            "CREATE TABLE hitl_requests (id text PRIMARY KEY, request_type text NOT NULL, tenant_id text NOT NULL,
              project_id text NOT NULL, user_id text, question text NOT NULL, options json, context json,
              message_id text, conversation_id text NOT NULL, status text NOT NULL, response text,
              request_metadata json, response_metadata json, expires_at timestamptz NOT NULL, answered_at timestamptz)",
            "CREATE TABLE agistack_checkpoints (session_id text PRIMARY KEY, state jsonb NOT NULL,
              updated_at timestamptz NOT NULL DEFAULT now())",
        ] { sqlx::query(ddl).execute(&pool).await.unwrap(); }
        Some(Self {
            admin,
            pool,
            schema,
        })
    }

    pub(super) async fn seed(&self, id: &str) {
        sqlx::query("INSERT INTO cron_jobs (id,tenant_id,project_id,created_by,payload_type,payload_config,timeout_seconds)
          VALUES ($1,'tenant','project','actor','agent_turn','{\"message\":\"ask and finish\"}',300)")
            .bind(id).execute(&self.pool).await.unwrap();
        sqlx::query("INSERT INTO cron_job_runs (id,job_id,project_id,runtime_execution_id,status,conversation_id)
          VALUES ($1,$1,'project',$1,'queued',$1)").bind(id).execute(&self.pool).await.unwrap();
        sqlx::query("INSERT INTO agistack_cron_operations (id,run_id,operation_kind,status,tenant_id,project_id,job_id,actor_user_id)
          VALUES ($1,$1,'execute_run','waiting_runtime','tenant','project',$1,'actor')")
            .bind(id).execute(&self.pool).await.unwrap();
    }

    pub(super) async fn close(self) {
        self.pool.close().await;
        sqlx::query(&format!("DROP SCHEMA {} CASCADE", self.schema))
            .execute(&self.admin)
            .await
            .unwrap();
        self.admin.close().await;
    }
}
