//! Read-only diagnostics expose metadata, never model input or credential bindings.
use super::{
    index::{IndexFailure, IndexSource},
    processing::{audit::ProcessingAuditFailure, ProcessingFailure, ProcessingSource},
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DiagnosticRequest {
    pub cursor: Option<String>,
    pub limit: usize,
}
#[derive(Debug, Clone, Serialize)]
pub struct DiagnosticPage<T> {
    pub items: Vec<T>,
    pub next_cursor: Option<String>,
}
#[derive(Debug, Clone, Serialize)]
pub struct ProcessingFailureDetail {
    pub source: ProcessingSource,
    pub attempt: u32,
    pub failure: ProcessingFailure,
}
#[derive(Debug, Clone, Serialize)]
pub struct IndexFailureDetail {
    pub input: IndexSource,
    pub attempt: u32,
    pub failure: IndexFailure,
}
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuditStatus {
    Running,
    Applied,
    Failed,
}
#[derive(Debug, Clone, Serialize)]
pub struct AuditSummary {
    pub source: ProcessingSource,
    pub attempt: u32,
    pub agent_id: String,
    pub provider_id: String,
    pub model_id: String,
    pub tool_name: String,
    pub contract_version: u32,
    pub started_at_ms: i64,
    pub finished_at_ms: Option<i64>,
    pub latency_ms: Option<u64>,
    pub status: AuditStatus,
    pub failure: Option<ProcessingAuditFailure>,
}
