use super::*;

const DOWNGRADE_FIXTURE: &str = "DROP TABLE knowledge_community_results;
 DROP TABLE knowledge_community_audits; DROP TABLE knowledge_community_selection;
 DROP TABLE knowledge_community_jobs;
 DROP TABLE knowledge_community_members; DROP TABLE knowledge_community_candidates;
 DROP TABLE knowledge_community_builds; UPDATE knowledge_schema SET version=12;";

#[test]
fn schema_12_upgrade_preserves_metadata_sources_audits_and_sync_changes() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let s = scope("a", "p");
        let mut memory = create(&repo, &s, "one", "Title", "Content").await;
        memory.metadata.insert(
            "nested".into(),
            serde_json::json!({"array": [1, true, null]}),
        );
        repo.update(&s, memory, 1).await.unwrap();
        finish(&repo, &s, true).await;
        let original = repo.community_snapshot_durable(&s, 2).unwrap();
        let counts = || {
            db.sql().query_row(
            "SELECT (SELECT count(*) FROM knowledge_processing_changes),
              (SELECT count(*) FROM knowledge_sync_outbox),(SELECT count(*) FROM knowledge_processing_audits)",
            [], |r| Ok((r.get::<_,u32>(0)?,r.get::<_,u32>(1)?,r.get::<_,u32>(2)?)),
        ).unwrap()
        };
        let before = counts();
        drop(repo);
        db.sql().execute_batch(DOWNGRADE_FIXTURE).unwrap();
        let repo = db.open();
        assert_eq!(original, repo.community_snapshot_durable(&s, 2).unwrap());
        assert_eq!(before, counts());
        let version: i64 = db
            .sql()
            .query_row("SELECT version FROM knowledge_schema", [], |r| r.get(0))
            .unwrap();
        assert_eq!(version, crate::knowledge::KNOWLEDGE_SCHEMA_VERSION);
        let build = repo
            .create_community_build(&s, &request("after-upgrade"), 10)
            .await
            .unwrap();
        assert_eq!(build.candidate_count, 1);
    });
}

#[test]
fn migration_failure_rolls_back_version_and_partial_tables() {
    let db = Database::new();
    drop(db.open());
    db.sql().execute_batch(DOWNGRADE_FIXTURE).unwrap();
    db.sql()
        .execute_batch("CREATE VIEW knowledge_community_candidates AS SELECT 1 AS invalid")
        .unwrap();
    assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
    let (version, builds): (i64, u32) = db.sql().query_row(
        "SELECT (SELECT version FROM knowledge_schema),
           (SELECT count(*) FROM sqlite_master WHERE type='table' AND name='knowledge_community_builds')",
        [], |r| Ok((r.get(0)?,r.get(1)?)),
    ).unwrap();
    assert_eq!((version, builds), (12, 0));
    db.sql()
        .execute_batch("DROP VIEW knowledge_community_candidates")
        .unwrap();
    drop(db.open());
}

#[test]
fn missing_current_community_objects_and_future_schema_fail_closed() {
    for damage in [
        "DROP TABLE knowledge_community_jobs",
        "DROP TRIGGER knowledge_community_member_immutable",
        "UPDATE knowledge_schema SET version=15",
    ] {
        let db = Database::new();
        drop(db.open());
        db.sql().execute_batch(damage).unwrap();
        assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
    }
}
