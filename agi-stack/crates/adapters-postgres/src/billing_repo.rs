//! Adapter over Python-owned billing tables.
//!
//! Rust owns tenant billing reads and the exact plan-upgrade mutation.

use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const INVOICE_COLS: &str =
    "id, tenant_id, amount, currency, status, period_start, period_end, created_at, paid_at, invoice_url";

#[derive(Debug, Clone)]
pub struct InvoiceRecord {
    pub id: String,
    pub tenant_id: String,
    pub amount: i32,
    pub currency: String,
    pub status: String,
    pub period_start: DateTime<Utc>,
    pub period_end: DateTime<Utc>,
    pub created_at: DateTime<Utc>,
    pub paid_at: Option<DateTime<Utc>>,
    pub invoice_url: Option<String>,
}

#[derive(Debug, Clone)]
pub struct BillingTenantRecord {
    pub id: String,
    pub name: String,
    pub plan: String,
    pub storage_limit: i64,
}

#[derive(Debug, Clone)]
pub struct BillingUsageRecord {
    pub projects: i64,
    pub memories: i64,
    pub users: i64,
    pub storage: i64,
}

pub struct PgBillingRepository {
    pool: PgPool,
}

impl PgBillingRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
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
        .map_err(|e| CoreError::Storage(format!("read billing tenant role: {e}")))
    }

    pub async fn tenant_exists(&self, tenant_id: &str) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM tenants WHERE id = $1")
            .bind(tenant_id)
            .fetch_one(&self.pool)
            .await
            .map(|(count,)| count > 0)
            .map_err(|e| CoreError::Storage(format!("check billing tenant exists: {e}")))
    }

    pub async fn list_invoices(&self, tenant_id: &str) -> CoreResult<Vec<InvoiceRecord>> {
        let sql = format!(
            "SELECT {INVOICE_COLS} \
             FROM invoices \
             WHERE tenant_id = $1 \
             ORDER BY created_at DESC"
        );
        let rows = sqlx::query(&sql)
            .bind(tenant_id)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list invoices: {e}")))?;

        rows.into_iter()
            .map(|row| {
                Ok(InvoiceRecord {
                    id: row.try_get("id")?,
                    tenant_id: row.try_get("tenant_id")?,
                    amount: row.try_get("amount")?,
                    currency: row.try_get("currency")?,
                    status: row.try_get("status")?,
                    period_start: row.try_get("period_start")?,
                    period_end: row.try_get("period_end")?,
                    created_at: row.try_get("created_at")?,
                    paid_at: row.try_get("paid_at")?,
                    invoice_url: row.try_get("invoice_url")?,
                })
            })
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read invoice row: {e}")))
    }

    pub async fn billing_tenant(&self, tenant_id: &str) -> CoreResult<Option<BillingTenantRecord>> {
        sqlx::query(
            "SELECT id, name, COALESCE(plan, 'free') AS plan, \
                    COALESCE(max_storage, 10737418240) AS storage_limit \
             FROM tenants \
             WHERE id = $1",
        )
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("read billing tenant: {e}")))?
        .map(|row| {
            Ok(BillingTenantRecord {
                id: row.try_get("id")?,
                name: row.try_get("name")?,
                plan: row.try_get("plan")?,
                storage_limit: row.try_get("storage_limit")?,
            })
        })
        .transpose()
        .map_err(|e: sqlx::Error| CoreError::Storage(format!("read billing tenant row: {e}")))
    }

    pub async fn billing_usage(&self, tenant_id: &str) -> CoreResult<BillingUsageRecord> {
        let project_rows = sqlx::query_as::<_, (String,)>(
            "SELECT id FROM projects WHERE tenant_id = $1 ORDER BY id",
        )
        .bind(tenant_id)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("list billing project ids: {e}")))?;
        let project_ids = project_rows.into_iter().map(|(id,)| id).collect::<Vec<_>>();
        let projects = project_ids.len() as i64;
        let memories = if project_ids.is_empty() {
            0
        } else {
            sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM memories WHERE project_id = ANY($1)")
                .bind(&project_ids)
                .fetch_one(&self.pool)
                .await
                .map_err(|e| CoreError::Storage(format!("count billing memories: {e}")))?
                .0
        };
        let users = if project_ids.is_empty() {
            0
        } else {
            sqlx::query_as::<_, (i64,)>(
                "SELECT count(DISTINCT user_id) FROM user_projects WHERE project_id = ANY($1)",
            )
            .bind(&project_ids)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("count billing users: {e}")))?
            .0
        };

        Ok(BillingUsageRecord {
            projects,
            memories,
            users,
            // The current Python Project model has no storage_used column, so
            // getattr(project, "storage_used", 0) always contributes zero.
            storage: 0,
        })
    }

    pub async fn list_recent_invoices(
        &self,
        tenant_id: &str,
        limit: i64,
    ) -> CoreResult<Vec<InvoiceRecord>> {
        let sql = format!(
            "SELECT {INVOICE_COLS} \
             FROM invoices \
             WHERE tenant_id = $1 \
             ORDER BY created_at DESC \
             LIMIT $2"
        );
        let rows = sqlx::query(&sql)
            .bind(tenant_id)
            .bind(limit)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list recent invoices: {e}")))?;

        rows.into_iter()
            .map(|row| {
                Ok(InvoiceRecord {
                    id: row.try_get("id")?,
                    tenant_id: row.try_get("tenant_id")?,
                    amount: row.try_get("amount")?,
                    currency: row.try_get("currency")?,
                    status: row.try_get("status")?,
                    period_start: row.try_get("period_start")?,
                    period_end: row.try_get("period_end")?,
                    created_at: row.try_get("created_at")?,
                    paid_at: row.try_get("paid_at")?,
                    invoice_url: row.try_get("invoice_url")?,
                })
            })
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read recent invoice row: {e}")))
    }

    pub async fn update_tenant_plan(
        &self,
        tenant_id: &str,
        plan: &str,
        storage_limit: i64,
    ) -> CoreResult<Option<BillingTenantRecord>> {
        sqlx::query(
            "UPDATE tenants \
             SET plan = $2, max_storage = $3 \
             WHERE id = $1 \
             RETURNING id, name, COALESCE(plan, 'free') AS plan, \
                       COALESCE(max_storage, 10737418240) AS storage_limit",
        )
        .bind(tenant_id)
        .bind(plan)
        .bind(storage_limit)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("update billing tenant plan: {e}")))?
        .map(|row| {
            Ok(BillingTenantRecord {
                id: row.try_get("id")?,
                name: row.try_get("name")?,
                plan: row.try_get("plan")?,
                storage_limit: row.try_get("storage_limit")?,
            })
        })
        .transpose()
        .map_err(|e: sqlx::Error| CoreError::Storage(format!("read updated billing tenant: {e}")))
    }
}
