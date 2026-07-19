use super::support::*;

static WORKSPACE_INTEGRATION_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[path = "workspace/access.rs"]
mod access;
#[path = "workspace/outbox.rs"]
mod outbox;
#[path = "workspace/plan_pipeline.rs"]
mod plan_pipeline;
#[path = "workspace/seed.rs"]
mod seed;
#[path = "workspace/task_attempts.rs"]
mod task_attempts;
#[path = "workspace/topology_blackboard.rs"]
mod topology_blackboard;

#[tokio::test]
async fn workspace_repository_roundtrips_against_shared_schema() {
    let _guard = WORKSPACE_INTEGRATION_LOCK.lock().await;
    let Some(pool) = pool_or_skip("workspace_repository_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    seed::reset_and_seed_workspace_rows(&pool).await;

    let repo = PgWorkspaceRepository::new(pool.clone());
    let created_at = ts(2026, 1, 2, 3, 4, 5);
    access::roundtrip_workspace_access(&pool, &repo, created_at).await;
    task_attempts::roundtrip_tasks_and_attempts(&repo, created_at).await;
    topology_blackboard::roundtrip_topology_blackboard(&pool, &repo, created_at).await;
    plan_pipeline::roundtrip_plan_pipeline(&repo, created_at).await;
    outbox::roundtrip_plan_outbox(&repo, created_at).await;
}

#[tokio::test]
async fn workspace_roster_repository_roundtrips_against_shared_schema() {
    let _guard = WORKSPACE_INTEGRATION_LOCK.lock().await;
    let Some(pool) =
        pool_or_skip("workspace_roster_repository_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    seed::reset_and_seed_workspace_rows(&pool).await;

    let repo = PgWorkspaceRepository::new(pool.clone());
    access::roundtrip_workspace_access(&pool, &repo, ts(2026, 1, 2, 3, 4, 5)).await;
}

/// Live-DB proof for the multi-row batch insert: one statement lands all rows
/// with the same constants (`pending` / 0 / 10) and nullable correlation_id as
/// the single-row enqueue.
#[tokio::test]
async fn workspace_blackboard_outbox_batch_insert_roundtrips() {
    let _guard = WORKSPACE_INTEGRATION_LOCK.lock().await;
    let Some(pool) = pool_or_skip("workspace_blackboard_outbox_batch_insert_roundtrips").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    seed::reset_and_seed_workspace_rows(&pool).await;

    let repo = PgWorkspaceRepository::new(pool.clone());
    repo.create_workspace(
        WorkspaceRecord {
            id: "ws_p6_repo".to_string(),
            tenant_id: "t_p6_repo".to_string(),
            project_id: "p_p6_repo".to_string(),
            name: "P6 workspace".to_string(),
            description: Some("shared tables".to_string()),
            created_by: "u_p6_owner".to_string(),
            is_archived: false,
            metadata_json: json!({"workspace_use_case": "programming"}),
            office_status: "inactive".to_string(),
            hex_layout_config_json: json!({}),
            default_blocking_categories_json: vec!["blocked".to_string()],
            created_at: ts(2026, 1, 2, 3, 4, 5),
            updated_at: None,
        },
        "wm_p6_owner".to_string(),
    )
    .await
    .unwrap();
    let batch: Vec<BlackboardOutboxRecord> = (0..3)
        .map(|index| BlackboardOutboxRecord {
            id: format!("outbox_p6_batch_{index}"),
            workspace_id: "ws_p6_repo".to_string(),
            tenant_id: "t_p6_repo".to_string(),
            project_id: "p_p6_repo".to_string(),
            event_type: "workspace_agent_mention_token_chunk".to_string(),
            payload_json: json!({"chunk_index": index}),
            metadata_json: json!({"tenant_id": "t_p6_repo"}),
            correlation_id: (index == 0).then(|| "msg_p6_batch".to_string()),
        })
        .collect();
    repo.enqueue_blackboard_outbox_batch(batch).await.unwrap();

    let batch_count = sqlx::query_as::<_, (i64,)>(
        "SELECT count(*) FROM workspace_blackboard_outbox \
         WHERE id IN ('outbox_p6_batch_0','outbox_p6_batch_1','outbox_p6_batch_2') \
         AND status = 'pending' AND attempt_count = 0 AND max_attempts = 10",
    )
    .fetch_one(&pool)
    .await
    .unwrap()
    .0;
    assert_eq!(batch_count, 3);
    let correlation: (Option<String>,) = sqlx::query_as(
        "SELECT correlation_id FROM workspace_blackboard_outbox WHERE id = 'outbox_p6_batch_0'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(correlation.0.as_deref(), Some("msg_p6_batch"));
}
