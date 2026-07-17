use super::support::*;

const USER_ID: &str = "u_my_work_repo";
const TENANT_ID: &str = "t_my_work_repo";
const PROJECT_ID: &str = "p_my_work_repo";
const WORKSPACE_ID: &str = "ws_my_work_repo";
const TASK_ID: &str = "task_my_work_repo";
const CONVERSATION_ID: &str = "conv_my_work_repo";

static MY_WORK_INTEGRATION_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[tokio::test]
async fn project_my_work_repository_enforces_complete_scope_and_latest_authorities() {
    let _guard = MY_WORK_INTEGRATION_LOCK.lock().await;
    let Some(pool) =
        pool_or_skip("project_my_work_repository_enforces_complete_scope_and_latest_authorities")
            .await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    ensure_project_read_tables(&pool).await;
    ensure_hitl_tables(&pool).await;
    cleanup(&pool).await;

    let now = ts(2026, 7, 15, 8, 0, 0);
    seed(&pool, now).await;
    let repo = PgWorkspaceRepository::new(pool.clone());

    assert!(repo
        .user_can_access_project_my_work(USER_ID, PROJECT_ID)
        .await
        .expect("complete project scope"));
    assert!(!repo
        .user_can_access_project_my_work("u_my_work_missing", PROJECT_ID)
        .await
        .expect("missing project scope"));

    let attempts = repo
        .list_latest_project_my_work_attempts(PROJECT_ID, USER_ID)
        .await
        .expect("latest attempts");
    assert_eq!(attempts.len(), 1);
    assert_eq!(attempts[0].authority_id, "attempt_my_work_2");
    assert_eq!(attempts[0].attempt_number, 2);
    assert_eq!(attempts[0].conversation_id, CONVERSATION_ID);
    assert_eq!(attempts[0].title, "Authoritative task");
    assert_eq!(
        attempts[0].conversation_agent_config,
        Some(json!({"capability_mode": "code"}))
    );
    assert_eq!(
        attempts[0].workspace_metadata,
        json!({"capability_mode": "work"})
    );

    let hitl = repo
        .list_pending_project_my_work_hitl(PROJECT_ID, USER_ID, now)
        .await
        .expect("pending HITL authorities");
    assert_eq!(hitl.len(), 1);
    assert_eq!(hitl[0].authority_id, "hitl_my_work_permission");
    assert_eq!(hitl[0].request_type, "permission");
    assert_eq!(hitl[0].workspace_id, WORKSPACE_ID);

    cleanup(&pool).await;
}

async fn seed(pool: &PgPool, now: DateTime<Utc>) {
    sqlx::query(
        "INSERT INTO users \
             (id, email, hashed_password, is_active, is_superuser, profile) \
         VALUES ($1, 'my-work-repo@example.com', 'integration-test-only', true, false, '{}'::json)",
    )
    .bind(USER_ID)
    .execute(pool)
    .await
    .expect("seed user");
    sqlx::query(
        "INSERT INTO tenants \
             (id, name, slug, owner_id, plan, max_projects, max_users, max_storage) \
         VALUES ($1, 'My Work', 'my-work-repo-integration', $2, 'free', 10, 5, 1073741824)",
    )
    .bind(TENANT_ID)
    .bind(USER_ID)
    .execute(pool)
    .await
    .expect("seed tenant");
    sqlx::query(
        "INSERT INTO projects \
             (id, tenant_id, name, owner_id, memory_rules, graph_config, sandbox_type, \
              sandbox_config, is_public, agent_conversation_mode) \
         VALUES ($1, $2, 'My Work project', $3, '{}'::json, '{}'::json, 'cloud', \
                 '{}'::json, false, 'single_agent')",
    )
    .bind(PROJECT_ID)
    .bind(TENANT_ID)
    .bind(USER_ID)
    .execute(pool)
    .await
    .expect("seed project");
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
         VALUES ('ut_my_work_repo', $1, $2, 'owner', '{}'::json)",
    )
    .bind(USER_ID)
    .bind(TENANT_ID)
    .execute(pool)
    .await
    .expect("seed tenant membership");
    sqlx::query(
        "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
         VALUES ('up_my_work_repo', $1, $2, 'owner', '{}'::json)",
    )
    .bind(USER_ID)
    .bind(PROJECT_ID)
    .execute(pool)
    .await
    .expect("seed project membership");
    sqlx::query(
        "INSERT INTO workspaces \
             (id, tenant_id, project_id, name, created_by, is_archived, metadata_json, \
              office_status, hex_layout_config_json, default_blocking_categories_json, \
              created_at) \
         VALUES ($1, $2, $3, 'My Work workspace', $4, false, \
                 '{\"capability_mode\":\"work\"}'::json, 'inactive', '{}'::json, '[]'::json, $5)",
    )
    .bind(WORKSPACE_ID)
    .bind(TENANT_ID)
    .bind(PROJECT_ID)
    .bind(USER_ID)
    .bind(now)
    .execute(pool)
    .await
    .expect("seed workspace");
    sqlx::query(
        "INSERT INTO workspace_members (id, workspace_id, user_id, role, created_at) \
         VALUES ('wm_my_work_repo', $1, $2, 'owner', $3)",
    )
    .bind(WORKSPACE_ID)
    .bind(USER_ID)
    .bind(now)
    .execute(pool)
    .await
    .expect("seed workspace membership");
    sqlx::query(
        "INSERT INTO workspace_tasks \
             (id, workspace_id, title, created_by, status, priority, metadata_json, created_at) \
         VALUES ($1, $2, 'Authoritative task', $3, 'in_progress', 1, '{}'::json, $4)",
    )
    .bind(TASK_ID)
    .bind(WORKSPACE_ID)
    .bind(USER_ID)
    .bind(now)
    .execute(pool)
    .await
    .expect("seed workspace task");
    sqlx::query(
        "INSERT INTO conversations \
             (id, project_id, tenant_id, user_id, title, status, agent_config, meta, \
              message_count, current_mode, merge_strategy, participant_agents, workspace_id, \
              linked_workspace_task_id, created_at) \
         VALUES ($1, $2, $3, $4, 'Authoritative session', 'active', \
                 '{\"capability_mode\":\"code\"}'::json, '{}'::json, 0, 'build', \
                 'result_only', '[]'::json, $5, $6, $7)",
    )
    .bind(CONVERSATION_ID)
    .bind(PROJECT_ID)
    .bind(TENANT_ID)
    .bind(USER_ID)
    .bind(WORKSPACE_ID)
    .bind(TASK_ID)
    .bind(now)
    .execute(pool)
    .await
    .expect("seed conversation");
    sqlx::query(
        "INSERT INTO workspace_task_session_attempts \
             (id, workspace_task_id, root_goal_task_id, workspace_id, attempt_number, status, \
              conversation_id, candidate_artifacts_json, candidate_verifications_json, \
              created_at, updated_at) \
         VALUES \
             ('attempt_my_work_1', $1, $1, $2, 1, 'blocked', $3, '[]'::json, '[]'::json, $4, $4), \
             ('attempt_my_work_2', $1, $1, $2, 2, 'running', $3, '[]'::json, '[]'::json, $5, $5)",
    )
    .bind(TASK_ID)
    .bind(WORKSPACE_ID)
    .bind(CONVERSATION_ID)
    .bind(now - chrono::Duration::minutes(2))
    .bind(now - chrono::Duration::minutes(1))
    .execute(pool)
    .await
    .expect("seed attempts");
    sqlx::query(
        "INSERT INTO hitl_requests \
             (id, request_type, conversation_id, tenant_id, project_id, user_id, question, \
              request_metadata, status, created_at, expires_at) \
         VALUES \
             ('hitl_my_work_permission', 'permission', $1, $2, $3, $4, 'Approve?', \
              '{}'::json, 'pending', $5, $6), \
             ('hitl_my_work_expired', 'decision', $1, $2, $3, $4, 'Choose?', \
              '{}'::json, 'pending', $5, $5)",
    )
    .bind(CONVERSATION_ID)
    .bind(TENANT_ID)
    .bind(PROJECT_ID)
    .bind(USER_ID)
    .bind(now)
    .bind(now + chrono::Duration::minutes(5))
    .execute(pool)
    .await
    .expect("seed HITL requests");
}

async fn cleanup(pool: &PgPool) {
    for statement in [
        "DELETE FROM hitl_requests WHERE id LIKE 'hitl_my_work_%'",
        "DELETE FROM workspace_task_session_attempts WHERE id LIKE 'attempt_my_work_%'",
        "DELETE FROM conversations WHERE id = 'conv_my_work_repo'",
        "DELETE FROM workspace_tasks WHERE id = 'task_my_work_repo'",
        "DELETE FROM workspace_members WHERE id = 'wm_my_work_repo'",
        "DELETE FROM workspaces WHERE id = 'ws_my_work_repo'",
        "DELETE FROM user_projects WHERE id = 'up_my_work_repo'",
        "DELETE FROM user_tenants WHERE id = 'ut_my_work_repo'",
        "DELETE FROM projects WHERE id = 'p_my_work_repo'",
        "DELETE FROM tenants WHERE id = 't_my_work_repo'",
        "DELETE FROM users WHERE id = 'u_my_work_repo'",
    ] {
        sqlx::query(statement)
            .execute(pool)
            .await
            .unwrap_or_else(|error| panic!("My Work cleanup failed for {statement}: {error}"));
    }
}
