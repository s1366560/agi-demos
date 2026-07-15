use super::support::*;

const TEST_HASHED_PASSWORD: &str = "integration-test-placeholder";

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

#[tokio::test]
async fn agent_execution_event_replay_access_preserves_conversation_membership_policy() {
    let Some(pool) = pool_or_skip(
        "agent_execution_event_replay_access_preserves_conversation_membership_policy",
    )
    .await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_event_rows(&pool, "conv_access").await;
    seed_conversation(&pool, "conv_access_scoped").await;
    seed_workspace(&pool, "conv_access_workspace").await;
    sqlx::query("UPDATE conversations SET workspace_id = $1 WHERE id = $2")
        .bind("conv_access_workspace")
        .bind("conv_access_scoped")
        .execute(&pool)
        .await
        .expect("bind conversation workspace");

    for (user_id, email) in [
        ("conv_access_admin", "conv-access-admin@example.com"),
        ("conv_access_member", "conv-access-member@example.com"),
        ("conv_access_unrelated", "conv-access-unrelated@example.com"),
    ] {
        sqlx::query(
            "INSERT INTO users \
             (id, email, hashed_password, is_active, is_superuser, profile) \
             VALUES ($1, $2, $3, true, false, '{}'::json) ON CONFLICT (id) DO NOTHING",
        )
        .bind(user_id)
        .bind(email)
        .bind(TEST_HASHED_PASSWORD)
        .execute(&pool)
        .await
        .expect("seed replay access user");
    }
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
         VALUES ($1, $2, $3, 'admin', '{}'::json) ON CONFLICT DO NOTHING",
    )
    .bind("conv_access_admin_membership")
    .bind("conv_access_admin")
    .bind("conv_events_tenant")
    .execute(&pool)
    .await
    .expect("seed tenant admin");
    sqlx::query(
        "INSERT INTO workspace_members (id, workspace_id, user_id, role) \
         VALUES ($1, $2, $3, 'member') ON CONFLICT DO NOTHING",
    )
    .bind("conv_access_workspace_membership")
    .bind("conv_access_workspace")
    .bind("conv_access_member")
    .execute(&pool)
    .await
    .expect("seed workspace member");
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
         VALUES ($1, $2, $3, 'member', '{}'::json) ON CONFLICT DO NOTHING",
    )
    .bind("conv_access_member_tenant_membership")
    .bind("conv_access_member")
    .bind("conv_events_tenant")
    .execute(&pool)
    .await
    .expect("seed workspace member tenant access");
    sqlx::query(
        "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
         VALUES ($1, $2, $3, 'member', '{}'::json) ON CONFLICT DO NOTHING",
    )
    .bind("conv_access_member_project_membership")
    .bind("conv_access_member")
    .bind("conv_events_project")
    .execute(&pool)
    .await
    .expect("seed workspace member project access");
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
         VALUES ($1, $2, $3, 'member', '{}'::json) ON CONFLICT DO NOTHING",
    )
    .bind("conv_access_revoked_owner_tenant_membership")
    .bind("conv_access_unrelated")
    .bind("conv_events_tenant")
    .execute(&pool)
    .await
    .expect("seed revocable owner tenant access");
    sqlx::query(
        "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
         VALUES ($1, $2, $3, 'member', '{}'::json) ON CONFLICT DO NOTHING",
    )
    .bind("conv_access_revoked_owner_project_membership")
    .bind("conv_access_unrelated")
    .bind("conv_events_project")
    .execute(&pool)
    .await
    .expect("seed revocable owner project access");
    sqlx::query(
        "INSERT INTO conversations \
         (id, user_id, tenant_id, project_id, title, status, agent_config, meta, message_count, \
          current_mode, merge_strategy, participant_agents) \
         VALUES ($1, $2, $3, $4, 'Revocable owner conversation', 'active', '{}'::json, \
                 '{}'::json, 0, 'build', 'result_only', '[]'::json) \
         ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id",
    )
    .bind("conv_access_revoked_owner")
    .bind("conv_access_unrelated")
    .bind("conv_events_tenant")
    .bind("conv_events_project")
    .execute(&pool)
    .await
    .expect("seed revocable owner conversation");

    let repo = PgAgentExecutionEventRepository::new(pool.clone());

    assert_eq!(
        repo.replay_access("conv_events_user", "conv_access_scoped")
            .await
            .expect("owner access resolves"),
        ConversationReplayAccess::Allowed
    );
    assert_eq!(
        repo.replay_access("conv_access_admin", "conv_access_scoped")
            .await
            .expect("tenant admin access resolves"),
        ConversationReplayAccess::Allowed
    );
    assert_eq!(
        repo.replay_access("conv_access_member", "conv_access_scoped")
            .await
            .expect("workspace member access resolves"),
        ConversationReplayAccess::Allowed
    );
    assert_eq!(
        repo.replay_access("conv_access_unrelated", "conv_access_scoped")
            .await
            .expect("unrelated access resolves"),
        ConversationReplayAccess::Denied
    );
    assert_eq!(
        repo.replay_access("conv_events_user", "conv_access_missing")
            .await
            .expect("missing conversation access resolves"),
        ConversationReplayAccess::NotFound
    );
    assert_eq!(
        repo.replay_access("conv_access_unrelated", "conv_access_revoked_owner")
            .await
            .expect("active owner access resolves"),
        ConversationReplayAccess::Allowed
    );

    sqlx::query("DELETE FROM user_projects WHERE id = $1")
        .bind("conv_access_member_project_membership")
        .execute(&pool)
        .await
        .expect("revoke workspace member project access");
    assert_eq!(
        repo.replay_access("conv_access_member", "conv_access_scoped")
            .await
            .expect("revoked workspace member access resolves"),
        ConversationReplayAccess::Denied
    );

    sqlx::query("DELETE FROM user_tenants WHERE id = $1")
        .bind("conv_access_revoked_owner_tenant_membership")
        .execute(&pool)
        .await
        .expect("revoke owner tenant access");
    assert_eq!(
        repo.replay_access("conv_access_unrelated", "conv_access_revoked_owner")
            .await
            .expect("revoked owner access resolves"),
        ConversationReplayAccess::Denied
    );
}

#[tokio::test]
async fn agent_conversation_owner_access_rejects_collaborator_mutation() {
    let Some(pool) =
        pool_or_skip("agent_conversation_owner_access_rejects_collaborator_mutation").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_event_rows(&pool, "conv_owner_access").await;
    seed_conversation(&pool, "conv_owner_access_scoped").await;

    let repo = PgAgentConversationRepository::new(pool.clone());
    assert_eq!(
        repo.owner_access("conv_events_user", "conv_owner_access_scoped")
            .await
            .expect("owner access resolves"),
        ConversationMutationAccess::Allowed
    );
    assert_eq!(
        repo.owner_access("conv_access_member", "conv_owner_access_scoped")
            .await
            .expect("collaborator access resolves"),
        ConversationMutationAccess::Denied
    );
    assert_eq!(
        repo.owner_access("conv_events_user", "conv_owner_access_missing")
            .await
            .expect("missing access resolves"),
        ConversationMutationAccess::NotFound
    );
}

#[tokio::test]
async fn agent_conversation_message_send_access_requires_full_active_scope() {
    let Some(pool) =
        pool_or_skip("agent_conversation_message_send_access_requires_full_active_scope").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_event_rows(&pool, "conv_send_access").await;
    seed_conversation_project_access(&pool).await;

    sqlx::query(
        "INSERT INTO projects \
         (id, tenant_id, name, owner_id, memory_rules, graph_config, sandbox_type, \
          sandbox_config, is_public, agent_conversation_mode) \
         VALUES ($1, $2, $3, $4, '{}'::json, '{}'::json, 'cloud', '{}'::json, true, \
                 'single_agent') \
         ON CONFLICT (id) DO UPDATE SET is_public = EXCLUDED.is_public",
    )
    .bind("conv_send_access_project")
    .bind("conv_events_tenant")
    .bind("Public send access project")
    .bind("conv_events_user")
    .execute(&pool)
    .await
    .expect("seed send access project");

    for suffix in ["allowed", "no_project", "no_tenant", "public_only"] {
        let user_id = format!("conv_send_access_user_{suffix}");
        sqlx::query(
            "INSERT INTO users \
             (id, email, hashed_password, is_active, is_superuser, profile) \
             VALUES ($1, $2, $3, true, false, '{}'::json) ON CONFLICT (id) DO NOTHING",
        )
        .bind(&user_id)
        .bind(format!("{suffix}@send-access.example.com"))
        .bind(TEST_HASHED_PASSWORD)
        .execute(&pool)
        .await
        .expect("seed send access user");
        sqlx::query(
            "INSERT INTO conversations \
             (id, user_id, tenant_id, project_id, title, status, agent_config, meta, \
              message_count, current_mode, merge_strategy, participant_agents) \
             VALUES ($1, $2, $3, $4, 'Send access conversation', 'active', '{}'::json, \
                     '{}'::json, 0, 'build', 'result_only', '[]'::json) \
             ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id",
        )
        .bind(format!("conv_send_access_{suffix}"))
        .bind(&user_id)
        .bind("conv_events_tenant")
        .bind("conv_send_access_project")
        .execute(&pool)
        .await
        .expect("seed send access conversation");
    }

    for suffix in ["allowed", "no_project"] {
        sqlx::query(
            "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
             VALUES ($1, $2, $3, 'member', '{}'::json) ON CONFLICT DO NOTHING",
        )
        .bind(format!("conv_send_access_tenant_{suffix}"))
        .bind(format!("conv_send_access_user_{suffix}"))
        .bind("conv_events_tenant")
        .execute(&pool)
        .await
        .expect("seed send access tenant membership");
    }
    for suffix in ["allowed", "no_tenant"] {
        sqlx::query(
            "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
             VALUES ($1, $2, $3, 'member', '{}'::json) ON CONFLICT DO NOTHING",
        )
        .bind(format!("conv_send_access_project_{suffix}"))
        .bind(format!("conv_send_access_user_{suffix}"))
        .bind("conv_send_access_project")
        .execute(&pool)
        .await
        .expect("seed send access project membership");
    }

    let repo = PgAgentConversationRepository::new(pool.clone());
    assert_eq!(
        repo.message_send_access(
            "conv_send_access_user_allowed",
            "conv_send_access_project",
            "conv_send_access_allowed",
        )
        .await
        .expect("complete send scope resolves"),
        ConversationMutationAccess::Allowed
    );
    assert_eq!(
        repo.owner_access("conv_send_access_user_allowed", "conv_send_access_allowed",)
            .await
            .expect("complete stop scope resolves"),
        ConversationMutationAccess::Allowed
    );
    for (user_id, conversation_id) in [
        (
            "conv_send_access_user_no_project",
            "conv_send_access_no_project",
        ),
        (
            "conv_send_access_user_no_tenant",
            "conv_send_access_no_tenant",
        ),
        (
            "conv_send_access_user_public_only",
            "conv_send_access_public_only",
        ),
    ] {
        assert_eq!(
            repo.message_send_access(user_id, "conv_send_access_project", conversation_id)
                .await
                .expect("incomplete send scope resolves"),
            ConversationMutationAccess::Denied
        );
        assert_eq!(
            repo.owner_access(user_id, conversation_id)
                .await
                .expect("incomplete stop scope resolves"),
            ConversationMutationAccess::Denied
        );
    }
    assert_eq!(
        repo.message_send_access(
            "conv_send_access_user_allowed",
            "conv_events_project",
            "conv_send_access_allowed",
        )
        .await
        .expect("project mismatch resolves"),
        ConversationMutationAccess::Denied
    );
    assert_eq!(
        repo.message_send_access(
            "conv_send_access_user_allowed",
            "conv_send_access_project",
            "conv_send_access_missing",
        )
        .await
        .expect("missing conversation resolves"),
        ConversationMutationAccess::NotFound
    );

    let projects = PgProjectStore::new(pool);
    let project = projects
        .find_by_id("conv_send_access_project")
        .await
        .expect("sandbox event project lookup succeeds")
        .expect("sandbox event project exists");
    assert!(projects
        .user_can_subscribe_project_events("conv_send_access_user_allowed", &project)
        .await
        .expect("complete sandbox event scope resolves"));
    for user_id in [
        "conv_events_user",
        "conv_send_access_user_no_project",
        "conv_send_access_user_no_tenant",
        "conv_send_access_user_public_only",
    ] {
        assert!(!projects
            .user_can_subscribe_project_events(user_id, &project)
            .await
            .expect("incomplete sandbox event scope resolves"));
    }
}

async fn seed_conversation_project_access(pool: &PgPool) {
    sqlx::query(
        "INSERT INTO users \
         (id, email, hashed_password, is_active, is_superuser, profile) \
         VALUES ($1, $2, $3, true, false, '{}'::json) ON CONFLICT (id) DO NOTHING",
    )
    .bind("conv_events_user")
    .bind("conv_events@example.com")
    .bind(TEST_HASHED_PASSWORD)
    .execute(pool)
    .await
    .expect("seed user");
    sqlx::query(
        "INSERT INTO tenants \
         (id, name, slug, owner_id, plan, max_projects, max_users, max_storage) \
         VALUES ($1, $2, $3, $4, 'free', 10, 5, 1073741824) \
         ON CONFLICT (id) DO NOTHING",
    )
    .bind("conv_events_tenant")
    .bind("Conversation Events")
    .bind("conv-events-tenant")
    .bind("conv_events_user")
    .execute(pool)
    .await
    .expect("seed tenant");
    sqlx::query(
        "INSERT INTO projects \
         (id, tenant_id, name, owner_id, memory_rules, graph_config, sandbox_type, \
          sandbox_config, is_public, agent_conversation_mode) \
         VALUES ($1, $2, $3, $4, '{}'::json, '{}'::json, 'cloud', '{}'::json, false, \
                 'single_agent') \
         ON CONFLICT (id) DO NOTHING",
    )
    .bind("conv_events_project")
    .bind("conv_events_tenant")
    .bind("Conversation Events Project")
    .bind("conv_events_user")
    .execute(pool)
    .await
    .expect("seed project");
    sqlx::query(
        "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
         VALUES ($1, $2, $3, 'owner', '{}'::json) ON CONFLICT DO NOTHING",
    )
    .bind("conv_events_membership")
    .bind("conv_events_user")
    .bind("conv_events_project")
    .execute(pool)
    .await
    .expect("seed user project membership");
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
         VALUES ($1, $2, $3, 'member', '{}'::json) ON CONFLICT DO NOTHING",
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
        "INSERT INTO conversations \
         (id, user_id, tenant_id, project_id, title, status, agent_config, meta, message_count, \
          current_mode, merge_strategy, participant_agents) \
         VALUES ($1, $2, $3, $4, 'Integration conversation', 'active', '{}'::json, '{}'::json, \
                 0, 'build', 'result_only', '[]'::json) \
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
             (id, tenant_id, project_id, name, created_by, is_archived, metadata_json, \
              office_status, hex_layout_config_json, default_blocking_categories_json) \
         VALUES ($1, $2, $3, $4, $5, false, '{}'::json, 'inactive', '{}'::json, '[]'::json) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(workspace_id)
    .bind("conv_events_tenant")
    .bind("conv_events_project")
    .bind(format!("Conversation Repo Workspace {workspace_id}"))
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
