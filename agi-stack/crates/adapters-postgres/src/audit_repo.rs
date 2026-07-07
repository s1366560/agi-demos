//! Read-only adapter over Python-owned tenant audit logs.
//!
//! Rust owns tenant-scoped list/filter/runtime-hook summary reads in this
//! checkpoint. Audit export and write-side logging remain Python-owned.

use std::collections::BTreeMap;

use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const AUDIT_COLS: &str = "id, \"timestamp\", actor, action, resource_type, resource_id, \
                          tenant_id, details, ip_address, user_agent";

#[derive(Debug, Clone)]
pub struct AuditLogRecord {
    pub id: String,
    pub timestamp: DateTime<Utc>,
    pub actor: Option<String>,
    pub action: String,
    pub resource_type: String,
    pub resource_id: Option<String>,
    pub tenant_id: Option<String>,
    pub details_json: serde_json::Value,
    pub ip_address: Option<String>,
    pub user_agent: Option<String>,
}

#[derive(Debug, Clone)]
pub struct AuditLogListQuery<'a> {
    pub tenant_id: &'a str,
    pub action: Option<&'a str>,
    pub resource_type: Option<&'a str>,
    pub actor: Option<&'a str>,
    pub start_time: Option<DateTime<Utc>>,
    pub end_time: Option<DateTime<Utc>>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone)]
pub struct RuntimeHookAuditQuery<'a> {
    pub tenant_id: &'a str,
    pub action: Option<&'a str>,
    pub hook_name: Option<&'a str>,
    pub executor_kind: Option<&'a str>,
    pub hook_family: Option<&'a str>,
    pub isolation_mode: Option<&'a str>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct RuntimeHookAuditSummaryRecord {
    pub total: i64,
    pub action_counts: BTreeMap<String, i64>,
    pub executor_counts: BTreeMap<String, i64>,
    pub family_counts: BTreeMap<String, i64>,
    pub isolation_mode_counts: BTreeMap<String, i64>,
    pub latest_timestamp: Option<DateTime<Utc>>,
}

pub struct PgAuditLogRepository {
    pool: PgPool,
}

impl PgAuditLogRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn tenant_exists(&self, tenant_id: &str) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM tenants WHERE id = $1")
            .bind(tenant_id)
            .fetch_one(&self.pool)
            .await
            .map(|(count,)| count > 0)
            .map_err(|e| CoreError::Storage(format!("check audit tenant exists: {e}")))
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
        .map_err(|e| CoreError::Storage(format!("read audit tenant role: {e}")))
    }

    pub async fn user_has_global_admin(&self, user_id: &str) -> CoreResult<bool> {
        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(is_superuser,)| is_superuser).unwrap_or(false))
        .map_err(|e| CoreError::Storage(format!("read audit user superuser: {e}")))?;
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
        .map_err(|e| CoreError::Storage(format!("read audit user global role: {e}")))
    }

    pub async fn list_audit_logs(
        &self,
        query: AuditLogListQuery<'_>,
    ) -> CoreResult<(Vec<AuditLogRecord>, i64)> {
        let total = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM audit_logs \
             WHERE (tenant_id = $1 OR tenant_id IS NULL) \
               AND ($2::text IS NULL OR action = $2) \
               AND ($3::text IS NULL OR resource_type = $3) \
               AND ($4::text IS NULL OR actor = $4) \
               AND ($5::timestamptz IS NULL OR \"timestamp\" >= $5) \
               AND ($6::timestamptz IS NULL OR \"timestamp\" <= $6)",
        )
        .bind(query.tenant_id)
        .bind(query.action)
        .bind(query.resource_type)
        .bind(query.actor)
        .bind(query.start_time)
        .bind(query.end_time)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("count audit logs: {e}")))?
        .0;

        let sql = format!(
            "SELECT {AUDIT_COLS} \
             FROM audit_logs \
             WHERE (tenant_id = $1 OR tenant_id IS NULL) \
               AND ($2::text IS NULL OR action = $2) \
               AND ($3::text IS NULL OR resource_type = $3) \
               AND ($4::text IS NULL OR actor = $4) \
               AND ($5::timestamptz IS NULL OR \"timestamp\" >= $5) \
               AND ($6::timestamptz IS NULL OR \"timestamp\" <= $6) \
             ORDER BY \"timestamp\" DESC, id ASC \
             LIMIT $7 OFFSET $8"
        );
        let rows = sqlx::query(&sql)
            .bind(query.tenant_id)
            .bind(query.action)
            .bind(query.resource_type)
            .bind(query.actor)
            .bind(query.start_time)
            .bind(query.end_time)
            .bind(query.limit)
            .bind(query.offset)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list audit logs: {e}")))?;

        Ok((read_audit_rows(rows)?, total))
    }

    pub async fn list_runtime_hook_logs(
        &self,
        query: RuntimeHookAuditQuery<'_>,
    ) -> CoreResult<(Vec<AuditLogRecord>, i64)> {
        let total = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM audit_logs \
             WHERE (tenant_id = $1 OR tenant_id IS NULL) \
               AND action LIKE 'runtime_hook.%' \
               AND resource_type = 'runtime_hook' \
               AND ($2::text IS NULL OR action = $2) \
               AND ($3::text IS NULL OR details ->> 'hook_name' = $3) \
               AND ($4::text IS NULL OR details ->> 'executor_kind' = $4) \
               AND ($5::text IS NULL OR details ->> 'hook_family' = $5) \
               AND ($6::text IS NULL OR details ->> 'isolation_mode' = $6)",
        )
        .bind(query.tenant_id)
        .bind(query.action)
        .bind(query.hook_name)
        .bind(query.executor_kind)
        .bind(query.hook_family)
        .bind(query.isolation_mode)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("count runtime hook audit logs: {e}")))?
        .0;

        let sql = format!(
            "SELECT {AUDIT_COLS} \
             FROM audit_logs \
             WHERE (tenant_id = $1 OR tenant_id IS NULL) \
               AND action LIKE 'runtime_hook.%' \
               AND resource_type = 'runtime_hook' \
               AND ($2::text IS NULL OR action = $2) \
               AND ($3::text IS NULL OR details ->> 'hook_name' = $3) \
               AND ($4::text IS NULL OR details ->> 'executor_kind' = $4) \
               AND ($5::text IS NULL OR details ->> 'hook_family' = $5) \
               AND ($6::text IS NULL OR details ->> 'isolation_mode' = $6) \
             ORDER BY \"timestamp\" DESC, id ASC \
             LIMIT $7 OFFSET $8"
        );
        let rows = sqlx::query(&sql)
            .bind(query.tenant_id)
            .bind(query.action)
            .bind(query.hook_name)
            .bind(query.executor_kind)
            .bind(query.hook_family)
            .bind(query.isolation_mode)
            .bind(query.limit)
            .bind(query.offset)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list runtime hook audit logs: {e}")))?;

        Ok((read_audit_rows(rows)?, total))
    }

    pub async fn summarize_runtime_hook_logs(
        &self,
        query: RuntimeHookAuditQuery<'_>,
    ) -> CoreResult<RuntimeHookAuditSummaryRecord> {
        let sql = format!(
            "SELECT {AUDIT_COLS} \
             FROM audit_logs \
             WHERE (tenant_id = $1 OR tenant_id IS NULL) \
               AND action LIKE 'runtime_hook.%' \
               AND resource_type = 'runtime_hook' \
               AND ($2::text IS NULL OR action = $2) \
               AND ($3::text IS NULL OR details ->> 'hook_name' = $3) \
               AND ($4::text IS NULL OR details ->> 'executor_kind' = $4) \
               AND ($5::text IS NULL OR details ->> 'hook_family' = $5) \
               AND ($6::text IS NULL OR details ->> 'isolation_mode' = $6) \
             ORDER BY \"timestamp\" DESC, id ASC"
        );
        let rows = sqlx::query(&sql)
            .bind(query.tenant_id)
            .bind(query.action)
            .bind(query.hook_name)
            .bind(query.executor_kind)
            .bind(query.hook_family)
            .bind(query.isolation_mode)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("summarize runtime hook audit logs: {e}")))?;

        Ok(summarize_runtime_hooks(read_audit_rows(rows)?))
    }
}

fn read_audit_rows(rows: Vec<sqlx::postgres::PgRow>) -> CoreResult<Vec<AuditLogRecord>> {
    rows.into_iter()
        .map(|row| {
            Ok(AuditLogRecord {
                id: row.try_get("id")?,
                timestamp: row.try_get("timestamp")?,
                actor: row.try_get("actor")?,
                action: row.try_get("action")?,
                resource_type: row.try_get("resource_type")?,
                resource_id: row.try_get("resource_id")?,
                tenant_id: row.try_get("tenant_id")?,
                details_json: row
                    .try_get::<Option<serde_json::Value>, _>("details")?
                    .unwrap_or_else(|| serde_json::json!({})),
                ip_address: row.try_get("ip_address")?,
                user_agent: row.try_get("user_agent")?,
            })
        })
        .collect::<Result<Vec<_>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(format!("read audit log row: {e}")))
}

fn summarize_runtime_hooks(records: Vec<AuditLogRecord>) -> RuntimeHookAuditSummaryRecord {
    let mut action_counts = BTreeMap::new();
    let mut executor_counts = BTreeMap::new();
    let mut family_counts = BTreeMap::new();
    let mut isolation_mode_counts = BTreeMap::new();
    let mut latest_timestamp = None;

    for record in &records {
        increment(&mut action_counts, &record.action);
        increment(
            &mut executor_counts,
            detail_string(&record.details_json, "executor_kind").as_str(),
        );
        increment(
            &mut family_counts,
            detail_string(&record.details_json, "hook_family").as_str(),
        );
        increment(
            &mut isolation_mode_counts,
            detail_string(&record.details_json, "isolation_mode").as_str(),
        );
        latest_timestamp = latest_timestamp.max(Some(record.timestamp));
    }

    RuntimeHookAuditSummaryRecord {
        total: records.len() as i64,
        action_counts,
        executor_counts,
        family_counts,
        isolation_mode_counts,
        latest_timestamp,
    }
}

fn increment(counts: &mut BTreeMap<String, i64>, key: &str) {
    *counts.entry(key.to_string()).or_insert(0) += 1;
}

fn detail_string(details: &serde_json::Value, key: &str) -> String {
    details
        .get(key)
        .and_then(serde_json::Value::as_str)
        .unwrap_or("unknown")
        .to_string()
}
