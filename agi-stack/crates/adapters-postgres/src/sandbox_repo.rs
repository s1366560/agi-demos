//! Shared-DB adapter for Python-owned `project_sandboxes`.
//!
//! The Rust P5 sandbox lifecycle surface reuses Python's project-sandbox
//! association table verbatim. This keeps the lifecycle state durable across
//! Rust server restarts without altering Python-owned schema.

use serde_json::Value;
use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

#[derive(Debug, Clone)]
pub struct ProjectSandboxRecord {
    pub id: String,
    pub project_id: String,
    pub tenant_id: String,
    pub sandbox_id: String,
    pub sandbox_type: String,
    pub status: String,
    pub created_at: DateTime<Utc>,
    pub started_at: Option<DateTime<Utc>>,
    pub last_accessed_at: DateTime<Utc>,
    pub health_checked_at: Option<DateTime<Utc>>,
    pub error_message: Option<String>,
    pub metadata_json: Value,
    pub local_config: Value,
}

pub struct PgProjectSandboxRepository {
    pool: PgPool,
}

impl PgProjectSandboxRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn find_by_project(
        &self,
        project_id: &str,
    ) -> CoreResult<Option<ProjectSandboxRecord>> {
        let row = sqlx::query_as::<_, ProjectSandboxRow>(
            "SELECT id, project_id, tenant_id, sandbox_id, sandbox_type, status, \
                    created_at, started_at, last_accessed_at, health_checked_at, \
                    error_message, metadata_json::text AS metadata_text, \
                    local_config::text AS local_config_text \
             FROM project_sandboxes \
             WHERE project_id = $1",
        )
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage_err)?;
        row.map(ProjectSandboxRow::into_record).transpose()
    }

    pub async fn find_by_sandbox(
        &self,
        sandbox_id: &str,
    ) -> CoreResult<Option<ProjectSandboxRecord>> {
        let row = sqlx::query_as::<_, ProjectSandboxRow>(
            "SELECT id, project_id, tenant_id, sandbox_id, sandbox_type, status, \
                    created_at, started_at, last_accessed_at, health_checked_at, \
                    error_message, metadata_json::text AS metadata_text, \
                    local_config::text AS local_config_text \
             FROM project_sandboxes \
             WHERE sandbox_id = $1",
        )
        .bind(sandbox_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage_err)?;
        row.map(ProjectSandboxRow::into_record).transpose()
    }

    pub async fn list_by_tenant(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<ProjectSandboxRecord>> {
        let rows = match status {
            Some(status) => sqlx::query_as::<_, ProjectSandboxRow>(
                "SELECT id, project_id, tenant_id, sandbox_id, sandbox_type, status, \
                            created_at, started_at, last_accessed_at, health_checked_at, \
                            error_message, metadata_json::text AS metadata_text, \
                            local_config::text AS local_config_text \
                     FROM project_sandboxes \
                     WHERE tenant_id = $1 AND status = $2 \
                     ORDER BY created_at DESC \
                     OFFSET $3 LIMIT $4",
            )
            .bind(tenant_id)
            .bind(status)
            .bind(offset)
            .bind(limit)
            .fetch_all(&self.pool)
            .await
            .map_err(storage_err)?,
            None => sqlx::query_as::<_, ProjectSandboxRow>(
                "SELECT id, project_id, tenant_id, sandbox_id, sandbox_type, status, \
                            created_at, started_at, last_accessed_at, health_checked_at, \
                            error_message, metadata_json::text AS metadata_text, \
                            local_config::text AS local_config_text \
                     FROM project_sandboxes \
                     WHERE tenant_id = $1 \
                     ORDER BY created_at DESC \
                     OFFSET $2 LIMIT $3",
            )
            .bind(tenant_id)
            .bind(offset)
            .bind(limit)
            .fetch_all(&self.pool)
            .await
            .map_err(storage_err)?,
        };
        rows.into_iter()
            .map(ProjectSandboxRow::into_record)
            .collect()
    }

    pub async fn upsert(&self, record: ProjectSandboxRecord) -> CoreResult<ProjectSandboxRecord> {
        let row = sqlx::query_as::<_, ProjectSandboxRow>(
            "INSERT INTO project_sandboxes \
                (id, project_id, tenant_id, sandbox_id, sandbox_type, status, \
                 created_at, started_at, last_accessed_at, health_checked_at, \
                 error_message, metadata_json, local_config) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::json, $13::json) \
             ON CONFLICT (project_id) DO UPDATE SET \
                 tenant_id = EXCLUDED.tenant_id, \
                 sandbox_id = EXCLUDED.sandbox_id, \
                 sandbox_type = EXCLUDED.sandbox_type, \
                 status = EXCLUDED.status, \
                 started_at = EXCLUDED.started_at, \
                 last_accessed_at = EXCLUDED.last_accessed_at, \
                 health_checked_at = EXCLUDED.health_checked_at, \
                 error_message = EXCLUDED.error_message, \
                 metadata_json = EXCLUDED.metadata_json, \
                 local_config = EXCLUDED.local_config \
             RETURNING id, project_id, tenant_id, sandbox_id, sandbox_type, status, \
                       created_at, started_at, last_accessed_at, health_checked_at, \
                       error_message, metadata_json::text AS metadata_text, \
                       local_config::text AS local_config_text",
        )
        .bind(record.id)
        .bind(record.project_id)
        .bind(record.tenant_id)
        .bind(record.sandbox_id)
        .bind(record.sandbox_type)
        .bind(record.status)
        .bind(record.created_at)
        .bind(record.started_at)
        .bind(record.last_accessed_at)
        .bind(record.health_checked_at)
        .bind(record.error_message)
        .bind(record.metadata_json.to_string())
        .bind(record.local_config.to_string())
        .fetch_one(&self.pool)
        .await
        .map_err(storage_err)?;
        row.into_record()
    }

    pub async fn delete_by_project(&self, project_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM project_sandboxes WHERE project_id = $1")
            .bind(project_id)
            .execute(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(result.rows_affected() > 0)
    }
}

#[derive(sqlx::FromRow)]
struct ProjectSandboxRow {
    id: String,
    project_id: String,
    tenant_id: String,
    sandbox_id: String,
    sandbox_type: String,
    status: String,
    created_at: DateTime<Utc>,
    started_at: Option<DateTime<Utc>>,
    last_accessed_at: DateTime<Utc>,
    health_checked_at: Option<DateTime<Utc>>,
    error_message: Option<String>,
    metadata_text: String,
    local_config_text: String,
}

impl ProjectSandboxRow {
    fn into_record(self) -> CoreResult<ProjectSandboxRecord> {
        Ok(ProjectSandboxRecord {
            id: self.id,
            project_id: self.project_id,
            tenant_id: self.tenant_id,
            sandbox_id: self.sandbox_id,
            sandbox_type: self.sandbox_type,
            status: self.status,
            created_at: self.created_at,
            started_at: self.started_at,
            last_accessed_at: self.last_accessed_at,
            health_checked_at: self.health_checked_at,
            error_message: self.error_message,
            metadata_json: parse_json("metadata_json", &self.metadata_text)?,
            local_config: parse_json("local_config", &self.local_config_text)?,
        })
    }
}

fn parse_json(label: &str, raw: &str) -> CoreResult<Value> {
    serde_json::from_str(raw)
        .map_err(|e| CoreError::Storage(format!("decode project_sandboxes.{label}: {e}")))
}

fn storage_err(e: sqlx::Error) -> CoreError {
    CoreError::Storage(e.to_string())
}
