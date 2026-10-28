use sqlx::{postgres::PgPoolOptions, PgPool};

pub(super) struct Fixture {
    admin: PgPool,
    pub pool: PgPool,
    schema: String,
}

impl Fixture {
    pub async fn open() -> Option<Self> {
        let Ok(url) = std::env::var("AGISTACK_HITL_TEST_DATABASE_URL") else {
            eprintln!("[skip] cloud HITL identity: AGISTACK_HITL_TEST_DATABASE_URL unset");
            return None;
        };
        let admin = PgPoolOptions::new()
            .max_connections(1)
            .connect(&url)
            .await
            .unwrap();
        let schema = format!("qa_cloud_hitl_{}", uuid::Uuid::new_v4().simple());
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
        // Private compatibility tables exercise production SQL without touching app data.
        for ddl in [
            "CREATE TABLE hitl_requests (id text PRIMARY KEY, request_type text NOT NULL,
             tenant_id text NOT NULL, project_id text NOT NULL, user_id text,
             question text NOT NULL, options json, context json, message_id text,
             conversation_id text NOT NULL, status text NOT NULL, response text,
             request_metadata json, response_metadata json, expires_at timestamptz,
             created_at timestamptz NOT NULL DEFAULT now(), answered_at timestamptz)",
            "CREATE TABLE agistack_checkpoints (session_id text PRIMARY KEY, state jsonb NOT NULL,
             updated_at timestamptz NOT NULL DEFAULT now())",
            "CREATE TABLE user_tenants (user_id text NOT NULL, tenant_id text NOT NULL)",
            "CREATE TABLE user_projects (user_id text NOT NULL, project_id text NOT NULL)",
            "INSERT INTO user_tenants VALUES ('actor', 'tenant')",
            "INSERT INTO user_projects VALUES ('actor', 'project')",
        ] {
            sqlx::query(ddl).execute(&pool).await.unwrap();
        }
        Some(Self {
            admin,
            pool,
            schema,
        })
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
