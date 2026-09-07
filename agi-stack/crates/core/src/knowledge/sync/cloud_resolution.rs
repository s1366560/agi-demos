//! Durable explicit cloud decisions. Verified remote snapshots and receipts are
//! trusted-port inputs and must never be accepted from a renderer.
use super::push::KnowledgeSyncTarget;
use super::{
    push::{valid_identifier, MAX_REMOTE_REVISION},
    resolution::{KnowledgeConflictChoice, KnowledgeMergeContent},
};
use crate::{
    knowledge::{KnowledgeError, KnowledgeResult, KnowledgeScope},
    Memory,
};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "decision", rename_all = "snake_case", deny_unknown_fields)]
pub enum KnowledgeCloudChoice {
    KeepCurrent {},
    UseProposed {},
    Merged { content: KnowledgeMergeContent },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnowledgeCloudResolutionGuard {
    pub expected_local_revision: u32,
    pub expected_remote_revision: u32,
    pub expected_baseline_revision: u32,
    pub conflict_sequences: Vec<u64>,
}
impl KnowledgeCloudResolutionGuard {
    pub fn validate(&self) -> KnowledgeResult<()> {
        if self.expected_local_revision == 0
            || self.expected_remote_revision > MAX_REMOTE_REVISION
            || self.expected_baseline_revision > MAX_REMOTE_REVISION
            || self.conflict_sequences.len() > 10_000
            || self
                .conflict_sequences
                .iter()
                .any(|v| *v == 0 || *v > i64::MAX as u64)
            || self.conflict_sequences.windows(2).any(|w| w[0] >= w[1])
        {
            return Err(KnowledgeError::InvalidInput);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnowledgeCloudResolutionCommand {
    pub local_sequence: u64,
    pub memory_id: String,
    pub conflict_id: String,
    pub guard: KnowledgeCloudResolutionGuard,
    pub choice: KnowledgeCloudChoice,
}
impl KnowledgeCloudResolutionCommand {
    pub fn validate(&self) -> KnowledgeResult<()> {
        valid_identifier(&self.memory_id)?;
        valid_identifier(&self.conflict_id)?;
        self.guard.validate()?;
        if self.local_sequence == 0 || self.local_sequence > i64::MAX as u64 {
            return Err(KnowledgeError::InvalidInput);
        }
        if let KnowledgeCloudChoice::Merged { content } = &self.choice {
            content.remote().validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KnowledgeCloudResolutionContext {
    pub local_sequence: u64,
    pub memory_id: String,
    pub conflict_id: String,
    pub original_request: Value,
    pub cloud_conflict: Value,
    pub local: Memory,
    pub local_deleted: bool,
    pub local_metadata: Map<String, Value>,
    pub baseline: Option<Value>,
    pub remote: Option<Value>,
    pub conflict_sequences: Vec<u64>,
    pub pending_sequences: Vec<u64>,
    pub observed_cursor: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KnowledgeCloudResolutionRecord {
    pub resolution_id: String,
    pub local_sequence: u64,
    /// Exact persisted POST body, including the stable new change_id.
    pub request_json: String,
    pub command: KnowledgeCloudResolutionCommand,
    pub archive: KnowledgeCloudResolutionContext,
    pub receipt: Option<Value>,
    /// Only a verified knowledge_sync_resolution_stale response can populate this.
    pub rejection: Option<Value>,
    pub reconciliation: Option<KnowledgeCloudReconciliationReceipt>,
    pub reconciliation_command: Option<Value>,
    pub reconciliation_archive: Option<KnowledgeCloudResolutionContext>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnowledgeCloudReconciliationCommand {
    pub guard: KnowledgeCloudResolutionGuard,
    pub choice: KnowledgeConflictChoice,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KnowledgeCloudReconciliationReceipt {
    pub local_revision: u32,
    pub copy_memory_id: Option<String>,
    pub processing_sequences: Vec<u64>,
    pub pending_push_sequences: Vec<u64>,
    pub superseded_sequences: Vec<u64>,
    pub conflict_sequences: Vec<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct KnowledgeCloudResolutionOutcome {
    pub resolution_id: String,
    pub receipt: Value,
    /// True means a new explicit local choice with a fresh guard is required.
    pub pending_reconciliation: bool,
    pub replayed: bool,
}

/// Ports carrying verified cloud documents are restricted to a trusted adapter.
/// Native callers use the synchronous durable forms while holding their fence.
#[async_trait]
pub trait KnowledgeCloudResolutionRepository: Send + Sync {
    async fn cloud_resolution_by_key(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        key: &str,
    ) -> KnowledgeResult<Option<KnowledgeCloudResolutionRecord>>;
    async fn cloud_conflict_snapshot(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        local_sequence: u64,
    ) -> KnowledgeResult<Value>;
    async fn cloud_conflict_context(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        local_sequence: u64,
        verified_conflict: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionContext>;
    async fn prepare_cloud_resolution(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        key: &str,
        command: KnowledgeCloudResolutionCommand,
        verified_conflict: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionRecord>;
    async fn cloud_resolution_record(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        resolution_id: &str,
    ) -> KnowledgeResult<KnowledgeCloudResolutionRecord>;
    async fn cloud_resolution_records(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        limit: usize,
    ) -> KnowledgeResult<Vec<KnowledgeCloudResolutionRecord>>;
    async fn accept_cloud_resolution_receipt(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        resolution_id: &str,
        verified_response: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionOutcome>;
    async fn reject_cloud_resolution_stale(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        resolution_id: &str,
        verified_response: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionRecord>;
    async fn cloud_reconciliation_context(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        resolution_id: &str,
    ) -> KnowledgeResult<KnowledgeCloudResolutionContext>;
    async fn reconcile_cloud_resolution(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        resolution_id: &str,
        command: KnowledgeCloudReconciliationCommand,
    ) -> KnowledgeResult<KnowledgeCloudResolutionOutcome>;
}
