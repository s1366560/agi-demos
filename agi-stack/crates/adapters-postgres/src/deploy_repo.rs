//! Read-only adapter over Python-owned instance deployment tables.
//!
//! Rust owns only deploy list/detail/latest reads in this checkpoint. Deploy
//! creation, lifecycle transitions, cancellation, and Redis/SSE progress remain
//! Python-owned.

use serde_json::{json, Value};
use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const DEPLOY_COLS: &str = "id, instance_id, revision, action, image_version, replicas, \
    config_snapshot, status, message, triggered_by, started_at, finished_at, created_at";

#[derive(Debug, Clone, Copy)]
pub struct DeployListQuery<'a> {
    pub instance_id: &'a str,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeployAccess {
    Allowed,
    Forbidden,
    NotFound,
}

#[derive(Debug, Clone)]
pub struct DeployRecord {
    pub id: String,
    pub instance_id: String,
    pub revision: i32,
    pub action: String,
    pub image_version: Option<String>,
    pub replicas: Option<i32>,
    pub config_snapshot: Value,
    pub status: String,
    pub message: Option<String>,
    pub triggered_by: Option<String>,
    pub started_at: Option<DateTime<Utc>>,
    pub finished_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
}

pub struct PgDeployRepository {
    pool: PgPool,
}

impl PgDeployRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn access_for_instance(
        &self,
        user_id: &str,
        instance_id: &str,
    ) -> CoreResult<DeployAccess> {
        let tenant_id = sqlx::query_as::<_, (String,)>(
            "SELECT tenant_id FROM instances WHERE id = $1 AND deleted_at IS NULL",
        )
        .bind(instance_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("read deploy instance tenant: {e}")))?
        .map(|(tenant_id,)| tenant_id);

        self.access_for_tenant(user_id, tenant_id.as_deref()).await
    }

    pub async fn access_for_deploy(
        &self,
        user_id: &str,
        deploy_id: &str,
    ) -> CoreResult<DeployAccess> {
        let tenant_id = sqlx::query_as::<_, (String,)>(
            "SELECT instances.tenant_id \
             FROM instances \
             JOIN deploy_records ON deploy_records.instance_id = instances.id \
             WHERE deploy_records.id = $1 \
               AND deploy_records.deleted_at IS NULL \
               AND instances.deleted_at IS NULL",
        )
        .bind(deploy_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("read deploy tenant access: {e}")))?
        .map(|(tenant_id,)| tenant_id);

        self.access_for_tenant(user_id, tenant_id.as_deref()).await
    }

    pub async fn list_deploys(
        &self,
        query: DeployListQuery<'_>,
    ) -> CoreResult<(Vec<DeployRecord>, i64)> {
        let total = sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) FROM deploy_records \
             WHERE instance_id = $1 AND deleted_at IS NULL",
        )
        .bind(query.instance_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count)
        .map_err(|e| CoreError::Storage(format!("count deploy records: {e}")))?;

        let sql = format!(
            "SELECT {DEPLOY_COLS} \
             FROM deploy_records \
             WHERE instance_id = $1 AND deleted_at IS NULL \
             ORDER BY created_at DESC, id ASC \
             LIMIT $2 OFFSET $3"
        );
        let rows = sqlx::query(&sql)
            .bind(query.instance_id)
            .bind(query.limit)
            .bind(query.offset)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list deploy records: {e}")))?;

        let records = rows
            .into_iter()
            .map(deploy_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read deploy row: {e}")))?;
        Ok((records, total))
    }

    pub async fn get_deploy(&self, deploy_id: &str) -> CoreResult<Option<DeployRecord>> {
        let sql = format!(
            "SELECT {DEPLOY_COLS} \
             FROM deploy_records \
             WHERE id = $1 AND deleted_at IS NULL"
        );
        sqlx::query(&sql)
            .bind(deploy_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get deploy record: {e}")))?
            .map(deploy_from_row)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read deploy row: {e}")))
    }

    pub async fn latest_deploy(&self, instance_id: &str) -> CoreResult<Option<DeployRecord>> {
        let sql = format!(
            "SELECT {DEPLOY_COLS} \
             FROM deploy_records \
             WHERE instance_id = $1 AND deleted_at IS NULL \
             ORDER BY created_at DESC, id ASC \
             LIMIT 1"
        );
        sqlx::query(&sql)
            .bind(instance_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get latest deploy record: {e}")))?
            .map(deploy_from_row)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read deploy row: {e}")))
    }

    async fn access_for_tenant(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> CoreResult<DeployAccess> {
        let Some(tenant_id) = tenant_id else {
            return Ok(DeployAccess::NotFound);
        };

        if self.user_has_global_admin(user_id).await? {
            return Ok(DeployAccess::Allowed);
        }

        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count)
        .map_err(|e| CoreError::Storage(format!("read deploy tenant membership: {e}")))?;

        if count > 0 {
            Ok(DeployAccess::Allowed)
        } else {
            Ok(DeployAccess::Forbidden)
        }
    }

    async fn user_has_global_admin(&self, user_id: &str) -> CoreResult<bool> {
        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(is_superuser,)| is_superuser).unwrap_or(false))
        .map_err(|e| CoreError::Storage(format!("read deploy user superuser: {e}")))?;
        if is_superuser {
            return Ok(true);
        }

        sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) \
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
        .map_err(|e| CoreError::Storage(format!("read deploy user global role: {e}")))
    }
}

fn deploy_from_row(row: PgRow) -> Result<DeployRecord, sqlx::Error> {
    Ok(DeployRecord {
        id: row.try_get("id")?,
        instance_id: row.try_get("instance_id")?,
        revision: row.try_get("revision")?,
        action: row.try_get("action")?,
        image_version: row.try_get("image_version")?,
        replicas: row.try_get("replicas")?,
        config_snapshot: row
            .try_get::<Option<Value>, _>("config_snapshot")?
            .unwrap_or_else(|| json!({})),
        status: row.try_get("status")?,
        message: row.try_get("message")?,
        triggered_by: row.try_get("triggered_by")?,
        started_at: row.try_get("started_at")?,
        finished_at: row.try_get("finished_at")?,
        created_at: row.try_get("created_at")?,
    })
}
