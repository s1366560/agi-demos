use super::support::*;

#[tokio::test]
async fn agent_conversation_repo_creates_lists_and_links_workspace_session() {
    let Some(pool) =
        pool_or_skip("agent_conversation_repo_creates_lists_and_links_workspace_session").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_event_rows(&pool, "conv_repo").await;
    seed_conversation_project_access(&pool).await;
    seed_workspace(&pool, "conv_repo_workspace").await;

    let repo = PgAgentConversationRepository::new(pool.clone());
    let created = repo
        .create_conversation(ConversationCreateRecord {
            id: "conv_repo_created".to_string(),
            project_id: "conv_events_project".to_string(),
            user_id: "conv_events_user".to_string(),
            title: "Rust conversation".to_string(),
            agent_config: json!({"selected_agent_id": "builtin:all-access"}),
        })
        .await
        .expect("conversation create succeeds")
        .expect("conversation was returned");

    assert_eq!(created.id, "conv_repo_created");
    assert_eq!(created.project_id, "conv_events_project");
    assert_eq!(created.status, "active");

    let linked = repo
        .update_mode(
            "conv_repo_created",
            "conv_events_project",
            ConversationModePatch {
                conversation_mode: Some(Some("workspace".to_string())),
                workspace_id: Some(Some("conv_repo_workspace".to_string())),
                linked_workspace_task_id: None,
            },
        )
        .await
        .expect("conversation mode update succeeds")
        .expect("updated conversation returned");

    assert_eq!(linked.workspace_id.as_deref(), Some("conv_repo_workspace"));
    assert_eq!(linked.conversation_mode.as_deref(), Some("workspace"));

    let listed = repo
        .list_conversations(ConversationListQuery {
            user_id: "conv_events_user",
            project_id: "conv_events_project",
            status: Some("active"),
            workspace_id: Some("conv_repo_workspace"),
            limit: 10,
            offset: 0,
        })
        .await
        .expect("workspace conversation list succeeds");

    assert!(listed
        .iter()
        .any(|conversation| conversation.id == "conv_repo_created"));
    assert_eq!(
        repo.workspace_access(
            "conv_events_user",
            "conv_events_project",
            "conv_repo_workspace",
        )
        .await
        .expect("workspace access check succeeds"),
        ConversationMutationAccess::Allowed
    );
}

#[tokio::test]
async fn agent_execution_events_replay_filters_by_event_type() {
    let Some(pool) = pool_or_skip("agent_execution_events_replay_filters_by_event_type").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_event_rows(&pool, "conv_events_filter").await;
    seed_conversation(&pool, "conv_events_filter").await;
    seed_event(
        &pool,
        "conv_events_filter_1",
        "conv_events_filter",
        "thought",
        10,
        1,
    )
    .await;
    seed_event(
        &pool,
        "conv_events_filter_2",
        "conv_events_filter",
        "error",
        20,
        1,
    )
    .await;
    seed_event(
        &pool,
        "conv_events_filter_3",
        "conv_events_filter",
        "dead_letter",
        30,
        1,
    )
    .await;

    let repo = PgAgentExecutionEventRepository::new(pool.clone());
    let event_types = vec!["error".to_string(), "dead_letter".to_string()];
    let filtered = repo
        .list_events(AgentExecutionEventListQuery {
            conversation_id: "conv_events_filter",
            from_time_us: 0,
            from_counter: 0,
            limit: 10,
            event_types: &event_types,
        })
        .await
        .expect("filtered replay succeeds");

    let event_types = filtered
        .iter()
        .map(|event| event.event_type.as_str())
        .collect::<Vec<_>>();
    assert_eq!(event_types, vec!["error", "dead_letter"]);
}

#[tokio::test]
async fn agent_execution_events_timeline_supports_backward_pagination() {
    let Some(pool) =
        pool_or_skip("agent_execution_events_timeline_supports_backward_pagination").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_event_rows(&pool, "conv_events_backward").await;
    seed_conversation(&pool, "conv_events_backward").await;
    for index in 1..=5 {
        seed_event(
            &pool,
            &format!("conv_events_backward_{index}"),
            "conv_events_backward",
            "thought",
            i64::from(index) * 10,
            1,
        )
        .await;
    }

    let repo = PgAgentExecutionEventRepository::new(pool.clone());
    let events = repo
        .list_timeline_events(AgentExecutionTimelineQuery {
            conversation_id: "conv_events_backward",
            from_time_us: 0,
            from_counter: 0,
            before_time_us: Some(51),
            before_counter: Some(0),
            limit: 2,
            include_event_types: &[],
            exclude_event_types: &[],
        })
        .await
        .expect("backward timeline replay succeeds");

    assert_eq!(
        events
            .iter()
            .map(|event| event.event_time_us)
            .collect::<Vec<_>>(),
        vec![40, 50]
    );
    assert!(repo
        .has_events_before("conv_events_backward", 40, 1, &[], &[])
        .await
        .expect("has_more check succeeds"));
}

#[tokio::test]
async fn agent_execution_events_empty_event_type_filter_preserves_default_replay() {
    let Some(pool) =
        pool_or_skip("agent_execution_events_empty_event_type_filter_preserves_default_replay")
            .await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_event_rows(&pool, "conv_events_default").await;
    seed_conversation(&pool, "conv_events_default").await;
    seed_event(
        &pool,
        "conv_events_default_1",
        "conv_events_default",
        "thought",
        10,
        1,
    )
    .await;
    seed_event(
        &pool,
        "conv_events_default_2",
        "conv_events_default",
        "error",
        20,
        1,
    )
    .await;

    let repo = PgAgentExecutionEventRepository::new(pool.clone());
    let replay = repo
        .list_events(AgentExecutionEventListQuery {
            conversation_id: "conv_events_default",
            from_time_us: 0,
            from_counter: 0,
            limit: 10,
            event_types: &[],
        })
        .await
        .expect("default replay succeeds");

    assert_eq!(replay.len(), 2);
    assert_eq!(replay[0].event_type, "thought");
    assert_eq!(replay[1].event_type, "error");
}

async fn seed_conversation_project_access(pool: &PgPool) {
    sqlx::query("INSERT INTO users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING")
        .bind("conv_events_user")
        .bind("conv_events@example.com")
        .execute(pool)
        .await
        .expect("seed user");
    sqlx::query("INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING")
        .bind("conv_events_tenant")
        .bind("Conversation Events")
        .execute(pool)
        .await
        .expect("seed tenant");
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id, is_public) \
         VALUES ($1, $2, $3, $4, false) ON CONFLICT (id) DO NOTHING",
    )
    .bind("conv_events_project")
    .bind("conv_events_tenant")
    .bind("Conversation Events Project")
    .bind("conv_events_user")
    .execute(pool)
    .await
    .expect("seed project");
    sqlx::query(
        "INSERT INTO user_projects (id, user_id, project_id, role) \
         VALUES ($1, $2, $3, 'owner') ON CONFLICT DO NOTHING",
    )
    .bind("conv_events_membership")
    .bind("conv_events_user")
    .bind("conv_events_project")
    .execute(pool)
    .await
    .expect("seed user project membership");
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ($1, $2, $3, 'member') ON CONFLICT DO NOTHING",
    )
    .bind("conv_events_tenant_membership")
    .bind("conv_events_user")
    .bind("conv_events_tenant")
    .execute(pool)
    .await
    .expect("seed user tenant membership");
}

async fn seed_conversation(pool: &PgPool, conversation_id: &str) {
    seed_conversation_project_access(pool).await;
    sqlx::query(
        "INSERT INTO conversations (id, user_id, tenant_id, project_id, meta) \
         VALUES ($1, $2, $3, $4, '{}'::json) \
         ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id",
    )
    .bind(conversation_id)
    .bind("conv_events_user")
    .bind("conv_events_tenant")
    .bind("conv_events_project")
    .execute(pool)
    .await
    .expect("seed conversation");
}

async fn seed_workspace(pool: &PgPool, workspace_id: &str) {
    sqlx::query(
        "INSERT INTO workspaces \
             (id, tenant_id, project_id, name, created_by, metadata_json) \
         VALUES ($1, $2, $3, $4, $5, '{}'::json) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(workspace_id)
    .bind("conv_events_tenant")
    .bind("conv_events_project")
    .bind("Conversation Repo Workspace")
    .bind("conv_events_user")
    .execute(pool)
    .await
    .expect("seed workspace");
    sqlx::query(
        "INSERT INTO workspace_members (id, workspace_id, user_id, role) \
         VALUES ($1, $2, $3, 'owner') ON CONFLICT DO NOTHING",
    )
    .bind(format!("{workspace_id}_member"))
    .bind(workspace_id)
    .bind("conv_events_user")
    .execute(pool)
    .await
    .expect("seed workspace member");
}

async fn seed_event(
    pool: &PgPool,
    id: &str,
    conversation_id: &str,
    event_type: &str,
    event_time_us: i64,
    event_counter: i32,
) {
    sqlx::query(
        "INSERT INTO agent_execution_events \
         (id, conversation_id, event_type, event_data, event_time_us, event_counter) \
         VALUES ($1, $2, $3, $4, $5, $6) \
         ON CONFLICT (id) DO UPDATE SET event_type = EXCLUDED.event_type",
    )
    .bind(id)
    .bind(conversation_id)
    .bind(event_type)
    .bind(json!({"event_type": event_type}))
    .bind(event_time_us)
    .bind(event_counter)
    .execute(pool)
    .await
    .expect("seed agent execution event");
}

async fn clean_event_rows(pool: &PgPool, prefix: &str) {
    sqlx::query("DELETE FROM agent_execution_events WHERE conversation_id LIKE $1 OR id LIKE $1")
        .bind(format!("{prefix}%"))
        .execute(pool)
        .await
        .expect("clean events");
    sqlx::query("DELETE FROM conversations WHERE id LIKE $1")
        .bind(format!("{prefix}%"))
        .execute(pool)
        .await
        .expect("clean conversations");
}
