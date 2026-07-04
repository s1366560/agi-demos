use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use agistack_core::ports::{CoreError, CoreResult, RerankHit, RerankPort};

use crate::endpoint::Endpoint;

#[derive(Serialize)]
struct RerankRequest<'a> {
    model: &'a str,
    query: &'a str,
    documents: &'a [String],
    #[serde(skip_serializing_if = "Option::is_none")]
    top_n: Option<usize>,
    return_documents: bool,
}

#[derive(Deserialize)]
struct RerankResponse {
    results: Vec<RerankResultWire>,
}

#[derive(Deserialize)]
struct RerankResultWire {
    index: usize,
    // Cohere/Jina/BGE emit `relevance_score`; some servers (vLLM) emit `score`.
    #[serde(default)]
    relevance_score: Option<f32>,
    #[serde(default)]
    score: Option<f32>,
}

/// Reranker adapter over a **Cohere/Jina/BGE-compatible** HTTP `POST /rerank`
/// endpoint (the second stage of hybrid search). `reqwest` keeps it native-only,
/// never in `core`/wasm (ADR-0001), same as [`crate::HttpLlm`]/[`crate::HttpEmbedding`].
pub struct HttpRerank {
    ep: Endpoint,
}

impl HttpRerank {
    /// Point at `base_url` (e.g. `http://localhost:8081` or a Cohere/Jina base)
    /// using cross-encoder `model` (ignored by servers that pin one model).
    pub fn new(base_url: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            ep: Endpoint::new(base_url, model),
        }
    }

    pub fn with_api_key(mut self, key: impl Into<String>) -> Self {
        self.ep.api_key = Some(key.into());
        self
    }
}

#[async_trait]
impl RerankPort for HttpRerank {
    async fn rerank(&self, query: &str, documents: &[String]) -> CoreResult<Vec<RerankHit>> {
        if documents.is_empty() {
            return Ok(Vec::new());
        }
        let body = RerankRequest {
            model: &self.ep.model,
            query,
            documents,
            top_n: None,
            return_documents: false,
        };
        let resp: RerankResponse = self
            .ep
            .post_json("/rerank", &body, CoreError::Rerank)
            .await?;
        let mut hits: Vec<RerankHit> = resp
            .results
            .into_iter()
            .map(|r| RerankHit {
                index: r.index,
                score: r.relevance_score.or(r.score).unwrap_or(0.0),
            })
            .collect();
        // Providers usually pre-sort by relevance; sort defensively (desc).
        hits.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        Ok(hits)
    }
}
