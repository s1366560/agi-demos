use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::sync::pull::KnowledgePullRepository;
use agistack_core::knowledge::sync::push::{KnowledgePushRepository, KnowledgeSyncTarget};
use agistack_core::knowledge::sync::resolution::*;
use agistack_core::knowledge::sync::{KnowledgeSyncLink, KnowledgeSyncRepository};
use agistack_core::knowledge::{KnowledgeScope, MemoryMutation, ScopedMemoryRepository};
use futures::executor::block_on;
use serde_json::{json, Value};
fn scope() -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: "tenant".into(),
        project_id: "project".into(),
    }
}
fn target() -> KnowledgeSyncTarget {
    KnowledgeSyncTarget {
        authority: "https://cloud.test/api/v1".into(),
        link: KnowledgeSyncLink {
            remote_tenant_id: "rt".into(),
            remote_project_id: "rp".into(),
            remote_actor_id: "ra".into(),
        },
    }
}
fn event(sequence: u64, revision: u32, deleted: bool) -> Value {
    json!({"sequence":sequence,"change_id":format!("00000000-0000-4000-8000-{sequence:012}"),"version":{"memory_id":"memory","revision":revision,"deleted":deleted,"author_id":"remote-author","created_at_ms":123,"future":{"retain":true},"content":{"title":"Remote","content":format!("remote {revision}"),"content_type":"text","tags":[],"metadata":{"remote_revision":revision},"status":"ENABLED"}}})
}
fn page(events: Vec<Value>, next: u64) -> Value {
    json!({"changes":events,"next_cursor":next,"has_more":false})
}
async fn setup(repo: &SqliteKnowledgeRepository, deleted: bool) {
    repo.configure_sync_link(&scope(), target().link)
        .await
        .unwrap();
    repo.accept_pull_page(&scope(), &target(), 0, page(vec![event(1, 1, false)], 1))
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
    repo.accept_pull_page(&scope(), &target(), 1, page(vec![event(2, 2, deleted)], 2))
        .await
        .unwrap();
}
fn command(choice: KnowledgeConflictChoice) -> KnowledgePullConflictResolution {
    KnowledgePullConflictResolution {
        memory_id: "memory".into(),
        conflict_sequences: vec![2],
        expected_local_revision: 2,
        expected_remote_revision: 2,
        expected_baseline_revision: 1,
        choice,
    }
}
#[test]
fn remote_choice_archives_both_sides_supersedes_only_local_intents_and_never_echoes() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        setup(&repo, true).await;
        let resolved = repo
            .resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "choose-remote",
                command(KnowledgeConflictChoice::UseRemote {}),
            )
            .await
            .unwrap();
        assert_eq!(resolved.receipt.local_revision, 3);
        assert!(resolved.receipt.pending_push_sequences.is_empty());
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        assert!(repo.pull_conflicts(&scope(), 20).await.unwrap().is_empty());
        assert!(repo.sync_outbox(&scope(), 0, 20).await.unwrap().is_empty());
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 2);
        let history = repo
            .resolution_history(&scope(), "memory", 10)
            .await
            .unwrap();
        assert_eq!(history[0]["archive"]["local"]["content"], "local edit");
        assert_eq!(history[0]["archive"]["remote"]["deleted"], true);
        repo.accept_pull_page(&scope(), &target(), 2, page(vec![event(3, 3, false)], 3))
            .await
            .unwrap();
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "remote 3"
        );
        assert!(repo.pull_conflicts(&scope(), 20).await.unwrap().is_empty());
    });
}

#[path = "knowledge_resolution/choices.rs"]
mod choices;
#[path = "knowledge_resolution/guards.rs"]
mod guards;
#[path = "knowledge_resolution/persistence.rs"]
mod persistence;
