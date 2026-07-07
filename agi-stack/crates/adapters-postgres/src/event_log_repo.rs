//! Read-only adapter over Python-owned `tenant_event_logs`.
//!
//! The Python events router exposes tenant-scoped observability event logs. This
//! Rust adapter starts with exact safe strangler slices: tenant-scoped event
//! listing and distinct event type discovery.

use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const EVENT_LOG_COLS: &str = "id, tenant_id, event_type, message, source, metadata, created_at";

#[derive(Debug, Clone)]
pub struct TenantEventLogRecord {
    pub id: String,
    pub tenant_id: String,
    pub event_type: String,
    pub message: String,
    pub source: String,
    pub metadata_json: serde_json::Value,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct TenantEventLogListQuery<'a> {
    pub tenant_id: &'a str,
    pub event_type: Option<&'a str>,
    pub date_from: Option<DateTime<Utc>>,
    pub date_to: Option<DateTime<Utc>>,
    pub page: i64,
    pub page_size: i64,
}

impl TenantEventLogListQuery<'_> {
    fn offset(&self) -> i64 {
        (self.page - 1) * self.page_size
    }
}

pub struct PgEventLogRepository {
    pool: PgPool,
}

impl PgEventLogRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_event_types(&self, tenant_id: &str) -> CoreResult<Vec<String>> {
        let rows = sqlx::query(
            "SELECT DISTINCT event_type \
             FROM tenant_event_logs \
             WHERE tenant_id = $1 \
             ORDER BY event_type",
        )
        .bind(tenant_id)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("list event types: {e}")))?;

        rows.into_iter()
            .map(|row| row.try_get::<String, _>("event_type"))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| CoreError::Storage(format!("read event type: {e}")))
    }

    pub async fn list_events(
        &self,
        query: TenantEventLogListQuery<'_>,
    ) -> CoreResult<(Vec<TenantEventLogRecord>, i64)> {
        let total = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM tenant_event_logs \
             WHERE tenant_id = $1 \
               AND ($2::text IS NULL OR event_type = $2) \
               AND ($3::timestamptz IS NULL OR created_at >= $3) \
               AND ($4::timestamptz IS NULL OR created_at <= $4)",
        )
        .bind(query.tenant_id)
        .bind(query.event_type)
        .bind(query.date_from)
        .bind(query.date_to)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("count tenant events: {e}")))?
        .0;

        let sql = format!(
            "SELECT {EVENT_LOG_COLS} \
             FROM tenant_event_logs \
             WHERE tenant_id = $1 \
               AND ($2::text IS NULL OR event_type = $2) \
               AND ($3::timestamptz IS NULL OR created_at >= $3) \
               AND ($4::timestamptz IS NULL OR created_at <= $4) \
             ORDER BY created_at DESC, id ASC \
             LIMIT $5 OFFSET $6"
        );
        let rows = sqlx::query(&sql)
            .bind(query.tenant_id)
            .bind(query.event_type)
            .bind(query.date_from)
            .bind(query.date_to)
            .bind(query.page_size)
            .bind(query.offset())
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list tenant events: {e}")))?;

        let records = rows
            .into_iter()
            .map(|row| {
                Ok(TenantEventLogRecord {
                    id: row.try_get("id")?,
                    tenant_id: row.try_get("tenant_id")?,
                    event_type: row.try_get("event_type")?,
                    message: row.try_get("message")?,
                    source: row.try_get("source")?,
                    metadata_json: row.try_get("metadata")?,
                    created_at: row.try_get("created_at")?,
                })
            })
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read tenant event row: {e}")))?;
        Ok((records, total))
    }
}
