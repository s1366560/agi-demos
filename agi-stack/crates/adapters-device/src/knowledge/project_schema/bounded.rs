//! Bound history before materializing further documents, within one read snapshot.
use agistack_core::project_schema::{ProjectSchemaDocument, ProjectSchemaError};
use rusqlite::{params, Transaction};

use super::{
    read, storage, KnowledgeScope, ProjectSchemaHistoryPage, ProjectSchemaStorageError,
    ProjectSchemaStorageResult,
};

pub(super) fn history(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    after: u32,
    limit: u32,
    item_budget: &dyn Fn(&ProjectSchemaHistoryPage) -> ProjectSchemaStorageResult<usize>,
) -> ProjectSchemaStorageResult<ProjectSchemaHistoryPage> {
    let head = read::head(tx, scope)?;
    let upper_revision = head.as_ref().map_or(0, ProjectSchemaDocument::revision);
    if after > upper_revision {
        return Err(ProjectSchemaError::RevisionConflict.into());
    }
    let mut page = ProjectSchemaHistoryPage {
        schema_id: head.as_ref().map(|doc| doc.schema_id().to_owned()),
        after_revision: after,
        upper_revision,
        next_after_revision: after,
        has_more: after < upper_revision,
        items: Vec::new(),
    };
    let mut remaining = item_budget(&page)?;
    let mut previous = if after == 0 {
        None
    } else {
        Some(read::revision(tx, scope, after)?.document)
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
            read::row,
        )
        .map_err(storage)?;
    let mut byte_limited = false;
    for stored in rows {
        let receipt = read::decode(scope, &stored.map_err(storage)?)?;
        receipt
            .document()
            .validate_successor(
                previous.as_ref(),
                previous.as_ref().map_or(0, ProjectSchemaDocument::revision),
            )
            .map_err(|_| ProjectSchemaStorageError::CorruptStorage)?;
        if page.schema_id.as_deref() != Some(receipt.document().schema_id()) {
            return Err(ProjectSchemaStorageError::CorruptStorage);
        }
        // Receipt JSON is canonical UTF-8, embedded as an object, not an escaped
        // JSON string. The caller's empty envelope already accounts for `[]`.
        let cost = receipt
            .as_json()
            .len()
            .checked_add(usize::from(!page.items.is_empty()))
            .ok_or(ProjectSchemaStorageError::ResponseTooLarge)?;
        if cost > remaining {
            if page.items.is_empty() {
                return Err(ProjectSchemaStorageError::ResponseTooLarge);
            }
            byte_limited = true;
            break;
        }
        remaining -= cost;
        page.next_after_revision = receipt.sequence();
        previous = Some(receipt.document().clone());
        page.items.push(receipt);
    }
    if !byte_limited
        && page.items.len()
            != usize::try_from(limit.min(upper_revision - after)).map_err(storage)?
    {
        return Err(ProjectSchemaStorageError::CorruptStorage);
    }
    page.has_more = page.next_after_revision < upper_revision;
    Ok(page)
}
