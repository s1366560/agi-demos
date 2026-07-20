use super::support::*;

const TENANT_ID: &str = "tenant_task_session_pg";
const PROJECT_ID: &str = "project_task_session_pg";
const OWNER_ID: &str = "user_task_session_owner_pg";
const VIEWER_ID: &str = "user_task_session_viewer_pg";
const MEMBER_ID: &str = "user_task_session_member_pg";
const HASH_CREATE: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const HASH_DIFFERENT: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const HASH_ROLLBACK: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const HASH_CONCURRENT: &str = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
static TASK_SESSION_INTEGRATION_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[tokio::test]
async fn task_session_receipt_schema_uses_root_owned_tombstone_lifecycle() {
    let _guard = TASK_SESSION_INTEGRATION_LOCK.lock().await;
    let Some(pool) =
        pool_or_skip("task_session_receipt_schema_uses_root_owned_tombstone_lifecycle").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    let nullable_columns: Vec<(String, String)> = sqlx::query_as(
        "SELECT column_name, is_nullable FROM information_schema.columns \
         WHERE table_schema = ANY(current_schemas(false)) \
           AND table_name = 'task_session_creation_receipts' \
           AND column_name IN ('conversation_id', 'initial_message_id') \
         ORDER BY column_name",
    )
    .fetch_all(&pool)
    .await
    .expect("load receipt child-column nullability");
    assert_eq!(
        nullable_columns,
        vec![
            ("conversation_id".to_string(), "YES".to_string()),
            ("initial_message_id".to_string(), "YES".to_string()),
        ]
    );

    let delete_actions: Vec<(String, String)> = sqlx::query_as(
        "SELECT source_attr.attname, constraint_row.confdeltype::text \
         FROM pg_constraint constraint_row \
         JOIN unnest(constraint_row.conkey) WITH ORDINALITY AS source_key(attnum, ord) \
              ON true \
         JOIN pg_attribute source_attr \
              ON source_attr.attrelid = constraint_row.conrelid \
             AND source_attr.attnum = source_key.attnum \
         WHERE constraint_row.conrelid = 'task_session_creation_receipts'::regclass \
           AND constraint_row.contype = 'f' \
           AND source_attr.attname IN ( \
               'tenant_id', 'project_id', 'workspace_id', \
               'conversation_id', 'initial_message_id' \
           ) \
         ORDER BY source_attr.attname",
    )
    .fetch_all(&pool)
    .await
    .expect("load receipt foreign-key delete actions");
    assert_eq!(
        delete_actions,
        vec![
            ("conversation_id".to_string(), "n".to_string()),
            ("initial_message_id".to_string(), "n".to_string()),
            ("project_id".to_string(), "c".to_string()),
            ("tenant_id".to_string(), "c".to_string()),
            ("workspace_id".to_string(), "c".to_string()),
        ]
    );

    let trigger_definitions: Vec<(String, String)> = sqlx::query_as(
        "SELECT trigger_row.tgname, pg_get_triggerdef(trigger_row.oid) \
         FROM pg_trigger trigger_row \
         WHERE NOT trigger_row.tgisinternal \
           AND trigger_row.tgname IN ( \
               'trg_task_session_receipt_conversation_delete', \
               'trg_task_session_receipt_message_delete' \
           ) \
         ORDER BY trigger_row.tgname",
    )
    .fetch_all(&pool)
    .await
    .expect("load receipt tombstone triggers");
    assert_eq!(trigger_definitions.len(), 2);
    assert!(trigger_definitions
        .iter()
        .all(|(_, definition)| definition.contains("BEFORE DELETE")));
}

#[tokio::test]
async fn task_session_create_replays_exactly_and_rejects_hash_conflicts() {
    let _guard = TASK_SESSION_INTEGRATION_LOCK.lock().await;
    let Some(pool) =
        pool_or_skip("task_session_create_replays_exactly_and_rejects_hash_conflicts").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    reset_task_session_rows(&pool).await;
    seed_project_access(&pool).await;

    let repo = PgWorkspaceRepository::new(pool.clone());
    let record = create_record("create", HASH_CREATE, "workspace_task_session_create");
    let created = repo
        .create_task_session(record.clone())
        .await
        .expect("task session create succeeds");

    assert!(!created.replayed);
    assert_eq!(created.workspace["id"], "workspace_task_session_create");
    assert_eq!(created.conversation["current_mode"], "plan");
    assert_eq!(created.conversation["conversation_mode"], "workspace");
    assert_eq!(
        created.conversation["agent_config"]["selected_agent_id"],
        "builtin:all-access"
    );
    assert_eq!(
        created.conversation["agent_config"]["capability_mode"],
        "code"
    );
    assert_eq!(created.initial_message["sender_type"], "human");
    assert_eq!(
        created.initial_message["metadata"]["source"],
        "task_session"
    );
    assert_task_session_row_counts(&pool, "create", 1).await;
    assert_persisted_task_session_contract(
        &pool,
        "create",
        HASH_CREATE,
        "workspace_task_session_create",
    )
    .await;

    let replayed = repo
        .create_task_session(record.clone())
        .await
        .expect("exact retry succeeds");
    assert!(replayed.replayed);
    assert_eq!(replayed.workspace, created.workspace);
    assert_eq!(replayed.conversation, created.conversation);
    assert_eq!(replayed.initial_message, created.initial_message);
    assert_task_session_row_counts(&pool, "create", 1).await;

    let conflict = repo
        .create_task_session(CreateTaskSessionRecord {
            payload_hash: HASH_DIFFERENT.to_string(),
            ..record.clone()
        })
        .await;
    assert_eq!(
        conflict,
        Err(TaskSessionRepositoryError::IdempotencyConflict)
    );
    assert_task_session_row_counts(&pool, "create", 1).await;
}

#[tokio::test]
async fn task_session_missing_tenant_is_denied_before_any_write() {
    let _guard = TASK_SESSION_INTEGRATION_LOCK.lock().await;
    let Some(pool) = pool_or_skip("task_session_missing_tenant_is_denied_before_any_write").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    reset_task_session_rows(&pool).await;
    seed_project_access(&pool).await;

    let mut record = create_record(
        "missing_tenant",
        HASH_CREATE,
        "workspace_task_session_missing_tenant",
    );
    record.tenant_id = "tenant_task_session_missing_pg".to_string();
    let TaskSessionWorkspaceRecord::Create { workspace, .. } = &mut record.workspace else {
        panic!("test fixture must create a workspace");
    };
    workspace.tenant_id = record.tenant_id.clone();

    let result = PgWorkspaceRepository::new(pool.clone())
        .create_task_session(record)
        .await;
    assert_eq!(result, Err(TaskSessionRepositoryError::ProjectAccessDenied));
    assert_task_session_row_counts(&pool, "missing_tenant", 0).await;
    assert_eq!(
        count_where(
            &pool,
            "workspaces",
            "id",
            "workspace_task_session_missing_tenant",
        )
        .await,
        0
    );
}

#[tokio::test]
async fn task_session_project_member_can_create_a_new_workspace() {
    let _guard = TASK_SESSION_INTEGRATION_LOCK.lock().await;
    let Some(pool) = pool_or_skip("task_session_project_member_can_create_a_new_workspace").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    reset_task_session_rows(&pool).await;
    seed_project_access(&pool).await;

    let mut record = create_record(
        "project_member",
        HASH_CREATE,
        "workspace_task_session_project_member",
    );
    record.actor_user_id = MEMBER_ID.to_string();
    let TaskSessionWorkspaceRecord::Create { workspace, .. } = &mut record.workspace else {
        panic!("test fixture must create a workspace");
    };
    workspace.created_by = MEMBER_ID.to_string();

    let created = PgWorkspaceRepository::new(pool.clone())
        .create_task_session(record)
        .await
        .expect("default project member can create a task session");
    assert!(!created.replayed);
    assert_eq!(created.workspace["created_by"], MEMBER_ID);
    assert_task_session_row_counts(&pool, "project_member", 1).await;
}

#[tokio::test]
async fn child_deletion_tombstones_receipt_and_prevents_ghost_recreation() {
    let _guard = TASK_SESSION_INTEGRATION_LOCK.lock().await;
    let Some(pool) =
        pool_or_skip("child_deletion_tombstones_receipt_and_prevents_ghost_recreation").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    reset_task_session_rows(&pool).await;
    seed_project_access(&pool).await;
    let repo = PgWorkspaceRepository::new(pool.clone());

    let conversation_record = create_record(
        "tombstone_conversation",
        HASH_CREATE,
        "workspace_task_session_tombstone_conversation",
    );
    repo.create_task_session(conversation_record.clone())
        .await
        .expect("create conversation tombstone fixture");
    sqlx::query("DELETE FROM conversations WHERE id = $1")
        .bind(&conversation_record.conversation.id)
        .execute(&pool)
        .await
        .expect("delete receipt conversation child");
    assert_tombstoned_receipt(&pool, &conversation_record.idempotency_key).await;

    let mut same_hash_retry = create_record(
        "tombstone_conversation_retry",
        HASH_CREATE,
        "workspace_task_session_tombstone_conversation_retry",
    );
    same_hash_retry.idempotency_key = conversation_record.idempotency_key.clone();
    assert_eq!(
        repo.create_task_session(same_hash_retry.clone()).await,
        Err(TaskSessionRepositoryError::IdempotencyConflict)
    );
    let mut different_hash_retry = same_hash_retry;
    different_hash_retry.payload_hash = HASH_DIFFERENT.to_string();
    assert_eq!(
        repo.create_task_session(different_hash_retry).await,
        Err(TaskSessionRepositoryError::IdempotencyConflict)
    );
    assert_eq!(
        count_where(
            &pool,
            "workspaces",
            "id",
            "workspace_task_session_tombstone_conversation_retry",
        )
        .await,
        0
    );
    assert_eq!(
        count_where(
            &pool,
            "task_session_creation_receipts",
            "idempotency_key",
            &conversation_record.idempotency_key,
        )
        .await,
        1
    );

    let message_record = create_record(
        "tombstone_message",
        HASH_CONCURRENT,
        "workspace_task_session_tombstone_message",
    );
    repo.create_task_session(message_record.clone())
        .await
        .expect("create message tombstone fixture");
    sqlx::query("DELETE FROM workspace_messages WHERE id = $1")
        .bind(&message_record.initial_message_id)
        .execute(&pool)
        .await
        .expect("delete receipt message child");
    assert_tombstoned_receipt(&pool, &message_record.idempotency_key).await;

    let mut message_retry = create_record(
        "tombstone_message_retry",
        HASH_CONCURRENT,
        "workspace_task_session_tombstone_message_retry",
    );
    message_retry.idempotency_key = message_record.idempotency_key.clone();
    assert_eq!(
        repo.create_task_session(message_retry).await,
        Err(TaskSessionRepositoryError::IdempotencyConflict)
    );
    assert_eq!(
        count_where(
            &pool,
            "workspaces",
            "id",
            "workspace_task_session_tombstone_message_retry",
        )
        .await,
        0
    );
}

#[tokio::test]
async fn task_session_receipts_are_deleted_only_with_project_or_tenant_roots() {
    let _guard = TASK_SESSION_INTEGRATION_LOCK.lock().await;
    let Some(pool) =
        pool_or_skip("task_session_receipts_are_deleted_only_with_project_or_tenant_roots").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    reset_task_session_rows(&pool).await;
    seed_project_access(&pool).await;

    let workspace_repo = PgWorkspaceRepository::new(pool.clone());
    let project_record = create_record(
        "project_root_delete",
        HASH_CREATE,
        "workspace_task_session_project_root_delete",
    );
    workspace_repo
        .create_task_session(project_record.clone())
        .await
        .expect("create project-root receipt fixture");
    assert!(PgProjectReadRepository::new(pool.clone())
        .delete_project(PROJECT_ID)
        .await
        .expect("delete project root"));
    assert_eq!(
        count_where(
            &pool,
            "task_session_creation_receipts",
            "idempotency_key",
            &project_record.idempotency_key,
        )
        .await,
        0
    );

    reset_task_session_rows(&pool).await;
    seed_project_access(&pool).await;
    let tenant_record = create_record(
        "tenant_root_delete",
        HASH_CONCURRENT,
        "workspace_task_session_tenant_root_delete",
    );
    workspace_repo
        .create_task_session(tenant_record.clone())
        .await
        .expect("create tenant-root receipt fixture");
    assert!(PgTenantRepository::new(pool.clone())
        .delete_owned_tenant(OWNER_ID, TENANT_ID)
        .await
        .expect("delete tenant root"));
    assert_eq!(
        count_where(
            &pool,
            "task_session_creation_receipts",
            "idempotency_key",
            &tenant_record.idempotency_key,
        )
        .await,
        0
    );
}

#[tokio::test]
async fn task_session_existing_workspace_requires_write_membership() {
    let _guard = TASK_SESSION_INTEGRATION_LOCK.lock().await;
    let Some(pool) =
        pool_or_skip("task_session_existing_workspace_requires_write_membership").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    reset_task_session_rows(&pool).await;
    seed_project_access(&pool).await;
    seed_existing_workspace(&pool).await;

    let repo = PgWorkspaceRepository::new(pool.clone());
    let owner_record = existing_record("existing_owner", OWNER_ID);
    let created = repo
        .create_task_session(owner_record.clone())
        .await
        .expect("workspace owner can create task session");
    assert_eq!(created.workspace["id"], "workspace_task_session_existing");
    assert_eq!(created.conversation["workspace_name"], "Existing workspace");

    let viewer_error = repo
        .create_task_session(existing_record("existing_viewer", VIEWER_ID))
        .await;
    assert_eq!(
        viewer_error,
        Err(TaskSessionRepositoryError::WorkspaceAccessDenied)
    );
    assert_task_session_row_counts(&pool, "existing_viewer", 0).await;

    sqlx::query(
        "DELETE FROM workspace_members \
         WHERE workspace_id = 'workspace_task_session_existing' AND user_id = $1 \
           AND role IN ('owner', 'admin', 'editor')",
    )
    .bind(OWNER_ID)
    .execute(&pool)
    .await
    .expect("revoke authorized duplicate workspace membership");
    let replay_after_revoke = repo.create_task_session(owner_record.clone()).await;
    assert_eq!(
        replay_after_revoke,
        Err(TaskSessionRepositoryError::WorkspaceAccessDenied)
    );

    let receipt_before_workspace_delete: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM task_session_creation_receipts \
         WHERE idempotency_key = 'task-session-key-existing_owner'",
    )
    .fetch_one(&pool)
    .await
    .expect("count receipt before workspace deletion");
    assert_eq!(receipt_before_workspace_delete, 1);

    sqlx::query("DELETE FROM workspaces WHERE id = 'workspace_task_session_existing'")
        .execute(&pool)
        .await
        .expect("delete receipt workspace resource");
    let receipt_after_workspace_delete: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM task_session_creation_receipts \
         WHERE idempotency_key = 'task-session-key-existing_owner'",
    )
    .fetch_one(&pool)
    .await
    .expect("count receipt after workspace deletion");
    assert_eq!(receipt_after_workspace_delete, 0);

    let replay_after_workspace_delete = repo.create_task_session(owner_record).await;
    assert_eq!(
        replay_after_workspace_delete,
        Err(TaskSessionRepositoryError::WorkspaceNotFound)
    );
}

#[tokio::test]
async fn task_session_failure_rolls_back_every_created_row() {
    let _guard = TASK_SESSION_INTEGRATION_LOCK.lock().await;
    let Some(pool) = pool_or_skip("task_session_failure_rolls_back_every_created_row").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    reset_task_session_rows(&pool).await;
    seed_project_access(&pool).await;
    sqlx::query(
        "INSERT INTO conversations \
         (id, project_id, tenant_id, user_id, title, status, agent_config, meta, message_count, \
          current_mode, merge_strategy, participant_agents, created_at, updated_at) \
         VALUES ('conversation_task_session_rollback', $1, $2, $3, 'Existing', 'active', \
                 '{}'::json, '{}'::json, 0, 'build', 'result_only', '[]'::json, $4, $4)",
    )
    .bind(PROJECT_ID)
    .bind(TENANT_ID)
    .bind(OWNER_ID)
    .bind(ts(2026, 7, 19, 10, 0, 0))
    .execute(&pool)
    .await
    .expect("seed duplicate conversation");

    let repo = PgWorkspaceRepository::new(pool.clone());
    let error = repo
        .create_task_session(create_record(
            "rollback",
            HASH_ROLLBACK,
            "workspace_task_session_rollback",
        ))
        .await;
    assert!(matches!(error, Err(TaskSessionRepositoryError::Storage(_))));

    let workspace_count: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM workspaces WHERE id = 'workspace_task_session_rollback'",
    )
    .fetch_one(&pool)
    .await
    .expect("count rolled back workspace");
    assert_eq!(workspace_count, 0);
    for (table, column, value) in [
        (
            "task_session_creation_receipts",
            "idempotency_key",
            "task-session-key-rollback",
        ),
        ("workspace_messages", "id", "message_task_session_rollback"),
        (
            "workspace_blackboard_outbox",
            "id",
            "outbox_task_session_rollback",
        ),
    ] {
        let sql = format!("SELECT count(*) FROM {table} WHERE {column} = $1");
        let count: i64 = sqlx::query_scalar(&sql)
            .bind(value)
            .fetch_one(&pool)
            .await
            .expect("count rolled back task-session row");
        assert_eq!(count, 0, "unexpected row in {table}");
    }
}

#[tokio::test]
async fn task_session_concurrent_same_key_creates_once_and_replays_once() {
    let _guard = TASK_SESSION_INTEGRATION_LOCK.lock().await;
    let Some(pool) =
        pool_or_skip("task_session_concurrent_same_key_creates_once_and_replays_once").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    reset_task_session_rows(&pool).await;
    seed_project_access(&pool).await;

    let first_repo = PgWorkspaceRepository::new(pool.clone());
    let second_repo = PgWorkspaceRepository::new(pool.clone());
    let record = create_record(
        "concurrent",
        HASH_CONCURRENT,
        "workspace_task_session_concurrent",
    );
    let (first, second) = tokio::join!(
        first_repo.create_task_session(record.clone()),
        second_repo.create_task_session(record)
    );
    let first = first.expect("first concurrent create succeeds");
    let second = second.expect("second concurrent create succeeds");
    assert_ne!(first.replayed, second.replayed);
    assert_eq!(first.workspace, second.workspace);
    assert_task_session_row_counts(&pool, "concurrent", 1).await;
}

fn create_record(suffix: &str, payload_hash: &str, workspace_id: &str) -> CreateTaskSessionRecord {
    let created_at = ts(2026, 7, 19, 10, 0, 0);
    CreateTaskSessionRecord {
        receipt_id: format!("receipt_task_session_{suffix}"),
        actor_user_id: OWNER_ID.to_string(),
        tenant_id: TENANT_ID.to_string(),
        project_id: PROJECT_ID.to_string(),
        idempotency_key: format!("task-session-key-{suffix}"),
        payload_hash: payload_hash.to_string(),
        workspace: TaskSessionWorkspaceRecord::Create {
            workspace: Box::new(WorkspaceRecord {
                id: workspace_id.to_string(),
                tenant_id: TENANT_ID.to_string(),
                project_id: PROJECT_ID.to_string(),
                name: format!("Task session {suffix}"),
                description: Some("Atomic task session".to_string()),
                created_by: OWNER_ID.to_string(),
                is_archived: false,
                metadata_json: json!({
                    "source": "desktop",
                    "workspace_use_case": "programming",
                    "collaboration_mode": "multi_agent_shared"
                }),
                office_status: "inactive".to_string(),
                hex_layout_config_json: json!({}),
                default_blocking_categories_json: Vec::new(),
                created_at,
                updated_at: None,
            }),
            owner_member_id: format!("member_task_session_{suffix}"),
        },
        conversation: TaskSessionConversationRecord {
            id: format!("conversation_task_session_{suffix}"),
            title: format!("Task session {suffix}"),
            capability_mode: TaskSessionCapabilityMode::Code,
        },
        initial_message_id: format!("message_task_session_{suffix}"),
        initial_message_content: "Build the atomic task session".to_string(),
        blackboard_outbox_id: format!("outbox_task_session_{suffix}"),
        created_at,
    }
}

fn existing_record(suffix: &str, actor_user_id: &str) -> CreateTaskSessionRecord {
    let created_at = ts(2026, 7, 19, 10, 0, 0);
    CreateTaskSessionRecord {
        receipt_id: format!("receipt_task_session_{suffix}"),
        actor_user_id: actor_user_id.to_string(),
        tenant_id: TENANT_ID.to_string(),
        project_id: PROJECT_ID.to_string(),
        idempotency_key: format!("task-session-key-{suffix}"),
        payload_hash: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
            .to_string(),
        workspace: TaskSessionWorkspaceRecord::Existing {
            workspace_id: "workspace_task_session_existing".to_string(),
        },
        conversation: TaskSessionConversationRecord {
            id: format!("conversation_task_session_{suffix}"),
            title: format!("Existing task session {suffix}"),
            capability_mode: TaskSessionCapabilityMode::Work,
        },
        initial_message_id: format!("message_task_session_{suffix}"),
        initial_message_content: "Research the existing workspace".to_string(),
        blackboard_outbox_id: format!("outbox_task_session_{suffix}"),
        created_at,
    }
}

async fn assert_task_session_row_counts(pool: &PgPool, suffix: &str, expected: i64) {
    for (table, column, value) in [
        (
            "task_session_creation_receipts",
            "idempotency_key",
            format!("task-session-key-{suffix}"),
        ),
        (
            "conversations",
            "id",
            format!("conversation_task_session_{suffix}"),
        ),
        (
            "workspace_messages",
            "id",
            format!("message_task_session_{suffix}"),
        ),
        (
            "workspace_blackboard_outbox",
            "id",
            format!("outbox_task_session_{suffix}"),
        ),
    ] {
        let sql = format!("SELECT count(*) FROM {table} WHERE {column} = $1");
        let count: i64 = sqlx::query_scalar(&sql)
            .bind(value)
            .fetch_one(pool)
            .await
            .unwrap_or_else(|error| panic!("count {table}: {error}"));
        assert_eq!(count, expected, "unexpected row count in {table}");
    }
}

async fn assert_tombstoned_receipt(pool: &PgPool, idempotency_key: &str) {
    let receipt: (
        Option<String>,
        Option<String>,
        sqlx::types::Json<serde_json::Value>,
    ) = sqlx::query_as(
        "SELECT conversation_id, initial_message_id, response_json \
         FROM task_session_creation_receipts WHERE idempotency_key = $1",
    )
    .bind(idempotency_key)
    .fetch_one(pool)
    .await
    .expect("load tombstoned receipt");
    assert_eq!(receipt.0, None);
    assert_eq!(receipt.1, None);
    assert_eq!(receipt.2 .0, json!({ "tombstone": true }));
}

async fn count_where(pool: &PgPool, table: &str, column: &str, value: &str) -> i64 {
    let sql = format!("SELECT count(*) FROM {table} WHERE {column} = $1");
    sqlx::query_scalar(&sql)
        .bind(value)
        .fetch_one(pool)
        .await
        .unwrap_or_else(|error| panic!("count {table}.{column}: {error}"))
}

async fn assert_persisted_task_session_contract(
    pool: &PgPool,
    suffix: &str,
    payload_hash: &str,
    workspace_id: &str,
) {
    let conversation_id = format!("conversation_task_session_{suffix}");
    let conversation: (
        String,
        String,
        String,
        sqlx::types::Json<serde_json::Value>,
        i32,
    ) = sqlx::query_as(
        "SELECT workspace_id, conversation_mode, current_mode, agent_config, message_count \
             FROM conversations WHERE id = $1",
    )
    .bind(&conversation_id)
    .fetch_one(pool)
    .await
    .expect("load persisted task-session conversation");
    assert_eq!(conversation.0, workspace_id);
    assert_eq!(conversation.1, "workspace");
    assert_eq!(conversation.2, "plan");
    assert_eq!(conversation.3["selected_agent_id"], "builtin:all-access");
    assert_eq!(conversation.3["capability_mode"], "code");
    assert_eq!(conversation.4, 0);

    let message_id = format!("message_task_session_{suffix}");
    let message: (String, String, String) = sqlx::query_as(
        "SELECT workspace_id, sender_type, content FROM workspace_messages WHERE id = $1",
    )
    .bind(&message_id)
    .fetch_one(pool)
    .await
    .expect("load persisted initial workspace message");
    assert_eq!(message.0, workspace_id);
    assert_eq!(message.1, "human");
    assert_eq!(message.2, "Build the atomic task session");

    let outbox_id = format!("outbox_task_session_{suffix}");
    let outbox: (
        String,
        String,
        i32,
        i32,
        sqlx::types::Json<serde_json::Value>,
    ) = sqlx::query_as(
        "SELECT event_type, status, attempt_count, max_attempts, payload_json \
             FROM workspace_blackboard_outbox WHERE id = $1",
    )
    .bind(&outbox_id)
    .fetch_one(pool)
    .await
    .expect("load persisted task-session outbox");
    assert_eq!(outbox.0, "workspace_message_created");
    assert_eq!(outbox.1, "pending");
    assert_eq!(outbox.2, 0);
    assert_eq!(outbox.3, 10);
    assert_eq!(outbox.4["message"]["id"], message_id);

    let receipt: (
        String,
        String,
        String,
        String,
        sqlx::types::Json<serde_json::Value>,
    ) = sqlx::query_as(
        "SELECT payload_hash, workspace_id, conversation_id, initial_message_id, response_json \
         FROM task_session_creation_receipts \
         WHERE idempotency_key = $1",
    )
    .bind(format!("task-session-key-{suffix}"))
    .fetch_one(pool)
    .await
    .expect("load persisted task-session receipt");
    assert_eq!(receipt.0, payload_hash);
    assert_eq!(receipt.1, workspace_id);
    assert_eq!(receipt.2, conversation_id);
    assert_eq!(receipt.3, message_id);
    assert_eq!(receipt.4["workspace"]["id"], workspace_id);
    assert_eq!(receipt.4["conversation"]["current_mode"], "plan");
}

async fn seed_project_access(pool: &PgPool) {
    sqlx::query(
        "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, profile) VALUES \
         ($1, 'task-session-owner@example.com', 'integration-test-only', true, false, '{}'::json), \
         ($2, 'task-session-viewer@example.com', 'integration-test-only', true, false, '{}'::json), \
         ($3, 'task-session-member@example.com', 'integration-test-only', true, false, '{}'::json)",
    )
    .bind(OWNER_ID)
    .bind(VIEWER_ID)
    .bind(MEMBER_ID)
    .execute(pool)
    .await
    .expect("seed task-session users");
    sqlx::query(
        "INSERT INTO tenants \
         (id, name, slug, owner_id, plan, max_projects, max_users, max_storage) \
         VALUES ($1, 'Task session tenant', 'task-session-pg', $2, 'free', 10, 5, 1073741824)",
    )
    .bind(TENANT_ID)
    .bind(OWNER_ID)
    .execute(pool)
    .await
    .expect("seed task-session tenant");
    sqlx::query(
        "INSERT INTO projects \
         (id, tenant_id, name, owner_id, memory_rules, graph_config, sandbox_type, \
          sandbox_config, is_public, agent_conversation_mode) \
         VALUES ($1, $2, 'Task session project', $3, '{}'::json, '{}'::json, \
                 'cloud', '{}'::json, false, 'single_agent')",
    )
    .bind(PROJECT_ID)
    .bind(TENANT_ID)
    .bind(OWNER_ID)
    .execute(pool)
    .await
    .expect("seed task-session project");
    sqlx::query(
        "INSERT INTO user_projects (id, user_id, project_id, role, permissions) VALUES \
         ('task_session_owner_access', $1, $4, 'owner', '{}'::json), \
         ('task_session_viewer_deny_access', $2, $4, 'viewer', '{}'::json), \
         ('task_session_viewer_write_access', $2, $4, 'editor', '{}'::json), \
         ('task_session_member_access', $3, $4, 'member', '{}'::json)",
    )
    .bind(OWNER_ID)
    .bind(VIEWER_ID)
    .bind(MEMBER_ID)
    .bind(PROJECT_ID)
    .execute(pool)
    .await
    .expect("seed task-session project access");
}

async fn seed_existing_workspace(pool: &PgPool) {
    let created_at = ts(2026, 7, 19, 9, 0, 0);
    sqlx::query(
        "INSERT INTO workspaces \
         (id, tenant_id, project_id, name, description, created_by, is_archived, metadata_json, \
          office_status, hex_layout_config_json, default_blocking_categories_json, \
          created_at, updated_at) \
         VALUES ('workspace_task_session_existing', $1, $2, 'Existing workspace', NULL, $3, \
                 false, '{}'::json, 'inactive', '{}'::json, '[]'::json, $4, NULL)",
    )
    .bind(TENANT_ID)
    .bind(PROJECT_ID)
    .bind(OWNER_ID)
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed existing workspace");
    sqlx::query(
        "INSERT INTO workspace_members \
         (id, workspace_id, user_id, role, invited_by, created_at, updated_at) VALUES \
         ('member_task_session_existing_owner_viewer', 'workspace_task_session_existing', $1, \
          'viewer', $1, $3, NULL), \
         ('member_task_session_existing_owner', 'workspace_task_session_existing', $1, \
          'owner', $1, $3, NULL), \
         ('member_task_session_existing_viewer', 'workspace_task_session_existing', $2, \
          'viewer', $1, $3, NULL)",
    )
    .bind(OWNER_ID)
    .bind(VIEWER_ID)
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed existing workspace members");
}

async fn reset_task_session_rows(pool: &PgPool) {
    for statement in [
        "DELETE FROM task_session_creation_receipts WHERE tenant_id = 'tenant_task_session_pg'",
        "DELETE FROM workspace_blackboard_outbox WHERE tenant_id = 'tenant_task_session_pg'",
        "DELETE FROM workspace_messages WHERE workspace_id LIKE 'workspace_task_session_%'",
        "DELETE FROM conversations WHERE tenant_id = 'tenant_task_session_pg'",
        "DELETE FROM workspace_members WHERE workspace_id LIKE 'workspace_task_session_%'",
        "DELETE FROM workspaces WHERE tenant_id = 'tenant_task_session_pg'",
        "DELETE FROM user_projects WHERE project_id = 'project_task_session_pg'",
        "DELETE FROM projects WHERE id = 'project_task_session_pg'",
        "DELETE FROM tenants WHERE id = 'tenant_task_session_pg'",
        "DELETE FROM users WHERE id IN ( \
            'user_task_session_owner_pg', \
            'user_task_session_viewer_pg', \
            'user_task_session_member_pg' \
        )",
    ] {
        sqlx::query(statement)
            .execute(pool)
            .await
            .unwrap_or_else(|error| panic!("task-session cleanup failed: {error}"));
    }
}
