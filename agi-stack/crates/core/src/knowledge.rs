//! Scoped storage boundary for new knowledge authorities. The legacy
//! `MemoryRepository` must not be used for tenant-facing knowledge operations.

use async_trait::async_trait;

use crate::model::Memory;

/// Explicit ownership supplied by the authenticated authority, never inferred
/// from a memory ID or from historical rows without tenant attribution.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KnowledgeScope {
    pub tenant_id: String,
    pub project_id: String,
}

#[derive(Debug, thiserror::Error)]
pub enum KnowledgeError {
    #[error("invalid knowledge scope or memory")]
    InvalidInput,
    #[error("memory not found in scope")]
    NotFound,
    #[error("memory revision conflict")]
    Conflict,
    #[error("knowledge storage error: {0}")]
    Storage(String),
}

pub type KnowledgeResult<T> = Result<T, KnowledgeError>;

/// Every operation includes both ownership fields. Updates and deletion use
/// atomic revision checks; successful writes must persist a processing change
/// in the same transaction. Deleted IDs stay reserved as tombstones.
#[async_trait]
pub trait ScopedMemoryRepository: Send + Sync {
    /// Create revision 1. Existing IDs, including tombstones, conflict.
    async fn create(&self, scope: &KnowledgeScope, memory: Memory) -> KnowledgeResult<Memory>;
    async fn get(&self, scope: &KnowledgeScope, id: &str) -> KnowledgeResult<Option<Memory>>;
    async fn list(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
        offset: usize,
    ) -> KnowledgeResult<Vec<Memory>>;
    /// Caller supplies the current revision in both `memory.version` and
    /// `expected_revision`; storage increments it on success.
    async fn update(
        &self,
        scope: &KnowledgeScope,
        memory: Memory,
        expected_revision: u32,
    ) -> KnowledgeResult<Memory>;
    /// Retain a tombstone at the next revision; no longer visible to get/list.
    async fn delete(
        &self,
        scope: &KnowledgeScope,
        id: &str,
        expected_revision: u32,
    ) -> KnowledgeResult<()>;
}
