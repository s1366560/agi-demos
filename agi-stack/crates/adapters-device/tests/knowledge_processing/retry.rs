use super::*;
use std::cell::Cell;

fn failed(db: &Database) -> ProcessingLease {
    block_on(async {
        let repo = db.open();
        repo.create(&scope(), memory()).await.unwrap();
        let lease = repo
            .claim(&scope(), "worker", 100, 50)
            .await
            .unwrap()
            .unwrap();
        repo.fail(
            &scope(),
            &lease,
            ProcessingFailure::ProviderUnavailable,
            101,
        )
        .await
        .unwrap();
        lease
    })
}

#[test]
fn durable_retry_reopens_with_only_exact_task_pending_and_rejects_duplicate() {
    let db = Database::new();
    let lease = failed(&db);
    let other_repo = db.open();
    let mut other = memory();
    other.id = "another-failure".into();
    block_on(other_repo.create(&scope(), other)).unwrap();
    let other_lease = block_on(other_repo.claim(&scope(), "worker", 100, 50))
        .unwrap()
        .unwrap();
    block_on(other_repo.fail(&scope(), &other_lease, ProcessingFailure::Cancelled, 101)).unwrap();
    let before = block_on(db.open().get(&scope(), "memory")).unwrap();
    let seen = db
        .open()
        .processing_task_durable(&scope(), &lease.source, &|| Ok(102))
        .unwrap();
    assert!(seen.current);
    assert_eq!(seen.task.unwrap().state, ProcessingState::Failed);
    db.open()
        .retry_processing_durable(&scope(), &lease.source, 1, &|| Ok(103))
        .unwrap();
    let reopened = db.open();
    assert_eq!(
        reopened
            .processing_task_durable(&scope(), &other_lease.source, &|| Ok(104))
            .unwrap()
            .task
            .unwrap()
            .state,
        ProcessingState::Failed
    );
    let current = reopened
        .processing_task_durable(&scope(), &lease.source, &|| Ok(104))
        .unwrap();
    assert_eq!(
        current.task.as_ref().unwrap().state,
        ProcessingState::Pending
    );
    assert_eq!(current.task.unwrap().attempt, 1);
    assert_eq!(
        serde_json::to_value(block_on(reopened.get(&scope(), "memory")).unwrap()).unwrap(),
        serde_json::to_value(before).unwrap()
    );
    assert!(matches!(
        reopened.retry_processing_durable(&scope(), &lease.source, 1, &|| Ok(105)),
        Err(KnowledgeError::Conflict)
    ));
    let next = block_on(reopened.claim(&scope(), "explicit-worker", 110, 50))
        .unwrap()
        .unwrap();
    assert_eq!(next.attempt, 2);
    block_on(reopened.complete(&scope(), &next, projection(), 111)).unwrap();
    assert!(matches!(
        reopened.retry_processing_durable(&scope(), &lease.source, 1, &|| Ok(112)),
        Err(KnowledgeError::Conflict)
    ));
}

#[test]
fn duplicate_retry_connections_have_one_winner_and_old_attempt_cannot_retry_new_failure() {
    let db = Database::new();
    let lease = failed(&db);
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let joins: Vec<_> = (0..2)
        .map(|_| {
            let repo = db.open();
            let source = lease.source.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                repo.retry_processing_durable(&scope(), &source, 1, &|| Ok(102))
            })
        })
        .collect();
    let results: Vec<_> = joins.into_iter().map(|join| join.join().unwrap()).collect();
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| matches!(result, Err(KnowledgeError::Conflict)))
            .count(),
        1
    );
    let repo = db.open();
    let next = block_on(repo.claim(&scope(), "explicit-worker", 110, 50))
        .unwrap()
        .unwrap();
    block_on(repo.fail(&scope(), &next, ProcessingFailure::Cancelled, 111)).unwrap();
    assert!(matches!(
        repo.retry_processing_durable(&scope(), &lease.source, 1, &|| Ok(112)),
        Err(KnowledgeError::Conflict)
    ));
    repo.retry_processing_durable(&scope(), &lease.source, 2, &|| Ok(112))
        .unwrap();
}

#[test]
fn retry_clock_rejection_rolls_back_and_obsolete_source_is_not_reported_as_success() {
    let db = Database::new();
    let lease = failed(&db);
    let repo = db.open();
    let calls = Cell::new(0);
    assert!(matches!(
        repo.retry_processing_durable(&scope(), &lease.source, 1, &|| {
            calls.set(calls.get() + 1);
            if calls.get() == 1 {
                Ok(102)
            } else {
                Err(KnowledgeError::Conflict)
            }
        }),
        Err(KnowledgeError::Conflict)
    ));
    assert_eq!(
        repo.processing_task_durable(&scope(), &lease.source, &|| Ok(104))
            .unwrap()
            .task
            .unwrap()
            .state,
        ProcessingState::Failed
    );
    let current = block_on(repo.get(&scope(), "memory")).unwrap().unwrap();
    block_on(repo.update(&scope(), current, 1)).unwrap();
    let observation = db
        .open()
        .processing_task_durable(&scope(), &lease.source, &|| Ok(105))
        .unwrap();
    assert!(!observation.current);
    assert!(observation.task.is_none());
    assert!(matches!(
        repo.retry_processing_durable(&scope(), &lease.source, 1, &|| Ok(106)),
        Err(KnowledgeError::Conflict)
    ));
    let wrong_scope = KnowledgeScope {
        tenant_id: "other".into(),
        ..scope()
    };
    assert!(repo
        .processing_task_durable(&wrong_scope, &lease.source, &|| Ok(107))
        .is_err());
    assert!(repo
        .retry_processing_durable(&wrong_scope, &lease.source, 1, &|| Ok(107))
        .is_err());
}
