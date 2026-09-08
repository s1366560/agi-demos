use super::*;

#[test]
fn restart_reclaim_and_failed_attempt_retry_fence_old_tokens() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let s = scope("a", "p");
        let receipt = populated(&repo, &s).await;
        let first = repo
            .claim_community_job(&s, &receipt.build_id, "worker", 100, 100)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(first.attempt, 1);
        assert_eq!(first.graph_digest, receipt.graph_digest);
        assert!(repo
            .claim_community_job(&s, &receipt.build_id, "other", 199, 100)
            .await
            .unwrap()
            .is_none());
        drop(repo);
        let repo = db.open();
        let second = repo
            .claim_community_job(&s, &receipt.build_id, "other", 200, 100)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(second.attempt, 2);
        assert_ne!(first.token, second.token);
        assert!(repo
            .renew_community_job(&s, &first, 201, 100)
            .await
            .is_err());
        assert!(repo
            .fail_community_job(&s, &first, CommunityJobFailure::ExecutionFailed, 201)
            .await
            .is_err());
        repo.fail_community_job(&s, &second, CommunityJobFailure::WorkerUnavailable, 201)
            .await
            .unwrap();
        assert!(repo
            .claim_community_job(&s, &receipt.build_id, "other", 400, 100)
            .await
            .unwrap()
            .is_none());
        assert!(repo
            .retry_community_job(&s, &receipt.build_id, &second.candidate_id, 1)
            .await
            .is_err());
        repo.retry_community_job(&s, &receipt.build_id, &second.candidate_id, 2)
            .await
            .unwrap();
        let third = repo
            .claim_community_job(&s, &receipt.build_id, "worker", 500, 100)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(third.attempt, 3);
        assert!(repo
            .fail_community_job(&s, &second, CommunityJobFailure::Cancelled, 501)
            .await
            .is_err());
        let renewed = repo
            .renew_community_job_durable(&s, &third, 100, &|| Ok(550))
            .unwrap();
        assert_eq!(renewed.expires_at_ms, 650);
        assert_eq!(renewed.token, third.token);
        assert!(repo
            .fail_community_job(&s, &renewed, CommunityJobFailure::Cancelled, 650)
            .await
            .is_err());
    });
}

#[test]
fn wrong_scope_build_token_and_attempt_cannot_mutate_lease() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        let receipt = populated(&repo, &s).await;
        let lease = repo
            .claim_community_job(&s, &receipt.build_id, "worker", 100, 100)
            .await
            .unwrap()
            .unwrap();
        for foreign in [scope("b", "p"), scope("a", "q")] {
            assert!(repo
                .fail_community_job(&foreign, &lease, CommunityJobFailure::Cancelled, 101)
                .await
                .is_err());
            assert!(repo
                .community_job_status(&foreign, &receipt.build_id, &lease.candidate_id)
                .await
                .unwrap()
                .is_none());
            assert!(repo
                .retry_community_job(&foreign, &receipt.build_id, &lease.candidate_id, 1)
                .await
                .is_err());
        }
        let mut wrong = lease.clone();
        wrong.token = "wrong".into();
        assert!(repo
            .renew_community_job(&s, &wrong, 101, 100)
            .await
            .is_err());
        let mut wrong = lease.clone();
        wrong.attempt += 1;
        assert!(repo
            .renew_community_job(&s, &wrong, 101, 100)
            .await
            .is_err());
        let mut wrong = lease.clone();
        wrong.build_id = "wrong".into();
        assert!(repo
            .renew_community_job(&s, &wrong, 101, 100)
            .await
            .is_err());
        let mut wrong = lease.clone();
        wrong.graph_digest = "wrong".into();
        assert!(repo
            .renew_community_job(&s, &wrong, 101, 100)
            .await
            .is_err());
        assert!(repo.renew_community_job(&s, &lease, 101, 0).await.is_err());
        assert!(repo
            .renew_community_job(&s, &lease, 101, u64::MAX)
            .await
            .is_err());
        assert_eq!(
            repo.community_job_status(&s, &receipt.build_id, &lease.candidate_id)
                .await
                .unwrap()
                .unwrap()
                .state,
            CommunityJobState::Leased
        );
    });
}

#[test]
fn admission_clock_change_and_deadline_crossing_roll_back_mutations() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        let receipt = populated(&repo, &s).await;
        let tick = std::cell::Cell::new(100);
        let clock = || {
            let value = tick.get();
            tick.set(value + 10);
            Ok(value)
        };
        assert!(repo
            .claim_community_job_durable(&s, &receipt.build_id, "worker", 10, &clock)
            .is_err());
        let lease = repo
            .claim_community_job(&s, &receipt.build_id, "worker", 100, 100)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(lease.attempt, 1);
        let tick = std::cell::Cell::new(199);
        let clock = || {
            let value = tick.get();
            tick.set(value + 1);
            Ok(value)
        };
        assert!(repo
            .renew_community_job_durable(&s, &lease, 100, &clock)
            .is_err());
        let calls = std::cell::Cell::new(0);
        let denied = || {
            calls.set(calls.get() + 1);
            if calls.get() == 1 {
                Ok(150)
            } else {
                Err(KnowledgeError::Conflict)
            }
        };
        assert!(repo
            .fail_community_job_durable(&s, &lease, CommunityJobFailure::Cancelled, &denied)
            .is_err());
        assert_eq!(
            repo.community_job_status(&s, &receipt.build_id, &lease.candidate_id)
                .await
                .unwrap()
                .unwrap()
                .state,
            CommunityJobState::Leased
        );
        // Failed renewal did not silently extend the authoritative deadline.
        assert!(repo
            .claim_community_job(&s, &receipt.build_id, "other", 200, 100)
            .await
            .unwrap()
            .is_some());
    });
}

#[test]
fn concurrent_connections_cannot_claim_the_same_live_job() {
    let db = Database::new();
    let s = scope("a", "p");
    let repo = db.open();
    let receipt = block_on(populated(&repo, &s));
    let first = db.open();
    let second = db.open();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let outcomes = std::thread::scope(|threads| {
        let a = threads.spawn(|| {
            barrier.wait();
            first
                .claim_community_job_durable(&s, &receipt.build_id, "first", 100, &|| Ok(100))
                .unwrap()
        });
        let b = threads.spawn(|| {
            barrier.wait();
            second
                .claim_community_job_durable(&s, &receipt.build_id, "second", 100, &|| Ok(100))
                .unwrap()
        });
        [a.join().unwrap(), b.join().unwrap()]
    });
    assert_eq!(outcomes.iter().filter(|lease| lease.is_some()).count(), 1);
}
