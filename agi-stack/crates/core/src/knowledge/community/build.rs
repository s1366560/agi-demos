//! Durable, immutable community build inputs and fenced work ownership.
//! There is deliberately no completion API for nonempty builds: semantic
//! output requires a separately reviewed structured submission/audit contract.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use super::{CommunityCandidate, CommunitySnapshot};
use crate::knowledge::{KnowledgeResult, KnowledgeScope};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityBuildRequest {
    pub actor_id: String,
    pub idempotency_key: String,
    pub min_community_size: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommunityBuildState {
    Pending,
    /// Only an empty candidate set may complete in this storage-only batch.
    CompletedEmpty,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityBuildReceipt {
    pub tenant_id: String,
    pub project_id: String,
    pub build_id: String,
    pub graph_digest: String,
    pub candidate_count: u32,
    pub state: CommunityBuildState,
    pub created_at_ms: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityBuildInput {
    pub receipt: CommunityBuildReceipt,
    pub snapshot: CommunitySnapshot,
    /// The membership digest is the candidate ID within this build.
    pub candidates: Vec<CommunityCandidate>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommunityJobState {
    Pending,
    Leased,
    Failed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommunityJobFailure {
    Cancelled,
    WorkerUnavailable,
    ExecutionFailed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityJobStatus {
    pub build_id: String,
    pub candidate_id: String,
    pub state: CommunityJobState,
    pub attempt: u32,
    pub failure: Option<CommunityJobFailure>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommunityJobLease {
    pub tenant_id: String,
    pub project_id: String,
    pub build_id: String,
    pub candidate_id: String,
    pub graph_digest: String,
    pub worker_id: String,
    pub token: String,
    pub attempt: u32,
    pub expires_at_ms: i64,
}

/// Host timestamps are trusted clock values, never renderer-supplied values.
/// Device adapters additionally expose clock callbacks checked under write locks.
#[async_trait]
pub trait CommunityBuildRepository: Send + Sync {
    async fn create_community_build(
        &self,
        scope: &KnowledgeScope,
        request: &CommunityBuildRequest,
        now_ms: i64,
    ) -> KnowledgeResult<CommunityBuildReceipt>;

    async fn community_build(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
    ) -> KnowledgeResult<Option<CommunityBuildInput>>;

    async fn claim_community_job(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        worker_id: &str,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<Option<CommunityJobLease>>;

    async fn renew_community_job(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<CommunityJobLease>;

    async fn fail_community_job(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        failure: CommunityJobFailure,
        now_ms: i64,
    ) -> KnowledgeResult<()>;

    async fn retry_community_job(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        candidate_id: &str,
        expected_attempt: u32,
    ) -> KnowledgeResult<()>;

    async fn community_job_status(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        candidate_id: &str,
    ) -> KnowledgeResult<Option<CommunityJobStatus>>;
}
