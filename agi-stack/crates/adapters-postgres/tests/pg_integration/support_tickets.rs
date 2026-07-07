use super::support::*;

#[tokio::test]
async fn support_tickets_are_user_scoped_filtered_counted_and_paged() {
    let Some(pool) =
        pool_or_skip("support_tickets_are_user_scoped_filtered_counted_and_paged").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_support_ticket_rows(&pool).await;
    seed_support_tenant(&pool, "support_tenant", "support_user", false).await;
    seed_support_ticket(
        &pool,
        "support_ticket_old",
        "support_tenant",
        "support_user",
        "open",
        ts(2026, 1, 1, 0, 0, 0),
    )
    .await;
    seed_support_ticket(
        &pool,
        "support_ticket_new",
        "support_tenant",
        "support_user",
        "open",
        ts(2026, 1, 2, 0, 0, 0),
    )
    .await;
    seed_support_ticket(
        &pool,
        "support_ticket_closed",
        "support_tenant",
        "support_user",
        "closed",
        ts(2026, 1, 3, 0, 0, 0),
    )
    .await;
    seed_support_ticket(
        &pool,
        "support_ticket_other_user",
        "support_tenant",
        "support_other_user",
        "open",
        ts(2026, 1, 4, 0, 0, 0),
    )
    .await;

    let repo = PgSupportRepository::new(pool.clone());
    assert!(repo
        .user_has_tenant_membership("support_user", "support_tenant")
        .await
        .expect("tenant access query succeeds"));
    assert!(!repo
        .user_is_superuser("support_user")
        .await
        .expect("superuser query succeeds"));

    let (tickets, total) = repo
        .list_tickets(agistack_adapters_postgres::SupportTicketListQuery {
            user_id: "support_user",
            tenant_id: Some("support_tenant"),
            status: Some("open"),
            limit: 1,
            offset: 0,
        })
        .await
        .expect("support ticket list succeeds");

    assert_eq!(total, 2);
    assert_eq!(tickets.len(), 1);
    assert_eq!(tickets[0].id, "support_ticket_new");
    assert_eq!(tickets[0].tenant_id.as_deref(), Some("support_tenant"));
    assert_eq!(tickets[0].user_id, "support_user");

    let ticket = repo
        .get_ticket("support_user", "support_ticket_new")
        .await
        .expect("support ticket detail query succeeds")
        .expect("support ticket belongs to user");
    assert_eq!(ticket.id, "support_ticket_new");

    let hidden = repo
        .get_ticket("support_user", "support_ticket_other_user")
        .await
        .expect("support ticket detail query succeeds");
    assert!(hidden.is_none());

    let created = repo
        .create_ticket(agistack_adapters_postgres::CreateSupportTicket {
            id: "support_ticket_created",
            tenant_id: Some("support_tenant"),
            user_id: "support_user",
            subject: "Created issue",
            message: "Created through Rust",
            priority: "medium",
        })
        .await
        .expect("support ticket create succeeds");
    assert_eq!(created.id, "support_ticket_created");
    assert_eq!(created.status, "open");
    assert_eq!(created.priority, "medium");
    assert!(created.resolved_at.is_none());

    let denied_update = repo
        .update_ticket(
            "support_other_user",
            "support_ticket_created",
            agistack_adapters_postgres::UpdateSupportTicket {
                subject: Some("Hidden update"),
                message: None,
                priority: None,
            },
        )
        .await
        .expect("support ticket update query succeeds");
    assert!(denied_update.is_none());

    let updated = repo
        .update_ticket(
            "support_user",
            "support_ticket_created",
            agistack_adapters_postgres::UpdateSupportTicket {
                subject: Some("Updated issue"),
                message: Some("Updated through Rust"),
                priority: Some("urgent"),
            },
        )
        .await
        .expect("support ticket update succeeds")
        .expect("current user's ticket is updated");
    assert_eq!(updated.subject, "Updated issue");
    assert_eq!(updated.message, "Updated through Rust");
    assert_eq!(updated.priority, "urgent");

    let denied_close = repo
        .close_ticket("support_other_user", "support_ticket_created")
        .await
        .expect("support ticket close query succeeds");
    assert!(denied_close.is_none());

    let closed = repo
        .close_ticket("support_user", "support_ticket_created")
        .await
        .expect("support ticket close succeeds")
        .expect("current user's ticket is closed");
    assert_eq!(closed.id, "support_ticket_created");
    assert_eq!(closed.status, "closed");
}

async fn clean_support_ticket_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM support_tickets WHERE id LIKE 'support_ticket_%'")
        .execute(pool)
        .await
        .expect("clean support tickets");
    sqlx::query("DELETE FROM user_tenants WHERE id LIKE 'support_user_tenant_%'")
        .execute(pool)
        .await
        .expect("clean support tenant memberships");
    sqlx::query("DELETE FROM users WHERE id LIKE 'support_%'")
        .execute(pool)
        .await
        .expect("clean support users");
    sqlx::query("DELETE FROM tenants WHERE id LIKE 'support_%'")
        .execute(pool)
        .await
        .expect("clean support tenants");
}

async fn seed_support_tenant(pool: &PgPool, tenant_id: &str, user_id: &str, is_superuser: bool) {
    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3) \
         ON CONFLICT (id) DO UPDATE SET is_superuser = EXCLUDED.is_superuser",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind(is_superuser)
    .execute(pool)
    .await
    .expect("seed support user");

    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ($1, $2) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(tenant_id)
    .bind(format!("Tenant {tenant_id}"))
    .execute(pool)
    .await
    .expect("seed support tenant");

    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) VALUES ($1, $2, $3, $4) \
         ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role",
    )
    .bind(format!("support_user_tenant_{tenant_id}_{user_id}"))
    .bind(user_id)
    .bind(tenant_id)
    .bind("member")
    .execute(pool)
    .await
    .expect("seed support tenant membership");
}

async fn seed_support_ticket(
    pool: &PgPool,
    id: &str,
    tenant_id: &str,
    user_id: &str,
    status: &str,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO support_tickets \
         (id, tenant_id, user_id, subject, message, priority, status, created_at, updated_at, resolved_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL) \
         ON CONFLICT (id) DO UPDATE SET \
            tenant_id = EXCLUDED.tenant_id, \
            user_id = EXCLUDED.user_id, \
            status = EXCLUDED.status, \
            created_at = EXCLUDED.created_at",
    )
    .bind(id)
    .bind(tenant_id)
    .bind(user_id)
    .bind("Cannot access workspace")
    .bind("Workspace returns a permission error")
    .bind("high")
    .bind(status)
    .bind(created_at)
    .bind(ts(2026, 1, 5, 0, 0, 0))
    .execute(pool)
    .await
    .expect("seed support ticket");
}
