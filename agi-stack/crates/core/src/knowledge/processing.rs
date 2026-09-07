//! Durable, revision-bound processing storage. Extraction and semantic judgments
//! belong to a later agent worker; these types describe storage effects only.

pub mod audit;
pub mod worker;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use super::{KnowledgeResult, KnowledgeScope};
use crate::model::Entity;

/// Exact accepted source, including its ownership and immutable change identity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProcessingSource {
    pub tenant_id: String,
    pub project_id: String,
    pub memory_id: String,
    pub revision: u32,
    pub change_sequence: u64,
}

/// The stored token and attempt fence every worker transition. Caller timestamps
/// are supplied by the trusted host clock; the database deadline is authoritative.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessingLease {
    pub source: ProcessingSource,
    pub worker_id: String,
    pub token: String,
    pub attempt: u32,
    pub expires_at_ms: i64,
}

/// Endpoints refer to explicit positions in `entities`, avoiding name resolution
/// or semantic entity merging inside the storage adapter.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProcessingRelationship {
    pub source_index: u32,
    pub target_index: u32,
    pub relation_type: String,
    pub fact: String,
    pub score: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProcessingProjection {
    pub entities: Vec<Entity>,
    pub relationships: Vec<ProcessingRelationship>,
}

/// Deletion is completed synchronously with the accepted source change and
/// never leased to an extraction worker.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "projection", rename_all = "snake_case")]
pub enum ProcessingResult {
    Projection(ProcessingProjection),
    Deleted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessingState {
    Pending,
    Leased,
    Completed,
    Failed,
    Superseded,
}

/// Safe codes only: provider responses, credentials and arbitrary error strings
/// cannot be persisted through the processing boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessingFailure {
    ModelUnconfigured,
    ProviderUnavailable,
    InvalidExtraction,
    Cancelled,
    ProcessingFailed,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ProcessingStatus {
    pub source: ProcessingSource,
    pub state: ProcessingState,
    pub attempt: u32,
    pub failure: Option<ProcessingFailure>,
    pub result: Option<ProcessingResult>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DerivedProjection {
    pub source: ProcessingSource,
    pub projection: ProcessingProjection,
}

/// Processing changes neither portable Memory revisions nor sync outbox state.
/// Old completed receipts remain available when a newer source supersedes them;
/// only the projection read represents the currently valid derived output.
#[async_trait]
pub trait ProcessingRepository: Send + Sync {
    /// Claim pending work or reclaim an expired lease, atomically. Failed work
    /// is excluded until explicitly retried; deletion receipts are never leased.
    async fn claim(
        &self,
        scope: &KnowledgeScope,
        worker_id: &str,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<Option<ProcessingLease>>;
    /// Extend an unexpired, current lease. Reclamation invalidates the old token.
    async fn renew(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<ProcessingLease>;
    async fn complete(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        projection: ProcessingProjection,
        now_ms: i64,
    ) -> KnowledgeResult<()>;
    async fn fail(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        failure: ProcessingFailure,
        now_ms: i64,
    ) -> KnowledgeResult<()>;
    /// Only the exact failed attempt of the current source can be retried.
    async fn retry(
        &self,
        scope: &KnowledgeScope,
        source: &ProcessingSource,
        expected_attempt: u32,
    ) -> KnowledgeResult<()>;
    async fn processing_status(
        &self,
        scope: &KnowledgeScope,
        source: &ProcessingSource,
    ) -> KnowledgeResult<Option<ProcessingStatus>>;
    /// Revalidates current source ownership/revision even if triggers were lost.
    async fn projection(
        &self,
        scope: &KnowledgeScope,
        memory_id: &str,
    ) -> KnowledgeResult<Option<DerivedProjection>>;
}
