//! Additive schema 15. No project row or schema head is created by migration.
use rusqlite::Transaction;

use super::super::{storage, KnowledgeError, KnowledgeResult};

pub(in super::super) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous < 15 {
        tx.execute_batch(include_str!("schema.sql"))
            .map_err(storage)?;
    }
    let count: u32 = tx.query_row(
        "SELECT count(*) FROM sqlite_master WHERE
         (type='table' AND name IN ('knowledge_project_schema_heads','knowledge_project_schema_changes'))
         OR (type='trigger' AND name IN ('knowledge_project_schema_change_guard',
           'knowledge_project_schema_change_append','knowledge_project_schema_change_immutable',
           'knowledge_project_schema_change_no_delete','knowledge_project_schema_head_insert_guard',
           'knowledge_project_schema_head_update_guard','knowledge_project_schema_head_no_delete'))",
        [], |r|r.get(0),
    ).map_err(storage)?;
    if count != 9 {
        return Err(KnowledgeError::Storage(
            "project schema storage is missing".into(),
        ));
    }
    Ok(())
}
