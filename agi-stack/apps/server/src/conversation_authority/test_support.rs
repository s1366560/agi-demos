use agistack_adapters_postgres::PgPool;

const RETIRED_WORKSPACE_TABLES: &[&str] = &[
    "workspaces",
    "workspace_tasks",
    "workspace_members",
    "workspace_task_session_attempts",
    "workspace_plans",
    "workspace_plan_nodes",
];
const SHARED_READER: &str = "conversation-authority-reader";

pub(crate) struct VisibleConversationScope {
    pub(crate) id: String,
    pub(crate) tenant_id: String,
    pub(crate) project_id: String,
    pub(crate) workspace_id: Option<String>,
    pub(crate) linked_workspace_task_id: Option<String>,
    pub(crate) user_id: String,
    pub(crate) current_mode: String,
}

async fn fixture_pool() -> Option<PgPool> {
    let database_url = match crate::startup_config::repository_database_url() {
        Ok(url) => url,
        Err(crate::startup_config::DatabaseUrlConfigError::EnvFileUnavailable { .. }) => {
            eprintln!(
                "[skip] conversation authority Postgres fixture: repository .env unavailable"
            );
            return None;
        }
        Err(error) => panic!("invalid conversation authority fixture configuration: {error}"),
    };
    Some(
        sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .max_lifetime(None)
            .idle_timeout(None)
            .after_connect(|connection, _| {
                Box::pin(async move {
                    // A replacement connection must fail closed instead of reading
                    // public tables when its connection-local fixture is gone.
                    sqlx::query("SET search_path = pg_temp, pg_catalog")
                        .execute(connection)
                        .await?;
                    Ok(())
                })
            })
            .connect(database_url.expose())
            .await
            .expect("connect isolated conversation authority fixture"),
    )
}

async fn assert_retired_workspace_tables_unavailable(pool: &PgPool) {
    // Ordinary Alembic upgrades do not physically delete the legacy public
    // tables. Prove that the tested queries cannot resolve them in this fixture,
    // independently of operator-controlled cleanup of the application database.
    let count: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM unnest($1::text[]) AS retired(name) \
         WHERE to_regclass(name) IS NOT NULL",
    )
    .bind(RETIRED_WORKSPACE_TABLES)
    .fetch_one(pool)
    .await
    .expect("inspect fixture relation visibility");
    assert_eq!(
        count, 0,
        "retired Workspace tables must be unavailable to fixture queries"
    );
}

pub(crate) async fn shared_reader(pool: &PgPool, scope: &VisibleConversationScope) -> String {
    sqlx::query_scalar(
        "SELECT up.user_id FROM user_projects up JOIN user_tenants ut ON ut.user_id = up.user_id \
         WHERE up.project_id = $1 AND ut.tenant_id = $2 AND up.user_id <> $3 \
         ORDER BY up.user_id LIMIT 1",
    )
    .bind(&scope.project_id)
    .bind(&scope.tenant_id)
    .bind(&scope.user_id)
    .fetch_one(pool)
    .await
    .expect("fixture must include a shared project and tenant member")
}

/// Copy only schema into connection-local tables and seed ordinary members.
/// Every business query resolves to TEMP tables; application rows are never
/// copied or mutated, and closing the connection removes the entire fixture.
pub(crate) async fn standalone_fixture() -> Option<(PgPool, VisibleConversationScope)> {
    let pool = fixture_pool().await?;
    for table in [
        "conversations",
        "agent_execution_events",
        "agent_plan_versions",
        "agent_plan_runs",
        "agent_run_authorities",
        "agent_tasks",
        "hitl_requests",
        "artifacts",
        "tool_execution_records",
    ] {
        sqlx::query(&format!(
            "CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING DEFAULTS)"
        ))
        .execute(&pool)
        .await
        .expect("copy migrated platform table schema into fixture");
    }
    for statement in [
        "CREATE TEMP TABLE projects (id text PRIMARY KEY, tenant_id text NOT NULL)",
        "CREATE TEMP TABLE user_projects (user_id text NOT NULL, project_id text NOT NULL)",
        "CREATE TEMP TABLE user_tenants (user_id text NOT NULL, tenant_id text NOT NULL, role text NOT NULL)",
    ] {
        sqlx::query(statement).execute(&pool).await.unwrap();
    }
    let scope = VisibleConversationScope {
        id: "conversation-authority-fixture".into(),
        tenant_id: "conversation-authority-tenant".into(),
        project_id: "conversation-authority-project".into(),
        workspace_id: None,
        linked_workspace_task_id: None,
        user_id: "conversation-authority-owner".into(),
        current_mode: "build".into(),
    };
    sqlx::query("INSERT INTO pg_temp.projects (id, tenant_id) VALUES ($1, $2)")
        .bind(&scope.project_id)
        .bind(&scope.tenant_id)
        .execute(&pool)
        .await
        .unwrap();
    for user_id in [scope.user_id.as_str(), SHARED_READER] {
        sqlx::query("INSERT INTO pg_temp.user_projects (user_id, project_id) VALUES ($1, $2)")
            .bind(user_id)
            .bind(&scope.project_id)
            .execute(&pool)
            .await
            .unwrap();
        sqlx::query(
            "INSERT INTO pg_temp.user_tenants (user_id, tenant_id, role) VALUES ($1, $2, 'member')",
        )
        .bind(user_id)
        .bind(&scope.tenant_id)
        .execute(&pool)
        .await
        .unwrap();
    }
    sqlx::query(
        "INSERT INTO pg_temp.conversations \
         (id, tenant_id, project_id, user_id, title, status, current_mode, merge_strategy, \
          agent_config, meta, message_count, participant_agents, created_at, updated_at) \
         VALUES ($1, $2, $3, $4, 'Isolated authority fixture', 'active', $5, 'result_only', \
                 '{}', '{}', 0, '[]', NOW(), NOW())",
    )
    .bind(&scope.id)
    .bind(&scope.tenant_id)
    .bind(&scope.project_id)
    .bind(&scope.user_id)
    .bind(&scope.current_mode)
    .execute(&pool)
    .await
    .expect("seed isolated standalone conversation");
    assert_retired_workspace_tables_unavailable(&pool).await;
    Some((pool, scope))
}

pub(crate) async fn workspace_fixture() -> Option<(PgPool, VisibleConversationScope)> {
    let (pool, mut scope) = standalone_fixture().await?;
    scope.workspace_id = Some("conversation-core-fixture-workspace".into());
    scope.linked_workspace_task_id = Some("conversation-core-fixture-task".into());
    sqlx::query(
        "UPDATE pg_temp.conversations SET workspace_id = $1, linked_workspace_task_id = $2",
    )
    .bind(&scope.workspace_id)
    .bind(&scope.linked_workspace_task_id)
    .execute(&pool)
    .await
    .expect("set temporary Core linkage");
    Some((pool, scope))
}

#[path = "test_support_tests.rs"]
mod tests;
