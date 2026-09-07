use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::sync::{
    cloud_resolution::*,
    pull::KnowledgePullRepository,
    push::{KnowledgePushRepository, KnowledgeSyncTarget},
    resolution::*,
    KnowledgeSyncLink, KnowledgeSyncRepository,
};
use agistack_core::knowledge::{KnowledgeScope, MemoryMutation, ScopedMemoryRepository};
use futures::executor::block_on;
use serde_json::{json, Value};

fn scope() -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: "local-tenant".into(),
        project_id: "local-project".into(),
    }
}
fn target() -> KnowledgeSyncTarget {
    KnowledgeSyncTarget {
        authority: "https://cloud.test/api/v1".into(),
        link: KnowledgeSyncLink {
            remote_tenant_id: "rt".into(),
            remote_project_id: "rp".into(),
            remote_actor_id: "remote-actor".into(),
        },
    }
}
fn remote(revision: u32, deleted: bool) -> Value {
    json!({"memory_id":"memory","revision":revision,"deleted":deleted,"author_id":"remote-author","created_at_ms":123,"extension":{"retained":true},"content":{"title":"Remote","content":format!("remote {revision}"),"content_type":"text","tags":[],"metadata":{"revision":revision},"status":"ENABLED"}})
}
fn page(sequence: u64, value: Value) -> Value {
    json!({"changes":[{"sequence":sequence,"change_id":format!("00000000-0000-4000-8000-{sequence:012}"),"version":value}],"next_cursor":sequence,"has_more":false})
}
async fn setup(repo: &SqliteKnowledgeRepository, deleted: bool) -> (u64, Value) {
    repo.configure_sync_link(&scope(), target().link)
        .await
        .unwrap();
    repo.accept_pull_page(&scope(), &target(), 0, page(1, remote(1, false)))
        .await
        .unwrap();
    edit(repo, "first", "local proposal").await;
    let push = repo
        .prepare_push(&scope(), &target())
        .await
        .unwrap()
        .unwrap();
    repo.accept_pull_page(&scope(), &target(), 1, page(2, remote(2, deleted)))
        .await
        .unwrap();
    let mut proposed: Value = serde_json::from_str(&push.request_json).unwrap();
    proposed.as_object_mut().unwrap().remove("change_id");
    let id = uuid::Uuid::new_v4().to_string();
    let verified = json!({"id":id,"memory_id":"memory","proposed":proposed,"current":remote(2,deleted),"observed_current":remote(2,deleted),"resolved_change_id":null});
    repo.accept_push_receipt(&scope(), &target(), push.local_sequence, json!({"replayed":false,"receipt":{"status":"conflict","change_id":push.change_id,"conflict_id":id}}), Some(verified.clone())).await.unwrap();
    (push.local_sequence, verified)
}
async fn edit(repo: &SqliteKnowledgeRepository, key: &str, text: &str) {
    let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
    let expected_revision = memory.version;
    memory.content = text.into();
    repo.mutate(
        &scope(),
        "actor",
        key,
        MemoryMutation::Update {
            memory,
            expected_revision,
        },
    )
    .await
    .unwrap();
}
fn command(
    sequence: u64,
    verified: &Value,
    choice: KnowledgeCloudChoice,
) -> KnowledgeCloudResolutionCommand {
    KnowledgeCloudResolutionCommand {
        local_sequence: sequence,
        memory_id: "memory".into(),
        conflict_id: verified["id"].as_str().unwrap().into(),
        guard: KnowledgeCloudResolutionGuard {
            expected_local_revision: 2,
            expected_remote_revision: 2,
            expected_baseline_revision: 1,
            conflict_sequences: vec![2],
        },
        choice,
    }
}
fn response(record: &KnowledgeCloudResolutionRecord, value: Value) -> Value {
    let receipt = if matches!(record.command.choice, KnowledgeCloudChoice::KeepCurrent {}) {
        json!({"status":"resolved","change_id":record.resolution_id,"conflict_id":record.command.conflict_id,"version":value})
    } else {
        json!({"status":"applied","change_id":record.resolution_id,"sequence":3,"version":value})
    };
    json!({"replayed":false,"receipt":receipt})
}
fn applied_version(record: &KnowledgeCloudResolutionRecord) -> Value {
    let mut value = remote(3, false);
    value["content"] = match &record.command.choice {
        KnowledgeCloudChoice::Merged { content } => serde_json::to_value(content).unwrap(),
        _ => record.archive.original_request["content"].clone(),
    };
    value
}
fn guard(ctx: &KnowledgeCloudResolutionContext) -> KnowledgeCloudResolutionGuard {
    KnowledgeCloudResolutionGuard {
        expected_local_revision: ctx.local.version,
        expected_remote_revision: ctx
            .remote
            .as_ref()
            .map_or(0, |v| v["revision"].as_u64().unwrap() as u32),
        expected_baseline_revision: ctx
            .baseline
            .as_ref()
            .map_or(0, |v| v["revision"].as_u64().unwrap() as u32),
        conflict_sequences: ctx.conflict_sequences.clone(),
    }
}
fn merged() -> KnowledgeMergeContent {
    KnowledgeMergeContent {
        title: "Merged".into(),
        content: "explicit combined content".into(),
        content_type: "text".into(),
        tags: vec!["selected".into()],
        metadata: serde_json::from_value(json!({"explicit":true})).unwrap(),
        status: "ENABLED".into(),
    }
}

#[path = "knowledge_cloud_resolution/choices.rs"]
mod choices;
#[path = "knowledge_cloud_resolution/guards.rs"]
mod guards;
#[path = "knowledge_cloud_resolution/persistence.rs"]
mod persistence;

#[path = "knowledge_cloud_resolution/absence.rs"]
mod absence;

#[test]
fn keep_current_has_no_journal_sequence_and_settles_both_conflicts_without_echo() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (sequence, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "keep",
                command(sequence, &verified, KnowledgeCloudChoice::KeepCurrent {}),
                verified.clone(),
            )
            .unwrap();
        let outcome = repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                response(&record, remote(2, false)),
            )
            .unwrap();
        assert!(!outcome.pending_reconciliation);
        assert_eq!(outcome.receipt["sequence"], Value::Null);
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "remote 2"
        );
        assert!(repo.push_conflicts(&scope(), 10).await.unwrap().is_empty());
        assert!(repo.pull_conflicts(&scope(), 10).await.unwrap().is_empty());
        assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 0);
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 2);
        assert_eq!(
            repo.remote_baseline(&scope(), "memory")
                .await
                .unwrap()
                .unwrap(),
            remote(2, false)
        );
    });
}
