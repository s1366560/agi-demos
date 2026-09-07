use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::sync::pull::KnowledgePullRepository;
use agistack_core::knowledge::sync::push::{KnowledgePushRepository, KnowledgeSyncTarget};
use agistack_core::knowledge::sync::{KnowledgeSyncLink, KnowledgeSyncRepository};
use agistack_core::knowledge::{KnowledgeScope, MemoryMutation, ScopedMemoryRepository};
use futures::executor::block_on;
use serde_json::{json, Value};

fn scope() -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: "local-t".into(),
        project_id: "local-p".into(),
    }
}
fn target() -> KnowledgeSyncTarget {
    KnowledgeSyncTarget {
        authority: "https://example.test/api/v1".into(),
        link: KnowledgeSyncLink {
            remote_tenant_id: "remote-t".into(),
            remote_project_id: "remote-p".into(),
            remote_actor_id: "actor".into(),
        },
    }
}
fn event(sequence: u64, revision: u32, deleted: bool, content: &str) -> Value {
    json!({"sequence":sequence,"change_id":format!("00000000-0000-4000-8000-{sequence:012}"),"version":{
        "memory_id":"memory","revision":revision,"deleted":deleted,"author_id":"remote-author","created_at_ms":123,
        "content":{"title":"Remote","content":content,"content_type":"text","tags":[],"metadata":{"preserved":true},"status":"ENABLED"}
    }})
}
fn page(items: Vec<Value>, next: u64) -> Value {
    json!({"changes":items,"next_cursor":next,"has_more":false})
}
async fn repository() -> SqliteKnowledgeRepository {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    repo.configure_sync_link(&scope(), target().link)
        .await
        .unwrap();
    repo
}

#[test]
fn remote_apply_advances_cursor_indexes_without_echo_and_preserves_metadata() {
    block_on(async {
        let repo = repository().await;
        let result = repo
            .accept_pull_page(
                &scope(),
                &target(),
                0,
                page(vec![event(4, 1, false, "first")], 4),
            )
            .await
            .unwrap();
        assert_eq!(result.next_cursor, 4);
        let memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        assert_eq!(memory.project_id, scope().project_id);
        assert_eq!(memory.version, 1);
        assert_eq!(repo.changes(&scope(), 0, 10).await.unwrap().len(), 1);
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
        assert_eq!(
            repo.remote_baseline(&scope(), "memory")
                .await
                .unwrap()
                .unwrap()["content"]["metadata"],
            json!({"preserved":true})
        );
        repo.accept_pull_page(
            &scope(),
            &target(),
            4,
            page(vec![event(7, 2, true, "first")], 7),
        )
        .await
        .unwrap();
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        assert!(repo.changes(&scope(), 0, 10).await.unwrap()[1].deleted);
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
    });
}

#[test]
fn dirty_local_copy_and_remote_delete_are_both_retained_and_push_is_blocked() {
    block_on(async {
        let repo = repository().await;
        repo.accept_pull_page(
            &scope(),
            &target(),
            0,
            page(vec![event(1, 1, false, "base")], 1),
        )
        .await
        .unwrap();
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        memory.content = "local edit".into();
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
        repo.accept_pull_page(
            &scope(),
            &target(),
            1,
            page(vec![event(2, 2, true, "base")], 2),
        )
        .await
        .unwrap();
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "local edit"
        );
        let conflicts = repo.pull_conflicts(&scope(), 20).await.unwrap();
        assert_eq!(conflicts.len(), 1);
        assert_eq!(conflicts[0]["remote"]["deleted"], true);
        assert_eq!(conflicts[0]["local"]["content"], "local edit");
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        assert_eq!(
            repo.remote_baseline(&scope(), "memory")
                .await
                .unwrap()
                .unwrap()["revision"],
            1
        );
    });
}

#[test]
fn malformed_later_event_rolls_back_memory_index_and_cursor() {
    block_on(async {
        let repo = repository().await;
        let mut invalid = event(2, 2, false, "invalid");
        invalid["version"]["author_id"] = json!("different-author");
        assert!(repo
            .accept_pull_page(
                &scope(),
                &target(),
                0,
                page(vec![event(1, 1, false, "valid"), invalid], 2)
            )
            .await
            .is_err());
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 0);
        assert!(repo.changes(&scope(), 0, 10).await.unwrap().is_empty());
    });
}

#[test]
fn stale_cursor_and_wrong_target_cannot_advance_or_duplicate_processing() {
    block_on(async {
        let repo = repository().await;
        let received = page(vec![event(5, 1, false, "first")], 5);
        repo.accept_pull_page(&scope(), &target(), 0, received.clone())
            .await
            .unwrap();
        assert!(repo
            .accept_pull_page(&scope(), &target(), 0, received)
            .await
            .is_err());
        let mut other = target();
        other.authority = "https://other.test/api/v1".into();
        assert!(repo
            .accept_pull_page(&scope(), &other, 5, page(vec![], 5))
            .await
            .is_err());
        assert!(repo
            .accept_pull_page(&scope(), &target(), 5, page(vec![], 6))
            .await
            .is_err());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 5);
        assert_eq!(repo.changes(&scope(), 0, 10).await.unwrap().len(), 1);
    });
}

#[path = "knowledge_pull/edges.rs"]
mod edges;

#[path = "knowledge_pull/persistence.rs"]
mod persistence;

#[path = "knowledge_pull/validation.rs"]
mod validation;

#[path = "knowledge_pull/prepared_retry.rs"]
mod prepared_retry;
