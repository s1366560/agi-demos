use super::support::*;

#[tokio::test]
async fn tenant_event_log_types_are_distinct_sorted_and_tenant_scoped() {
    let Some(pool) =
        pool_or_skip("tenant_event_log_types_are_distinct_sorted_and_tenant_scoped").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_event_log_rows(&pool).await;
    seed_tenant_event(
        &pool,
        "event_log_1",
        "event_logs_tenant",
        "workspace.message.created",
    )
    .await;
    seed_tenant_event(&pool, "event_log_2", "event_logs_tenant", "gene.installed").await;
    seed_tenant_event(&pool, "event_log_3", "event_logs_tenant", "gene.installed").await;
    seed_tenant_event(
        &pool,
        "event_log_other",
        "event_logs_other_tenant",
        "other.visible",
    )
    .await;

    let repo = PgEventLogRepository::new(pool.clone());
    let event_types = repo
        .list_event_types("event_logs_tenant")
        .await
        .expect("event types query succeeds");

    assert_eq!(
        event_types,
        vec![
            "gene.installed".to_string(),
            "workspace.message.created".to_string()
        ]
    );
}

#[tokio::test]
async fn tenant_event_logs_list_filters_counts_and_paginates() {
    let Some(pool) = pool_or_skip("tenant_event_logs_list_filters_counts_and_paginates").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_event_log_rows(&pool).await;
    seed_tenant_event_at(
        &pool,
        "event_log_list_1",
        "event_logs_tenant",
        "gene.installed",
        ts(2026, 1, 1, 0, 0, 0),
    )
    .await;
    seed_tenant_event_at(
        &pool,
        "event_log_list_2",
        "event_logs_tenant",
        "workspace.message.created",
        ts(2026, 1, 2, 0, 0, 0),
    )
    .await;
    seed_tenant_event_at(
        &pool,
        "event_log_list_3",
        "event_logs_tenant",
        "gene.installed",
        ts(2026, 1, 3, 0, 0, 0),
    )
    .await;
    seed_tenant_event_at(
        &pool,
        "event_log_list_other",
        "event_logs_other_tenant",
        "gene.installed",
        ts(2026, 1, 4, 0, 0, 0),
    )
    .await;

    let repo = PgEventLogRepository::new(pool.clone());
    let (records, total) = repo
        .list_events(TenantEventLogListQuery {
            tenant_id: "event_logs_tenant",
            event_type: Some("gene.installed"),
            date_from: Some(ts(2026, 1, 1, 12, 0, 0)),
            date_to: Some(ts(2026, 1, 3, 12, 0, 0)),
            page: 1,
            page_size: 1,
        })
        .await
        .expect("event list query succeeds");

    assert_eq!(total, 1);
    assert_eq!(records.len(), 1);
    assert_eq!(records[0].id, "event_log_list_3");
    assert_eq!(records[0].event_type, "gene.installed");
    assert_eq!(records[0].tenant_id, "event_logs_tenant");
}

async fn clean_event_log_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM tenant_event_logs WHERE id LIKE 'event_log_%'")
        .execute(pool)
        .await
        .expect("clean event log rows");
}

async fn seed_tenant_event(pool: &PgPool, id: &str, tenant_id: &str, event_type: &str) {
    seed_tenant_event_at(pool, id, tenant_id, event_type, ts(2026, 1, 1, 0, 0, 0)).await;
}

async fn seed_tenant_event_at(
    pool: &PgPool,
    id: &str,
    tenant_id: &str,
    event_type: &str,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO tenant_event_logs \
         (id, tenant_id, event_type, message, source, metadata, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7) \
         ON CONFLICT (id) DO UPDATE SET \
            tenant_id = EXCLUDED.tenant_id, \
            event_type = EXCLUDED.event_type, \
            created_at = EXCLUDED.created_at",
    )
    .bind(id)
    .bind(tenant_id)
    .bind(event_type)
    .bind("event message")
    .bind("event-test")
    .bind(json!({"test": true}))
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed tenant event");
}
