use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::sync::pull::{KnowledgePullReceipt, KnowledgePullRepository};
use agistack_core::knowledge::sync::push::{KnowledgePushRepository, KnowledgeSyncTarget};
use agistack_core::knowledge::sync::{
    KnowledgeSyncLink, KnowledgeSyncRepository, KnowledgeUnbindPolicy,
};
use agistack_core::knowledge::KnowledgeMemory as Memory;
use agistack_core::knowledge::{
    KnowledgeError, KnowledgeScope, MemoryMutation, ScopedMemoryRepository,
};
use futures::executor::block_on;
use serde_json::{json, Value};
use uuid::Uuid;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-unbind-{}.db", Uuid::new_v4())))
    }
    fn open(&self) -> SqliteKnowledgeRepository {
        SqliteKnowledgeRepository::open(self.0.to_str().unwrap()).unwrap()
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn scope() -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: "local-tenant".into(),
        project_id: "local-project".into(),
    }
}
fn target() -> KnowledgeSyncTarget {
    KnowledgeSyncTarget {
        authority: "https://example.test/api/v1".into(),
        link: KnowledgeSyncLink {
            remote_tenant_id: "remote-tenant".into(),
            remote_project_id: "remote-project".into(),
            remote_actor_id: "remote-actor".into(),
        },
    }
}
fn create(id: &str) -> MemoryMutation {
    MemoryMutation::Create {
        memory: Memory {
            id: id.into(),
            project_id: "local-project".into(),
            title: "title".into(),
            content: "original".into(),
            content_type: "text".into(),
            author_id: "local-author".into(),
            tags: vec![],
            entities: vec![],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1,
            metadata: Default::default(),
            embedding: None,
        },
    }
}
fn event(sequence: u64, memory_id: &str, revision: u32, deleted: bool) -> Value {
    json!({"sequence":sequence,"change_id":format!("00000000-0000-4000-8000-{sequence:012}"),"version":{
        "memory_id":memory_id,"revision":revision,"deleted":deleted,"author_id":"remote-author","created_at_ms":123,
        "content":{"title":"Remote","content":"downloaded","content_type":"text","tags":[],"metadata":{},"status":"ENABLED"}
    }})
}
fn page(items: Vec<Value>, next: u64) -> Value {
    json!({"changes":items,"next_cursor":next,"has_more":false})
}
async fn bound(repo: &SqliteKnowledgeRepository) {
    repo.bind_verified_sync_target_durable(&scope(), &target(), &|| Ok(()))
        .unwrap();
}
async fn pull(repo: &SqliteKnowledgeRepository, after: u64, page: Value) -> KnowledgePullReceipt {
    repo.accept_pull_page(&scope(), &target(), after, page)
        .await
        .unwrap()
}

#[test]
fn unbind_requires_an_existing_binding() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        assert!(matches!(
            repo.unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Keep, 1),
            Err(KnowledgeError::NotFound)
        ));
        assert!(matches!(
            repo.unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Delete, 1),
            Err(KnowledgeError::NotFound)
        ));
    });
}

#[test]
fn keep_unbind_preserves_copies_and_fences_pending_work() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        bound(&repo).await;
        pull(&repo, 0, page(vec![event(3, "cloud-1", 1, false)], 3)).await;
        repo.mutate(&scope(), "local-author", "create", create("local-1"))
            .await
            .unwrap();
        assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 1);

        let receipt = repo
            .unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Keep, 42)
            .unwrap();
        assert_eq!(receipt.link, target().link);
        assert_eq!(receipt.policy, KnowledgeUnbindPolicy::Keep);
        assert_eq!(receipt.fenced_outbox, 1);
        assert_eq!(receipt.removed_local_copies, 0);

        let status = repo.sync_status(&scope()).await.unwrap();
        assert_eq!(status.link, None);
        assert_eq!(status.pending_changes, 0);
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
        // Every transport path rechecks the stored binding and fails closed.
        assert!(matches!(
            repo.prepare_push(&scope(), &target()).await,
            Err(KnowledgeError::Conflict)
        ));
        assert!(matches!(
            repo.pull_cursor(&scope(), &target()).await,
            Err(KnowledgeError::Conflict)
        ));
        assert!(matches!(
            repo.accept_pull_page(&scope(), &target(), 0, page(vec![], 0))
                .await,
            Err(KnowledgeError::Conflict)
        ));
        // Both copies remain ordinary local records; the keep policy retains
        // the remote baseline so a later re-bind can resume without conflicts.
        assert!(repo.get(&scope(), "cloud-1").await.unwrap().is_some());
        assert!(repo.get(&scope(), "local-1").await.unwrap().is_some());
        assert!(repo
            .remote_baseline(&scope(), "cloud-1")
            .await
            .unwrap()
            .is_some());
    });
}

#[test]
fn delete_unbind_tombstones_only_cloud_origin_copies() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        bound(&repo).await;
        pull(
            &repo,
            0,
            page(
                vec![event(1, "cloud-1", 1, false), event(2, "cloud-2", 1, false)],
                2,
            ),
        )
        .await;
        // A local edit of a downloaded copy does not change its cloud origin.
        let mut edited = repo.get(&scope(), "cloud-2").await.unwrap().unwrap();
        edited.content = "local edit".into();
        repo.mutate(
            &scope(),
            "local-author",
            "edit",
            MemoryMutation::Update {
                memory: edited,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        repo.mutate(&scope(), "local-author", "create", create("local-1"))
            .await
            .unwrap();

        let receipt = repo
            .unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Delete, 42)
            .unwrap();
        assert_eq!(receipt.removed_local_copies, 2);
        assert!(repo.get(&scope(), "cloud-1").await.unwrap().is_none());
        assert!(repo.get(&scope(), "cloud-2").await.unwrap().is_none());
        assert!(repo.get(&scope(), "local-1").await.unwrap().is_some());
        assert!(repo
            .remote_baseline(&scope(), "cloud-1")
            .await
            .unwrap()
            .is_none());
        // v1 policy keeps tombstones: the rows stay, flagged out of visibility.
        let connection = rusqlite::Connection::open(&db.0).unwrap();
        let tombstones: i64 = connection
            .query_row(
                "SELECT count(*) FROM knowledge_memories WHERE tenant_id='local-tenant' AND project_id='local-project' AND deleted=1",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(tombstones, 2);
        let audited: (String, i64, i64) = connection
            .query_row(
                "SELECT policy,fenced_outbox,removed_local_copies FROM knowledge_sync_unbinds",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(audited, ("delete".to_string(), 2, 2));
    });
}

#[test]
fn rebind_after_unbind_is_fresh_and_never_revives_fenced_work() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        bound(&repo).await;
        pull(&repo, 0, page(vec![event(3, "cloud-1", 1, false)], 3)).await;
        repo.mutate(&scope(), "local-author", "create", create("local-1"))
            .await
            .unwrap();
        repo.unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Keep, 42)
            .unwrap();

        let rebound = repo
            .bind_verified_sync_target_durable(&scope(), &target(), &|| Ok(()))
            .unwrap();
        assert_eq!(rebound.link, Some(target().link));
        assert_eq!(rebound.pending_changes, 0);
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 0);
        // The kept baseline consumes the replayed journal without conflicts.
        let replayed = pull(&repo, 0, page(vec![event(3, "cloud-1", 1, false)], 3)).await;
        assert_eq!(replayed.applied, 0);
        assert_eq!(replayed.conflicts, 0);
        assert!(repo.pull_conflicts(&scope(), 10).await.unwrap().is_empty());
        // New local work after the re-bind enrolls fresh outbox entries.
        repo.mutate(&scope(), "local-author", "create-2", create("local-2"))
            .await
            .unwrap();
        assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 1);
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_some());
        // A different remote is a legitimate fresh binding after unbind.
        repo.unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Keep, 43)
            .unwrap();
        let mut other = target();
        other.link.remote_project_id = "other-remote-project".into();
        assert!(repo
            .bind_verified_sync_target_durable(&scope(), &other, &|| Ok(()))
            .is_ok());
    });
}

#[test]
fn rebind_after_delete_unbind_surfaces_conflicts_instead_of_resurrecting() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        bound(&repo).await;
        pull(&repo, 0, page(vec![event(3, "cloud-1", 1, false)], 3)).await;
        repo.unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Delete, 42)
            .unwrap();
        assert!(repo
            .bind_verified_sync_target_durable(&scope(), &target(), &|| Ok(()))
            .is_ok());
        let replayed = pull(&repo, 0, page(vec![event(3, "cloud-1", 1, false)], 3)).await;
        assert_eq!(replayed.applied, 0);
        assert_eq!(replayed.conflicts, 1);
        assert_eq!(repo.pull_conflicts(&scope(), 10).await.unwrap().len(), 1);
        // The tombstone survives the replay; only an explicit resolution can restore.
        assert!(repo.get(&scope(), "cloud-1").await.unwrap().is_none());
    });
}

#[test]
fn unbind_rejects_inflight_pushes_and_prepared_pulls() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        bound(&repo).await;
        repo.mutate(&scope(), "local-author", "create", create("local-1"))
            .await
            .unwrap();
        let prepared = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        repo.unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Keep, 42)
            .unwrap();
        let response = json!({"receipt":{"status":"applied","change_id":prepared.change_id,
            "sequence":10,"version":{"memory_id":"local-1","revision":1,"deleted":false,
            "author_id":"remote-actor","created_at_ms":100,"content":{}}},"replayed":false});
        assert!(matches!(
            repo.accept_push_receipt_durable(
                &scope(),
                &target(),
                prepared.local_sequence,
                response,
                None
            ),
            Err(KnowledgeError::Conflict)
        ));
        assert!(matches!(
            repo.accept_pull_page_durable(&scope(), &target(), 0, page(vec![], 0)),
            Err(KnowledgeError::Conflict)
        ));
    });
}

#[test]
fn failed_unbind_rolls_back_atomically() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        bound(&repo).await;
        pull(&repo, 0, page(vec![event(1, "cloud-1", 1, false)], 1)).await;
        repo.mutate(&scope(), "local-author", "create", create("local-1"))
            .await
            .unwrap();
        let connection = rusqlite::Connection::open(&db.0).unwrap();
        connection
            .execute_batch(
                "CREATE TRIGGER fail_unbind BEFORE INSERT ON knowledge_sync_unbinds
                 BEGIN SELECT RAISE(ABORT,'fixture'); END;",
            )
            .unwrap();
        assert!(repo
            .unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Delete, 42)
            .is_err());
        let status = repo.sync_status(&scope()).await.unwrap();
        assert_eq!(status.link, Some(target().link));
        assert_eq!(status.pending_changes, 1);
        assert!(repo.get(&scope(), "cloud-1").await.unwrap().is_some());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 1);
        let fenced: i64 = connection
            .query_row(
                "SELECT count(*) FROM knowledge_sync_unbound_outbox",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(fenced, 0);
        connection
            .execute_batch("DROP TRIGGER fail_unbind")
            .unwrap();
        assert!(repo
            .unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Delete, 42)
            .is_ok());
        assert_eq!(repo.sync_status(&scope()).await.unwrap().link, None);
    });
}
