use agistack_adapters_postgres::{connect, PgPool};
use sqlx::FromRow;

#[derive(FromRow)]
pub(crate) struct VisibleConversationScope {
    pub(crate) id: String,
    pub(crate) tenant_id: String,
    pub(crate) project_id: String,
    pub(crate) workspace_id: Option<String>,
    pub(crate) linked_workspace_task_id: Option<String>,
    pub(crate) user_id: String,
    pub(crate) current_mode: String,
}

pub(crate) async fn repository_pool() -> Option<PgPool> {
    let Ok(database_url) = crate::startup_config::repository_database_url() else {
        eprintln!(
            "[skip] conversation authority Postgres checks: repository DATABASE_URL unavailable"
        );
        return None;
    };
    Some(
        connect(database_url.expose())
            .await
            .expect("repository database must connect"),
    )
}

pub(crate) async fn visible_scope(
    pool: &PgPool,
    workspace: bool,
) -> Option<VisibleConversationScope> {
    let result = sqlx::query_as::<_, VisibleConversationScope>(
        "SELECT c.id, c.tenant_id, c.project_id, c.workspace_id, \
                c.linked_workspace_task_id, c.user_id, c.current_mode \
         FROM conversations AS c \
         WHERE EXISTS (SELECT 1 FROM projects AS p \
                       WHERE p.id = c.project_id AND p.tenant_id = c.tenant_id) \
           AND EXISTS (SELECT 1 FROM user_projects AS up \
                       WHERE up.project_id = c.project_id AND up.user_id = c.user_id) \
           AND EXISTS (SELECT 1 FROM user_tenants AS ut \
                       WHERE ut.tenant_id = c.tenant_id AND ut.user_id = c.user_id) \
           AND (c.workspace_id IS NOT NULL) = $1 \
         ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC LIMIT 1",
    )
    .bind(workspace)
    .fetch_optional(pool)
    .await
    .expect("platform-only conversation lookup must succeed after Workspace retirement");
    if result.is_none() {
        eprintln!(
            "[skip] conversation authority fixture: no visible workspace={workspace} conversation"
        );
    }
    result
}

pub(crate) async fn assert_retired_workspace_tables_absent(pool: &PgPool) {
    let count: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM information_schema.tables \
         WHERE table_schema = 'public' AND table_name IN \
         ('workspaces', 'workspace_tasks', 'workspace_members', \
          'workspace_task_session_attempts', 'workspace_plans', 'workspace_plan_nodes')",
    )
    .fetch_one(pool)
    .await
    .expect("inspect retirement schema");
    assert_eq!(
        count, 0,
        "retired Workspace tables must not be restored for these tests"
    );
}

pub(crate) async fn shared_reader(
    pool: &PgPool,
    scope: &VisibleConversationScope,
) -> Option<String> {
    sqlx::query_scalar(
        "SELECT up.user_id FROM user_projects up JOIN user_tenants ut ON ut.user_id = up.user_id \
         WHERE up.project_id = $1 AND ut.tenant_id = $2 AND up.user_id <> $3 \
         ORDER BY up.user_id LIMIT 1",
    )
    .bind(&scope.project_id)
    .bind(&scope.tenant_id)
    .bind(&scope.user_id)
    .fetch_optional(pool)
    .await
    .expect("platform shared reader lookup")
}

/// One-connection temporary tables exercise the real Postgres projection without
/// writing application rows or reviving any retired Workspace table.
pub(crate) async fn workspace_fixture() -> Option<(PgPool, VisibleConversationScope)> {
    let Ok(database_url) = crate::startup_config::repository_database_url() else {
        eprintln!("[skip] workspace projection fixture: repository DATABASE_URL unavailable");
        return None;
    };
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .connect(database_url.expose())
        .await
        .expect("connect isolated temporary fixture");
    assert_retired_workspace_tables_absent(&pool).await;
    let mut scope = visible_scope(&pool, false).await?;
    sqlx::query(
        "CREATE TEMP TABLE conversations AS SELECT * FROM public.conversations WHERE id = $1",
    )
    .bind(&scope.id)
    .execute(&pool)
    .await
    .expect("copy one conversation into connection-local fixture");
    sqlx::query(
        "UPDATE pg_temp.conversations SET workspace_id = $1, linked_workspace_task_id = $2",
    )
    .bind("conversation-core-fixture-workspace")
    .bind("conversation-core-fixture-task")
    .execute(&pool)
    .await
    .expect("set temporary Core linkage");
    sqlx::query("CREATE TEMP TABLE user_projects AS SELECT user_id, project_id FROM public.user_projects WHERE project_id = $1")
        .bind(&scope.project_id).execute(&pool).await.expect("copy platform project membership facts");
    sqlx::query("CREATE TEMP TABLE user_tenants AS SELECT user_id, tenant_id, role FROM public.user_tenants WHERE tenant_id = $1")
        .bind(&scope.tenant_id).execute(&pool).await.expect("copy platform tenant membership facts");
    sqlx::query("INSERT INTO pg_temp.user_projects (user_id, project_id) VALUES ($1, $2)")
        .bind("conversation-core-fixture-reader")
        .bind(&scope.project_id)
        .execute(&pool)
        .await
        .expect("add temporary shared project reader");
    sqlx::query(
        "INSERT INTO pg_temp.user_tenants (user_id, tenant_id, role) VALUES ($1, $2, 'member')",
    )
    .bind("conversation-core-fixture-reader")
    .bind(&scope.tenant_id)
    .execute(&pool)
    .await
    .expect("add temporary shared tenant reader");
    scope.workspace_id = Some("conversation-core-fixture-workspace".into());
    scope.linked_workspace_task_id = Some("conversation-core-fixture-task".into());
    Some((pool, scope))
}
