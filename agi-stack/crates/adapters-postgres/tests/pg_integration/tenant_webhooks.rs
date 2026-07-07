use super::support::*;

#[tokio::test]
async fn tenant_webhooks_are_admin_scoped_redacted_and_created_desc() {
    let Some(pool) =
        pool_or_skip("tenant_webhooks_are_admin_scoped_redacted_and_created_desc").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    clean_tenant_webhook_rows(&pool).await;
    seed_webhook_user(&pool, "tenant_webhook_admin", false).await;
    seed_webhook_user(&pool, "tenant_webhook_system_admin", false).await;
    seed_webhook_tenant(&pool, "tenant_webhook_tenant").await;
    seed_webhook_tenant(&pool, "tenant_webhook_other_tenant").await;
    seed_webhook_membership(
        &pool,
        "tenant_webhook_member_admin",
        "tenant_webhook_admin",
        "tenant_webhook_tenant",
        "owner",
    )
    .await;
    seed_system_admin_role(&pool, "tenant_webhook_system_admin").await;
    seed_tenant_webhook(
        &pool,
        "tenant_webhook_old",
        "tenant_webhook_tenant",
        "Workspace Old",
        ts(2026, 1, 1, 0, 0, 0),
        None,
    )
    .await;
    seed_tenant_webhook(
        &pool,
        "tenant_webhook_new",
        "tenant_webhook_tenant",
        "Workspace New",
        ts(2026, 1, 2, 0, 0, 0),
        None,
    )
    .await;
    seed_tenant_webhook(
        &pool,
        "tenant_webhook_deleted",
        "tenant_webhook_tenant",
        "Deleted",
        ts(2026, 1, 3, 0, 0, 0),
        Some(ts(2026, 1, 4, 0, 0, 0)),
    )
    .await;
    seed_tenant_webhook(
        &pool,
        "tenant_webhook_other",
        "tenant_webhook_other_tenant",
        "Other",
        ts(2026, 1, 5, 0, 0, 0),
        None,
    )
    .await;

    let repo = PgTenantWebhookRepository::new(pool.clone());
    assert!(repo
        .tenant_exists("tenant_webhook_tenant")
        .await
        .expect("tenant exists query succeeds"));
    assert_eq!(
        repo.tenant_member_role("tenant_webhook_admin", "tenant_webhook_tenant")
            .await
            .expect("tenant role query succeeds")
            .as_deref(),
        Some("owner")
    );
    assert!(repo
        .user_has_global_admin("tenant_webhook_system_admin")
        .await
        .expect("global admin query succeeds"));

    let webhooks = repo
        .list_webhooks("tenant_webhook_tenant")
        .await
        .expect("tenant webhook list succeeds");

    assert_eq!(webhooks.len(), 2);
    assert_eq!(webhooks[0].id, "tenant_webhook_new");
    assert_eq!(webhooks[0].name, "Workspace New");
    assert_eq!(webhooks[0].events, vec!["workspace.message.created"]);
    assert_eq!(webhooks[0].secret.as_deref(), Some("stored-secret"));
    assert_eq!(webhooks[1].id, "tenant_webhook_old");

    assert!(repo
        .get_webhook("tenant_webhook_deleted")
        .await
        .expect("deleted webhook lookup succeeds")
        .is_none());

    let create_events = vec!["workspace.message.created".to_string()];
    let created = repo
        .create_webhook(CreateTenantWebhook {
            id: "tenant_webhook_created",
            tenant_id: "tenant_webhook_tenant",
            name: "Created",
            url: "https://hooks.example.test/created",
            secret: "whsec_created",
            events: &create_events,
            is_active: true,
        })
        .await
        .expect("tenant webhook create succeeds");
    assert_eq!(created.id, "tenant_webhook_created");
    assert_eq!(created.secret.as_deref(), Some("whsec_created"));
    assert_eq!(created.events, create_events);
    assert!(created.updated_at.is_none());

    let update_events = vec!["workspace.task.completed".to_string()];
    let updated = repo
        .update_webhook(
            "tenant_webhook_created",
            "Created Updated",
            "https://hooks.example.test/updated",
            &update_events,
            false,
        )
        .await
        .expect("tenant webhook update succeeds")
        .expect("updated webhook is returned");
    assert_eq!(updated.name, "Created Updated");
    assert_eq!(updated.url, "https://hooks.example.test/updated");
    assert_eq!(updated.events, update_events);
    assert_eq!(updated.secret.as_deref(), Some("whsec_created"));
    assert!(!updated.is_active);
    assert!(updated.updated_at.is_some());

    assert!(repo
        .delete_webhook("tenant_webhook_created")
        .await
        .expect("tenant webhook delete succeeds"));
    assert!(repo
        .get_webhook("tenant_webhook_created")
        .await
        .expect("deleted created lookup succeeds")
        .is_none());
    assert!(!repo
        .delete_webhook("tenant_webhook_missing")
        .await
        .expect("missing tenant webhook delete succeeds"));
}

async fn clean_tenant_webhook_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM webhooks WHERE id LIKE 'tenant_webhook_%'")
        .execute(pool)
        .await
        .expect("clean tenant webhooks");
    sqlx::query("DELETE FROM user_roles WHERE id LIKE 'tenant_webhook_%'")
        .execute(pool)
        .await
        .expect("clean tenant webhook user roles");
    sqlx::query("DELETE FROM roles WHERE id LIKE 'tenant_webhook_%'")
        .execute(pool)
        .await
        .expect("clean tenant webhook roles");
    sqlx::query("DELETE FROM user_tenants WHERE id LIKE 'tenant_webhook_%'")
        .execute(pool)
        .await
        .expect("clean tenant webhook memberships");
    sqlx::query("DELETE FROM users WHERE id LIKE 'tenant_webhook_%'")
        .execute(pool)
        .await
        .expect("clean tenant webhook users");
    sqlx::query("DELETE FROM tenants WHERE id LIKE 'tenant_webhook_%'")
        .execute(pool)
        .await
        .expect("clean tenant webhook tenants");
}

async fn seed_webhook_user(pool: &PgPool, user_id: &str, is_superuser: bool) {
    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3) \
         ON CONFLICT (id) DO UPDATE SET is_superuser = EXCLUDED.is_superuser",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind(is_superuser)
    .execute(pool)
    .await
    .expect("seed webhook user");
}

async fn seed_webhook_tenant(pool: &PgPool, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ($1, $2) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(tenant_id)
    .bind(format!("Tenant {tenant_id}"))
    .execute(pool)
    .await
    .expect("seed webhook tenant");
}

async fn seed_webhook_membership(
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
    .expect("seed webhook tenant membership");
}

async fn seed_system_admin_role(pool: &PgPool, user_id: &str) {
    sqlx::query(
        "INSERT INTO roles (id, name, description) VALUES ($1, $2, $3) \
         ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description",
    )
    .bind("tenant_webhook_role_system_admin")
    .bind("system_admin")
    .bind("System administrator")
    .execute(pool)
    .await
    .expect("seed system admin role");
    let (role_id,) = sqlx::query_as::<_, (String,)>("SELECT id FROM roles WHERE name = $1")
        .bind("system_admin")
        .fetch_one(pool)
        .await
        .expect("read system admin role id");

    sqlx::query(
        "INSERT INTO user_roles (id, user_id, role_id, tenant_id) VALUES ($1, $2, $3, NULL) \
         ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id",
    )
    .bind(format!("tenant_webhook_role_binding_{user_id}"))
    .bind(user_id)
    .bind(role_id)
    .execute(pool)
    .await
    .expect("seed system admin user role");
}

async fn seed_tenant_webhook(
    pool: &PgPool,
    id: &str,
    tenant_id: &str,
    name: &str,
    created_at: DateTime<Utc>,
    deleted_at: Option<DateTime<Utc>>,
) {
    sqlx::query(
        "INSERT INTO webhooks \
         (id, tenant_id, name, url, secret, events, is_active, created_at, updated_at, deleted_at) \
         VALUES ($1, $2, $3, $4, $5, $6, true, $7, NULL, $8) \
         ON CONFLICT (id) DO UPDATE SET \
            tenant_id = EXCLUDED.tenant_id, \
            name = EXCLUDED.name, \
            created_at = EXCLUDED.created_at, \
            deleted_at = EXCLUDED.deleted_at",
    )
    .bind(id)
    .bind(tenant_id)
    .bind(name)
    .bind("https://hooks.example.test/workspace")
    .bind("stored-secret")
    .bind(json!(["workspace.message.created"]))
    .bind(created_at)
    .bind(deleted_at)
    .execute(pool)
    .await
    .expect("seed tenant webhook");
}
