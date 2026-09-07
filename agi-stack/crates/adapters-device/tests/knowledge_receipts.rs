use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::{
    KnowledgeError, KnowledgeScope, MemoryMutation, ScopedMemoryRepository,
};
use agistack_core::Memory;
use futures::executor::block_on;

fn scope(tenant: &str) -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: tenant.into(),
        project_id: "project".into(),
    }
}

fn create(id: &str) -> MemoryMutation {
    MemoryMutation::Create {
        memory: Memory {
            id: id.into(),
            project_id: "project".into(),
            title: "original".into(),
            content: "content".into(),
            author_id: "author".into(),
            content_type: "text".into(),
            tags: vec![],
            entities: vec![],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1,
            embedding: None,
        },
    }
}

#[test]
fn receipts_replay_original_results_and_reject_changed_requests() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let scope = scope("tenant");
        let first = repo
            .mutate(&scope, "actor", "key", create("memory"))
            .await
            .unwrap();
        assert!(!first.replayed);
        let mut edited = first.receipt.memory.clone();
        edited.content = "changed".into();
        let update = MemoryMutation::Update {
            memory: edited,
            expected_revision: 1,
        };
        let second = repo
            .mutate(&scope, "actor", "update", update.clone())
            .await
            .unwrap();
        assert_eq!(second.receipt.memory.version, 2);
        let delete = MemoryMutation::Delete {
            id: "memory".into(),
            expected_revision: 2,
        };
        let third = repo
            .mutate(&scope, "actor", "delete", delete.clone())
            .await
            .unwrap();
        assert!(third.receipt.deleted);
        for (key, mutation, expected) in [
            ("key", create("memory"), first),
            ("update", update, second),
            ("delete", delete, third),
        ] {
            let replay = repo.mutate(&scope, "actor", key, mutation).await.unwrap();
            assert!(replay.replayed);
            assert_eq!(
                serde_json::to_value(replay.receipt).unwrap(),
                serde_json::to_value(expected.receipt).unwrap()
            );
        }
        assert!(matches!(
            repo.mutate(&scope, "actor", "key", create("other")).await,
            Err(KnowledgeError::IdempotencyConflict)
        ));
        assert_eq!(repo.changes(&scope, 0, 100).await.unwrap().len(), 3);
        assert!(repo.get(&scope, "memory").await.unwrap().is_none());
    });
}

#[test]
fn receipts_and_change_pages_are_scoped_and_actor_keys_do_not_collide() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let a = scope("a");
        let b = scope("b");
        let first = repo.mutate(&a, "one", "key", create("one")).await.unwrap();
        repo.mutate(&b, "one", "key", create("one")).await.unwrap();
        let third = repo.mutate(&a, "two", "key", create("two")).await.unwrap();
        assert!(repo
            .change(&b, first.receipt.sequence)
            .await
            .unwrap()
            .is_none());
        let page = repo.changes(&a, first.receipt.sequence, 1).await.unwrap();
        assert_eq!(page.len(), 1);
        assert_eq!(page[0].sequence, third.receipt.sequence);
        assert!(repo.changes(&a, u64::MAX, 1).await.unwrap().is_empty());
        assert!(repo.change(&a, 0).await.unwrap().is_none());
        assert!(repo.changes(&a, 0, 0).await.unwrap().is_empty());
        assert!(matches!(
            repo.mutate(&a, " ", "key", create("bad")).await,
            Err(KnowledgeError::InvalidInput)
        ));
    });
}

#[test]
fn receipts_survive_restart_and_receipt_failure_rolls_back_all_writes() {
    block_on(async {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "knowledge-receipt-{}-{unique}.sqlite",
            std::process::id()
        ));
        let a = scope("a");
        let original;
        {
            let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
            original = repo
                .mutate(&a, "actor", "key", create("memory"))
                .await
                .unwrap()
                .receipt;
        }
        let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        let replay = repo
            .mutate(&a, "actor", "key", create("memory"))
            .await
            .unwrap();
        assert!(replay.replayed);
        assert_eq!(replay.receipt.sequence, original.sequence);
        let connection = rusqlite::Connection::open(&path).unwrap();
        connection.execute_batch("CREATE TRIGGER fail_receipt BEFORE INSERT ON knowledge_mutation_receipts BEGIN SELECT RAISE(ABORT,'injected receipt failure'); END;").unwrap();
        assert!(matches!(
            repo.mutate(&a, "actor", "second", create("second")).await,
            Err(KnowledgeError::Storage(_))
        ));
        assert!(repo.get(&a, "second").await.unwrap().is_none());
        assert_eq!(repo.changes(&a, 0, 100).await.unwrap().len(), 1);
        connection
            .execute_batch("DROP TRIGGER fail_receipt;")
            .unwrap();
        let retry = repo
            .mutate(&a, "actor", "second", create("second"))
            .await
            .unwrap();
        assert!(!retry.replayed);
        drop(connection);
        drop(repo);
        std::fs::remove_file(path).unwrap();
    });
}

#[test]
fn version_one_upgrade_preserves_existing_content_and_changes() {
    block_on(async {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "knowledge-upgrade-{}-{unique}.sqlite",
            std::process::id()
        ));
        let scope = scope("tenant");
        {
            let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
            let MemoryMutation::Create { memory } = create("memory") else {
                unreachable!()
            };
            repo.create(&scope, memory).await.unwrap();
        }
        let connection = rusqlite::Connection::open(&path).unwrap();
        connection.execute_batch("DROP VIEW knowledge_active_pull_conflicts; DROP VIEW knowledge_pending_outbox; DROP VIEW knowledge_unsettled_pushes; DROP TABLE knowledge_cloud_resolved_pushes; DROP TABLE knowledge_cloud_resolved_pull_conflicts; DROP TABLE knowledge_cloud_superseded_outbox; DROP TABLE knowledge_cloud_resolutions;").unwrap();
        connection
            .execute_batch(
                "DROP TABLE knowledge_sync_outbox_metadata; DROP TABLE knowledge_sync_superseded_outbox; DROP TABLE knowledge_sync_resolved_pull_conflicts; DROP TABLE knowledge_sync_resolutions; DROP TABLE knowledge_sync_pull_cursors; DROP TABLE knowledge_sync_pull_events; DROP TABLE knowledge_sync_pull_conflicts; DROP TABLE knowledge_mutation_receipts; DROP TABLE knowledge_sync_pushes; DROP TABLE knowledge_sync_remote_versions; DROP TABLE knowledge_sync_targets; DROP TABLE knowledge_sync_outbox; DROP TABLE knowledge_sync_links; DROP TABLE knowledge_replica; DROP TABLE knowledge_processing_audits; DROP TRIGGER knowledge_processing_enqueue; DROP TABLE knowledge_processing_jobs; DROP TABLE knowledge_derived_projections; UPDATE knowledge_schema SET version=1;",
            )
            .unwrap();
        let upgraded = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        assert_eq!(
            upgraded
                .get(&scope, "memory")
                .await
                .unwrap()
                .unwrap()
                .version,
            1
        );
        assert_eq!(upgraded.changes(&scope, 0, 10).await.unwrap().len(), 1);
        upgraded
            .mutate(&scope, "actor", "key", create("new"))
            .await
            .unwrap();
        let version: i64 = connection
            .query_row("SELECT version FROM knowledge_schema", [], |r| r.get(0))
            .unwrap();
        assert_eq!(
            version,
            agistack_adapters_device::knowledge::KNOWLEDGE_SCHEMA_VERSION
        );
        drop(upgraded);
        drop(connection);
        std::fs::remove_file(path).unwrap();
    });
}

#[test]
fn concurrent_same_key_commits_one_change_and_replays_one_receipt() {
    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "knowledge-idempotency-{}-{unique}.sqlite",
        std::process::id()
    ));
    let first = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
    let second = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let workers: Vec<_> = [first, second]
        .into_iter()
        .map(|repo| {
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                block_on(repo.mutate(&scope("tenant"), "actor", "key", create("memory"))).unwrap()
            })
        })
        .collect();
    let outcomes: Vec<_> = workers
        .into_iter()
        .map(|worker| worker.join().unwrap())
        .collect();
    assert_eq!(
        outcomes.iter().filter(|outcome| outcome.replayed).count(),
        1
    );
    assert_eq!(outcomes[0].receipt.sequence, outcomes[1].receipt.sequence);
    let reopened = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
    assert_eq!(
        block_on(reopened.changes(&scope("tenant"), 0, 100))
            .unwrap()
            .len(),
        1
    );
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}
