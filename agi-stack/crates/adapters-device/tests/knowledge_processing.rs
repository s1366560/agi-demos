use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::processing::*;
use agistack_core::knowledge::KnowledgeMemory as Memory;
use agistack_core::knowledge::{KnowledgeError, KnowledgeScope, ScopedMemoryRepository};
use agistack_core::Entity;
use futures::executor::block_on;
use rusqlite::Connection;
use uuid::Uuid;

#[path = "knowledge_processing/retry.rs"]
mod retry;
#[path = "knowledge_processing/leases.rs"]
mod leases;
#[path = "knowledge_processing/persistence.rs"]
mod persistence;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-processing-{}.db", Uuid::new_v4())))
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
fn scope() -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: "tenant".into(),
        project_id: "project".into(),
    }
}
fn memory() -> Memory {
    Memory {
        id: "memory".into(),
        project_id: "project".into(),
        title: "Title".into(),
        content: "Source".into(),
        author_id: "actor".into(),
        content_type: "text".into(),
        tags: vec![],
        entities: vec![],
        version: 1,
        status: "ENABLED".into(),
        created_at_ms: 1,
        metadata: Default::default(),
        embedding: None,
    }
}
fn projection() -> ProcessingProjection {
    ProcessingProjection {
        entities: vec![
            Entity {
                name: "Alice".into(),
                kind: "Person".into(),
            },
            Entity {
                name: "OpenAI".into(),
                kind: "Organization".into(),
            },
        ],
        relationships: vec![ProcessingRelationship {
            source_index: 0,
            target_index: 1,
            relation_type: "WORKS_AT".into(),
            fact: "Alice works at OpenAI".into(),
            score: 0.8,
        }],
    }
}

#[test]
fn completed_projection_never_changes_portable_source_or_sync_outbox() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let original = repo.create(&scope(), memory()).await.unwrap();
        let count = || {
            db.connection().query_row("SELECT (SELECT count(*) FROM knowledge_processing_changes),(SELECT count(*) FROM knowledge_sync_outbox)", [], |r| Ok((r.get::<_,i64>(0)?,r.get::<_,i64>(1)?))).unwrap()
        };
        let before = count();
        let lease = repo
            .claim(&scope(), "worker", 100, 50)
            .await
            .unwrap()
            .unwrap();
        repo.complete(&scope(), &lease, projection(), 101)
            .await
            .unwrap();
        let output = repo.projection(&scope(), "memory").await.unwrap().unwrap();
        assert_eq!(output.source, lease.source);
        assert_eq!(output.projection, projection());
        let saved = repo.get(&scope(), "memory").await.unwrap().unwrap();
        assert_eq!(saved.version, original.version);
        assert_eq!(saved.content, original.content);
        assert_eq!(count(), before);
        assert!(repo
            .claim(&scope(), "next", 200, 50)
            .await
            .unwrap()
            .is_none());
        assert_eq!(
            repo.processing_status(&scope(), &lease.source)
                .await
                .unwrap()
                .unwrap()
                .state,
            ProcessingState::Completed
        );
    });
}

#[test]
fn update_preserves_completed_history_but_removes_current_projection() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let mut current = repo.create(&scope(), memory()).await.unwrap();
        let completed = repo
            .claim(&scope(), "worker", 0, 50)
            .await
            .unwrap()
            .unwrap();
        repo.complete(&scope(), &completed, projection(), 1)
            .await
            .unwrap();
        current.content = "New source".into();
        repo.update(&scope(), current, 1).await.unwrap();
        assert!(repo.projection(&scope(), "memory").await.unwrap().is_none());
        let status = repo
            .processing_status(&scope(), &completed.source)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(status.state, ProcessingState::Completed);
        assert_eq!(
            status.result,
            Some(ProcessingResult::Projection(projection()))
        );
        let next = repo
            .claim(&scope(), "worker", 2, 50)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(next.source.revision, 2);
    });
}

#[test]
fn update_supersedes_lease_and_delete_finishes_without_claim_or_projection() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let mut current = repo.create(&scope(), memory()).await.unwrap();
        let stale = repo
            .claim(&scope(), "worker", 0, 50)
            .await
            .unwrap()
            .unwrap();
        current.content = "New source".into();
        repo.update(&scope(), current, 1).await.unwrap();
        assert!(matches!(
            repo.complete(&scope(), &stale, projection(), 1).await,
            Err(KnowledgeError::Conflict)
        ));
        assert_eq!(
            repo.processing_status(&scope(), &stale.source)
                .await
                .unwrap()
                .unwrap()
                .state,
            ProcessingState::Superseded
        );
        let current = repo
            .claim(&scope(), "worker", 2, 50)
            .await
            .unwrap()
            .unwrap();
        repo.complete(&scope(), &current, projection(), 3)
            .await
            .unwrap();
        repo.delete(&scope(), "memory", 2).await.unwrap();
        assert!(repo.projection(&scope(), "memory").await.unwrap().is_none());
        assert!(repo
            .claim(&scope(), "worker", 4, 50)
            .await
            .unwrap()
            .is_none());
        let change = repo
            .changes(&scope(), current.source.change_sequence, 1)
            .await
            .unwrap()
            .remove(0);
        let deleted = ProcessingSource {
            tenant_id: scope().tenant_id,
            project_id: scope().project_id,
            memory_id: "memory".into(),
            revision: 3,
            change_sequence: change.sequence,
        };
        let receipt = repo
            .processing_status(&scope(), &deleted)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(receipt.state, ProcessingState::Completed);
        assert_eq!(receipt.attempt, 0);
        assert_eq!(receipt.result, Some(ProcessingResult::Deleted));
    });
}

#[path = "knowledge_processing/audit.rs"]
mod audit;
