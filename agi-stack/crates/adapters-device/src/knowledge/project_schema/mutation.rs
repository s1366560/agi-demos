//! Validated schema writes compose inside the caller's existing transaction.
//! This module never locks, commits, or grants operation authority.

use rusqlite::{params, Transaction};
use serde_json::json;

use super::{
    canonical_document, change_id_valid, identifier, read, scope_valid, scoped_document, storage,
    KnowledgeScope, ProjectSchemaError, ProjectSchemaMutation, ProjectSchemaReceipt,
    ProjectSchemaStorageError, ProjectSchemaStorageResult, ReceiptCheck, MAX_REVISION,
};

pub(super) struct ValidatedMutation<'a> {
    scope: &'a KnowledgeScope,
    actor_id: &'a str,
    command: &'a ProjectSchemaMutation,
    request: String,
}

#[cfg(test)]
#[path = "mutation_tests.rs"]
mod tests;

impl<'a> ValidatedMutation<'a> {
    pub(super) fn new(
        scope: &'a KnowledgeScope,
        actor_id: &'a str,
        command: &'a ProjectSchemaMutation,
        operation: &str,
    ) -> ProjectSchemaStorageResult<Self> {
        scope_valid(scope)?;
        identifier(actor_id)?;
        change_id_valid(&command.change_id)?;
        scoped_document(scope, &command.document)?;
        match operation {
            "bootstrap" if command.expected_revision == 0 => {}
            "replace" if (1..=MAX_REVISION).contains(&command.expected_revision) => {}
            _ => return Err(ProjectSchemaError::RevisionConflict.into()),
        }
        // Original member order belongs to replay identity; only acceptance is sorted.
        let request = json!({
            "command": operation, "tenant_id": scope.tenant_id, "project_id": scope.project_id,
            "actor_id": actor_id, "change_id": command.change_id,
            "expected_revision": command.expected_revision, "document": command.document.to_value(),
        })
        .to_string();
        Ok(Self {
            scope,
            actor_id,
            command,
            request,
        })
    }

    pub(super) fn as_request_json(&self) -> &str {
        &self.request
    }

    /// The caller owns authorization/deadline checks and the enclosing commit.
    /// Any later composition failure must roll back this same transaction.
    pub(super) fn apply_in_tx(
        &self,
        tx: &Transaction<'_>,
        receipt_check: Option<ReceiptCheck<'_>>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
        let Self {
            scope,
            actor_id,
            command,
            request,
        } = self;
        if let Some((original, receipt)) = read::receipt(tx, scope, actor_id, &command.change_id)? {
            if original != *request {
                return Err(ProjectSchemaStorageError::ChangeIdReused);
            }
            if let Some(check) = receipt_check {
                check(&receipt)?;
            }
            return Ok(receipt);
        }
        let previous = read::head(tx, scope)?;
        let document = canonical_document(&command.document)?;
        document.validate_successor(previous.as_ref(), command.expected_revision)?;
        let receipt = read::new_receipt(actor_id, &command.change_id, document)?;
        tx.execute(
            "INSERT INTO knowledge_project_schema_changes
             (tenant_id,project_id,schema_id,revision,actor_id,change_id,expected_revision,request_json,receipt_json)
             VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)",
            params![scope.tenant_id,scope.project_id,receipt.document().schema_id(),
                receipt.sequence(),actor_id,command.change_id,command.expected_revision,
                request,receipt.as_json()],
        ).map_err(storage)?;
        // The journal insert advances the head in the same SQLite statement.
        if read::head(tx, scope)?.as_ref() != Some(receipt.document()) {
            return Err(ProjectSchemaStorageError::CorruptStorage);
        }
        if let Some(check) = receipt_check {
            check(&receipt)?;
        }
        Ok(receipt)
    }
}
