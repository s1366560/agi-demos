use super::support::*;

#[tokio::test]
async fn notifications_list_is_user_scoped_unread_filtered_and_limited() {
    let Some(pool) =
        pool_or_skip("notifications_list_is_user_scoped_unread_filtered_and_limited").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_notification_rows(&pool).await;
    seed_notification_user(&pool, "notification_user", false).await;
    seed_notification_user(&pool, "notification_admin", true).await;
    seed_notification(
        &pool,
        "notification_1",
        "notification_user",
        false,
        ts(2026, 1, 3, 0, 0, 0),
        None,
    )
    .await;
    seed_notification(
        &pool,
        "notification_2",
        "notification_user",
        true,
        ts(2026, 1, 2, 0, 0, 0),
        None,
    )
    .await;
    seed_notification(
        &pool,
        "notification_3",
        "notification_other_user",
        false,
        ts(2026, 1, 4, 0, 0, 0),
        None,
    )
    .await;

    let repo = PgNotificationRepository::new(pool.clone());
    let notifications = repo
        .list_notifications(agistack_adapters_postgres::NotificationListQuery {
            user_id: "notification_user",
            unread_only: true,
            limit: 10,
        })
        .await
        .expect("notification list query succeeds");

    assert_eq!(notifications.len(), 1);
    assert_eq!(notifications[0].id, "notification_1");
    assert_eq!(notifications[0].user_id, "notification_user");
    assert!(!notifications[0].is_read);

    assert!(repo
        .mark_read("notification_user", "notification_1")
        .await
        .expect("mark notification read succeeds"));
    assert!(!repo
        .mark_read("notification_other_user", "notification_1")
        .await
        .expect("other user cannot mark notification"));

    let count = repo
        .mark_all_read("notification_user")
        .await
        .expect("mark all notification read succeeds");
    assert_eq!(count, 0);

    assert!(!repo
        .delete_notification("notification_other_user", "notification_1")
        .await
        .expect("other user cannot delete notification"));
    assert!(repo
        .delete_notification("notification_user", "notification_1")
        .await
        .expect("delete notification succeeds"));

    let created_id = repo
        .create_notification(agistack_adapters_postgres::CreateNotification {
            id: "notification_created",
            user_id: "notification_user",
            notification_type: "general",
            title: "Created notice",
            message: "Created through Rust",
            data_json: &json!({"source": "rust"}),
            action_url: Some("/created"),
            expires_at: Some(ts(2026, 1, 5, 0, 0, 0)),
        })
        .await
        .expect("create notification succeeds");
    assert_eq!(created_id, "notification_created");
    let created = repo
        .list_notifications(agistack_adapters_postgres::NotificationListQuery {
            user_id: "notification_user",
            unread_only: false,
            limit: 10,
        })
        .await
        .expect("notification list query succeeds")
        .into_iter()
        .find(|notification| notification.id == "notification_created")
        .expect("created notification is visible to target user");
    assert_eq!(created.title, "Created notice");
    assert_eq!(created.action_url.as_deref(), Some("/created"));

    assert!(!repo
        .user_is_superuser("notification_user")
        .await
        .expect("superuser query succeeds"));
    assert!(repo
        .user_is_superuser("notification_admin")
        .await
        .expect("superuser query succeeds"));
}

async fn clean_notification_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM notifications WHERE id LIKE 'notification_%'")
        .execute(pool)
        .await
        .expect("clean notification rows");
    sqlx::query("DELETE FROM users WHERE id LIKE 'notification_%'")
        .execute(pool)
        .await
        .expect("clean notification users");
}

async fn seed_notification_user(pool: &PgPool, user_id: &str, is_superuser: bool) {
    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3) \
         ON CONFLICT (id) DO UPDATE SET is_superuser = EXCLUDED.is_superuser",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind(is_superuser)
    .execute(pool)
    .await
    .expect("seed notification user");
}

async fn seed_notification(
    pool: &PgPool,
    id: &str,
    user_id: &str,
    is_read: bool,
    created_at: DateTime<Utc>,
    expires_at: Option<DateTime<Utc>>,
) {
    sqlx::query(
        "INSERT INTO notifications \
         (id, user_id, type, title, message, data, is_read, action_url, created_at, expires_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) \
         ON CONFLICT (id) DO UPDATE SET \
            user_id = EXCLUDED.user_id, \
            is_read = EXCLUDED.is_read, \
            created_at = EXCLUDED.created_at, \
            expires_at = EXCLUDED.expires_at",
    )
    .bind(id)
    .bind(user_id)
    .bind("system")
    .bind("System notice")
    .bind("A system event happened")
    .bind(json!({"severity": "info"}))
    .bind(is_read)
    .bind("/settings")
    .bind(created_at)
    .bind(expires_at)
    .execute(pool)
    .await
    .expect("seed notification");
}
