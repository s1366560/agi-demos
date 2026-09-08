use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Arc, Barrier,
};

use agistack_adapters_device::knowledge::project_schema::*;
use agistack_core::project_schema::ProjectSchemaError;

use super::support::*;

#[test]
fn separate_connections_serialize_competing_cas_writers() {
    let db = Database::new();
    let repo = db.open();
    repo.bootstrap_project_schema_durable(&scope(), "actor", &command(&scope(), 1), &current)
        .unwrap();
    let workers: Vec<_> = (0..2).map(|_| db.open()).collect();
    let start = Arc::new(Barrier::new(2));
    let tasks: Vec<_> = workers
        .into_iter()
        .map(|repo| {
            let start = Arc::clone(&start);
            std::thread::spawn(move || {
                let c = command(&scope(), 2);
                start.wait();
                repo.replace_project_schema_durable(&scope(), "actor", &c, &current)
            })
        })
        .collect();
    let results: Vec<_> = tasks.into_iter().map(|task| task.join().unwrap()).collect();
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| matches!(
                result,
                Err(ProjectSchemaStorageError::Document(
                    ProjectSchemaError::RevisionConflict
                ))
            ))
            .count(),
        1
    );
    assert_eq!(db.counts(), (1, 2));
}

#[test]
fn concurrent_exact_bootstrap_replays_one_durable_acceptance() {
    let db = Database::new();
    let workers: Vec<_> = (0..2).map(|_| db.open()).collect();
    let start = Arc::new(Barrier::new(2));
    let initial = command(&scope(), 1);
    let tasks: Vec<_> = workers
        .into_iter()
        .map(|repo| {
            let start = Arc::clone(&start);
            let c = initial.clone();
            std::thread::spawn(move || {
                start.wait();
                repo.bootstrap_project_schema_durable(&scope(), "actor", &c, &current)
                    .unwrap()
            })
        })
        .collect();
    let results: Vec<_> = tasks.into_iter().map(|task| task.join().unwrap()).collect();
    assert_eq!(results[0].as_json(), results[1].as_json());
    assert_eq!(db.counts(), (1, 1));
}

#[test]
fn final_fence_cancellation_rolls_back_journal_and_head_and_fences_replay() {
    let db = Database::new();
    let repo = db.open();
    let c = command(&scope(), 1);
    let calls = AtomicUsize::new(0);
    let revoked_at_commit = || {
        if calls.fetch_add(1, Ordering::SeqCst) == 0 {
            Ok(())
        } else {
            Err(ProjectSchemaStorageError::AdmissionChanged)
        }
    };
    assert!(matches!(
        repo.bootstrap_project_schema_durable(&scope(), "actor", &c, &revoked_at_commit),
        Err(ProjectSchemaStorageError::AdmissionChanged)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(db.counts(), (0, 0));
    repo.bootstrap_project_schema_durable(&scope(), "actor", &c, &current)
        .unwrap();
    calls.store(0, Ordering::SeqCst);
    assert!(repo
        .bootstrap_project_schema_durable(&scope(), "actor", &c, &revoked_at_commit)
        .is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(db.counts(), (1, 1));
    calls.store(0, Ordering::SeqCst);
    assert!(repo
        .replace_project_schema_durable(
            &scope(),
            "actor",
            &command(&scope(), 2),
            &revoked_at_commit
        )
        .is_err());
    assert_eq!(db.counts(), (1, 1));
    calls.store(0, Ordering::SeqCst);
    assert!(repo
        .read_project_schema_durable(&scope(), &revoked_at_commit)
        .is_err());
    calls.store(0, Ordering::SeqCst);
    assert!(repo
        .project_schema_changes_durable(&scope(), 0, 10, &revoked_at_commit)
        .is_err());
    calls.store(0, Ordering::SeqCst);
    assert!(repo
        .project_schema_receipt_durable(&scope(), "actor", &c.change_id, &revoked_at_commit)
        .is_err());
}

#[test]
fn admission_is_checked_after_waiting_for_a_sqlite_write_lock() {
    let db = Database::new();
    let repo = db.open();
    let mut lock = db.sql();
    let tx = lock
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .unwrap();
    let allowed = Arc::new(AtomicBool::new(true));
    let current_calls = Arc::new(AtomicUsize::new(0));
    let (ready_tx, ready_rx) = std::sync::mpsc::channel();
    let task = {
        let allowed = Arc::clone(&allowed);
        let count = Arc::clone(&current_calls);
        std::thread::spawn(move || {
            ready_tx.send(()).unwrap();
            repo.bootstrap_project_schema_durable(&scope(), "actor", &command(&scope(), 1), &|| {
                count.fetch_add(1, Ordering::SeqCst);
                if allowed.load(Ordering::SeqCst) {
                    Ok(())
                } else {
                    Err(ProjectSchemaStorageError::AdmissionChanged)
                }
            })
        })
    };
    ready_rx
        .recv_timeout(std::time::Duration::from_secs(2))
        .unwrap();
    // No callback can run while the external writer owns the database lock.
    assert_eq!(current_calls.load(Ordering::SeqCst), 0);
    allowed.store(false, Ordering::SeqCst);
    tx.commit().unwrap();
    assert!(matches!(
        task.join().unwrap(),
        Err(ProjectSchemaStorageError::AdmissionChanged)
    ));
    assert_eq!(db.counts(), (0, 0));
}
