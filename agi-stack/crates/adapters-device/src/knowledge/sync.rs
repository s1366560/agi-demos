use agistack_core::knowledge::sync::{
    KnowledgeSyncLink, KnowledgeSyncOutboxChange, KnowledgeSyncRepository, KnowledgeSyncStatus,
};
use rusqlite::{Transaction, TransactionBehavior};
use uuid::Uuid;

use super::*;

pub(super) fn migrate(tx: &Transaction<'_>, previous_version: i64) -> KnowledgeResult<()> {
    if previous_version >= 3 {
        let tables: i64 = tx.query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('knowledge_replica','knowledge_sync_links','knowledge_sync_outbox')",
            [], |row| row.get(0),
        ).map_err(storage)?;
        if tables != 3 {
            return Err(KnowledgeError::Storage(
                "knowledge synchronization tables are missing".into(),
            ));
        }
    }
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS knowledge_replica (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            replica_id TEXT NOT NULL UNIQUE
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_links (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            remote_tenant_id TEXT NOT NULL,
            remote_project_id TEXT NOT NULL,
            remote_actor_id TEXT NOT NULL,
            PRIMARY KEY(tenant_id,project_id)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_outbox (
            sequence INTEGER PRIMARY KEY,
            change_id TEXT NOT NULL UNIQUE,
            FOREIGN KEY(sequence) REFERENCES knowledge_processing_changes(sequence)
         );",
    )
    .map_err(storage)?;
    if previous_version < 3 {
        tx.execute(
            "INSERT INTO knowledge_replica(singleton,replica_id) VALUES(1,?1)",
            [Uuid::new_v4().to_string()],
        )
        .map_err(storage)?;
        // Every pre-v3 scoped processing change was produced by a local write.
        // Unscoped legacy memories have no proven tenant and are never enrolled.
        let mut statement = tx
            .prepare("SELECT sequence FROM knowledge_processing_changes ORDER BY sequence")
            .map_err(storage)?;
        let sequences = statement
            .query_map([], |row| row.get::<_, u64>(0))
            .map_err(storage)?;
        for sequence in sequences {
            enqueue_local(tx, sequence.map_err(storage)?)?;
        }
    }
    replica(tx)?;
    Ok(())
}

fn replica(conn: &Connection) -> KnowledgeResult<Uuid> {
    let value: String = conn
        .query_row(
            "SELECT replica_id FROM knowledge_replica WHERE singleton=1",
            [],
            |row| row.get(0),
        )
        .map_err(storage)?;
    Uuid::parse_str(&value).map_err(storage)
}

/// Only local mutation paths call this. A remote apply must persist its own
/// indexing change without enrolling it as a fresh local-origin outbox entry.
pub(super) fn enqueue_local(tx: &Transaction<'_>, sequence: u64) -> KnowledgeResult<()> {
    let change_id = Uuid::new_v5(&replica(tx)?, sequence.to_string().as_bytes());
    tx.execute(
        "INSERT INTO knowledge_sync_outbox(sequence,change_id) VALUES(?1,?2)",
        params![sequence, change_id.to_string()],
    )
    .map_err(storage)?;
    Ok(())
}

fn status(conn: &Connection, scope: &KnowledgeScope) -> KnowledgeResult<KnowledgeSyncStatus> {
    let link = conn.query_row(
        "SELECT remote_tenant_id,remote_project_id,remote_actor_id FROM knowledge_sync_links WHERE tenant_id=?1 AND project_id=?2",
        params![scope.tenant_id, scope.project_id],
        |row| Ok(KnowledgeSyncLink { remote_tenant_id: row.get(0)?, remote_project_id: row.get(1)?, remote_actor_id: row.get(2)? }),
    ).optional().map_err(storage)?;
    let pending_changes = conn.query_row(
        "SELECT count(*) FROM knowledge_sync_outbox o JOIN knowledge_processing_changes c ON c.sequence=o.sequence WHERE c.tenant_id=?1 AND c.project_id=?2",
        params![scope.tenant_id, scope.project_id], |row| row.get(0),
    ).map_err(storage)?;
    Ok(KnowledgeSyncStatus {
        replica_id: replica(conn)?.to_string(),
        link,
        pending_changes,
    })
}

fn validate_identifier(value: &str) -> KnowledgeResult<()> {
    if value.is_empty() || value.trim() != value || value.chars().count() > 512 {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

#[async_trait]
impl KnowledgeSyncRepository for SqliteKnowledgeRepository {
    async fn sync_status(&self, scope: &KnowledgeScope) -> KnowledgeResult<KnowledgeSyncStatus> {
        validate(scope, "sync status")?;
        let conn = self.conn.lock().map_err(storage)?;
        status(&conn, scope)
    }

    async fn configure_sync_link(
        &self,
        scope: &KnowledgeScope,
        link: KnowledgeSyncLink,
    ) -> KnowledgeResult<KnowledgeSyncStatus> {
        validate(scope, "sync link")?;
        for value in [
            &link.remote_tenant_id,
            &link.remote_project_id,
            &link.remote_actor_id,
        ] {
            validate_identifier(value)?;
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        let previous = status(&tx, scope)?;
        if let Some(existing) = &previous.link {
            return if existing == &link {
                Ok(previous)
            } else {
                Err(KnowledgeError::Conflict)
            };
        }
        tx.execute(
            "INSERT INTO knowledge_sync_links(tenant_id,project_id,remote_tenant_id,remote_project_id,remote_actor_id) VALUES(?1,?2,?3,?4,?5)",
            params![scope.tenant_id,scope.project_id,link.remote_tenant_id,link.remote_project_id,link.remote_actor_id],
        ).map_err(storage)?;
        let result = status(&tx, scope)?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }

    async fn sync_outbox(
        &self,
        scope: &KnowledgeScope,
        after_sequence: u64,
        limit: usize,
    ) -> KnowledgeResult<Vec<KnowledgeSyncOutboxChange>> {
        validate(scope, "sync outbox")?;
        if !(1..=200).contains(&limit) {
            return Err(KnowledgeError::InvalidInput);
        }
        let Ok(after) = i64::try_from(after_sequence) else {
            return Ok(Vec::new());
        };
        let conn = self.conn.lock().map_err(storage)?;
        let mut statement = conn.prepare(
            "SELECT o.change_id,c.sequence,c.payload,c.operation FROM knowledge_sync_outbox o JOIN knowledge_processing_changes c ON c.sequence=o.sequence WHERE c.tenant_id=?1 AND c.project_id=?2 AND c.sequence>?3 ORDER BY c.sequence LIMIT ?4",
        ).map_err(storage)?;
        let rows = statement
            .query_map(
                params![scope.tenant_id, scope.project_id, after, limit as i64],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, u64>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                    ))
                },
            )
            .map_err(storage)?;
        rows.map(|row| {
            let (change_id, sequence, payload, operation) = row.map_err(storage)?;
            Ok(KnowledgeSyncOutboxChange {
                change_id,
                local_change: MemoryChange {
                    sequence,
                    memory: serde_json::from_str(&payload).map_err(storage)?,
                    deleted: operation == "delete",
                },
            })
        })
        .collect()
    }
}
