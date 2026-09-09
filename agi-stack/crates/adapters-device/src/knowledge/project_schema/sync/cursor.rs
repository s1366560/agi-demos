//! Sync cursor and anchor persistence. SQLite triggers enforce the binding,
//! transition chain and immutability; these helpers pre-check the same facts
//! so callers receive typed errors instead of trigger aborts.
use agistack_core::project_schema::cloud_rpc::CloudSchemaReceipt;
use rusqlite::{params, OptionalExtension, Transaction};

use super::super::{read, storage, ProjectSchemaReceipt};
use super::{
    change_id_valid, prepared, ProjectSchemaStorageError, ProjectSchemaStorageResult,
    ProjectSchemaSyncAnchor, ProjectSchemaSyncAnchorKind, ProjectSchemaSyncBinding,
    ProjectSchemaSyncImportedSide, ProjectSchemaSyncState,
};

#[derive(Debug, Clone)]
pub(super) struct CursorRow {
    pub(super) anchor_id: Option<String>,
    pub(super) epoch: u64,
    pub(super) native_after: u32,
    pub(super) cloud_after: u32,
}

pub(super) struct NewAnchor<'a> {
    pub(super) anchor_id: &'a str,
    pub(super) kind: ProjectSchemaSyncAnchorKind,
    pub(super) imported: ProjectSchemaSyncImportedSide,
    pub(super) native_receipt: Option<&'a ProjectSchemaReceipt>,
    pub(super) cloud_receipt: &'a CloudSchemaReceipt,
}

type CursorColumns = (
    Option<String>,
    i64,
    i64,
    i64,
    String,
    String,
    String,
    String,
    String,
    String,
    String,
);

type AnchorColumns = (
    Option<String>,
    String,
    String,
    Option<String>,
    String,
    i64,
    i64,
    String,
    String,
);

fn counter(value: i64) -> ProjectSchemaStorageResult<u32> {
    u32::try_from(value).map_err(|_| ProjectSchemaStorageError::CorruptStorage)
}

/// Mirror of the cursor insert trigger's binding requirement.
fn binding_exists(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
) -> ProjectSchemaStorageResult<bool> {
    let count: u32 = tx
        .query_row(
            "SELECT count(*) FROM knowledge_sync_links l JOIN knowledge_sync_targets t
          ON t.tenant_id=l.tenant_id AND t.project_id=l.project_id
         WHERE l.tenant_id=?1 AND l.project_id=?2 AND t.authority=?3
           AND l.remote_tenant_id=?4 AND l.remote_project_id=?5 AND l.remote_actor_id=?6",
            params![
                binding.scope.tenant_id,
                binding.scope.project_id,
                binding.authority,
                binding.remote_tenant_id,
                binding.remote_project_id,
                binding.remote_actor_id
            ],
            |row| row.get(0),
        )
        .map_err(storage)?;
    Ok(count == 1)
}

pub(super) fn row(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
) -> ProjectSchemaStorageResult<Option<CursorRow>> {
    let stored: Option<CursorColumns> = tx.query_row(
        "SELECT anchor_id,epoch,native_after,cloud_after,
                tenant_id,project_id,authority,remote_tenant_id,remote_project_id,remote_actor_id,schema_id
         FROM knowledge_project_schema_sync_cursors WHERE sync_key=?1",
        params![binding.sync_key],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?,
            row.get(5)?, row.get(6)?, row.get(7)?, row.get(8)?, row.get(9)?, row.get(10)?)),
    ).optional().map_err(storage)?;
    let Some((
        anchor_id,
        epoch,
        native_after,
        cloud_after,
        tenant_id,
        project_id,
        authority,
        remote_tenant_id,
        remote_project_id,
        remote_actor_id,
        schema_id,
    )) = stored
    else {
        return Ok(None);
    };
    if tenant_id != binding.scope.tenant_id
        || project_id != binding.scope.project_id
        || authority != binding.authority
        || remote_tenant_id != binding.remote_tenant_id
        || remote_project_id != binding.remote_project_id
        || remote_actor_id != binding.remote_actor_id
        || schema_id != binding.schema_id
    {
        return Err(ProjectSchemaStorageError::SyncConflict);
    }
    if let Some(anchor_id) = &anchor_id {
        change_id_valid(anchor_id).map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
    }
    Ok(Some(CursorRow {
        anchor_id,
        epoch: u64::try_from(epoch).map_err(|_| ProjectSchemaStorageError::CorruptStorage)?,
        native_after: counter(native_after)?,
        cloud_after: counter(cloud_after)?,
    }))
}

/// Begin is replay-safe for an identical binding. The durable Memory sync
/// association must already exist; schema sync never creates or widens it.
pub(super) fn begin(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
) -> ProjectSchemaStorageResult<CursorRow> {
    if let Some(existing) = row(tx, binding)? {
        return Ok(existing);
    }
    if !binding_exists(tx, binding)? {
        return Err(ProjectSchemaStorageError::SyncConflict);
    }
    tx.execute(
        "INSERT INTO knowledge_project_schema_sync_cursors
         (sync_key,tenant_id,project_id,authority,remote_tenant_id,remote_project_id,remote_actor_id,schema_id)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
        params![binding.sync_key, binding.scope.tenant_id, binding.scope.project_id,
            binding.authority, binding.remote_tenant_id, binding.remote_project_id,
            binding.remote_actor_id, binding.schema_id],
    ).map_err(storage)?;
    row(tx, binding)?.ok_or(ProjectSchemaStorageError::CorruptStorage)
}

pub(super) fn anchor(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
    anchor_id: &str,
) -> ProjectSchemaStorageResult<ProjectSchemaSyncAnchor> {
    let stored: Option<AnchorColumns> = tx
        .query_row(
            "SELECT predecessor_anchor_id,producing_step_id,kind,native_receipt,cloud_receipt,
                native_revision,cloud_revision,imported_side,sync_key
         FROM knowledge_project_schema_sync_anchors WHERE anchor_id=?1",
            params![anchor_id],
            |row| {
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
                ))
            },
        )
        .optional()
        .map_err(storage)?;
    let Some((
        predecessor,
        producing_step_id,
        kind,
        native_raw,
        cloud_raw,
        native_revision,
        cloud_revision,
        imported,
        sync_key,
    )) = stored
    else {
        return Err(ProjectSchemaStorageError::CorruptStorage);
    };
    let corrupt = || ProjectSchemaStorageError::CorruptStorage;
    if sync_key != binding.sync_key {
        return Err(corrupt());
    }
    change_id_valid(anchor_id).map_err(|_| corrupt())?;
    change_id_valid(&producing_step_id).map_err(|_| corrupt())?;
    if let Some(predecessor) = &predecessor {
        change_id_valid(predecessor).map_err(|_| corrupt())?;
    }
    let kind = ProjectSchemaSyncAnchorKind::from_str(&kind).ok_or_else(corrupt)?;
    let imported = ProjectSchemaSyncImportedSide::from_str(&imported).ok_or_else(corrupt)?;
    let cloud_receipt = CloudSchemaReceipt::from_json(
        &cloud_raw,
        &binding.remote_tenant_id,
        &binding.remote_project_id,
    )
    .map_err(|_| corrupt())?;
    if cloud_receipt.document().schema_id() != binding.schema_id
        || cloud_receipt.revision() != counter(cloud_revision)?
    {
        return Err(corrupt());
    }
    let native_revision = counter(native_revision)?;
    let native_receipt = match (kind, native_raw) {
        (ProjectSchemaSyncAnchorKind::Pair, Some(raw)) => {
            let receipt = read::revision(tx, &binding.scope, native_revision)?;
            if receipt.as_json() != raw {
                return Err(corrupt());
            }
            Some(receipt)
        }
        (
            ProjectSchemaSyncAnchorKind::SourceSeed | ProjectSchemaSyncAnchorKind::DestinationSeed,
            None,
        ) => {
            if native_revision != 0 || cloud_receipt.revision() != 1 {
                return Err(corrupt());
            }
            None
        }
        _ => return Err(corrupt()),
    };
    // The completed prepared intent must point back at this exact acceptance.
    let completed: Option<String> = tx
        .query_row(
            "SELECT completed_anchor_id FROM knowledge_project_schema_prepared WHERE step_id=?1",
            params![producing_step_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    if completed.as_deref() != Some(anchor_id) {
        return Err(corrupt());
    }
    Ok(ProjectSchemaSyncAnchor {
        anchor_id: anchor_id.into(),
        predecessor_anchor_id: predecessor,
        producing_step_id,
        kind,
        native_receipt,
        cloud_receipt,
        imported_side: imported,
    })
}

/// Insert the acceptance mapping, complete its prepared intent and advance the
/// cursor epoch. The triggers verify the full chain against the live tables.
pub(super) fn accept_anchor(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
    cursor: &CursorRow,
    step_id: &str,
    anchor: &NewAnchor<'_>,
) -> ProjectSchemaStorageResult<()> {
    let NewAnchor {
        anchor_id,
        kind,
        imported,
        native_receipt,
        cloud_receipt,
    } = *anchor;
    change_id_valid(anchor_id)?;
    let native_revision = native_receipt.map_or(0, |receipt| receipt.document().revision());
    let cloud_revision = cloud_receipt.revision();
    let valid = match kind {
        ProjectSchemaSyncAnchorKind::Pair => native_receipt.is_some() && native_revision > 0,
        ProjectSchemaSyncAnchorKind::SourceSeed | ProjectSchemaSyncAnchorKind::DestinationSeed => {
            native_receipt.is_none() && cloud_revision == 1
        }
    };
    if !valid {
        return Err(ProjectSchemaStorageError::InvalidInput);
    }
    tx.execute(
        "INSERT INTO knowledge_project_schema_sync_anchors
         (anchor_id,sync_key,producing_step_id,predecessor_anchor_id,kind,native_receipt,cloud_receipt,
          native_revision,cloud_revision,imported_side)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
        params![anchor_id, binding.sync_key, step_id, cursor.anchor_id, kind.as_str(),
            native_receipt.map(ProjectSchemaReceipt::as_json), cloud_receipt.as_json(),
            native_revision, cloud_revision, imported.as_str()],
    ).map_err(storage)?;
    prepared::complete(tx, binding, step_id, anchor_id)?;
    let (native_after, cloud_after) = match kind {
        ProjectSchemaSyncAnchorKind::Pair => (native_revision, cloud_revision),
        ProjectSchemaSyncAnchorKind::SourceSeed => (0, 0),
        ProjectSchemaSyncAnchorKind::DestinationSeed => (0, cloud_revision),
    };
    let updated = tx
        .execute(
            "UPDATE knowledge_project_schema_sync_cursors
         SET anchor_id=?2, epoch=epoch+1, native_after=?3, cloud_after=?4
         WHERE sync_key=?1 AND epoch=?5",
            params![
                binding.sync_key,
                anchor_id,
                native_after,
                cloud_after,
                cursor.epoch
            ],
        )
        .map_err(storage)?;
    if updated != 1 {
        return Err(ProjectSchemaStorageError::SyncConflict);
    }
    Ok(())
}

pub(super) fn state(
    tx: &Transaction<'_>,
    binding: &ProjectSchemaSyncBinding,
) -> ProjectSchemaStorageResult<Option<ProjectSchemaSyncState>> {
    let Some(cursor) = row(tx, binding)? else {
        return Ok(None);
    };
    let head = cursor
        .anchor_id
        .as_deref()
        .map(|anchor_id| anchor(tx, binding, anchor_id))
        .transpose()?;
    Ok(Some(ProjectSchemaSyncState {
        epoch: cursor.epoch,
        native_after: cursor.native_after,
        cloud_after: cursor.cloud_after,
        head,
    }))
}
