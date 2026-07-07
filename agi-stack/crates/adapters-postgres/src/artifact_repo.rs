//! Adapter over the Python-owned `artifacts` table.
//!
//! Rust owns list/detail REST reads plus exact content-save and soft-delete
//! metadata updates for this P7 slice. Upload/multipart, URL refresh, and
//! download remain Python-owned.

use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const ARTIFACT_COLS: &str = "id, project_id, tenant_id, sandbox_id, tool_execution_id, \
    conversation_id, filename, mime_type, category, size_bytes, object_key, url, preview_url, status, \
    error_message, source_tool, source_path, COALESCE(artifact_metadata, '{}'::json) AS metadata, \
    created_at";

#[derive(Debug, Clone, PartialEq)]
pub struct ArtifactRecord {
    pub id: String,
    pub project_id: String,
    pub tenant_id: String,
    pub sandbox_id: Option<String>,
    pub tool_execution_id: Option<String>,
    pub conversation_id: Option<String>,
    pub filename: String,
    pub mime_type: String,
    pub category: String,
    pub size_bytes: i64,
    pub object_key: String,
    pub url: Option<String>,
    pub preview_url: Option<String>,
    pub status: String,
    pub error_message: Option<String>,
    pub source_tool: Option<String>,
    pub source_path: Option<String>,
    pub metadata: serde_json::Value,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy)]
pub struct ArtifactListQuery<'a> {
    pub project_id: &'a str,
    pub category: Option<&'a str>,
    pub tool_execution_id: Option<&'a str>,
    pub limit: i64,
}

pub struct PgArtifactRepository {
    pool: PgPool,
}

impl PgArtifactRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list(&self, query: ArtifactListQuery<'_>) -> CoreResult<Vec<ArtifactRecord>> {
        let limit = query.limit.clamp(1, 500);
        let rows = match (
            blank_to_none(query.tool_execution_id),
            blank_to_none(query.category),
        ) {
            (Some(tool_execution_id), Some(category)) => {
                let sql = format!(
                    "SELECT {ARTIFACT_COLS} FROM artifacts \
                     WHERE project_id = $1 \
                       AND tool_execution_id = $2 \
                       AND status = 'ready' \
                       AND category = $3 \
                     ORDER BY created_at DESC \
                     LIMIT $4"
                );
                sqlx::query(&sql)
                    .bind(query.project_id)
                    .bind(tool_execution_id)
                    .bind(category)
                    .bind(limit)
                    .fetch_all(&self.pool)
                    .await
            }
            (Some(tool_execution_id), None) => {
                let sql = format!(
                    "SELECT {ARTIFACT_COLS} FROM artifacts \
                     WHERE project_id = $1 \
                       AND tool_execution_id = $2 \
                       AND status = 'ready' \
                     ORDER BY created_at DESC \
                     LIMIT $3"
                );
                sqlx::query(&sql)
                    .bind(query.project_id)
                    .bind(tool_execution_id)
                    .bind(limit)
                    .fetch_all(&self.pool)
                    .await
            }
            (None, Some(category)) => {
                let sql = format!(
                    "SELECT {ARTIFACT_COLS} FROM artifacts \
                     WHERE project_id = $1 \
                       AND status = 'ready' \
                       AND category = $2 \
                     ORDER BY created_at DESC \
                     LIMIT $3"
                );
                sqlx::query(&sql)
                    .bind(query.project_id)
                    .bind(category)
                    .bind(limit)
                    .fetch_all(&self.pool)
                    .await
            }
            (None, None) => {
                let sql = format!(
                    "SELECT {ARTIFACT_COLS} FROM artifacts \
                     WHERE project_id = $1 \
                       AND status = 'ready' \
                     ORDER BY created_at DESC \
                     LIMIT $2"
                );
                sqlx::query(&sql)
                    .bind(query.project_id)
                    .bind(limit)
                    .fetch_all(&self.pool)
                    .await
            }
        }
        .map_err(|e| CoreError::Storage(format!("list artifacts: {e}")))?;

        rows.into_iter().map(row_to_record).collect()
    }

    pub async fn get(&self, artifact_id: &str) -> CoreResult<Option<ArtifactRecord>> {
        let sql = format!("SELECT {ARTIFACT_COLS} FROM artifacts WHERE id = $1");
        let row = sqlx::query(&sql)
            .bind(artifact_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get artifact: {e}")))?;
        row.map(row_to_record).transpose()
    }

    pub async fn update_content_metadata(
        &self,
        artifact_id: &str,
        size_bytes: i64,
    ) -> CoreResult<Option<ArtifactRecord>> {
        let sql = format!(
            "UPDATE artifacts \
             SET size_bytes = $2, error_message = NULL \
             WHERE id = $1 AND status = 'ready' \
             RETURNING {ARTIFACT_COLS}"
        );
        let row = sqlx::query(&sql)
            .bind(artifact_id)
            .bind(size_bytes)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("update artifact content metadata: {e}")))?;
        row.map(row_to_record).transpose()
    }

    pub async fn mark_deleted(&self, artifact_id: &str) -> CoreResult<Option<ArtifactRecord>> {
        let sql = format!(
            "UPDATE artifacts \
             SET status = 'deleted', error_message = NULL \
             WHERE id = $1 \
             RETURNING {ARTIFACT_COLS}"
        );
        let row = sqlx::query(&sql)
            .bind(artifact_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("mark artifact deleted: {e}")))?;
        row.map(row_to_record).transpose()
    }
}

fn row_to_record(row: sqlx::postgres::PgRow) -> CoreResult<ArtifactRecord> {
    Ok(ArtifactRecord {
        id: row.try_get("id").map_err(row_error)?,
        project_id: row.try_get("project_id").map_err(row_error)?,
        tenant_id: row.try_get("tenant_id").map_err(row_error)?,
        sandbox_id: row.try_get("sandbox_id").map_err(row_error)?,
        tool_execution_id: row.try_get("tool_execution_id").map_err(row_error)?,
        conversation_id: row.try_get("conversation_id").map_err(row_error)?,
        filename: row.try_get("filename").map_err(row_error)?,
        mime_type: row.try_get("mime_type").map_err(row_error)?,
        category: row.try_get("category").map_err(row_error)?,
        size_bytes: row.try_get("size_bytes").map_err(row_error)?,
        object_key: row.try_get("object_key").map_err(row_error)?,
        url: row.try_get("url").map_err(row_error)?,
        preview_url: row.try_get("preview_url").map_err(row_error)?,
        status: row.try_get("status").map_err(row_error)?,
        error_message: row.try_get("error_message").map_err(row_error)?,
        source_tool: row.try_get("source_tool").map_err(row_error)?,
        source_path: row.try_get("source_path").map_err(row_error)?,
        metadata: row.try_get("metadata").map_err(row_error)?,
        created_at: row.try_get("created_at").map_err(row_error)?,
    })
}

fn row_error(err: sqlx::Error) -> CoreError {
    CoreError::Storage(format!("read artifact row: {err}"))
}

fn blank_to_none(value: Option<&str>) -> Option<&str> {
    value.and_then(|raw| {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed)
        }
    })
}
