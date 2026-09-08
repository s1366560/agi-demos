use super::*;

#[test]
fn selection_is_required_and_switching_blocks_old_active_vectors_until_new_build_is_ready() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let a = build("t", "p", "a");
        create(&repo, &a.scope, "one").await;
        finish(&repo, &a.scope).await;
        repo.begin_index_build_durable(&a, &|| Ok(110)).unwrap();
        let unselected = DesiredEmbeddingConfig {
            revision: 1,
            build: a.clone(),
        };
        assert!(repo
            .claim_index_durable(&unselected, "worker", 100, &|| Ok(110))
            .is_err());
        let selected_a = repo
            .select_index_config_durable(&a, None, &|| Ok(110))
            .unwrap();
        let lease = repo
            .claim_index_durable(&selected_a, "worker", 100, &|| Ok(110))
            .unwrap()
            .unwrap();
        repo.complete_index_durable(&lease, &[1.0, 0.0], &|| Ok(111))
            .unwrap();
        repo.promote_index_build_durable(&selected_a, None, &|| Ok(112))
            .unwrap();
        assert_eq!(
            repo.read_active_index_durable(&selected_a, &|| Ok(113))
                .unwrap()
                .vectors
                .len(),
            1
        );
        let mut b = a.clone();
        b.build_id = "b".into();
        b.profile.model_id = "another-allowed-model".into();
        repo.begin_index_build_durable(&b, &|| Ok(114)).unwrap();
        let selected_b = repo
            .select_index_config_durable(&b, Some(1), &|| Ok(114))
            .unwrap();
        assert_eq!(selected_b.revision, 2);
        assert_eq!(
            repo.active_index_build_durable(&a.scope, &|| Ok(115))
                .unwrap(),
            Some(a)
        );
        assert!(repo
            .read_active_index_durable(&selected_a, &|| Ok(115))
            .is_err());
        assert!(repo
            .read_active_index_durable(&selected_b, &|| Ok(115))
            .is_err());
        assert!(repo
            .promote_index_build_durable(&selected_a, Some("a"), &|| Ok(115))
            .is_err());
        assert!(repo
            .promote_index_build_durable(&selected_b, Some("a"), &|| Ok(115))
            .is_err());
    });
}

#[test]
fn selecting_a_b_a_rejects_old_lease_and_query_even_with_forged_current_revision() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let a = build("t", "p", "a");
        create(&repo, &a.scope, "one").await;
        finish(&repo, &a.scope).await;
        repo.begin_index_build_durable(&a, &|| Ok(110)).unwrap();
        let first = repo
            .select_index_config_durable(&a, None, &|| Ok(110))
            .unwrap();
        let lease = repo
            .claim_index_durable(&first, "worker", 100, &|| Ok(110))
            .unwrap()
            .unwrap();
        let b = build("t", "p", "b");
        repo.begin_index_build_durable(&b, &|| Ok(111)).unwrap();
        repo.select_index_config_durable(&b, Some(1), &|| Ok(111))
            .unwrap();
        let third = repo
            .select_index_config_durable(&a, Some(2), &|| Ok(112))
            .unwrap();
        assert_eq!(third.revision, 3);
        for candidate in [
            lease.clone(),
            IndexLease {
                config_revision: 3,
                ..lease.clone()
            },
        ] {
            assert!(repo
                .renew_index_durable(&candidate, 100, &|| Ok(113))
                .is_err());
            assert!(repo
                .complete_index_durable(&candidate, &[1.0, 0.0], &|| Ok(113))
                .is_err());
            assert!(repo
                .fail_index_durable(&candidate, IndexFailure::Cancelled, &|| Ok(113))
                .is_err());
        }
        assert!(repo.read_active_index_durable(&first, &|| Ok(113)).is_err());
        drop(repo);
        let repo = db.open();
        assert_eq!(
            repo.desired_index_config_durable(&a.scope, &|| Ok(210))
                .unwrap(),
            Some(third.clone())
        );
        let reclaimed = repo
            .claim_index_durable(&third, "new-worker", 100, &|| Ok(210))
            .unwrap()
            .unwrap();
        assert_eq!(reclaimed.attempt, 2);
        assert_eq!(reclaimed.config_revision, 3);
        repo.complete_index_durable(&reclaimed, &[1.0, 0.0], &|| Ok(211))
            .unwrap();
        repo.promote_index_build_durable(&third, None, &|| Ok(211))
            .unwrap();
        assert!(repo.read_active_index_durable(&first, &|| Ok(212)).is_err());
        assert_eq!(
            repo.read_active_index_durable(&third, &|| Ok(212))
                .unwrap()
                .config_revision,
            3
        );
    });
}

#[test]
fn competing_cas_selections_have_exactly_one_winner_and_do_not_cross_scopes() {
    let db = Database::new();
    let repo = db.open();
    let a = build("t", "p", "a");
    let b = build("t", "p", "b");
    let other = build("other-tenant", "p", "a");
    for build in [&a, &b, &other] {
        repo.begin_index_build_durable(build, &|| Ok(1)).unwrap();
    }
    repo.select_index_config_durable(&a, None, &|| Ok(1))
        .unwrap();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let handles = [a.clone(), b]
        .into_iter()
        .map(|build| {
            let repo = db.open();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                repo.select_index_config_durable(&build, Some(1), &|| Ok(2))
            })
        })
        .collect::<Vec<_>>();
    assert_eq!(
        handles
            .into_iter()
            .map(|h| h.join().unwrap())
            .filter(Result::is_ok)
            .count(),
        1
    );
    assert!(repo
        .desired_index_config_durable(&other.scope, &|| Ok(3))
        .unwrap()
        .is_none());
    assert_eq!(
        repo.select_index_config_durable(&other, None, &|| Ok(3))
            .unwrap()
            .revision,
        1
    );
    assert!(repo
        .select_index_config_durable(&a, Some(1), &|| Ok(3))
        .is_err());
}

#[test]
fn v10_upgrade_requires_explicit_selection_and_corrupt_v11_schema_fails_closed() {
    let db = Database::new();
    let repo = db.open();
    let a = build("t", "p", "a");
    repo.begin_index_build_durable(&a, &|| Ok(1)).unwrap();
    drop(repo);
    db.sql().execute_batch("DROP TABLE knowledge_index_configuration; ALTER TABLE knowledge_index_jobs DROP COLUMN config_revision; DROP TABLE IF EXISTS knowledge_community_results; DROP TABLE IF EXISTS knowledge_community_audits; DROP TABLE IF EXISTS knowledge_community_selection; UPDATE knowledge_schema SET version=10;").unwrap();
    let repo = db.open();
    assert!(repo
        .desired_index_config_durable(&a.scope, &|| Ok(2))
        .unwrap()
        .is_none());
    assert_eq!(
        repo.select_index_config_durable(&a, None, &|| Ok(2))
            .unwrap()
            .revision,
        1
    );
    drop(repo);
    db.sql()
        .execute_batch("DROP TABLE knowledge_index_configuration;")
        .unwrap();
    assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
}

#[test]
fn migrated_v10_lease_cannot_complete_under_first_selection_and_reclaims_after_expiry() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let a = build("t", "p", "a");
        create(&repo, &a.scope, "one").await;
        finish(&repo, &a.scope).await;
        repo.begin_index_build_durable(&a, &|| Ok(110)).unwrap();
        let selected = repo
            .select_index_config_durable(&a, None, &|| Ok(110))
            .unwrap();
        let lease = repo
            .claim_index_durable(&selected, "worker", 100, &|| Ok(110))
            .unwrap()
            .unwrap();
        drop(repo);
        db.sql()
            .execute_batch(
                "DROP TABLE knowledge_index_configuration;
            ALTER TABLE knowledge_index_jobs DROP COLUMN config_revision;
            DROP TABLE IF EXISTS knowledge_community_results; DROP TABLE IF EXISTS knowledge_community_audits; DROP TABLE IF EXISTS knowledge_community_selection; UPDATE knowledge_schema SET version=10;",
            )
            .unwrap();
        let repo = db.open();
        let selected = repo
            .select_index_config_durable(&a, None, &|| Ok(111))
            .unwrap();
        assert!(repo
            .complete_index_durable(&lease, &[1.0, 0.0], &|| Ok(112))
            .is_err());
        assert!(repo
            .claim_index_durable(&selected, "new-worker", 100, &|| Ok(112))
            .unwrap()
            .is_none());
        let reclaimed = repo
            .claim_index_durable(&selected, "new-worker", 100, &|| Ok(210))
            .unwrap()
            .unwrap();
        assert_eq!(reclaimed.attempt, 2);
        repo.complete_index_durable(&reclaimed, &[1.0, 0.0], &|| Ok(211))
            .unwrap();
    });
}
