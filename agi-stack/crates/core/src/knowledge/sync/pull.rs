//! Trusted remote change ingestion. The native transport owns the target and
//! response; these are never accepted from a renderer mutation payload.

use async_trait::async_trait;
use serde::Serialize;
use serde_json::Value;

use super::push::KnowledgeSyncTarget;
use super::{KnowledgeResult, KnowledgeScope};

/// Cursor and applied/conflicting event counts committed by one page.
#[derive(Debug, Clone, Serialize)]
pub struct KnowledgePullReceipt {
    pub next_cursor: u64,
    pub applied: usize,
    pub conflicts: usize,
    pub has_more: bool,
}

#[async_trait]
pub trait KnowledgePullRepository: Send + Sync {
    async fn pull_cursor(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
    ) -> KnowledgeResult<u64>;
    /// Commits content, indexing events, conflict copies and cursor atomically.
    /// A stale expected cursor is rejected; callers fetch again from the durable cursor.
    async fn accept_pull_page(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        after: u64,
        response: Value,
    ) -> KnowledgeResult<KnowledgePullReceipt>;
    async fn pull_conflicts(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>>;
}
