use super::*;

#[tokio::test]
async fn model_switch_during_http_discards_query_and_requires_selected_config_even_after_rollback()
{
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let a = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "a")
        .await
        .unwrap();
    let first = f
        .operation
        .select_index_build(&f.state, &f.auth, &a, None)
        .unwrap();
    f.operation
        .index_one(&f.state, &f.auth, &first, IndexRunOptions::default())
        .await
        .unwrap();
    f.operation
        .promote_index_build(&f.state, &f.auth, &first, None)
        .unwrap();
    let other_route = EmbeddingRoute {
        model_id: "other-embedding-model".into(),
        ..route.clone()
    };
    let b = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &other_route, "b")
        .await
        .unwrap();
    assert_eq!(a.profile.provider_revision, b.profile.provider_revision);
    endpoint.pause();
    let op = f.operation.clone();
    let state = f.state.clone();
    let auth = f.auth.clone();
    let config = first.clone();
    let query =
        tokio::spawn(async move { op.semantic_query(&state, &auth, &config, "query", 10).await });
    endpoint.entered().await;
    let second = f
        .operation
        .select_index_build(&f.state, &f.auth, &b, Some(1))
        .unwrap();
    endpoint.release();
    assert!(query.await.unwrap().is_err());
    let requests = endpoint.state.requests.lock().unwrap().len();
    assert!(f
        .operation
        .semantic_query(&f.state, &f.auth, &first, "query", 10)
        .await
        .is_err());
    assert!(f
        .operation
        .semantic_query(&f.state, &f.auth, &second, "query", 10)
        .await
        .is_err());
    assert_eq!(endpoint.state.requests.lock().unwrap().len(), requests);
    assert!(f
        .operation
        .select_index_build(&f.state, &f.auth, &a, Some(1))
        .is_err());
    let third = f
        .operation
        .select_index_build(&f.state, &f.auth, &a, Some(2))
        .unwrap();
    assert!(f
        .operation
        .semantic_query(&f.state, &f.auth, &first, "query", 10)
        .await
        .is_err());
    let result = f
        .operation
        .semantic_query(&f.state, &f.auth, &third, "query", 10)
        .await
        .unwrap();
    assert_eq!(result.config_revision, 3);
    assert_eq!(result.hits.len(), 1);
}

#[tokio::test]
async fn model_switch_while_worker_waits_blocks_late_write() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let a = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "a")
        .await
        .unwrap();
    let b = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "b")
        .await
        .unwrap();
    let first = f
        .operation
        .select_index_build(&f.state, &f.auth, &a, None)
        .unwrap();
    endpoint.pause();
    let worker = f.run(first.clone(), IndexRunOptions::default());
    endpoint.entered().await;
    let second = f
        .operation
        .select_index_build(&f.state, &f.auth, &b, Some(1))
        .unwrap();
    endpoint.release();
    assert!(worker.await.unwrap().is_err());
    assert!(f
        .operation
        .promote_index_build(&f.state, &f.auth, &first, None)
        .is_err());
    assert_eq!(
        f.repo()
            .reconcile_index_durable(&second, &|| Ok(1000))
            .unwrap()
            .completed_sources,
        0
    );
}
