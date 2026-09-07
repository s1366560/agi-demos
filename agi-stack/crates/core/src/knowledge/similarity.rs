//! Deterministic cosine ordering for already-authorized, current index vectors.
//! The caller must validate the live build/profile and source visibility. This
//! module computes scores; it does not judge relevance or select a fallback.

use super::{
    index::{IndexSource, IndexedVector},
    KnowledgeError, KnowledgeResult,
};

#[derive(Debug, Clone, PartialEq)]
pub struct ScoredIndexSource {
    pub input: IndexSource,
    /// Cosine similarity in [-1, 1], highest first. No relevance cutoff.
    pub score: f64,
}

/// Rank the complete supplied batch, rejecting malformed vectors rather than
/// returning a partially trusted result. Ties use immutable source identity.
/// Provider/model compatibility is established by the caller's IndexBuild.
pub fn rank_index_vectors(
    query: &[f32],
    candidates: &[IndexedVector],
) -> KnowledgeResult<Vec<ScoredIndexSource>> {
    let query_norm = norm(query)?;
    let scope = candidates.first().map(|value| &value.input.source);
    let mut output = Vec::with_capacity(candidates.len());
    for candidate in candidates {
        let source = &candidate.input.source;
        if candidate.vector.len() != query.len()
            || scope.is_some_and(|scope| {
                scope.tenant_id != source.tenant_id || scope.project_id != source.project_id
            })
        {
            return Err(KnowledgeError::InvalidInput);
        }
        let candidate_norm = norm(&candidate.vector)?;
        let dot: f64 = query
            .iter()
            .zip(&candidate.vector)
            .map(|(&a, &b)| f64::from(a) * f64::from(b))
            .sum();
        // f64 products/sums accommodate the full finite f32 range, including
        // subnormals. Clamp only floating-point roundoff at the cosine bounds.
        let score = (dot / query_norm / candidate_norm).clamp(-1.0, 1.0);
        output.push(ScoredIndexSource {
            input: candidate.input.clone(),
            score: if score == 0.0 { 0.0 } else { score },
        });
    }
    output.sort_by(|a, b| {
        b.score.total_cmp(&a.score).then_with(|| {
            let identity = |value: &ScoredIndexSource| {
                (
                    value.input.source.change_sequence,
                    value.input.source.revision,
                    value.input.audit_attempt,
                )
            };
            identity(a)
                .cmp(&identity(b))
                .then_with(|| a.input.source.memory_id.cmp(&b.input.source.memory_id))
                .then_with(|| a.input.input_digest.cmp(&b.input.input_digest))
        })
    });
    Ok(output)
}

fn norm(vector: &[f32]) -> KnowledgeResult<f64> {
    if vector.is_empty() || vector.iter().any(|value| !value.is_finite()) {
        return Err(KnowledgeError::InvalidInput);
    }
    let squared: f64 = vector
        .iter()
        .map(|&value| {
            let value = f64::from(value);
            value * value
        })
        .sum();
    if squared == 0.0 {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(squared.sqrt())
}
