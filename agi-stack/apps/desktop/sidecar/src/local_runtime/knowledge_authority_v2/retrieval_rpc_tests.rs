use super::*;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use tower::ServiceExt;

#[path = "graph_source_rpc_tests.rs"]
mod graph_source;

async fn query(f: &Fixture, query: Value) -> (StatusCode, Value) {
    let scope = operation_scope(&f.auth, &f.operation._lease);
    let response = crate::local_runtime::local_router_with_generation_required(f.state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/knowledge/processing-query")
                .header("authorization", format!("Bearer {TOKEN}"))
                .header("x-agistack-launch", TOKEN)
                .header("content-type", "application/json")
                .body(Body::from(json!({"scope":scope,"query":query}).to_string()))
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

#[tokio::test]
async fn public_graph_pages_preserve_exact_source_references_and_reject_cross_query_cursors() {
    let f = Fixture::new("viewer").await;
    let repo = f.operation.authority.repository().unwrap();
    let mut memory = repo
        .get(&f.operation.scope, &f.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    memory.id = "second-source".into();
    repo.create(&f.operation.scope, memory.clone())
        .await
        .unwrap();
    let lease = repo
        .claim(&f.operation.scope, "fixture-extractor", 100, 100)
        .await
        .unwrap()
        .unwrap();
    let old = repo
        .processing_audit_durable(&f.operation.scope, &f.source, 1)
        .unwrap()
        .unwrap();
    let mut invocation = old.invocation;
    invocation.input.source = lease.source.clone();
    repo.begin_processing_audit_durable(&f.operation.scope, &lease, invocation, 100)
        .unwrap();
    let Some(ProcessingAuditOutcome::Applied { mut submission }) = old.outcome else {
        panic!("applied fixture")
    };
    submission.source = lease.source.clone();
    repo.finish_processing_audit_durable(
        &f.operation.scope,
        &lease,
        ProcessingAuditOutcome::Applied { submission },
        101,
        1,
    )
    .unwrap();
    let first = query(&f, json!({"operation":"entities","request":{"limit":1}})).await;
    assert_eq!(first.0, StatusCode::OK);
    assert_eq!(first.1["result"]["items"].as_array().unwrap().len(), 1);
    assert_eq!(first.1["result"]["items"][0]["entity"]["name"], "Knowledge");
    let cursor = first.1["result"]["next_cursor"].clone();
    assert!(cursor.is_object());
    let second = query(
        &f,
        json!({"operation":"entities","request":{"limit":1,"cursor":cursor}}),
    )
    .await;
    assert_eq!(second.0, StatusCode::OK);
    assert_ne!(
        first.1["result"]["items"][0]["reference"]["source"],
        second.1["result"]["items"][0]["reference"]["source"]
    );
    assert!(second.1["result"]["next_cursor"].is_null());
    assert_eq!(
        query(
            &f,
            json!({"operation":"relationships","request":{"limit":1,"cursor":cursor}})
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let graph = query(
        &f,
        json!({"operation":"relationships","request":{"limit":2}}),
    )
    .await;
    assert_eq!(graph.0, StatusCode::OK);
    assert_eq!(graph.1["result"]["items"].as_array().unwrap().len(), 2);
    for edge in graph.1["result"]["items"].as_array().unwrap() {
        assert_eq!(edge["source_entity"]["source"], edge["source"]);
        assert_eq!(edge["target_entity"]["source"], edge["source"]);
    }
    let literal = query(
        &f,
        json!({"operation":"text","literal":memory.content,"request":{"limit":2}}),
    )
    .await;
    assert_eq!(literal.0, StatusCode::OK);
    assert_eq!(literal.1["result"]["items"].as_array().unwrap().len(), 2);
    repo.delete(&f.operation.scope, &f.source.memory_id, 1)
        .await
        .unwrap();
    let live = query(&f, json!({"operation":"entities","request":{"limit":2}})).await;
    assert_eq!(live.1["result"]["items"].as_array().unwrap().len(), 1);
    assert_eq!(
        live.1["result"]["items"][0]["reference"]["source"]["memory_id"],
        "second-source"
    );
}
