//! Durable local store for synced derived records and their local-origin
//! outbox. Extraction publishes enqueue here; pulls apply remote records.
//! Visibility of a synced record's source is computed per read, never stored.

use agistack_core::knowledge::processing::{ProcessingProjection, ProcessingSource};
use agistack_core::knowledge::sync::graph::{
    KnowledgeGraphSyncReadRepository, RemoteGraphContent, RemoteGraphEntity,
    RemoteGraphRelationship, RemoteGraphVersion, SyncedGraphProjection,
};
use rusqlite::Transaction;
use uuid::Uuid;

use super::*;

pub(super) fn migrate(tx: &Transaction<'_>, previous_version: i64) -> KnowledgeResult<()> {
    if previous_version >= 18 {
        let count: i64 = tx
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN (
                    'knowledge_sync_graph_objects',
                    'knowledge_sync_graph_outbox',
                    'knowledge_sync_graph_pushes',
                    'knowledge_sync_graph_remote_versions',
                    'knowledge_sync_graph_pull_cursors',
                    'knowledge_sync_graph_pull_events',
                    'knowledge_sync_graph_pull_conflicts',
                    'knowledge_sync_graph_resolutions',
                    'knowledge_sync_graph_resolved_pull_conflicts',
                    'knowledge_sync_graph_superseded_outbox',
                    'knowledge_sync_graph_unbound_outbox'
                 )",
                [],
                |row| row.get(0),
            )
            .map_err(storage)?;
        if count != 11 {
            return Err(KnowledgeError::Storage(
                "knowledge graph sync tables are missing".into(),
            ));
        }
    }
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS knowledge_sync_graph_objects (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            object_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK(revision > 0),
            deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0, 1)),
            author_id TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY(tenant_id, project_id, object_id)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_outbox (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            object_id TEXT NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('upsert', 'delete')),
            payload TEXT NOT NULL,
            change_id TEXT NOT NULL UNIQUE
         );
         CREATE INDEX IF NOT EXISTS knowledge_sync_graph_outbox_object
            ON knowledge_sync_graph_outbox(tenant_id, project_id, object_id, sequence);
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_pushes (
            sequence INTEGER PRIMARY KEY,
            request_json TEXT NOT NULL,
            receipt_json TEXT,
            conflict_json TEXT,
            FOREIGN KEY(sequence) REFERENCES knowledge_sync_graph_outbox(sequence)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_remote_versions (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            object_id TEXT NOT NULL,
            version_json TEXT NOT NULL,
            PRIMARY KEY(tenant_id, project_id, object_id)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_pull_cursors (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            cursor INTEGER NOT NULL,
            PRIMARY KEY(tenant_id, project_id)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_pull_events (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            change_id TEXT NOT NULL,
            object_id TEXT NOT NULL,
            version_json TEXT NOT NULL,
            PRIMARY KEY(tenant_id, project_id, sequence),
            UNIQUE(tenant_id, project_id, change_id)
         );
         CREATE INDEX IF NOT EXISTS knowledge_sync_graph_pull_object
            ON knowledge_sync_graph_pull_events(tenant_id, project_id, object_id, sequence DESC);
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_pull_conflicts (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            object_id TEXT NOT NULL,
            conflict_json TEXT NOT NULL,
            PRIMARY KEY(tenant_id, project_id, sequence)
         );
         CREATE INDEX IF NOT EXISTS knowledge_sync_graph_pull_conflict_object
            ON knowledge_sync_graph_pull_conflicts(tenant_id, project_id, object_id);
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_resolutions (
            resolution_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            object_id TEXT NOT NULL,
            request_json TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            archive_json TEXT NOT NULL,
            UNIQUE(tenant_id, project_id, actor_id, idempotency_key)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_resolved_pull_conflicts (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            resolution_id TEXT NOT NULL,
            PRIMARY KEY(tenant_id, project_id, sequence)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_superseded_outbox (
            sequence INTEGER PRIMARY KEY,
            resolution_id TEXT NOT NULL
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_graph_unbound_outbox (
            sequence INTEGER PRIMARY KEY,
            FOREIGN KEY(sequence) REFERENCES knowledge_sync_graph_outbox(sequence)
         );",
    )
    .map_err(storage)?;
    tx.execute_batch(
        "DROP VIEW IF EXISTS knowledge_pending_graph_outbox;
         DROP VIEW IF EXISTS knowledge_unsettled_graph_pushes;
         DROP VIEW IF EXISTS knowledge_active_graph_pull_conflicts;
         CREATE VIEW knowledge_pending_graph_outbox AS
            SELECT o.*,p.request_json,p.receipt_json,p.conflict_json
            FROM knowledge_sync_graph_outbox o
            LEFT JOIN knowledge_sync_graph_pushes p ON p.sequence=o.sequence
            WHERE (p.receipt_json IS NULL OR p.conflict_json IS NOT NULL)
            AND NOT EXISTS(SELECT 1 FROM knowledge_sync_graph_superseded_outbox s WHERE s.sequence=o.sequence)
            AND NOT EXISTS(SELECT 1 FROM knowledge_sync_graph_unbound_outbox u WHERE u.sequence=o.sequence);
         CREATE VIEW knowledge_unsettled_graph_pushes AS
            SELECT p.*,o.tenant_id,o.project_id,o.object_id FROM knowledge_sync_graph_pushes p
            JOIN knowledge_sync_graph_outbox o ON o.sequence=p.sequence
            WHERE (p.receipt_json IS NULL OR p.conflict_json IS NOT NULL)
            AND NOT EXISTS(SELECT 1 FROM knowledge_sync_graph_unbound_outbox u WHERE u.sequence=p.sequence);
         CREATE VIEW knowledge_active_graph_pull_conflicts AS
            SELECT pc.* FROM knowledge_sync_graph_pull_conflicts pc
            WHERE NOT EXISTS(
                SELECT 1 FROM knowledge_sync_graph_resolved_pull_conflicts r
                WHERE r.tenant_id=pc.tenant_id AND r.project_id=pc.project_id AND r.sequence=pc.sequence);",
    )
    .map_err(storage)
}

/// Clean decimal wire form: the f32 shortest representation parsed as f64.
fn wire_score(score: f32) -> KnowledgeResult<f64> {
    score
        .to_string()
        .parse::<f64>()
        .map_err(|_| KnowledgeError::InvalidInput)
}

pub(super) fn graph_content(
    source: &ProcessingSource,
    audit_attempt: u32,
    projection: &ProcessingProjection,
) -> KnowledgeResult<RemoteGraphContent> {
    let content = RemoteGraphContent {
        source_revision: source.revision,
        change_sequence: source.change_sequence,
        audit_attempt,
        entities: projection
            .entities
            .iter()
            .map(|entity| RemoteGraphEntity {
                name: entity.name.clone(),
                kind: entity.kind.clone(),
            })
            .collect(),
        relationships: projection
            .relationships
            .iter()
            .map(|relationship| {
                Ok(RemoteGraphRelationship {
                    source_index: relationship.source_index,
                    target_index: relationship.target_index,
                    relation_type: relationship.relation_type.clone(),
                    fact: relationship.fact.clone(),
                    score: wire_score(relationship.score)?,
                })
            })
            .collect::<KnowledgeResult<Vec<_>>>()?,
    };
    content.validate()?;
    Ok(content)
}

/// Only the local extraction pipeline calls this, inside the same transaction
/// as the projection publish. A remote apply never enqueues local-origin work.
pub(super) fn enqueue_local(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    source: &ProcessingSource,
    audit_attempt: u32,
    projection: &ProcessingProjection,
) -> KnowledgeResult<()> {
    let content = graph_content(source, audit_attempt, projection)?;
    enqueue_content(tx, scope, &source.memory_id, &content)?;
    Ok(())
}

/// Deterministic change IDs survive retries and restarts for one logical push.
pub(super) fn change_id_for(tx: &Transaction<'_>, name: &str) -> KnowledgeResult<String> {
    let replica = super::sync::replica(tx)?;
    Ok(Uuid::new_v5(&replica, name.as_bytes()).to_string())
}

pub(super) fn enqueue_content(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    object_id: &str,
    content: &RemoteGraphContent,
) -> KnowledgeResult<u64> {
    enqueue_named(
        tx,
        scope,
        object_id,
        content,
        &format!("graph-projection:{}", content.change_sequence),
    )
}

pub(super) fn enqueue_named(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    object_id: &str,
    content: &RemoteGraphContent,
    name: &str,
) -> KnowledgeResult<u64> {
    validate(scope, object_id)?;
    content.validate()?;
    let change_id = change_id_for(tx, name)?;
    tx.execute(
        "INSERT INTO knowledge_sync_graph_outbox(tenant_id, project_id, object_id, operation, payload, change_id)
         VALUES(?1, ?2, ?3, 'upsert', ?4, ?5)",
        params![
            scope.tenant_id,
            scope.project_id,
            object_id,
            serde_json::to_string(content).map_err(storage)?,
            change_id
        ],
    )
    .map_err(storage)?;
    u64::try_from(tx.last_insert_rowid()).map_err(storage)
}

pub(super) fn pending_count(conn: &Connection, scope: &KnowledgeScope) -> KnowledgeResult<u64> {
    conn.query_row(
        "SELECT count(*) FROM knowledge_pending_graph_outbox WHERE tenant_id=?1 AND project_id=?2",
        params![scope.tenant_id, scope.project_id],
        |row| row.get(0),
    )
    .map_err(storage)
}

pub(super) struct LocalGraphObject {
    pub revision: u32,
    pub deleted: bool,
    pub version: RemoteGraphVersion,
}

pub(super) fn local_object(
    conn: &Connection,
    scope: &KnowledgeScope,
    object_id: &str,
) -> KnowledgeResult<Option<LocalGraphObject>> {
    let row: Option<(u32, bool, String)> = conn
        .query_row(
            "SELECT revision, deleted, payload FROM knowledge_sync_graph_objects
             WHERE tenant_id=?1 AND project_id=?2 AND object_id=?3",
            params![scope.tenant_id, scope.project_id, object_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()
        .map_err(storage)?;
    let Some((revision, deleted, payload)) = row else {
        return Ok(None);
    };
    let version: RemoteGraphVersion = serde_json::from_str(&payload).map_err(storage)?;
    version.validate()?;
    Ok(Some(LocalGraphObject {
        revision,
        deleted,
        version,
    }))
}

pub(super) fn store_object(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    version: &RemoteGraphVersion,
    local_revision: u32,
) -> KnowledgeResult<()> {
    version.validate()?;
    if local_revision == 0 {
        return Err(KnowledgeError::InvalidInput);
    }
    let mut stored = version.clone();
    stored.revision = local_revision;
    tx.execute(
        "INSERT INTO knowledge_sync_graph_objects(tenant_id, project_id, object_id, revision, deleted, author_id, created_at_ms, payload)
         VALUES(?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
         ON CONFLICT(tenant_id, project_id, object_id)
         DO UPDATE SET revision=excluded.revision, deleted=excluded.deleted,
           author_id=excluded.author_id, created_at_ms=excluded.created_at_ms, payload=excluded.payload",
        params![
            scope.tenant_id,
            scope.project_id,
            version.object_id,
            local_revision,
            version.deleted,
            version.author_id,
            version.created_at_ms,
            serde_json::to_string(&stored).map_err(storage)?
        ],
    )
    .map_err(storage)?;
    Ok(())
}

fn synced(
    conn: &Connection,
    scope: &KnowledgeScope,
    object: LocalGraphObject,
) -> KnowledgeResult<SyncedGraphProjection> {
    let live: Option<u32> = conn
        .query_row(
            "SELECT revision FROM knowledge_memories
             WHERE tenant_id=?1 AND project_id=?2 AND id=?3 AND deleted=0",
            params![scope.tenant_id, scope.project_id, object.version.object_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    Ok(SyncedGraphProjection {
        object_id: object.version.object_id.clone(),
        revision: object.revision,
        deleted: object.deleted,
        author_id: object.version.author_id.clone(),
        created_at_ms: object.version.created_at_ms,
        source_available: live.is_some(),
        source_current: live == Some(object.version.content.source_revision),
        content: object.version.content,
    })
}

impl SqliteKnowledgeRepository {
    pub fn synced_graph_projection_durable(
        &self,
        scope: &KnowledgeScope,
        object_id: &str,
    ) -> KnowledgeResult<Option<SyncedGraphProjection>> {
        validate(scope, object_id)?;
        let conn = self.conn.lock().map_err(storage)?;
        local_object(&conn, scope, object_id)?
            .map(|object| synced(&conn, scope, object))
            .transpose()
    }

    pub fn synced_graph_projections_durable(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
        offset: usize,
    ) -> KnowledgeResult<Vec<SyncedGraphProjection>> {
        validate(scope, "synced graph projections")?;
        if !(1..=200).contains(&limit) {
            return Err(KnowledgeError::InvalidInput);
        }
        let conn = self.conn.lock().map_err(storage)?;
        let mut statement = conn
            .prepare(
                "SELECT object_id FROM knowledge_sync_graph_objects
                 WHERE tenant_id=?1 AND project_id=?2
                 ORDER BY created_at_ms DESC, object_id ASC LIMIT ?3 OFFSET ?4",
            )
            .map_err(storage)?;
        let rows = statement
            .query_map(
                params![
                    scope.tenant_id,
                    scope.project_id,
                    i64::try_from(limit).unwrap_or(i64::MAX),
                    i64::try_from(offset).unwrap_or(i64::MAX)
                ],
                |row| row.get::<_, String>(0),
            )
            .map_err(storage)?;
        rows.map(|row| {
            let object_id = row.map_err(storage)?;
            let object = local_object(&conn, scope, &object_id)?
                .ok_or(KnowledgeError::NotFound)?;
            synced(&conn, scope, object)
        })
        .collect()
    }
}

#[async_trait]
impl KnowledgeGraphSyncReadRepository for SqliteKnowledgeRepository {
    async fn synced_graph_projection(
        &self,
        scope: &KnowledgeScope,
        object_id: &str,
    ) -> KnowledgeResult<Option<SyncedGraphProjection>> {
        self.synced_graph_projection_durable(scope, object_id)
    }

    async fn synced_graph_projections(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
        offset: usize,
    ) -> KnowledgeResult<Vec<SyncedGraphProjection>> {
        self.synced_graph_projections_durable(scope, limit, offset)
    }
}
