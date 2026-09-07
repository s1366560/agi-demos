use super::*;

#[test]
fn leases_are_atomic_across_connections() {
    let db = Database::new();
    block_on(db.open().create(&scope(), memory())).unwrap();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let workers: Vec<_> = (0..2)
        .map(|index| {
            let repo = db.open();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                block_on(repo.claim(&scope(), &format!("worker-{index}"), 100, 50)).unwrap()
            })
        })
        .collect();
    let leases: Vec<_> = workers
        .into_iter()
        .filter_map(|worker| worker.join().unwrap())
        .collect();
    assert_eq!(leases.len(), 1);
    assert_eq!(leases[0].attempt, 1);
}

#[test]
fn exact_expiry_reclaims_and_invalidates_old_token_for_all_transitions() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.create(&scope(), memory()).await.unwrap();
        let first = repo
            .claim(&scope(), "worker", 100, 50)
            .await
            .unwrap()
            .unwrap();
        assert!(repo
            .claim(&scope(), "next", 149, 50)
            .await
            .unwrap()
            .is_none());
        assert!(matches!(
            repo.renew(&scope(), &first, 150, 50).await,
            Err(KnowledgeError::Conflict)
        ));
        let second = repo
            .claim(&scope(), "next", 150, 50)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(second.attempt, 2);
        assert_ne!(first.token, second.token);
        assert!(matches!(
            repo.renew(&scope(), &first, 151, 50).await,
            Err(KnowledgeError::Conflict)
        ));
        assert!(matches!(
            repo.complete(&scope(), &first, projection(), 151).await,
            Err(KnowledgeError::Conflict)
        ));
        assert!(matches!(
            repo.fail(&scope(), &first, ProcessingFailure::Cancelled, 151)
                .await,
            Err(KnowledgeError::Conflict)
        ));
        repo.complete(&scope(), &second, projection(), 151)
            .await
            .unwrap();
    });
}

#[test]
fn renew_uses_database_deadline_and_never_shortens_it() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.create(&scope(), memory()).await.unwrap();
        let first = repo
            .claim(&scope(), "worker", 100, 50)
            .await
            .unwrap()
            .unwrap();
        let renewed = repo.renew(&scope(), &first, 140, 50).await.unwrap();
        assert_eq!(renewed.expires_at_ms, 190);
        assert_eq!(renewed.token, first.token);
        assert_eq!(renewed.attempt, first.attempt);
        let unchanged = repo.renew(&scope(), &first, 151, 1).await.unwrap();
        assert_eq!(unchanged.expires_at_ms, 190);
        assert!(repo
            .claim(&scope(), "next", 189, 50)
            .await
            .unwrap()
            .is_none());
        let current = repo.get(&scope(), "memory").await.unwrap().unwrap();
        repo.update(&scope(), current, 1).await.unwrap();
        assert!(matches!(
            repo.renew(&scope(), &renewed, 160, 50).await,
            Err(KnowledgeError::Conflict)
        ));
    });
}

#[test]
fn failure_requires_explicit_retry_of_exact_attempt() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.create(&scope(), memory()).await.unwrap();
        let first = repo
            .claim(&scope(), "worker", 0, 50)
            .await
            .unwrap()
            .unwrap();
        repo.fail(&scope(), &first, ProcessingFailure::ProviderUnavailable, 1)
            .await
            .unwrap();
        let failed = repo
            .processing_status(&scope(), &first.source)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(failed.failure, Some(ProcessingFailure::ProviderUnavailable));
        assert_eq!(failed.state, ProcessingState::Failed);
        assert!(repo
            .claim(&scope(), "worker", 100, 50)
            .await
            .unwrap()
            .is_none());
        assert!(matches!(
            repo.retry(&scope(), &first.source, 0).await,
            Err(KnowledgeError::Conflict)
        ));
        repo.retry(&scope(), &first.source, 1).await.unwrap();
        let second = repo
            .claim(&scope(), "worker", 100, 50)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(second.attempt, 2);
        assert!(matches!(
            repo.complete(&scope(), &first, projection(), 101).await,
            Err(KnowledgeError::Conflict)
        ));
        repo.fail(&scope(), &second, ProcessingFailure::Cancelled, 101)
            .await
            .unwrap();
        assert!(matches!(
            repo.retry(&scope(), &second.source, 1).await,
            Err(KnowledgeError::Conflict)
        ));
        repo.delete(&scope(), "memory", 1).await.unwrap();
        assert!(matches!(
            repo.retry(&scope(), &second.source, 2).await,
            Err(KnowledgeError::Conflict)
        ));
    });
}

#[test]
fn scope_and_lease_fields_cannot_be_substituted() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.create(&scope(), memory()).await.unwrap();
        let lease = repo
            .claim(&scope(), "worker", 100, 50)
            .await
            .unwrap()
            .unwrap();
        for other in [
            KnowledgeScope {
                tenant_id: "other".into(),
                ..scope()
            },
            KnowledgeScope {
                project_id: "other".into(),
                ..scope()
            },
        ] {
            assert!(repo
                .claim(&other, "worker", 100, 50)
                .await
                .unwrap()
                .is_none());
            assert!(repo.projection(&other, "memory").await.unwrap().is_none());
            assert!(repo
                .complete(&other, &lease, projection(), 101)
                .await
                .is_err());
            assert!(repo.processing_status(&other, &lease.source).await.is_err());
        }
        let mut wrong = lease.clone();
        wrong.worker_id = "other-worker".into();
        assert!(matches!(
            repo.renew(&scope(), &wrong, 101, 50).await,
            Err(KnowledgeError::Conflict)
        ));
        wrong = lease.clone();
        wrong.attempt += 1;
        assert!(matches!(
            repo.complete(&scope(), &wrong, projection(), 101).await,
            Err(KnowledgeError::Conflict)
        ));
        wrong = lease.clone();
        wrong.source.revision += 1;
        assert!(matches!(
            repo.fail(&scope(), &wrong, ProcessingFailure::ProcessingFailed, 101)
                .await,
            Err(KnowledgeError::Conflict)
        ));
        repo.complete(&scope(), &lease, projection(), 101)
            .await
            .unwrap();
    });
}

#[test]
fn invalid_projection_and_time_values_do_not_consume_the_lease() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.create(&scope(), memory()).await.unwrap();
        for (now, duration) in [(-1, 5), (0, 0), (i64::MAX, 1), (0, u64::MAX)] {
            assert!(matches!(
                repo.claim(&scope(), "worker", now, duration).await,
                Err(KnowledgeError::InvalidInput)
            ));
        }
        let lease = repo
            .claim(&scope(), "worker", 100, 50)
            .await
            .unwrap()
            .unwrap();
        let mut invalid = projection();
        invalid.relationships[0].target_index = 2;
        assert!(matches!(
            repo.complete(&scope(), &lease, invalid, 101).await,
            Err(KnowledgeError::InvalidInput)
        ));
        let mut invalid = projection();
        invalid.relationships[0].score = f32::NAN;
        assert!(matches!(
            repo.complete(&scope(), &lease, invalid, 101).await,
            Err(KnowledgeError::InvalidInput)
        ));
        repo.complete(&scope(), &lease, projection(), 101)
            .await
            .unwrap();
    });
}

#[test]
fn deletion_invalidates_inflight_work_without_waiting_for_a_worker() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.create(&scope(), memory()).await.unwrap();
        let lease = repo
            .claim(&scope(), "worker", 0, 100)
            .await
            .unwrap()
            .unwrap();
        repo.delete(&scope(), "memory", 1).await.unwrap();
        assert!(matches!(
            repo.complete(&scope(), &lease, projection(), 1).await,
            Err(KnowledgeError::Conflict)
        ));
        assert!(matches!(
            repo.renew(&scope(), &lease, 1, 100).await,
            Err(KnowledgeError::Conflict)
        ));
        assert!(repo
            .claim(&scope(), "worker", 1, 100)
            .await
            .unwrap()
            .is_none());
        assert_eq!(
            repo.processing_status(&scope(), &lease.source)
                .await
                .unwrap()
                .unwrap()
                .state,
            ProcessingState::Superseded
        );
        assert!(repo.projection(&scope(), "memory").await.unwrap().is_none());
    });
}

#[test]
fn equal_memory_ids_have_independent_tenant_projections() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let other = KnowledgeScope {
            tenant_id: "other".into(),
            ..scope()
        };
        repo.create(&scope(), memory()).await.unwrap();
        repo.create(&other, memory()).await.unwrap();
        let first = repo
            .claim(&scope(), "worker", 0, 100)
            .await
            .unwrap()
            .unwrap();
        let second = repo.claim(&other, "worker", 0, 100).await.unwrap().unwrap();
        let mut different = projection();
        different.entities[0].name = "Other tenant".into();
        repo.complete(&scope(), &first, projection(), 1)
            .await
            .unwrap();
        repo.complete(&other, &second, different.clone(), 1)
            .await
            .unwrap();
        assert_eq!(
            repo.projection(&scope(), "memory")
                .await
                .unwrap()
                .unwrap()
                .projection,
            projection()
        );
        assert_eq!(
            repo.projection(&other, "memory")
                .await
                .unwrap()
                .unwrap()
                .projection,
            different
        );
        repo.delete(&other, "memory", 1).await.unwrap();
        assert!(repo.projection(&scope(), "memory").await.unwrap().is_some());
    });
}
