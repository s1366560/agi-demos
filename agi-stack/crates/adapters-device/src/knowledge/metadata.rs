//! Upgrade scoped documents from trusted metadata retained by sync. Prepared
//! HTTP requests and their receipts are immutable and are never rewritten.

use rusqlite::{params, OptionalExtension, Transaction};
use serde_json::{Map, Value};

use super::{storage, KnowledgeError, KnowledgeResult};

pub(super) fn migrate(tx: &Transaction<'_>, previous_version: i64) -> KnowledgeResult<()> {
    if previous_version >= 12 {
        return Ok(());
    }
    let mut statement = tx
        .prepare("SELECT tenant_id,project_id,id,payload FROM knowledge_memories")
        .map_err(storage)?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
            ))
        })
        .map_err(storage)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(storage)?;
    for (tenant, project, id, payload) in rows {
        let metadata = trusted_current(tx, &tenant, &project, &id)?;
        let payload = extend(&payload, metadata)?;
        tx.execute("UPDATE knowledge_memories SET payload=?4 WHERE tenant_id=?1 AND project_id=?2 AND id=?3",
            params![tenant,project,id,payload]).map_err(storage)?;
    }
    // Unprepared changes previously used their explicit outbox metadata, or the
    // retained remote baseline at preparation. Materialize exactly that source.
    // Historical changes without such evidence acquire only an empty object.
    let mut statement = tx
        .prepare(
            "SELECT c.sequence,c.payload,m.metadata_json,
                CASE WHEN o.sequence IS NOT NULL AND o.request_json IS NULL THEN r.version_json ELSE NULL END
         FROM knowledge_processing_changes c
         LEFT JOIN knowledge_sync_outbox_metadata m ON m.sequence=c.sequence
         LEFT JOIN knowledge_pending_outbox o ON o.sequence=c.sequence
         LEFT JOIN knowledge_sync_remote_versions r ON r.tenant_id=c.tenant_id
           AND r.project_id=c.project_id AND r.memory_id=c.memory_id",
        )
        .map_err(storage)?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, u64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Option<String>>(3)?,
            ))
        })
        .map_err(storage)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(storage)?;
    for (sequence, payload, explicit, baseline) in rows {
        let metadata = retained(explicit, baseline)?;
        tx.execute(
            "UPDATE knowledge_processing_changes SET payload=?2 WHERE sequence=?1",
            params![sequence, extend(&payload, metadata)?],
        )
        .map_err(storage)?;
    }
    Ok(())
}

fn trusted_current(
    tx: &Transaction<'_>,
    tenant: &str,
    project: &str,
    id: &str,
) -> KnowledgeResult<Map<String, Value>> {
    let exact: Option<String> = tx
        .query_row(
            "SELECT m.metadata_json FROM knowledge_sync_outbox_metadata m
         JOIN knowledge_processing_changes c ON c.sequence=m.sequence
         JOIN knowledge_memories d ON d.tenant_id=c.tenant_id AND d.project_id=c.project_id
           AND d.id=c.memory_id AND d.revision=c.revision
         WHERE c.tenant_id=?1 AND c.project_id=?2 AND c.memory_id=?3",
            params![tenant, project, id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    if let Some(exact) = exact {
        return retained(Some(exact), None);
    }
    let explicit: Option<String> = tx
        .query_row(
            "SELECT m.metadata_json FROM knowledge_sync_outbox_metadata m
         JOIN knowledge_pending_outbox o ON o.sequence=m.sequence
         WHERE o.tenant_id=?1 AND o.project_id=?2 AND o.memory_id=?3
         ORDER BY o.sequence DESC LIMIT 1",
            params![tenant, project, id],
            |r| r.get(0),
        )
        .optional()
        .map_err(storage)?;
    let baseline:Option<String> = tx.query_row(
        "SELECT version_json FROM knowledge_sync_remote_versions WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3",
        params![tenant,project,id],|r|r.get(0)
    ).optional().map_err(storage)?;
    retained(explicit, baseline)
}

fn retained(
    explicit: Option<String>,
    baseline: Option<String>,
) -> KnowledgeResult<Map<String, Value>> {
    if let Some(explicit) = explicit {
        return serde_json::from_str(&explicit).map_err(storage);
    }
    baseline
        .map(|json| {
            let version: agistack_core::knowledge::sync::push::RemoteMemoryVersion =
                serde_json::from_str(&json).map_err(storage)?;
            version.validate()?;
            Ok(version.content.metadata)
        })
        .transpose()
        .map(|v| v.unwrap_or_default())
}

fn extend(payload: &str, metadata: Map<String, Value>) -> KnowledgeResult<String> {
    let mut value: Value = serde_json::from_str(payload).map_err(storage)?;
    value
        .as_object_mut()
        .ok_or(KnowledgeError::InvalidInput)?
        .entry("metadata")
        .or_insert(Value::Object(metadata));
    serde_json::to_string(&value).map_err(storage)
}
