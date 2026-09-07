use super::*;
use std::{
    sync::{mpsc, Arc},
    time::Duration,
};

#[test]
fn deadline_before_commit_rolls_back_claim_renew_complete_fail_and_retry() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let b = build("t", "p", "b");
        create(&repo, &b.scope, "one").await;
        finish(&repo, &b.scope).await;
        repo.begin_index_build_durable(&b, &|| Ok(110)).unwrap();
        let advancing = || {
            let c = std::cell::Cell::new(0);
            move || {
                let call = c.get();
                c.set(call + 1);
                Ok(if call == 0 { 110 } else { 210 })
            }
        };
        assert!(repo
            .claim_index_durable(&b, "worker", 100, &advancing())
            .is_err());
        let lease = claim(&repo, &b, 110);
        assert_eq!(lease.attempt, 1);
        assert!(repo.renew_index_durable(&lease, 500, &advancing()).is_err());
        assert!(repo
            .complete_index_durable(&lease, &[1.0, 0.0], &advancing())
            .is_err());
        assert!(repo
            .fail_index_durable(&lease, IndexFailure::Cancelled, &advancing())
            .is_err());
        let before = repo
            .index_job_status_durable(&b, &lease.input, &|| Ok(111))
            .unwrap()
            .unwrap();
        assert_eq!(before.state, IndexJobState::Leased);
        repo.fail_index_durable(&lease, IndexFailure::Cancelled, &|| Ok(111))
            .unwrap();
        let c = std::cell::Cell::new(0);
        let expired = || {
            let call = c.get();
            c.set(call + 1);
            if call == 0 {
                Ok(112)
            } else {
                Err(KnowledgeError::Conflict)
            }
        };
        assert!(repo
            .retry_index_durable(&b, &lease.input, 1, &expired)
            .is_err());
        assert_eq!(
            repo.index_job_status_durable(&b, &lease.input, &|| Ok(113))
                .unwrap()
                .unwrap()
                .state,
            IndexJobState::Failed
        );
        repo.retry_index_durable(&b, &lease.input, 1, &|| Ok(114))
            .unwrap();
        let retried = claim(&repo, &b, 115);
        repo.complete_index_durable(&retried, &[1.0, 0.0], &|| Ok(116))
            .unwrap();
        let c = std::cell::Cell::new(0);
        let expired = || {
            let call = c.get();
            c.set(call + 1);
            if call == 0 {
                Ok(117)
            } else {
                Err(KnowledgeError::Conflict)
            }
        };
        assert!(repo
            .promote_index_build_durable(&b, None, &expired)
            .is_err());
        assert!(repo
            .active_index_build_durable(&b.scope, &|| Ok(118))
            .unwrap()
            .is_none());
    });
}

#[test]
fn sqlite_lock_wait_uses_fresh_admission_clock_before_any_index_write() {
    let db = Database::new();
    let repo = Arc::new(db.open());
    let b = build("t", "p", "b");
    repo.begin_index_build_durable(&b, &|| Ok(1)).unwrap();
    let connection = db.sql();
    connection.execute_batch("BEGIN EXCLUSIVE").unwrap();
    let deadline = std::time::Instant::now() + Duration::from_millis(150);
    let (sent, received) = mpsc::channel();
    let worker_repo = repo.clone();
    let worker_build = b.clone();
    let worker = std::thread::spawn(move || {
        sent.send(()).unwrap();
        worker_repo.claim_index_durable(&worker_build, "worker", 100, &|| {
            if std::time::Instant::now() >= deadline {
                Err(KnowledgeError::Conflict)
            } else {
                Ok(1)
            }
        })
    });
    received.recv_timeout(Duration::from_secs(2)).unwrap();
    std::thread::sleep(Duration::from_millis(200));
    connection.execute_batch("COMMIT").unwrap();
    assert!(matches!(
        worker.join().unwrap(),
        Err(KnowledgeError::Conflict)
    ));
}
