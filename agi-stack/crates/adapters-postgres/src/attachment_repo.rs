//! Adapter over the Python-owned `attachments` table.
//!
//! Rust owns attachment list/detail metadata reads plus exact hard-delete for
//! this P7 slice. Multipart upload, simple upload, download URL generation, and
//! upload-time object-storage side effects remain Python-owned.

use serde_json::json;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const ATTACHMENT_COLS: &str = "id, conversation_id, project_id, tenant_id, filename, \
    mime_type, size_bytes, object_key, purpose, status, sandbox_path, created_at, error_message";
const ATTACHMENT_COLS_ALIASED: &str = "a.id, a.conversation_id, a.project_id, a.tenant_id, \
    a.filename, a.mime_type, a.size_bytes, a.object_key, a.purpose, a.status, a.sandbox_path, \
    a.created_at, a.error_message";

#[derive(Debug, Clone, PartialEq)]
pub struct AttachmentRecord {
    pub id: String,
    pub conversation_id: String,
    pub project_id: String,
    pub tenant_id: String,
    pub filename: String,
    pub mime_type: String,
    pub size_bytes: i64,
    pub object_key: String,
    pub purpose: String,
    pub status: String,
    pub sandbox_path: Option<String>,
    pub created_at: DateTime<Utc>,
    pub error_message: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AttachmentUploadRecord {
    pub id: String,
    pub conversation_id: String,
    pub project_id: String,
    pub tenant_id: String,
    pub filename: String,
    pub mime_type: String,
    pub size_bytes: i64,
    pub object_key: String,
    pub purpose: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy)]
pub struct AttachmentListQuery<'a> {
    pub user_id: &'a str,
    pub conversation_id: &'a str,
    pub status: Option<&'a str>,
}

pub struct PgAttachmentRepository {
    pool: PgPool,
}

impl PgAttachmentRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_visible(
        &self,
        query: AttachmentListQuery<'_>,
    ) -> CoreResult<Vec<AttachmentRecord>> {
        let rows = match blank_to_none(query.status) {
            Some(status) => {
                let sql = format!(
                    "SELECT {cols} \
                     FROM attachments a \
                     JOIN projects p ON p.id = a.project_id \
                     LEFT JOIN users u ON u.id = $2 \
                     WHERE a.conversation_id = $1 \
                       AND a.status = $3 \
                       AND a.tenant_id = p.tenant_id \
                       AND (COALESCE(u.is_superuser, false) OR EXISTS (\
                           SELECT 1 FROM user_projects up \
                           WHERE up.user_id = $2 AND up.project_id = a.project_id\
                       )) \
                     ORDER BY a.created_at",
                    cols = ATTACHMENT_COLS_ALIASED
                );
                sqlx::query(&sql)
                    .bind(query.conversation_id)
                    .bind(query.user_id)
                    .bind(status)
                    .fetch_all(&self.pool)
                    .await
            }
            None => {
                let sql = format!(
                    "SELECT {cols} \
                     FROM attachments a \
                     JOIN projects p ON p.id = a.project_id \
                     LEFT JOIN users u ON u.id = $2 \
                     WHERE a.conversation_id = $1 \
                       AND a.tenant_id = p.tenant_id \
                       AND (COALESCE(u.is_superuser, false) OR EXISTS (\
                           SELECT 1 FROM user_projects up \
                           WHERE up.user_id = $2 AND up.project_id = a.project_id\
                       )) \
                     ORDER BY a.created_at",
                    cols = ATTACHMENT_COLS_ALIASED
                );
                sqlx::query(&sql)
                    .bind(query.conversation_id)
                    .bind(query.user_id)
                    .fetch_all(&self.pool)
                    .await
            }
        }
        .map_err(|e| CoreError::Storage(format!("list attachments: {e}")))?;

        rows.into_iter().map(row_to_record).collect()
    }

    pub async fn get(&self, attachment_id: &str) -> CoreResult<Option<AttachmentRecord>> {
        let sql = format!("SELECT {ATTACHMENT_COLS} FROM attachments WHERE id = $1");
        let row = sqlx::query(&sql)
            .bind(attachment_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get attachment: {e}")))?;
        row.map(row_to_record).transpose()
    }

    pub async fn delete(&self, attachment_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM attachments WHERE id = $1")
            .bind(attachment_id)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("delete attachment: {e}")))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn insert_uploaded(
        &self,
        record: AttachmentUploadRecord,
    ) -> CoreResult<AttachmentRecord> {
        let row = sqlx::query(
            "INSERT INTO attachments \
             (id, conversation_id, project_id, tenant_id, filename, mime_type, size_bytes, \
              object_key, purpose, status, upload_id, total_parts, uploaded_parts, \
              sandbox_path, file_metadata, error_message, created_at, expires_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'uploaded', NULL, NULL, 0, \
                     NULL, $10, NULL, $11, $11 + INTERVAL '24 hours') \
             RETURNING id, conversation_id, project_id, tenant_id, filename, mime_type, \
                       size_bytes, object_key, purpose, status, sandbox_path, created_at, \
                       error_message",
        )
        .bind(record.id)
        .bind(record.conversation_id)
        .bind(record.project_id)
        .bind(record.tenant_id)
        .bind(record.filename)
        .bind(record.mime_type)
        .bind(record.size_bytes)
        .bind(record.object_key)
        .bind(record.purpose)
        .bind(json!({}))
        .bind(record.created_at)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("insert uploaded attachment: {e}")))?;
        row_to_record(row)
    }

    pub async fn accessible_project_tenant(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> CoreResult<Option<String>> {
        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("check attachment user access: {e}")))?
        .map(|(is_superuser,)| is_superuser)
        .unwrap_or(false);

        let row = if is_superuser {
            sqlx::query_as::<_, (String,)>("SELECT tenant_id FROM projects WHERE id = $1")
                .bind(project_id)
                .fetch_optional(&self.pool)
                .await
        } else {
            sqlx::query_as::<_, (String,)>(
                "SELECT p.tenant_id \
                 FROM projects p \
                 JOIN user_projects up ON up.project_id = p.id \
                 WHERE p.id = $1 AND up.user_id = $2",
            )
            .bind(project_id)
            .bind(user_id)
            .fetch_optional(&self.pool)
            .await
        }
        .map_err(|e| CoreError::Storage(format!("read accessible project tenant: {e}")))?;

        Ok(row.map(|(tenant_id,)| tenant_id))
    }
}

fn row_to_record(row: sqlx::postgres::PgRow) -> CoreResult<AttachmentRecord> {
    Ok(AttachmentRecord {
        id: row.try_get("id").map_err(row_error)?,
        conversation_id: row.try_get("conversation_id").map_err(row_error)?,
        project_id: row.try_get("project_id").map_err(row_error)?,
        tenant_id: row.try_get("tenant_id").map_err(row_error)?,
        filename: row.try_get("filename").map_err(row_error)?,
        mime_type: row.try_get("mime_type").map_err(row_error)?,
        size_bytes: row.try_get("size_bytes").map_err(row_error)?,
        object_key: row.try_get("object_key").map_err(row_error)?,
        purpose: row.try_get("purpose").map_err(row_error)?,
        status: row.try_get("status").map_err(row_error)?,
        sandbox_path: row.try_get("sandbox_path").map_err(row_error)?,
        created_at: row.try_get("created_at").map_err(row_error)?,
        error_message: row.try_get("error_message").map_err(row_error)?,
    })
}

fn row_error(err: sqlx::Error) -> CoreError {
    CoreError::Storage(format!("read attachment row: {err}"))
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
