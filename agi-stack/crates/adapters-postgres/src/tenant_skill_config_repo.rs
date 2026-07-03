//! Repository over Python-owned `tenant_skill_configs`.
//!
//! This is the P5 tenant skill config bridge for the strangler migration. It
//! keeps sqlx and shared-schema details server-side while the HTTP layer
//! preserves Python's wire contract.

use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const CONFIG_COLS: &str =
    "id, tenant_id, system_skill_name, action, override_skill_id, created_at, updated_at";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TenantSkillConfigRecord {
    pub id: String,
    pub tenant_id: String,
    pub system_skill_name: String,
    pub action: String,
    pub override_skill_id: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

pub struct PgTenantSkillConfigRepository {
    pool: PgPool,
}

impl PgTenantSkillConfigRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn first_tenant_for_user(&self, user_id: &str) -> CoreResult<Option<String>> {
        let row = sqlx::query_as::<_, (String,)>(
            "SELECT tenant_id FROM user_tenants WHERE user_id = $1 \
             ORDER BY created_at ASC, id ASC LIMIT 1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.map(|(tenant_id,)| tenant_id))
    }

    pub async fn user_has_tenant_access(&self, user_id: &str, tenant_id: &str) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.0 > 0)
    }

    pub async fn user_is_tenant_admin(&self, user_id: &str, tenant_id: &str) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (Option<String>,)>(
            "SELECT role FROM user_tenants WHERE user_id = $1 AND tenant_id = $2 LIMIT 1",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        Ok(matches!(
            row.and_then(|(role,)| role),
            Some(role) if role == "owner" || role == "admin"
        ))
    }

    pub async fn override_skill_belongs_to_tenant(
        &self,
        skill_id: &str,
        tenant_id: &str,
    ) -> CoreResult<Option<bool>> {
        let row = sqlx::query_as::<_, (String,)>("SELECT tenant_id FROM skills WHERE id = $1")
            .bind(skill_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?;
        Ok(row.map(|(skill_tenant_id,)| skill_tenant_id == tenant_id))
    }

    pub async fn list_by_tenant(
        &self,
        tenant_id: &str,
    ) -> CoreResult<Vec<TenantSkillConfigRecord>> {
        let sql = format!(
            "SELECT {CONFIG_COLS} FROM tenant_skill_configs \
             WHERE tenant_id = $1 ORDER BY created_at DESC"
        );
        let rows = sqlx::query(&sql)
            .bind(tenant_id)
            .fetch_all(&self.pool)
            .await
            .map_err(storage)?;
        rows.into_iter().map(row_to_config).collect()
    }

    pub async fn count_by_tenant(&self, tenant_id: &str) -> CoreResult<i64> {
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM tenant_skill_configs WHERE tenant_id = $1",
        )
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.0)
    }

    pub async fn get_by_tenant_and_skill(
        &self,
        tenant_id: &str,
        system_skill_name: &str,
    ) -> CoreResult<Option<TenantSkillConfigRecord>> {
        let sql = format!(
            "SELECT {CONFIG_COLS} FROM tenant_skill_configs \
             WHERE tenant_id = $1 AND system_skill_name = $2 LIMIT 1"
        );
        let row = sqlx::query(&sql)
            .bind(tenant_id)
            .bind(system_skill_name)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?;
        row.map(row_to_config).transpose()
    }

    pub async fn create(
        &self,
        record: &TenantSkillConfigRecord,
    ) -> CoreResult<TenantSkillConfigRecord> {
        sqlx::query(
            "INSERT INTO tenant_skill_configs \
             (id, tenant_id, system_skill_name, action, override_skill_id, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7)",
        )
        .bind(&record.id)
        .bind(&record.tenant_id)
        .bind(&record.system_skill_name)
        .bind(&record.action)
        .bind(&record.override_skill_id)
        .bind(record.created_at)
        .bind(record.updated_at)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(record.clone())
    }

    pub async fn update(
        &self,
        record: &TenantSkillConfigRecord,
    ) -> CoreResult<TenantSkillConfigRecord> {
        sqlx::query(
            "UPDATE tenant_skill_configs SET action=$2, override_skill_id=$3, updated_at=$4 \
             WHERE id=$1",
        )
        .bind(&record.id)
        .bind(&record.action)
        .bind(&record.override_skill_id)
        .bind(record.updated_at)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(record.clone())
    }

    pub async fn delete(&self, config_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM tenant_skill_configs WHERE id = $1")
            .bind(config_id)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn delete_by_tenant_and_skill(
        &self,
        tenant_id: &str,
        system_skill_name: &str,
    ) -> CoreResult<bool> {
        let result = sqlx::query(
            "DELETE FROM tenant_skill_configs WHERE tenant_id = $1 AND system_skill_name = $2",
        )
        .bind(tenant_id)
        .bind(system_skill_name)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }
}

fn row_to_config(row: PgRow) -> CoreResult<TenantSkillConfigRecord> {
    Ok(TenantSkillConfigRecord {
        id: row.try_get("id").map_err(storage)?,
        tenant_id: row.try_get("tenant_id").map_err(storage)?,
        system_skill_name: row.try_get("system_skill_name").map_err(storage)?,
        action: row.try_get("action").map_err(storage)?,
        override_skill_id: row.try_get("override_skill_id").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

fn storage<E: std::fmt::Display>(error: E) -> CoreError {
    CoreError::Storage(error.to_string())
}
