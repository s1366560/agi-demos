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

/// Character **n-gram** hashing embedding — a higher-fidelity, still-offline
/// stand-in that captures sub-word signal [`HashEmbedding`] misses. Each word
/// contributes both a whole-token feature and its space-padded character n-grams
/// (so `"memory"` and `"memories"` share most trigrams and land close in cosine
/// space). Higher `dim` reduces hash collisions; the result is L2-normalized so
/// cosine reduces to a dot product. Pure and identical across server/device/web,
/// which keeps the on-device vector bench reproducible (`04 §2`, `05 §3`).
pub struct NgramHashEmbedding {
    dim: usize,
    n: usize,
}

impl NgramHashEmbedding {
    /// `dim` buckets (e.g. 256), char n-gram width `n` (e.g. 3). A real device
    /// build swaps this for a quantized on-device model behind the same port.
    pub fn new(dim: usize, n: usize) -> Self {
        assert!(dim > 0, "embedding dim must be > 0");
        assert!(n > 0, "n-gram width must be > 0");
        Self { dim, n }
    }
}

#[async_trait]
impl EmbeddingPort for NgramHashEmbedding {
    async fn embed(&self, text: &str) -> CoreResult<Vec<f32>> {
        let mut v = vec![0f32; self.dim];
        let lower = text.to_lowercase();
        for token in lower.split_whitespace() {
            // Whole-token feature (word-level signal).
            v[(fnv1a(token) as usize) % self.dim] += 1.0;
            // Space-padded character n-grams (sub-word signal). Padding marks
            // word boundaries so prefixes/suffixes are distinguishable.
            let chars: Vec<char> = format!(" {token} ").chars().collect();
            if chars.len() >= self.n {
                for window in chars.windows(self.n) {
                    let gram: String = window.iter().collect();
                    v[(fnv1a(&gram) as usize) % self.dim] += 1.0;
                }
            }
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

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

    fn cosine(a: &[f32], b: &[f32]) -> f32 {
        a.iter().zip(b).map(|(x, y)| x * y).sum()
    }

    #[test]
    fn ngram_embedding_places_related_text_closer() {
        let e = NgramHashEmbedding::new(256, 3);
        let q = block_on(e.embed("memory graph")).unwrap();
        let near = block_on(e.embed("memories graph")).unwrap();
        let far = block_on(e.embed("quarterly revenue forecast")).unwrap();
        assert!(
            cosine(&q, &near) > cosine(&q, &far),
            "shared sub-words should win: near={} far={}",
            cosine(&q, &near),
            cosine(&q, &far)
        );
        // Normalized vectors: self-similarity is ~1.
        assert!((cosine(&q, &q) - 1.0).abs() < 1e-4);
    }
}
