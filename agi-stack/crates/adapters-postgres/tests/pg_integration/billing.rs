use super::support::*;

#[tokio::test]
async fn billing_invoices_are_admin_scoped_and_created_desc() {
    let Some(pool) = pool_or_skip("billing_invoices_are_admin_scoped_and_created_desc").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    clean_billing_rows(&pool).await;
    seed_billing_tenant(&pool, "billing_tenant", "notification_user", "admin").await;
    seed_billing_tenant(
        &pool,
        "billing_member_tenant",
        "notification_user",
        "member",
    )
    .await;
    seed_billing_tenant(&pool, "billing_owner_tenant", "notification_user", "owner").await;
    seed_invoice(
        &pool,
        "billing_invoice_old",
        "billing_tenant",
        ts(2026, 1, 1, 0, 0, 0),
    )
    .await;
    seed_invoice(
        &pool,
        "billing_invoice_new",
        "billing_tenant",
        ts(2026, 1, 2, 0, 0, 0),
    )
    .await;
    seed_invoice(
        &pool,
        "billing_invoice_other",
        "billing_other_tenant",
        ts(2026, 1, 3, 0, 0, 0),
    )
    .await;
    seed_billing_project(
        &pool,
        "billing_project_1",
        "billing_tenant",
        "notification_user",
    )
    .await;
    seed_billing_project(
        &pool,
        "billing_project_2",
        "billing_tenant",
        "notification_user",
    )
    .await;
    seed_billing_project(
        &pool,
        "billing_project_other",
        "billing_other_tenant",
        "notification_user",
    )
    .await;
    seed_billing_memory(&pool, "billing_memory_1", "billing_project_1").await;
    seed_billing_memory(&pool, "billing_memory_2", "billing_project_1").await;
    seed_billing_memory(&pool, "billing_memory_3", "billing_project_2").await;
    seed_billing_project_user(&pool, "billing_project_1", "billing_user_a").await;
    seed_billing_project_user(&pool, "billing_project_1", "billing_user_b").await;
    seed_billing_project_user(&pool, "billing_project_2", "billing_user_a").await;

    let repo = PgBillingRepository::new(pool.clone());
    assert_eq!(
        repo.tenant_member_role("notification_user", "billing_tenant")
            .await
            .expect("role query succeeds")
            .as_deref(),
        Some("admin")
    );
    assert_eq!(
        repo.tenant_member_role("notification_user", "billing_member_tenant")
            .await
            .expect("role query succeeds")
            .as_deref(),
        Some("member")
    );
    assert_eq!(
        repo.tenant_member_role("notification_user", "billing_owner_tenant")
            .await
            .expect("role query succeeds")
            .as_deref(),
        Some("owner")
    );
    assert!(repo
        .tenant_exists("billing_tenant")
        .await
        .expect("tenant exists query succeeds"));

    let invoices = repo
        .list_invoices("billing_tenant")
        .await
        .expect("invoice list succeeds");

    assert_eq!(invoices.len(), 2);
    assert_eq!(invoices[0].id, "billing_invoice_new");
    assert_eq!(invoices[1].id, "billing_invoice_old");
    assert!(invoices
        .iter()
        .all(|invoice| invoice.tenant_id == "billing_tenant"));

    let tenant = repo
        .billing_tenant("billing_tenant")
        .await
        .expect("tenant summary query succeeds")
        .expect("tenant exists");
    assert_eq!(tenant.plan, "pro");
    assert_eq!(tenant.storage_limit, 107_374_182_400);

    let usage = repo
        .billing_usage("billing_tenant")
        .await
        .expect("billing usage query succeeds");
    assert_eq!(usage.projects, 2);
    assert_eq!(usage.memories, 3);
    assert_eq!(usage.users, 2);
    assert_eq!(usage.storage, 0);

    let recent = repo
        .list_recent_invoices("billing_tenant", 1)
        .await
        .expect("recent invoice query succeeds");
    assert_eq!(recent.len(), 1);
    assert_eq!(recent[0].id, "billing_invoice_new");

    let upgraded = repo
        .update_tenant_plan("billing_owner_tenant", "enterprise", 1_099_511_627_776)
        .await
        .expect("plan update succeeds")
        .expect("tenant exists");
    assert_eq!(upgraded.plan, "enterprise");
    assert_eq!(upgraded.storage_limit, 1_099_511_627_776);

    let missing_upgrade = repo
        .update_tenant_plan("billing_missing_tenant", "pro", 107_374_182_400)
        .await
        .expect("missing plan update query succeeds");
    assert!(missing_upgrade.is_none());
}

async fn clean_billing_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM invoices WHERE id LIKE 'billing_invoice_%'")
        .execute(pool)
        .await
        .expect("clean billing invoices");
    sqlx::query("DELETE FROM memories WHERE id LIKE 'billing_memory_%'")
        .execute(pool)
        .await
        .expect("clean billing memories");
    sqlx::query("DELETE FROM user_projects WHERE project_id LIKE 'billing_project_%'")
        .execute(pool)
        .await
        .expect("clean billing user projects");
    sqlx::query("DELETE FROM projects WHERE id LIKE 'billing_project_%'")
        .execute(pool)
        .await
        .expect("clean billing projects");
    sqlx::query("DELETE FROM user_tenants WHERE id LIKE 'billing_user_tenant_%'")
        .execute(pool)
        .await
        .expect("clean billing user tenants");
    sqlx::query("DELETE FROM tenants WHERE id LIKE 'billing_%'")
        .execute(pool)
        .await
        .expect("clean billing tenants");
}

async fn seed_billing_tenant(pool: &PgPool, tenant_id: &str, user_id: &str, role: &str) {
    sqlx::query(
        "INSERT INTO tenants (id, name, plan, max_storage) VALUES ($1, $2, $3, $4) \
         ON CONFLICT (id) DO UPDATE SET \
            name = EXCLUDED.name, \
            plan = EXCLUDED.plan, \
            max_storage = EXCLUDED.max_storage",
    )
    .bind(tenant_id)
    .bind(format!("Tenant {tenant_id}"))
    .bind("pro")
    .bind(107_374_182_400_i64)
    .execute(pool)
    .await
    .expect("seed billing tenant");

    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) VALUES ($1, $2, $3, $4) \
         ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role",
    )
    .bind(format!("billing_user_tenant_{tenant_id}"))
    .bind(user_id)
    .bind(tenant_id)
    .bind(role)
    .execute(pool)
    .await
    .expect("seed billing tenant membership");
}

async fn seed_billing_project(pool: &PgPool, project_id: &str, tenant_id: &str, owner_id: &str) {
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id, is_public) \
         VALUES ($1, $2, $3, $4, false) \
         ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id",
    )
    .bind(project_id)
    .bind(tenant_id)
    .bind(format!("Project {project_id}"))
    .bind(owner_id)
    .execute(pool)
    .await
    .expect("seed billing project");
}

async fn seed_billing_memory(pool: &PgPool, memory_id: &str, project_id: &str) {
    sqlx::query(
        "INSERT INTO memories (id, project_id, title, content, author_id) \
         VALUES ($1, $2, $3, $4, $5) \
         ON CONFLICT (id) DO UPDATE SET project_id = EXCLUDED.project_id",
    )
    .bind(memory_id)
    .bind(project_id)
    .bind(format!("Memory {memory_id}"))
    .bind("Billing memory")
    .bind("notification_user")
    .execute(pool)
    .await
    .expect("seed billing memory");
}

async fn seed_billing_project_user(pool: &PgPool, project_id: &str, user_id: &str) {
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) \
         VALUES ($1, $2, 'member') \
         ON CONFLICT (user_id, project_id) DO UPDATE SET role = EXCLUDED.role",
    )
    .bind(user_id)
    .bind(project_id)
    .execute(pool)
    .await
    .expect("seed billing project user");
}

async fn seed_invoice(pool: &PgPool, id: &str, tenant_id: &str, created_at: DateTime<Utc>) {
    sqlx::query(
        "INSERT INTO invoices \
         (id, tenant_id, amount, currency, status, period_start, period_end, created_at, paid_at, invoice_url) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) \
         ON CONFLICT (id) DO UPDATE SET \
            tenant_id = EXCLUDED.tenant_id, \
            created_at = EXCLUDED.created_at",
    )
    .bind(id)
    .bind(tenant_id)
    .bind(1999_i32)
    .bind("USD")
    .bind("paid")
    .bind(ts(2026, 1, 1, 0, 0, 0))
    .bind(ts(2026, 2, 1, 0, 0, 0))
    .bind(created_at)
    .bind(ts(2026, 1, 6, 0, 0, 0))
    .bind("https://billing.example.test/invoices/billing-invoice")
    .execute(pool)
    .await
    .expect("seed invoice");
}
