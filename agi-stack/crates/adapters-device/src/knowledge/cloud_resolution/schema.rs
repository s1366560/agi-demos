use super::*;

pub(in crate::knowledge) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous >= 7 {
        let count: i64 = tx.query_row("SELECT count(*) FROM sqlite_master WHERE
            (type='table' AND name IN ('knowledge_cloud_resolutions','knowledge_cloud_resolved_pushes','knowledge_cloud_resolved_pull_conflicts','knowledge_cloud_superseded_outbox')) OR
            (type='view' AND name IN ('knowledge_active_pull_conflicts','knowledge_pending_outbox','knowledge_unsettled_pushes'))", [], |r|r.get(0)).map_err(storage)?;
        if count != 7 {
            return Err(KnowledgeError::Storage(
                "knowledge cloud resolution schema is missing".into(),
            ));
        }
    }
    tx.execute_batch("CREATE TABLE IF NOT EXISTS knowledge_cloud_resolutions (
        resolution_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,
        actor_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,memory_id TEXT NOT NULL,
        local_sequence INTEGER NOT NULL REFERENCES knowledge_sync_pushes(sequence),
        command_json TEXT NOT NULL,request_json TEXT NOT NULL,archive_json TEXT NOT NULL,
        receipt_json TEXT,rejection_json TEXT,reconciliation_command_json TEXT,
        reconciliation_archive_json TEXT,reconciliation_json TEXT,
        UNIQUE(tenant_id,project_id,actor_id,idempotency_key)
    );
    CREATE TABLE IF NOT EXISTS knowledge_cloud_resolved_pushes (
        sequence INTEGER PRIMARY KEY REFERENCES knowledge_sync_pushes(sequence),
        resolution_id TEXT NOT NULL REFERENCES knowledge_cloud_resolutions(resolution_id)
    );
    CREATE TABLE IF NOT EXISTS knowledge_cloud_resolved_pull_conflicts (
        tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,sequence INTEGER NOT NULL,
        resolution_id TEXT NOT NULL REFERENCES knowledge_cloud_resolutions(resolution_id),
        PRIMARY KEY(tenant_id,project_id,sequence)
    );
    CREATE TABLE IF NOT EXISTS knowledge_cloud_superseded_outbox (
        sequence INTEGER PRIMARY KEY REFERENCES knowledge_sync_outbox(sequence),
        resolution_id TEXT NOT NULL REFERENCES knowledge_cloud_resolutions(resolution_id)
    );
    CREATE INDEX IF NOT EXISTS knowledge_cloud_resolution_object ON knowledge_cloud_resolutions(tenant_id,project_id,memory_id);
    CREATE VIEW IF NOT EXISTS knowledge_active_pull_conflicts AS
        SELECT c.* FROM knowledge_sync_pull_conflicts c
        WHERE NOT EXISTS(SELECT 1 FROM knowledge_sync_resolved_pull_conflicts r WHERE r.tenant_id=c.tenant_id AND r.project_id=c.project_id AND r.sequence=c.sequence)
        AND NOT EXISTS(SELECT 1 FROM knowledge_cloud_resolved_pull_conflicts r WHERE r.tenant_id=c.tenant_id AND r.project_id=c.project_id AND r.sequence=c.sequence);
    CREATE VIEW IF NOT EXISTS knowledge_pending_outbox AS
        SELECT c.*,o.change_id,p.request_json,p.receipt_json,p.conflict_json
        FROM knowledge_sync_outbox o JOIN knowledge_processing_changes c ON c.sequence=o.sequence
        LEFT JOIN knowledge_sync_pushes p ON p.sequence=o.sequence
        WHERE (p.receipt_json IS NULL OR p.conflict_json IS NOT NULL)
        AND NOT EXISTS(SELECT 1 FROM knowledge_sync_superseded_outbox s WHERE s.sequence=o.sequence)
        AND NOT EXISTS(SELECT 1 FROM knowledge_cloud_superseded_outbox s WHERE s.sequence=o.sequence)
        AND NOT EXISTS(SELECT 1 FROM knowledge_cloud_resolved_pushes r WHERE r.sequence=o.sequence);
    CREATE VIEW IF NOT EXISTS knowledge_unsettled_pushes AS
        SELECT p.*,c.tenant_id,c.project_id,c.memory_id FROM knowledge_sync_pushes p
        JOIN knowledge_processing_changes c ON c.sequence=p.sequence
        WHERE (p.receipt_json IS NULL OR p.conflict_json IS NOT NULL)
        AND NOT EXISTS(SELECT 1 FROM knowledge_cloud_resolved_pushes r WHERE r.sequence=p.sequence);")
        .map_err(storage)
}
