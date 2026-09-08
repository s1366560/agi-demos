//! Audited community outputs and explicit, revision-fenced project selection.
//! Provider credentials and raw rejected responses have no storage field.

use serde::{Deserialize, Serialize};

use super::{worker::*, CommunityCandidate};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityInvocation {
    pub agent_id: String,
    pub provider_id: String,
    pub model_id: String,
    pub tool_name: String,
    pub contract_version: u32,
    pub input: CommunityInput,
}

impl CommunityInvocation {
    pub fn validate(&self) -> bool {
        [&self.agent_id, &self.provider_id, &self.model_id]
            .iter()
            .all(|id| !id.trim().is_empty() && id.len() <= 256)
            && self.tool_name == SUBMIT_COMMUNITY_TOOL
            && self.contract_version == 1
            && self.input.validate()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommunityAuditFailure {
    ProviderUnavailable,
    InvalidSubmission,
    Cancelled,
    LeaseLost,
    AdmissionChanged,
    GraphChanged,
    InternalFailure,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum CommunityAuditOutcome {
    Applied {
        submission: CommunitySubmission,
    },
    Failed {
        code: CommunityAuditFailure,
        response_digest: Option<String>,
    },
}

impl CommunityAuditOutcome {
    pub fn validate(&self, input: &CommunityInput) -> bool {
        match self {
            Self::Applied { submission } => submission.validate(input),
            Self::Failed {
                response_digest, ..
            } => response_digest.as_ref().is_none_or(|digest| {
                digest.len() == 64 && digest.bytes().all(|byte| byte.is_ascii_hexdigit())
            }),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityAuditRecord {
    pub invocation: CommunityInvocation,
    pub attempt: u32,
    pub started_at_ms: i64,
    pub finished_at_ms: Option<i64>,
    pub latency_ms: Option<u64>,
    pub outcome: Option<CommunityAuditOutcome>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityResult {
    pub build_id: String,
    pub candidate_id: String,
    pub attempt: u32,
    pub submission: CommunitySubmission,
    pub finished_at_ms: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommunityProgressState {
    Pending,
    Failed,
    Completed,
    CompletedEmpty,
}

/// Derived from durable jobs/results, never written into the immutable B1 receipt.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityBuildStatus {
    pub build_id: String,
    pub state: CommunityProgressState,
    pub candidate_count: u32,
    pub ready_count: u32,
    pub insufficient_evidence_count: u32,
    pub failed_count: u32,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunitySelection {
    pub requested_build_id: Option<String>,
    pub active_build_id: Option<String>,
    pub revision: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityPublishedBuild {
    pub status: CommunityBuildStatus,
    pub candidates: Vec<CommunityCandidate>,
    pub results: Vec<CommunityResult>,
}

/// Stale named output is available only through explicit historical-build reads.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityActiveView {
    pub selection: CommunitySelection,
    pub current: Option<CommunityPublishedBuild>,
    pub stale_build_id: Option<String>,
}
