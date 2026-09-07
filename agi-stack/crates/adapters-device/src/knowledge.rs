//! Tenant-scoped knowledge storage. Legacy `memories` rows are deliberately
//! untouched: absent tenant ownership is not sufficient evidence to migrate.

use std::sync::Mutex;

use agistack_core::knowledge::{
    KnowledgeError, KnowledgeResult, KnowledgeScope, ScopedMemoryRepository,
};
use agistack_core::Memory;
use async_trait::async_trait;
use rusqlite::{params, Connection, OptionalExtension, Transaction};

pub struct SqliteKnowledgeRepository {
    conn: Mutex<Connection>,
}

impl SqliteKnowledgeRepository {
    pub fn open(path: &str) -> KnowledgeResult<Self> {
        Self::init(Connection::open(path).map_err(storage)?)
    }

    pub fn in_memory() -> KnowledgeResult<Self> {
        Self::init(Connection::open_in_memory().map_err(storage)?)
    }

    fn init(mut conn: Connection) -> KnowledgeResult<Self> {
        conn.busy_timeout(std::time::Duration::from_secs(5))
            .map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        tx.execute_batch(
            "CREATE TABLE IF NOT EXISTS knowledge_schema (version INTEGER NOT NULL);
             INSERT INTO knowledge_schema(version) SELECT 1
                 WHERE NOT EXISTS (SELECT 1 FROM knowledge_schema);",
        )
        .map_err(storage)?;
        let version: i64 = tx
            .query_row("SELECT version FROM knowledge_schema", [], |r| r.get(0))
            .map_err(storage)?;
        if version != 1 {
            return Err(KnowledgeError::Storage(
                "unsupported knowledge schema version".into(),
            ));
        }
        tx.execute_batch(
            "CREATE TABLE IF NOT EXISTS knowledge_memories (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision > 0),
                deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0, 1)),
                created_at_ms INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(tenant_id, project_id, id)
             );
             CREATE INDEX IF NOT EXISTS knowledge_memory_page
                 ON knowledge_memories(tenant_id, project_id, deleted, created_at_ms DESC, id);
             CREATE TABLE IF NOT EXISTS knowledge_processing_changes (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                operation TEXT NOT NULL CHECK(operation IN ('upsert', 'delete')),
                payload TEXT NOT NULL,
                UNIQUE(tenant_id, project_id, memory_id, revision)
             );",
        )
        .map_err(storage)?;
        tx.commit().map_err(storage)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }
}

fn storage(e: impl std::fmt::Display) -> KnowledgeError {
    KnowledgeError::Storage(e.to_string())
}

fn validate(scope: &KnowledgeScope, id: &str) -> KnowledgeResult<()> {
    if scope.tenant_id.trim().is_empty()
        || scope.project_id.trim().is_empty()
        || id.trim().is_empty()
    {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

fn validate_memory(scope: &KnowledgeScope, memory: &Memory, revision: u32) -> KnowledgeResult<()> {
    validate(scope, &memory.id)?;
    if memory.project_id != scope.project_id || revision == 0 || memory.version != revision {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

fn payload(conn: &Connection, scope: &KnowledgeScope, id: &str) -> KnowledgeResult<Option<String>> {
    conn.query_row(
        "SELECT payload FROM knowledge_memories WHERE tenant_id=?1 AND project_id=?2 AND id=?3 AND deleted=0",
        params![scope.tenant_id, scope.project_id, id], |r| r.get(0),
    ).optional().map_err(storage)
}

fn record_change(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    memory: &Memory,
    operation: &str,
    payload: &str,
) -> KnowledgeResult<()> {
    tx.execute(
        "INSERT INTO knowledge_processing_changes(tenant_id,project_id,memory_id,revision,operation,payload) VALUES(?1,?2,?3,?4,?5,?6)",
        params![scope.tenant_id,scope.project_id,memory.id,memory.version,operation,payload],
    ).map_err(storage)?;
    Ok(())
}

#[async_trait]
impl ScopedMemoryRepository for SqliteKnowledgeRepository {
    async fn create(&self, scope: &KnowledgeScope, memory: Memory) -> KnowledgeResult<Memory> {
        validate_memory(scope, &memory, 1)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        let json = serde_json::to_string(&memory).map_err(storage)?;
        let inserted = tx.execute(
            "INSERT INTO knowledge_memories(tenant_id,project_id,id,revision,created_at_ms,payload) VALUES(?1,?2,?3,1,?4,?5) ON CONFLICT(tenant_id,project_id,id) DO NOTHING",
            params![scope.tenant_id,scope.project_id,memory.id,memory.created_at_ms,json],
        ).map_err(storage)?;
        if inserted == 0 {
            return Err(KnowledgeError::Conflict);
        }
        record_change(&tx, scope, &memory, "upsert", &json)?;
        tx.commit().map_err(storage)?;
        Ok(memory)
    }

    async fn get(&self, scope: &KnowledgeScope, id: &str) -> KnowledgeResult<Option<Memory>> {
        validate(scope, id)?;
        let conn = self.conn.lock().map_err(storage)?;
        payload(&conn, scope, id)?
            .map(|json| serde_json::from_str(&json).map_err(storage))
            .transpose()
    }

    async fn list(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
        offset: usize,
    ) -> KnowledgeResult<Vec<Memory>> {
        validate(scope, "list")?;
        let conn = self.conn.lock().map_err(storage)?;
        let mut statement = conn.prepare(
            "SELECT payload FROM knowledge_memories WHERE tenant_id=?1 AND project_id=?2 AND deleted=0 ORDER BY created_at_ms DESC,id ASC LIMIT ?3 OFFSET ?4",
        ).map_err(storage)?;
        let rows = statement
            .query_map(
                params![
                    scope.tenant_id,
                    scope.project_id,
                    i64::try_from(limit).unwrap_or(i64::MAX),
                    i64::try_from(offset).unwrap_or(i64::MAX)
                ],
                |r| r.get::<_, String>(0),
            )
            .map_err(storage)?;
        rows.map(|row| serde_json::from_str(&row.map_err(storage)?).map_err(storage))
            .collect()
    }

    async fn update(
        &self,
        scope: &KnowledgeScope,
        mut memory: Memory,
        expected_revision: u32,
    ) -> KnowledgeResult<Memory> {
        validate_memory(scope, &memory, expected_revision)?;
        memory.version = expected_revision
            .checked_add(1)
            .ok_or(KnowledgeError::InvalidInput)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        let json = serde_json::to_string(&memory).map_err(storage)?;
        let updated = tx.execute(
            "UPDATE knowledge_memories SET revision=?4,payload=?5 WHERE tenant_id=?1 AND project_id=?2 AND id=?3 AND revision=?6 AND deleted=0",
            params![scope.tenant_id,scope.project_id,memory.id,memory.version,json,expected_revision],
        ).map_err(storage)?;
        if updated == 0 {
            return Err(if payload(&tx, scope, &memory.id)?.is_some() {
                KnowledgeError::Conflict
            } else {
                KnowledgeError::NotFound
            });
        }
        record_change(&tx, scope, &memory, "upsert", &json)?;
        tx.commit().map_err(storage)?;
        Ok(memory)
    }

    async fn delete(
        &self,
        scope: &KnowledgeScope,
        id: &str,
        expected_revision: u32,
    ) -> KnowledgeResult<()> {
        validate(scope, id)?;
        let revision = expected_revision
            .checked_add(1)
            .filter(|_| expected_revision > 0)
            .ok_or(KnowledgeError::InvalidInput)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
            .map_err(storage)?;
        let json = payload(&tx, scope, id)?.ok_or(KnowledgeError::NotFound)?;
        let mut memory: Memory = serde_json::from_str(&json).map_err(storage)?;
        if memory.version != expected_revision {
            return Err(KnowledgeError::Conflict);
        }
        memory.version = revision;
        let json = serde_json::to_string(&memory).map_err(storage)?;
        tx.execute(
            "UPDATE knowledge_memories SET revision=?4,deleted=1,payload=?5 WHERE tenant_id=?1 AND project_id=?2 AND id=?3 AND revision=?6 AND deleted=0",
            params![scope.tenant_id,scope.project_id,id,revision,json,expected_revision],
        ).map_err(storage)?;
        record_change(&tx, scope, &memory, "delete", &json)?;
        tx.commit().map_err(storage)?;
        Ok(())
    }
}
