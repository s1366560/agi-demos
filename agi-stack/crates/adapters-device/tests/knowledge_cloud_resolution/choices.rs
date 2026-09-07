use super::*;

#[test]
fn own_resolution_journal_event_recovers_lost_applied_receipt_before_cursor_commit() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (seq, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "choose",
                command(seq, &verified, KnowledgeCloudChoice::UseProposed {}),
                verified,
            )
            .unwrap();
        let mut event = page(3, applied_version(&record));
        event["changes"][0]["change_id"] = json!(record.resolution_id);
        let result = repo
            .accept_pull_page(&scope(), &target(), 2, event)
            .await
            .unwrap();
        assert_eq!(result.conflicts, 0);
        let recovered = repo
            .cloud_resolution_record_durable(&scope(), &target(), "actor", &record.resolution_id)
            .unwrap();
        assert!(recovered.receipt.is_some());
        assert!(recovered.reconciliation.is_some());
        assert!(
            repo.accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                response(&record, applied_version(&record))
            )
            .unwrap()
            .replayed
        );
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 3);
    });
}

#[test]
fn cloud_proposed_and_merged_restore_tombstones_without_echo_or_rewriting_history() {
    block_on(async {
        for choice in [
            KnowledgeCloudChoice::UseProposed {},
            KnowledgeCloudChoice::Merged { content: merged() },
        ] {
            let repo = SqliteKnowledgeRepository::in_memory().unwrap();
            let (seq, verified) = setup(&repo, true).await;
            let record = repo
                .prepare_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    "restore",
                    command(seq, &verified, choice),
                    verified,
                )
                .unwrap();
            let value = applied_version(&record);
            let result = repo
                .accept_cloud_resolution_receipt_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    response(&record, value.clone()),
                )
                .unwrap();
            assert!(!result.pending_reconciliation);
            assert_eq!(
                repo.get(&scope(), "memory").await.unwrap().unwrap().content,
                value["content"]["content"]
            );
            assert_eq!(
                repo.remote_baseline(&scope(), "memory")
                    .await
                    .unwrap()
                    .unwrap(),
                value
            );
            assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
            let replay = repo
                .accept_cloud_resolution_receipt_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    response(&record, value.clone()),
                )
                .unwrap();
            assert!(replay.replayed);
            assert_eq!(repo.changes(&scope(), 0, 20).await.unwrap().len(), 3);
            repo.accept_pull_page(&scope(), &target(), 2, page(3, value))
                .await
                .unwrap();
            assert!(repo.pull_conflicts(&scope(), 10).await.unwrap().is_empty());
        }
    });
}

#[test]
fn network_edit_preserves_success_and_requires_a_fresh_explicit_reconciliation() {
    block_on(async {
        for choice in [
            KnowledgeConflictChoice::UseLocal {},
            KnowledgeConflictChoice::UseRemote {},
            KnowledgeConflictChoice::Merged { content: merged() },
            KnowledgeConflictChoice::KeepBoth {},
        ] {
            let repo = SqliteKnowledgeRepository::in_memory().unwrap();
            let (seq, verified) = setup(&repo, false).await;
            let record = repo
                .prepare_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    "decide",
                    command(seq, &verified, KnowledgeCloudChoice::KeepCurrent {}),
                    verified,
                )
                .unwrap();
            edit(&repo, "during network", "new local work").await;
            let ack = response(&record, remote(2, false));
            let result = repo
                .accept_cloud_resolution_receipt_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    ack.clone(),
                )
                .unwrap();
            assert!(result.pending_reconciliation);
            let local_context = repo
                .pull_conflict_context(&scope(), "memory")
                .await
                .unwrap()
                .unwrap();
            assert!(repo
                .resolve_pull_conflicts(
                    &scope(),
                    &target(),
                    "actor",
                    "must wait",
                    KnowledgePullConflictResolution {
                        memory_id: "memory".into(),
                        conflict_sequences: local_context.conflict_sequences,
                        expected_local_revision: local_context.local.version,
                        expected_remote_revision: 2,
                        expected_baseline_revision: 2,
                        choice: KnowledgeConflictChoice::UseRemote {}
                    }
                )
                .await
                .is_err());
            assert_eq!(
                repo.get(&scope(), "memory").await.unwrap().unwrap().content,
                "new local work"
            );
            assert!(repo
                .prepare_push(&scope(), &target())
                .await
                .unwrap()
                .is_none());
            assert!(
                repo.accept_cloud_resolution_receipt_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    ack
                )
                .unwrap()
                .pending_reconciliation
            );
            let ctx = repo
                .cloud_reconciliation_context_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                )
                .unwrap();
            assert_eq!(ctx.local_metadata, record.archive.local_metadata);
            let command = KnowledgeCloudReconciliationCommand {
                guard: guard(&ctx),
                choice: choice.clone(),
            };
            let mut stale = command.clone();
            stale.guard.expected_local_revision -= 1;
            assert!(repo
                .reconcile_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    stale
                )
                .is_err());
            let done = repo
                .reconcile_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    command.clone(),
                )
                .unwrap();
            assert!(!done.pending_reconciliation);
            assert!(
                repo.reconcile_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    command
                )
                .unwrap()
                .replayed
            );
            assert!(repo.push_conflicts(&scope(), 10).await.unwrap().is_empty());
            assert!(repo.pull_conflicts(&scope(), 10).await.unwrap().is_empty());
            let journal = repo
                .cloud_resolution_record_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                )
                .unwrap();
            let reconciliation = journal.reconciliation.unwrap();
            match choice {
                KnowledgeConflictChoice::UseRemote {} => {
                    assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty())
                }
                KnowledgeConflictChoice::KeepBoth {} => {
                    let copy = repo
                        .get(&scope(), &reconciliation.copy_memory_id.unwrap())
                        .await
                        .unwrap()
                        .unwrap();
                    assert_eq!(copy.content, "new local work");
                    assert_eq!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().len(), 1);
                }
                _ => {
                    let push = repo
                        .prepare_push(&scope(), &target())
                        .await
                        .unwrap()
                        .unwrap();
                    let request: Value = serde_json::from_str(&push.request_json).unwrap();
                    assert_eq!(request["expected_revision"], 2);
                    assert_eq!(
                        request["content"]["metadata"],
                        if matches!(choice, KnowledgeConflictChoice::UseLocal {}) {
                            json!({"revision":1})
                        } else {
                            json!({"explicit":true})
                        }
                    );
                }
            }
        }
    });
}

#[test]
fn new_remote_conflict_during_network_requires_new_choice_and_latest_remote_guard() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (seq, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "decide",
                command(seq, &verified, KnowledgeCloudChoice::UseProposed {}),
                verified,
            )
            .unwrap();
        repo.accept_pull_page(&scope(), &target(), 2, page(4, remote(4, false)))
            .await
            .unwrap();
        let ack = repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                response(&record, applied_version(&record)),
            )
            .unwrap();
        assert!(ack.pending_reconciliation);
        let ctx = repo
            .cloud_reconciliation_context_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
            )
            .unwrap();
        assert_eq!(ctx.remote.as_ref().unwrap()["revision"], 4);
        assert_eq!(ctx.conflict_sequences, vec![2, 4]);
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 4);
        repo.reconcile_cloud_resolution_durable(
            &scope(),
            &target(),
            "actor",
            &record.resolution_id,
            KnowledgeCloudReconciliationCommand {
                guard: guard(&ctx),
                choice: KnowledgeConflictChoice::UseRemote {},
            },
        )
        .unwrap();
        assert_eq!(
            repo.remote_baseline(&scope(), "memory")
                .await
                .unwrap()
                .unwrap(),
            remote(4, false)
        );
        repo.accept_pull_page(&scope(), &target(), 4, page(5, remote(5, false)))
            .await
            .unwrap();
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "remote 5"
        );
    });
}
