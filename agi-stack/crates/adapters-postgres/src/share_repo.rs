//! Shared-DB adapter for Python-owned `memory_shares`.
//!
//! The memory sharing routes are part of the P2 identity/project surface, but the
//! data lives beside `memories` in the Python schema. This repository keeps the
//! SQL in the server-only Postgres adapter so the portable core and its wasm
//! target remain dependency-free.

use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

#[derive(Debug, Clone)]
pub struct ShareMemoryRecord {
    pub id: String,
    pub project_id: String,
    pub title: String,
    pub content: String,
    pub author_id: String,
    pub tags: serde_json::Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct ShareRecord {
    pub id: String,
    pub memory_id: String,
    pub share_token: Option<String>,
    pub shared_with_user_id: Option<String>,
    pub shared_with_project_id: Option<String>,
    pub permissions: serde_json::Value,
    pub shared_by: String,
    pub created_at: DateTime<Utc>,
    pub expires_at: Option<DateTime<Utc>>,
    pub access_count: i32,
}

pub struct NewShareRecord {
    pub id: String,
    pub memory_id: String,
    pub share_token: String,
    pub shared_with_user_id: Option<String>,
    pub shared_with_project_id: Option<String>,
    pub permissions: serde_json::Value,
    pub shared_by: String,
    pub expires_at: Option<DateTime<Utc>>,
}

pub struct PgShareRepository {
    pool: PgPool,
}

impl PgShareRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn find_memory(&self, memory_id: &str) -> CoreResult<Option<ShareMemoryRecord>> {
        let row = sqlx::query_as::<_, ShareMemoryRow>(
            "SELECT id, project_id, title, content, author_id, tags::text AS tags_text, \
                    created_at, updated_at \
             FROM memories WHERE id = $1",
        )
        .bind(memory_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(row.map(ShareMemoryRow::into_record))
    }

    pub async fn user_exists(&self, user_id: &str) -> CoreResult<bool> {
        let (exists,): (bool,) = sqlx::query_as("SELECT EXISTS(SELECT 1 FROM users WHERE id = $1)")
            .bind(user_id)
            .fetch_one(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(exists)
    }

    pub async fn project_exists(&self, project_id: &str) -> CoreResult<bool> {
        let (exists,): (bool,) =
            sqlx::query_as("SELECT EXISTS(SELECT 1 FROM projects WHERE id = $1)")
                .bind(project_id)
                .fetch_one(&self.pool)
                .await
                .map_err(storage_err)?;
        Ok(exists)
    }

    pub async fn user_can_admin_project(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> CoreResult<bool> {
        let (exists,): (bool,) = sqlx::query_as(
            "SELECT EXISTS(\
                SELECT 1 FROM user_projects \
                WHERE user_id = $1 AND project_id = $2 AND role IN ('owner', 'admin')\
            )",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(exists)
    }

    pub async fn explicit_target_share_exists(
        &self,
        memory_id: &str,
        target_type: &str,
        target_id: &str,
    ) -> CoreResult<bool> {
        let sql = match target_type {
            "user" => {
                "SELECT EXISTS(\
                    SELECT 1 FROM memory_shares \
                    WHERE memory_id = $1 AND shared_with_user_id = $2\
                )"
            }
            _ => {
                "SELECT EXISTS(\
                    SELECT 1 FROM memory_shares \
                    WHERE memory_id = $1 AND shared_with_project_id = $2\
                )"
            }
        };
        let (exists,): (bool,) = sqlx::query_as(sql)
            .bind(memory_id)
            .bind(target_id)
            .fetch_one(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(exists)
    }

    pub async fn create_share(&self, share: NewShareRecord) -> CoreResult<ShareRecord> {
        let permissions_json = serde_json::to_string(&share.permissions)
            .map_err(|e| CoreError::Storage(format!("encode share permissions: {e}")))?;
        let row = sqlx::query_as::<_, ShareRow>(
            "INSERT INTO memory_shares \
                (id, memory_id, share_token, shared_with_user_id, shared_with_project_id, \
                 permissions, shared_by, expires_at, access_count) \
             VALUES ($1, $2, $3, $4, $5, $6::json, $7, $8, 0) \
             RETURNING id, memory_id, share_token, shared_with_user_id, \
                       shared_with_project_id, permissions::text AS permissions_text, \
                       shared_by, created_at, expires_at, access_count",
        )
        .bind(share.id)
        .bind(share.memory_id)
        .bind(share.share_token)
        .bind(share.shared_with_user_id)
        .bind(share.shared_with_project_id)
        .bind(permissions_json)
        .bind(share.shared_by)
        .bind(share.expires_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(row.into_record())
    }

    pub async fn list_for_memory(&self, memory_id: &str) -> CoreResult<Vec<ShareRecord>> {
        let rows = sqlx::query_as::<_, ShareRow>(
            "SELECT id, memory_id, share_token, shared_with_user_id, shared_with_project_id, \
                    permissions::text AS permissions_text, shared_by, created_at, expires_at, \
                    access_count \
             FROM memory_shares \
             WHERE memory_id = $1 \
             ORDER BY created_at DESC",
        )
        .bind(memory_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(rows.into_iter().map(ShareRow::into_record).collect())
    }

    pub async fn find_share_by_id(&self, share_id: &str) -> CoreResult<Option<ShareRecord>> {
        let row = sqlx::query_as::<_, ShareRow>(
            "SELECT id, memory_id, share_token, shared_with_user_id, shared_with_project_id, \
                    permissions::text AS permissions_text, shared_by, created_at, expires_at, \
                    access_count \
             FROM memory_shares WHERE id = $1",
        )
        .bind(share_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(row.map(ShareRow::into_record))
    }

    pub async fn delete_share(&self, share_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM memory_shares WHERE id = $1")
            .bind(share_id)
            .execute(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn find_share_by_token(&self, share_token: &str) -> CoreResult<Option<ShareRecord>> {
        let row = sqlx::query_as::<_, ShareRow>(
            "SELECT id, memory_id, share_token, shared_with_user_id, shared_with_project_id, \
                    permissions::text AS permissions_text, shared_by, created_at, expires_at, \
                    access_count \
             FROM memory_shares WHERE share_token = $1",
        )
        .bind(share_token)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(row.map(ShareRow::into_record))
    }

    pub async fn increment_access_count(&self, share_id: &str) -> CoreResult<()> {
        sqlx::query("UPDATE memory_shares SET access_count = access_count + 1 WHERE id = $1")
            .bind(share_id)
            .execute(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(())
    }
}

#[derive(sqlx::FromRow)]
struct ShareMemoryRow {
    id: String,
    project_id: String,
    title: String,
    content: String,
    author_id: String,
    tags_text: Option<String>,
    created_at: DateTime<Utc>,
    updated_at: Option<DateTime<Utc>>,
}

impl ShareMemoryRow {
    fn into_record(self) -> ShareMemoryRecord {
        ShareMemoryRecord {
            id: self.id,
            project_id: self.project_id,
            title: self.title,
            content: self.content,
            author_id: self.author_id,
            tags: parse_json_or(self.tags_text, serde_json::json!([])),
            created_at: self.created_at,
            updated_at: self.updated_at,
        }
    }
}

#[derive(sqlx::FromRow)]
struct ShareRow {
    id: String,
    memory_id: String,
    share_token: Option<String>,
    shared_with_user_id: Option<String>,
    shared_with_project_id: Option<String>,
    permissions_text: Option<String>,
    shared_by: String,
    created_at: DateTime<Utc>,
    expires_at: Option<DateTime<Utc>>,
    access_count: i32,
}

impl ShareRow {
    fn into_record(self) -> ShareRecord {
        ShareRecord {
            id: self.id,
            memory_id: self.memory_id,
            share_token: self.share_token,
            shared_with_user_id: self.shared_with_user_id,
            shared_with_project_id: self.shared_with_project_id,
            permissions: parse_json_or(self.permissions_text, serde_json::json!({})),
            shared_by: self.shared_by,
            created_at: self.created_at,
            expires_at: self.expires_at,
            access_count: self.access_count,
        }
    }
}

fn parse_json_or(text: Option<String>, default: serde_json::Value) -> serde_json::Value {
    text.and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(default)
}

fn storage_err(e: sqlx::Error) -> CoreError {
    CoreError::Storage(e.to_string())
}
