//! Immutable prepared transfer intent. At most one step per cursor is pending;
//! completion only records the anchor its own transaction produced.
use rusqlite::{params, OptionalExtension, Transaction};

use super::super::storage;
use super::{
    change_id_valid, cursor::CursorRow, identifier, ProjectSchemaStorageError,
    ProjectSchemaStorageResult, ProjectSchemaSyncBinding, ProjectSchemaSyncPrepared,
    ProjectSchemaSyncStepKind,
};

pub(super) struct NewStep<'a> {
    pub(super) step_id: &'a str,
    pub(super) kind: ProjectSchemaSyncStepKind,
    pub(super) local_actor_id: &'a str,
    pub(super) source_receipt: &'a str,
    pub(super) destination_base: Option<&'a str>,
    pub(super) destination_change_id: &'a str,
    pub(super) request_json: &'a str,
}

type PreparedColumns = (
    String,
    String,
    String,
    Option<String>,
    i64,
    String,
    Option<String>,
    String,
    String,
    Option<String>,
);

fn decode(columns: PreparedColumns) -> ProjectSchemaStorageResult<ProjectSchemaSyncPrepared> {
    let (
        step_id,
        kind,
        local_actor_id,
        expected_anchor_id,
        expected_epoch,
        source_receipt,
        destination_base,
        destination_change_id,
        request_json,
        completed_anchor_id,
    ) = columns;
    let corrupt = || ProjectSchemaStorageError::CorruptStorage;
    let kind = ProjectSchemaSyncStepKind::from_str(&kind).ok_or_else(corrupt)?;
    change_id_valid(&step_id).map_err(|_| corrupt())?;
    change_id_valid(&destination_change_id).map_err(|_| corrupt())?;
    identifier(&local_actor_id).map_err(|_| corrupt())?;
    if let Some(anchor_id) = &expected_anchor_id {
        change_id_valid(anchor_id).map_err(|_| corrupt())?;
    }
    if let Some(anchor_id) = &completed_anchor_id {
        change_id_valid(anchor_id).map_err(|_| corrupt())?;
    }
    Ok(ProjectSchemaSyncPrepared {
        step_id,
        kind,
        local_actor_id,
        expected_anchor_id,
        expected_epoch: u64::try_from(expected_epoch).map_err(|_| corrupt())?,
        source_receipt,
        destination_base,
        destination_change_id,
        request_json,
        completed_anchor_id,
    })
}

fn columns(row: &rusqlite::Row<'_>) -> rusqlite::Result<PreparedColumns> {
    Ok((
        row.get(0)?,
        row.get(1)?,
        row.get(2)?,
        row.get(3)?,
        row.get(4)?,
        row.get(5)?,
        row.get(6)?,
        row.get(7)?,
        row.get(8)?,
        row.get(9)?,
    ))
}

const SELECT: &str = "SELECT step_id,kind,local_actor_id,expected_anchor_id,expected_epoch,
    source_receipt,destination_base,destination_change_id,request_json,completed_anchor_id
    FROM knowledge_project_schema_prepared";

pub(super) fn by_step_id(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
    step_id: &str,
) -> ProjectSchemaStorageResult<Option<ProjectSchemaSyncPrepared>> {
    tx.query_row(
        &format!("{SELECT} WHERE sync_key=?1 AND step_id=?2"),
        params![binding.sync_key, step_id],
        columns,
    )
    .optional()
    .map_err(storage)?
    .map(decode)
    .transpose()
}

pub(super) fn pending(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
) -> ProjectSchemaStorageResult<Option<ProjectSchemaSyncPrepared>> {
    tx.query_row(
        &format!("{SELECT} WHERE sync_key=?1 AND completed_anchor_id IS NULL"),
        params![binding.sync_key],
        columns,
    )
    .optional()
    .map_err(storage)?
    .map(decode)
    .transpose()
}

/// Insert fenced to the observed cursor position. Re-preparing an identical
/// step replays; a different step for the same ID or a second pending step
/// conflicts. Multi-step initialization grouping is reserved: initialization_id
/// currently equals the step's own identity.
pub(super) fn insert(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
    cursor: &CursorRow,
    step: &NewStep<'_>,
) -> ProjectSchemaStorageResult<()> {
    change_id_valid(step.step_id)?;
    change_id_valid(step.destination_change_id)?;
    identifier(step.local_actor_id)?;
    if let Some(existing) = by_step_id(tx, binding, step.step_id)? {
        let identical = existing.kind == step.kind
            && existing.local_actor_id == step.local_actor_id
            && existing.expected_anchor_id == cursor.anchor_id
            && existing.expected_epoch == cursor.epoch
            && existing.source_receipt == step.source_receipt
            && existing.destination_base.as_deref() == step.destination_base
            && existing.destination_change_id == step.destination_change_id
            && existing.request_json == step.request_json;
        return if identical {
            Ok(())
        } else {
            Err(ProjectSchemaStorageError::SyncConflict)
        };
    }
    if pending(tx, binding)?.is_some() {
        return Err(ProjectSchemaStorageError::SyncConflict);
    }
    tx.execute(
        "INSERT INTO knowledge_project_schema_prepared
         (step_id,sync_key,initialization_id,local_actor_id,kind,expected_anchor_id,expected_epoch,
          source_receipt,destination_base,destination_change_id,request_json)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
        params![
            step.step_id,
            binding.sync_key,
            step.step_id,
            step.local_actor_id,
            step.kind.as_str(),
            cursor.anchor_id,
            cursor.epoch,
            step.source_receipt,
            step.destination_base,
            step.destination_change_id,
            step.request_json
        ],
    )
    .map_err(storage)?;
    Ok(())
}

pub(super) fn complete(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
    step_id: &str,
    anchor_id: &str,
) -> ProjectSchemaStorageResult<()> {
    let updated = tx
        .execute(
            "UPDATE knowledge_project_schema_prepared SET completed_anchor_id=?3
         WHERE sync_key=?1 AND step_id=?2 AND completed_anchor_id IS NULL",
            params![binding.sync_key, step_id, anchor_id],
        )
        .map_err(storage)?;
    if updated != 1 {
        return Err(ProjectSchemaStorageError::CorruptStorage);
    }
    Ok(())
}
