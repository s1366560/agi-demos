//! Production list/count SQL over connection-local rows, without changing application tables.
use agistack_adapters_postgres::{ConversationListQuery, PgAgentConversationRepository};
use serde_json::json;
use sqlx::postgres::PgPoolOptions;

#[tokio::test]
async fn unbound_filter_preserves_owner_scope_and_paginates_after_effective_workspace_filter() {
    let Ok(url) = std::env::var("AGISTACK_TEST_DATABASE_URL") else {
        return;
    };
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .max_lifetime(None)
        .idle_timeout(None)
        .connect(&url)
        .await
        .expect("test Postgres must be available");
    for statement in [
        "CREATE TEMP TABLE projects (id text PRIMARY KEY, tenant_id text NOT NULL)",
        "CREATE TEMP TABLE agent_execution_events (conversation_id text, event_time_us bigint)",
        "CREATE TEMP TABLE conversations (id text PRIMARY KEY, project_id text NOT NULL, user_id text NOT NULL, tenant_id text NOT NULL, title text NOT NULL, status text NOT NULL DEFAULT 'active', message_count int NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT NOW(), updated_at timestamptz, summary text, agent_config jsonb, meta jsonb, parent_conversation_id text, branch_point_message_id text, conversation_mode text, workspace_id text, linked_workspace_task_id text, participant_agents jsonb, coordinator_agent_id text, focused_agent_id text)",
        "INSERT INTO projects VALUES ('project', 'tenant'), ('other-project', 'tenant')",
    ] { sqlx::query(statement).execute(&pool).await.unwrap(); }
    for (id, owner, tenant, project, status, workspace, metadata) in [
        (
            "bound-column",
            "owner",
            "tenant",
            "project",
            "active",
            Some("workspace"),
            json!({}),
        ),
        (
            "bound-metadata",
            "owner",
            "tenant",
            "project",
            "active",
            None,
            json!({"workspace_id":" metadata-workspace "}),
        ),
        (
            "workspace-worker:legacy:task:agent",
            "owner",
            "tenant",
            "project",
            "active",
            None,
            json!({"workspace_id":7}),
        ),
        (
            "workspace-chat:chat-workspace",
            "owner",
            "tenant",
            "project",
            "active",
            None,
            json!({}),
        ),
        (
            "foreign-owner",
            "other",
            "tenant",
            "project",
            "active",
            None,
            json!({}),
        ),
        (
            "foreign-tenant",
            "owner",
            "other",
            "project",
            "active",
            None,
            json!({}),
        ),
        (
            "foreign-project",
            "owner",
            "tenant",
            "other-project",
            "active",
            None,
            json!({}),
        ),
        (
            "archived",
            "owner",
            "tenant",
            "project",
            "archived",
            None,
            json!({}),
        ),
        (
            "free-a",
            "owner",
            "tenant",
            "project",
            "active",
            None,
            json!({}),
        ),
        (
            "free-b",
            "owner",
            "tenant",
            "project",
            "active",
            None,
            json!({"workspace_id":7}),
        ),
        (
            "free-c",
            "owner",
            "tenant",
            "project",
            "active",
            Some("  "),
            json!({"workspace_id":"  "}),
        ),
        (
            "free-d",
            "owner",
            "tenant",
            "project",
            "active",
            None,
            json!({"workspace_id":{"nested":"not-a-workspace"}}),
        ),
        (
            "workspace-worker:  :task",
            "owner",
            "tenant",
            "project",
            "active",
            None,
            json!({}),
        ),
    ] {
        sqlx::query("INSERT INTO conversations (id,user_id,tenant_id,project_id,status,workspace_id,meta,title,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,'Owned fixture',TIMESTAMPTZ '2026-10-29 00:00:00+00')")
            .bind(id).bind(owner).bind(tenant).bind(project).bind(status).bind(workspace).bind(metadata)
            .execute(&pool).await.unwrap();
    }
    let repository = PgAgentConversationRepository::new(pool.clone());
    let query = |offset| ConversationListQuery {
        user_id: "owner",
        project_id: "project",
        status: Some("active"),
        workspace_id: None,
        unbound_only: true,
        limit: 2,
        offset,
    };
    assert_eq!(repository.count_conversations(query(0)).await.unwrap(), 5);
    let mut ids = Vec::new();
    for offset in [0, 2, 4] {
        let page = repository.list_conversations(query(offset)).await.unwrap();
        assert_eq!(page.len(), if offset == 4 { 1 } else { 2 });
        ids.extend(page.into_iter().map(|row| row.id));
    }
    assert_eq!(
        ids,
        [
            "free-a",
            "free-b",
            "free-c",
            "free-d",
            "workspace-worker:  :task"
        ]
    );
    assert!(repository
        .list_conversations(query(5))
        .await
        .unwrap()
        .is_empty());
    let all = ConversationListQuery {
        unbound_only: false,
        ..query(0)
    };
    assert_eq!(repository.count_conversations(all).await.unwrap(), 9);
    pool.close().await;
}
