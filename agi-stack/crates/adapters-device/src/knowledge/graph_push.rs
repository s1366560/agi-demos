//! Cloud push of derived records. Mirrors the memory push contract: immutable
//! persisted requests, revision-checked receipts, durable conflict pauses.

use agistack_core::knowledge::sync::graph::{
    KnowledgeGraphPushReceipt, KnowledgeGraphPushRepository, RemoteGraphContent,
    RemoteGraphVersion,
};
use agistack_core::knowledge::sync::push::{
    KnowledgeSyncTarget, PreparedKnowledgePush, MAX_REMOTE_REVISION,
};
use rusqlite::{Transaction, TransactionBehavior};
use serde_json::{json, Value};

use super::*;

#[path = "graph_push_receipts.rs"]
mod receipts;

/// A verified graph journal event for our own change recovers a lost HTTP
/// response without creating a false conflict or replacing local records.
pub(super) fn accept_journal_receipt(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    target: &KnowledgeSyncTarget,
    change_id: &str,
    sequence: u64,
    version: &Value,
) -> KnowledgeResult<()> {
    let local_sequence: Option<u64> = tx
        .query_row(
            "SELECT sequence FROM knowledge_sync_graph_outbox
             WHERE tenant_id=?1 AND project_id=?2 AND change_id=?3",
            params![scope.tenant_id, scope.project_id, change_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    if let Some(local_sequence) = local_sequence {
        receipts::accept(
            tx,
            scope,
            target,
            local_sequence,
            json!({
                "replayed": false,
                "receipt": {"status":"applied", "change_id":change_id,
                            "sequence":sequence, "version":version}
            }),
            None,
        )?;
    }
    Ok(())
}

pub(super) fn baseline(
    conn: &Connection,
    scope: &KnowledgeScope,
    object_id: &str,
) -> KnowledgeResult<Option<Value>> {
    let json: Option<String> = conn
        .query_row(
            "SELECT version_json FROM knowledge_sync_graph_remote_versions
             WHERE tenant_id=?1 AND project_id=?2 AND object_id=?3",
            params![scope.tenant_id, scope.project_id, object_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    json.map(|json| serde_json::from_str(&json).map_err(storage))
        .transpose()
}

fn prepared_request(
    change_id: &str,
    object_id: &str,
    content: &RemoteGraphContent,
    deleted: bool,
    baseline: Option<Value>,
) -> KnowledgeResult<String> {
    let previous: Option<RemoteGraphVersion> = baseline
        .map(|value| serde_json::from_value(value).map_err(storage))
        .transpose()?;
    if let Some(previous) = &previous {
        previous.validate()?;
    }
    let revision = previous.as_ref().map_or(0, |version| version.revision);
    if revision >= MAX_REMOTE_REVISION || (deleted && revision == 0) {
        return Err(KnowledgeError::Conflict);
    }
    valid_sync_identifier(object_id)?;
    if !deleted {
        content.validate()?;
    }
    serde_json::to_string(&json!({"change_id":change_id,"object_id":object_id,
        "operation":if deleted {"delete"} else if revision == 0 {"create"} else {"update"},
        "expected_revision":revision,"content":if deleted {Value::Null} else {serde_json::to_value(content).map_err(storage)?}
    }))
    .map_err(storage)
}

fn valid_sync_identifier(value: &str) -> KnowledgeResult<()> {
    if value.is_empty() || value.trim() != value || value.chars().count() > 512 {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

impl SqliteKnowledgeRepository {
    /// Synchronous form for a trusted caller holding its identity fence
    /// through commit. No external or async work occurs.
    pub fn accept_graph_push_receipt_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        local_sequence: u64,
        response: Value,
        conflict: Option<Value>,
    ) -> KnowledgeResult<KnowledgeGraphPushReceipt> {
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        super::push::check_target(&tx, scope, target, false)?;
        let result = receipts::accept(&tx, scope, target, local_sequence, response, conflict)?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }
}

#[async_trait]
impl KnowledgeGraphPushRepository for SqliteKnowledgeRepository {
    async fn prepare_graph_push(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
    ) -> KnowledgeResult<Option<PreparedKnowledgePush>> {
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        super::push::check_target(&tx, scope, target, true)?;
        let candidate: Option<(u64, String, String, String, String, Option<String>)> = tx
            .query_row(
                "SELECT c.sequence, c.change_id, c.object_id, c.payload, c.operation, c.request_json
                 FROM knowledge_pending_graph_outbox c
                 WHERE c.tenant_id=?1 AND c.project_id=?2 AND c.receipt_json IS NULL
                   AND (c.request_json IS NOT NULL OR NOT EXISTS (
                     SELECT 1 FROM knowledge_active_graph_pull_conflicts pc
                     WHERE pc.tenant_id=c.tenant_id AND pc.project_id=c.project_id
                       AND pc.object_id=c.object_id
                   ))
                   AND NOT EXISTS (
                     SELECT 1 FROM knowledge_pending_graph_outbox ec
                     WHERE ec.tenant_id=c.tenant_id AND ec.project_id=c.project_id
                       AND ec.object_id=c.object_id AND ec.sequence<c.sequence
                   )
                 ORDER BY (c.request_json IS NULL), c.sequence LIMIT 1",
                params![scope.tenant_id, scope.project_id],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                    ))
                },
            )
            .optional()
            .map_err(storage)?;
        let Some((local_sequence, change_id, object_id, payload, operation, existing)) = candidate
        else {
            tx.commit().map_err(storage)?;
            return Ok(None);
        };
        let request_json = if let Some(existing) = existing {
            existing
        } else {
            let content: RemoteGraphContent = serde_json::from_str(&payload).map_err(storage)?;
            let request = prepared_request(
                &change_id,
                &object_id,
                &content,
                operation == "delete",
                baseline(&tx, scope, &object_id)?,
            )?;
            tx.execute(
                "INSERT INTO knowledge_sync_graph_pushes(sequence,request_json) VALUES(?1,?2)",
                params![local_sequence, request],
            )
            .map_err(storage)?;
            request
        };
        tx.commit().map_err(storage)?;
        Ok(Some(PreparedKnowledgePush {
            local_sequence,
            change_id,
            request_json,
        }))
    }

    async fn accept_graph_push_receipt(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        local_sequence: u64,
        response: Value,
        conflict: Option<Value>,
    ) -> KnowledgeResult<KnowledgeGraphPushReceipt> {
        self.accept_graph_push_receipt_durable(scope, target, local_sequence, response, conflict)
    }

    async fn remote_graph_baseline(
        &self,
        scope: &KnowledgeScope,
        object_id: &str,
    ) -> KnowledgeResult<Option<Value>> {
        validate(scope, object_id)?;
        let conn = self.conn.lock().map_err(storage)?;
        baseline(&conn, scope, object_id)
    }

    async fn graph_push_conflicts(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>> {
        validate(scope, "graph push conflicts")?;
        if !(1..=200).contains(&limit) {
            return Err(KnowledgeError::InvalidInput);
        }
        let conn = self.conn.lock().map_err(storage)?;
        let mut statement = conn
            .prepare(
                "SELECT conflict_json FROM knowledge_unsettled_graph_pushes
                 WHERE tenant_id=?1 AND project_id=?2 AND conflict_json IS NOT NULL
                 ORDER BY sequence LIMIT ?3",
            )
            .map_err(storage)?;
        let rows = statement
            .query_map(
                params![scope.tenant_id, scope.project_id, limit as i64],
                |row| row.get::<_, String>(0),
            )
            .map_err(storage)?;
        rows.map(|row| serde_json::from_str(&row.map_err(storage)?).map_err(storage))
            .collect()
    }
}
