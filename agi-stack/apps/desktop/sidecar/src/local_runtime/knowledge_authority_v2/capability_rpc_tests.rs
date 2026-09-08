use super::*;

fn restrict(f: &Fixture, actions: &[&str]) {
    f.operation
        .authority
        .inner
        .lock()
        .unwrap()
        .validation_actions = Some(actions.iter().map(|action| (*action).to_owned()).collect());
}

#[tokio::test]
async fn processing_routes_require_the_exact_published_action_before_provider_work() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    restrict(
        &f,
        &[
            "text",
            "processing-query",
            "processing-command",
            "view",
            "list",
        ],
    );
    assert_eq!(
        query(&f, json!({"operation":"configuration"})).await.0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        query(&f, json!({"operation":"entities","request":{"limit":1}}))
            .await
            .0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        query(
            &f,
            json!({"operation":"text","literal":"missing","request":{"limit":1}})
        )
        .await
        .0,
        StatusCode::OK
    );
    assert_eq!(
        command(&f, configure(&route, "a", None)).await.0,
        StatusCode::FORBIDDEN
    );
    assert!(endpoint.state.requests.lock().unwrap().is_empty());
    restrict(&f, &["configure_embedding"]);
    assert_eq!(
        command(&f, configure(&route, "a", None)).await.0,
        StatusCode::OK
    );
    assert_eq!(
        command(
            &f,
            json!({"operation":"index_one","build_id":"a","config_revision":1})
        )
        .await
        .0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(endpoint.state.requests.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn withdrawing_an_index_action_during_embedding_prevents_vector_commit() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    assert_eq!(
        command(&f, configure(&route, "a", None)).await.0,
        StatusCode::OK
    );
    endpoint.pause();
    let state = f.state.clone();
    let scope = operation_scope(&f.auth, &f.operation._lease);
    let pending = tokio::spawn(async move {
        request(state,"/api/v1/knowledge/processing-command",json!({"scope":scope,"command":{"operation":"index_one","build_id":"a","config_revision":1}}),true).await
    });
    endpoint.entered().await;
    restrict(&f, &["configuration"]);
    endpoint.release();
    assert_eq!(pending.await.unwrap().0, StatusCode::FORBIDDEN);
    let status = query(&f, json!({"operation":"configuration"})).await;
    assert_eq!(status.0, StatusCode::OK);
    assert_eq!(status.1["result"]["index"]["completed_sources"], 0);
}
