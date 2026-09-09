//! Pull/apply orchestration. Every presented source transition is verified
//! through the pure cross-scope projection before any local acceptance, and
//! initialization never overwrites a divergent non-empty native scope. Native
//! intent, acceptance, anchor and cursor advance commit in one transaction.

use agistack_core::project_schema::cloud_rpc::CloudSchemaReceipt;
use agistack_core::project_schema::{projection, ProjectSchemaError};
use rusqlite::TransactionBehavior;

use super::super::{
    change_id_valid, identifier, mutation::ValidatedMutation, read, storage, ProjectSchemaMutation,
    ProjectSchemaStorageError, ProjectSchemaStorageResult, SqliteKnowledgeRepository,
};
use super::{
    binding_valid, cursor, prepared, remote_scoped, Current, ProjectSchemaSyncAnchorKind,
    ProjectSchemaSyncBinding, ProjectSchemaSyncImportedSide, ProjectSchemaSyncState,
    ProjectSchemaSyncStepKind,
};

fn conflict<T>() -> ProjectSchemaStorageResult<T> {
    Err(ProjectSchemaStorageError::SyncConflict)
}

impl SqliteKnowledgeRepository {
    /// Begin a schema synchronization association. The durable Memory binding
    /// must already exist; an identical repeat begin replays harmlessly.
    pub fn begin_project_schema_sync_durable(
        &self,
        binding: &ProjectSchemaSyncBinding,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaSyncState> {
        binding_valid(binding)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        current()?;
        cursor::begin(&tx, binding)?;
        let state =
            cursor::state(&tx, binding)?.ok_or(ProjectSchemaStorageError::CorruptStorage)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(state)
    }

    /// Read the durable cursor and validated head anchor, or None before begin.
    pub fn project_schema_sync_state_durable(
        &self,
        binding: &ProjectSchemaSyncBinding,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<Option<ProjectSchemaSyncState>> {
        binding_valid(binding)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        current()?;
        let state = cursor::state(&tx, binding)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(state)
    }

    /// Initialize pull from an exact accepted cloud root. An empty native scope
    /// accepts the projected root; an accepted empty native seed receives it as
    /// the next revision; an already equivalent head is bound without a write.
    /// Any other existing native content is a revision conflict, never an
    /// overwrite. The presented root is pinned by the resulting anchor.
    pub fn initialize_project_schema_pull_durable(
        &self,
        binding: &ProjectSchemaSyncBinding,
        source_root: &CloudSchemaReceipt,
        actor_id: &str,
        change_id: &str,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaSyncState> {
        binding_valid(binding)?;
        identifier(actor_id)?;
        change_id_valid(change_id)?;
        remote_scoped(binding, source_root)?;
        if source_root.revision() != 1 {
            return Err(ProjectSchemaError::InvalidTransition.into());
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        current()?;
        let Some(cursor) = cursor::row(&tx, binding)? else {
            return conflict();
        };
        if cursor.anchor_id.is_some() {
            return conflict();
        }
        let head = read::head(&tx, &binding.scope)?;
        let step_kind;
        let imported;
        let destination_base: Option<String>;
        let request_json: String;
        let native_receipt;
        match head {
            None => {
                let document = projection::project_bootstrap(
                    source_root.document(),
                    &binding.scope.tenant_id,
                    &binding.scope.project_id,
                )?;
                let command = ProjectSchemaMutation {
                    document,
                    expected_revision: 0,
                    change_id: change_id.into(),
                };
                let mutation =
                    ValidatedMutation::new(&binding.scope, actor_id, &command, "bootstrap")?;
                request_json = mutation.as_request_json().to_owned();
                native_receipt = mutation.apply_in_tx(&tx, None)?;
                step_kind = ProjectSchemaSyncStepKind::NativeBootstrap;
                imported = ProjectSchemaSyncImportedSide::Native;
                destination_base = None;
            }
            Some(head) => {
                if head.schema_id() != binding.schema_id {
                    return conflict();
                }
                let base = read::revision(&tx, &binding.scope, head.revision())?;
                if projection::equivalent_content(&head, source_root.document()) {
                    let (original_request, _) =
                        read::receipt(&tx, &binding.scope, base.actor_id(), base.change_id())?
                            .ok_or(ProjectSchemaStorageError::CorruptStorage)?;
                    request_json = original_request;
                    native_receipt = base;
                    step_kind = if head.revision() == 1 {
                        ProjectSchemaSyncStepKind::NativeBootstrap
                    } else {
                        ProjectSchemaSyncStepKind::NativeReplace
                    };
                    imported = ProjectSchemaSyncImportedSide::Neither;
                    destination_base = None;
                } else if head.revision() == 1
                    && !head.is_deleted()
                    && head.entity_types().is_empty()
                    && head.edge_types().is_empty()
                    && head.mappings().is_empty()
                {
                    let document =
                        projection::project_root_after_empty_seed(source_root.document(), &head)?;
                    let command = ProjectSchemaMutation {
                        document,
                        expected_revision: 1,
                        change_id: change_id.into(),
                    };
                    let mutation =
                        ValidatedMutation::new(&binding.scope, actor_id, &command, "replace")?;
                    request_json = mutation.as_request_json().to_owned();
                    native_receipt = mutation.apply_in_tx(&tx, None)?;
                    step_kind = ProjectSchemaSyncStepKind::NativeReplace;
                    imported = ProjectSchemaSyncImportedSide::Native;
                    destination_base = Some(base.as_json().to_owned());
                } else {
                    return Err(ProjectSchemaError::RevisionConflict.into());
                }
            }
        }
        let step_id = uuid::Uuid::new_v4().to_string();
        prepared::insert(
            &tx,
            binding,
            &cursor,
            &prepared::NewStep {
                step_id: &step_id,
                kind: step_kind,
                local_actor_id: actor_id,
                source_receipt: source_root.as_json(),
                destination_base: destination_base.as_deref(),
                destination_change_id: native_receipt.change_id(),
                request_json: &request_json,
            },
        )?;
        let anchor_id = uuid::Uuid::new_v4().to_string();
        cursor::accept_anchor(
            &tx,
            binding,
            &cursor,
            &step_id,
            &cursor::NewAnchor {
                anchor_id: &anchor_id,
                kind: ProjectSchemaSyncAnchorKind::Pair,
                imported,
                native_receipt: Some(&native_receipt),
                cloud_receipt: source_root,
            },
        )?;
        let state =
            cursor::state(&tx, binding)?.ok_or(ProjectSchemaStorageError::CorruptStorage)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(state)
    }

    /// Apply exactly one adjacent accepted cloud transition. The projection
    /// requires the presented receipt to continue the head anchor's cloud
    /// document and the native head to match the anchor's native receipt; a
    /// moved local head conflicts and is never rebased or overwritten.
    pub fn apply_project_schema_pull_durable(
        &self,
        binding: &ProjectSchemaSyncBinding,
        source: &CloudSchemaReceipt,
        actor_id: &str,
        change_id: &str,
        current: Current<'_>,
    ) -> ProjectSchemaStorageResult<ProjectSchemaSyncState> {
        binding_valid(binding)?;
        identifier(actor_id)?;
        change_id_valid(change_id)?;
        remote_scoped(binding, source)?;
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
        if Some(source.revision()) != anchor.cloud_revision().checked_add(1) {
            return Err(ProjectSchemaError::RevisionConflict.into());
        }
        let Some(head) = read::head(&tx, &binding.scope)? else {
            return conflict();
        };
        let native_base = anchor
            .native_receipt
            .as_ref()
            .ok_or(ProjectSchemaStorageError::CorruptStorage)?;
        if head.revision() != native_base.document().revision()
            || !projection::equivalent_content(&head, native_base.document())
        {
            return conflict();
        }
        let document = projection::project_successor(
            anchor.cloud_receipt.document(),
            source.document(),
            &head,
        )?;
        let command = ProjectSchemaMutation {
            document,
            expected_revision: head.revision(),
            change_id: change_id.into(),
        };
        let mutation = ValidatedMutation::new(&binding.scope, actor_id, &command, "replace")?;
        let request_json = mutation.as_request_json().to_owned();
        let native_receipt = mutation.apply_in_tx(&tx, None)?;
        let step_id = uuid::Uuid::new_v4().to_string();
        prepared::insert(
            &tx,
            binding,
            &cursor,
            &prepared::NewStep {
                step_id: &step_id,
                kind: ProjectSchemaSyncStepKind::NativeReplace,
                local_actor_id: actor_id,
                source_receipt: source.as_json(),
                destination_base: Some(native_base.as_json()),
                destination_change_id: native_receipt.change_id(),
                request_json: &request_json,
            },
        )?;
        let anchor_id = uuid::Uuid::new_v4().to_string();
        cursor::accept_anchor(
            &tx,
            binding,
            &cursor,
            &step_id,
            &cursor::NewAnchor {
                anchor_id: &anchor_id,
                kind: ProjectSchemaSyncAnchorKind::Pair,
                imported: ProjectSchemaSyncImportedSide::Native,
                native_receipt: Some(&native_receipt),
                cloud_receipt: source,
            },
        )?;
        let state =
            cursor::state(&tx, binding)?.ok_or(ProjectSchemaStorageError::CorruptStorage)?;
        current()?;
        tx.commit().map_err(storage)?;
        Ok(state)
    }
}
