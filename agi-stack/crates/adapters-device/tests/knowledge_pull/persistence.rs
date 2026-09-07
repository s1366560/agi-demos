use super::*;
use rusqlite::Connection;
use std::sync::{Arc, Barrier};

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-pull-{}.db", uuid::Uuid::new_v4())))
    }
    fn open(&self) -> SqliteKnowledgeRepository {
        SqliteKnowledgeRepository::open(self.0.to_str().unwrap()).unwrap()
    }
    fn connection(&self) -> Connection {
        Connection::open(&self.0).unwrap()
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

#[test]
fn concurrent_pages_compare_and_swap_cursor_once_across_connections() {
    let db = Database::new();
    let first = db.open();
    block_on(first.configure_sync_link(&scope(), target().link)).unwrap();
    let second = db.open();
    let barrier = Arc::new(Barrier::new(2));
    let workers: Vec<_> = [first, second]
        .into_iter()
        .map(|repo| {
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                block_on(repo.accept_pull_page(
                    &scope(),
                    &target(),
                    0,
                    page(vec![event(3, 1, false, "one")], 3),
                ))
            })
        })
        .collect();
    let outcomes: Vec<_> = workers
        .into_iter()
        .map(|worker| worker.join().unwrap())
        .collect();
    assert_eq!(outcomes.iter().filter(|result| result.is_ok()).count(), 1);
    assert!(outcomes.iter().any(|result| matches!(
        result,
        Err(agistack_core::knowledge::KnowledgeError::Conflict)
    )));
    let repo = db.open();
    assert_eq!(block_on(repo.pull_cursor(&scope(), &target())).unwrap(), 3);
    assert_eq!(block_on(repo.changes(&scope(), 0, 10)).unwrap().len(), 1);
    assert!(block_on(repo.sync_outbox(&scope(), 0, 10))
        .unwrap()
        .is_empty());
}

#[test]
fn cursor_write_failure_rolls_back_content_baselines_conflicts_and_journal() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        repo.accept_pull_page(
            &scope(),
            &target(),
            0,
            page(vec![event(1, 1, false, "base")], 1),
        )
        .await
        .unwrap();
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        memory.content = "local".into();
        repo.mutate(
            &scope(),
            "actor",
            "edit",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        db.connection().execute_batch("CREATE TRIGGER fail_pull_cursor BEFORE UPDATE ON knowledge_sync_pull_cursors BEGIN SELECT RAISE(ABORT, 'injected cursor persistence failure'); END;").unwrap();
        let mut other = event(3, 1, false, "other");
        other["version"]["memory_id"] = json!("other");
        let response = page(vec![event(2, 2, true, "base"), other], 3);
        assert!(repo
            .accept_pull_page(&scope(), &target(), 1, response.clone())
            .await
            .is_err());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 1);
        assert!(repo.pull_conflicts(&scope(), 10).await.unwrap().is_empty());
        assert!(repo.get(&scope(), "other").await.unwrap().is_none());
        assert!(repo
            .remote_baseline(&scope(), "other")
            .await
            .unwrap()
            .is_none());
        assert_eq!(repo.changes(&scope(), 0, 10).await.unwrap().len(), 2);
        db.connection()
            .execute_batch("DROP TRIGGER fail_pull_cursor;")
            .unwrap();
        let result = repo
            .accept_pull_page(&scope(), &target(), 1, response)
            .await
            .unwrap();
        assert_eq!((result.applied, result.conflicts), (1, 1));
    });
}

#[test]
fn version_four_upgrade_preserves_replica_prepared_outbox_and_restart_cursor_without_echo() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        let push = super::edges::prepared(&repo).await;
        let replica: String = db
            .connection()
            .query_row("SELECT replica_id FROM knowledge_replica", [], |row| {
                row.get(0)
            })
            .unwrap();
        drop(repo);
        db.connection().execute_batch("DROP VIEW knowledge_active_pull_conflicts; DROP VIEW knowledge_pending_outbox; DROP VIEW knowledge_unsettled_pushes; DROP TABLE knowledge_cloud_resolved_pushes; DROP TABLE knowledge_cloud_resolved_pull_conflicts; DROP TABLE knowledge_cloud_superseded_outbox; DROP TABLE knowledge_cloud_resolutions;").unwrap();
        db.connection().execute_batch("DROP TABLE knowledge_sync_outbox_metadata; DROP TABLE knowledge_sync_superseded_outbox; DROP TABLE knowledge_sync_resolved_pull_conflicts; DROP TABLE knowledge_sync_resolutions; DROP TABLE knowledge_sync_pull_cursors; DROP TABLE knowledge_sync_pull_events; DROP TABLE knowledge_sync_pull_conflicts; DROP TRIGGER knowledge_processing_enqueue; DROP TABLE knowledge_processing_jobs; DROP TABLE knowledge_derived_projections; UPDATE knowledge_schema SET version=4;").unwrap();
        let repo = db.open();
        assert_eq!(
            repo.prepare_push(&scope(), &target())
                .await
                .unwrap()
                .unwrap(),
            push
        );
        let replica_after: String = db
            .connection()
            .query_row("SELECT replica_id FROM knowledge_replica", [], |row| {
                row.get(0)
            })
            .unwrap();
        assert_eq!(replica_after, replica);
        let version: i64 = db
            .connection()
            .query_row("SELECT version FROM knowledge_schema", [], |row| row.get(0))
            .unwrap();
        assert_eq!(
            version,
            agistack_adapters_device::knowledge::KNOWLEDGE_SCHEMA_VERSION
        );
        let remote = super::edges::own_event(&push, 6);
        repo.accept_pull_page(&scope(), &target(), 0, page(vec![remote], 6))
            .await
            .unwrap();
        let mut deleted = event(9, 2, true, "local");
        deleted["version"]["author_id"] = json!(target().link.remote_actor_id);
        deleted["version"]["content"]["metadata"] = json!({});
        repo.accept_pull_page(&scope(), &target(), 6, page(vec![deleted], 9))
            .await
            .unwrap();
        drop(repo);
        let repo = db.open();
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 9);
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        assert_eq!(repo.changes(&scope(), 0, 10).await.unwrap().len(), 2);
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
    });
}

#[test]
fn claimed_current_schema_with_missing_pull_table_fails_without_silent_repair() {
    let db = Database::new();
    drop(db.open());
    db.connection()
        .execute_batch("DROP TABLE knowledge_sync_pull_events;")
        .unwrap();
    assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
    let count: i64 = db
        .connection()
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE name='knowledge_sync_pull_events'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(count, 0);
}

#[test]
fn concurrent_local_edit_and_remote_page_never_overwrite_an_accepted_local_mutation() {
    let db = Database::new();
    let first = db.open();
    block_on(first.configure_sync_link(&scope(), target().link)).unwrap();
    block_on(first.accept_pull_page(
        &scope(),
        &target(),
        0,
        page(vec![event(1, 1, false, "base")], 1),
    ))
    .unwrap();
    let second = db.open();
    let mut memory = block_on(first.get(&scope(), "memory")).unwrap().unwrap();
    memory.content = "local edit".into();
    let barrier = Arc::new(Barrier::new(2));
    let local_barrier = Arc::clone(&barrier);
    let local = std::thread::spawn(move || {
        local_barrier.wait();
        block_on(first.mutate(
            &scope(),
            "actor",
            "edit",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        ))
    });
    let remote = std::thread::spawn(move || {
        barrier.wait();
        block_on(second.accept_pull_page(
            &scope(),
            &target(),
            1,
            page(vec![event(2, 2, false, "remote edit")], 2),
        ))
        .unwrap()
    });
    let local = local.join().unwrap();
    let remote = remote.join().unwrap();
    let repo = db.open();
    let current = block_on(repo.get(&scope(), "memory")).unwrap().unwrap();
    if local.is_ok() {
        assert_eq!(current.content, "local edit");
        assert_eq!((remote.applied, remote.conflicts), (0, 1));
        assert_eq!(
            block_on(repo.sync_outbox(&scope(), 0, 10)).unwrap().len(),
            1
        );
    } else {
        assert!(matches!(
            local,
            Err(agistack_core::knowledge::KnowledgeError::Conflict)
        ));
        assert_eq!(current.content, "remote edit");
        assert_eq!((remote.applied, remote.conflicts), (1, 0));
        assert!(block_on(repo.sync_outbox(&scope(), 0, 10))
            .unwrap()
            .is_empty());
    }
    assert_eq!(current.version, 2);
    assert_eq!(block_on(repo.changes(&scope(), 0, 10)).unwrap().len(), 2);
}
