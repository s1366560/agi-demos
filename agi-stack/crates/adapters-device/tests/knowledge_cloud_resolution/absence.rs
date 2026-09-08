use super::*;

#[test]
fn keep_current_null_retains_local_archive_without_inventing_a_remote_version_or_sequence() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        let memory = agistack_core::knowledge::KnowledgeMemory {
            id: "memory".into(),
            project_id: scope().project_id,
            title: "Local".into(),
            content: "local only".into(),
            author_id: "actor".into(),
            content_type: "text".into(),
            tags: vec![],
            entities: vec![],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1,
            metadata: Default::default(),
            embedding: None,
        };
        repo.mutate(
            &scope(),
            "actor",
            "create",
            MemoryMutation::Create { memory },
        )
        .await
        .unwrap();
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let mut proposed: Value = serde_json::from_str(&push.request_json).unwrap();
        proposed.as_object_mut().unwrap().remove("change_id");
        let id = uuid::Uuid::new_v4().to_string();
        let verified = json!({"id":id,"memory_id":"memory","proposed":proposed,"current":null,"observed_current":null,"resolved_change_id":null});
        repo.accept_push_receipt(&scope(),&target(),push.local_sequence,json!({"replayed":false,"receipt":{"status":"conflict","change_id":push.change_id,"conflict_id":id}}),Some(verified.clone())).await.unwrap();
        let mut cmd = command(
            push.local_sequence,
            &verified,
            KnowledgeCloudChoice::KeepCurrent {},
        );
        cmd.guard = KnowledgeCloudResolutionGuard {
            expected_local_revision: 1,
            expected_remote_revision: 0,
            expected_baseline_revision: 0,
            conflict_sequences: vec![],
        };
        let record = repo
            .prepare_cloud_resolution_durable(&scope(), &target(), "actor", "absent", cmd, verified)
            .unwrap();
        let ack = repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                response(&record, Value::Null),
            )
            .unwrap();
        assert!(!ack.pending_reconciliation);
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        assert!(repo
            .remote_baseline(&scope(), "memory")
            .await
            .unwrap()
            .is_none());
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 0);
        assert_eq!(record.archive.local.content, "local only");
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
    });
}

#[test]
fn proposed_local_delete_uses_latest_remote_content_and_keeps_a_real_tombstone_receipt() {
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
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "confirm delete",
                command(
                    push.local_sequence,
                    &verified,
                    KnowledgeCloudChoice::UseProposed {},
                ),
                verified,
            )
            .unwrap();
        let mut value = remote(2, false);
        value["revision"] = json!(3);
        value["deleted"] = json!(true);
        repo.accept_cloud_resolution_receipt_durable(
            &scope(),
            &target(),
            "actor",
            &record.resolution_id,
            response(&record, value.clone()),
        )
        .unwrap();
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        assert_eq!(
            repo.remote_baseline(&scope(), "memory")
                .await
                .unwrap()
                .unwrap(),
            value
        );
        assert!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().is_empty());
    });
}

#[test]
fn subsequent_local_pull_resolution_ignores_archived_cloud_conflict() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (seq, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "first",
                command(seq, &verified, KnowledgeCloudChoice::KeepCurrent {}),
                verified,
            )
            .unwrap();
        repo.accept_cloud_resolution_receipt_durable(
            &scope(),
            &target(),
            "actor",
            &record.resolution_id,
            response(&record, remote(2, false)),
        )
        .unwrap();
        edit(&repo, "later", "later independent edit").await;
        repo.accept_pull_page(&scope(), &target(), 2, page(3, remote(3, false)))
            .await
            .unwrap();
        let ctx = repo
            .pull_conflict_context(&scope(), "memory")
            .await
            .unwrap()
            .unwrap();
        repo.resolve_pull_conflicts(
            &scope(),
            &target(),
            "actor",
            "next local choice",
            KnowledgePullConflictResolution {
                memory_id: "memory".into(),
                expected_local_revision: ctx.local.version,
                expected_remote_revision: 3,
                expected_baseline_revision: 2,
                conflict_sequences: vec![3],
                choice: KnowledgeConflictChoice::UseLocal {},
            },
        )
        .await
        .unwrap();
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_some());
    });
}
