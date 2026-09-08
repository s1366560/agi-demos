//! Storage command values. None of these values grants caller authorization.
use agistack_core::project_schema::{ProjectSchemaDocument, ProjectSchemaError};

#[derive(Debug, thiserror::Error)]
pub enum ProjectSchemaStorageError {
    #[error("project_schema_invalid_input")]
    InvalidInput,
    #[error("project_schema_scope_mismatch")]
    ScopeMismatch,
    #[error(transparent)]
    Document(#[from] ProjectSchemaError),
    #[error("project_schema_change_id_reused")]
    ChangeIdReused,
    #[error("project_schema_admission_changed")]
    AdmissionChanged,
    #[error("project_schema_response_too_large")]
    ResponseTooLarge,
    #[error("project_schema_storage_corrupt")]
    CorruptStorage,
    #[error("project_schema_storage: {0}")]
    Storage(String),
}

pub type ProjectSchemaStorageResult<T> = Result<T, ProjectSchemaStorageError>;

/// Caller-supplied adjacent snapshot and explicit CAS/idempotency conditions.
/// Bootstrap requires expected_revision=0; replace requires a positive revision.
#[derive(Debug, Clone)]
pub struct ProjectSchemaMutation {
    pub document: ProjectSchemaDocument,
    pub expected_revision: u32,
    pub change_id: String,
}

/// Exact persisted acceptance. The document is a canonical snapshot of that
/// revision, even when the current head has subsequently changed or been deleted.
#[derive(Debug, Clone, PartialEq)]
pub struct ProjectSchemaReceipt {
    pub(super) json: String,
    pub(super) actor_id: String,
    pub(super) change_id: String,
    pub(super) document: ProjectSchemaDocument,
}

impl ProjectSchemaReceipt {
    pub fn as_json(&self) -> &str {
        &self.json
    }

    pub fn actor_id(&self) -> &str {
        &self.actor_id
    }

    pub fn change_id(&self) -> &str {
        &self.change_id
    }

    pub fn document(&self) -> &ProjectSchemaDocument {
        &self.document
    }

    /// The aggregate's journal sequence is its strictly increasing revision.
    pub fn sequence(&self) -> u32 {
        self.document.revision()
    }
}

/// A bounded journal read from one SQLite snapshot. This is storage history,
/// not a transport outbox, enrollment, or claim that synchronization occurred.
#[derive(Debug, Clone, PartialEq)]
pub struct ProjectSchemaJournalPage {
    pub upper_revision: u32,
    pub items: Vec<ProjectSchemaReceipt>,
}

/// One transaction's complete receipt prefix. The caller supplies an envelope
/// budget derived from this same schema identity and upper revision.
#[derive(Debug, Clone, PartialEq)]
pub struct ProjectSchemaHistoryPage {
    pub schema_id: Option<String>,
    pub after_revision: u32,
    pub upper_revision: u32,
    pub next_after_revision: u32,
    pub has_more: bool,
    pub items: Vec<ProjectSchemaReceipt>,
}
