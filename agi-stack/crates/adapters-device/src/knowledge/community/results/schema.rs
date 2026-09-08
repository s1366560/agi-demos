use super::*;

pub(in super::super) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous >= 14 {
        let count: u32 = tx.query_row(
            "SELECT count(*) FROM sqlite_master WHERE
             (type='table' AND name IN ('knowledge_community_audits','knowledge_community_results','knowledge_community_selection'))
             OR (type='trigger' AND name IN ('knowledge_community_audit_immutable','knowledge_community_audit_no_delete','knowledge_community_result_immutable','knowledge_community_result_no_delete'))",
            [], |row| row.get(0),
        ).map_err(storage)?;
        return if count == 7 {
            Ok(())
        } else {
            Err(KnowledgeError::Storage(
                "knowledge community result schema is missing".into(),
            ))
        };
    }
    tx.execute_batch(
        "CREATE TABLE knowledge_community_jobs_v14 (
            tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, build_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','leased','failed','completed')),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt>=0 AND attempt<=4294967295),
            worker_id TEXT, token TEXT, expires_at_ms INTEGER, failure_json TEXT,
            PRIMARY KEY(tenant_id,project_id,build_id,candidate_id),
            FOREIGN KEY(tenant_id,project_id,build_id,candidate_id)
                REFERENCES knowledge_community_candidates(tenant_id,project_id,build_id,candidate_id),
            CHECK((state='leased' AND attempt>0 AND worker_id IS NOT NULL AND token IS NOT NULL
                AND expires_at_ms IS NOT NULL AND expires_at_ms>=0)
                OR (state!='leased' AND worker_id IS NULL AND token IS NULL AND expires_at_ms IS NULL)),
            CHECK((state='failed' AND attempt>0 AND failure_json IS NOT NULL AND json_valid(failure_json))
                OR (state!='failed' AND failure_json IS NULL)),
            CHECK(state!='completed' OR attempt>0)
         );
         INSERT INTO knowledge_community_jobs_v14 SELECT tenant_id,project_id,build_id,candidate_id,
            state,attempt,worker_id,token,expires_at_ms,failure_json FROM knowledge_community_jobs;
         DROP TABLE knowledge_community_jobs;
         ALTER TABLE knowledge_community_jobs_v14 RENAME TO knowledge_community_jobs;
         CREATE INDEX knowledge_community_claim ON knowledge_community_jobs(tenant_id,project_id,build_id,state);
         CREATE TABLE knowledge_community_audits (
            tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, build_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL, attempt INTEGER NOT NULL CHECK(attempt>0 AND attempt<=4294967295),
            worker_id TEXT NOT NULL, token TEXT NOT NULL,
            invocation_json TEXT NOT NULL CHECK(json_valid(invocation_json)),
            started_at_ms INTEGER NOT NULL CHECK(started_at_ms>=0),
            finished_at_ms INTEGER, latency_ms INTEGER, outcome_json TEXT, request_digest TEXT,
            PRIMARY KEY(tenant_id,project_id,build_id,candidate_id,attempt),
            FOREIGN KEY(tenant_id,project_id,build_id,candidate_id)
                REFERENCES knowledge_community_candidates(tenant_id,project_id,build_id,candidate_id),
            CHECK((finished_at_ms IS NULL AND latency_ms IS NULL AND outcome_json IS NULL AND request_digest IS NULL)
                OR (finished_at_ms>=started_at_ms AND latency_ms>=0 AND json_valid(outcome_json)
                    AND finished_at_ms IS NOT NULL AND latency_ms IS NOT NULL AND outcome_json IS NOT NULL
                    AND request_digest IS NOT NULL AND length(request_digest)=64 AND request_digest NOT GLOB '*[^0-9a-f]*'))
         );
         CREATE TABLE knowledge_community_results (
            tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, build_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL, attempt INTEGER NOT NULL CHECK(attempt>0),
            graph_digest TEXT NOT NULL, submission_json TEXT NOT NULL CHECK(json_valid(submission_json)),
            finished_at_ms INTEGER NOT NULL CHECK(finished_at_ms>=0),
            PRIMARY KEY(tenant_id,project_id,build_id,candidate_id),
            FOREIGN KEY(tenant_id,project_id,build_id,candidate_id,attempt)
                REFERENCES knowledge_community_audits(tenant_id,project_id,build_id,candidate_id,attempt)
         );
         CREATE TABLE knowledge_community_selection (
            tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
            requested_build_id TEXT NOT NULL, active_build_id TEXT,
            revision INTEGER NOT NULL CHECK(revision>0),
            PRIMARY KEY(tenant_id,project_id)
         );
         CREATE TRIGGER knowledge_community_audit_immutable BEFORE UPDATE ON knowledge_community_audits
         WHEN OLD.outcome_json IS NOT NULL OR NEW.tenant_id!=OLD.tenant_id OR NEW.project_id!=OLD.project_id
            OR NEW.build_id!=OLD.build_id OR NEW.candidate_id!=OLD.candidate_id OR NEW.attempt!=OLD.attempt
            OR NEW.worker_id!=OLD.worker_id OR NEW.token!=OLD.token
            OR NEW.invocation_json!=OLD.invocation_json OR NEW.started_at_ms!=OLD.started_at_ms
         BEGIN SELECT RAISE(ABORT,'community audit input or terminal outcome is immutable'); END;
         CREATE TRIGGER knowledge_community_audit_no_delete BEFORE DELETE ON knowledge_community_audits
         BEGIN SELECT RAISE(ABORT,'community audit is immutable'); END;
         CREATE TRIGGER knowledge_community_result_immutable BEFORE UPDATE ON knowledge_community_results
         BEGIN SELECT RAISE(ABORT,'community result is immutable'); END;
         CREATE TRIGGER knowledge_community_result_no_delete BEFORE DELETE ON knowledge_community_results
         BEGIN SELECT RAISE(ABORT,'community result is immutable'); END;"
    ).map_err(storage)
}
