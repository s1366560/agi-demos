//! [`PgMemoryRepository`] — the production [`MemoryRepository`] over the
//! **Python-owned `memories` table** (shared-DB strangler, plan.md Section 14).
//!
//! Column names and types mirror `Memory` in
//! `src/infrastructure/adapters/secondary/persistence/models.py` exactly, so a
//! row written here is indistinguishable from one written by the Python backend
//! and vice versa. The core [`Memory`] is a reduced projection: the DB-required
//! columns the core does not model (`relationships`, `collaborators`, `is_public`,
//! `processing_status`, `meta`) are written with their Python defaults so the row
//! stays valid for the still-live Python readers.
//!
//! The JSON columns are read back via a `::text` cast and parsed with serde —
//! robust regardless of whether SQLAlchemy emitted `json` or `jsonb`, and
//! tolerant of rows Python wrote with a richer entity shape.

use async_trait::async_trait;
use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::model::{Entity, Memory};
use agistack_core::ports::{CoreError, CoreResult, MemoryRepository};

use crate::PgPool;

/// `MemoryRepository` backed by a shared PostgreSQL `memories` table.
pub struct PgMemoryRepository {
    pool: PgPool,
}

impl PgMemoryRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

/// Row projection of the columns the core cares about. JSON columns arrive as
/// text (`tags::text`, `entities::text`) and are parsed in [`MemoryRow::into_core`].
#[derive(sqlx::FromRow)]
struct MemoryRow {
    id: String,
    project_id: String,
    title: String,
    content: String,
    author_id: String,
    content_type: String,
    tags_text: Option<String>,
    entities_text: Option<String>,
    version: i32,
    status: String,
    created_at: DateTime<Utc>,
}

/// Parse a JSON-array-of-strings text blob into `Vec<String>`, tolerating
/// null/non-array/non-string entries (returns what it can).
fn parse_tags(text: Option<String>) -> Vec<String> {
    let Some(text) = text else {
        return Vec::new();
    };
    match serde_json::from_str::<serde_json::Value>(&text) {
        Ok(serde_json::Value::Array(items)) => items
            .into_iter()
            .filter_map(|v| v.as_str().map(str::to_owned))
            .collect(),
        _ => Vec::new(),
    }
}

/// Parse the `entities` JSON into the core [`Entity`] shape. Python may store a
/// richer dict per entity; we extract `name` plus `kind` (falling back to `type`,
/// matching the graph schema), skipping entries without a name.
fn parse_entities(text: Option<String>) -> Vec<Entity> {
    let Some(text) = text else {
        return Vec::new();
    };
    let Ok(serde_json::Value::Array(items)) = serde_json::from_str::<serde_json::Value>(&text)
    else {
        return Vec::new();
    };
    items
        .into_iter()
        .filter_map(|item| {
            let name = item.get("name").and_then(|v| v.as_str())?.to_string();
            let kind = item
                .get("kind")
                .or_else(|| item.get("type"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            Some(Entity { name, kind })
        })
        .collect()
}

impl MemoryRow {
    fn into_core(self) -> Memory {
        Memory {
            id: self.id,
            project_id: self.project_id,
            title: self.title,
            content: self.content,
            author_id: self.author_id,
            content_type: self.content_type,
            tags: parse_tags(self.tags_text),
            entities: parse_entities(self.entities_text),
            version: self.version.max(0) as u32,
            status: self.status,
            created_at_ms: self.created_at.timestamp_millis(),
            // The shared `memories` table carries no embedding column (Python
            // keeps vectors in the graph); the embedding lives in the Rust-owned
            // `agistack_memory_vectors` table instead. See `PgVectorIndex`.
            embedding: None,
        }
    }
}

const SELECT_COLS: &str = "id, project_id, title, content, author_id, content_type, \
    tags::text AS tags_text, entities::text AS entities_text, version, status, created_at";

fn storage_err(e: sqlx::Error) -> CoreError {
    CoreError::Storage(e.to_string())
}

#[async_trait]
impl MemoryRepository for PgMemoryRepository {
    async fn save(&self, memory: Memory) -> CoreResult<Memory> {
        let tags_json = serde_json::to_string(&memory.tags)
            .map_err(|e| CoreError::Storage(format!("encode tags: {e}")))?;
        let entities_json = serde_json::to_string(&memory.entities)
            .map_err(|e| CoreError::Storage(format!("encode entities: {e}")))?;

        // Insert-or-replace by id. DB-required columns the core does not model are
        // written with their Python defaults so the row remains valid for Python
        // readers. `processing_status = COMPLETED` because the Rust ingest path
        // extracts + embeds synchronously before saving.
        sqlx::query(
            "INSERT INTO memories \
             (id, project_id, title, content, content_type, tags, entities, relationships, \
              version, author_id, collaborators, is_public, status, processing_status, meta, created_at) \
             VALUES ($1, $2, $3, $4, $5, $6::json, $7::json, '[]'::json, $8, $9, '[]'::json, false, \
                     $10, 'COMPLETED', '{}'::json, to_timestamp($11::double precision / 1000.0)) \
             ON CONFLICT (id) DO UPDATE SET \
               title = EXCLUDED.title, content = EXCLUDED.content, \
               content_type = EXCLUDED.content_type, tags = EXCLUDED.tags, \
               entities = EXCLUDED.entities, version = EXCLUDED.version, \
               status = EXCLUDED.status, updated_at = now()",
        )
        .bind(&memory.id)
        .bind(&memory.project_id)
        .bind(&memory.title)
        .bind(&memory.content)
        .bind(&memory.content_type)
        .bind(&tags_json)
        .bind(&entities_json)
        .bind(memory.version as i32)
        .bind(&memory.author_id)
        .bind(&memory.status)
        .bind(memory.created_at_ms)
        .execute(&self.pool)
        .await
        .map_err(storage_err)?;

        Ok(memory)
    }

    async fn find_by_id(&self, id: &str) -> CoreResult<Option<Memory>> {
        let sql = format!("SELECT {SELECT_COLS} FROM memories WHERE id = $1");
        let row = sqlx::query_as::<_, MemoryRow>(&sql)
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(row.map(MemoryRow::into_core))
    }

    /// Override the per-id loop with a single round-trip: semantic-search
    /// hydration fetches k rows per query, so k sequential `find_by_id`s would
    /// cost k network RTTs.
    async fn find_by_ids(&self, ids: &[String]) -> CoreResult<Vec<Memory>> {
        if ids.is_empty() {
            return Ok(Vec::new());
        }
        let sql = format!("SELECT {SELECT_COLS} FROM memories WHERE id = ANY($1)");
        let rows = sqlx::query_as::<_, MemoryRow>(&sql)
            .bind(ids)
            .fetch_all(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(rows.into_iter().map(MemoryRow::into_core).collect())
    }

    async fn list_by_project(
        &self,
        project_id: &str,
        limit: usize,
        offset: usize,
    ) -> CoreResult<Vec<Memory>> {
        let sql = format!(
            "SELECT {SELECT_COLS} FROM memories WHERE project_id = $1 \
             ORDER BY created_at DESC, id ASC OFFSET $2 LIMIT $3"
        );
        let rows = sqlx::query_as::<_, MemoryRow>(&sql)
            .bind(project_id)
            .bind(offset as i64)
            .bind(limit as i64)
            .fetch_all(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(rows.into_iter().map(MemoryRow::into_core).collect())
    }

    /// Override the in-core fallback: push the substring filter into SQL as a
    /// case-insensitive `ILIKE` over title/content, matching the Python
    /// `list_memories` search path exactly (`Memory.title.ilike` / `content.ilike`).
    async fn search_by_project(
        &self,
        project_id: &str,
        query: &str,
        limit: usize,
    ) -> CoreResult<Vec<Memory>> {
        let pattern = format!("%{}%", query.replace('%', "\\%").replace('_', "\\_"));
        let sql = format!(
            "SELECT {SELECT_COLS} FROM memories \
             WHERE project_id = $1 AND (title ILIKE $2 OR content ILIKE $2) \
             ORDER BY created_at DESC, id ASC LIMIT $3"
        );
        let rows = sqlx::query_as::<_, MemoryRow>(&sql)
            .bind(project_id)
            .bind(&pattern)
            .bind(limit as i64)
            .fetch_all(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(rows.into_iter().map(MemoryRow::into_core).collect())
    }

    async fn delete(&self, id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM memories WHERE id = $1")
            .bind(id)
            .execute(&self.pool)
            .await
            .map_err(storage_err)?;
        Ok(result.rows_affected() > 0)
    }

    /// Efficient `SELECT count(*)` with the same optional `ILIKE` filter as
    /// [`search_by_project`](MemoryRepository::search_by_project) — backs the
    /// paginated list `total` without materializing rows.
    async fn count_by_project(&self, project_id: &str, search: Option<&str>) -> CoreResult<usize> {
        let row: (i64,) = match search {
            Some(query) => {
                let pattern = format!("%{}%", query.replace('%', "\\%").replace('_', "\\_"));
                sqlx::query_as(
                    "SELECT count(*) FROM memories \
                     WHERE project_id = $1 AND (title ILIKE $2 OR content ILIKE $2)",
                )
                .bind(project_id)
                .bind(&pattern)
                .fetch_one(&self.pool)
                .await
                .map_err(storage_err)?
            }
            None => sqlx::query_as("SELECT count(*) FROM memories WHERE project_id = $1")
                .bind(project_id)
                .fetch_one(&self.pool)
                .await
                .map_err(storage_err)?,
        };
        Ok(row.0.max(0) as usize)
    }
}
