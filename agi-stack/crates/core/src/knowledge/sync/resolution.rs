//! Explicit local pull-conflict decisions. No choice implies a cloud receipt.
use super::push::{
    valid_identifier, KnowledgeSyncTarget, RemoteMemoryContent, MAX_REMOTE_REVISION,
};
use crate::{
    knowledge::{KnowledgeError, KnowledgeResult, KnowledgeScope},
    Memory,
};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnowledgeMergeContent {
    pub title: String,
    pub content: String,
    pub content_type: String,
    pub tags: Vec<String>,
    pub metadata: Map<String, Value>,
    pub status: String,
}
impl KnowledgeMergeContent {
    pub fn remote(&self) -> RemoteMemoryContent {
        RemoteMemoryContent {
            title: self.title.clone(),
            content: self.content.clone(),
            content_type: self.content_type.clone(),
            tags: self.tags.clone(),
            metadata: self.metadata.clone(),
            status: self.status.clone(),
        }
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "decision", rename_all = "snake_case", deny_unknown_fields)]
pub enum KnowledgeConflictChoice {
    UseLocal {},
    UseRemote {},
    Merged { content: KnowledgeMergeContent },
    KeepBoth {},
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnowledgePullConflictResolution {
    pub memory_id: String,
    pub conflict_sequences: Vec<u64>,
    pub expected_local_revision: u32,
    pub expected_remote_revision: u32,
    /// Zero denotes the absence of a previously acknowledged remote baseline.
    pub expected_baseline_revision: u32,
    pub choice: KnowledgeConflictChoice,
}
impl KnowledgePullConflictResolution {
    pub fn validate(&self) -> KnowledgeResult<()> {
        valid_identifier(&self.memory_id)?;
        if self.expected_local_revision == 0
            || self.expected_remote_revision == 0
            || self.expected_remote_revision > MAX_REMOTE_REVISION
            || self.expected_baseline_revision > MAX_REMOTE_REVISION
            || self.conflict_sequences.is_empty()
            || self.conflict_sequences.len() > 10_000
            || self
                .conflict_sequences
                .iter()
                .any(|s| *s == 0 || *s > i64::MAX as u64)
            || self.conflict_sequences.windows(2).any(|w| w[0] >= w[1])
        {
            return Err(KnowledgeError::InvalidInput);
        }
        if let KnowledgeConflictChoice::Merged { content } = &self.choice {
            content.remote().validate()?;
        }
        Ok(())
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KnowledgePullConflictContext {
    pub memory_id: String,
    pub conflict_sequences: Vec<u64>,
    pub local: Memory,
    pub local_deleted: bool,
    pub local_metadata: Map<String, Value>,
    pub baseline: Option<Value>,
    pub remote: Value,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KnowledgeResolutionReceipt {
    pub resolution_id: String,
    pub memory_id: String,
    pub local_revision: u32,
    pub remote_baseline_revision: u32,
    pub copy_memory_id: Option<String>,
    pub processing_sequences: Vec<u64>,
    pub pending_push_sequences: Vec<u64>,
    pub superseded_sequences: Vec<u64>,
    pub conflict_sequences: Vec<u64>,
}
#[derive(Debug, Clone, Serialize)]
pub struct KnowledgeResolutionOutcome {
    pub receipt: KnowledgeResolutionReceipt,
    pub replayed: bool,
}
#[async_trait]
pub trait KnowledgeResolutionRepository: Send + Sync {
    async fn pull_conflict_context(
        &self,
        scope: &KnowledgeScope,
        memory_id: &str,
    ) -> KnowledgeResult<Option<KnowledgePullConflictContext>>;
    async fn resolve_pull_conflicts(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor_id: &str,
        key: &str,
        resolution: KnowledgePullConflictResolution,
    ) -> KnowledgeResult<KnowledgeResolutionOutcome>;
    async fn resolution_history(
        &self,
        scope: &KnowledgeScope,
        memory_id: &str,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>>;
}
