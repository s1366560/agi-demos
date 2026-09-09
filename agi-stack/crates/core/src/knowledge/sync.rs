//! Local synchronization intent. These records are not cloud requests: remote
//! revisions, remote authorization and transport acknowledgments are separate.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use super::{KnowledgeResult, KnowledgeScope, MemoryChange};

pub mod pull;
pub mod push;

/// Explicit user-selected association. Configured does not mean the remote
/// actor or project has been authenticated. Rebinding requires a future
/// explicit migration protocol rather than silently reusing existing outbox IDs.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KnowledgeSyncLink {
    pub remote_tenant_id: String,
    pub remote_project_id: String,
    pub remote_actor_id: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct KnowledgeSyncStatus {
    pub replica_id: String,
    pub link: Option<KnowledgeSyncLink>,
    pub pending_changes: u64,
    pub pending_graph_changes: u64,
}

/// Explicit user choice for the locally downloaded copies at unbind time.
/// Local copies are never remotely revocable; unbinding is a purely local
/// lifecycle decision with no "remote wipe" semantics.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum KnowledgeUnbindPolicy {
    /// Cloud-origin downloaded memories stay as ordinary local records.
    Keep,
    /// Cloud-origin memories are tombstoned out of visibility immediately.
    /// Local-origin records are never removed by this path.
    Delete,
}

/// Durable record of one atomic unbind: the removed association, the chosen
/// policy, and the fencing applied to the previous binding's pending work.
#[derive(Debug, Clone, Serialize)]
pub struct KnowledgeUnbindReceipt {
    pub link: KnowledgeSyncLink,
    pub policy: KnowledgeUnbindPolicy,
    pub fenced_outbox: u64,
    pub fenced_graph_outbox: u64,
    pub removed_local_copies: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct KnowledgeSyncOutboxChange {
    /// UUID v5 using the persistent replica UUID as namespace and the decimal
    /// UTF-8 processing sequence as name. Immutable across retries and restarts.
    pub change_id: String,
    pub local_change: MemoryChange,
}

#[async_trait]
pub trait KnowledgeSyncRepository: Send + Sync {
    async fn sync_status(&self, scope: &KnowledgeScope) -> KnowledgeResult<KnowledgeSyncStatus>;
    /// First association persists; identical calls replay, different ones conflict.
    async fn configure_sync_link(
        &self,
        scope: &KnowledgeScope,
        link: KnowledgeSyncLink,
    ) -> KnowledgeResult<KnowledgeSyncStatus>;
    /// Ordered local-origin records only. This query neither acknowledges nor
    /// prepares a remote mutation and never infers a remote revision from local.
    async fn sync_outbox(
        &self,
        scope: &KnowledgeScope,
        after_sequence: u64,
        limit: usize,
    ) -> KnowledgeResult<Vec<KnowledgeSyncOutboxChange>>;
}

pub mod cloud_resolution;
pub mod graph;
pub mod graph_resolution;
pub mod resolution;
