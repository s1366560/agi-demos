//! Explicit legacy-write lifetime; adapters must choose their admission policy.

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum LegacyMemoryWriteError {
    #[error("knowledge_sync_write_context_required")]
    ContextRequired,
    #[error("knowledge_sync_forbidden")]
    Forbidden,
    #[error("knowledge_sync_write_conflict")]
    Conflict,
    #[error("knowledge_sync_memory_not_found")]
    NotFound,
    #[error("knowledge_sync_fence_missing")]
    FenceMissing,
    #[error("knowledge_sync_admission_unavailable")]
    Unavailable,
}

#[derive(Debug, Clone)]
pub struct LegacyMemoryScope {
    pub project_id: String,
    /// Cloud adapters resolve this from the canonical project row.
    pub tenant_id: Option<String>,
}

/// Keep this value alive until SQL, vector and graph work has finished.
pub trait LegacyMemoryWriteLease: Send + Sync {
    fn scope(&self) -> &LegacyMemoryScope;
}

/// Local stores have no cloud enrollment table and opt in explicitly.
pub struct LocalMemoryWriteLease(pub LegacyMemoryScope);
impl LegacyMemoryWriteLease for LocalMemoryWriteLease {
    fn scope(&self) -> &LegacyMemoryScope {
        &self.0
    }
}
