//! Fresh local portable-schema authority in the knowledge database.
//!
//! Initialization creates empty storage only. Bootstrap is an explicit caller
//! command; there are no legacy defaults, API/capability registration, sync
//! associations, transport outboxes, or semantic merge policy in this module.
//! The mandatory `current` callback belongs to the admitting host. It runs after
//! transaction acquisition and immediately before commit, including receipt replay.
//! Callbacks must not reenter this repository while its connection lock is held.

use agistack_core::project_schema::{ProjectSchemaDocument, ProjectSchemaError, MAX_REVISION};
use rusqlite::TransactionBehavior;

use super::{KnowledgeScope, SqliteKnowledgeRepository};

mod bounded;
mod mutation;
mod read;
mod schema;
pub mod sync;
mod types;
pub(super) use schema::migrate;
pub use types::{
    ProjectSchemaHistoryPage, ProjectSchemaJournalPage, ProjectSchemaMutation,
    ProjectSchemaReceipt, ProjectSchemaStorageError, ProjectSchemaStorageResult,
};

type Current<'a> = &'a dyn Fn() -> ProjectSchemaStorageResult<()>;
type ReceiptCheck<'a> = &'a dyn Fn(&ProjectSchemaReceipt) -> ProjectSchemaStorageResult<()>;

fn storage(error: impl std::fmt::Display) -> ProjectSchemaStorageError {
    ProjectSchemaStorageError::Storage(error.to_string())
}

fn identifier(value: &str) -> ProjectSchemaStorageResult<()> {
    if value.is_empty()
        || value.len() > 512
        || value.contains('\0')
        || value.trim_matches([' ', '\t', '\r', '\n']) != value
    {
        return Err(ProjectSchemaStorageError::InvalidInput);
    }
    Ok(())
}

fn scope_valid(scope: &KnowledgeScope) -> ProjectSchemaStorageResult<()> {
    identifier(&scope.tenant_id)?;
    identifier(&scope.project_id)
}

fn change_id_valid(value: &str) -> ProjectSchemaStorageResult<()> {
    match uuid::Uuid::parse_str(value) {
        Ok(id) if !id.is_nil() && id.to_string() == value => Ok(()),
        _ => Err(ProjectSchemaStorageError::InvalidInput),
    }
}

fn scoped_document(
    scope: &KnowledgeScope,
    document: &ProjectSchemaDocument,
) -> ProjectSchemaStorageResult<()> {
    if document.tenant_id() != scope.tenant_id || document.project_id() != scope.project_id {
        return Err(ProjectSchemaStorageError::ScopeMismatch);
    }
    Ok(())
}

/// Canonicalize member order only. Opaque schema objects/numbers are represented
/// exclusively by the existing core parser/serializer, without reinterpretation.
fn canonical_document(
    document: &ProjectSchemaDocument,
) -> ProjectSchemaStorageResult<ProjectSchemaDocument> {
    let mut value = document.to_value();
    for field in ["entity_types", "edge_types", "mappings", "tombstones"] {
        let members = value[field]
            .as_array_mut()
            .ok_or(ProjectSchemaStorageError::CorruptStorage)?;
        members.sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
    }
    Ok(ProjectSchemaDocument::from_json(&value.to_string())?)
}

impl SqliteKnowledgeRepository {
    /// Reads the exact current aggregate, retaining terminal deletion snapshots.
    /// An absent schema stays absent; the read never initializes defaults.
    pub fn read_project_schema_durable(
        &self,
        scope: &KnowledgeScope,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<Option<ProjectSchemaDocument>> {
        scope_valid(scope)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        current()?;
        let result = read::head(&tx, scope)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }

    /// Explicit creation of a new local aggregate, never an inferred migration.
    pub fn bootstrap_project_schema_durable(
        &self,
        scope: &KnowledgeScope,
        actor_id: &str,
        command: &ProjectSchemaMutation,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
        if command.expected_revision != 0 {
            return Err(ProjectSchemaError::RevisionConflict.into());
        }
        self.write_project_schema(scope, actor_id, command, "bootstrap", current, None)
    }

    pub fn replace_project_schema_durable(
        &self,
        scope: &KnowledgeScope,
        actor_id: &str,
        command: &ProjectSchemaMutation,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
        if !(1..=MAX_REVISION).contains(&command.expected_revision) {
            return Err(ProjectSchemaError::RevisionConflict.into());
        }
        self.write_project_schema(scope, actor_id, command, "replace", current, None)
    }

    /// Preflights the exact acceptance inside the write transaction, including replay.
    pub fn bootstrap_project_schema_checked_durable(
        &self,
        scope: &KnowledgeScope,
        actor_id: &str,
        command: &ProjectSchemaMutation,
        current: Current<'_>,
        receipt_check: ReceiptCheck<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
        if command.expected_revision != 0 {
            return Err(ProjectSchemaError::RevisionConflict.into());
        }
        self.write_project_schema(
            scope,
            actor_id,
            command,
            "bootstrap",
            current,
            Some(receipt_check),
        )
    }

    pub fn replace_project_schema_checked_durable(
        &self,
        scope: &KnowledgeScope,
        actor_id: &str,
        command: &ProjectSchemaMutation,
        current: Current<'_>,
        receipt_check: ReceiptCheck<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
        if !(1..=MAX_REVISION).contains(&command.expected_revision) {
            return Err(ProjectSchemaError::RevisionConflict.into());
        }
        self.write_project_schema(
            scope,
            actor_id,
            command,
            "replace",
            current,
            Some(receipt_check),
        )
    }

    fn write_project_schema(
        &self,
        scope: &KnowledgeScope,
        actor_id: &str,
        command: &ProjectSchemaMutation,
        operation: &str,
        current: Current<'_>,
        receipt_check: Option<ReceiptCheck<'_>>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
        let mutation = mutation::ValidatedMutation::new(scope, actor_id, command, operation)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        current()?;
        let receipt = mutation.apply_in_tx(&tx, receipt_check)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(receipt)
    }

    pub fn project_schema_receipt_durable(
        &self,
        scope: &KnowledgeScope,
        actor_id: &str,
        change_id: &str,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<Option<ProjectSchemaReceipt>> {
        scope_valid(scope)?;
        identifier(actor_id)?;
        change_id_valid(change_id)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        current()?;
        let result = read::receipt(&tx, scope, actor_id, change_id)?.map(|(_, receipt)| receipt);
        current()?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }

    /// Reads revisions `(after_revision, upper_revision]`, up to 100 at a time.
    /// A cursor ahead of this exact scope's retained head is a conflict.
    pub fn project_schema_changes_durable(
        &self,
        scope: &KnowledgeScope,
        after_revision: u32,
        limit: u32,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaJournalPage> {
        scope_valid(scope)?;
        if !(1..=100).contains(&limit) {
            return Err(ProjectSchemaStorageError::InvalidInput);
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        current()?;
        let result = read::changes(&tx, scope, after_revision, limit)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }

    pub fn project_schema_history_bounded_durable(
        &self,
        scope: &KnowledgeScope,
        after_revision: u32,
        limit: u32,
        item_budget: &dyn Fn(&ProjectSchemaHistoryPage) -> ProjectSchemaStorageResult<usize>,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaHistoryPage> {
        scope_valid(scope)?;
        if !(1..=100).contains(&limit) {
            return Err(ProjectSchemaStorageError::InvalidInput);
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        current()?;
        let result = bounded::history(&tx, scope, after_revision, limit, item_budget)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }
}
