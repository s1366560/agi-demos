use super::*;
use rusqlite::Connection;
use std::sync::{Arc, Barrier};
struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-resolution-{}.db", uuid::Uuid::new_v4())))
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
#[test]
fn resolution_and_copy_receipt_survive_restart_and_same_key_concurrency() {
    let db = Database::new();
    let first = db.open();
    block_on(setup(&first, true));
    let second = db.open();
    let barrier = Arc::new(Barrier::new(2));
    let workers: Vec<_> = [first, second]
        .into_iter()
        .map(|repo| {
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                block_on(repo.resolve_pull_conflicts(
                    &scope(),
                    &target(),
                    "actor",
                    "both",
                    command(KnowledgeConflictChoice::KeepBoth {}),
                ))
                .unwrap()
            })
        })
        .collect();
    let results: Vec<_> = workers.into_iter().map(|w| w.join().unwrap()).collect();
    assert_eq!(results.iter().filter(|r| r.replayed).count(), 1);
    assert_eq!(
        serde_json::to_value(&results[0].receipt).unwrap(),
        serde_json::to_value(&results[1].receipt).unwrap()
    );
    let repo = db.open();
    let replay = block_on(repo.resolve_pull_conflicts(
        &scope(),
        &target(),
        "actor",
        "both",
        command(KnowledgeConflictChoice::KeepBoth {}),
    ))
    .unwrap();
    assert!(replay.replayed);
    assert_eq!(
        serde_json::to_value(&replay.receipt).unwrap(),
        serde_json::to_value(&results[0].receipt).unwrap()
    );
    assert_eq!(
        block_on(repo.resolution_history(&scope(), "memory", 20))
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        block_on(repo.sync_outbox(&scope(), 0, 20)).unwrap().len(),
        1
    );
    assert_eq!(block_on(repo.pull_cursor(&scope(), &target())).unwrap(), 2);
}
#[test]
fn injected_failures_roll_back_resolution_archives_maps_content_and_outbox() {
    block_on(async {
        for table in [
            "knowledge_sync_resolutions",
            "knowledge_sync_resolved_pull_conflicts",
            "knowledge_sync_superseded_outbox",
            "knowledge_sync_outbox_metadata",
        ] {
            let db = Database::new();
            let repo = db.open();
            setup(&repo, false).await;
            db.sql().execute_batch(&format!("CREATE TRIGGER injected_failure BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END;")).unwrap();
            assert!(repo
                .resolve_pull_conflicts(
                    &scope(),
                    &target(),
                    "actor",
                    "both",
                    command(KnowledgeConflictChoice::KeepBoth {})
                )
                .await
                .is_err());
            assert_eq!(
                repo.get(&scope(), "memory").await.unwrap().unwrap().content,
                "local edit"
            );
            assert_eq!(repo.changes(&scope(), 0, 20).await.unwrap().len(), 2);
            assert_eq!(repo.sync_outbox(&scope(), 0, 20).await.unwrap().len(), 1);
            assert_eq!(repo.pull_conflicts(&scope(), 20).await.unwrap().len(), 1);
            assert!(repo
                .resolution_history(&scope(), "memory", 20)
                .await
                .unwrap()
                .is_empty());
            assert_eq!(
                repo.remote_baseline(&scope(), "memory")
                    .await
                    .unwrap()
                    .unwrap()["revision"],
                1
            );
            assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 2);
            db.sql()
                .execute_batch("DROP TRIGGER injected_failure;")
                .unwrap();
            repo.resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "both",
                command(KnowledgeConflictChoice::KeepBoth {}),
            )
            .await
            .unwrap();
        }
    });
}
#[test]
fn schema_five_upgrade_keeps_conflicts_and_replica_and_current_missing_table_is_not_repaired() {
    let db = Database::new();
    let repo = db.open();
    block_on(setup(&repo, false));
    drop(repo);
    let replica: String = db
        .sql()
        .query_row("SELECT replica_id FROM knowledge_replica", [], |r| r.get(0))
        .unwrap();
    db.sql().execute_batch("DROP VIEW knowledge_active_pull_conflicts; DROP VIEW knowledge_pending_outbox; DROP VIEW knowledge_unsettled_pushes; DROP TABLE knowledge_cloud_resolved_pushes; DROP TABLE knowledge_cloud_resolved_pull_conflicts; DROP TABLE knowledge_cloud_superseded_outbox; DROP TABLE knowledge_cloud_resolutions;").unwrap();
    db.sql().execute_batch("DROP TABLE knowledge_sync_outbox_metadata; DROP TABLE knowledge_sync_superseded_outbox; DROP TABLE knowledge_sync_resolved_pull_conflicts; DROP TABLE knowledge_sync_resolutions; UPDATE knowledge_schema SET version=5;").unwrap();
    let repo = db.open();
    assert_eq!(
        block_on(repo.pull_conflicts(&scope(), 20)).unwrap().len(),
        1
    );
    assert_eq!(
        block_on(repo.sync_outbox(&scope(), 0, 20)).unwrap().len(),
        1
    );
    let current:(i64,String)=db.sql().query_row("SELECT (SELECT version FROM knowledge_schema),(SELECT replica_id FROM knowledge_replica)",[],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();
    assert_eq!(current, (7, replica));
    drop(repo);
    db.sql()
        .execute_batch("DROP TABLE knowledge_sync_outbox_metadata;")
        .unwrap();
    assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
    let count: i64 = db
        .sql()
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE name='knowledge_sync_outbox_metadata'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(count, 0);
}
