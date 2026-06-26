//! Deterministic hashing embedding — a stand-in for a real embedding model that
//! is pure, offline, and identical across platforms. The same vector is produced
//! on server, device and browser, so similarity tests are reproducible.

use async_trait::async_trait;
use agistack_core::ports::{CoreResult, EmbeddingPort};
use agistack_core::util::fnv1a;

/// Bag-of-words hashed into a fixed-dimension, L2-normalized vector. Because it
/// is normalized, cosine similarity reduces to a dot product (see
/// [`crate::vector::InMemoryVectorIndex`]).
pub struct HashEmbedding {
    dim: usize,
}

impl HashEmbedding {
    pub fn new(dim: usize) -> Self {
        assert!(dim > 0, "embedding dim must be > 0");
        Self { dim }
    }
}

#[async_trait]
impl EmbeddingPort for HashEmbedding {
    async fn embed(&self, text: &str) -> CoreResult<Vec<f32>> {
        let mut v = vec![0f32; self.dim];
        for token in text.split_whitespace() {
            let h = fnv1a(&token.to_lowercase());
            v[(h as usize) % self.dim] += 1.0;
        }
        let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        if norm > 0.0 {
            for x in &mut v {
                *x /= norm;
            }
        }
        Ok(v)
    }
}
