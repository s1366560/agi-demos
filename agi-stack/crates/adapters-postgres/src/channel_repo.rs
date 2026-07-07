use serde_json::Value;
use sqlx::types::{
    chrono::{DateTime, Utc},
    Json,
};
use sqlx::{FromRow, Postgres, Transaction};
use std::collections::BTreeMap;

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

#[derive(Debug, Clone, FromRow, PartialEq, Eq)]
pub struct ChannelWebhookSecretRecord {
    pub config_id: String,
    pub project_id: String,
    pub channel_type: String,
    pub enabled: bool,
    pub connection_mode: String,
    pub domain: Option<String>,
    pub encrypt_key: Option<String>,
    pub verification_token: Option<String>,
}

#[derive(Debug, Clone, FromRow)]
pub struct ChannelOutboxRecord {
    pub id: String,
    pub project_id: String,
    pub channel_config_id: String,
    pub channel_type: Option<String>,
    pub webhook_url: Option<String>,
    pub domain: Option<String>,
    pub conversation_id: String,
    pub chat_id: String,
    pub content_text: String,
    pub status: String,
    pub attempt_count: i32,
    pub max_attempts: i32,
    pub sent_channel_message_id: Option<String>,
    pub last_error: Option<String>,
    pub next_retry_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, FromRow, PartialEq)]
pub struct ChannelWebhookEventRecord {
    pub id: String,
    pub project_id: String,
    pub channel_config_id: String,
    pub channel_type: String,
    pub idempotency_key: String,
    pub headers_json: Value,
    pub raw_event_json: Value,
    pub normalized_event_json: Value,
    pub status: String,
    pub route_error: Option<String>,
    pub route_session_key: Option<String>,
    pub route_binding_id: Option<String>,
    pub route_conversation_id: Option<String>,
    pub received_at: DateTime<Utc>,
    pub routed_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ChannelWebhookEventInsertRecord {
    pub id: String,
    pub channel_config_id: String,
    pub idempotency_key: String,
    pub headers_json: Value,
    pub raw_event_json: Value,
    pub normalized_event_json: Value,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ChannelWebhookIngressRecord {
    pub event: ChannelWebhookEventRecord,
    pub inserted: bool,
}

#[derive(Debug, Clone)]
pub struct ChannelWebhookRouteRecord {
    pub event: ChannelWebhookEventRecord,
    pub session_binding: Option<ChannelSessionBindingRecord>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ChannelWebhookSessionCreateRecord {
    pub binding_id: String,
    pub conversation_id: String,
    pub session_key: String,
    pub chat_id: String,
    pub chat_type: String,
    pub thread_id: Option<String>,
    pub topic_id: Option<String>,
    pub conversation_title: String,
    pub metadata_json: Value,
}

#[derive(Debug, Clone, FromRow, PartialEq)]
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChannelObservabilitySummaryRecord {
    pub project_id: String,
    pub session_bindings_total: i64,
    pub outbox_total: i64,
    pub outbox_by_status: BTreeMap<String, i64>,
    pub latest_delivery_error: Option<String>,
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

#[derive(Debug, Clone, FromRow)]
struct ChannelConversationOwnerRecord {
    tenant_id: String,
    user_id: String,
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

    pub async fn update_connection_status(
        &self,
        config_id: &str,
        status: &str,
        last_error: Option<&str>,
    ) -> CoreResult<Option<ChannelStatusRecord>> {
        sqlx::query_as::<_, ChannelStatusRecord>(
            "UPDATE channel_configs \
             SET status = $2, last_error = $3, updated_at = now() \
             WHERE id = $1 \
             RETURNING \
                id AS config_id, \
                project_id, \
                channel_type, \
                COALESCE(status, 'disconnected') AS status, \
                COALESCE(status, 'disconnected') = 'connected' AS connected, \
                last_error",
        )
        .bind(config_id)
        .bind(status)
        .bind(last_error)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn get_webhook_secrets(
        &self,
        config_id: &str,
    ) -> CoreResult<Option<ChannelWebhookSecretRecord>> {
        sqlx::query_as::<_, ChannelWebhookSecretRecord>(
            "SELECT \
                id AS config_id, \
                project_id, \
                channel_type, \
                COALESCE(enabled, true) AS enabled, \
                COALESCE(connection_mode, 'websocket') AS connection_mode, \
                domain, \
                encrypt_key, \
                verification_token \
             FROM channel_configs \
             WHERE id = $1",
        )
        .bind(config_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn record_webhook_event(
        &self,
        event: &ChannelWebhookEventInsertRecord,
    ) -> CoreResult<Option<ChannelWebhookIngressRecord>> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let insert_sql = format!(
            "WITH config AS (\
                SELECT id, project_id, channel_type \
                FROM channel_configs \
                WHERE id = $2\
             ) \
             INSERT INTO agistack_channel_webhook_events \
                (id, project_id, channel_config_id, channel_type, idempotency_key, \
                 headers_json, raw_event_json, normalized_event_json, status, received_at) \
             SELECT $1, project_id, id, channel_type, $3, $4, $5, $6, 'received', now() \
             FROM config \
             ON CONFLICT (channel_config_id, idempotency_key) DO NOTHING \
             RETURNING {CHANNEL_WEBHOOK_EVENT_SELECT_COLS}"
        );
        let inserted = sqlx::query_as::<_, ChannelWebhookEventRecord>(&insert_sql)
            .bind(&event.id)
            .bind(&event.channel_config_id)
            .bind(&event.idempotency_key)
            .bind(&event.headers_json)
            .bind(&event.raw_event_json)
            .bind(&event.normalized_event_json)
            .fetch_optional(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        if let Some(event) = inserted {
            tx.commit()
                .await
                .map_err(|e| CoreError::Storage(e.to_string()))?;
            return Ok(Some(ChannelWebhookIngressRecord {
                event,
                inserted: true,
            }));
        }

        let select_sql = format!(
            "SELECT {CHANNEL_WEBHOOK_EVENT_SELECT_COLS} \
             FROM agistack_channel_webhook_events \
             WHERE channel_config_id = $1 AND idempotency_key = $2"
        );
        let existing = sqlx::query_as::<_, ChannelWebhookEventRecord>(&select_sql)
            .bind(&event.channel_config_id)
            .bind(&event.idempotency_key)
            .fetch_optional(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(existing.map(|event| ChannelWebhookIngressRecord {
            event,
            inserted: false,
        }))
    }

    pub async fn route_webhook_event_to_session_binding(
        &self,
        event_id: &str,
        session_key: Option<&str>,
        route_error: Option<&str>,
    ) -> CoreResult<Option<ChannelWebhookRouteRecord>> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let select_event_sql = format!(
            "SELECT {CHANNEL_WEBHOOK_EVENT_SELECT_COLS} \
             FROM agistack_channel_webhook_events \
             WHERE id = $1 \
             FOR UPDATE"
        );
        let Some(event) = sqlx::query_as::<_, ChannelWebhookEventRecord>(&select_event_sql)
            .bind(event_id)
            .fetch_optional(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?
        else {
            tx.commit()
                .await
                .map_err(|e| CoreError::Storage(e.to_string()))?;
            return Ok(None);
        };

        let session_binding = if let Some(session_key) = session_key {
            sqlx::query_as::<_, ChannelSessionBindingRecord>(
                "SELECT \
                    id, channel_config_id, conversation_id, channel_type, chat_id, chat_type, \
                    thread_id, topic_id, session_key, created_at, updated_at \
                 FROM channel_session_bindings \
                 WHERE project_id = $1 \
                   AND channel_config_id = $2 \
                   AND session_key = $3 \
                 LIMIT 1",
            )
            .bind(&event.project_id)
            .bind(&event.channel_config_id)
            .bind(session_key)
            .fetch_optional(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?
        } else {
            None
        };

        let status = if session_binding.is_some() {
            "routed"
        } else {
            "unbound"
        };
        let resolved_error = if session_binding.is_some() {
            None
        } else {
            Some(
                route_error
                    .unwrap_or("channel session binding not found")
                    .to_string(),
            )
        };
        let route_session_key = session_key.map(str::to_string);
        let route_binding_id = session_binding.as_ref().map(|binding| binding.id.as_str());
        let route_conversation_id = session_binding
            .as_ref()
            .map(|binding| binding.conversation_id.as_str());
        let update_sql = format!(
            "UPDATE agistack_channel_webhook_events \
             SET status = $2, \
                 route_error = $3, \
                 route_session_key = $4, \
                 route_binding_id = $5, \
                 route_conversation_id = $6, \
                 routed_at = now() \
             WHERE id = $1 \
             RETURNING {CHANNEL_WEBHOOK_EVENT_SELECT_COLS}"
        );
        let event = sqlx::query_as::<_, ChannelWebhookEventRecord>(&update_sql)
            .bind(event_id)
            .bind(status)
            .bind(resolved_error.as_deref())
            .bind(route_session_key.as_deref())
            .bind(route_binding_id)
            .bind(route_conversation_id)
            .fetch_one(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(Some(ChannelWebhookRouteRecord {
            event,
            session_binding,
        }))
    }

    pub async fn route_webhook_event_to_session_binding_or_create(
        &self,
        event_id: &str,
        route: Option<&ChannelWebhookSessionCreateRecord>,
        route_error: Option<&str>,
    ) -> CoreResult<Option<ChannelWebhookRouteRecord>> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let select_event_sql = format!(
            "SELECT {CHANNEL_WEBHOOK_EVENT_SELECT_COLS} \
             FROM agistack_channel_webhook_events \
             WHERE id = $1 \
             FOR UPDATE"
        );
        let Some(event) = sqlx::query_as::<_, ChannelWebhookEventRecord>(&select_event_sql)
            .bind(event_id)
            .fetch_optional(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?
        else {
            tx.commit()
                .await
                .map_err(|e| CoreError::Storage(e.to_string()))?;
            return Ok(None);
        };

        let session_binding = match route {
            Some(route) => {
                let existing = select_channel_session_binding(
                    &mut tx,
                    &event.project_id,
                    &event.channel_config_id,
                    &route.session_key,
                )
                .await?;
                match existing {
                    Some(binding) => Some(binding),
                    None => {
                        create_channel_session_binding_for_webhook_event(&mut tx, &event, route)
                            .await?
                    }
                }
            }
            None => None,
        };

        let status = if session_binding.is_some() {
            "routed"
        } else {
            "unbound"
        };
        let resolved_error = if session_binding.is_some() {
            None
        } else {
            Some(
                route_error
                    .unwrap_or("channel session binding not found")
                    .to_string(),
            )
        };
        let route_session_key = route.map(|route| route.session_key.as_str());
        let route_binding_id = session_binding.as_ref().map(|binding| binding.id.as_str());
        let route_conversation_id = session_binding
            .as_ref()
            .map(|binding| binding.conversation_id.as_str());
        let update_sql = format!(
            "UPDATE agistack_channel_webhook_events \
             SET status = $2, \
                 route_error = $3, \
                 route_session_key = $4, \
                 route_binding_id = $5, \
                 route_conversation_id = $6, \
                 routed_at = now() \
             WHERE id = $1 \
             RETURNING {CHANNEL_WEBHOOK_EVENT_SELECT_COLS}"
        );
        let event = sqlx::query_as::<_, ChannelWebhookEventRecord>(&update_sql)
            .bind(event_id)
            .bind(status)
            .bind(resolved_error.as_deref())
            .bind(route_session_key)
            .bind(route_binding_id)
            .bind(route_conversation_id)
            .fetch_one(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(Some(ChannelWebhookRouteRecord {
            event,
            session_binding,
        }))
    }

    pub async fn list_outbox(
        &self,
        query: ChannelOutboxListQuery<'_>,
    ) -> CoreResult<Vec<ChannelOutboxRecord>> {
        let sql = format!(
            "SELECT {CHANNEL_OUTBOX_SELECT_COLS} \
             FROM channel_outbox \
             WHERE project_id = $1 \
               AND ($2::text IS NULL OR status = $2) \
             ORDER BY created_at DESC \
             LIMIT $3 OFFSET $4"
        );
        sqlx::query_as::<_, ChannelOutboxRecord>(&sql)
            .bind(query.project_id)
            .bind(query.status_filter)
            .bind(query.limit)
            .bind(query.offset)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn claim_due_outbox(
        &self,
        worker_id: &str,
        lease_seconds: i64,
        limit: i64,
    ) -> CoreResult<Vec<ChannelOutboxRecord>> {
        let lease_seconds = i32::try_from(lease_seconds.max(1)).unwrap_or(i32::MAX);
        let limit = limit.clamp(1, 100);
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let sql = "\
            WITH due AS (\
                SELECT o.id \
                FROM channel_outbox o \
                JOIN channel_configs c ON c.id = o.channel_config_id \
                LEFT JOIN agistack_channel_outbox_leases l \
                  ON l.outbox_id = o.id AND l.lease_expires_at > now() \
                WHERE o.status IN ('pending', 'failed') \
                  AND COALESCE(c.enabled, true) IS TRUE \
                  AND (o.next_retry_at IS NULL OR o.next_retry_at <= now()) \
                  AND o.attempt_count < o.max_attempts \
                  AND l.outbox_id IS NULL \
                ORDER BY COALESCE(o.next_retry_at, o.created_at), o.created_at, o.id \
                LIMIT $1 \
                FOR UPDATE OF o SKIP LOCKED\
             ), leased AS (\
                INSERT INTO agistack_channel_outbox_leases \
                    (outbox_id, lease_owner, lease_expires_at, created_at, updated_at) \
                SELECT id, $2, now() + ($3 * interval '1 second'), now(), now() \
                FROM due \
                ON CONFLICT (outbox_id) DO UPDATE \
                    SET lease_owner = EXCLUDED.lease_owner, \
                        lease_expires_at = EXCLUDED.lease_expires_at, \
                        updated_at = now() \
                WHERE agistack_channel_outbox_leases.lease_expires_at <= now() \
                RETURNING outbox_id\
             ), updated AS (\
                UPDATE channel_outbox o \
                SET attempt_count = o.attempt_count + 1, \
                    last_error = NULL, \
                    updated_at = now() \
                FROM leased \
                WHERE o.id = leased.outbox_id \
                RETURNING o.id, o.project_id, o.channel_config_id, o.conversation_id, \
                    o.chat_id, o.content_text, o.status, o.attempt_count, o.max_attempts, \
                    o.sent_channel_message_id, o.last_error, o.next_retry_at, o.created_at, \
                    o.updated_at\
             ) \
             SELECT updated.id, updated.project_id, updated.channel_config_id, \
                    c.channel_type, c.webhook_url, c.domain, updated.conversation_id, \
                    updated.chat_id, updated.content_text, updated.status, \
                    updated.attempt_count, updated.max_attempts, \
                    updated.sent_channel_message_id, updated.last_error, \
                    updated.next_retry_at, updated.created_at, updated.updated_at \
             FROM updated \
             JOIN channel_configs c ON c.id = updated.channel_config_id \
             ORDER BY updated.created_at ASC, updated.id ASC";
        let rows = sqlx::query_as::<_, ChannelOutboxRecord>(sql)
            .bind(limit)
            .bind(worker_id)
            .bind(lease_seconds)
            .fetch_all(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(rows)
    }

    pub async fn mark_outbox_sent(
        &self,
        outbox_id: &str,
        worker_id: &str,
        sent_channel_message_id: &str,
    ) -> CoreResult<Option<ChannelOutboxRecord>> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let sql = format!(
            "UPDATE channel_outbox o \
             SET status = 'sent', \
                 sent_channel_message_id = $3, \
                 last_error = NULL, \
                 next_retry_at = NULL, \
                 updated_at = now() \
             WHERE o.id = $1 \
               AND EXISTS (\
                    SELECT 1 \
                    FROM agistack_channel_outbox_leases l \
                    WHERE l.outbox_id = o.id \
                      AND l.lease_owner = $2 \
                      AND l.lease_expires_at > now()\
               ) \
             RETURNING {CHANNEL_OUTBOX_RETURNING_COLS}"
        );
        let row = sqlx::query_as::<_, ChannelOutboxRecord>(&sql)
            .bind(outbox_id)
            .bind(worker_id)
            .bind(sent_channel_message_id)
            .fetch_optional(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        if row.is_some() {
            delete_channel_outbox_lease(&mut tx, outbox_id).await?;
        }
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row)
    }

    pub async fn mark_outbox_failed(
        &self,
        outbox_id: &str,
        worker_id: &str,
        error: &str,
        retry_after_seconds: i64,
    ) -> CoreResult<Option<ChannelOutboxRecord>> {
        let retry_after_seconds = i32::try_from(retry_after_seconds.max(0)).unwrap_or(i32::MAX);
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let sql = format!(
            "UPDATE channel_outbox o \
             SET status = CASE \
                    WHEN o.attempt_count >= o.max_attempts THEN 'dead_letter' \
                    ELSE 'failed' \
                 END, \
                 last_error = $3, \
                 next_retry_at = CASE \
                    WHEN o.attempt_count >= o.max_attempts THEN NULL \
                    ELSE now() + ($4 * interval '1 second') \
                 END, \
                 updated_at = now() \
             WHERE o.id = $1 \
               AND EXISTS (\
                    SELECT 1 \
                    FROM agistack_channel_outbox_leases l \
                    WHERE l.outbox_id = o.id \
                      AND l.lease_owner = $2 \
                      AND l.lease_expires_at > now()\
               ) \
             RETURNING {CHANNEL_OUTBOX_RETURNING_COLS}"
        );
        let row = sqlx::query_as::<_, ChannelOutboxRecord>(&sql)
            .bind(outbox_id)
            .bind(worker_id)
            .bind(error)
            .bind(retry_after_seconds)
            .fetch_optional(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        if row.is_some() {
            delete_channel_outbox_lease(&mut tx, outbox_id).await?;
        }
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row)
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

    pub async fn observability_summary(
        &self,
        project_id: &str,
    ) -> CoreResult<ChannelObservabilitySummaryRecord> {
        let session_bindings_total = self.count_session_bindings(project_id).await?;
        let outbox_total = self.count_outbox(project_id, None).await?;
        let status_counts = sqlx::query_as::<_, (String, i64)>(
            "SELECT status, count(*) \
             FROM channel_outbox \
             WHERE project_id = $1 \
             GROUP BY status \
             ORDER BY status ASC",
        )
        .bind(project_id)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        let latest_delivery_error = sqlx::query_as::<_, (String,)>(
            "SELECT last_error \
             FROM channel_outbox \
             WHERE project_id = $1 \
               AND last_error IS NOT NULL \
               AND status IN ('failed', 'dead_letter') \
             ORDER BY updated_at DESC NULLS LAST, created_at DESC \
             LIMIT 1",
        )
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?
        .map(|(last_error,)| last_error);

        Ok(ChannelObservabilitySummaryRecord {
            project_id: project_id.to_string(),
            session_bindings_total,
            outbox_total,
            outbox_by_status: status_counts.into_iter().collect(),
            latest_delivery_error,
        })
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

const CHANNEL_OUTBOX_SELECT_COLS: &str = "\
    id, project_id, channel_config_id, NULL::text AS channel_type, NULL::text AS webhook_url, \
    NULL::text AS domain, conversation_id, chat_id, content_text, status, attempt_count, \
    max_attempts, sent_channel_message_id, last_error, next_retry_at, created_at, updated_at";

const CHANNEL_OUTBOX_RETURNING_COLS: &str = "\
    o.id, o.project_id, o.channel_config_id, NULL::text AS channel_type, \
    NULL::text AS webhook_url, NULL::text AS domain, o.conversation_id, o.chat_id, o.content_text, \
    o.status, o.attempt_count, \
    o.max_attempts, o.sent_channel_message_id, o.last_error, o.next_retry_at, \
    o.created_at, o.updated_at";

const CHANNEL_WEBHOOK_EVENT_SELECT_COLS: &str = "\
    id, project_id, channel_config_id, channel_type, idempotency_key, headers_json, \
    raw_event_json, COALESCE(normalized_event_json, '{}'::jsonb) AS normalized_event_json, \
    status, route_error, route_session_key, route_binding_id, route_conversation_id, \
    received_at, routed_at";

const CHANNEL_SESSION_BINDING_SELECT_COLS: &str = "\
    id, channel_config_id, conversation_id, channel_type, chat_id, chat_type, \
    thread_id, topic_id, session_key, created_at, updated_at";

async fn select_channel_session_binding(
    tx: &mut Transaction<'_, Postgres>,
    project_id: &str,
    channel_config_id: &str,
    session_key: &str,
) -> CoreResult<Option<ChannelSessionBindingRecord>> {
    let sql = format!(
        "SELECT {CHANNEL_SESSION_BINDING_SELECT_COLS} \
         FROM channel_session_bindings \
         WHERE project_id = $1 \
           AND channel_config_id = $2 \
           AND session_key = $3 \
         LIMIT 1"
    );
    sqlx::query_as::<_, ChannelSessionBindingRecord>(&sql)
        .bind(project_id)
        .bind(channel_config_id)
        .bind(session_key)
        .fetch_optional(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn create_channel_session_binding_for_webhook_event(
    tx: &mut Transaction<'_, Postgres>,
    event: &ChannelWebhookEventRecord,
    route: &ChannelWebhookSessionCreateRecord,
) -> CoreResult<Option<ChannelSessionBindingRecord>> {
    let owner = sqlx::query_as::<_, ChannelConversationOwnerRecord>(
        "SELECT \
            p.tenant_id, \
            COALESCE(NULLIF(c.created_by, ''), p.owner_id) AS user_id \
         FROM projects p \
         JOIN channel_configs c ON c.project_id = p.id \
         WHERE p.id = $1 AND c.id = $2",
    )
    .bind(&event.project_id)
    .bind(&event.channel_config_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(|e| CoreError::Storage(e.to_string()))?;
    let Some(owner) = owner else {
        return Ok(None);
    };

    let empty_agent_config = serde_json::json!({});
    sqlx::query(
        "INSERT INTO conversations \
            (id, project_id, tenant_id, user_id, title, status, agent_config, meta, \
             message_count, current_mode, created_at, updated_at) \
         VALUES ($1, $2, $3, $4, $5, 'active', $6, $7, 0, 'build', now(), now())",
    )
    .bind(&route.conversation_id)
    .bind(&event.project_id)
    .bind(&owner.tenant_id)
    .bind(&owner.user_id)
    .bind(&route.conversation_title)
    .bind(Json(&empty_agent_config))
    .bind(Json(&route.metadata_json))
    .execute(&mut **tx)
    .await
    .map_err(|e| CoreError::Storage(e.to_string()))?;

    let insert_sql = format!(
        "INSERT INTO channel_session_bindings \
            (id, project_id, channel_config_id, conversation_id, channel_type, chat_id, chat_type, \
             thread_id, topic_id, session_key, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now()) \
         ON CONFLICT (project_id, session_key) DO NOTHING \
         RETURNING {CHANNEL_SESSION_BINDING_SELECT_COLS}"
    );
    let inserted = sqlx::query_as::<_, ChannelSessionBindingRecord>(&insert_sql)
        .bind(&route.binding_id)
        .bind(&event.project_id)
        .bind(&event.channel_config_id)
        .bind(&route.conversation_id)
        .bind(&event.channel_type)
        .bind(&route.chat_id)
        .bind(&route.chat_type)
        .bind(route.thread_id.as_deref())
        .bind(route.topic_id.as_deref())
        .bind(&route.session_key)
        .fetch_optional(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    if let Some(binding) = inserted {
        return Ok(Some(binding));
    }

    sqlx::query("DELETE FROM conversations WHERE id = $1")
        .bind(&route.conversation_id)
        .execute(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    select_channel_session_binding(
        tx,
        &event.project_id,
        &event.channel_config_id,
        &route.session_key,
    )
    .await
}

async fn delete_channel_outbox_lease(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    outbox_id: &str,
) -> CoreResult<()> {
    sqlx::query("DELETE FROM agistack_channel_outbox_leases WHERE outbox_id = $1")
        .bind(outbox_id)
        .execute(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::CHANNEL_CONFIG_SELECT_BY_ID_SQL;
    use super::*;

    #[test]
    fn channel_config_column_list_documents_secret_exclusion() {
        assert!(CHANNEL_CONFIG_SELECT_BY_ID_SQL.contains("app_id"));
        assert!(!CHANNEL_CONFIG_SELECT_BY_ID_SQL.contains("app_secret"));
        assert!(!CHANNEL_CONFIG_SELECT_BY_ID_SQL.contains("encrypt_key"));
        assert!(!CHANNEL_CONFIG_SELECT_BY_ID_SQL.contains("verification_token"));
    }

    #[test]
    fn observability_summary_status_counts_are_sorted_for_stable_wire_output() {
        let record = ChannelObservabilitySummaryRecord {
            project_id: "project-1".to_string(),
            session_bindings_total: 1,
            outbox_total: 2,
            outbox_by_status: [
                ("failed".to_string(), 1_i64),
                ("pending".to_string(), 1_i64),
            ]
            .into_iter()
            .collect(),
            latest_delivery_error: Some("delivery failed".to_string()),
        };

        assert_eq!(
            record.outbox_by_status.keys().collect::<Vec<_>>(),
            vec!["failed", "pending"]
        );
    }
}
