use super::*;
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        mpsc,
    },
    time::Duration,
};

fn deadline(f: &Fixture) -> i64 {
    let expires = chrono::Utc::now().timestamp_millis() + 1000;
    f.state
        .session_store
        .connection()
        .unwrap()
        .execute(
            "UPDATE desktop_user_sessions SET expires_at_ms=?1 WHERE id=?2",
            rusqlite::params![expires, f.auth.session_id],
        )
        .unwrap();
    expires
}

fn wait_until_expired(expires: i64) {
    while chrono::Utc::now().timestamp_millis() <= expires {
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[tokio::test]
async fn expiry_during_sqlite_lock_wait_rejects_with_outer_generation_lease_still_held() {
    let f = Fixture::new().await;
    let first = f.command(1);
    let expires = deadline(&f);
    let lock = f.sql();
    lock.execute_batch("BEGIN IMMEDIATE").unwrap();
    let (entered, ready) = mpsc::channel();
    let calls = Arc::new(AtomicUsize::new(0));
    let operation = Arc::clone(&f.operation);
    let state = Arc::clone(&f.state);
    let auth = f.auth.clone();
    let count = Arc::clone(&calls);
    let worker = tokio::task::spawn_blocking(move || {
        operation.with_current_for_test(&state, &auth, true, |repo, current| {
            entered.send(()).unwrap();
            repo.bootstrap_project_schema_durable(
                &KnowledgeScope {
                    tenant_id: auth.workspace.tenant_id.clone(),
                    project_id: auth.workspace.project_id.clone(),
                },
                &auth.user.user_id,
                &first,
                &|| {
                    count.fetch_add(1, Ordering::SeqCst);
                    current()
                },
            )
        })
    });
    ready.recv_timeout(Duration::from_secs(3)).unwrap();
    assert!(chrono::Utc::now().timestamp_millis() < expires);
    assert!(!worker.is_finished());
    // The operation entered with current auth/generation while another writer
    // holds SQLite. Storage's entry callback cannot run before that lock clears.
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    wait_until_expired(expires);
    lock.execute_batch("COMMIT").unwrap();
    assert!(matches!(
        worker.await.unwrap(),
        Err(ProjectSchemaOperationError::Authority(
            KnowledgeAuthorityErrorV2::Forbidden
        ))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(f.counts(), (0, 0, 0));
}

#[tokio::test]
async fn final_real_callback_expiry_rolls_back_insert_and_fences_exact_replay() {
    for replay in [false, true] {
        let f = Fixture::new().await;
        let first = f.command(1);
        if replay {
            f.operation.bootstrap(&f.state, &f.auth, &first).unwrap();
        }
        let expires = deadline(&f);
        let (entered, ready) = mpsc::channel();
        let (release, resume) = mpsc::channel();
        let count = Arc::new(AtomicUsize::new(0));
        let calls = Arc::clone(&count);
        let operation = Arc::clone(&f.operation);
        let state = Arc::clone(&f.state);
        let auth = f.auth.clone();
        let worker = tokio::task::spawn_blocking(move || {
            operation.with_current_for_test(&state, &auth, true, |repo, current| {
                repo.bootstrap_project_schema_durable(
                    &KnowledgeScope {
                        tenant_id: auth.workspace.tenant_id.clone(),
                        project_id: auth.workspace.project_id.clone(),
                    },
                    &auth.user.user_id,
                    &first,
                    &|| {
                        if calls.fetch_add(1, Ordering::SeqCst) == 1 {
                            entered.send(()).unwrap();
                            resume.recv_timeout(Duration::from_secs(3)).unwrap();
                        }
                        current()
                    },
                )
            })
        });
        ready.recv_timeout(Duration::from_secs(3)).unwrap();
        assert!(chrono::Utc::now().timestamp_millis() < expires);
        let observer = f.sql();
        observer.busy_timeout(Duration::ZERO).unwrap();
        assert!(
            observer.execute_batch("BEGIN IMMEDIATE").is_err(),
            "final callback must execute inside the SQLite write transaction"
        );
        wait_until_expired(expires);
        release.send(()).unwrap();
        assert!(matches!(
            worker.await.unwrap(),
            Err(ProjectSchemaOperationError::Authority(
                KnowledgeAuthorityErrorV2::Forbidden
            ))
        ));
        assert_eq!(count.load(Ordering::SeqCst), 2);
        assert_eq!(f.counts(), if replay { (1, 1, 0) } else { (0, 0, 0) });
    }
}
