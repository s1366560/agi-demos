//! Strict cloud full-document protocol. No transport, credentials or authority.
//!
//! Cloud receipts deliberately keep their own wire shape and original JSON;
//! they are not native receipts and do not identify their actor. Document rules
//! and adjacent-history checks come from the existing portable schema core.

use serde::Deserialize;

use super::{validation, ProjectSchemaDocument, ProjectSchemaError};

mod history;
mod receipt;
mod requests;

pub use history::CloudSchemaHistoryPage;
pub use receipt::CloudSchemaReceipt;
pub use requests::{CloudSchemaHistoryQuery, CloudSchemaReceiptQuery, CloudSchemaReplaceRequest};

/// Both request and response envelopes use the cloud-rpc v1 UTF-8 byte limit.
pub const MAX_CLOUD_SCHEMA_BYTES: usize = 2 * 1024 * 1024;
pub const MAX_CLOUD_SCHEMA_HISTORY_ITEMS: u32 = 100;

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum CloudSchemaProtocolError {
    #[error("cloud schema envelope is invalid")]
    InvalidEnvelope,
    #[error("cloud schema scope does not match")]
    ScopeMismatch,
    #[error("cloud schema receipt does not match the request")]
    ReceiptMismatch,
    #[error("cloud schema history is not a contiguous accepted prefix")]
    InvalidHistory,
    #[error("cloud schema command is invalid")]
    InvalidCommand,
    #[error(transparent)]
    Document(#[from] ProjectSchemaError),
}

type Result<T> = std::result::Result<T, CloudSchemaProtocolError>;

// All callers use closed typed envelopes. Embedded document RawValues are
// separately parsed by ProjectSchemaDocument, preserving duplicate/integer tokens.
fn parse<'de, T: Deserialize<'de>>(raw: &'de str) -> Result<T> {
    if raw.len() > MAX_CLOUD_SCHEMA_BYTES {
        return Err(CloudSchemaProtocolError::InvalidEnvelope);
    }
    serde_json::from_str(raw).map_err(|_| CloudSchemaProtocolError::InvalidEnvelope)
}

fn scoped_document(raw: &str, tenant: &str, project: &str) -> Result<ProjectSchemaDocument> {
    let document = ProjectSchemaDocument::from_json(raw)?;
    if document.tenant_id() != tenant || document.project_id() != project {
        return Err(CloudSchemaProtocolError::ScopeMismatch);
    }
    if document.revision() == 1 {
        document.validate_successor(None, 0)?;
    }
    Ok(document)
}

fn uuid(value: &str) -> Result<()> {
    validation::uuid(value).map_err(|_| CloudSchemaProtocolError::InvalidEnvelope)
}
