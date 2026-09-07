use std::{fmt, num::NonZeroUsize, time::Duration};

use serde::{Deserialize, Serialize};

use super::HttpEmbedding;

/// One nonzero finite vector whose model and single-input response index were checked.
/// Provider identity, credential revision and source revision belong to the caller's scope.
#[derive(Clone, Debug, PartialEq)]
pub struct VerifiedEmbedding {
    model: String,
    dimensions: NonZeroUsize,
    vector: Vec<f32>,
}

impl VerifiedEmbedding {
    pub fn model(&self) -> &str {
        &self.model
    }

    pub fn dimensions(&self) -> NonZeroUsize {
        self.dimensions
    }

    pub fn vector(&self) -> &[f32] {
        &self.vector
    }

    pub fn into_vector(self) -> Vec<f32> {
        self.vector
    }
}

/// Safe failure categories; never contain URLs, credentials, input or provider response text.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VerifiedEmbeddingError {
    InvalidInput,
    Transport,
    HttpStatus(u16),
    InvalidResponse,
    ModelMismatch,
    DimensionMismatch,
    InvalidVector,
}

impl fmt::Display for VerifiedEmbeddingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let code = match self {
            Self::InvalidInput => "embedding_invalid_input",
            Self::Transport => "embedding_transport_failed",
            Self::HttpStatus(_) => "embedding_http_status",
            Self::InvalidResponse => "embedding_invalid_response",
            Self::ModelMismatch => "embedding_model_mismatch",
            Self::DimensionMismatch => "embedding_dimension_mismatch",
            Self::InvalidVector => "embedding_invalid_vector",
        };
        formatter.write_str(code)
    }
}

impl std::error::Error for VerifiedEmbeddingError {}

#[derive(Serialize)]
struct Request<'a> {
    model: &'a str,
    input: &'a str,
    encoding_format: &'static str,
}

#[derive(Deserialize)]
struct Response {
    model: String,
    data: Vec<Vector>,
}

#[derive(Deserialize)]
struct Vector {
    index: usize,
    embedding: Vec<f32>,
}

impl HttpEmbedding {
    /// Request a vector suitable for a provenance-bound index, without fallback.
    ///
    /// The response must report exactly the configured model (aliases are not inferred)
    /// and exactly one item at index zero. `None` observes dimensions for a new index;
    /// subsequent documents and queries should supply the established dimension.
    /// Redirects are rejected. The request has a 30-second ceiling; callers may impose
    /// a shorter operation deadline by cancelling this future.
    ///
    /// # Errors
    /// Returns a safe typed error for invalid input, transport/HTTP failure or an
    /// invalid model/index/vector/dimension response. No provider text is retained.
    pub async fn embed_verified(
        &self,
        text: &str,
        expected_dimensions: Option<NonZeroUsize>,
    ) -> Result<VerifiedEmbedding, VerifiedEmbeddingError> {
        let mut url = reqwest::Url::parse(&self.ep.base_url)
            .map_err(|_| VerifiedEmbeddingError::InvalidInput)?;
        if text.is_empty()
            || self.ep.model.is_empty()
            || self.ep.model.trim() != self.ep.model
            || !matches!(url.scheme(), "http" | "https")
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
        {
            return Err(VerifiedEmbeddingError::InvalidInput);
        }
        url.set_path(&format!("{}/embeddings", url.path().trim_end_matches('/')));
        // This stricter client is independent of the legacy port's redirect policy.
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| VerifiedEmbeddingError::Transport)?;
        let mut request = client.post(url).json(&Request {
            model: &self.ep.model,
            input: text,
            encoding_format: "float",
        });
        if let Some(key) = &self.ep.api_key {
            request = request.bearer_auth(key);
        }
        let response = request
            .send()
            .await
            .map_err(|_| VerifiedEmbeddingError::Transport)?;
        if !response.status().is_success() {
            return Err(VerifiedEmbeddingError::HttpStatus(
                response.status().as_u16(),
            ));
        }
        let response: Response = response
            .json()
            .await
            .map_err(|_| VerifiedEmbeddingError::InvalidResponse)?;
        if response.model != self.ep.model {
            return Err(VerifiedEmbeddingError::ModelMismatch);
        }
        let [vector]: [Vector; 1] = response
            .data
            .try_into()
            .map_err(|_| VerifiedEmbeddingError::InvalidResponse)?;
        if vector.index != 0 {
            return Err(VerifiedEmbeddingError::InvalidResponse);
        }
        let dimensions = NonZeroUsize::new(vector.embedding.len())
            .ok_or(VerifiedEmbeddingError::InvalidVector)?;
        if vector.embedding.iter().any(|value| !value.is_finite())
            || !vector.embedding.iter().any(|value| *value != 0.0)
        {
            return Err(VerifiedEmbeddingError::InvalidVector);
        }
        if expected_dimensions.is_some_and(|expected| expected != dimensions) {
            return Err(VerifiedEmbeddingError::DimensionMismatch);
        }
        Ok(VerifiedEmbedding {
            model: response.model,
            dimensions,
            vector: vector.embedding,
        })
    }
}
