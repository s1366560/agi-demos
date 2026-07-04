use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use agistack_core::ports::{CoreError, CoreResult, EmbeddingPort};

use crate::endpoint::Endpoint;

#[derive(Serialize)]
struct EmbeddingRequest {
    model: String,
    input: String,
}

#[derive(Deserialize)]
struct EmbeddingResponse {
    data: Vec<EmbeddingData>,
}

#[derive(Deserialize)]
struct EmbeddingData {
    embedding: Vec<f32>,
}

/// Embedding adapter over an HTTP `/embeddings` API.
pub struct HttpEmbedding {
    ep: Endpoint,
}

impl HttpEmbedding {
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
impl EmbeddingPort for HttpEmbedding {
    async fn embed(&self, text: &str) -> CoreResult<Vec<f32>> {
        let body = EmbeddingRequest {
            model: self.ep.model.clone(),
            input: text.to_string(),
        };
        let resp: EmbeddingResponse = self
            .ep
            .post_json("/embeddings", &body, CoreError::Embedding)
            .await?;
        resp.data
            .into_iter()
            .next()
            .map(|d| d.embedding)
            .ok_or_else(|| CoreError::Embedding("no data in embedding response".into()))
    }
}
