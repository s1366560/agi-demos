use super::*;
fn merged() -> KnowledgeConflictChoice {
    KnowledgeConflictChoice::Merged {
        content: KnowledgeMergeContent {
            title: "Merged title".into(),
            content: "Explicit merged content".into(),
            content_type: "document".into(),
            tags: vec!["chosen".into()],
            metadata: json!({"explicit":{"retain":[1,2]}})
                .as_object()
                .unwrap()
                .clone(),
            status: "DISABLED".into(),
        },
    }
}
#[test]
fn local_and_merged_choices_queue_one_genuine_write_with_exact_metadata() {
    block_on(async {
        for choice in [KnowledgeConflictChoice::UseLocal {}, merged()] {
            let repo = SqliteKnowledgeRepository::in_memory().unwrap();
            setup(&repo, false).await;
            let is_merge = matches!(choice, KnowledgeConflictChoice::Merged { .. });
            let result = repo
                .resolve_pull_conflicts(&scope(), &target(), "actor", "choose", command(choice))
                .await
                .unwrap();
            assert_eq!(result.receipt.pending_push_sequences.len(), 1);
            assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 1);
            let push = repo
                .prepare_push(&scope(), &target())
                .await
                .unwrap()
                .unwrap();
            let request: Value = serde_json::from_str(&push.request_json).unwrap();
            assert_eq!(request["expected_revision"], 2);
            assert_eq!(request["operation"], "update");
            assert_eq!(
                request["content"]["metadata"],
                if is_merge {
                    json!({"explicit":{"retain":[1,2]}})
                } else {
                    json!({"remote_revision":1})
                }
            );
            assert_eq!(
                request["content"]["content"],
                if is_merge {
                    "Explicit merged content"
                } else {
                    "local edit"
                }
            );
            assert!(repo.pull_conflicts(&scope(), 20).await.unwrap().is_empty());
            assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 2);
        }
    });
}
#[test]
fn keep_both_copies_local_content_metadata_once_and_original_adopts_remote_tombstone() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        setup(&repo, true).await;
        let first = repo
            .resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "both",
                command(KnowledgeConflictChoice::KeepBoth {}),
            )
            .await
            .unwrap();
        let copy = first.receipt.copy_memory_id.as_ref().unwrap();
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        let copied = repo.get(&scope(), copy).await.unwrap().unwrap();
        assert_eq!(copied.content, "local edit");
        assert_eq!(copied.author_id, "actor");
        assert_eq!(copied.version, 1);
        let replay = repo
            .resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "both",
                command(KnowledgeConflictChoice::KeepBoth {}),
            )
            .await
            .unwrap();
        assert!(replay.replayed);
        assert_eq!(
            serde_json::to_value(&first.receipt).unwrap(),
            serde_json::to_value(replay.receipt).unwrap()
        );
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&push.request_json).unwrap();
        assert_eq!(request["memory_id"], *copy);
        assert_eq!(request["expected_revision"], 0);
        assert_eq!(request["operation"], "create");
        assert_eq!(request["content"]["metadata"], json!({"remote_revision":1}));
        assert_eq!(repo.sync_outbox(&scope(), 0, 20).await.unwrap().len(), 1);
    });
}
#[test]
fn tombstone_restore_is_local_pending_intent_and_never_claims_remote_success() {
    block_on(async {
        for choice in [KnowledgeConflictChoice::UseLocal {}, merged()] {
            let repo = SqliteKnowledgeRepository::in_memory().unwrap();
            setup(&repo, true).await;
            let result = repo
                .resolve_pull_conflicts(&scope(), &target(), "actor", "restore", command(choice))
                .await
                .unwrap();
            assert_eq!(result.receipt.pending_push_sequences.len(), 1);
            assert!(repo.get(&scope(), "memory").await.unwrap().is_some());
            assert_eq!(
                repo.remote_baseline(&scope(), "memory")
                    .await
                    .unwrap()
                    .unwrap()["deleted"],
                true
            );
            assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 1);
            let prepared = repo
                .prepare_push(&scope(), &target())
                .await
                .unwrap()
                .unwrap();
            let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
            assert_eq!(request["operation"], "update");
            assert_eq!(request["expected_revision"], 2);
            assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 1);
        }
    });
}
#[test]
fn user_choice_of_local_tombstone_preserves_it_and_queues_actual_delete() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        setup(&repo, false).await;
        repo.mutate(
            &scope(),
            "actor",
            "delete",
            MemoryMutation::Delete {
                id: "memory".into(),
                expected_revision: 2,
            },
        )
        .await
        .unwrap();
        let mut decision = command(KnowledgeConflictChoice::UseLocal {});
        decision.expected_local_revision = 3;
        let outcome = repo
            .resolve_pull_conflicts(&scope(), &target(), "actor", "local-delete", decision)
            .await
            .unwrap();
        assert_eq!(outcome.receipt.superseded_sequences.len(), 2);
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&push.request_json).unwrap();
        assert_eq!(request["operation"], "delete");
        assert_eq!(request["expected_revision"], 2);
        assert!(request["content"].is_null());
        assert_eq!(
            repo.resolution_history(&scope(), "memory", 10)
                .await
                .unwrap()[0]["archive"]["local_deleted"],
            true
        );
    });
}

#[test]
fn a_new_remote_conflict_after_resolution_retains_explicit_pending_metadata() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        setup(&repo, false).await;
        repo.resolve_pull_conflicts(&scope(), &target(), "actor", "merge", command(merged()))
            .await
            .unwrap();
        repo.accept_pull_page(&scope(), &target(), 2, page(vec![event(3, 3, false)], 3))
            .await
            .unwrap();
        let context = repo
            .pull_conflict_context(&scope(), "memory")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(context.conflict_sequences, [3]);
        assert_eq!(
            context.local_metadata,
            json!({"explicit":{"retain":[1,2]}})
                .as_object()
                .unwrap()
                .clone()
        );
        let mut next = command(KnowledgeConflictChoice::UseLocal {});
        next.conflict_sequences = vec![3];
        next.expected_local_revision = 3;
        next.expected_remote_revision = 3;
        next.expected_baseline_revision = 2;
        repo.resolve_pull_conflicts(&scope(), &target(), "actor", "keep-merge", next)
            .await
            .unwrap();
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let body: Value = serde_json::from_str(&push.request_json).unwrap();
        assert_eq!(body["expected_revision"], 3);
        assert_eq!(
            body["content"]["metadata"],
            json!({"explicit":{"retain":[1,2]}})
        );
        assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 1);
    });
}
