use serde_json::Value;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::FromRow;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

#[derive(Debug, Clone, FromRow)]
pub struct ChannelConfigRecord {
    pub id: String,
    pub project_id: String,
    pub channel_type: String,
    pub name: String,
    pub enabled: bool,
    pub connection_mode: String,
    pub app_id: Option<String>,
    pub webhook_url: Option<String>,
    pub webhook_port: Option<i32>,
    pub webhook_path: Option<String>,
    pub domain: Option<String>,
    pub extra_settings: Option<Value>,
    pub dm_policy: String,
    pub group_policy: String,
    pub allow_from: Option<Value>,
    pub group_allow_from: Option<Value>,
    pub rate_limit_per_minute: i32,
    pub status: String,
    pub last_error: Option<String>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, FromRow)]
pub struct ChannelStatusRecord {
    pub config_id: String,
    pub project_id: String,
    pub channel_type: String,
    pub status: String,
    pub connected: bool,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, FromRow)]
pub struct ChannelOutboxRecord {
    pub id: String,
    pub channel_config_id: String,
    pub conversation_id: String,
    pub chat_id: String,
    pub status: String,
    pub attempt_count: i32,
    pub max_attempts: i32,
    pub sent_channel_message_id: Option<String>,
    pub last_error: Option<String>,
    pub next_retry_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, FromRow)]
pub struct ChannelSessionBindingRecord {
    pub id: String,
    pub channel_config_id: String,
    pub conversation_id: String,
    pub channel_type: String,
    pub chat_id: String,
    pub chat_type: String,
    pub thread_id: Option<String>,
    pub topic_id: Option<String>,
    pub session_key: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy)]
pub struct ChannelConfigListQuery<'a> {
    pub project_id: &'a str,
    pub channel_type: Option<&'a str>,
    pub enabled_only: bool,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone, Copy)]
pub struct ChannelOutboxListQuery<'a> {
    pub project_id: &'a str,
    pub status_filter: Option<&'a str>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone, Copy)]
pub struct ChannelPageQuery<'a> {
    pub project_id: &'a str,
    pub limit: i64,
    pub offset: i64,
}

pub struct PgChannelRepository {
    pool: PgPool,
}

impl PgChannelRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn user_has_project_access(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects WHERE user_id = $1 AND project_id = $2",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?
        .0;
        Ok(count > 0)
    }

    pub async fn user_is_project_admin(&self, user_id: &str, project_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects \
             WHERE user_id = $1 AND project_id = $2 AND role IN ('owner', 'admin')",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?
        .0;
        Ok(count > 0)
    }

    pub async fn list_configs(
        &self,
        query: ChannelConfigListQuery<'_>,
    ) -> CoreResult<Vec<ChannelConfigRecord>> {
        sqlx::query_as::<_, ChannelConfigRecord>(CHANNEL_CONFIG_SELECT_BY_PROJECT_SQL)
            .bind(query.project_id)
            .bind(query.channel_type)
            .bind(query.enabled_only)
            .bind(query.limit)
            .bind(query.offset)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn count_configs(
        &self,
        project_id: &str,
        channel_type: Option<&str>,
        enabled_only: bool,
    ) -> CoreResult<i64> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM channel_configs \
             WHERE project_id = $1 \
               AND ($2::text IS NULL OR channel_type = $2) \
               AND (NOT $3::bool OR enabled IS TRUE)",
        )
        .bind(project_id)
        .bind(channel_type)
        .bind(enabled_only)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))
        .map(|(count,)| count)
    }

    pub async fn get_config(&self, config_id: &str) -> CoreResult<Option<ChannelConfigRecord>> {
        sqlx::query_as::<_, ChannelConfigRecord>(CHANNEL_CONFIG_SELECT_BY_ID_SQL)
            .bind(config_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn get_status(&self, config_id: &str) -> CoreResult<Option<ChannelStatusRecord>> {
        sqlx::query_as::<_, ChannelStatusRecord>(
            "SELECT \
                id AS config_id, \
                project_id, \
                channel_type, \
                COALESCE(status, 'disconnected') AS status, \
                COALESCE(status, 'disconnected') = 'connected' AS connected, \
                last_error \
             FROM channel_configs \
             WHERE id = $1",
        )
        .bind(config_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn list_outbox(
        &self,
        query: ChannelOutboxListQuery<'_>,
    ) -> CoreResult<Vec<ChannelOutboxRecord>> {
        sqlx::query_as::<_, ChannelOutboxRecord>(
            "SELECT \
                id, channel_config_id, conversation_id, chat_id, status, attempt_count, \
                max_attempts, sent_channel_message_id, last_error, next_retry_at, \
                created_at, updated_at \
             FROM channel_outbox \
             WHERE project_id = $1 \
               AND ($2::text IS NULL OR status = $2) \
             ORDER BY created_at DESC \
             LIMIT $3 OFFSET $4",
        )
        .bind(query.project_id)
        .bind(query.status_filter)
        .bind(query.limit)
        .bind(query.offset)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn count_outbox(
        &self,
        project_id: &str,
        status_filter: Option<&str>,
    ) -> CoreResult<i64> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM channel_outbox \
             WHERE project_id = $1 \
               AND ($2::text IS NULL OR status = $2)",
        )
        .bind(project_id)
        .bind(status_filter)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))
        .map(|(count,)| count)
    }

    pub async fn list_session_bindings(
        &self,
        query: ChannelPageQuery<'_>,
    ) -> CoreResult<Vec<ChannelSessionBindingRecord>> {
        sqlx::query_as::<_, ChannelSessionBindingRecord>(
            "SELECT \
                id, channel_config_id, conversation_id, channel_type, chat_id, chat_type, \
                thread_id, topic_id, session_key, created_at, updated_at \
             FROM channel_session_bindings \
             WHERE project_id = $1 \
             ORDER BY created_at DESC \
             LIMIT $2 OFFSET $3",
        )
        .bind(query.project_id)
        .bind(query.limit)
        .bind(query.offset)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn count_session_bindings(&self, project_id: &str) -> CoreResult<i64> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM channel_session_bindings \
             WHERE project_id = $1",
        )
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))
        .map(|(count,)| count)
    }
}

const CHANNEL_CONFIG_SELECT_BY_PROJECT_SQL: &str = "\
    SELECT \
        id, project_id, channel_type, name, COALESCE(enabled, true) AS enabled, \
        COALESCE(connection_mode, 'websocket') AS connection_mode, app_id, webhook_url, \
        webhook_port, webhook_path, domain, extra_settings, COALESCE(dm_policy, 'open') AS dm_policy, \
        COALESCE(group_policy, 'open') AS group_policy, allow_from, group_allow_from, \
        COALESCE(rate_limit_per_minute, 60) AS rate_limit_per_minute, \
        COALESCE(status, 'disconnected') AS status, last_error, description, created_at, updated_at \
    FROM channel_configs \
    WHERE project_id = $1 \
      AND ($2::text IS NULL OR channel_type = $2) \
      AND (NOT $3::bool OR enabled IS TRUE) \
    ORDER BY created_at DESC, id DESC \
    LIMIT $4 OFFSET $5";

const CHANNEL_CONFIG_SELECT_BY_ID_SQL: &str = "\
    SELECT \
        id, project_id, channel_type, name, COALESCE(enabled, true) AS enabled, \
        COALESCE(connection_mode, 'websocket') AS connection_mode, app_id, webhook_url, \
        webhook_port, webhook_path, domain, extra_settings, COALESCE(dm_policy, 'open') AS dm_policy, \
        COALESCE(group_policy, 'open') AS group_policy, allow_from, group_allow_from, \
        COALESCE(rate_limit_per_minute, 60) AS rate_limit_per_minute, \
        COALESCE(status, 'disconnected') AS status, last_error, description, created_at, updated_at \
    FROM channel_configs \
    WHERE id = $1";

#[cfg(test)]
mod tests {
    use super::CHANNEL_CONFIG_SELECT_BY_ID_SQL;

    #[test]
    fn channel_config_column_list_documents_secret_exclusion() {
        assert!(CHANNEL_CONFIG_SELECT_BY_ID_SQL.contains("app_id"));
        assert!(!CHANNEL_CONFIG_SELECT_BY_ID_SQL.contains("app_secret"));
        assert!(!CHANNEL_CONFIG_SELECT_BY_ID_SQL.contains("encrypt_key"));
        assert!(!CHANNEL_CONFIG_SELECT_BY_ID_SQL.contains("verification_token"));
    }
}
