use rusqlite::Transaction;

use super::super::{storage, KnowledgeError, KnowledgeResult};

pub(in super::super) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous >= 8 {
        let objects: i64 = tx.query_row(
            "SELECT count(*) FROM sqlite_master WHERE
             (type='table' AND name IN ('knowledge_processing_jobs','knowledge_derived_projections'))
             OR (type='trigger' AND name='knowledge_processing_enqueue')",
            [], |row| row.get(0),
        ).map_err(storage)?;
        if objects != 3 {
            return Err(KnowledgeError::Storage(
                "knowledge processing schema is missing".into(),
            ));
        }
        return Ok(());
    }
    tx.execute_batch(
        "CREATE TABLE knowledge_processing_jobs (
            change_sequence INTEGER PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK(revision > 0 AND revision <= 4294967295),
            state TEXT NOT NULL CHECK(state IN ('pending','leased','completed','failed','superseded')),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0 AND attempt <= 4294967295),
            worker_id TEXT,
            token TEXT,
            expires_at_ms INTEGER,
            failure_json TEXT,
            result_json TEXT,
            UNIQUE(tenant_id,project_id,memory_id,revision),
            CHECK((state='leased' AND worker_id IS NOT NULL AND token IS NOT NULL AND expires_at_ms IS NOT NULL)
                OR (state!='leased' AND worker_id IS NULL AND token IS NULL AND expires_at_ms IS NULL))
         );
         CREATE INDEX knowledge_processing_claim ON knowledge_processing_jobs(tenant_id,project_id,state,change_sequence);
         CREATE TABLE knowledge_derived_projections (
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK(revision > 0),
            change_sequence INTEGER NOT NULL,
            projection_json TEXT NOT NULL,
            PRIMARY KEY(tenant_id,project_id,memory_id)
         );
         CREATE TRIGGER knowledge_processing_enqueue AFTER INSERT ON knowledge_processing_changes
         WHEN EXISTS (
            SELECT 1 FROM knowledge_memories m
            WHERE m.tenant_id=NEW.tenant_id AND m.project_id=NEW.project_id
              AND m.id=NEW.memory_id AND m.revision=NEW.revision AND m.payload=NEW.payload
              AND m.deleted=(NEW.operation='delete')
              AND json_valid(NEW.payload)
              AND json_extract(NEW.payload,'$.id')=NEW.memory_id
              AND json_extract(NEW.payload,'$.project_id')=NEW.project_id
              AND json_extract(NEW.payload,'$.version')=NEW.revision
         ) BEGIN
            UPDATE knowledge_processing_jobs SET state='superseded', worker_id=NULL, token=NULL,
                expires_at_ms=NULL, failure_json=NULL
            WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND memory_id=NEW.memory_id
              AND revision!=NEW.revision AND state IN ('pending','leased','failed');
            DELETE FROM knowledge_derived_projections
            WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND memory_id=NEW.memory_id
              AND (revision!=NEW.revision OR NEW.operation='delete');
            INSERT INTO knowledge_processing_jobs(change_sequence,tenant_id,project_id,memory_id,revision,state,result_json)
            VALUES(NEW.sequence,NEW.tenant_id,NEW.project_id,NEW.memory_id,NEW.revision,
                CASE NEW.operation WHEN 'delete' THEN 'completed' ELSE 'pending' END,
                CASE NEW.operation WHEN 'delete' THEN '{\"kind\":\"deleted\"}' ELSE NULL END);
         END;
         INSERT INTO knowledge_processing_jobs(change_sequence,tenant_id,project_id,memory_id,revision,state)
         SELECT c.sequence,c.tenant_id,c.project_id,c.memory_id,c.revision,'pending'
         FROM knowledge_processing_changes c JOIN knowledge_memories m
           ON m.tenant_id=c.tenant_id AND m.project_id=c.project_id AND m.id=c.memory_id
          AND m.revision=c.revision AND m.payload=c.payload
         WHERE m.deleted=0 AND c.operation='upsert' AND json_valid(c.payload)
           AND json_extract(c.payload,'$.id')=c.memory_id
           AND json_extract(c.payload,'$.project_id')=c.project_id
           AND json_extract(c.payload,'$.version')=c.revision;",
    ).map_err(storage)
}
