use super::*;
use crate::local_runtime::local_router_with_generation_required;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use tower::ServiceExt;
async fn discover(state: Arc<LocalRuntimeState>, authorized: bool) -> (StatusCode, Value) {
    let mut builder = Request::builder()
        .uri("/api/v1/knowledge/context")
        .header("x-agistack-launch", TOKEN);
    if authorized {
        builder = builder.header("authorization", format!("Bearer {TOKEN}"));
    }
    let response = local_router_with_generation_required(state)
        .oneshot(builder.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}
#[tokio::test]
async fn authenticated_scope_discovery_tracks_sidecar_generation_without_opening_closed_storage() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    assert_eq!(
        discover(Arc::clone(&state), true).await.0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../../contracts/local-route-parity.v1.json"
    ))
    .unwrap();
    let probe = fixture["negative_routes"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["uri"] == "/api/v1/knowledge/context")
        .unwrap();
    assert_eq!(probe["method"], "GET");
    assert_eq!(probe["authority"], "native_session_required");
    for generation in [1, 2] {
        publish(&state, &directory, generation, false).await;
        assert_eq!(
            discover(Arc::clone(&state), false).await.0.as_u16(),
            probe["expected_status"].as_u64().unwrap() as u16
        );
        let result = discover(Arc::clone(&state), true).await;
        assert_eq!(result.0, StatusCode::OK);
        assert_eq!(result.1["contract_version"], "1.0.0");
        let auth = authenticated(&state);
        let lease = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap();
        assert_eq!(
            result.1["scope"],
            serde_json::to_value(operation_scope(&auth, &lease)).unwrap()
        );
        assert_eq!(result.1["scope"]["generation"], generation);
        assert!(!directory.0.exists());
        let closed = super::pull_http_tests::request(
            Arc::clone(&state),
            "/api/v1/knowledge/query",
            json!({"scope":result.1["scope"],"query":{"operation":"list","limit":10,"offset":0}}),
        )
        .await;
        assert_eq!(closed.0, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(closed.1["error"]["code"], "knowledge_release_closed");
        assert!(!directory.0.exists());
    }
    state.platform_plugin_authority_v2.deactivate().await;
}
