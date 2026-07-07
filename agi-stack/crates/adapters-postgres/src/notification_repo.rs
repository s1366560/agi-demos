//! Adapter over Python-owned `notifications`.
//!
//! Rust owns the exact current-user list/mutation API-v1 slice and keeps
//! expiration filtering in the server layer so the SQL `LIMIT` semantics match
//! Python.

use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const NOTIFICATION_COLS: &str =
    "id, user_id, type, title, message, data, is_read, action_url, created_at, expires_at";

#[derive(Debug, Clone)]
pub struct NotificationRecord {
    pub id: String,
    pub user_id: String,
    pub notification_type: String,
    pub title: String,
    pub message: String,
    pub data_json: Option<serde_json::Value>,
    pub is_read: bool,
    pub action_url: Option<String>,
    pub created_at: DateTime<Utc>,
    pub expires_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy)]
pub struct NotificationListQuery<'a> {
    pub user_id: &'a str,
    pub unread_only: bool,
    pub limit: i64,
}

#[derive(Debug, Clone, Copy)]
pub struct CreateNotification<'a> {
    pub id: &'a str,
    pub user_id: &'a str,
    pub notification_type: &'a str,
    pub title: &'a str,
    pub message: &'a str,
    pub data_json: &'a serde_json::Value,
    pub action_url: Option<&'a str>,
    pub expires_at: Option<DateTime<Utc>>,
}

pub struct PgNotificationRepository {
    pool: PgPool,
}

impl PgNotificationRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_notifications(
        &self,
        query: NotificationListQuery<'_>,
    ) -> CoreResult<Vec<NotificationRecord>> {
        let sql = format!(
            "SELECT {NOTIFICATION_COLS} \
             FROM notifications \
             WHERE user_id = $1 \
               AND ($2::bool IS FALSE OR is_read IS FALSE) \
             ORDER BY created_at DESC \
             LIMIT $3"
        );
        let rows = sqlx::query(&sql)
            .bind(query.user_id)
            .bind(query.unread_only)
            .bind(query.limit)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list notifications: {e}")))?;

        rows.into_iter()
            .map(|row| {
                Ok(NotificationRecord {
                    id: row.try_get("id")?,
                    user_id: row.try_get("user_id")?,
                    notification_type: row.try_get("type")?,
                    title: row.try_get("title")?,
                    message: row.try_get("message")?,
                    data_json: row.try_get("data")?,
                    is_read: row.try_get("is_read")?,
                    action_url: row.try_get("action_url")?,
                    created_at: row.try_get("created_at")?,
                    expires_at: row.try_get("expires_at")?,
                })
            })
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read notification row: {e}")))
    }

    pub async fn user_is_superuser(&self, user_id: &str) -> CoreResult<bool> {
        sqlx::query_as::<_, (Option<bool>,)>("SELECT is_superuser FROM users WHERE id = $1")
            .bind(user_id)
            .fetch_optional(&self.pool)
            .await
            .map(|row| {
                row.and_then(|(is_superuser,)| is_superuser)
                    .unwrap_or(false)
            })
            .map_err(|e| CoreError::Storage(format!("read notification user superuser: {e}")))
    }

    pub async fn mark_read(&self, user_id: &str, notification_id: &str) -> CoreResult<bool> {
        let result =
            sqlx::query("UPDATE notifications SET is_read = TRUE WHERE id = $1 AND user_id = $2")
                .bind(notification_id)
                .bind(user_id)
                .execute(&self.pool)
                .await
                .map_err(|e| CoreError::Storage(format!("mark notification read: {e}")))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn mark_all_read(&self, user_id: &str) -> CoreResult<i64> {
        let result = sqlx::query(
            "UPDATE notifications SET is_read = TRUE \
             WHERE user_id = $1 AND is_read IS FALSE",
        )
        .bind(user_id)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("mark notifications read: {e}")))?;
        i64::try_from(result.rows_affected())
            .map_err(|e| CoreError::Storage(format!("notification read count overflow: {e}")))
    }

    pub async fn delete_notification(
        &self,
        user_id: &str,
        notification_id: &str,
    ) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM notifications WHERE id = $1 AND user_id = $2")
            .bind(notification_id)
            .bind(user_id)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("delete notification: {e}")))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn create_notification(&self, input: CreateNotification<'_>) -> CoreResult<String> {
        sqlx::query(
            "INSERT INTO notifications \
             (id, user_id, type, title, message, data, is_read, action_url, created_at, expires_at) \
             VALUES ($1, $2, $3, $4, $5, $6, FALSE, $7, now(), $8)",
        )
        .bind(input.id)
        .bind(input.user_id)
        .bind(input.notification_type)
        .bind(input.title)
        .bind(input.message)
        .bind(input.data_json)
        .bind(input.action_url)
        .bind(input.expires_at)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("create notification: {e}")))?;
        Ok(input.id.to_string())
    }
}
