//! Native server target for the spike.
//!
//! It wires the portable [`MemoryService`] with in-memory adapters and exposes
//! the Episode -> Memory slice over HTTP. `tokio` is used *here* only; the core
//! crate it depends on is runtime-agnostic.

use std::sync::Arc;

use axum::{
    extract::{Query, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;

use memstack_adapters_mem::{HashEmbedding, InMemoryMemoryRepository, StubLlm, SystemClock};
use memstack_core::{Episode, Memory, MemoryService, SourceType};

#[derive(Deserialize)]
struct IngestRequest {
    project_id: String,
    author_id: String,
    content: String,
}

#[derive(Deserialize)]
struct SearchQuery {
    project_id: String,
    q: String,
    limit: Option<usize>,
}

async fn ingest(
    State(service): State<Arc<MemoryService>>,
    Json(req): Json<IngestRequest>,
) -> Result<Json<Memory>, (StatusCode, String)> {
    let episode = Episode {
        content: req.content,
        source_type: SourceType::Text,
        valid_at_ms: 0,
        name: None,
        project_id: Some(req.project_id.clone()),
        user_id: None,
    };
    service
        .ingest_episode(&req.project_id, &req.author_id, &episode)
        .await
        .map(Json)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

async fn search(
    State(service): State<Arc<MemoryService>>,
    Query(q): Query<SearchQuery>,
) -> Result<Json<Vec<Memory>>, (StatusCode, String)> {
    service
        .search(&q.project_id, &q.q, q.limit.unwrap_or(20))
        .await
        .map(Json)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

#[tokio::main]
async fn main() {
    let service = Arc::new(MemoryService::new(
        Arc::new(InMemoryMemoryRepository::new()),
        Arc::new(StubLlm),
        Arc::new(HashEmbedding::new(8)),
        Arc::new(SystemClock),
    ));

    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/episodes", post(ingest))
        .route("/memories/search", get(search))
        .with_state(service);

    let addr = "127.0.0.1:8088";
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    println!("memstack-core spike server listening on http://{addr}");
    axum::serve(listener, app).await.unwrap();
}
