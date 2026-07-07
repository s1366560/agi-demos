//! Read-only adapter over Python-owned `subagent_templates`.
//!
//! Rust owns only the exact template category discovery slice. Template
//! list/create/update/install paths remain Python-owned.

use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

pub struct PgSubagentTemplateRepository {
    pool: PgPool,
}

impl PgSubagentTemplateRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_categories(&self, tenant_id: &str) -> CoreResult<Vec<String>> {
        let rows = sqlx::query(
            "SELECT DISTINCT category \
             FROM subagent_templates \
             WHERE tenant_id = $1 \
               AND is_published IS TRUE \
             ORDER BY category",
        )
        .bind(tenant_id)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("list subagent template categories: {e}")))?;

        rows.into_iter()
            .map(|row| row.try_get::<String, _>("category"))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| CoreError::Storage(format!("read subagent template category: {e}")))
    }
}
