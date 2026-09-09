use super::*;

fn copy_version(record: &KnowledgeCloudResolutionRecord, id: &str) -> Value {
    json!({"memory_id":id,"revision":1,"deleted":false,"author_id":"remote-actor","created_at_ms":999,"content":record.archive.original_request["content"].clone()})
}
fn keep_both_response(record: &KnowledgeCloudResolutionRecord, copy: Value) -> Value {
    json!({"replayed":false,"receipt":{
        "status":"resolved","change_id":record.resolution_id,
        "conflict_id":record.command.conflict_id,
        "version":record.archive.remote.clone().unwrap_or(Value::Null),
        "sequence":3,
        "copy_memory_id":copy["memory_id"].clone(),
        "copy_version":copy}})
}
fn copy_event(record: &KnowledgeCloudResolutionRecord, copy: Value) -> Value {
    let mut event = page(3, copy);
    event["changes"][0]["change_id"] = json!(record.resolution_id);
    event
}

#[test]
fn keep_both_settles_outbox_records_copy_and_converges_object_to_cloud_version() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (seq, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "both",
                command(seq, &verified, KnowledgeCloudChoice::KeepBoth {}),
                verified,
            )
            .unwrap();
        let request: Value = serde_json::from_str(&record.request_json).unwrap();
        assert_eq!(request["decision"], "keep_both");
        assert_eq!(request["expected_current_revision"], 2);
        let copy = copy_version(&record, "memory-copy-1");
        let outcome = repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                keep_both_response(&record, copy.clone()),
            )
            .unwrap();
        assert!(!outcome.pending_reconciliation);
        assert_eq!(outcome.receipt["copy_memory_id"], "memory-copy-1");
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "remote 2"
        );
        assert_eq!(
            repo.remote_baseline(&scope(), "memory")
                .await
                .unwrap()
                .unwrap(),
            remote(2, false)
        );
        assert!(repo.push_conflicts(&scope(), 10).await.unwrap().is_empty());
        assert!(repo.pull_conflicts(&scope(), 10).await.unwrap().is_empty());
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        let replay = repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                keep_both_response(&record, copy.clone()),
            )
            .unwrap();
        assert!(replay.replayed);
        assert!(repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                keep_both_response(&record, copy_version(&record, "memory-copy-2")),
            )
            .is_err());
        let result = repo
            .accept_pull_page(&scope(), &target(), 2, copy_event(&record, copy))
            .await
            .unwrap();
        assert_eq!((result.applied, result.conflicts), (1, 0));
        let saved = repo
            .get(&scope(), "memory-copy-1")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(saved.content, "local proposal");
        assert_eq!(saved.version, 1);
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 3);
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
    });
}

#[test]
fn keep_both_journal_echo_recovers_lost_receipt_before_cursor_commit() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (seq, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "both",
                command(seq, &verified, KnowledgeCloudChoice::KeepBoth {}),
                verified,
            )
            .unwrap();
        let copy = copy_version(&record, "memory-copy-1");
        let result = repo
            .accept_pull_page(&scope(), &target(), 2, copy_event(&record, copy.clone()))
            .await
            .unwrap();
        assert_eq!((result.applied, result.conflicts), (1, 0));
        let recovered = repo
            .cloud_resolution_record_durable(&scope(), &target(), "actor", &record.resolution_id)
            .unwrap();
        assert!(recovered.receipt.is_some());
        assert!(recovered.reconciliation.is_some());
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "remote 2"
        );
        assert_eq!(
            repo.get(&scope(), "memory-copy-1")
                .await
                .unwrap()
                .unwrap()
                .content,
            "local proposal"
        );
        assert!(
            repo.accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                keep_both_response(&record, copy)
            )
            .unwrap()
            .replayed
        );
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 3);
        assert!(repo.push_conflicts(&scope(), 10).await.unwrap().is_empty());
    });
}

#[test]
fn forged_keep_both_receipts_leave_the_object_paused_until_a_valid_receipt_settles() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (seq, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "both",
                command(seq, &verified, KnowledgeCloudChoice::KeepBoth {}),
                verified,
            )
            .unwrap();
        let copy = copy_version(&record, "memory-copy-1");
        let good = keep_both_response(&record, copy.clone());
        let mut variants = vec![];
        let mut tampered = copy.clone();
        tampered["content"]["content"] = json!("tampered");
        variants.push(keep_both_response(&record, tampered));
        let mut bumped = good.clone();
        bumped["receipt"]["version"] = remote(3, false);
        variants.push(bumped);
        variants.push(keep_both_response(&record, copy_version(&record, "memory")));
        let mut missing = good.clone();
        missing["receipt"].as_object_mut().unwrap().remove("sequence");
        variants.push(missing);
        let mut zero = good.clone();
        zero["receipt"]["sequence"] = json!(0);
        variants.push(zero);
        let mut revision = copy.clone();
        revision["revision"] = json!(2);
        variants.push(keep_both_response(&record, revision));
        let mut author = copy.clone();
        author["author_id"] = json!("mallory");
        variants.push(keep_both_response(&record, author));
        let mut deleted = copy.clone();
        deleted["deleted"] = json!(true);
        variants.push(keep_both_response(&record, deleted));
        let mut status = good.clone();
        status["receipt"]["status"] = json!("applied");
        variants.push(status);
        let mut conflict = good.clone();
        conflict["receipt"]["conflict_id"] = json!(uuid::Uuid::new_v4().to_string());
        variants.push(conflict);
        for bad in variants {
            assert!(repo
                .accept_cloud_resolution_receipt_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    bad
                )
                .is_err());
        }
        let pending = repo
            .cloud_resolution_record_durable(&scope(), &target(), "actor", &record.resolution_id)
            .unwrap();
        assert!(pending.receipt.is_none());
        assert_eq!(repo.push_conflicts(&scope(), 10).await.unwrap().len(), 1);
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "local proposal"
        );
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        repo.accept_cloud_resolution_receipt_durable(
            &scope(),
            &target(),
            "actor",
            &record.resolution_id,
            good,
        )
        .unwrap();
        assert!(repo.push_conflicts(&scope(), 10).await.unwrap().is_empty());
    });
}

#[test]
fn keep_both_delete_proposal_is_refused_before_any_send() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        repo.accept_pull_page(&scope(), &target(), 0, page(1, remote(1, false)))
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
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        repo.accept_pull_page(&scope(), &target(), 1, page(2, remote(2, false)))
            .await
            .unwrap();
        let mut proposed: Value = serde_json::from_str(&push.request_json).unwrap();
        proposed.as_object_mut().unwrap().remove("change_id");
        let id = uuid::Uuid::new_v4().to_string();
        let verified = json!({"id":id,"memory_id":"memory","proposed":proposed,"current":remote(2,false),"observed_current":remote(2,false),"resolved_change_id":null});
        repo.accept_push_receipt(&scope(),&target(),push.local_sequence,json!({"replayed":false,"receipt":{"status":"conflict","change_id":push.change_id,"conflict_id":id}}),Some(verified.clone())).await.unwrap();
        assert!(
            repo.prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "both",
                command(
                    push.local_sequence,
                    &verified,
                    KnowledgeCloudChoice::KeepBoth {},
                ),
                verified,
            )
            .is_err()
        );
        assert_eq!(repo.push_conflicts(&scope(), 10).await.unwrap().len(), 1);
    });
}

#[test]
fn keep_both_prepare_fences_the_object_until_the_receipt_settles() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (seq, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "both",
                command(seq, &verified, KnowledgeCloudChoice::KeepBoth {}),
                verified,
            )
            .unwrap();
        edit(&repo, "during review", "new local work").await;
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        let outcome = repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                keep_both_response(&record, copy_version(&record, "memory-copy-1")),
            )
            .unwrap();
        assert!(outcome.pending_reconciliation);
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "new local work"
        );
        let ctx = repo
            .cloud_reconciliation_context_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
            )
            .unwrap();
        let done = repo
            .reconcile_cloud_resolution_durable(
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
        assert!(!done.pending_reconciliation);
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "remote 2"
        );
        assert!(repo.push_conflicts(&scope(), 10).await.unwrap().is_empty());
        assert!(repo.pull_conflicts(&scope(), 10).await.unwrap().is_empty());
    });
}
