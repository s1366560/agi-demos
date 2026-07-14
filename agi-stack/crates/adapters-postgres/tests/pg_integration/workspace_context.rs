use super::support::*;

const USER_ID: &str = "u_workspace_context";
const TENANT_A: &str = "t_workspace_context_a";
const TENANT_B: &str = "t_workspace_context_b";
const PROJECT_A: &str = "p_workspace_context_a";
const PROJECT_B: &str = "p_workspace_context_b";

#[tokio::test]
async fn workspace_context_is_revision_fenced_idempotent_and_membership_scoped() {
    let Some(pool) =
        pool_or_skip("workspace_context_is_revision_fenced_idempotent_and_membership_scoped").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    let schema_ready = sqlx::query_scalar::<_, bool>(
        "SELECT to_regclass('public.agistack_desktop_workspace_contexts') IS NOT NULL \
         AND to_regclass('public.agistack_desktop_workspace_context_events') IS NOT NULL",
    )
    .fetch_one(&pool)
    .await
    .expect("inspect workspace context migration");
    assert!(
        schema_ready,
        "run Alembic migrations before the integration test"
    );
    clean(&pool).await;
    seed(&pool).await;

    let initial_at = ts(2026, 7, 14, 20, 0, 0);
    let repository = PgWorkspaceContextRepository::new(pool.clone());
    let initial = repository
        .get_or_initialize(USER_ID, initial_at)
        .await
        .expect("initialize authoritative context");
    assert_eq!(initial.context.tenant_id, TENANT_A);
    assert_eq!(initial.context.project_id, PROJECT_A);
    assert_eq!(initial.context.revision, 0);
    assert_eq!(initial.membership_role, "owner");

    let switch_at = initial_at + std::time::Duration::from_secs(1);
    let request = WorkspaceContextSwitchRequest {
        tenant_id: TENANT_B.to_string(),
        project_id: PROJECT_B.to_string(),
        expected_revision: 0,
        idempotency_key: "workspace-context-switch-1".to_string(),
    };
    let switched = repository
        .switch(USER_ID, None, &request, switch_at)
        .await
        .expect("switch context");
    assert!(switched.changed);
    assert_eq!(switched.context.revision, 1);
    assert_eq!(switched.context.tenant_id, TENANT_B);

    let replay = repository
        .switch(
            USER_ID,
            None,
            &request,
            switch_at + std::time::Duration::from_secs(1),
        )
        .await
        .expect("replay switch");
    assert!(!replay.changed);
    assert_eq!(replay.context, switched.context);

    let reused = WorkspaceContextSwitchRequest {
        tenant_id: TENANT_A.to_string(),
        project_id: PROJECT_A.to_string(),
        expected_revision: 1,
        idempotency_key: request.idempotency_key.clone(),
    };
    assert_eq!(
        repository.switch(USER_ID, None, &reused, switch_at).await,
        Err(WorkspaceContextRepositoryError::IdempotencyConflict)
    );

    let stale = WorkspaceContextSwitchRequest {
        idempotency_key: "workspace-context-switch-2".to_string(),
        expected_revision: 0,
        ..request.clone()
    };
    assert_eq!(
        repository.switch(USER_ID, None, &stale, switch_at).await,
        Err(WorkspaceContextRepositoryError::RevisionConflict {
            expected: 0,
            actual: 1,
        })
    );

    let missing_membership = WorkspaceContextSwitchRequest {
        tenant_id: "missing-tenant".to_string(),
        project_id: PROJECT_A.to_string(),
        expected_revision: 1,
        idempotency_key: "workspace-context-switch-3".to_string(),
    };
    assert_eq!(
        repository
            .switch(USER_ID, None, &missing_membership, switch_at)
            .await,
        Err(WorkspaceContextRepositoryError::TenantMembershipRequired)
    );

    let wrong_tenant = WorkspaceContextSwitchRequest {
        tenant_id: TENANT_B.to_string(),
        project_id: PROJECT_A.to_string(),
        expected_revision: 1,
        idempotency_key: "workspace-context-switch-4".to_string(),
    };
    assert_eq!(
        repository
            .switch(USER_ID, None, &wrong_tenant, switch_at)
            .await,
        Err(WorkspaceContextRepositoryError::ProjectUnavailable)
    );

    sqlx::query("DELETE FROM user_projects WHERE user_id = $1 AND project_id = $2")
        .bind(USER_ID)
        .bind(PROJECT_B)
        .execute(&pool)
        .await
        .expect("revoke selected project membership");
    let repaired = repository
        .get_or_initialize(USER_ID, switch_at + std::time::Duration::from_secs(2))
        .await
        .expect("repair inaccessible context deterministically");
    assert_eq!(repaired.context.tenant_id, TENANT_A);
    assert_eq!(repaired.context.project_id, PROJECT_A);
    assert_eq!(repaired.context.revision, 2);

    let event_count = sqlx::query_scalar::<_, i64>(
        "SELECT count(*) FROM agistack_desktop_workspace_context_events WHERE user_id = $1",
    )
    .bind(USER_ID)
    .fetch_one(&pool)
    .await
    .expect("count context events");
    assert_eq!(event_count, 2);
    clean(&pool).await;
}

async fn seed(pool: &PgPool) {
    sqlx::query(
        "INSERT INTO users( \
         id, email, hashed_password, full_name, is_active, is_superuser, must_change_password, profile) \
         VALUES ($1, 'workspace-context@test.invalid', 'unused', 'Context Test', \
                 true, false, false, '{}'::json)",
    )
    .bind(USER_ID)
    .execute(pool)
    .await
    .expect("insert context user");
    for (tenant_id, name, slug, created_at) in [
        (
            TENANT_A,
            "Workspace Context A",
            "workspace-context-a",
            ts(2026, 7, 14, 18, 0, 0),
        ),
        (
            TENANT_B,
            "Workspace Context B",
            "workspace-context-b",
            ts(2026, 7, 14, 19, 0, 0),
        ),
    ] {
        sqlx::query(
            "INSERT INTO tenants( \
             id, name, slug, owner_id, plan, max_projects, max_users, max_storage, created_at) \
             VALUES ($1, $2, $3, $4, 'free', 10, 5, 1073741824, $5)",
        )
        .bind(tenant_id)
        .bind(name)
        .bind(slug)
        .bind(USER_ID)
        .bind(created_at)
        .execute(pool)
        .await
        .expect("insert context tenant");
        sqlx::query(
            "INSERT INTO user_tenants(id, user_id, tenant_id, role, permissions, created_at) \
             VALUES ($1, $2, $3, $4, '{}'::json, $5)",
        )
        .bind(format!("ut_{tenant_id}"))
        .bind(USER_ID)
        .bind(tenant_id)
        .bind(if tenant_id == TENANT_A {
            "owner"
        } else {
            "member"
        })
        .bind(created_at)
        .execute(pool)
        .await
        .expect("insert tenant membership");
    }

    for (project_id, tenant_id, name, created_at) in [
        (
            PROJECT_A,
            TENANT_A,
            "Default project",
            ts(2026, 7, 14, 18, 30, 0),
        ),
        (PROJECT_B, TENANT_B, "Project B", ts(2026, 7, 14, 19, 30, 0)),
    ] {
        sqlx::query(
            "INSERT INTO projects( \
             id, tenant_id, name, owner_id, memory_rules, graph_config, sandbox_type, \
             sandbox_config, is_public, agent_conversation_mode, created_at) \
             VALUES ($1, $2, $3, $4, '{}'::json, '{}'::json, 'cloud', '{}'::json, \
                     false, 'single_agent', $5)",
        )
        .bind(project_id)
        .bind(tenant_id)
        .bind(name)
        .bind(USER_ID)
        .bind(created_at)
        .execute(pool)
        .await
        .expect("insert context project");
        sqlx::query(
            "INSERT INTO user_projects(id, user_id, project_id, role, permissions, created_at) \
             VALUES ($1, $2, $3, 'owner', '{}'::json, $4)",
        )
        .bind(format!("up_{project_id}"))
        .bind(USER_ID)
        .bind(project_id)
        .bind(created_at)
        .execute(pool)
        .await
        .expect("insert project membership");
    }
}

async fn clean(pool: &PgPool) {
    sqlx::query("DELETE FROM agistack_desktop_workspace_context_events WHERE user_id = $1")
        .bind(USER_ID)
        .execute(pool)
        .await
        .expect("delete context events");
    sqlx::query("DELETE FROM agistack_desktop_workspace_contexts WHERE user_id = $1")
        .bind(USER_ID)
        .execute(pool)
        .await
        .expect("delete context");
    sqlx::query("DELETE FROM user_projects WHERE user_id = $1")
        .bind(USER_ID)
        .execute(pool)
        .await
        .expect("delete project memberships");
    sqlx::query("DELETE FROM projects WHERE id = ANY($1)")
        .bind([PROJECT_A, PROJECT_B].as_slice())
        .execute(pool)
        .await
        .expect("delete context projects");
    sqlx::query("DELETE FROM user_tenants WHERE user_id = $1")
        .bind(USER_ID)
        .execute(pool)
        .await
        .expect("delete tenant memberships");
    sqlx::query("DELETE FROM tenants WHERE id = ANY($1)")
        .bind([TENANT_A, TENANT_B].as_slice())
        .execute(pool)
        .await
        .expect("delete context tenants");
    sqlx::query("DELETE FROM users WHERE id = $1")
        .bind(USER_ID)
        .execute(pool)
        .await
        .expect("delete context user");
}
