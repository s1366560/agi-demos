use super::*;

#[tokio::test]
async fn delayed_embedding_renews_and_cancelled_future_marks_only_current_lease_failed() {
    for cancel in [false, true] {
        let f = Fixture::new().await;
        let endpoint = Endpoint::new().await;
        let route = f.provider(&endpoint).await;
        let build = f
            .operation
            .prepare_index_build(&f.state, &f.auth, &route, "build")
            .await
            .unwrap();
        endpoint.pause();
        let task = f.run(
            build.clone(),
            IndexRunOptions {
                lease_ms: 200,
                renew_every_ms: 40,
            },
        );
        endpoint.entered().await;
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
        if cancel {
            task.abort();
            assert!(task.await.unwrap_err().is_cancelled());
            endpoint.release();
            let status = f
                .repo()
                .reconcile_index_durable(&build, &|| Ok(chrono::Utc::now().timestamp_millis()))
                .unwrap();
            assert_eq!(status.failed_sources, 1);
            assert!(f
                .repo()
                .claim_index_durable(&build, "other", 100, &|| Ok(
                    chrono::Utc::now().timestamp_millis()
                ))
                .unwrap()
                .is_none());
        } else {
            endpoint.release();
            assert_eq!(
                task.await.unwrap().unwrap().unwrap().outcome,
                IndexRunOutcome::Indexed
            );
            f.operation
                .promote_index_build(&f.state, &f.auth, &build, None)
                .unwrap();
        }
    }
}

#[tokio::test]
async fn revoked_or_downgraded_admission_during_embedding_never_publishes() {
    for sql in [
        "UPDATE desktop_user_sessions SET status='revoked'",
        "UPDATE desktop_tenant_memberships SET role='viewer'",
        "UPDATE desktop_user_sessions SET expires_at_ms=0",
    ] {
        let f = Fixture::new().await;
        let endpoint = Endpoint::new().await;
        let route = f.provider(&endpoint).await;
        let build = f
            .operation
            .prepare_index_build(&f.state, &f.auth, &route, "build")
            .await
            .unwrap();
        endpoint.pause();
        let task = f.run(
            build.clone(),
            IndexRunOptions {
                lease_ms: 1000,
                renew_every_ms: 500,
            },
        );
        endpoint.entered().await;
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute_batch(sql)
            .unwrap();
        endpoint.release();
        assert!(task.await.unwrap().is_err());
        assert_eq!(
            f.repo()
                .reconcile_index_durable(&build, &|| Ok(chrono::Utc::now().timestamp_millis()))
                .unwrap()
                .completed_sources,
            0
        );
    }
}

#[tokio::test]
async fn retired_generation_rejects_index_writeback_and_new_generation_reclaims() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let build = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "build")
        .await
        .unwrap();
    endpoint.pause();
    let task = f.run(
        build.clone(),
        IndexRunOptions {
            lease_ms: 200,
            renew_every_ms: 100,
        },
    );
    endpoint.entered().await;
    let (snapshot, generation) = stage(&f.directory, 2, true).await;
    let retirement = f.state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    endpoint.release();
    assert!(matches!(
        task.await.unwrap(),
        Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
    ));
    tokio::time::sleep(std::time::Duration::from_millis(210)).await;
    let lease = Arc::new(
        f.state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let next =
        KnowledgeOperationV2::admit(lease.clone(), &f.auth, &operation_scope(&f.auth, &lease))
            .unwrap();
    let receipt = next
        .index_one(&f.state, &f.auth, &build, IndexRunOptions::default())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(receipt.attempt, 2);
    assert_eq!(receipt.outcome, IndexRunOutcome::Indexed);
    next.promote_index_build(&f.state, &f.auth, &build, None)
        .unwrap();
    drop(f.operation);
    retirement.dispose().await;
}

#[tokio::test]
async fn source_edit_while_query_embedding_waits_removes_old_source_from_final_hits() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let build = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "build")
        .await
        .unwrap();
    f.operation
        .index_one(&f.state, &f.auth, &build, IndexRunOptions::default())
        .await
        .unwrap();
    f.operation
        .promote_index_build(&f.state, &f.auth, &build, None)
        .unwrap();
    endpoint.pause();
    let op = f.operation.clone();
    let state = f.state.clone();
    let auth = f.auth.clone();
    let querybuild = build.clone();
    let task = tokio::spawn(async move {
        op.semantic_query(&state, &auth, &querybuild, "query", 10)
            .await
    });
    endpoint.entered().await;
    let mut memory = f
        .repo()
        .get(&f.operation.scope, &f.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    memory.content = "changed during query".into();
    f.repo()
        .update(&f.operation.scope, memory, 1)
        .await
        .unwrap();
    endpoint.release();
    let result = task.await.unwrap().unwrap();
    assert!(result.hits.is_empty());
    assert_eq!(result.processing.pending_sources, 1);
    assert_eq!(result.index.current_sources, 0);
}

#[tokio::test]
async fn generation_publication_waits_for_admitted_index_transaction_commit() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let build = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "build")
        .await
        .unwrap();
    let provider = super::super::super::embedding_provider::resolve(
        &f.operation,
        &f.state,
        &f.auth,
        &route,
        true,
    )
    .unwrap();
    let repo = f.repo();
    let claim = repo
        .claim_index_durable(&build, "linearize", 5000, &|| {
            Ok(chrono::Utc::now().timestamp_millis())
        })
        .unwrap()
        .unwrap();
    let connection =
        rusqlite::Connection::open(f.directory.0.join("knowledge/memories.db")).unwrap();
    connection.execute_batch("BEGIN EXCLUSIVE").unwrap();
    let (entered, waiting) = std::sync::mpsc::channel();
    let operation = f.operation.clone();
    let state = f.state.clone();
    let auth = f.auth.clone();
    let write = tokio::task::spawn_blocking(move || {
        super::super::super::embedding_provider::with_current(
            &operation,
            &state,
            &auth,
            &provider,
            true,
            |clock| {
                entered.send(()).unwrap();
                repo.complete_index_durable(&claim, &[1.0, 0.0], clock)
            },
        )
    });
    waiting
        .recv_timeout(std::time::Duration::from_secs(3))
        .unwrap();
    let (snapshot, generation) = stage(&f.directory, 2, true).await;
    let state = f.state.clone();
    let (published, check) = std::sync::mpsc::channel();
    let publish = tokio::task::spawn_blocking(move || {
        let retirement = state.platform_plugin_authority_v2.replace_local_baseline(
            &snapshot,
            &serde_json::to_value(&snapshot).unwrap(),
            generation,
        );
        published.send(()).unwrap();
        retirement
    });
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    assert!(matches!(
        check.try_recv(),
        Err(std::sync::mpsc::TryRecvError::Empty)
    ));
    connection.execute_batch("COMMIT").unwrap();
    assert!(write.await.unwrap().is_ok());
    let retirement = publish.await.unwrap();
    check
        .recv_timeout(std::time::Duration::from_secs(3))
        .unwrap();
    assert_eq!(
        f.repo()
            .reconcile_index_durable(&build, &|| Ok(chrono::Utc::now().timestamp_millis()))
            .unwrap()
            .completed_sources,
        1
    );
    assert!(f
        .operation
        .promote_index_build(&f.state, &f.auth, &build, None)
        .is_err());
    drop(f.operation);
    retirement.dispose().await;
}

#[tokio::test]
async fn session_expiry_during_post_read_work_discards_the_result() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let build = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "build")
        .await
        .unwrap();
    f.operation
        .index_one(&f.state, &f.auth, &build, IndexRunOptions::default())
        .await
        .unwrap();
    f.operation
        .promote_index_build(&f.state, &f.auth, &build, None)
        .unwrap();
    let provider = super::super::super::embedding_provider::resolve(
        &f.operation,
        &f.state,
        &f.auth,
        &route,
        false,
    )
    .unwrap();
    f.state
        .session_store
        .connection()
        .unwrap()
        .execute(
            "UPDATE desktop_user_sessions SET expires_at_ms=?1 WHERE id=?2",
            rusqlite::params![
                chrono::Utc::now().timestamp_millis() + 500,
                f.auth.session_id
            ],
        )
        .unwrap();
    let result = super::super::super::embedding_provider::with_current(
        &f.operation,
        &f.state,
        &f.auth,
        &provider,
        false,
        |clock| {
            let read = f.repo().read_active_index_durable(&build, clock)?;
            assert_eq!(read.vectors.len(), 1);
            // Ranking happens after the SQLite read transaction. The wrapper's
            // final clock must reject expiry during that post-read work too.
            std::thread::sleep(std::time::Duration::from_millis(650));
            Ok(read)
        },
    );
    assert!(matches!(result, Err(KnowledgeAuthorityErrorV2::Forbidden)));
}
