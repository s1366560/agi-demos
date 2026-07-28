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
    content_revision, content_hash, created_at";

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
    pub content_revision: i64,
    pub content_hash: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy)]
pub struct ArtifactContentSaveCommand<'a> {
    pub artifact_id: &'a str,
    pub project_id: &'a str,
    pub tenant_id: &'a str,
    pub expected_revision: i64,
    pub idempotency_key: &'a str,
    pub request_hash: &'a str,
    pub content_hash: &'a str,
    pub object_key: &'a str,
    pub size_bytes: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactContentReceiptRecord {
    pub artifact_id: String,
    pub revision: i64,
    pub content_hash: String,
    pub duplicate: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactContentConflictRecord {
    pub reason_code: String,
    pub server_revision: i64,
    pub server_content_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ArtifactContentSaveResult {
    Saved(ArtifactContentReceiptRecord),
    Conflict(ArtifactContentConflictRecord),
    NotFound,
    NotReady,
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

    pub async fn initialize_content_hash(
        &self,
        artifact_id: &str,
        expected_revision: i64,
        content_hash: &str,
    ) -> CoreResult<Option<ArtifactRecord>> {
        let sql = format!(
            "UPDATE artifacts \
             SET content_hash = $3 \
             WHERE id = $1 AND content_revision = $2 AND content_hash IS NULL \
             RETURNING {ARTIFACT_COLS}"
        );
        let row = sqlx::query(&sql)
            .bind(artifact_id)
            .bind(expected_revision)
            .bind(content_hash)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("initialize artifact content hash: {e}")))?;
        if let Some(row) = row {
            return row_to_record(row).map(Some);
        }
        self.get(artifact_id).await
    }

    pub async fn save_content_v2(
        &self,
        command: ArtifactContentSaveCommand<'_>,
    ) -> CoreResult<ArtifactContentSaveResult> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(format!("begin artifact content save: {e}")))?;
        let authority = sqlx::query(
            "SELECT status, content_revision, content_hash \
             FROM artifacts \
             WHERE id = $1 AND project_id = $2 AND tenant_id = $3 \
             FOR UPDATE",
        )
        .bind(command.artifact_id)
        .bind(command.project_id)
        .bind(command.tenant_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|e| CoreError::Storage(format!("lock artifact content authority: {e}")))?;
        let Some(authority) = authority else {
            tx.rollback()
                .await
                .map_err(|e| CoreError::Storage(format!("rollback missing artifact save: {e}")))?;
            return Ok(ArtifactContentSaveResult::NotFound);
        };

        let status: String = authority.try_get("status").map_err(row_error)?;
        let server_revision: i64 = authority.try_get("content_revision").map_err(row_error)?;
        let server_content_hash: Option<String> =
            authority.try_get("content_hash").map_err(row_error)?;
        let server_content_hash = server_content_hash.ok_or_else(|| {
            CoreError::Storage("artifact content authority hash is not initialized".to_string())
        })?;

        let receipt = sqlx::query(
            "SELECT request_hash, resulting_revision, content_hash \
             FROM artifact_content_receipts \
             WHERE artifact_id = $1 AND project_id = $2 AND tenant_id = $3 \
               AND idempotency_key = $4",
        )
        .bind(command.artifact_id)
        .bind(command.project_id)
        .bind(command.tenant_id)
        .bind(command.idempotency_key)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|e| CoreError::Storage(format!("read artifact content receipt: {e}")))?;
        if let Some(receipt) = receipt {
            let request_hash: String = receipt.try_get("request_hash").map_err(row_error)?;
            if request_hash == command.request_hash {
                let result = ArtifactContentSaveResult::Saved(ArtifactContentReceiptRecord {
                    artifact_id: command.artifact_id.to_string(),
                    revision: receipt.try_get("resulting_revision").map_err(row_error)?,
                    content_hash: receipt.try_get("content_hash").map_err(row_error)?,
                    duplicate: true,
                });
                tx.commit().await.map_err(|e| {
                    CoreError::Storage(format!("commit artifact content replay: {e}"))
                })?;
                return Ok(result);
            }
            tx.commit().await.map_err(|e| {
                CoreError::Storage(format!("commit artifact idempotency conflict: {e}"))
            })?;
            return Ok(ArtifactContentSaveResult::Conflict(
                ArtifactContentConflictRecord {
                    reason_code: "artifact_content_idempotency_conflict".to_string(),
                    server_revision,
                    server_content_hash,
                },
            ));
        }

        if status != "ready" {
            tx.rollback().await.map_err(|e| {
                CoreError::Storage(format!("rollback non-ready artifact save: {e}"))
            })?;
            return Ok(ArtifactContentSaveResult::NotReady);
        }
        if server_revision != command.expected_revision {
            tx.commit().await.map_err(|e| {
                CoreError::Storage(format!("commit artifact revision conflict: {e}"))
            })?;
            return Ok(ArtifactContentSaveResult::Conflict(
                ArtifactContentConflictRecord {
                    reason_code: "artifact_content_revision_conflict".to_string(),
                    server_revision,
                    server_content_hash,
                },
            ));
        }
        let next_revision = server_revision
            .checked_add(1)
            .ok_or_else(|| CoreError::Storage("artifact content revision exhausted".to_string()))?;

        let updated = sqlx::query(
            "UPDATE artifacts \
             SET object_key = $4, size_bytes = $5, content_revision = $6, content_hash = $7, \
                 url = NULL, preview_url = NULL, error_message = NULL \
             WHERE id = $1 AND project_id = $2 AND tenant_id = $3 \
               AND content_revision = $8 AND status = 'ready'",
        )
        .bind(command.artifact_id)
        .bind(command.project_id)
        .bind(command.tenant_id)
        .bind(command.object_key)
        .bind(command.size_bytes)
        .bind(next_revision)
        .bind(command.content_hash)
        .bind(command.expected_revision)
        .execute(&mut *tx)
        .await
        .map_err(|e| CoreError::Storage(format!("advance artifact content pointer: {e}")))?;
        if updated.rows_affected() != 1 {
            return Err(CoreError::Storage(
                "artifact content pointer update lost its revision fence".to_string(),
            ));
        }

        sqlx::query(
            "INSERT INTO artifact_content_receipts \
             (artifact_id, project_id, tenant_id, idempotency_key, request_hash, \
              expected_revision, resulting_revision, content_hash, object_key, size_bytes) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
        )
        .bind(command.artifact_id)
        .bind(command.project_id)
        .bind(command.tenant_id)
        .bind(command.idempotency_key)
        .bind(command.request_hash)
        .bind(command.expected_revision)
        .bind(next_revision)
        .bind(command.content_hash)
        .bind(command.object_key)
        .bind(command.size_bytes)
        .execute(&mut *tx)
        .await
        .map_err(|e| CoreError::Storage(format!("record artifact content receipt: {e}")))?;
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(format!("commit artifact content save: {e}")))?;

        Ok(ArtifactContentSaveResult::Saved(
            ArtifactContentReceiptRecord {
                artifact_id: command.artifact_id.to_string(),
                revision: next_revision,
                content_hash: command.content_hash.to_string(),
                duplicate: false,
            },
        ))
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
        content_revision: row.try_get("content_revision").map_err(row_error)?,
        content_hash: row.try_get("content_hash").map_err(row_error)?,
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
