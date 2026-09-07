use super::*;

#[tokio::test]
async fn superseded_generation_cannot_start_a_new_read_with_an_old_operation() {
    let f = Fixture::new("viewer").await;
    let (snapshot, generation) = stage(&f.directory, 2, true).await;
    let retirement = f.state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    assert!(matches!(
        f.operation.entities(&f.state, &f.auth, &request()),
        Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
    ));
    drop(f.operation);
    retirement.dispose().await;
}

#[tokio::test]
async fn generation_replacement_during_read_wait_discards_the_result() {
    let f = Fixture::new("viewer").await;
    let connection =
        rusqlite::Connection::open(f.directory.0.join("knowledge/memories.db")).unwrap();
    connection.execute_batch("BEGIN EXCLUSIVE").unwrap();
    let (entered, wait) = std::sync::mpsc::channel();
    let op = f.operation.clone();
    let state = f.state.clone();
    let auth = f.auth.clone();
    let read = tokio::task::spawn_blocking(move || {
        super::super::super::processing_context::with_read_current(&op, &state, &auth, |clock| {
            entered.send(()).unwrap();
            op.authority
                .repository()
                .unwrap()
                .entities_durable(&op.scope, &request(), clock)
        })
    });
    wait.recv_timeout(std::time::Duration::from_secs(3))
        .unwrap();
    // Stage before releasing the read lock: the new generation never opens this storage here.
    let (snapshot, generation) = stage(&f.directory, 2, false).await;
    let retirement = f.state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    connection.execute_batch("COMMIT").unwrap();
    assert!(matches!(
        read.await.unwrap(),
        Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
    ));
    drop(f.operation);
    retirement.dispose().await;
}

#[tokio::test]
async fn session_expiry_after_read_lock_wait_or_before_return_discards_all_rows() {
    for before_return in [false, true] {
        let f = Fixture::new("viewer").await;
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute(
                "UPDATE desktop_user_sessions SET expires_at_ms=?1 WHERE id=?2",
                rusqlite::params![
                    chrono::Utc::now().timestamp_millis() + 1000,
                    f.auth.session_id
                ],
            )
            .unwrap();
        let connection =
            rusqlite::Connection::open(f.directory.0.join("knowledge/memories.db")).unwrap();
        if !before_return {
            connection.execute_batch("BEGIN EXCLUSIVE").unwrap();
        }
        let (entered, wait) = std::sync::mpsc::channel();
        let op = f.operation.clone();
        let state = f.state.clone();
        let auth = f.auth.clone();
        let read = tokio::task::spawn_blocking(move || {
            super::super::super::processing_context::with_read_current(
                &op,
                &state,
                &auth,
                |clock| {
                    entered.send(()).unwrap();
                    let calls = std::cell::Cell::new(0);
                    op.authority.repository().unwrap().entities_durable(
                        &op.scope,
                        &request(),
                        &|| {
                            let call = calls.get();
                            calls.set(call + 1);
                            if before_return && call == 1 {
                                std::thread::sleep(std::time::Duration::from_millis(1100));
                            }
                            clock()
                        },
                    )
                },
            )
        });
        wait.recv_timeout(std::time::Duration::from_secs(3))
            .unwrap();
        if !before_return {
            std::thread::sleep(std::time::Duration::from_millis(1100));
            connection.execute_batch("COMMIT").unwrap();
        }
        assert!(matches!(
            read.await.unwrap(),
            Err(KnowledgeAuthorityErrorV2::Forbidden)
        ));
    }
}
