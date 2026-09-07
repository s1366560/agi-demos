//! Local synchronization intent. These records are not cloud requests: remote
//! revisions, remote authorization and transport acknowledgments are separate.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use super::{KnowledgeResult, KnowledgeScope, MemoryChange};

pub mod push;
pub mod pull;

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
