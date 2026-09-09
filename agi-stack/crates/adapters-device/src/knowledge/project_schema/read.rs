//! Canonical persisted records are validated before becoming public snapshots.
use agistack_core::project_schema::{ProjectSchemaDocument, ProjectSchemaError};
use rusqlite::{params, OptionalExtension, Row, Transaction};
use serde::Deserialize;
use serde_json::{json, Value};

use super::{
    canonical_document, change_id_valid, identifier, scoped_document, storage, KnowledgeScope,
    ProjectSchemaJournalPage, ProjectSchemaReceipt, ProjectSchemaStorageError,
    ProjectSchemaStorageResult,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReceiptBody {
    format_version: u32,
    actor_id: String,
    change_id: String,
    sequence: u32,
    document: Value,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RequestBody {
    command: String,
    tenant_id: String,
    project_id: String,
    actor_id: String,
    change_id: String,
    expected_revision: u32,
    document: Value,
}

pub(super) struct StoredChange {
    schema_id: String,
    revision: u32,
    actor_id: String,
    change_id: String,
    expected_revision: u32,
    request: String,
    receipt: String,
}

pub(super) fn row(row: &Row<'_>) -> rusqlite::Result<StoredChange> {
    Ok(StoredChange {
        schema_id: row.get(0)?,
        revision: row.get(1)?,
        actor_id: row.get(2)?,
        change_id: row.get(3)?,
        expected_revision: row.get(4)?,
        request: row.get(5)?,
        receipt: row.get(6)?,
    })
}

// Comparing with the canonical serialization also rejects duplicate keys in
// a tampered storage record, including keys inside opaque schema objects.
fn canonical_value(raw: &str) -> ProjectSchemaStorageResult<Value> {
    let value: Value =
        serde_json::from_str(raw).map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
    if serde_json::to_string(&value).map_err(storage)? != raw {
        return Err(ProjectSchemaStorageError::CorruptStorage);
    }
    Ok(value)
}

pub(super) fn new_receipt(
    actor_id: &str,
    change_id: &str,
    document: ProjectSchemaDocument,
) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
    identifier(actor_id)?;
    change_id_valid(change_id)?;
    Ok(ProjectSchemaReceipt {
        json: json!({"format_version":1,"actor_id":actor_id,"change_id":change_id,
            "sequence":document.revision(),"document":document.to_value()})
        .to_string(),
        actor_id: actor_id.into(),
        change_id: change_id.into(),
        document,
    })
}

pub(super) fn decode(
    scope: &KnowledgeScope,
    stored: &StoredChange,
) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
    let body: ReceiptBody = serde_json::from_value(canonical_value(&stored.receipt)?)
        .map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
    let request: RequestBody = serde_json::from_value(canonical_value(&stored.request)?)
        .map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
    let document = ProjectSchemaDocument::from_json(&body.document.to_string())
        .map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
    let submitted = ProjectSchemaDocument::from_json(&request.document.to_string())
        .map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
    if scoped_document(scope, &document).is_err()
        || identifier(&stored.actor_id).is_err()
        || change_id_valid(&stored.change_id).is_err()
        || body.format_version != 1
        || body.actor_id != stored.actor_id
        || body.change_id != stored.change_id
        || body.sequence != stored.revision
        || document.revision() != stored.revision
        || document.schema_id() != stored.schema_id
        || stored.expected_revision.checked_add(1) != Some(stored.revision)
        || request.actor_id != stored.actor_id
        || request.change_id != stored.change_id
        || request.expected_revision != stored.expected_revision
        || request.tenant_id != scope.tenant_id
        || request.project_id != scope.project_id
        || request.command
            != if stored.revision == 1 {
                "bootstrap"
            } else {
                "replace"
            }
        || canonical_document(&submitted)? != document
    {
        return Err(ProjectSchemaStorageError::CorruptStorage);
    }
    Ok(ProjectSchemaReceipt {
        json: stored.receipt.clone(),
        actor_id: body.actor_id,
        change_id: body.change_id,
        document,
    })
}

pub(super) fn receipt(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    actor_id: &str,
    change_id: &str,
) -> ProjectSchemaStorageResult<Option<(String, ProjectSchemaReceipt)>> {
    let stored = tx.query_row(
        "SELECT schema_id,revision,actor_id,change_id,expected_revision,request_json,receipt_json
         FROM knowledge_project_schema_changes
         WHERE tenant_id=?1 AND project_id=?2 AND actor_id=?3 AND change_id=?4",
        params![scope.tenant_id,scope.project_id,actor_id,change_id], row,
    ).optional().map_err(storage)?;
    stored
        .map(|stored| Ok((stored.request.clone(), decode(scope, &stored)?)))
        .transpose()
}

/// Re-derive a journaled receipt from its exact persisted JSON, requiring the
/// immutable journal itself to confirm the same actor, change and bytes.
pub(super) fn journal_receipt_by_json(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    json: &str,
) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
    let body: ReceiptBody = serde_json::from_value(canonical_value(json)?)
        .map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
    let Some((_, receipt)) = receipt(tx, scope, &body.actor_id, &body.change_id)? else {
        return Err(ProjectSchemaStorageError::CorruptStorage);
    };
    if receipt.as_json() != json || receipt.sequence() != body.sequence {
        return Err(ProjectSchemaStorageError::CorruptStorage);
    }
    Ok(receipt)
}

pub(super) fn revision(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    revision: u32,
) -> ProjectSchemaStorageResult<ProjectSchemaReceipt> {
    let stored = tx.query_row(
        "SELECT schema_id,revision,actor_id,change_id,expected_revision,request_json,receipt_json
         FROM knowledge_project_schema_changes WHERE tenant_id=?1 AND project_id=?2 AND revision=?3",
        params![scope.tenant_id,scope.project_id,revision], row,
    ).optional().map_err(storage)?.ok_or(ProjectSchemaStorageError::CorruptStorage)?;
    decode(scope, &stored)
}

pub(super) fn head(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
) -> ProjectSchemaStorageResult<Option<ProjectSchemaDocument>> {
    let head: Option<(String, u32, bool, String)> = tx
        .query_row(
            "SELECT schema_id,revision,deleted,document_json FROM knowledge_project_schema_heads
         WHERE tenant_id=?1 AND project_id=?2",
            params![scope.tenant_id, scope.project_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .optional()
        .map_err(storage)?;
    let latest: Option<u32> = tx.query_row(
        "SELECT max(revision) FROM knowledge_project_schema_changes WHERE tenant_id=?1 AND project_id=?2",
        params![scope.tenant_id,scope.project_id], |r|r.get(0),
    ).map_err(storage)?;
    let Some((schema_id, rev, deleted, raw)) = head else {
        return if latest.is_none() {
            Ok(None)
        } else {
            Err(ProjectSchemaStorageError::CorruptStorage)
        };
    };
    let accepted = revision(tx, scope, rev)?;
    let document = accepted.document;
    if latest != Some(rev)
        || document.schema_id() != schema_id
        || document.is_deleted() != deleted
        || serde_json::to_string(&document.to_value()).map_err(storage)? != raw
    {
        return Err(ProjectSchemaStorageError::CorruptStorage);
    }
    Ok(Some(document))
}

pub(super) fn changes(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    after: u32,
    limit: u32,
) -> ProjectSchemaStorageResult<ProjectSchemaJournalPage> {
    let current = head(tx, scope)?;
    let upper_revision = current.as_ref().map_or(0, ProjectSchemaDocument::revision);
    if after > upper_revision {
        return Err(ProjectSchemaError::RevisionConflict.into());
    }
    let mut previous = if after == 0 {
        None
    } else {
        Some(revision(tx, scope, after)?.document)
    };
    let mut statement = tx.prepare(
        "SELECT schema_id,revision,actor_id,change_id,expected_revision,request_json,receipt_json
         FROM knowledge_project_schema_changes WHERE tenant_id=?1 AND project_id=?2
         AND revision>?3 AND revision<=?4 ORDER BY revision LIMIT ?5",
    ).map_err(storage)?;
    let rows = statement
        .query_map(
            params![
                scope.tenant_id,
                scope.project_id,
                after,
                upper_revision,
                limit
            ],
            row,
        )
        .map_err(storage)?;
    let mut items = Vec::new();
    for row in rows {
        let receipt = decode(scope, &row.map_err(storage)?)?;
        receipt
            .document
            .validate_successor(
                previous.as_ref(),
                previous.as_ref().map_or(0, ProjectSchemaDocument::revision),
            )
            .map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
        if !matches!(current.as_ref(), Some(head) if head.schema_id() == receipt.document.schema_id())
        {
            return Err(ProjectSchemaStorageError::CorruptStorage);
        }
        previous = Some(receipt.document.clone());
        items.push(receipt);
    }
    if items.len() != usize::try_from(limit.min(upper_revision - after)).map_err(storage)? {
        return Err(ProjectSchemaStorageError::CorruptStorage);
    }
    Ok(ProjectSchemaJournalPage {
        upper_revision,
        items,
    })
}
