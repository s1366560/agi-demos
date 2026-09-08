use super::*;

async fn prepare(
    repo: &SqliteKnowledgeRepository,
    id: &str,
    actor: &str,
) -> KnowledgeCloudResolutionRecord {
    let memory = agistack_core::knowledge::KnowledgeMemory {
        id: id.into(),
        project_id: scope().project_id,
        title: "Local".into(),
        content: "local proposal".into(),
        author_id: actor.into(),
        content_type: "text".into(),
        tags: vec![],
        entities: vec![],
        version: 1,
        status: "ENABLED".into(),
        created_at_ms: 1,
        metadata: Default::default(),
        embedding: None,
    };
    repo.mutate(&scope(), actor, id, MemoryMutation::Create { memory })
        .await
        .unwrap();
    let push = repo
        .prepare_push(&scope(), &target())
        .await
        .unwrap()
        .unwrap();
    let mut proposed: Value = serde_json::from_str(&push.request_json).unwrap();
    proposed.as_object_mut().unwrap().remove("change_id");
    assert_eq!(proposed["memory_id"], id);
    let mut current = remote(1, false);
    current["memory_id"] = json!(id);
    let conflict_id = uuid::Uuid::new_v4().to_string();
    let verified = json!({
        "id": conflict_id, "memory_id": id, "proposed": proposed,
        "current": current, "observed_current": current, "resolved_change_id": null,
    });
    repo.accept_push_receipt(
        &scope(),
        &target(),
        push.local_sequence,
        json!({"replayed": false, "receipt": {
            "status": "conflict", "change_id": push.change_id, "conflict_id": conflict_id,
        }}),
        Some(verified.clone()),
    )
    .await
    .unwrap();
    repo.prepare_cloud_resolution_durable(
        &scope(),
        &target(),
        actor,
        id,
        KnowledgeCloudResolutionCommand {
            local_sequence: push.local_sequence,
            memory_id: id.into(),
            conflict_id,
            guard: KnowledgeCloudResolutionGuard {
                expected_local_revision: 1,
                expected_remote_revision: 1,
                expected_baseline_revision: 0,
                conflict_sequences: vec![],
            },
            choice: KnowledgeCloudChoice::KeepCurrent {},
        },
        verified,
    )
    .unwrap()
}

fn settle(repo: &SqliteKnowledgeRepository, actor: &str, record: &KnowledgeCloudResolutionRecord) {
    let result = repo
        .accept_cloud_resolution_receipt_durable(
            &scope(),
            &target(),
            actor,
            &record.resolution_id,
            response(record, record.archive.remote.clone().unwrap()),
        )
        .unwrap();
    assert!(!result.pending_reconciliation);
}

#[test]
fn pending_discovery_reaches_old_records_beyond_two_hundred_completed_decisions() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        let oldest = prepare(&repo, "oldest", "actor").await;
        for n in 0..201 {
            let record = prepare(&repo, &format!("completed-{n}"), "actor").await;
            settle(&repo, "actor", &record);
        }
        let rejected = prepare(&repo, "rejected", "actor").await;
        repo.reject_cloud_resolution_stale_durable(
            &scope(),
            &target(),
            "actor",
            &rejected.resolution_id,
            json!({"detail": {"code": "knowledge_sync_resolution_stale"}}),
        )
        .unwrap();
        let pending = prepare(&repo, "receipt-pending", "actor").await;
        let mut memory = repo
            .get(&scope(), "receipt-pending")
            .await
            .unwrap()
            .unwrap();
        memory.content = "edited during cloud response".into();
        repo.mutate(
            &scope(),
            "actor",
            "later-edit",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        let result = repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &pending.resolution_id,
                response(&pending, pending.archive.remote.clone().unwrap()),
            )
            .unwrap();
        assert!(result.pending_reconciliation);
        let recent = repo
            .cloud_resolution_records(&scope(), &target(), "actor", 200)
            .await
            .unwrap();
        assert!(!recent
            .iter()
            .any(|r| r.resolution_id == oldest.resolution_id));
        let page = repo
            .pending_cloud_resolutions(&scope(), &target(), "actor", None, 200)
            .await
            .unwrap();
        assert_eq!(
            page.items
                .iter()
                .map(|r| &r.resolution_id)
                .collect::<Vec<_>>(),
            vec![&pending.resolution_id, &oldest.resolution_id]
        );
        assert!(page.items[0].receipt.is_some());
        assert!(page.items[1].receipt.is_none());
        assert!(page.next_before_resolution_id.is_none());
    });
}

#[test]
fn keyset_recovery_does_not_skip_when_new_records_arrive_or_cursor_settles() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        let old = prepare(&repo, "old", "actor").await;
        let middle = prepare(&repo, "middle", "actor").await;
        let first = prepare(&repo, "first", "actor").await;
        let page = repo
            .pending_cloud_resolutions(&scope(), &target(), "actor", None, 1)
            .await
            .unwrap();
        assert_eq!(page.items[0].resolution_id, first.resolution_id);
        assert_eq!(
            page.next_before_resolution_id.as_deref(),
            Some(first.resolution_id.as_str())
        );
        settle(&repo, "actor", &first);
        let newest = prepare(&repo, "newest", "actor").await;
        let rest = repo
            .pending_cloud_resolutions(
                &scope(),
                &target(),
                "actor",
                page.next_before_resolution_id.as_deref(),
                200,
            )
            .await
            .unwrap();
        assert_eq!(
            rest.items
                .iter()
                .map(|r| &r.resolution_id)
                .collect::<Vec<_>>(),
            vec![&middle.resolution_id, &old.resolution_id]
        );
        assert!(rest.next_before_resolution_id.is_none());
        assert_eq!(
            repo.pending_cloud_resolutions(&scope(), &target(), "actor", None, 1)
                .await
                .unwrap()
                .items[0]
                .resolution_id,
            newest.resolution_id
        );
        let after_last = repo
            .pending_cloud_resolutions(&scope(), &target(), "actor", Some(&old.resolution_id), 1)
            .await
            .unwrap();
        assert!(after_last.items.is_empty());
        assert!(after_last.next_before_resolution_id.is_none());
    });
}

#[test]
fn pending_cursor_and_by_key_reads_are_actor_bound_validated_and_immutable() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        let own = prepare(&repo, "own", "actor").await;
        let other = prepare(&repo, "other", "other-actor").await;
        let before = serde_json::to_value(repo.sync_status(&scope()).await.unwrap()).unwrap();
        assert!(repo
            .cloud_resolution_by_key(&scope(), &target(), "other-actor", "own")
            .await
            .unwrap()
            .is_none());
        assert!(repo
            .pending_cloud_resolutions(&scope(), &target(), "actor", Some(&other.resolution_id), 1)
            .await
            .is_err());
        for (actor, cursor, limit) in [
            ("", None, 1),
            ("actor", Some("bad"), 1),
            ("actor", Some("00000000-0000-0000-0000-000000000000"), 1),
            ("actor", None, 0),
            ("actor", None, 201),
        ] {
            assert!(repo
                .pending_cloud_resolutions(&scope(), &target(), actor, cursor, limit)
                .await
                .is_err());
        }
        let mut wrong_target = target();
        wrong_target.authority = "https://other.test/api/v1".into();
        assert!(repo
            .pending_cloud_resolutions(&scope(), &wrong_target, "actor", None, 1)
            .await
            .is_err());
        assert_eq!(
            repo.pending_cloud_resolutions(&scope(), &target(), "actor", None, 200)
                .await
                .unwrap()
                .items[0]
                .resolution_id,
            own.resolution_id
        );
        assert_eq!(
            serde_json::to_value(
                repo.cloud_resolution_by_key(&scope(), &target(), "actor", "own")
                    .await
                    .unwrap()
                    .unwrap()
            )
            .unwrap(),
            serde_json::to_value(own).unwrap()
        );
        assert_eq!(
            serde_json::to_value(repo.sync_status(&scope()).await.unwrap()).unwrap(),
            before
        );
    });
}

#[test]
fn more_than_two_hundred_pending_records_remain_pageable_after_reopen() {
    struct Database(std::path::PathBuf);
    impl Drop for Database {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.0);
        }
    }
    block_on(async {
        let database = Database(
            std::env::temp_dir().join(format!("knowledge-recovery-{}.db", uuid::Uuid::new_v4())),
        );
        let repo = SqliteKnowledgeRepository::open(database.0.to_str().unwrap()).unwrap();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        let mut ids = Vec::new();
        for n in 0..205 {
            ids.push(
                prepare(&repo, &format!("pending-{n}"), "actor")
                    .await
                    .resolution_id,
            );
        }
        drop(repo);
        let repo = SqliteKnowledgeRepository::open(database.0.to_str().unwrap()).unwrap();
        let first = repo
            .pending_cloud_resolutions(&scope(), &target(), "actor", None, 200)
            .await
            .unwrap();
        assert_eq!(first.items.len(), 200);
        assert_eq!(
            first.next_before_resolution_id.as_deref(),
            Some(ids[5].as_str())
        );
        let second = repo
            .pending_cloud_resolutions(
                &scope(),
                &target(),
                "actor",
                first.next_before_resolution_id.as_deref(),
                200,
            )
            .await
            .unwrap();
        assert_eq!(second.items.len(), 5);
        assert!(second.next_before_resolution_id.is_none());
        let observed: Vec<_> = first
            .items
            .into_iter()
            .chain(second.items)
            .map(|record| record.resolution_id)
            .collect();
        ids.reverse();
        assert_eq!(observed, ids);
    });
}
