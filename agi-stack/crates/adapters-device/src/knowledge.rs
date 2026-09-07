//! Tenant-scoped knowledge storage. Legacy `memories` rows are deliberately
//! untouched: absent tenant ownership is not sufficient evidence to migrate.

use std::sync::Mutex;

use agistack_core::knowledge::{
    KnowledgeError, KnowledgeResult, KnowledgeScope, MemoryChange, MemoryMutation,
    MemoryMutationOutcome, ScopedMemoryRepository,
};
use agistack_core::Memory;
use async_trait::async_trait;
use rusqlite::{params, Connection, OptionalExtension};

mod mutations;
mod resolution;
mod push;
mod pull;
mod sync;

pub const KNOWLEDGE_SCHEMA_VERSION: i64 = 6;

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
        if !(1..=KNOWLEDGE_SCHEMA_VERSION).contains(&version) {
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
        tx.execute_batch(
            "CREATE TABLE IF NOT EXISTS knowledge_mutation_receipts (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_json TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                PRIMARY KEY(tenant_id,project_id,actor_id,idempotency_key)
             );",
        )
        .map_err(storage)?;
        sync::migrate(&tx, version)?;
        pull::migrate(&tx, version)?;
        resolution::migrate(&tx, version)?;
        tx.execute(
            "UPDATE knowledge_schema SET version=?1",
            [KNOWLEDGE_SCHEMA_VERSION],
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

#[async_trait]
impl ScopedMemoryRepository for SqliteKnowledgeRepository {
    async fn mutate(
        &self,
        scope: &KnowledgeScope,
        actor_id: &str,
        idempotency_key: &str,
        mutation: MemoryMutation,
    ) -> KnowledgeResult<MemoryMutationOutcome> {
        self.mutate_durable(scope, actor_id, idempotency_key, mutation)
    }

    async fn changes(
        &self,
        scope: &KnowledgeScope,
        after_sequence: u64,
        limit: usize,
    ) -> KnowledgeResult<Vec<MemoryChange>> {
        self.read_changes(scope, after_sequence, limit)
    }

    async fn change(
        &self,
        scope: &KnowledgeScope,
        sequence: u64,
    ) -> KnowledgeResult<Option<MemoryChange>> {
        if sequence == 0 {
            validate(scope, "change")?;
            return Ok(None);
        }
        Ok(self
            .read_changes(scope, sequence - 1, 1)?
            .into_iter()
            .find(|change| change.sequence == sequence))
    }

    async fn create(&self, scope: &KnowledgeScope, memory: Memory) -> KnowledgeResult<Memory> {
        Ok(self
            .apply_unkeyed(scope, MemoryMutation::Create { memory })?
            .memory)
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
        memory: Memory,
        expected_revision: u32,
    ) -> KnowledgeResult<Memory> {
        Ok(self
            .apply_unkeyed(
                scope,
                MemoryMutation::Update {
                    memory,
                    expected_revision,
                },
            )?
            .memory)
    }

    async fn delete(
        &self,
        scope: &KnowledgeScope,
        id: &str,
        expected_revision: u32,
    ) -> KnowledgeResult<()> {
        self.apply_unkeyed(
            scope,
            MemoryMutation::Delete {
                id: id.into(),
                expected_revision,
            },
        )?;
        Ok(())
    }
}
