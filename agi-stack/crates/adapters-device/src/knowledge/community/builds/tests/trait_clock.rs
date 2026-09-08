use std::time::Duration;

use super::*;

// Hold the repository mutex while a trait call queues behind it. The supplied
// host timestamp is valid at invocation but its lease expires during the wait.
fn while_write_locked<T: Send>(
    repo: &SqliteKnowledgeRepository,
    action: impl FnOnce() -> T + Send,
) -> T {
    std::thread::scope(|threads| {
        let guard = repo.conn.lock().unwrap();
        let (ready, started) = std::sync::mpsc::channel();
        let worker = threads.spawn(move || {
            ready.send(()).unwrap();
            action()
        });
        started.recv().unwrap();
        std::thread::sleep(Duration::from_millis(150));
        drop(guard);
        worker.join().unwrap()
    })
}

fn reject_expired_transition(renew: bool) {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let s = scope("a", "p");
    let receipt = block_on(populated(&repo, &s));
    let lease = repo
        .claim_community_job_durable(&s, &receipt.build_id, "worker", 40, &|| Ok(100))
        .unwrap()
        .unwrap();
    let result = while_write_locked(&repo, || {
        if renew {
            block_on(CommunityBuildRepository::renew_community_job(
                &repo, &s, &lease, 110, 100,
            ))
            .map(|_| ())
        } else {
            block_on(CommunityBuildRepository::fail_community_job(
                &repo,
                &s,
                &lease,
                CommunityJobFailure::Cancelled,
                110,
            ))
        }
    });
    assert!(matches!(result, Err(KnowledgeError::Conflict)));
    let status = repo
        .community_job_status_durable(&s, &receipt.build_id, &lease.candidate_id)
        .unwrap()
        .unwrap();
    assert_eq!(status.state, CommunityJobState::Leased);
    assert_eq!(status.attempt, 1);
}

#[test]
fn trait_renew_rejects_expiry_while_waiting_for_write_lock() {
    reject_expired_transition(true);
}

#[test]
fn trait_fail_rejects_expiry_while_waiting_for_write_lock() {
    reject_expired_transition(false);
}

#[test]
fn trait_claim_uses_lock_admission_time_for_new_deadline() {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let s = scope("a", "p");
    let receipt = block_on(populated(&repo, &s));
    let lease = while_write_locked(&repo, || {
        block_on(CommunityBuildRepository::claim_community_job(
            &repo,
            &s,
            &receipt.build_id,
            "worker",
            100,
            1000,
        ))
        .unwrap()
        .unwrap()
    });
    assert!(
        lease.expires_at_ms >= 1200,
        "deadline must include lock waiting"
    );
}

#[test]
fn trait_claim_reclaims_a_lease_that_expires_during_lock_wait() {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let s = scope("a", "p");
    let receipt = block_on(populated(&repo, &s));
    let old = repo
        .claim_community_job_durable(&s, &receipt.build_id, "old", 40, &|| Ok(100))
        .unwrap()
        .unwrap();
    let lease = while_write_locked(&repo, || {
        block_on(CommunityBuildRepository::claim_community_job(
            &repo,
            &s,
            &receipt.build_id,
            "new",
            110,
            1000,
        ))
        .unwrap()
        .unwrap()
    });
    assert_eq!(lease.attempt, 2);
    assert_ne!(lease.token, old.token);
    assert!(lease.expires_at_ms >= 1210);
}

#[test]
fn trait_failure_rejects_expiry_while_waiting_on_another_sqlite_connection() {
    let db = Database::new();
    let repo = db.open();
    let s = scope("a", "p");
    let receipt = block_on(populated(&repo, &s));
    let lease = repo
        .claim_community_job_durable(&s, &receipt.build_id, "worker", 40, &|| Ok(100))
        .unwrap()
        .unwrap();
    let lock = db.sql();
    lock.execute_batch("BEGIN IMMEDIATE").unwrap();
    let result = std::thread::scope(|threads| {
        let (ready, started) = std::sync::mpsc::channel();
        let repo = &repo;
        let s = &s;
        let lease = &lease;
        let worker = threads.spawn(move || {
            ready.send(()).unwrap();
            block_on(CommunityBuildRepository::fail_community_job(
                repo,
                s,
                lease,
                CommunityJobFailure::Cancelled,
                110,
            ))
        });
        started.recv().unwrap();
        std::thread::sleep(Duration::from_millis(150));
        lock.execute_batch("COMMIT").unwrap();
        worker.join().unwrap()
    });
    assert!(matches!(result, Err(KnowledgeError::Conflict)));
    assert_eq!(
        repo.community_job_status_durable(&s, &receipt.build_id, &lease.candidate_id)
            .unwrap()
            .unwrap()
            .state,
        CommunityJobState::Leased
    );
}
