use super::*;
use agistack_core::knowledge::KnowledgeError;
#[test]
fn complete_conflict_set_and_all_three_revisions_are_atomic_compare_and_swap_guards() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        setup(&repo, false).await;
        for field in 0..4 {
            let mut wrong = command(KnowledgeConflictChoice::UseRemote {});
            match field {
                0 => wrong.expected_local_revision = 1,
                1 => wrong.expected_remote_revision = 1,
                2 => wrong.expected_baseline_revision = 0,
                _ => wrong.conflict_sequences = vec![1, 2],
            };
            assert!(matches!(
                repo.resolve_pull_conflicts(&scope(), &target(), "actor", "choice", wrong)
                    .await,
                Err(KnowledgeError::Conflict)
            ));
        }
        repo.accept_pull_page(&scope(), &target(), 2, page(vec![event(4, 3, false)], 4))
            .await
            .unwrap();
        assert!(matches!(
            repo.resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "choice",
                command(KnowledgeConflictChoice::UseRemote {})
            )
            .await,
            Err(KnowledgeError::Conflict)
        ));
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "local edit"
        );
        assert_eq!(repo.pull_conflicts(&scope(), 20).await.unwrap().len(), 2);
        assert!(repo
            .resolution_history(&scope(), "memory", 10)
            .await
            .unwrap()
            .is_empty());
        let context = repo
            .pull_conflict_context(&scope(), "memory")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(context.conflict_sequences, [2, 4]);
        let mut current = command(KnowledgeConflictChoice::UseRemote {});
        current.conflict_sequences = context.conflict_sequences;
        current.expected_remote_revision = 3;
        repo.resolve_pull_conflicts(&scope(), &target(), "actor", "choice", current)
            .await
            .unwrap();
        assert!(repo.pull_conflicts(&scope(), 20).await.unwrap().is_empty());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 4);
    });
}
#[test]
fn prepared_or_cloud_conflicted_push_cannot_be_released_by_local_resolution() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
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
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        repo.accept_pull_page(&scope(), &target(), 1, page(vec![event(2, 2, false)], 2))
            .await
            .unwrap();
        assert!(matches!(
            repo.resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "resolve",
                command(KnowledgeConflictChoice::UseRemote {})
            )
            .await,
            Err(KnowledgeError::Conflict)
        ));
        let mut proposed: Value = serde_json::from_str(&push.request_json).unwrap();
        proposed.as_object_mut().unwrap().remove("change_id");
        let id = uuid::Uuid::new_v4().to_string();
        let conflict = json!({"id":id,"memory_id":"memory","proposed":proposed,"current":event(2,2,false)["version"],"resolved_change_id":null});
        repo.accept_push_receipt(&scope(),&target(),push.local_sequence,json!({"receipt":{"status":"conflict","change_id":push.change_id,"conflict_id":id},"replayed":false}),Some(conflict.clone())).await.unwrap();
        assert!(matches!(
            repo.resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "resolve",
                command(KnowledgeConflictChoice::UseRemote {})
            )
            .await,
            Err(KnowledgeError::Conflict)
        ));
        assert_eq!(repo.push_conflicts(&scope(), 10).await.unwrap(), [conflict]);
        assert_eq!(repo.pull_conflicts(&scope(), 10).await.unwrap().len(), 1);
    });
}
#[test]
fn replay_after_later_edit_is_exact_and_different_payload_or_scope_cannot_reuse_it() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        setup(&repo, false).await;
        let first = repo
            .resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "key",
                command(KnowledgeConflictChoice::UseRemote {}),
            )
            .await
            .unwrap();
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        memory.content = "later".into();
        repo.mutate(
            &scope(),
            "actor",
            "later",
            MemoryMutation::Update {
                memory,
                expected_revision: 3,
            },
        )
        .await
        .unwrap();
        let replay = repo
            .resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "key",
                command(KnowledgeConflictChoice::UseRemote {}),
            )
            .await
            .unwrap();
        assert!(replay.replayed);
        assert_eq!(
            serde_json::to_value(first.receipt).unwrap(),
            serde_json::to_value(replay.receipt).unwrap()
        );
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "later"
        );
        assert!(matches!(
            repo.resolve_pull_conflicts(
                &scope(),
                &target(),
                "actor",
                "key",
                command(KnowledgeConflictChoice::UseLocal {})
            )
            .await,
            Err(KnowledgeError::IdempotencyConflict)
        ));
        assert!(repo
            .resolve_pull_conflicts(
                &scope(),
                &target(),
                "other-actor",
                "key",
                command(KnowledgeConflictChoice::UseRemote {})
            )
            .await
            .is_err());
        let other = KnowledgeScope {
            tenant_id: "other".into(),
            project_id: scope().project_id,
        };
        assert!(repo
            .resolution_history(&other, "memory", 10)
            .await
            .unwrap()
            .is_empty());
        assert!(repo
            .resolve_pull_conflicts(
                &other,
                &target(),
                "actor",
                "key",
                command(KnowledgeConflictChoice::UseRemote {})
            )
            .await
            .is_err());
        let mut wrong = target();
        wrong.link.remote_actor_id = "other".into();
        assert!(repo
            .resolve_pull_conflicts(
                &scope(),
                &wrong,
                "actor",
                "key",
                command(KnowledgeConflictChoice::UseRemote {})
            )
            .await
            .is_err());
    });
}

#[test]
fn structured_resolution_rejects_extra_or_ambiguous_choices_and_invalid_guards() {
    let original = serde_json::to_value(command(KnowledgeConflictChoice::UseRemote {})).unwrap();
    let mut extra = original.clone();
    extra["choice"]["content"] = json!({});
    assert!(serde_json::from_value::<KnowledgePullConflictResolution>(extra).is_err());
    let mut extra = original.clone();
    extra["remote_snapshot"] = json!({});
    assert!(serde_json::from_value::<KnowledgePullConflictResolution>(extra).is_err());
    for sequences in [vec![], vec![2, 2], vec![3, 2], vec![0]] {
        let mut invalid = command(KnowledgeConflictChoice::UseRemote {});
        invalid.conflict_sequences = sequences;
        assert!(invalid.validate().is_err());
    }
    let mut invalid = command(KnowledgeConflictChoice::UseRemote {});
    invalid.expected_local_revision = 0;
    assert!(invalid.validate().is_err());
    let mut invalid = original;
    invalid["choice"] = json!({"decision":"merged","content":{"title":"title","content":"text","content_type":"text","tags":[],"status":"ENABLED","metadata":{},"extra":true}});
    assert!(serde_json::from_value::<KnowledgePullConflictResolution>(invalid).is_err());
}

#[test]
fn historical_successful_push_does_not_block_local_pull_resolution_or_become_superseded() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        repo.accept_pull_page(&scope(), &target(), 0, page(vec![event(1, 1, false)], 1))
            .await
            .unwrap();
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        memory.content = "first edit".into();
        repo.mutate(
            &scope(),
            "actor",
            "first",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&push.request_json).unwrap();
        let mut own = event(2, 2, false);
        own["change_id"] = json!(push.change_id);
        own["version"]["content"] = request["content"].clone();
        repo.accept_push_receipt(&scope(),&target(),push.local_sequence,json!({"receipt":{"status":"applied","change_id":own["change_id"],"sequence":2,"version":own["version"]},"replayed":false}),None).await.unwrap();
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        memory.content = "second edit".into();
        repo.mutate(
            &scope(),
            "actor",
            "second",
            MemoryMutation::Update {
                memory,
                expected_revision: 2,
            },
        )
        .await
        .unwrap();
        repo.accept_pull_page(
            &scope(),
            &target(),
            1,
            page(vec![own, event(5, 3, false)], 5),
        )
        .await
        .unwrap();
        let mut decision = command(KnowledgeConflictChoice::UseRemote {});
        decision.conflict_sequences = vec![5];
        decision.expected_local_revision = 3;
        decision.expected_remote_revision = 3;
        decision.expected_baseline_revision = 2;
        let result = repo
            .resolve_pull_conflicts(&scope(), &target(), "actor", "remote", decision)
            .await
            .unwrap();
        assert_eq!(result.receipt.superseded_sequences.len(), 1);
        assert!(!result
            .receipt
            .superseded_sequences
            .contains(&push.local_sequence));
        assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 0);
    });
}
