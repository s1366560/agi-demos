use super::support::*;

#[tokio::test]
async fn data_stats_scope_matches_python_authorization() {
    let Some(pool) = pool_or_skip("data_stats_scope_matches_python_authorization").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    ensure_project_read_tables(&pool).await;
    clean_data_stats_rows(&pool).await;

    seed_data_stats_user(&pool, "data_stats_user", false).await;
    seed_data_stats_user(&pool, "data_stats_admin", true).await;
    seed_data_stats_user(&pool, "data_stats_other", false).await;
    seed_data_stats_user(&pool, "data_stats_project_admin", false).await;
    seed_data_stats_tenant(&pool, "data_stats_tenant").await;
    seed_data_stats_tenant(&pool, "data_stats_other_tenant").await;
    seed_data_stats_tenant_member(
        &pool,
        "data_stats_user_tenant",
        "data_stats_user",
        "data_stats_tenant",
        "member",
        ts(2026, 1, 1, 0, 0, 0),
    )
    .await;
    seed_data_stats_tenant_member(
        &pool,
        "data_stats_user_tenant_later",
        "data_stats_user",
        "data_stats_other_tenant",
        "member",
        ts(2026, 1, 2, 0, 0, 0),
    )
    .await;
    seed_data_stats_tenant_member(
        &pool,
        "data_stats_project_admin_tenant",
        "data_stats_project_admin",
        "data_stats_tenant",
        "admin",
        ts(2026, 1, 1, 0, 30, 0),
    )
    .await;
    seed_data_stats_project(
        &pool,
        "data_stats_project_a",
        "data_stats_tenant",
        "data_stats_user",
        ts(2026, 1, 1, 1, 0, 0),
    )
    .await;
    seed_data_stats_project(
        &pool,
        "data_stats_project_b",
        "data_stats_tenant",
        "data_stats_user",
        ts(2026, 1, 1, 2, 0, 0),
    )
    .await;
    seed_data_stats_project(
        &pool,
        "data_stats_project_other",
        "data_stats_other_tenant",
        "data_stats_other",
        ts(2026, 1, 1, 3, 0, 0),
    )
    .await;
    seed_data_stats_project_member(&pool, "data_stats_user", "data_stats_project_a", "member")
        .await;
    seed_data_stats_project_member(&pool, "data_stats_other", "data_stats_project_b", "member")
        .await;
    seed_data_stats_project_member(
        &pool,
        "data_stats_project_admin",
        "data_stats_project_a",
        "admin",
    )
    .await;

    let repo = PgDataStatsRepository::new(pool.clone());
    let tenant_scope = repo
        .resolve_scope("data_stats_user", Some("data_stats_tenant"), None)
        .await
        .expect("tenant scope query succeeds")
        .expect("tenant scope is authorized");
    assert_eq!(tenant_scope.tenant_id.as_deref(), Some("data_stats_tenant"));
    assert_eq!(tenant_scope.project_id, None);
    assert_eq!(
        tenant_scope.access,
        DataStatsAccess::ProjectIds(vec![
            "data_stats_project_a".to_string(),
            "data_stats_project_b".to_string(),
        ])
    );

    let default_scope = repo
        .resolve_scope("data_stats_user", None, None)
        .await
        .expect("default scope query succeeds")
        .expect("default tenant scope is authorized");
    assert_eq!(default_scope, tenant_scope);

    let project_scope = repo
        .resolve_scope(
            "data_stats_user",
            Some("data_stats_tenant"),
            Some("data_stats_project_a"),
        )
        .await
        .expect("project scope query succeeds")
        .expect("project scope is authorized");
    assert_eq!(
        project_scope.tenant_id.as_deref(),
        Some("data_stats_tenant")
    );
    assert_eq!(
        project_scope.project_id.as_deref(),
        Some("data_stats_project_a")
    );
    assert_eq!(
        project_scope.access,
        DataStatsAccess::ProjectIds(vec!["data_stats_project_a".to_string()])
    );

    let tenant_write_denied = repo
        .resolve_scope_with_admin_requirement(
            "data_stats_user",
            Some("data_stats_tenant"),
            None,
            true,
        )
        .await
        .expect("tenant write access query succeeds")
        .expect_err("tenant member cannot perform cleanup delete");
    assert_eq!(
        tenant_write_denied,
        DataStatsScopeError::AdminAccessRequired
    );

    let tenant_admin_scope = repo
        .resolve_scope_with_admin_requirement(
            "data_stats_project_admin",
            Some("data_stats_tenant"),
            None,
            true,
        )
        .await
        .expect("tenant admin cleanup query succeeds")
        .expect("tenant admin can perform cleanup delete");
    assert_eq!(
        tenant_admin_scope.access,
        DataStatsAccess::ProjectIds(vec![
            "data_stats_project_a".to_string(),
            "data_stats_project_b".to_string(),
        ])
    );

    let project_write_denied = repo
        .resolve_scope_with_admin_requirement(
            "data_stats_user",
            None,
            Some("data_stats_project_a"),
            true,
        )
        .await
        .expect("project write access query succeeds")
        .expect_err("project member cannot perform cleanup delete");
    assert_eq!(
        project_write_denied,
        DataStatsScopeError::ProjectAccessRequired
    );

    let project_admin_scope = repo
        .resolve_scope_with_admin_requirement(
            "data_stats_project_admin",
            None,
            Some("data_stats_project_a"),
            true,
        )
        .await
        .expect("project admin cleanup query succeeds")
        .expect("project admin can perform cleanup delete");
    assert_eq!(
        project_admin_scope.access,
        DataStatsAccess::ProjectIds(vec!["data_stats_project_a".to_string()])
    );

    let project_without_membership = repo
        .resolve_scope("data_stats_user", None, Some("data_stats_project_b"))
        .await
        .expect("project access denial query succeeds")
        .expect_err("project membership is required for project-scoped stats");
    assert_eq!(
        project_without_membership,
        DataStatsScopeError::ProjectAccessRequired
    );

    let admin_project_scope = repo
        .resolve_scope("data_stats_admin", None, Some("data_stats_project_b"))
        .await
        .expect("admin project scope query succeeds")
        .expect("global admin bypasses project membership");
    assert_eq!(
        admin_project_scope.access,
        DataStatsAccess::ProjectIds(vec!["data_stats_project_b".to_string()])
    );

    let admin_all_scope = repo
        .resolve_scope("data_stats_admin", None, None)
        .await
        .expect("admin all-scope query succeeds")
        .expect("global admin can request all projects");
    assert_eq!(admin_all_scope.tenant_id, None);
    assert_eq!(admin_all_scope.project_id, None);
    assert_eq!(admin_all_scope.access, DataStatsAccess::AllProjects);

    let missing_project = repo
        .resolve_scope("data_stats_user", None, Some("data_stats_missing_project"))
        .await
        .expect("missing project query succeeds")
        .expect_err("missing project is rejected");
    assert_eq!(missing_project, DataStatsScopeError::ProjectNotFound);

    let mismatched_tenant = repo
        .resolve_scope(
            "data_stats_user",
            Some("data_stats_other_tenant"),
            Some("data_stats_project_a"),
        )
        .await
        .expect("tenant mismatch query succeeds")
        .expect_err("mismatched project tenant is rejected");
    assert_eq!(
        mismatched_tenant,
        DataStatsScopeError::ProjectTenantMismatch
    );

    let tenant_without_membership = repo
        .resolve_scope("data_stats_other", Some("data_stats_tenant"), None)
        .await
        .expect("tenant access denial query succeeds")
        .expect_err("tenant membership is required");
    assert_eq!(
        tenant_without_membership,
        DataStatsScopeError::TenantAccessRequired
    );

    clean_data_stats_rows(&pool).await;
}

async fn clean_data_stats_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM user_projects WHERE project_id LIKE 'data_stats_%'")
        .execute(pool)
        .await
        .expect("clean data stats user projects");
    sqlx::query("DELETE FROM projects WHERE id LIKE 'data_stats_%'")
        .execute(pool)
        .await
        .expect("clean data stats projects");
    sqlx::query("DELETE FROM user_tenants WHERE id LIKE 'data_stats_%'")
        .execute(pool)
        .await
        .expect("clean data stats tenant memberships");
    sqlx::query("DELETE FROM tenants WHERE id LIKE 'data_stats_%'")
        .execute(pool)
        .await
        .expect("clean data stats tenants");
    sqlx::query("DELETE FROM users WHERE id LIKE 'data_stats_%'")
        .execute(pool)
        .await
        .expect("clean data stats users");
}

async fn seed_data_stats_user(pool: &PgPool, user_id: &str, is_superuser: bool) {
    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3) \
         ON CONFLICT (id) DO UPDATE SET \
            email = EXCLUDED.email, \
            is_superuser = EXCLUDED.is_superuser",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind(is_superuser)
    .execute(pool)
    .await
    .expect("seed data stats user");
}

async fn seed_data_stats_tenant(pool: &PgPool, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ($1, $2) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(tenant_id)
    .bind(format!("Tenant {tenant_id}"))
    .execute(pool)
    .await
    .expect("seed data stats tenant");
}

async fn seed_data_stats_tenant_member(
    pool: &PgPool,
    membership_id: &str,
    user_id: &str,
    tenant_id: &str,
    role: &str,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, created_at) \
         VALUES ($1, $2, $3, $4, $5) \
         ON CONFLICT (id) DO UPDATE SET \
            user_id = EXCLUDED.user_id, \
            tenant_id = EXCLUDED.tenant_id, \
            role = EXCLUDED.role, \
            created_at = EXCLUDED.created_at",
    )
    .bind(membership_id)
    .bind(user_id)
    .bind(tenant_id)
    .bind(role)
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed data stats tenant member");
}

async fn seed_data_stats_project(
    pool: &PgPool,
    project_id: &str,
    tenant_id: &str,
    owner_id: &str,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id, is_public, created_at) \
         VALUES ($1, $2, $3, $4, false, $5) \
         ON CONFLICT (id) DO UPDATE SET \
            tenant_id = EXCLUDED.tenant_id, \
            owner_id = EXCLUDED.owner_id, \
            created_at = EXCLUDED.created_at",
    )
    .bind(project_id)
    .bind(tenant_id)
    .bind(format!("Project {project_id}"))
    .bind(owner_id)
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed data stats project");
}

async fn seed_data_stats_project_member(
    pool: &PgPool,
    user_id: &str,
    project_id: &str,
    role: &str,
) {
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) \
         VALUES ($1, $2, $3) \
         ON CONFLICT (user_id, project_id) DO UPDATE SET role = EXCLUDED.role",
    )
    .bind(user_id)
    .bind(project_id)
    .bind(role)
    .execute(pool)
    .await
    .expect("seed data stats project member");
}
