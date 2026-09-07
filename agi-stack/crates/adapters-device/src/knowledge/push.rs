use agistack_core::knowledge::sync::push::{
    valid_identifier, KnowledgePushReceipt, KnowledgePushRepository, KnowledgeSyncTarget,
    PreparedKnowledgePush, RemoteMemoryContent, RemoteMemoryVersion, MAX_REMOTE_REVISION,
};
use rusqlite::{Transaction, TransactionBehavior};
use serde_json::{json, Value};

use super::*;

#[path = "push_receipts.rs"]
mod receipts;

impl SqliteKnowledgeRepository {
    /// Synchronous form for a trusted caller that must hold its identity fence
    /// until the receipt and baseline commit. No external or async work occurs.
    pub fn accept_push_receipt_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        local_sequence: u64,
        response: Value,
        conflict: Option<Value>,
    ) -> KnowledgeResult<KnowledgePushReceipt> {
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        check_target(&tx, scope, target, false)?;
        let result = receipts::accept(&tx, scope, target, local_sequence, response, conflict)?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }
}

pub(super) fn migrate(tx: &Transaction<'_>, previous_version: i64) -> KnowledgeResult<()> {
    if previous_version >= 4 {
        let count: i64 = tx
            .query_row(
                "SELECT count(*) FROM sqlite_master
                 WHERE type='table' AND name IN (
                    'knowledge_sync_targets',
                    'knowledge_sync_pushes',
                    'knowledge_sync_remote_versions'
                 )",
                [],
                |row| row.get(0),
            )
            .map_err(storage)?;
        if count != 3 {
            return Err(KnowledgeError::Storage(
                "knowledge push tables are missing".into(),
            ));
        }
    }
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS knowledge_sync_targets (
            tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, authority TEXT NOT NULL,
            PRIMARY KEY(tenant_id,project_id)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_pushes (
            sequence INTEGER PRIMARY KEY, request_json TEXT NOT NULL,
            receipt_json TEXT, conflict_json TEXT,
            FOREIGN KEY(sequence) REFERENCES knowledge_sync_outbox(sequence)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_remote_versions (
            tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, memory_id TEXT NOT NULL,
            version_json TEXT NOT NULL,
            PRIMARY KEY(tenant_id,project_id,memory_id)
         );",
    )
    .map_err(storage)
}

fn check_target(
    conn: &Connection,
    scope: &KnowledgeScope,
    target: &KnowledgeSyncTarget,
    bind: bool,
) -> KnowledgeResult<()> {
    validate(scope, "push")?;
    valid_identifier(&target.authority)?;
    let stored: Option<(String, String, String)> = conn
        .query_row(
            "SELECT remote_tenant_id, remote_project_id, remote_actor_id
             FROM knowledge_sync_links WHERE tenant_id=?1 AND project_id=?2",
            params![scope.tenant_id, scope.project_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()
        .map_err(storage)?;
    if stored
        != Some((
            target.link.remote_tenant_id.clone(),
            target.link.remote_project_id.clone(),
            target.link.remote_actor_id.clone(),
        ))
    {
        return Err(KnowledgeError::Conflict);
    }
    if bind {
        conn.execute(
            "INSERT INTO knowledge_sync_targets(tenant_id, project_id, authority)
             VALUES(?1, ?2, ?3) ON CONFLICT DO NOTHING",
            params![scope.tenant_id, scope.project_id, target.authority],
        )
        .map_err(storage)?;
    }
    let authority: Option<String> = conn
        .query_row(
            "SELECT authority FROM knowledge_sync_targets WHERE tenant_id=?1 AND project_id=?2",
            params![scope.tenant_id, scope.project_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    if authority.as_deref() != Some(&target.authority) {
        return Err(KnowledgeError::Conflict);
    }
    Ok(())
}

fn baseline(conn: &Connection, scope: &KnowledgeScope, id: &str) -> KnowledgeResult<Option<Value>> {
    let json: Option<String> = conn
        .query_row(
            "SELECT version_json FROM knowledge_sync_remote_versions
             WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3",
            params![scope.tenant_id, scope.project_id, id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    json.map(|json| serde_json::from_str(&json).map_err(storage))
        .transpose()
}

fn prepared_request(
    change_id: &str,
    local: &Memory,
    deleted: bool,
    baseline: Option<Value>,
) -> KnowledgeResult<String> {
    let previous: Option<RemoteMemoryVersion> = baseline
        .map(|value| serde_json::from_value(value).map_err(storage))
        .transpose()?;
    if let Some(previous) = &previous {
        previous.validate()?;
    }
    let revision = previous.as_ref().map_or(0, |version| version.revision);
    if revision >= MAX_REMOTE_REVISION
        || previous.as_ref().is_some_and(|version| version.deleted)
        || (deleted && revision == 0)
    {
        return Err(KnowledgeError::Conflict);
    }
    valid_identifier(&local.id)?;
    let content = RemoteMemoryContent {
        title: local.title.clone(),
        content: local.content.clone(),
        content_type: local.content_type.clone(),
        tags: local.tags.clone(),
        status: local.status.clone(),
        metadata: previous.map_or_else(Default::default, |version| version.content.metadata),
    };
    if !deleted {
        content.validate()?;
    }
    serde_json::to_string(&json!({"change_id":change_id,"memory_id":local.id,
        "operation":if deleted {"delete"} else if revision == 0 {"create"} else {"update"},
        "expected_revision":revision,"content":if deleted {Value::Null} else {serde_json::to_value(content).map_err(storage)?}
    })).map_err(storage)
}

#[async_trait]
impl KnowledgePushRepository for SqliteKnowledgeRepository {
    async fn prepare_push(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
    ) -> KnowledgeResult<Option<PreparedKnowledgePush>> {
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        check_target(&tx, scope, target, true)?;
        let candidate: Option<(u64, String, String, String, Option<String>)> = tx
            .query_row(
                "SELECT c.sequence, o.change_id, c.payload, c.operation, p.request_json
                 FROM knowledge_sync_outbox o
                 JOIN knowledge_processing_changes c ON c.sequence=o.sequence
                 LEFT JOIN knowledge_sync_pushes p ON p.sequence=o.sequence
                 WHERE c.tenant_id=?1 AND c.project_id=?2 AND p.receipt_json IS NULL
                   AND NOT EXISTS (
                     SELECT 1 FROM knowledge_sync_outbox eo
                     JOIN knowledge_processing_changes ec ON ec.sequence=eo.sequence
                     LEFT JOIN knowledge_sync_pushes ep ON ep.sequence=eo.sequence
                     WHERE ec.tenant_id=c.tenant_id AND ec.project_id=c.project_id
                       AND ec.memory_id=c.memory_id AND ec.sequence<c.sequence
                       AND (ep.receipt_json IS NULL OR ep.conflict_json IS NOT NULL)
                   )
                 ORDER BY c.sequence LIMIT 1",
                params![scope.tenant_id, scope.project_id],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                    ))
                },
            )
            .optional()
            .map_err(storage)?;
        let Some((local_sequence, change_id, payload, operation, existing)) = candidate else {
            tx.commit().map_err(storage)?;
            return Ok(None);
        };
        let request_json = if let Some(existing) = existing {
            existing
        } else {
            let memory: Memory = serde_json::from_str(&payload).map_err(storage)?;
            let request = prepared_request(
                &change_id,
                &memory,
                operation == "delete",
                baseline(&tx, scope, &memory.id)?,
            )?;
            tx.execute(
                "INSERT INTO knowledge_sync_pushes(sequence,request_json) VALUES(?1,?2)",
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

    async fn accept_push_receipt(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        local_sequence: u64,
        response: Value,
        conflict: Option<Value>,
    ) -> KnowledgeResult<KnowledgePushReceipt> {
        self.accept_push_receipt_durable(scope, target, local_sequence, response, conflict)
    }

    async fn remote_baseline(
        &self,
        scope: &KnowledgeScope,
        memory_id: &str,
    ) -> KnowledgeResult<Option<Value>> {
        validate(scope, memory_id)?;
        let conn = self.conn.lock().map_err(storage)?;
        baseline(&conn, scope, memory_id)
    }

    async fn push_conflicts(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>> {
        validate(scope, "push conflicts")?;
        if !(1..=200).contains(&limit) {
            return Err(KnowledgeError::InvalidInput);
        }
        let conn = self.conn.lock().map_err(storage)?;
        let mut statement = conn
            .prepare(
                "SELECT p.conflict_json FROM knowledge_sync_pushes p
                 JOIN knowledge_processing_changes c ON c.sequence=p.sequence
                 WHERE c.tenant_id=?1 AND c.project_id=?2 AND p.conflict_json IS NOT NULL
                 ORDER BY c.sequence LIMIT ?3",
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
