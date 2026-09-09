//! Durable intent for cloud-bound replacements. Preparation persists the exact
//! request bytes against the pinned anchor pair; completion accepts only the
//! actual receipt for those bytes. Transport, dispatch and any retry belong to
//! the admitting host, never to this storage layer.

use agistack_core::project_schema::cloud_rpc::{CloudSchemaReceipt, CloudSchemaReplaceRequest};
use agistack_core::project_schema::{projection, ProjectSchemaError};
use rusqlite::TransactionBehavior;

use super::super::{
    change_id_valid, identifier, read, storage, ProjectSchemaStorageError,
    ProjectSchemaStorageResult, SqliteKnowledgeRepository,
};
use super::{
    binding_valid, cursor, prepared, remote_scoped, Current, ProjectSchemaSyncAnchorKind,
    ProjectSchemaSyncBinding, ProjectSchemaSyncImportedSide, ProjectSchemaSyncPrepared,
    ProjectSchemaSyncState, ProjectSchemaSyncStepKind,
};

fn conflict<T>() -> ProjectSchemaStorageResult<T> {
    Err(ProjectSchemaStorageError::SyncConflict)
}

impl SqliteKnowledgeRepository {
    /// Persist one cloud replacement intent fenced to the current anchor pair.
    /// The exact request bytes must validate against the durable cloud receipt
    /// and equal the projection of the adjacent native head onto that pair.
    pub fn prepare_project_schema_cloud_replace_durable(
        &self,
        binding: &ProjectSchemaSyncBinding,
        actor_id: &str,
        request: &CloudSchemaReplaceRequest,
        step_id: &str,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaSyncPrepared> {
        binding_valid(binding)?;
        identifier(actor_id)?;
        change_id_valid(step_id)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        current()?;
        let Some(cursor) = cursor::row(&tx, binding)? else {
            return conflict();
        };
        let Some(anchor_id) = cursor.anchor_id.clone() else {
            return conflict();
        };
        let anchor = cursor::anchor(&tx, binding, &anchor_id)?;
        if anchor.kind != ProjectSchemaSyncAnchorKind::Pair {
            return conflict();
        }
        if request.expected_revision() != anchor.cloud_revision() {
            return Err(ProjectSchemaError::RevisionConflict.into());
        }
        let checked =
            CloudSchemaReplaceRequest::from_json(request.as_json(), &anchor.cloud_receipt)
                .map_err(|_| ProjectSchemaStorageError::SyncConflict)?;
        let native_base = anchor
            .native_receipt
            .as_ref()
            .ok_or(ProjectSchemaStorageError::CorruptStorage)?;
        let Some(head) = read::head(&tx, &binding.scope)? else {
            return conflict();
        };
        if Some(head.revision()) != native_base.document().revision().checked_add(1) {
            return Err(ProjectSchemaError::RevisionConflict.into());
        }
        let source = read::revision(&tx, &binding.scope, head.revision())?;
        let projected = projection::project_successor(
            native_base.document(),
            &head,
            anchor.cloud_receipt.document(),
        )?;
        if !projection::equivalent_content(&projected, checked.document()) {
            return conflict();
        }
        prepared::insert(
            &tx,
            binding,
            &cursor,
            &prepared::NewStep {
                step_id,
                kind: ProjectSchemaSyncStepKind::CloudReplace,
                local_actor_id: actor_id,
                source_receipt: source.as_json(),
                destination_base: Some(anchor.cloud_receipt.as_json()),
                destination_change_id: checked.change_id(),
                request_json: checked.as_json(),
            },
        )?;
        let prepared = prepared::by_step_id(&tx, binding, step_id)?
            .ok_or(ProjectSchemaStorageError::CorruptStorage)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(prepared)
    }

    /// The pending prepared step, if any, for explicit crash/uncertainty recovery.
    pub fn project_schema_sync_pending_durable(
        &self,
        binding: &ProjectSchemaSyncBinding,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<Option<ProjectSchemaSyncPrepared>> {
        binding_valid(binding)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        current()?;
        let pending = prepared::pending(&tx, binding)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(pending)
    }

    /// Record the actual cloud acceptance of a prepared replacement. Only the
    /// receipt matching the persisted request bytes completes the step.
    pub fn complete_project_schema_cloud_replace_durable(
        &self,
        binding: &ProjectSchemaSyncBinding,
        step_id: &str,
        receipt: &CloudSchemaReceipt,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaSyncState> {
        binding_valid(binding)?;
        change_id_valid(step_id)?;
        remote_scoped(binding, receipt)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        current()?;
        let Some(cursor) = cursor::row(&tx, binding)? else {
            return conflict();
        };
        let Some(anchor_id) = cursor.anchor_id.clone() else {
            return conflict();
        };
        let anchor = cursor::anchor(&tx, binding, &anchor_id)?;
        if anchor.kind != ProjectSchemaSyncAnchorKind::Pair {
            return conflict();
        }
        let Some(pending) = prepared::pending(&tx, binding)? else {
            return conflict();
        };
        if pending.step_id != step_id || pending.kind != ProjectSchemaSyncStepKind::CloudReplace {
            return conflict();
        }
        let request =
            CloudSchemaReplaceRequest::from_json(&pending.request_json, &anchor.cloud_receipt)
                .map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
        request
            .require_receipt(receipt)
            .map_err(|_| ProjectSchemaStorageError::SyncConflict)?;
        let native_receipt =
            read::journal_receipt_by_json(&tx, &binding.scope, &pending.source_receipt)?;
        cursor::accept_anchor(
            &tx,
            binding,
            &cursor,
            &pending.step_id,
            &cursor::NewAnchor {
                anchor_id: &uuid::Uuid::new_v4().to_string(),
                kind: ProjectSchemaSyncAnchorKind::Pair,
                imported: ProjectSchemaSyncImportedSide::Cloud,
                native_receipt: Some(&native_receipt),
                cloud_receipt: receipt,
            },
        )?;
        let state =
            cursor::state(&tx, binding)?.ok_or(ProjectSchemaStorageError::CorruptStorage)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(state)
    }
}
