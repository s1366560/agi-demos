use std::{path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Method, Request, StatusCode},
    response::Response,
};
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

struct SearchTestRuntime {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for SearchTestRuntime {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn test_runtime(credential: &str) -> SearchTestRuntime {
    let root = std::env::temp_dir().join(format!("agistack-local-search-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create test workspace");
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.clone(),
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    let conversation = LocalConversation {
        id: "local-search-conversation".to_string(),
        project_id: "local-project".to_string(),
        tenant_id: "local".to_string(),
        title: "Local Search".to_string(),
        workspace_id: Some("local-workspace".to_string()),
        capability_mode: ConversationCapabilityMode::Code,
        current_mode: ConversationRunMode::Build,
        created_at: "2026-07-27T09:00:00Z".to_string(),
        updated_at: "2026-07-27T10:00:00Z".to_string(),
    };
    state
        .session_store
        .insert_conversation(&conversation)
        .expect("insert search conversation");
    state
        .session_store
        .append_timeline(
            &conversation.id,
            &json!({
                "id": "local-search-message",
                "type": "user_message",
                "content": "Investigate the pipeline race",
                "created_at": "2026-07-27T09:15:00Z",
                "tags": ["urgent", "pipeline"],
            }),
        )
        .expect("insert searchable message");
    state
        .session_store
        .append_timeline(
            &conversation.id,
            &json!({
                "id": "local-search-result",
                "type": "assistant_message",
                "content": "The fixture now owns one runner per job",
                "created_at": "2026-07-27T09:45:00Z",
                "tags": ["verified"],
            }),
        )
        .expect("insert second searchable message");
    SearchTestRuntime { root, state }
}

fn request(method: Method, uri: &str, credential: &str, body: Option<Value>) -> Request<Body> {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential);
    if body.is_some() {
        builder = builder.header("content-type", "application/json");
    }
    builder
        .body(
            body.map(|body| Body::from(serde_json::to_vec(&body).expect("serialize request")))
                .unwrap_or_else(Body::empty),
        )
        .expect("search request")
}

async fn response_json(response: Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}

#[tokio::test]
async fn local_search_backfills_timeline_and_serves_keyword_temporal_and_faceted_contracts() {
    let credential = "local-search-secret";
    let runtime = test_runtime(credential);
    let app = local_router(Arc::clone(&runtime.state));

    let capability = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/search-enhanced/capabilities",
            credential,
            None,
        ))
        .await
        .expect("capability response");
    assert_eq!(capability.status(), StatusCode::OK);
    let capability = response_json(capability).await;
    assert_eq!(capability["mode"], "keyword_degraded");
    assert_eq!(capability["reason_code"], "local_embeddings_unavailable");
    assert_eq!(capability["tenant_id"], "local");
    assert_eq!(capability["project_id"], "local-project");
    assert_eq!(
        capability["supported_search_types"],
        json!(["advanced", "temporal", "faceted"])
    );

    let advanced = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/search-enhanced/advanced",
            credential,
            Some(json!({
                "query": "pipeline race",
                "strategy": "COMBINED_HYBRID_SEARCH_RRF",
                "focal_node_uuid": null,
                "reranker": null,
                "limit": 20,
                "tenant_id": "local",
                "project_id": "local-project",
            })),
        ))
        .await
        .expect("advanced response");
    assert_eq!(advanced.status(), StatusCode::OK);
    let advanced = response_json(advanced).await;
    assert_eq!(advanced["search_type"], "advanced");
    assert_eq!(advanced["total"], 1);
    assert_eq!(advanced["results"][0]["uuid"], "local-search-message");
    assert_eq!(advanced["results"][0]["source"], "desktop_timeline");

    let temporal = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/search-enhanced/temporal",
            credential,
            Some(json!({
                "query": "runner",
                "since": "2026-07-27T09:30:00Z",
                "until": "2026-07-27T10:00:00Z",
                "limit": 20,
                "tenant_id": "local",
                "project_id": "local-project",
            })),
        ))
        .await
        .expect("temporal response");
    assert_eq!(temporal.status(), StatusCode::OK);
    assert_eq!(response_json(temporal).await["total"], 1);

    let faceted = app
        .oneshot(request(
            Method::POST,
            "/api/v1/search-enhanced/faceted",
            credential,
            Some(json!({
                "query": "pipeline",
                "entity_types": ["user_message"],
                "tags": ["urgent"],
                "since": null,
                "limit": 20,
                "offset": 0,
                "tenant_id": "local",
                "project_id": "local-project",
            })),
        ))
        .await
        .expect("faceted response");
    assert_eq!(faceted.status(), StatusCode::OK);
    let faceted = response_json(faceted).await;
    assert_eq!(faceted["total"], 1);
    assert_eq!(faceted["facets"]["entity_types"]["user_message"], 1);
}

#[tokio::test]
async fn local_search_fails_closed_for_graph_authority_scope_and_malformed_payloads() {
    let credential = "local-search-fail-closed-secret";
    let runtime = test_runtime(credential);
    let app = local_router(Arc::clone(&runtime.state));
    let graph_body = json!({
        "start_entity_uuid": "entity-1",
        "max_depth": 2,
        "relationship_types": [],
        "limit": 20,
        "tenant_id": "local",
        "project_id": "local-project",
    });

    let graph = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/search-enhanced/graph-traversal",
            credential,
            Some(graph_body.clone()),
        ))
        .await
        .expect("graph response");
    assert_eq!(graph.status(), StatusCode::NOT_IMPLEMENTED);
    assert_eq!(
        response_json(graph).await["reason_code"],
        "local_structured_graph_projection_unavailable"
    );

    let mut wrong_scope_body = graph_body.clone();
    wrong_scope_body["project_id"] = json!("other-project");
    let wrong_scope = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/search-enhanced/graph-traversal",
            credential,
            Some(wrong_scope_body),
        ))
        .await
        .expect("scope response");
    assert_eq!(wrong_scope.status(), StatusCode::FORBIDDEN);

    let malformed = app
        .oneshot(request(
            Method::POST,
            "/api/v1/search-enhanced/advanced",
            credential,
            Some(json!({
                "query": "pipeline",
                "strategy": "keyword",
                "focal_node_uuid": null,
                "reranker": null,
                "limit": 20,
                "tenant_id": "local",
                "project_id": "local-project",
                "unexpected": true,
            })),
        ))
        .await
        .expect("malformed response");
    assert_eq!(malformed.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        response_json(malformed).await["reason_code"],
        "local_search_payload_invalid"
    );
}
