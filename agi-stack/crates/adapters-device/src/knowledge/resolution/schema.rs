use super::*;
pub(in crate::knowledge) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous >= 6 {
        let count:i64=tx.query_row("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('knowledge_sync_resolutions','knowledge_sync_resolved_pull_conflicts','knowledge_sync_superseded_outbox','knowledge_sync_outbox_metadata')",[],|row|row.get(0)).map_err(storage)?;
        if count != 4 {
            return Err(KnowledgeError::Storage(
                "knowledge resolution tables are missing".into(),
            ));
        }
    }
    tx.execute_batch("CREATE TABLE IF NOT EXISTS knowledge_sync_resolutions (
        resolution_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
        actor_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, memory_id TEXT NOT NULL,
        request_json TEXT NOT NULL, receipt_json TEXT NOT NULL, archive_json TEXT NOT NULL,
        UNIQUE(tenant_id,project_id,actor_id,idempotency_key)
    );
    CREATE TABLE IF NOT EXISTS knowledge_sync_resolved_pull_conflicts (
        tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, sequence INTEGER NOT NULL,
        resolution_id TEXT NOT NULL REFERENCES knowledge_sync_resolutions(resolution_id),
        PRIMARY KEY(tenant_id,project_id,sequence)
    );
    CREATE TABLE IF NOT EXISTS knowledge_sync_superseded_outbox (
        sequence INTEGER PRIMARY KEY REFERENCES knowledge_sync_outbox(sequence),
        resolution_id TEXT NOT NULL REFERENCES knowledge_sync_resolutions(resolution_id)
    );
    CREATE TABLE IF NOT EXISTS knowledge_sync_outbox_metadata (
        sequence INTEGER PRIMARY KEY REFERENCES knowledge_sync_outbox(sequence),
        metadata_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS knowledge_resolution_history ON knowledge_sync_resolutions(tenant_id,project_id,memory_id);")
    .map_err(storage)
}
