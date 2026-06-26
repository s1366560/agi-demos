//! Embedded SQLite implementation of [`MemoryRepository`] — the on-device
//! storage path (server would use Postgres/pgvector instead, same port).
//!
//! Note: rusqlite is synchronous; for the spike we call it directly inside the
//! async methods (work is tiny). A production adapter would offload to a thread
//! pool. This crate also *overrides* `search_by_project` to push the filter into
//! SQL, demonstrating the port's override path (vs the in-core default).

use std::sync::Mutex;

use async_trait::async_trait;
use rusqlite::{params, Connection, OptionalExtension};

use memstack_core::model::{Entity, Memory};
use memstack_core::ports::{CoreError, CoreResult, MemoryRepository};

pub struct SqliteMemoryRepository {
    conn: Mutex<Connection>,
}

impl SqliteMemoryRepository {
    pub fn open(path: &str) -> CoreResult<Self> {
        let conn = Connection::open(path).map_err(to_storage)?;
        Self::init(conn)
    }

    pub fn in_memory() -> CoreResult<Self> {
        let conn = Connection::open_in_memory().map_err(to_storage)?;
        Self::init(conn)
    }

    fn init(conn: Connection) -> CoreResult<Self> {
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                author_id TEXT NOT NULL,
                content_type TEXT NOT NULL,
                tags TEXT NOT NULL,
                entities TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                embedding TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_mem_project
                ON memories(project_id, created_at_ms DESC);",
        )
        .map_err(to_storage)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }
}

fn to_storage<E: std::fmt::Display>(e: E) -> CoreError {
    CoreError::Storage(e.to_string())
}

fn row_to_memory(row: &rusqlite::Row) -> rusqlite::Result<Memory> {
    let tags_json: String = row.get("tags")?;
    let entities_json: String = row.get("entities")?;
    let embedding_json: Option<String> = row.get("embedding")?;
    Ok(Memory {
        id: row.get("id")?,
        project_id: row.get("project_id")?,
        title: row.get("title")?,
        content: row.get("content")?,
        author_id: row.get("author_id")?,
        content_type: row.get("content_type")?,
        tags: serde_json::from_str(&tags_json).unwrap_or_default(),
        entities: serde_json::from_str::<Vec<Entity>>(&entities_json).unwrap_or_default(),
        version: row.get("version")?,
        status: row.get("status")?,
        created_at_ms: row.get("created_at_ms")?,
        embedding: embedding_json.and_then(|s| serde_json::from_str(&s).ok()),
    })
}

#[async_trait]
impl MemoryRepository for SqliteMemoryRepository {
    async fn save(&self, memory: Memory) -> CoreResult<Memory> {
        let conn = self.conn.lock().map_err(to_storage)?;
        let tags = serde_json::to_string(&memory.tags).map_err(to_storage)?;
        let entities = serde_json::to_string(&memory.entities).map_err(to_storage)?;
        let embedding = match &memory.embedding {
            Some(e) => Some(serde_json::to_string(e).map_err(to_storage)?),
            None => None,
        };
        conn.execute(
            "INSERT OR REPLACE INTO memories
             (id,project_id,title,content,author_id,content_type,tags,entities,version,status,created_at_ms,embedding)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)",
            params![
                memory.id, memory.project_id, memory.title, memory.content, memory.author_id,
                memory.content_type, tags, entities, memory.version, memory.status,
                memory.created_at_ms, embedding
            ],
        )
        .map_err(to_storage)?;
        Ok(memory)
    }

    async fn find_by_id(&self, id: &str) -> CoreResult<Option<Memory>> {
        let conn = self.conn.lock().map_err(to_storage)?;
        let mut stmt = conn
            .prepare("SELECT * FROM memories WHERE id = ?1")
            .map_err(to_storage)?;
        let mem = stmt
            .query_row(params![id], |r| row_to_memory(r))
            .optional()
            .map_err(to_storage)?;
        Ok(mem)
    }

    async fn list_by_project(
        &self,
        project_id: &str,
        limit: usize,
        offset: usize,
    ) -> CoreResult<Vec<Memory>> {
        let conn = self.conn.lock().map_err(to_storage)?;
        let mut stmt = conn
            .prepare(
                "SELECT * FROM memories WHERE project_id = ?1
                 ORDER BY created_at_ms DESC LIMIT ?2 OFFSET ?3",
            )
            .map_err(to_storage)?;
        let rows = stmt
            .query_map(params![project_id, limit as i64, offset as i64], |r| {
                row_to_memory(r)
            })
            .map_err(to_storage)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r.map_err(to_storage)?);
        }
        Ok(out)
    }

    /// Override: push the search into SQL instead of using the in-core fallback.
    async fn search_by_project(
        &self,
        project_id: &str,
        query: &str,
        limit: usize,
    ) -> CoreResult<Vec<Memory>> {
        let conn = self.conn.lock().map_err(to_storage)?;
        let like = format!("%{}%", query.to_lowercase());
        let mut stmt = conn
            .prepare(
                "SELECT * FROM memories
                 WHERE project_id = ?1 AND (lower(title) LIKE ?2 OR lower(content) LIKE ?2)
                 ORDER BY created_at_ms DESC LIMIT ?3",
            )
            .map_err(to_storage)?;
        let rows = stmt
            .query_map(params![project_id, like, limit as i64], |r| row_to_memory(r))
            .map_err(to_storage)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r.map_err(to_storage)?);
        }
        Ok(out)
    }

    async fn delete(&self, id: &str) -> CoreResult<bool> {
        let conn = self.conn.lock().map_err(to_storage)?;
        let n = conn
            .execute("DELETE FROM memories WHERE id = ?1", params![id])
            .map_err(to_storage)?;
        Ok(n > 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use memstack_adapters_mem::{FixedClock, HashEmbedding, StubLlm};
    use memstack_core::{Episode, MemoryService, SourceType};
    use std::sync::Arc;

    #[test]
    fn sqlite_repo_persists_and_searches_via_sql() {
        let repo = Arc::new(SqliteMemoryRepository::in_memory().unwrap());
        let service = MemoryService::new(
            repo,
            Arc::new(StubLlm),
            Arc::new(HashEmbedding::new(8)),
            Arc::new(FixedClock(1)),
        );

        let episode = Episode {
            content: "Local-first apps store data on device using sqlite".to_string(),
            source_type: SourceType::Text,
            valid_at_ms: 0,
            name: None,
            project_id: Some("p1".into()),
            user_id: None,
        };

        let mem =
            futures::executor::block_on(service.ingest_episode("p1", "u1", &episode)).unwrap();
        let got = futures::executor::block_on(service.get(&mem.id))
            .unwrap()
            .unwrap();
        assert_eq!(got.id, mem.id);
        assert_eq!(got.embedding.unwrap().len(), 8);

        let hits = futures::executor::block_on(service.search("p1", "sqlite", 10)).unwrap();
        assert_eq!(hits.len(), 1);
        let miss = futures::executor::block_on(service.search("p1", "postgres", 10)).unwrap();
        assert_eq!(miss.len(), 0);
    }
}
