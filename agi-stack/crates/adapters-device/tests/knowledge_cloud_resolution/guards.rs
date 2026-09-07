use super::*;

#[test]
fn wire_choices_reject_extra_fields_and_never_infer_a_decision() {
    for value in [
        json!({"decision":"keep_current","content":merged()}),
        json!({"decision":"use_proposed","policy":"overwrite"}),
        json!({"decision":"automatic"}),
    ] {
        assert!(serde_json::from_value::<KnowledgeCloudChoice>(value).is_err());
    }
}

#[test]
fn all_prepare_guards_and_verified_document_identity_are_required() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (seq, verified) = setup(&repo, false).await;
        let original = command(seq, &verified, KnowledgeCloudChoice::KeepCurrent {});
        let mut variants = vec![];
        let mut v = original.clone();
        v.guard.expected_local_revision += 1;
        variants.push(v);
        let mut v = original.clone();
        v.guard.expected_remote_revision += 1;
        variants.push(v);
        let mut v = original.clone();
        v.guard.expected_baseline_revision += 1;
        variants.push(v);
        let mut v = original.clone();
        v.guard.conflict_sequences.clear();
        variants.push(v);
        let mut v = original.clone();
        v.conflict_id = uuid::Uuid::new_v4().to_string();
        variants.push(v);
        for v in variants {
            assert!(repo
                .prepare_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    "bad",
                    v,
                    verified.clone()
                )
                .is_err());
        }
        for field in ["id", "memory_id", "current", "proposed", "observed_current"] {
            let mut bad = verified.clone();
            bad[field] = Value::Null;
            assert!(repo
                .prepare_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    "bad",
                    original.clone(),
                    bad
                )
                .is_err());
        }
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "valid",
                original.clone(),
                verified.clone(),
            )
            .unwrap();
        assert!(repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "other-key",
                original.clone(),
                verified
            )
            .is_err());
        let replay = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "valid",
                original.clone(),
                Value::Null,
            )
            .unwrap();
        assert_eq!(record.request_json, replay.request_json);
        let mut changed = original;
        changed.choice = KnowledgeCloudChoice::UseProposed {};
        assert!(repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "valid",
                changed,
                Value::Null
            )
            .is_err());
        assert!(repo
            .cloud_resolution_record_durable(
                &scope(),
                &target(),
                "other-actor",
                &record.resolution_id
            )
            .is_err());
        let mut wrong = target();
        wrong.authority = "https://other.test".into();
        assert!(repo
            .cloud_resolution_record_durable(&scope(), &wrong, "actor", &record.resolution_id)
            .is_err());
    });
}

#[test]
fn forged_receipts_leave_prepared_request_and_original_conflicts_recoverable() {
    block_on(async {
        for choice in [
            KnowledgeCloudChoice::KeepCurrent {},
            KnowledgeCloudChoice::UseProposed {},
        ] {
            let repo = SqliteKnowledgeRepository::in_memory().unwrap();
            let (seq, verified) = setup(&repo, false).await;
            let record = repo
                .prepare_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    "choose",
                    command(seq, &verified, choice),
                    verified,
                )
                .unwrap();
            let good = response(
                &record,
                if matches!(record.command.choice, KnowledgeCloudChoice::KeepCurrent {}) {
                    remote(2, false)
                } else {
                    applied_version(&record)
                },
            );
            let mut variants = vec![];
            for (field, bad) in [
                ("memory_id", json!("other")),
                ("revision", json!(6)),
                ("deleted", json!(true)),
                ("author_id", json!("forged")),
                ("created_at_ms", json!(9)),
                ("content", json!({})),
            ] {
                let mut v = good.clone();
                v["receipt"]["version"][field] = bad;
                variants.push(v);
            }
            let mut v = good.clone();
            v["receipt"]["change_id"] = json!(uuid::Uuid::new_v4().to_string());
            variants.push(v);
            let mut v = good.clone();
            v["receipt"]["status"] = json!("conflict");
            variants.push(v);
            let mut v = good.clone();
            v["receipt"]["sequence"] = json!(0);
            variants.push(v);
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
            assert!(repo
                .cloud_resolution_record_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id
                )
                .unwrap()
                .receipt
                .is_none());
            assert_eq!(repo.push_conflicts(&scope(), 10).await.unwrap().len(), 1);
            repo.accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                good,
            )
            .unwrap();
        }
    });
}

#[test]
fn only_verified_stale_rejection_allows_new_key_and_old_key_replays_terminal_evidence() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let (seq, mut verified) = setup(&repo, false).await;
        let cmd = command(seq, &verified, KnowledgeCloudChoice::UseProposed {});
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "stale",
                cmd.clone(),
                verified.clone(),
            )
            .unwrap();
        for code in [
            "timeout",
            "knowledge_sync_conflict_resolved",
            "knowledge_sync_forbidden",
        ] {
            assert!(repo
                .reject_cloud_resolution_stale_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    json!({"detail":{"code":code}})
                )
                .is_err());
        }
        let rejection =
            json!({"detail":{"code":"knowledge_sync_resolution_stale","message":"stale"}});
        repo.reject_cloud_resolution_stale_durable(
            &scope(),
            &target(),
            "actor",
            &record.resolution_id,
            rejection.clone(),
        )
        .unwrap();
        let replay = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "stale",
                cmd.clone(),
                Value::Null,
            )
            .unwrap();
        assert_eq!(replay.rejection, Some(rejection));
        assert_eq!(replay.request_json, record.request_json);
        assert!(repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                response(&record, applied_version(&record))
            )
            .is_err());
        verified["observed_current"] = remote(3, false);
        let mut fresh = cmd;
        fresh.guard.expected_remote_revision = 3;
        let next = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "fresh",
                fresh,
                verified,
            )
            .unwrap();
        assert_ne!(next.resolution_id, record.resolution_id);
    });
}
