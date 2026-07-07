use super::support::*;

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

async fn seed_conversation(pool: &PgPool, conversation_id: &str) {
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
