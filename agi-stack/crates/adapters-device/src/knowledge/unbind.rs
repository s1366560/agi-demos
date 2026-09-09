//! Atomic local unbind lifecycle. Removing the verified association fences the
//! previous binding's outbox and pull state in the same transaction as the
//! caller's explicit keep/delete choice for downloaded copies. Local copies are
//! never remotely revocable: this module performs no cloud operation.
use agistack_core::knowledge::sync::{
    KnowledgeSyncLink, KnowledgeUnbindPolicy, KnowledgeUnbindReceipt,
};
use rusqlite::{Transaction, TransactionBehavior};
use uuid::Uuid;

use super::*;

pub(super) fn migrate(tx: &Transaction<'_>, previous_version: i64) -> KnowledgeResult<()> {
    if previous_version >= 17 {
        let count: i64 = tx
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN (
                    'knowledge_sync_unbound_outbox', 'knowledge_sync_unbinds')",
                [],
                |row| row.get(0),
            )
            .map_err(storage)?;
        if count != 2 {
            return Err(KnowledgeError::Storage(
                "knowledge unbind tables are missing".into(),
            ));
        }
    }
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS knowledge_sync_unbound_outbox (
            sequence INTEGER PRIMARY KEY,
            FOREIGN KEY(sequence) REFERENCES knowledge_sync_outbox(sequence)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_unbinds (
            unbind_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            remote_tenant_id TEXT NOT NULL,
            remote_project_id TEXT NOT NULL,
            remote_actor_id TEXT NOT NULL,
            policy TEXT NOT NULL CHECK(policy IN ('keep', 'delete')),
            fenced_outbox INTEGER NOT NULL,
            removed_local_copies INTEGER NOT NULL,
            unbound_at_ms INTEGER NOT NULL
         );",
    )
    .map_err(storage)?;
    // The previous binding generation's pending work must never be prepared,
    // sent, or surfaced again, including after any later re-bind.
    tx.execute_batch(
        "DROP VIEW IF EXISTS knowledge_pending_outbox;
         DROP VIEW IF EXISTS knowledge_unsettled_pushes;
         CREATE VIEW knowledge_pending_outbox AS
            SELECT c.*,o.change_id,p.request_json,p.receipt_json,p.conflict_json
            FROM knowledge_sync_outbox o JOIN knowledge_processing_changes c ON c.sequence=o.sequence
            LEFT JOIN knowledge_sync_pushes p ON p.sequence=o.sequence
            WHERE (p.receipt_json IS NULL OR p.conflict_json IS NOT NULL)
            AND NOT EXISTS(SELECT 1 FROM knowledge_sync_superseded_outbox s WHERE s.sequence=o.sequence)
            AND NOT EXISTS(SELECT 1 FROM knowledge_cloud_superseded_outbox s WHERE s.sequence=o.sequence)
            AND NOT EXISTS(SELECT 1 FROM knowledge_cloud_resolved_pushes r WHERE r.sequence=o.sequence)
            AND NOT EXISTS(SELECT 1 FROM knowledge_sync_unbound_outbox u WHERE u.sequence=o.sequence);
         CREATE VIEW knowledge_unsettled_pushes AS
            SELECT p.*,c.tenant_id,c.project_id,c.memory_id FROM knowledge_sync_pushes p
            JOIN knowledge_processing_changes c ON c.sequence=p.sequence
            WHERE (p.receipt_json IS NULL OR p.conflict_json IS NOT NULL)
            AND NOT EXISTS(SELECT 1 FROM knowledge_cloud_resolved_pushes r WHERE r.sequence=p.sequence)
            AND NOT EXISTS(SELECT 1 FROM knowledge_sync_unbound_outbox u WHERE u.sequence=p.sequence);",
    )
    .map_err(storage)
}

/// A memory is cloud-origin when its earliest processing change was applied
/// from a pull rather than enrolled by a local write. Later local edits of a
/// downloaded copy do not change its origin.
fn cloud_origin(outer_table: &str, memory_id_column: &str) -> String {
    format!(
        "NOT EXISTS (
            SELECT 1 FROM knowledge_sync_outbox o WHERE o.sequence = (
                SELECT MIN(c.sequence) FROM knowledge_processing_changes c
                WHERE c.tenant_id={outer_table}.tenant_id
                  AND c.project_id={outer_table}.project_id
                  AND c.memory_id={outer_table}.{memory_id_column}))"
    )
}

impl SqliteKnowledgeRepository {
    /// Fail-closed unbind. The association row disappears in the same
    /// transaction that fences pending work, so every push/pull/receipt path
    /// that rechecks the stored binding rejects in-flight operations.
    pub fn unbind_sync_target_durable(
        &self,
        scope: &KnowledgeScope,
        policy: KnowledgeUnbindPolicy,
        unbound_at_ms: i64,
    ) -> KnowledgeResult<KnowledgeUnbindReceipt> {
        validate(scope, "sync unbind")?;
        if unbound_at_ms < 0 {
            return Err(KnowledgeError::InvalidInput);
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        let link: Option<KnowledgeSyncLink> = tx
            .query_row(
                "SELECT remote_tenant_id,remote_project_id,remote_actor_id FROM knowledge_sync_links WHERE tenant_id=?1 AND project_id=?2",
                params![scope.tenant_id, scope.project_id],
                |row| Ok(KnowledgeSyncLink { remote_tenant_id: row.get(0)?, remote_project_id: row.get(1)?, remote_actor_id: row.get(2)? }),
            )
            .optional()
            .map_err(storage)?;
        let Some(link) = link else {
            return Err(KnowledgeError::NotFound);
        };
        let fenced = tx
            .execute(
                "INSERT INTO knowledge_sync_unbound_outbox(sequence)
                 SELECT o.sequence FROM knowledge_sync_outbox o
                 JOIN knowledge_processing_changes c ON c.sequence=o.sequence
                 WHERE c.tenant_id=?1 AND c.project_id=?2
                 ON CONFLICT(sequence) DO NOTHING",
                params![scope.tenant_id, scope.project_id],
            )
            .map_err(storage)?;
        let fenced_graph = tx
            .execute(
                "INSERT INTO knowledge_sync_graph_unbound_outbox(sequence)
                 SELECT o.sequence FROM knowledge_sync_graph_outbox o
                 WHERE o.tenant_id=?1 AND o.project_id=?2
                 ON CONFLICT(sequence) DO NOTHING",
                params![scope.tenant_id, scope.project_id],
            )
            .map_err(storage)?;
        for statement in [
            "DELETE FROM knowledge_sync_links WHERE tenant_id=?1 AND project_id=?2",
            "DELETE FROM knowledge_sync_targets WHERE tenant_id=?1 AND project_id=?2",
            "DELETE FROM knowledge_sync_pull_cursors WHERE tenant_id=?1 AND project_id=?2",
            "DELETE FROM knowledge_sync_pull_events WHERE tenant_id=?1 AND project_id=?2",
            "DELETE FROM knowledge_sync_pull_conflicts WHERE tenant_id=?1 AND project_id=?2",
            "DELETE FROM knowledge_sync_graph_pull_cursors WHERE tenant_id=?1 AND project_id=?2",
            "DELETE FROM knowledge_sync_graph_pull_events WHERE tenant_id=?1 AND project_id=?2",
            "DELETE FROM knowledge_sync_graph_pull_conflicts WHERE tenant_id=?1 AND project_id=?2",
        ] {
            tx.execute(statement, params![scope.tenant_id, scope.project_id])
                .map_err(storage)?;
        }
        let removed = if policy == KnowledgeUnbindPolicy::Delete {
            // Remote baselines of cloud-origin copies are cleared so a later
            // re-bind replay surfaces them as explicit conflicts instead of
            // silently resurrecting the deleted copies.
            tx.execute(
                &format!(
                    "DELETE FROM knowledge_sync_remote_versions
                     WHERE tenant_id=?1 AND project_id=?2 AND {}",
                    cloud_origin("knowledge_sync_remote_versions", "memory_id")
                ),
                params![scope.tenant_id, scope.project_id],
            )
            .map_err(storage)?;
            tx.execute(
                "DELETE FROM knowledge_sync_graph_remote_versions
                 WHERE tenant_id=?1 AND project_id=?2
                   AND NOT EXISTS (
                     SELECT 1 FROM knowledge_sync_graph_outbox o
                     WHERE o.tenant_id=knowledge_sync_graph_remote_versions.tenant_id
                       AND o.project_id=knowledge_sync_graph_remote_versions.project_id
                       AND o.object_id=knowledge_sync_graph_remote_versions.object_id)",
                params![scope.tenant_id, scope.project_id],
            )
            .map_err(storage)?;
            tx.execute(
                "UPDATE knowledge_sync_graph_objects SET deleted=1
                 WHERE tenant_id=?1 AND project_id=?2 AND deleted=0
                   AND NOT EXISTS (
                     SELECT 1 FROM knowledge_sync_graph_outbox o
                     WHERE o.tenant_id=knowledge_sync_graph_objects.tenant_id
                       AND o.project_id=knowledge_sync_graph_objects.project_id
                       AND o.object_id=knowledge_sync_graph_objects.object_id)",
                params![scope.tenant_id, scope.project_id],
            )
            .map_err(storage)?;
            tx.execute(
                &format!(
                    "UPDATE knowledge_memories SET deleted=1
                     WHERE tenant_id=?1 AND project_id=?2 AND deleted=0 AND {}",
                    cloud_origin("knowledge_memories", "id")
                ),
                params![scope.tenant_id, scope.project_id],
            )
            .map_err(storage)?
        } else {
            0
        };
        let (fenced_outbox, fenced_graph_outbox, removed_local_copies) = (
            u64::try_from(fenced).map_err(storage)?,
            u64::try_from(fenced_graph).map_err(storage)?,
            u64::try_from(removed).map_err(storage)?,
        );
        tx.execute(
            "INSERT INTO knowledge_sync_unbinds(
                unbind_id,tenant_id,project_id,remote_tenant_id,remote_project_id,remote_actor_id,
                policy,fenced_outbox,removed_local_copies,unbound_at_ms
             ) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
            params![
                Uuid::new_v4().to_string(),
                scope.tenant_id,
                scope.project_id,
                link.remote_tenant_id,
                link.remote_project_id,
                link.remote_actor_id,
                match policy {
                    KnowledgeUnbindPolicy::Keep => "keep",
                    KnowledgeUnbindPolicy::Delete => "delete",
                },
                fenced_outbox,
                removed_local_copies,
                unbound_at_ms,
            ],
        )
        .map_err(storage)?;
        tx.commit().map_err(storage)?;
        Ok(KnowledgeUnbindReceipt {
            link,
            policy,
            fenced_outbox,
            fenced_graph_outbox,
            removed_local_copies,
        })
    }
}
