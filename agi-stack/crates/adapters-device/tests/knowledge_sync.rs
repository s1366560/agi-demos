use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::sync::{KnowledgeSyncLink, KnowledgeSyncRepository};
use agistack_core::knowledge::KnowledgeMemory as Memory;
use agistack_core::knowledge::{
    KnowledgeError, KnowledgeScope, MemoryMutation, ScopedMemoryRepository,
};
use futures::executor::block_on;
use uuid::Uuid;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-sync-{}.db", Uuid::new_v4())))
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
fn scope(tenant: &str) -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: tenant.into(),
        project_id: "project".into(),
    }
}
fn link() -> KnowledgeSyncLink {
    KnowledgeSyncLink {
        remote_tenant_id: "remote-tenant".into(),
        remote_project_id: "remote-project".into(),
        remote_actor_id: "remote-actor".into(),
    }
}
fn create() -> MemoryMutation {
    MemoryMutation::Create {
        memory: Memory {
            id: "memory".into(),
            project_id: "project".into(),
            title: "title".into(),
            content: "original".into(),
            author_id: "actor".into(),
            content_type: "text".into(),
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

#[test]
fn missing_replica_or_outbox_cannot_silently_start_a_new_identity() {
    for damage in [
        "DELETE FROM knowledge_replica",
        "DROP TABLE knowledge_sync_outbox",
    ] {
        let db = Database::new();
        drop(db.open());
        let connection = rusqlite::Connection::open(&db.0).unwrap();
        connection.execute_batch(damage).unwrap();
        assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
    }
}

#[test]
fn replica_outbox_and_explicit_links_survive_restart_without_scope_inference() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let scope = scope("tenant");
        let status = repo.sync_status(&scope).await.unwrap();
        assert!(status.link.is_none());
        assert_eq!(status.pending_changes, 0);
        let created = repo
            .mutate(&scope, "actor", "create", create())
            .await
            .unwrap();
        assert!(repo.sync_status(&scope).await.unwrap().link.is_none());
        let configured = repo.configure_sync_link(&scope, link()).await.unwrap();
        assert_eq!(configured.link, Some(link()));
        assert_eq!(
            repo.configure_sync_link(&scope, link()).await.unwrap().link,
            Some(link())
        );
        let mut foreign = link();
        foreign.remote_actor_id = "another".into();
        assert!(matches!(
            repo.configure_sync_link(&scope, foreign).await,
            Err(KnowledgeError::Conflict)
        ));
        let other = KnowledgeScope {
            tenant_id: "foreign".into(),
            project_id: scope.project_id.clone(),
        };
        assert!(repo.sync_status(&other).await.unwrap().link.is_none());
        assert!(repo.sync_outbox(&other, 0, 10).await.unwrap().is_empty());
        let other_project = KnowledgeScope {
            tenant_id: scope.tenant_id.clone(),
            project_id: "other-project".into(),
        };
        assert!(repo
            .sync_outbox(&other_project, 0, 10)
            .await
            .unwrap()
            .is_empty());
        let mut memory = created.receipt.memory;
        memory.content = "updated".into();
        repo.mutate(
            &scope,
            "actor",
            "update",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        repo.mutate(
            &scope,
            "actor",
            "delete",
            MemoryMutation::Delete {
                id: "memory".into(),
                expected_revision: 2,
            },
        )
        .await
        .unwrap();
        assert!(
            repo.mutate(&scope, "actor", "create", create())
                .await
                .unwrap()
                .replayed
        );
        let changes = repo.sync_outbox(&scope, 0, 10).await.unwrap();
        assert_eq!(changes.len(), 3);
        assert!(changes[2].local_change.deleted);
        for change in &changes {
            assert_eq!(
                change.change_id,
                Uuid::new_v5(
                    &Uuid::parse_str(&status.replica_id).unwrap(),
                    change.local_change.sequence.to_string().as_bytes()
                )
                .to_string()
            );
        }
        let last_page = repo
            .sync_outbox(&scope, changes[0].local_change.sequence, 1)
            .await
            .unwrap();
        assert_eq!(last_page[0].change_id, changes[1].change_id);
        drop(repo);
        let reopened = db.open();
        assert_eq!(
            reopened.sync_status(&scope).await.unwrap().replica_id,
            status.replica_id
        );
        assert_eq!(
            reopened.sync_status(&scope).await.unwrap().link,
            Some(link())
        );
        assert_eq!(
            serde_json::to_value(reopened.sync_outbox(&scope, 0, 10).await.unwrap()).unwrap(),
            serde_json::to_value(changes).unwrap()
        );
    });
}

#[test]
fn outbox_failure_rolls_back_content_changes_and_receipts() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let scope = scope("tenant");
        let connection = rusqlite::Connection::open(&db.0).unwrap();
        connection.execute_batch("CREATE TRIGGER fail_outbox BEFORE INSERT ON knowledge_sync_outbox BEGIN SELECT RAISE(ABORT,'outbox unavailable'); END;").unwrap();
        assert!(repo
            .mutate(&scope, "actor", "create", create())
            .await
            .is_err());
        assert!(repo.get(&scope, "memory").await.unwrap().is_none());
        assert!(repo.changes(&scope, 0, 10).await.unwrap().is_empty());
        assert_eq!(repo.sync_status(&scope).await.unwrap().pending_changes, 0);
        connection
            .execute_batch("DROP TRIGGER fail_outbox;")
            .unwrap();
        assert!(
            !repo
                .mutate(&scope, "actor", "create", create())
                .await
                .unwrap()
                .replayed
        );
        assert_eq!(repo.sync_outbox(&scope, 0, 10).await.unwrap().len(), 1);
    });
}

#[test]
fn v2_migration_backfills_only_scoped_local_changes_once() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let scope = scope("tenant");
        repo.mutate(&scope, "actor", "create", create())
            .await
            .unwrap();
        drop(repo);
        let connection = rusqlite::Connection::open(&db.0).unwrap();
        connection.execute_batch("DROP VIEW knowledge_active_pull_conflicts; DROP VIEW knowledge_pending_outbox; DROP VIEW knowledge_unsettled_pushes; DROP TABLE knowledge_cloud_resolved_pushes; DROP TABLE knowledge_cloud_resolved_pull_conflicts; DROP TABLE knowledge_cloud_superseded_outbox; DROP TABLE knowledge_cloud_resolutions;").unwrap();
        connection.execute_batch("DROP TABLE knowledge_sync_pushes; DROP TABLE knowledge_sync_remote_versions; DROP TABLE knowledge_sync_targets; DROP TABLE knowledge_sync_outbox; DROP TABLE knowledge_sync_links; DROP TABLE knowledge_replica; DROP TABLE knowledge_processing_audits; DROP TRIGGER knowledge_processing_enqueue; DROP TABLE knowledge_processing_jobs; DROP TABLE knowledge_derived_projections; UPDATE knowledge_schema SET version=2; CREATE TABLE memories(id TEXT,project_id TEXT); INSERT INTO memories VALUES('unattributed','project');").unwrap();
        let upgraded = db.open();
        let status = upgraded.sync_status(&scope).await.unwrap();
        assert!(status.link.is_none());
        assert_eq!(status.pending_changes, 1);
        assert_eq!(
            upgraded.sync_outbox(&scope, 0, 10).await.unwrap()[0]
                .local_change
                .memory
                .id,
            "memory"
        );
        drop(upgraded);
        let reopened = db.open();
        assert_eq!(
            reopened.sync_status(&scope).await.unwrap().replica_id,
            status.replica_id
        );
        assert_eq!(
            reopened.sync_status(&scope).await.unwrap().pending_changes,
            1
        );
        let legacy: i64 = connection
            .query_row("SELECT count(*) FROM memories", [], |row| row.get(0))
            .unwrap();
        assert_eq!(legacy, 1);
    });
}
