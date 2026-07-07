//! Adapter over Python-owned tenant webhooks.
//!
//! Rust owns the admin-scoped tenant webhook CRUD API-v1 slice in this
//! checkpoint. Webhook provider delivery execution remains Python-owned.

use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const WEBHOOK_COLS: &str =
    "id, tenant_id, name, url, secret, events, is_active, created_at, updated_at";

#[derive(Debug, Clone)]
pub struct TenantWebhookRecord {
    pub id: String,
    pub tenant_id: String,
    pub name: String,
    pub url: String,
    pub secret: Option<String>,
    pub events: Vec<String>,
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

pub struct CreateTenantWebhook<'a> {
    pub id: &'a str,
    pub tenant_id: &'a str,
    pub name: &'a str,
    pub url: &'a str,
    pub secret: &'a str,
    pub events: &'a [String],
    pub is_active: bool,
}

pub struct PgTenantWebhookRepository {
    pool: PgPool,
}

impl PgTenantWebhookRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn tenant_exists(&self, tenant_id: &str) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM tenants WHERE id = $1")
            .bind(tenant_id)
            .fetch_one(&self.pool)
            .await
            .map(|(count,)| count > 0)
            .map_err(|e| CoreError::Storage(format!("check webhook tenant exists: {e}")))
    }

    pub async fn tenant_member_role(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>(
            "SELECT COALESCE(role, 'member') \
             FROM user_tenants \
             WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(role,)| role))
        .map_err(|e| CoreError::Storage(format!("read webhook tenant role: {e}")))
    }

    pub async fn user_has_global_admin(&self, user_id: &str) -> CoreResult<bool> {
        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(is_superuser,)| is_superuser).unwrap_or(false))
        .map_err(|e| CoreError::Storage(format!("read webhook user superuser: {e}")))?;
        if is_superuser {
            return Ok(true);
        }

        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM user_roles \
             JOIN roles ON roles.id = user_roles.role_id \
             WHERE user_roles.user_id = $1 \
               AND user_roles.tenant_id IS NULL \
               AND roles.name = 'system_admin'",
        )
        .bind(user_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read webhook user global role: {e}")))
    }

    pub async fn list_webhooks(&self, tenant_id: &str) -> CoreResult<Vec<TenantWebhookRecord>> {
        let sql = format!(
            "SELECT {WEBHOOK_COLS} \
             FROM webhooks \
             WHERE tenant_id = $1 AND deleted_at IS NULL \
             ORDER BY created_at DESC"
        );
        let rows = sqlx::query(&sql)
            .bind(tenant_id)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list tenant webhooks: {e}")))?;

        rows.into_iter()
            .map(row_to_webhook)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read tenant webhook row: {e}")))
    }

    pub async fn get_webhook(&self, webhook_id: &str) -> CoreResult<Option<TenantWebhookRecord>> {
        let sql = format!(
            "SELECT {WEBHOOK_COLS} \
             FROM webhooks \
             WHERE id = $1 AND deleted_at IS NULL"
        );
        sqlx::query(&sql)
            .bind(webhook_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get tenant webhook: {e}")))?
            .map(row_to_webhook)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read tenant webhook row: {e}")))
    }

    pub async fn create_webhook(
        &self,
        input: CreateTenantWebhook<'_>,
    ) -> CoreResult<TenantWebhookRecord> {
        let sql = format!(
            "INSERT INTO webhooks \
             (id, tenant_id, name, url, secret, events, is_active, created_at, updated_at, deleted_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, now(), NULL, NULL) \
             RETURNING {WEBHOOK_COLS}"
        );
        sqlx::query(&sql)
            .bind(input.id)
            .bind(input.tenant_id)
            .bind(input.name)
            .bind(input.url)
            .bind(input.secret)
            .bind(serde_json::json!(input.events))
            .bind(input.is_active)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("create tenant webhook: {e}")))
            .and_then(|row| {
                row_to_webhook(row)
                    .map_err(|e| CoreError::Storage(format!("read tenant webhook row: {e}")))
            })
    }

    pub async fn update_webhook(
        &self,
        webhook_id: &str,
        name: &str,
        url: &str,
        events: &[String],
        is_active: bool,
    ) -> CoreResult<Option<TenantWebhookRecord>> {
        let sql = format!(
            "UPDATE webhooks \
             SET name = $2, url = $3, events = $4, is_active = $5, updated_at = now() \
             WHERE id = $1 AND deleted_at IS NULL \
             RETURNING {WEBHOOK_COLS}"
        );
        sqlx::query(&sql)
            .bind(webhook_id)
            .bind(name)
            .bind(url)
            .bind(serde_json::json!(events))
            .bind(is_active)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("update tenant webhook: {e}")))?
            .map(row_to_webhook)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read tenant webhook row: {e}")))
    }

    pub async fn delete_webhook(&self, webhook_id: &str) -> CoreResult<bool> {
        sqlx::query(
            "UPDATE webhooks \
             SET deleted_at = now() \
             WHERE id = $1 AND deleted_at IS NULL",
        )
        .bind(webhook_id)
        .execute(&self.pool)
        .await
        .map(|result| result.rows_affected() > 0)
        .map_err(|e| CoreError::Storage(format!("delete tenant webhook: {e}")))
    }
}

fn row_to_webhook(row: sqlx::postgres::PgRow) -> Result<TenantWebhookRecord, sqlx::Error> {
    let events_json: serde_json::Value = row.try_get("events")?;
    Ok(TenantWebhookRecord {
        id: row.try_get("id")?,
        tenant_id: row.try_get("tenant_id")?,
        name: row.try_get("name")?,
        url: row.try_get("url")?,
        secret: row.try_get("secret")?,
        events: event_strings(events_json),
        is_active: row.try_get("is_active")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

fn event_strings(value: serde_json::Value) -> Vec<String> {
    match value {
        serde_json::Value::Array(values) => values
            .into_iter()
            .filter_map(|value| value.as_str().map(ToOwned::to_owned))
            .collect(),
        _ => Vec::new(),
    }
}
