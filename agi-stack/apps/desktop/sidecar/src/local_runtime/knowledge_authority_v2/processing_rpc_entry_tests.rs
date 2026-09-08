use super::*;
use crate::local_runtime::{
    local_router, local_router_with_generation_required, workspace_core_bridge,
};
use axum::{
    body::{to_bytes, Body},
    extract::Path,
    http::{Request, StatusCode},
    routing::get,
};
use tower::ServiceExt;

#[tokio::test]
async fn public_extraction_runs_verified_workspace_policy_and_returns_only_typed_receipt() {
    let f = Fixture::new().await;
    let scope = operation_scope(&f.auth, &f.operation._lease);
    let body = json!({"scope":scope,"command":{"operation":"process_one","workspace_id":"explicit-workspace"}});
    let make_request = |body: &Value| {
        Request::builder()
            .method("POST")
            .uri("/api/v1/knowledge/processing-command")
            .header("authorization", format!("Bearer {TOKEN}"))
            .header("x-agistack-launch", TOKEN)
            .header("content-type", "application/json")
            .body(Body::from(body.to_string()))
            .unwrap()
    };
    let rejected = local_router_with_generation_required(f.state.clone())
        .oneshot(make_request(&body))
        .await
        .unwrap();
    assert_eq!(rejected.status(), StatusCode::FORBIDDEN);
    assert!(f
        .repo()
        .processing_audit_durable(&f.operation.scope, &f.source, 1)
        .unwrap()
        .is_none());
    let endpoint = Endpoint::new(&f, action(&f.source)).await;
    let configured=local_router(f.state.clone()).oneshot(Request::builder().method("PUT").uri("/api/v1/llm-providers/local-runtime")
        .header("authorization",format!("Bearer {TOKEN}")).header("x-agistack-launch",TOKEN)
        .header("content-type","application/json")
        .body(Body::from(json!({"provider_type":"openai_compatible","base_url":endpoint.base,"auth_method":"none","llm_model":"fixture-model","allowed_models":["fixture-model"],"is_active":true,"expected_revision":0}).to_string())).unwrap()).await.unwrap();
    assert_eq!(configured.status(), StatusCode::OK);
    let app=Router::new().route("/api/v1/tenants/:tenant/projects/:project/workspaces/:workspace",get(|Path((tenant,project,workspace)):Path<(String,String,String)>|async move {Json(json!({"id":workspace,"tenant_id":tenant,"project_id":project}))}))
        .route("/api/v1/tenants/:tenant/projects/:project/workspaces/:workspace/agent-policy",get(|Path((tenant,project,workspace)):Path<(String,String,String)>|async move {Json(json!({"workspace_id":workspace,"tenant_id":tenant,"project_id":project,"roles":{"default":{"provider_id":"local-runtime","model_id":"fixture-model"},"fast":null,"coding":null,"vision":null},"fallbacks":[]}))}));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}/", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    workspace_core_bridge::install_authority(
        &f.state,
        base,
        "fixture-service".into(),
        "fixture-registry".into(),
        "fixture-webhook".into(),
        "fixture-event".into(),
    )
    .unwrap();
    let state = f.state.clone();
    let request = make_request(&body);
    let pending = tokio::spawn(async move {
        local_router_with_generation_required(state)
            .oneshot(request)
            .await
            .unwrap()
    });
    endpoint.wait().await;
    endpoint.release.notify_one();
    let response = pending.await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let result: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(result["result"]["receipt"]["source"], json!(f.source));
    assert_eq!(result["result"]["receipt"]["status"], "applied");
    assert!(result["result"]["receipt"]["failure"].is_null());
    assert_eq!(f.audit().invocation.provider_id, "local-runtime");
    assert!(matches!(
        f.audit().outcome,
        Some(ProcessingAuditOutcome::Applied { .. })
    ));
    server.abort();
}
