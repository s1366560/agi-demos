use super::*;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("community-results-{}.db", uuid::Uuid::new_v4())))
    }
    fn open(&self) -> SqliteKnowledgeRepository {
        SqliteKnowledgeRepository::open(self.0.to_str().unwrap()).unwrap()
    }
    fn sql(&self) -> Connection {
        Connection::open(&self.0).unwrap()
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

// A storage fixture, not a supported binary rollback. Restore the actual B1
// job state constraint and remove only B2 tables before marking schema 13.
fn schema_13_fixture(db: &Database) {
    db.sql().execute_batch("DROP TABLE knowledge_community_results;
        DROP TABLE knowledge_community_audits; DROP TABLE knowledge_community_selection;
        CREATE TABLE knowledge_community_jobs_v13 (
            tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,build_id TEXT NOT NULL,candidate_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','leased','failed')),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt>=0 AND attempt<=4294967295),
            worker_id TEXT,token TEXT,expires_at_ms INTEGER,failure_json TEXT,
            PRIMARY KEY(tenant_id,project_id,build_id,candidate_id),
            CHECK((state='leased' AND attempt>0 AND worker_id IS NOT NULL AND token IS NOT NULL
                AND expires_at_ms IS NOT NULL AND expires_at_ms>=0)
                OR (state!='leased' AND worker_id IS NULL AND token IS NULL AND expires_at_ms IS NULL)),
            CHECK((state='failed' AND attempt>0 AND failure_json IS NOT NULL AND json_valid(failure_json))
                OR (state!='failed' AND failure_json IS NULL))
        );
        INSERT INTO knowledge_community_jobs_v13 SELECT * FROM knowledge_community_jobs;
        DROP TABLE knowledge_community_jobs;
        ALTER TABLE knowledge_community_jobs_v13 RENAME TO knowledge_community_jobs;
        CREATE INDEX knowledge_community_claim ON knowledge_community_jobs(tenant_id,project_id,build_id,state);
        UPDATE knowledge_schema SET version=13;").unwrap();
}

#[test]
fn upgrade_preserves_b1_input_lease_and_existing_sources_and_audits() {
    let db = Database::new();
    let repo = db.open();
    let s = scope("tenant", "project");
    block_on(create(&repo, &s, "source", "Title", "Content"));
    block_on(finish(&repo, &s, true));
    let build = new_build(&repo, &s, "before-upgrade");
    let input = repo
        .community_build_durable(&s, &build.build_id)
        .unwrap()
        .unwrap();
    let lease = repo
        .claim_community_job_durable(&s, &build.build_id, "worker", 1000, &|| Ok(100))
        .unwrap()
        .unwrap();
    let counts = || {
        db.sql().query_row("SELECT (SELECT count(*) FROM knowledge_processing_audits),
        (SELECT count(*) FROM knowledge_processing_changes),(SELECT count(*) FROM knowledge_sync_outbox)",[],|row|
        Ok((row.get::<_,u32>(0)?,row.get::<_,u32>(1)?,row.get::<_,u32>(2)?))).unwrap()
    };
    let before = counts();
    drop(repo);
    schema_13_fixture(&db);
    let repo = db.open();
    assert_eq!(counts(), before);
    assert_eq!(
        repo.community_build_durable(&s, &build.build_id)
            .unwrap()
            .unwrap(),
        input
    );
    let renewed = repo
        .renew_community_job_durable(&s, &lease, 1000, &|| Ok(102))
        .unwrap();
    assert_eq!(renewed.token, lease.token);
    assert_eq!(renewed.attempt, lease.attempt);
    let version: i64 = db
        .sql()
        .query_row("SELECT version FROM knowledge_schema", [], |r| r.get(0))
        .unwrap();
    assert_eq!(version, 14);
}

#[test]
fn migration_failure_rolls_back_rebuilt_jobs_and_version() {
    let db = Database::new();
    drop(db.open());
    schema_13_fixture(&db);
    db.sql()
        .execute_batch("CREATE VIEW knowledge_community_results AS SELECT 1 AS invalid")
        .unwrap();
    assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
    let (version, temporary, audits): (i64, u32, u32) = db
        .sql()
        .query_row(
            "SELECT
        (SELECT version FROM knowledge_schema),
        (SELECT count(*) FROM sqlite_master WHERE name='knowledge_community_jobs_v14'),
        (SELECT count(*) FROM sqlite_master WHERE name='knowledge_community_audits')",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap();
    assert_eq!((version, temporary, audits), (13, 0, 0));
    let sql: String = db
        .sql()
        .query_row(
            "SELECT sql FROM sqlite_master WHERE name='knowledge_community_jobs'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert!(!sql.contains("completed"));
    db.sql()
        .execute_batch("DROP VIEW knowledge_community_results")
        .unwrap();
    drop(db.open());
}

#[test]
fn results_audits_and_active_selection_survive_reopen() {
    let db = Database::new();
    let repo = db.open();
    let s = scope("tenant", "project");
    block_on(create(&repo, &s, "source", "Title", "Content"));
    block_on(finish(&repo, &s, true));
    let build = new_build(&repo, &s, "durable");
    let (lease, input) = begin(&repo, &s, &build);
    let audit = apply(&repo, &s, &lease, &input, true);
    let selected = repo
        .select_community_build_durable(&s, &build.build_id, 0, &|| Ok(103))
        .unwrap();
    repo.activate_community_build_durable(&s, &build.build_id, selected.revision, &|| Ok(104))
        .unwrap();
    let active = repo.active_community_build_durable(&s).unwrap();
    drop(repo);
    let repo = db.open();
    assert_eq!(repo.active_community_build_durable(&s).unwrap(), active);
    assert_eq!(
        repo.community_audit_durable(&s, &build.build_id, &lease.candidate_id, lease.attempt)
            .unwrap()
            .unwrap(),
        audit
    );
    assert_eq!(apply(&repo, &s, &lease, &input, true), audit);
}

#[test]
fn missing_result_schema_and_future_versions_fail_closed() {
    for sql in [
        "DROP TABLE knowledge_community_selection",
        "DROP TRIGGER knowledge_community_audit_no_delete",
        "UPDATE knowledge_schema SET version=15",
    ] {
        let db = Database::new();
        drop(db.open());
        db.sql().execute_batch(sql).unwrap();
        assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
    }
}
