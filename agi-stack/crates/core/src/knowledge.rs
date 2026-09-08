//! Scoped storage boundary for new knowledge authorities. The legacy
//! `MemoryRepository` must not be used for tenant-facing knowledge operations.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

pub mod document;
pub use document::KnowledgeMemory;
use document::KnowledgeMemory as Memory;

pub mod community;
pub mod diagnostics;
pub mod index;
pub mod processing;
pub mod retrieval;
pub mod similarity;
pub mod sync;

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
    #[error("idempotency key belongs to a different request")]
    IdempotencyConflict,
    #[error("knowledge storage error: {0}")]
    Storage(String),
}

pub type KnowledgeResult<T> = Result<T, KnowledgeError>;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub enum MemoryMutation {
    Create {
        #[serde(deserialize_with = "document::deserialize_mutation_memory")]
        memory: Memory,
    },
    Update {
        #[serde(deserialize_with = "document::deserialize_mutation_memory")]
        memory: Memory,
        expected_revision: u32,
    },
    Delete {
        id: String,
        expected_revision: u32,
    },
}

/// Durable change available for processing. This is an accepted change, not
/// evidence that extraction, indexing or synchronization has completed.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryChange {
    pub sequence: u64,
    pub memory: Memory,
    pub deleted: bool,
}

#[derive(Debug, Clone)]
pub struct MemoryMutationOutcome {
    pub receipt: MemoryChange,
    pub replayed: bool,
}

/// Every operation includes both ownership fields. Updates and deletion use
/// atomic revision checks; successful writes must persist a processing change
/// in the same transaction. Deleted IDs stay reserved as tombstones.
#[async_trait]
pub trait ScopedMemoryRepository: Send + Sync {
    /// Idempotency keys are isolated by scope and authenticated actor. Equal
    /// requests replay the original receipt, including after subsequent edits.
    /// Receipt, change and content are committed atomically.
    async fn mutate(
        &self,
        scope: &KnowledgeScope,
        actor_id: &str,
        idempotency_key: &str,
        mutation: MemoryMutation,
    ) -> KnowledgeResult<MemoryMutationOutcome>;
    async fn changes(
        &self,
        scope: &KnowledgeScope,
        after_sequence: u64,
        limit: usize,
    ) -> KnowledgeResult<Vec<MemoryChange>>;
    async fn change(
        &self,
        scope: &KnowledgeScope,
        sequence: u64,
    ) -> KnowledgeResult<Option<MemoryChange>>;
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
