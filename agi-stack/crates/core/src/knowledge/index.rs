//! Provenance-bound vector storage. Provider resolution and semantic queries are
//! separate adapters; this boundary never infers a model or fabricates a vector.
use std::num::NonZeroU32;

use serde::{Deserialize, Serialize};

use super::{processing::ProcessingSource, KnowledgeScope};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IndexProfile {
    pub provider_id: String,
    pub provider_revision: u64,
    /// Digest of the existing credential binding, never the credential itself.
    pub credential_binding_digest: String,
    pub model_id: String,
    /// Established by a real verified response, not a model-name catalogue.
    pub dimensions: NonZeroU32,
    /// Version 1 embeds the exact JSON tuple [1, title, content].
    pub input_contract_version: u32,
    /// Version 1 stores raw finite nonzero f32 output; cosine uses f64 arithmetic.
    pub normalization_version: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IndexBuild {
    pub scope: KnowledgeScope,
    pub build_id: String,
    pub profile: IndexProfile,
}

/// Project selection is independent of the last fully promoted index. Every
/// worker and query carries this version, including when reselecting an old build.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DesiredEmbeddingConfig {
    pub revision: u64,
    pub build: IndexBuild,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IndexSource {
    pub source: ProcessingSource,
    pub audit_attempt: u32,
    pub input_digest: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IndexLease {
    pub config_revision: u64,
    pub build: IndexBuild,
    pub input: IndexSource,
    /// Exact versioned text to send to the verified embedding adapter.
    pub input_text: String,
    pub worker_id: String,
    pub token: String,
    pub attempt: u32,
    pub expires_at_ms: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IndexFailure {
    ProviderUnavailable,
    ProfileChanged,
    InvalidEmbedding,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IndexJobState {
    Pending,
    Leased,
    Completed,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IndexJobStatus {
    pub input: IndexSource,
    pub state: IndexJobState,
    pub attempt: u32,
    pub failure: Option<IndexFailure>,
}

/// Current raw sources are counted independently of their vector coverage.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessingCoverage {
    pub current_sources: usize,
    pub applied_sources: usize,
    pub pending_sources: usize,
    pub failed_sources: usize,
}

/// Coverage is recalculated against current Applied audits on every read. A
/// promoted build can become partial when a source is added or finishes late.
/// This counts only successfully processed sources. Project-level readiness must
/// separately account for pending/failed extraction; this is not that verdict.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IndexCoverage {
    pub current_sources: usize,
    pub completed_sources: usize,
    pub failed_sources: usize,
}
impl IndexCoverage {
    pub fn complete(&self) -> bool {
        self.current_sources == self.completed_sources
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct IndexedVector {
    pub input: IndexSource,
    pub vector: Vec<f32>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct IndexRead {
    pub config_revision: u64,
    pub build: IndexBuild,
    pub coverage: IndexCoverage,
    pub processing: ProcessingCoverage,
    pub vectors: Vec<IndexedVector>,
}

/// Discovery is available before selection or promotion, with extraction counts
/// kept separate from coverage of the selected build.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IndexConfigurationStatus {
    pub configuration: Option<DesiredEmbeddingConfig>,
    pub active_build_id: Option<String>,
    pub processing: ProcessingCoverage,
    pub index: Option<IndexCoverage>,
}
