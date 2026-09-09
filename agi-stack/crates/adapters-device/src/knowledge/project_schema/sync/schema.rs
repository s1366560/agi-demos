//! Additive schema 16; existing bindings, journals and heads are unchanged.
use rusqlite::Transaction;

use super::super::super::{storage, KnowledgeError, KnowledgeResult};

pub(in super::super::super) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous < 16 {
        tx.execute_batch(include_str!("schema.sql"))
            .map_err(storage)?;
    }
    let count: u32 = tx.query_row(
        "SELECT count(*) FROM sqlite_master WHERE name IN (
         'knowledge_project_schema_sync_cursors','knowledge_project_schema_prepared',
         'knowledge_project_schema_sync_anchors','knowledge_project_schema_one_pending',
         'knowledge_project_schema_sync_cursor_insert','knowledge_project_schema_sync_cursor_update',
         'knowledge_project_schema_sync_cursor_no_delete','knowledge_project_schema_prepared_insert',
         'knowledge_project_schema_prepared_update','knowledge_project_schema_prepared_no_delete',
         'knowledge_project_schema_anchor_insert','knowledge_project_schema_anchor_no_update',
         'knowledge_project_schema_anchor_no_delete')", [], |row| row.get(0),
    ).map_err(storage)?;
    if count != 13 {
        return Err(KnowledgeError::Storage(
            "project schema sync storage is missing".into(),
        ));
    }
    Ok(())
}
