use super::support::*;

#[tokio::test]
async fn audit_logs_filter_runtime_summary_and_access_match_python_scope() {
    let Some(pool) =
        pool_or_skip("audit_logs_filter_runtime_summary_and_access_match_python_scope").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    clean_audit_rows(&pool).await;
    seed_audit_user(&pool, "audit_user", false).await;
    seed_audit_user(&pool, "audit_system_admin", false).await;
    seed_audit_tenant(&pool, "audit_tenant").await;
    seed_audit_tenant(&pool, "audit_other_tenant").await;
    seed_audit_membership(
        &pool,
        "audit_membership",
        "audit_user",
        "audit_tenant",
        "viewer",
    )
    .await;
    seed_audit_system_admin_role(&pool, "audit_system_admin").await;

    seed_audit_log(
        &pool,
        "audit_log_old",
        Some("audit_tenant"),
        "runtime_hook.completed",
        "runtime_hook",
        ts(2026, 1, 1, 0, 0, 0),
        "sandbox",
    )
    .await;
    seed_audit_log(
        &pool,
        "audit_log_new",
        Some("audit_tenant"),
        "runtime_hook.completed",
        "runtime_hook",
        ts(2026, 1, 2, 0, 0, 0),
        "sandbox",
    )
    .await;
    seed_audit_log(
        &pool,
        "audit_log_legacy_system",
        None,
        "runtime_hook.failed",
        "runtime_hook",
        ts(2026, 1, 3, 0, 0, 0),
        "local",
    )
    .await;
    seed_audit_log(
        &pool,
        "audit_log_other_tenant",
        Some("audit_other_tenant"),
        "runtime_hook.completed",
        "runtime_hook",
        ts(2026, 1, 4, 0, 0, 0),
        "sandbox",
    )
    .await;
    seed_audit_log(
        &pool,
        "audit_log_memory",
        Some("audit_tenant"),
        "memory.created",
        "memory",
        ts(2026, 1, 5, 0, 0, 0),
        "unknown",
    )
    .await;

    let repo = PgAuditLogRepository::new(pool.clone());
    assert!(repo
        .tenant_exists("audit_tenant")
        .await
        .expect("tenant exists query succeeds"));
    assert_eq!(
        repo.tenant_member_role("audit_user", "audit_tenant")
            .await
            .expect("tenant role query succeeds")
            .as_deref(),
        Some("viewer")
    );
    assert!(repo
        .user_has_global_admin("audit_system_admin")
        .await
        .expect("global admin query succeeds"));

    let (filtered, total) = repo
        .list_audit_logs(AuditLogListQuery {
            tenant_id: "audit_tenant",
            action: Some("runtime_hook.completed"),
            resource_type: Some("runtime_hook"),
            actor: Some("actor-1"),
            start_time: Some(ts(2026, 1, 1, 12, 0, 0)),
            end_time: Some(ts(2026, 1, 2, 12, 0, 0)),
            limit: 10,
            offset: 0,
        })
        .await
        .expect("audit log list succeeds");
    assert_eq!(total, 1);
    assert_eq!(filtered[0].id, "audit_log_new");

    let (runtime_hooks, total) = repo
        .list_runtime_hook_logs(RuntimeHookAuditQuery {
            tenant_id: "audit_tenant",
            action: None,
            hook_name: Some("pre_tool"),
            executor_kind: None,
            hook_family: Some("tool"),
            isolation_mode: Some("container"),
            limit: 10,
            offset: 0,
        })
        .await
        .expect("runtime hook audit list succeeds");
    assert_eq!(total, 3);
    assert_eq!(
        runtime_hooks
            .iter()
            .map(|row| row.id.as_str())
            .collect::<Vec<_>>(),
        vec!["audit_log_legacy_system", "audit_log_new", "audit_log_old"]
    );

    let summary = repo
        .summarize_runtime_hook_logs(RuntimeHookAuditQuery {
            tenant_id: "audit_tenant",
            action: None,
            hook_name: Some("pre_tool"),
            executor_kind: None,
            hook_family: Some("tool"),
            isolation_mode: Some("container"),
            limit: 50,
            offset: 0,
        })
        .await
        .expect("runtime hook audit summary succeeds");
    assert_eq!(summary.total, 3);
    assert_eq!(summary.action_counts["runtime_hook.completed"], 2);
    assert_eq!(summary.action_counts["runtime_hook.failed"], 1);
    assert_eq!(summary.executor_counts["sandbox"], 2);
    assert_eq!(summary.executor_counts["local"], 1);
    assert_eq!(
        summary.latest_timestamp,
        Some(ts(2026, 1, 3, 0, 0, 0)),
        "legacy system rows remain in tenant-scoped audit scope like Python"
    );
}

async fn clean_audit_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM audit_logs WHERE id LIKE 'audit_log_%'")
        .execute(pool)
        .await
        .expect("clean audit logs");
    sqlx::query("DELETE FROM user_roles WHERE id LIKE 'audit_%'")
        .execute(pool)
        .await
        .expect("clean audit user roles");
    sqlx::query("DELETE FROM roles WHERE id LIKE 'audit_%'")
        .execute(pool)
        .await
        .expect("clean audit roles");
    sqlx::query("DELETE FROM user_tenants WHERE id LIKE 'audit_%'")
        .execute(pool)
        .await
        .expect("clean audit memberships");
    sqlx::query("DELETE FROM users WHERE id LIKE 'audit_%'")
        .execute(pool)
        .await
        .expect("clean audit users");
    sqlx::query("DELETE FROM tenants WHERE id LIKE 'audit_%'")
        .execute(pool)
        .await
        .expect("clean audit tenants");
}

async fn seed_audit_user(pool: &PgPool, user_id: &str, is_superuser: bool) {
    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3) \
         ON CONFLICT (id) DO UPDATE SET is_superuser = EXCLUDED.is_superuser",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind(is_superuser)
    .execute(pool)
    .await
    .expect("seed audit user");
}

async fn seed_audit_tenant(pool: &PgPool, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ($1, $2) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(tenant_id)
    .bind(format!("Tenant {tenant_id}"))
    .execute(pool)
    .await
    .expect("seed audit tenant");
}

async fn seed_audit_membership(
    pool: &PgPool,
    id: &str,
    user_id: &str,
    tenant_id: &str,
    role: &str,
) {
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) VALUES ($1, $2, $3, $4) \
         ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role",
    )
    .bind(id)
    .bind(user_id)
    .bind(tenant_id)
    .bind(role)
    .execute(pool)
    .await
    .expect("seed audit tenant membership");
}

async fn seed_audit_system_admin_role(pool: &PgPool, user_id: &str) {
    sqlx::query(
        "INSERT INTO roles (id, name, description) VALUES ($1, $2, $3) \
         ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description",
    )
    .bind("audit_role_system_admin")
    .bind("system_admin")
    .bind("System administrator")
    .execute(pool)
    .await
    .expect("seed audit system admin role");
    let (role_id,) = sqlx::query_as::<_, (String,)>("SELECT id FROM roles WHERE name = $1")
        .bind("system_admin")
        .fetch_one(pool)
        .await
        .expect("read audit system admin role id");

    sqlx::query(
        "INSERT INTO user_roles (id, user_id, role_id, tenant_id) VALUES ($1, $2, $3, NULL) \
         ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id",
    )
    .bind(format!("audit_role_binding_{user_id}"))
    .bind(user_id)
    .bind(role_id)
    .execute(pool)
    .await
    .expect("seed audit system admin user role");
}

async fn seed_audit_log(
    pool: &PgPool,
    id: &str,
    tenant_id: Option<&str>,
    action: &str,
    resource_type: &str,
    timestamp: DateTime<Utc>,
    executor_kind: &str,
) {
    sqlx::query(
        "INSERT INTO audit_logs \
         (id, \"timestamp\", actor, action, resource_type, resource_id, tenant_id, details, ip_address, user_agent) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) \
         ON CONFLICT (id) DO UPDATE SET \
            \"timestamp\" = EXCLUDED.\"timestamp\", \
            action = EXCLUDED.action, \
            resource_type = EXCLUDED.resource_type, \
            tenant_id = EXCLUDED.tenant_id, \
            details = EXCLUDED.details",
    )
    .bind(id)
    .bind(timestamp)
    .bind("actor-1")
    .bind(action)
    .bind(resource_type)
    .bind("resource-1")
    .bind(tenant_id)
    .bind(json!({
        "hook_name": "pre_tool",
        "executor_kind": executor_kind,
        "hook_family": "tool",
        "isolation_mode": "container"
    }))
    .bind("127.0.0.1")
    .bind("pytest")
    .execute(pool)
    .await
    .expect("seed audit log");
}
