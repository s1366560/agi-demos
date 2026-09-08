use super::*;
use agistack_core::knowledge::sync::push::PreparedKnowledgePush;

pub(super) async fn prepared(repo: &SqliteKnowledgeRepository) -> PreparedKnowledgePush {
    let remote = event(1, 1, false, "local");
    let memory = agistack_core::knowledge::KnowledgeMemory {
        id: "memory".into(),
        project_id: scope().project_id,
        title: "Remote".into(),
        content: "local".into(),
        author_id: "local-author".into(),
        content_type: "text".into(),
        tags: vec![],
        entities: vec![],
        version: 1,
        status: "ENABLED".into(),
        created_at_ms: remote["version"]["created_at_ms"].as_i64().unwrap(),
        metadata: Default::default(),
        embedding: None,
    };
    repo.mutate(
        &scope(),
        "local-author",
        "create",
        MemoryMutation::Create { memory },
    )
    .await
    .unwrap();
    repo.prepare_push(&scope(), &target())
        .await
        .unwrap()
        .unwrap()
}
pub(super) fn own_event(push: &PreparedKnowledgePush, sequence: u64) -> Value {
    let request: Value = serde_json::from_str(&push.request_json).unwrap();
    let mut value = event(sequence, 1, false, "local");
    value["change_id"] = json!(push.change_id);
    value["version"]["author_id"] = json!(target().link.remote_actor_id);
    value["version"]["content"] = request["content"].clone();
    value
}
fn receipt(event: &Value) -> Value {
    json!({"receipt":{"status":"applied","sequence":event["sequence"],"change_id":event["change_id"],"version":event["version"]},"replayed":false})
}

#[test]
fn own_journal_before_lost_receipt_acknowledges_without_conflict_or_local_overwrite() {
    block_on(async {
        let repo = repository().await;
        let push = prepared(&repo).await;
        let remote = own_event(&push, 5);
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        memory.content = "later local edit".into();
        repo.mutate(
            &scope(),
            "local-author",
            "edit",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        let result = repo
            .accept_pull_page(&scope(), &target(), 0, page(vec![remote.clone()], 5))
            .await
            .unwrap();
        assert_eq!(result.conflicts, 0);
        assert_eq!(result.applied, 0);
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "later local edit"
        );
        assert_eq!(repo.changes(&scope(), 0, 10).await.unwrap().len(), 2);
        assert_eq!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().len(), 1);
        assert!(repo.pull_conflicts(&scope(), 10).await.unwrap().is_empty());
        let replay = repo
            .accept_push_receipt(
                &scope(),
                &target(),
                push.local_sequence,
                receipt(&remote),
                None,
            )
            .await
            .unwrap();
        assert!(replay.replayed);
        let next = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&next.request_json).unwrap();
        assert_eq!(request["expected_revision"], 1);
        assert_eq!(request["content"]["content"], "later local edit");
    });
}

#[test]
fn own_journal_acknowledgement_rolls_back_with_the_page_and_rejects_forged_snapshots() {
    block_on(async {
        let repo = repository().await;
        let push = prepared(&repo).await;
        let remote = own_event(&push, 5);
        let mut forged = remote.clone();
        forged["version"]["content"]["content"] = json!("not the submitted content");
        assert!(repo
            .accept_pull_page(&scope(), &target(), 0, page(vec![forged], 5))
            .await
            .is_err());
        let mut invalid = event(6, 2, false, "invalid");
        invalid["version"]["author_id"] = json!("wrong-author");
        assert!(repo
            .accept_pull_page(
                &scope(),
                &target(),
                0,
                page(vec![remote.clone(), invalid], 6)
            )
            .await
            .is_err());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 0);
        assert!(repo
            .remote_baseline(&scope(), "memory")
            .await
            .unwrap()
            .is_none());
        assert_eq!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().len(), 1);
        assert_eq!(
            repo.prepare_push(&scope(), &target())
                .await
                .unwrap()
                .unwrap(),
            push
        );
        repo.accept_pull_page(&scope(), &target(), 0, page(vec![remote], 5))
            .await
            .unwrap();
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
    });
}

#[test]
fn push_receipts_ahead_of_cursor_consume_old_journal_without_regressing_baseline() {
    block_on(async {
        let repo = repository().await;
        let first = prepared(&repo).await;
        let old = own_event(&first, 3);
        repo.accept_push_receipt(
            &scope(),
            &target(),
            first.local_sequence,
            receipt(&old),
            None,
        )
        .await
        .unwrap();
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        memory.content = "second".into();
        repo.mutate(
            &scope(),
            "local-author",
            "second",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        let second = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let mut new = own_event(&second, 7);
        new["version"]["revision"] = json!(2);
        repo.accept_push_receipt(
            &scope(),
            &target(),
            second.local_sequence,
            receipt(&new),
            None,
        )
        .await
        .unwrap();
        let result = repo
            .accept_pull_page(&scope(), &target(), 0, page(vec![old, new], 7))
            .await
            .unwrap();
        assert_eq!((result.applied, result.conflicts), (0, 0));
        assert_eq!(
            repo.remote_baseline(&scope(), "memory")
                .await
                .unwrap()
                .unwrap()["revision"],
            2
        );
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "second"
        );
        assert_eq!(repo.changes(&scope(), 0, 10).await.unwrap().len(), 2);
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
    });
}

#[test]
fn remote_delete_restore_and_newer_edit_preserve_snapshots_and_never_echo() {
    block_on(async {
        let repo = repository().await;
        let mut restored = event(9, 3, false, "restored");
        restored["version"]["content"]["metadata"] = json!({"nested":[{"你好": true}]});
        restored["version"]["future_version_field"] = json!({"preserve": [1, 2]});
        repo.accept_pull_page(
            &scope(),
            &target(),
            0,
            page(
                vec![
                    event(2, 1, false, "base"),
                    event(5, 2, true, "base"),
                    restored.clone(),
                ],
                9,
            ),
        )
        .await
        .unwrap();
        let memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        assert_eq!((memory.version, memory.content.as_str()), (3, "restored"));
        assert_eq!(
            repo.remote_baseline(&scope(), "memory")
                .await
                .unwrap()
                .unwrap(),
            restored["version"]
        );
        let changes = repo.changes(&scope(), 0, 10).await.unwrap();
        assert_eq!(
            changes.iter().map(|c| c.deleted).collect::<Vec<_>>(),
            [false, true, false]
        );
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
    });
}

#[test]
fn local_tombstone_and_multiple_remote_versions_remain_conflicts_while_other_objects_apply() {
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
        repo.mutate(
            &scope(),
            "actor",
            "delete",
            MemoryMutation::Delete {
                id: "memory".into(),
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        let mut other = event(4, 1, false, "other");
        other["version"]["memory_id"] = json!("other");
        let result = repo
            .accept_pull_page(
                &scope(),
                &target(),
                1,
                page(
                    vec![
                        event(2, 2, false, "remote edit"),
                        event(3, 3, true, "remote edit"),
                        other,
                    ],
                    4,
                ),
            )
            .await
            .unwrap();
        assert_eq!((result.applied, result.conflicts), (1, 2));
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        assert_eq!(
            repo.get(&scope(), "other").await.unwrap().unwrap().content,
            "other"
        );
        let conflicts = repo.pull_conflicts(&scope(), 10).await.unwrap();
        assert_eq!(conflicts.len(), 2);
        for conflict in conflicts {
            assert_eq!(conflict["local_deleted"], true);
            assert_eq!(conflict["baseline"]["revision"], 1);
            assert_eq!(conflict["local"]["content"], "base");
        }
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
    });
}

#[test]
fn wrong_remote_identity_and_local_scope_never_observe_or_advance_another_cursor() {
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
        for field in 0..4 {
            let mut wrong = target();
            match field {
                0 => wrong.authority = "https://elsewhere.test/api/v1".into(),
                1 => wrong.link.remote_actor_id = "another-actor".into(),
                2 => wrong.link.remote_tenant_id = "another-tenant".into(),
                _ => wrong.link.remote_project_id = "another-project".into(),
            }
            assert!(repo.pull_cursor(&scope(), &wrong).await.is_err());
            assert!(repo
                .accept_pull_page(
                    &scope(),
                    &wrong,
                    1,
                    page(vec![event(2, 2, false, "wrong")], 2)
                )
                .await
                .is_err());
        }
        for field in 0..2 {
            let mut other = scope();
            if field == 0 {
                other.tenant_id = "other-tenant".into();
            } else {
                other.project_id = "other-project".into();
            }
            assert!(repo.pull_cursor(&other, &target()).await.is_err());
            assert!(repo
                .accept_pull_page(
                    &other,
                    &target(),
                    0,
                    page(vec![event(1, 1, false, "wrong")], 1)
                )
                .await
                .is_err());
            assert!(repo.pull_conflicts(&other, 10).await.unwrap().is_empty());
        }
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 1);
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "base"
        );
    });
}
