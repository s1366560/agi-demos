//! Explicit local graph pull-conflict decisions. No choice implies a cloud
//! receipt; cloud push-conflict resolution settles through the verified
//! transport like memory sync.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::graph::RemoteGraphContent;
use super::push::{valid_identifier, KnowledgeSyncTarget, MAX_REMOTE_REVISION};
use super::{KnowledgeResult, KnowledgeScope};
use crate::knowledge::KnowledgeError;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "decision", rename_all = "snake_case", deny_unknown_fields)]
pub enum GraphConflictChoice {
    UseLocal {},
    UseRemote {},
    Merged { content: RemoteGraphContent },
    KeepBoth {},
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GraphPullConflictResolution {
    pub object_id: String,
    pub conflict_sequences: Vec<u64>,
    pub expected_local_revision: u32,
    pub expected_remote_revision: u32,
    /// Zero denotes the absence of a previously acknowledged remote baseline.
    pub expected_baseline_revision: u32,
    pub choice: GraphConflictChoice,
}

impl GraphPullConflictResolution {
    pub fn validate(&self) -> KnowledgeResult<()> {
        valid_identifier(&self.object_id)?;
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
        if let GraphConflictChoice::Merged { content } = &self.choice {
            content.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphPullConflictContext {
    pub object_id: String,
    pub conflict_sequences: Vec<u64>,
    pub local: Option<Value>,
    pub local_deleted: bool,
    pub baseline: Option<Value>,
    pub remote: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphResolutionReceipt {
    pub resolution_id: String,
    pub object_id: String,
    pub local_revision: u32,
    pub remote_baseline_revision: u32,
    pub copy_object_id: Option<String>,
    pub conflict_sequences: Vec<u64>,
    pub superseded_sequences: Vec<u64>,
    pub pending_push_sequences: Vec<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GraphResolutionOutcome {
    pub receipt: GraphResolutionReceipt,
    pub replayed: bool,
}

#[async_trait]
pub trait KnowledgeGraphResolutionRepository: Send + Sync {
    async fn graph_pull_conflict_context(
        &self,
        scope: &KnowledgeScope,
        object_id: &str,
    ) -> KnowledgeResult<Option<GraphPullConflictContext>>;
    async fn resolve_graph_pull_conflicts(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor_id: &str,
        key: &str,
        resolution: GraphPullConflictResolution,
    ) -> KnowledgeResult<GraphResolutionOutcome>;
    async fn graph_resolution_history(
        &self,
        scope: &KnowledgeScope,
        object_id: &str,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>>;
}
