//! Atomic, explicit resolution of local pull conflicts. Cloud guards are untouched.
use super::*;
use agistack_core::knowledge::sync::push::{
    valid_identifier, KnowledgeSyncTarget, RemoteMemoryContent, RemoteMemoryVersion,
};
use agistack_core::knowledge::sync::resolution::*;
use rusqlite::{Transaction, TransactionBehavior};
use serde_json::{json, Map, Value};
use uuid::Uuid;
mod apply;
mod schema;
mod snapshot;
pub(super) use schema::migrate;
fn version(value: &Value) -> KnowledgeResult<RemoteMemoryVersion> {
    let version: RemoteMemoryVersion = serde_json::from_value(value.clone()).map_err(storage)?;
    version.validate()?;
    Ok(version)
}
pub(super) fn metadata(
    conn: &Connection,
    sequence: u64,
) -> KnowledgeResult<Option<Map<String, Value>>> {
    let value: Option<String> = conn
        .query_row(
            "SELECT metadata_json FROM knowledge_sync_outbox_metadata WHERE sequence=?1",
            [sequence],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    value
        .map(|v| serde_json::from_str(&v).map_err(storage))
        .transpose()
}
impl SqliteKnowledgeRepository {
    /// Holds no network or async work; trusted authorities keep their session fence through commit.
    pub fn resolve_pull_conflicts_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        key: &str,
        command: KnowledgePullConflictResolution,
    ) -> KnowledgeResult<KnowledgeResolutionOutcome> {
        valid_identifier(actor)?;
        valid_identifier(key)?;
        command.validate()?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        super::push::check_target(&tx, scope, target, false)?;
        let request = serde_json::to_value(&command).map_err(storage)?;
        let previous: Option<(String, String)> = tx
            .query_row(
                "SELECT request_json,receipt_json FROM knowledge_sync_resolutions
            WHERE tenant_id=?1 AND project_id=?2 AND actor_id=?3 AND idempotency_key=?4",
                params![scope.tenant_id, scope.project_id, actor, key],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()
            .map_err(storage)?;
        if let Some((original, receipt)) = previous {
            if serde_json::from_str::<Value>(&original).map_err(storage)? != request {
                return Err(KnowledgeError::IdempotencyConflict);
            }
            return Ok(KnowledgeResolutionOutcome {
                receipt: serde_json::from_str(&receipt).map_err(storage)?,
                replayed: true,
            });
        }
        let context =
            snapshot::context(&tx, scope, &command.memory_id)?.ok_or(KnowledgeError::Conflict)?;
        let superseded = snapshot::validate_guard(&tx, scope, &command, &context)?;
        let replica: String = tx
            .query_row("SELECT replica_id FROM knowledge_replica", [], |row| {
                row.get(0)
            })
            .map_err(storage)?;
        let namespace = Uuid::parse_str(&replica).map_err(storage)?;
        let identity = serde_json::to_vec(&json!([scope.tenant_id, scope.project_id, actor, key]))
            .map_err(storage)?;
        let id = Uuid::new_v5(&namespace, &identity).to_string();
        let receipt = apply::apply(&tx, scope, actor, &id, &command, &context, superseded)?;
        tx.execute("INSERT INTO knowledge_sync_resolutions(resolution_id,tenant_id,project_id,actor_id,idempotency_key,memory_id,request_json,receipt_json,archive_json)
            VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)",params![id,scope.tenant_id,scope.project_id,actor,key,command.memory_id,request.to_string(),serde_json::to_string(&receipt).map_err(storage)?,serde_json::to_string(&context).map_err(storage)?]).map_err(storage)?;
        for sequence in &receipt.conflict_sequences {
            tx.execute("INSERT INTO knowledge_sync_resolved_pull_conflicts(tenant_id,project_id,sequence,resolution_id) VALUES(?1,?2,?3,?4)",params![scope.tenant_id,scope.project_id,sequence,id]).map_err(storage)?;
        }
        for sequence in &receipt.superseded_sequences {
            tx.execute("INSERT INTO knowledge_sync_superseded_outbox(sequence,resolution_id) VALUES(?1,?2)",params![sequence,id]).map_err(storage)?;
        }
        tx.commit().map_err(storage)?;
        Ok(KnowledgeResolutionOutcome {
            receipt,
            replayed: false,
        })
    }
}
#[async_trait]
impl KnowledgeResolutionRepository for SqliteKnowledgeRepository {
    async fn pull_conflict_context(
        &self,
        scope: &KnowledgeScope,
        id: &str,
    ) -> KnowledgeResult<Option<KnowledgePullConflictContext>> {
        validate(scope, id)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        let context = snapshot::context(&tx, scope, id)?;
        tx.commit().map_err(storage)?;
        Ok(context)
    }
    async fn resolve_pull_conflicts(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        key: &str,
        command: KnowledgePullConflictResolution,
    ) -> KnowledgeResult<KnowledgeResolutionOutcome> {
        self.resolve_pull_conflicts_durable(scope, target, actor, key, command)
    }
    async fn resolution_history(
        &self,
        scope: &KnowledgeScope,
        id: &str,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>> {
        validate(scope, id)?;
        if !(1..=200).contains(&limit) {
            return Err(KnowledgeError::InvalidInput);
        }
        let conn = self.conn.lock().map_err(storage)?;
        let mut stmt=conn.prepare("SELECT request_json,receipt_json,archive_json FROM knowledge_sync_resolutions WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 ORDER BY rowid LIMIT ?4").map_err(storage)?;
        let rows = stmt
            .query_map(
                params![scope.tenant_id, scope.project_id, id, limit as i64],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                },
            )
            .map_err(storage)?;
        rows.map(|row|{let (request,receipt,archive)=row.map_err(storage)?;Ok(json!({"request":serde_json::from_str::<Value>(&request).map_err(storage)?,"receipt":serde_json::from_str::<Value>(&receipt).map_err(storage)?,"archive":serde_json::from_str::<Value>(&archive).map_err(storage)?}))}).collect()
    }
}
