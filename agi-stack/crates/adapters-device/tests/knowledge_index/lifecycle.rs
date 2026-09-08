use super::*;

#[test]
fn durable_build_reopens_resumes_and_promotes_only_full_current_coverage() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let b = build("t", "p", "build");
        create(&repo, &b.scope, "one").await;
        finish(&repo, &b.scope).await;
        create(&repo, &b.scope, "two").await;
        finish(&repo, &b.scope).await;
        repo.begin_index_build_durable(&b, &|| Ok(110)).unwrap();
        select_initial(&repo, &b);
        let first = claim(&repo, &b, 110);
        assert_eq!(first.input.audit_attempt, 1);
        assert_eq!(first.input.input_digest.len(), 64);
        let input: serde_json::Value = serde_json::from_str(&first.input_text).unwrap();
        assert_eq!(input[0], 1);
        assert_eq!(input[1], "Title\"\\中");
        repo.complete_index_durable(&first, &[1.0, 2.0], &|| Ok(111))
            .unwrap();
        assert!(repo
            .promote_index_build_durable(&config(&repo, &b), None, &|| Ok(112))
            .is_err());
        let second = claim(&repo, &b, 120);
        drop(repo);
        let repo = db.open();
        repo.begin_index_build_durable(&b, &|| Ok(130)).unwrap();
        select_initial(&repo, &b);
        assert!(repo
            .claim_index_durable(&config(&repo, &b), "other", 100, &|| Ok(219))
            .unwrap()
            .is_none());
        let reclaimed = claim(&repo, &b, 220);
        assert_eq!(reclaimed.attempt, 2);
        assert_ne!(reclaimed.token, second.token);
        assert!(repo
            .complete_index_durable(&second, &[1.0, 0.0], &|| Ok(221))
            .is_err());
        repo.complete_index_durable(&reclaimed, &[0.0, 1.0], &|| Ok(221))
            .unwrap();
        repo.promote_index_build_durable(&config(&repo, &b), None, &|| Ok(222))
            .unwrap();
        assert_eq!(
            repo.active_index_build_durable(&b.scope, &|| Ok(223))
                .unwrap(),
            Some(b.clone())
        );
        let read = repo
            .read_active_index_durable(&config(&repo, &b), &|| Ok(223))
            .unwrap();
        assert!(read.coverage.complete());
        assert_eq!(read.vectors.len(), 2);
        let selected = config(&repo, &b);
        drop(repo);
        assert_eq!(
            db.open()
                .read_active_index_durable(&selected, &|| Ok(224))
                .unwrap(),
            read
        );
    });
}

#[test]
fn failed_jobs_need_exact_retry_and_nonfinite_zero_or_wrong_dimension_vectors_cannot_publish() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let b = build("t", "p", "b");
        create(&repo, &b.scope, "one").await;
        finish(&repo, &b.scope).await;
        repo.begin_index_build_durable(&b, &|| Ok(110)).unwrap();
        select_initial(&repo, &b);
        let lease = claim(&repo, &b, 110);
        for vector in [
            vec![],
            vec![1.0],
            vec![0.0, 0.0],
            vec![f32::NAN, 1.0],
            vec![f32::INFINITY, 1.0],
        ] {
            assert!(repo
                .complete_index_durable(&lease, &vector, &|| Ok(111))
                .is_err());
        }
        repo.fail_index_durable(&lease, IndexFailure::InvalidEmbedding, &|| Ok(111))
            .unwrap();
        assert!(repo
            .claim_index_durable(&config(&repo, &b), "other", 100, &|| Ok(112))
            .unwrap()
            .is_none());
        assert_eq!(
            repo.reconcile_index_durable(&config(&repo, &b), &|| Ok(112))
                .unwrap()
                .failed_sources,
            1
        );
        assert!(repo
            .promote_index_build_durable(&config(&repo, &b), None, &|| Ok(112))
            .is_err());
        assert!(repo
            .retry_index_durable(&config(&repo, &b), &lease.input, 2, &|| Ok(112))
            .is_err());
        repo.retry_index_durable(&config(&repo, &b), &lease.input, 1, &|| Ok(112))
            .unwrap();
        let retry = claim(&repo, &b, 113);
        assert_eq!(retry.attempt, 2);
        repo.complete_index_durable(&retry, &[f32::MAX, f32::MIN_POSITIVE], &|| Ok(114))
            .unwrap();
        repo.promote_index_build_durable(&config(&repo, &b), None, &|| Ok(115))
            .unwrap();
    });
}

#[test]
fn immutable_profiles_and_cas_promotion_prevent_mixed_models_and_allow_explicit_rollback() {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let b = build("t", "p", "b");
    repo.begin_index_build_durable(&b, &|| Ok(1)).unwrap();
    select_initial(&repo, &b);
    for field in 0..7 {
        let mut changed = b.clone();
        match field {
            0 => changed.profile.provider_id.push('2'),
            1 => changed.profile.provider_revision += 1,
            2 => changed.profile.credential_binding_digest = "cd".repeat(32),
            3 => changed.profile.model_id.push('2'),
            4 => changed.profile.dimensions = NonZeroU32::new(3).unwrap(),
            5 => changed.profile.input_contract_version = 2,
            _ => changed.profile.normalization_version = 2,
        }
        assert!(repo.begin_index_build_durable(&changed, &|| Ok(2)).is_err());
    }
    repo.promote_index_build_durable(&config(&repo, &b), None, &|| Ok(2))
        .unwrap();
    let mut newer = b.clone();
    newer.build_id = "newer".into();
    newer.profile.dimensions = NonZeroU32::new(3).unwrap();
    repo.begin_index_build_durable(&newer, &|| Ok(3)).unwrap();
    repo.select_index_config_durable(&newer, Some(1), &|| Ok(3))
        .unwrap();
    assert!(repo
        .promote_index_build_durable(&config(&repo, &newer), None, &|| Ok(4))
        .is_err());
    repo.promote_index_build_durable(&config(&repo, &newer), Some("b"), &|| Ok(4))
        .unwrap();
    assert!(repo
        .read_active_index_durable(&config(&repo, &b), &|| Ok(5))
        .is_err());
    repo.select_index_config_durable(&b, Some(2), &|| Ok(5))
        .unwrap();
    repo.promote_index_build_durable(&config(&repo, &b), Some("newer"), &|| Ok(5))
        .unwrap();
    assert!(repo
        .read_active_index_durable(&config(&repo, &b), &|| Ok(6))
        .unwrap()
        .coverage
        .complete());
}
