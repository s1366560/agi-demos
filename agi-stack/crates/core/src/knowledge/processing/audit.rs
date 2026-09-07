//! Typed durable invocation and terminal records; raw provider errors and
//! rejected model text have no field in this contract.

use serde::{Deserialize, Serialize};

use super::worker::{ProcessingInput, ProjectionSubmission};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProcessingInvocation {
    pub agent_id: String,
    pub provider_id: String,
    pub model_id: String,
    pub tool_name: String,
    pub contract_version: u32,
    pub input: ProcessingInput,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessingAuditFailure {
    ProviderUnavailable,
    InvalidExtraction,
    Cancelled,
    LeaseLost,
    AdmissionChanged,
    InternalFailure,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProcessingAuditOutcome {
    Applied {
        submission: ProjectionSubmission,
    },
    Failed {
        code: ProcessingAuditFailure,
        response_digest: Option<String>,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub struct ProcessingAuditRecord {
    pub invocation: ProcessingInvocation,
    pub attempt: u32,
    pub started_at_ms: i64,
    pub finished_at_ms: Option<i64>,
    pub latency_ms: Option<u64>,
    pub outcome: Option<ProcessingAuditOutcome>,
}
