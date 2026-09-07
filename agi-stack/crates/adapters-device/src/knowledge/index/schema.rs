use super::*;

pub(in super::super) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous >= 10 {
        let count: i64 = tx.query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN
             ('knowledge_index_builds','knowledge_index_active','knowledge_index_jobs','knowledge_index_vectors')",
            [], |row| row.get(0),
        ).map_err(storage)?;
        return if count == 4 {
            Ok(())
        } else {
            Err(KnowledgeError::Storage(
                "knowledge index schema is missing".into(),
            ))
        };
    }
    tx.execute_batch("CREATE TABLE IF NOT EXISTS knowledge_index_builds (
        tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, build_id TEXT NOT NULL,
        profile_json TEXT NOT NULL, created_at_ms INTEGER NOT NULL,
        PRIMARY KEY(tenant_id,project_id,build_id)
    );
    CREATE TABLE IF NOT EXISTS knowledge_index_active (
        tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, build_id TEXT NOT NULL,
        PRIMARY KEY(tenant_id,project_id)
    );
    CREATE TABLE IF NOT EXISTS knowledge_index_jobs (
        tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, build_id TEXT NOT NULL,
        change_sequence INTEGER NOT NULL, memory_id TEXT NOT NULL, revision INTEGER NOT NULL,
        audit_attempt INTEGER NOT NULL CHECK(audit_attempt>0), input_digest TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending','leased','completed','failed')),
        attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt>=0),
        worker_id TEXT, token TEXT, expires_at_ms INTEGER, failure_json TEXT,
        PRIMARY KEY(tenant_id,project_id,build_id,change_sequence,audit_attempt,input_digest),
        CHECK((state='leased' AND worker_id IS NOT NULL AND token IS NOT NULL AND expires_at_ms IS NOT NULL)
           OR (state!='leased' AND worker_id IS NULL AND token IS NULL AND expires_at_ms IS NULL))
    );
    CREATE TABLE IF NOT EXISTS knowledge_index_vectors (
        tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, build_id TEXT NOT NULL,
        change_sequence INTEGER NOT NULL, audit_attempt INTEGER NOT NULL, input_digest TEXT NOT NULL,
        index_attempt INTEGER NOT NULL CHECK(index_attempt>0), vector_json TEXT NOT NULL,
        PRIMARY KEY(tenant_id,project_id,build_id,change_sequence,audit_attempt,input_digest)
    );
    CREATE INDEX IF NOT EXISTS knowledge_index_pending ON knowledge_index_jobs
        (tenant_id,project_id,build_id,state,change_sequence);")
        .map_err(storage)
}
