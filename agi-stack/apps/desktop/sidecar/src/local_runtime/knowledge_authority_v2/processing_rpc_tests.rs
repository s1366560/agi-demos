use super::*;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use tower::ServiceExt;

#[path = "processing_rpc_admission_tests.rs"]
mod admission;

async fn request(
    state: Arc<LocalRuntimeState>,
    path: &str,
    body: Value,
    authenticated: bool,
) -> (StatusCode, Value) {
    let mut request = Request::builder()
        .method("POST")
        .uri(path)
        .header("content-type", "application/json")
        .header("x-agistack-launch", TOKEN);
    if authenticated {
        request = request.header("authorization", format!("Bearer {TOKEN}"));
    }
    let response = crate::local_runtime::local_router_with_generation_required(state)
        .oneshot(
            request
                .body(Body::from(serde_json::to_vec(&body).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}
async fn query(f: &Fixture, query: Value) -> (StatusCode, Value) {
    request(
        f.state.clone(),
        "/api/v1/knowledge/processing-query",
        json!({"scope":operation_scope(&f.auth,&f.operation._lease),"query":query}),
        true,
    )
    .await
}
async fn command(f: &Fixture, command: Value) -> (StatusCode, Value) {
    request(
        f.state.clone(),
        "/api/v1/knowledge/processing-command",
        json!({"scope":operation_scope(&f.auth,&f.operation._lease),"command":command}),
        true,
    )
    .await
}
fn configure(route: &EmbeddingRoute, id: &str, expected: Option<u64>) -> Value {
    json!({"operation":"configure_embedding","build_id":id,"provider_id":route.provider_id,
        "provider_revision":route.provider_revision,"model_id":route.model_id,"expected_config_revision":expected})
}

#[tokio::test]
async fn public_config_probe_index_promote_and_query_use_only_server_stored_profiles() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let initial = query(&f, json!({"operation":"configuration"})).await;
    assert_eq!(initial.0, StatusCode::OK);
    assert!(initial.1["result"]["configuration"].is_null());
    assert_eq!(initial.1["result"]["processing"]["applied_sources"], 1);
    let selected = command(&f, configure(&route, "a", None)).await;
    assert_eq!(selected.0, StatusCode::OK);
    assert_eq!(selected.1["result"]["configuration"]["revision"], 1);
    assert_eq!(endpoint.state.requests.lock().unwrap().len(), 1);
    assert!(!selected.1.to_string().contains("credential_binding_digest"));
    let building = query(&f, json!({"operation":"configuration"})).await;
    assert_eq!(building.1["result"]["index"]["current_sources"], 1);
    assert_eq!(building.1["result"]["index"]["completed_sources"], 0);
    assert!(building.1["result"]["active_build_id"].is_null());
    let indexed = command(
        &f,
        json!({"operation":"index_one","build_id":"a","config_revision":1}),
    )
    .await;
    assert_eq!(indexed.0, StatusCode::OK);
    assert_eq!(indexed.1["result"]["receipt"]["status"], "indexed");
    assert_eq!(command(&f,json!({"operation":"promote_index","build_id":"a","config_revision":1,"expected_active_build_id":null})).await.0,StatusCode::OK);
    let found=query(&f,json!({"operation":"semantic","build_id":"a","config_revision":1,"query":"query","limit":10})).await;
    assert_eq!(found.0, StatusCode::OK);
    assert_eq!(found.1["result"]["hits"].as_array().unwrap().len(), 1);
    assert_eq!(
        found.1["result"]["configuration"]["model_id"],
        route.model_id
    );
    assert_eq!(
        found.1["result"]["hits"][0]["input"]["source"],
        json!(f.source)
    );
    assert_eq!(endpoint.state.requests.lock().unwrap().len(), 3);
    assert!(endpoint.state.credential_seen.load(Ordering::SeqCst));
    let idle = command(
        &f,
        json!({"operation":"index_one","build_id":"a","config_revision":1}),
    )
    .await;
    assert_eq!(idle.0, StatusCode::OK);
    assert!(idle.1["result"]["receipt"].is_null());
    assert_eq!(
        command(&f, configure(&route, "lost-response-retry", None))
            .await
            .0,
        StatusCode::CONFLICT
    );
    assert_eq!(endpoint.state.requests.lock().unwrap().len(), 3);
}

#[tokio::test]
async fn public_model_switch_while_semantic_http_waits_discards_result_without_old_active_fallback()
{
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    assert_eq!(
        command(&f, configure(&route, "a", None)).await.0,
        StatusCode::OK
    );
    command(
        &f,
        json!({"operation":"index_one","build_id":"a","config_revision":1}),
    )
    .await;
    command(&f,json!({"operation":"promote_index","build_id":"a","config_revision":1,"expected_active_build_id":null})).await;
    let route_b = EmbeddingRoute {
        model_id: "other-embedding-model".into(),
        ..route.clone()
    };
    f.operation
        .prepare_index_build(&f.state, &f.auth, &route_b, "b")
        .await
        .unwrap();
    endpoint.pause();
    let state = f.state.clone();
    let scope = operation_scope(&f.auth, &f.operation._lease);
    let pending = tokio::spawn(async move {
        request(state,"/api/v1/knowledge/processing-query",json!({"scope":scope,"query":{"operation":"semantic","build_id":"a","config_revision":1,"query":"query","limit":10}}),true).await
    });
    endpoint.entered().await;
    assert_eq!(
        command(
            &f,
            json!({"operation":"select_embedding","build_id":"b","expected_config_revision":1})
        )
        .await
        .0,
        StatusCode::OK
    );
    endpoint.release();
    let rejected = pending.await.unwrap();
    assert_eq!(rejected.0, StatusCode::CONFLICT);
    assert_eq!(rejected.1["error"]["code"], "knowledge_revision_conflict");
    let status = query(&f, json!({"operation":"configuration"})).await;
    assert_eq!(status.1["result"]["active_build_id"], "a");
    assert_eq!(status.1["result"]["configuration"]["build_id"], "b");
    assert_eq!(status.1["result"]["index"]["completed_sources"], 0);
    let requests = endpoint.state.requests.lock().unwrap().len();
    for (id, revision) in [("a", 1), ("b", 2)] {
        assert_eq!(query(&f,json!({"operation":"semantic","build_id":id,"config_revision":revision,"query":"query","limit":10})).await.0,StatusCode::CONFLICT);
    }
    assert_eq!(endpoint.state.requests.lock().unwrap().len(), requests);
}

#[tokio::test]
async fn public_index_failure_requires_exact_attempt_retry_and_does_not_report_completion() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    assert_eq!(
        command(&f, configure(&route, "a", None)).await.0,
        StatusCode::OK
    );
    *endpoint.state.response.lock().unwrap() =
        Some(json!({"model":"wrong-model","data":[{"index":0,"embedding":[1.0,0.0]}]}));
    let failed = command(
        &f,
        json!({"operation":"index_one","build_id":"a","config_revision":1}),
    )
    .await;
    assert_eq!(failed.0, StatusCode::OK);
    let receipt = &failed.1["result"]["receipt"];
    assert_eq!(receipt["status"], "failed");
    assert_eq!(receipt["failure"], "invalid_embedding");
    let status = query(&f, json!({"operation":"configuration"})).await;
    assert_eq!(status.1["result"]["index"]["failed_sources"], 1);
    assert_eq!(status.1["result"]["index"]["completed_sources"], 0);
    assert_eq!(command(&f,json!({"operation":"retry_index","build_id":"a","config_revision":1,"input":receipt["input"],"expected_attempt":2})).await.0,StatusCode::CONFLICT);
    assert_eq!(command(&f,json!({"operation":"retry_index","build_id":"a","config_revision":1,"input":receipt["input"],"expected_attempt":1})).await.0,StatusCode::OK);
    *endpoint.state.response.lock().unwrap() = None;
    let retried = command(
        &f,
        json!({"operation":"index_one","build_id":"a","config_revision":1}),
    )
    .await;
    assert_eq!(retried.1["result"]["receipt"]["status"], "indexed");
    assert_eq!(retried.1["result"]["receipt"]["attempt"], 2);
}

#[test]
fn generated_requests_consume_all_shared_crud_sync_and_processing_fixtures() {
    use super::super::super::contracts::*;
    fn parse<T: serde::de::DeserializeOwned + serde::Serialize>(value: &Value) {
        let parsed: T = serde_json::from_value(value.clone()).unwrap();
        assert_eq!(
            serde_json::to_value(parsed).unwrap()["scope"],
            value["scope"]
        );
    }
    let fixture: Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../../shared/fixtures/native-knowledge.v1.json"
    )))
    .unwrap();
    for case in fixture["requests"].as_array().unwrap() {
        let value = &case["request"];
        match case["path"].as_str().unwrap() {
            "/api/v1/knowledge/query" => parse::<QueryRequest>(value),
            "/api/v1/knowledge/mutations" => parse::<MutationRequest>(value),
            "/api/v1/knowledge/sync-link" => parse::<SyncLinkRequest>(value),
            "/api/v1/knowledge/sync-push" => parse::<PushRequest>(value),
            "/api/v1/knowledge/sync-pull" => parse::<PullRequest>(value),
            "/api/v1/knowledge/sync-resolve-push" => parse::<ResolveRequest>(value),
            "/api/v1/knowledge/sync-resume-resolution" => parse::<ResumeRequest>(value),
            "/api/v1/knowledge/sync-reconcile-resolution" => parse::<ReconcileRequest>(value),
            "/api/v1/knowledge/sync-cloud-query" => parse::<CloudQueryRequest>(value),
            "/api/v1/knowledge/sync-resolve-pull" => parse::<ResolutionRequest>(value),
            "/api/v1/knowledge/processing-query" => parse::<ProcessingQueryRequest>(value),
            "/api/v1/knowledge/processing-command" => parse::<ProcessingCommandRequest>(value),
            path => panic!("unhandled fixture {path}"),
        }
    }
}

#[path = "capability_rpc_tests.rs"]
mod capability_rpc_tests;
