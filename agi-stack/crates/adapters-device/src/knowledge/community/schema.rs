use rusqlite::Transaction;

use super::super::{storage, KnowledgeError, KnowledgeResult};

pub(in super::super) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous >= 13 {
        let objects: i64 = tx.query_row(
            "SELECT count(*) FROM sqlite_master WHERE
             (type='table' AND name IN ('knowledge_community_builds','knowledge_community_candidates',
               'knowledge_community_members','knowledge_community_jobs')) OR
             (type='trigger' AND name IN ('knowledge_community_build_immutable',
               'knowledge_community_candidate_immutable','knowledge_community_member_immutable'))",
            [], |row| row.get(0),
        ).map_err(storage)?;
        if objects != 7 {
            return Err(KnowledgeError::Storage(
                "knowledge community schema is missing".into(),
            ));
        }
        return super::results::migrate(tx, previous);
    }
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS knowledge_community_builds (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            build_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_json TEXT NOT NULL CHECK(json_valid(request_json)),
            graph_digest TEXT NOT NULL,
            snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
            receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)),
            PRIMARY KEY(tenant_id,project_id,build_id),
            UNIQUE(tenant_id,project_id,actor_id,idempotency_key)
         );
         CREATE TABLE IF NOT EXISTS knowledge_community_candidates (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            build_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            position INTEGER NOT NULL CHECK(position>=0),
            member_count INTEGER NOT NULL CHECK(member_count>=2),
            PRIMARY KEY(tenant_id,project_id,build_id,candidate_id),
            UNIQUE(tenant_id,project_id,build_id,position),
            FOREIGN KEY(tenant_id,project_id,build_id)
                REFERENCES knowledge_community_builds(tenant_id,project_id,build_id)
         );
         CREATE TABLE IF NOT EXISTS knowledge_community_members (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            build_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            position INTEGER NOT NULL CHECK(position>=0),
            reference_json TEXT NOT NULL CHECK(json_valid(reference_json)),
            PRIMARY KEY(tenant_id,project_id,build_id,candidate_id,position),
            FOREIGN KEY(tenant_id,project_id,build_id,candidate_id)
                REFERENCES knowledge_community_candidates(tenant_id,project_id,build_id,candidate_id)
         );
         CREATE TABLE IF NOT EXISTS knowledge_community_jobs (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            build_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','leased','failed')),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt>=0 AND attempt<=4294967295),
            worker_id TEXT,
            token TEXT,
            expires_at_ms INTEGER,
            failure_json TEXT,
            PRIMARY KEY(tenant_id,project_id,build_id,candidate_id),
            FOREIGN KEY(tenant_id,project_id,build_id,candidate_id)
                REFERENCES knowledge_community_candidates(tenant_id,project_id,build_id,candidate_id),
            CHECK((state='leased' AND attempt>0 AND worker_id IS NOT NULL AND token IS NOT NULL
                AND expires_at_ms IS NOT NULL AND expires_at_ms>=0)
                OR (state!='leased' AND worker_id IS NULL AND token IS NULL AND expires_at_ms IS NULL)),
            CHECK((state='failed' AND attempt>0 AND failure_json IS NOT NULL AND json_valid(failure_json))
                OR (state!='failed' AND failure_json IS NULL))
         );
         CREATE INDEX IF NOT EXISTS knowledge_community_claim ON knowledge_community_jobs
            (tenant_id,project_id,build_id,state);
         CREATE TRIGGER IF NOT EXISTS knowledge_community_build_immutable BEFORE UPDATE ON knowledge_community_builds
            BEGIN SELECT RAISE(ABORT,'community build input is immutable'); END;
         CREATE TRIGGER IF NOT EXISTS knowledge_community_candidate_immutable BEFORE UPDATE ON knowledge_community_candidates
            BEGIN SELECT RAISE(ABORT,'community candidate input is immutable'); END;
         CREATE TRIGGER IF NOT EXISTS knowledge_community_member_immutable BEFORE UPDATE ON knowledge_community_members
            BEGIN SELECT RAISE(ABORT,'community member input is immutable'); END;",
    ).map_err(storage)?;
    super::results::migrate(tx, previous)
}
