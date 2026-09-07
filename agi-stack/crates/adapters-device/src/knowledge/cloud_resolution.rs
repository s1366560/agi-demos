//! Independent journal; original mutation requests and receipts remain immutable.
//! These synchronous ports require a trusted authority's session fence.
use super::*;
use agistack_core::knowledge::sync::cloud_resolution::*;
use agistack_core::knowledge::sync::push::{
    valid_identifier, KnowledgeSyncTarget, RemoteMemoryContent, RemoteMemoryVersion,
    MAX_REMOTE_REVISION,
};
use agistack_core::knowledge::sync::resolution::KnowledgeConflictChoice;
use rusqlite::{Transaction, TransactionBehavior};
use serde_json::{json, Map, Value};
use uuid::Uuid;
mod context;
mod ports;
mod prepare;
mod receipt;
mod reconcile;
mod schema;
pub(super) use schema::migrate;

fn valid_uuid(id: &str) -> KnowledgeResult<()> {
    if Uuid::parse_str(id)
        .map_err(|_| KnowledgeError::InvalidInput)?
        .to_string()
        != id
    {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}
fn load(
    conn: &Connection,
    scope: &KnowledgeScope,
    actor: &str,
    id: &str,
) -> KnowledgeResult<KnowledgeCloudResolutionRecord> {
    let row=conn.query_row("SELECT local_sequence,request_json,command_json,archive_json,receipt_json,rejection_json,reconciliation_json FROM knowledge_cloud_resolutions WHERE tenant_id=?1 AND project_id=?2 AND actor_id=?3 AND resolution_id=?4",params![scope.tenant_id,scope.project_id,actor,id],|r|Ok((r.get::<_,u64>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,String>(3)?,r.get::<_,Option<String>>(4)?,r.get::<_,Option<String>>(5)?,r.get::<_,Option<String>>(6)?))).optional().map_err(storage)?.ok_or(KnowledgeError::NotFound)?;
    let (command,archive):(Option<String>,Option<String>)=conn.query_row("SELECT reconciliation_command_json,reconciliation_archive_json FROM knowledge_cloud_resolutions WHERE resolution_id=?1",[id],|r|Ok((r.get(0)?,r.get(1)?))).map_err(storage)?;
    Ok(KnowledgeCloudResolutionRecord {
        resolution_id: id.into(),
        local_sequence: row.0,
        request_json: row.1,
        command: serde_json::from_str(&row.2).map_err(storage)?,
        archive: serde_json::from_str(&row.3).map_err(storage)?,
        receipt: row
            .4
            .map(|v| serde_json::from_str(&v).map_err(storage))
            .transpose()?,
        rejection: row
            .5
            .map(|v| serde_json::from_str(&v).map_err(storage))
            .transpose()?,
        reconciliation: row
            .6
            .map(|v| serde_json::from_str(&v).map_err(storage))
            .transpose()?,
        reconciliation_command: command
            .map(|v| serde_json::from_str(&v).map_err(storage))
            .transpose()?,
        reconciliation_archive: archive
            .map(|v| serde_json::from_str(&v).map_err(storage))
            .transpose()?,
    })
}
fn outcome(
    record: &KnowledgeCloudResolutionRecord,
    replayed: bool,
) -> KnowledgeResult<KnowledgeCloudResolutionOutcome> {
    Ok(KnowledgeCloudResolutionOutcome {
        resolution_id: record.resolution_id.clone(),
        receipt: record.receipt.clone().ok_or(KnowledgeError::Conflict)?,
        pending_reconciliation: record.reconciliation.is_none(),
        replayed,
    })
}
pub(super) fn accept_journal(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    id: &str,
    sequence: u64,
    version: &Value,
) -> KnowledgeResult<()> {
    let actor:Option<String>=tx.query_row("SELECT actor_id FROM knowledge_cloud_resolutions WHERE tenant_id=?1 AND project_id=?2 AND resolution_id=?3",params![scope.tenant_id,scope.project_id,id],|r|r.get(0)).optional().map_err(storage)?;
    if let Some(actor) = actor {
        receipt::accept(
            tx,
            scope,
            &actor,
            id,
            json!({"replayed":false,"receipt":{"status":"applied","change_id":id,"sequence":sequence,"version":version}}),
        )?;
    }
    Ok(())
}
impl SqliteKnowledgeRepository {
    fn cloud_transaction<T>(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        action: impl FnOnce(&Transaction<'_>) -> KnowledgeResult<T>,
    ) -> KnowledgeResult<T> {
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        super::push::check_target(&tx, scope, target, false)?;
        let result = action(&tx)?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }
    /// `verified` is the complete conflict document fetched by trusted transport.
    pub fn cloud_conflict_context_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        sequence: u64,
        verified: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionContext> {
        self.cloud_transaction(scope, target, |tx| {
            context::current(tx, scope, sequence, verified)
        })
    }
    pub fn prepare_cloud_resolution_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        key: &str,
        command: KnowledgeCloudResolutionCommand,
        verified: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionRecord> {
        valid_identifier(actor)?;
        valid_identifier(key)?;
        command.validate()?;
        valid_uuid(&command.conflict_id)?;
        self.cloud_transaction(scope, target, |tx| {
            prepare::prepare(tx, scope, actor, key, command, verified)
        })
    }
    pub fn cloud_resolution_record_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
    ) -> KnowledgeResult<KnowledgeCloudResolutionRecord> {
        valid_identifier(actor)?;
        valid_uuid(id)?;
        self.cloud_transaction(scope, target, |tx| load(tx, scope, actor, id))
    }
    /// Recovery/history discovery is actor-scoped and does not imply a send.
    pub fn cloud_resolution_records_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        limit: usize,
    ) -> KnowledgeResult<Vec<KnowledgeCloudResolutionRecord>> {
        valid_identifier(actor)?;
        if !(1..=200).contains(&limit) {
            return Err(KnowledgeError::InvalidInput);
        }
        self.cloud_transaction(scope,target,|tx|{
            let mut stmt=tx.prepare("SELECT resolution_id FROM knowledge_cloud_resolutions WHERE tenant_id=?1 AND project_id=?2 AND actor_id=?3 ORDER BY rowid DESC LIMIT ?4").map_err(storage)?;
            let ids=stmt.query_map(params![scope.tenant_id,scope.project_id,actor,limit as i64],|r|r.get::<_,String>(0)).map_err(storage)?.collect::<Result<Vec<_>,_>>().map_err(storage)?;
            ids.iter().map(|id|load(tx,scope,actor,id)).collect()
        })
    }
    /// Successful verified responses only. Pending preserves cloud success and
    /// never instructs the caller to resend a different cloud decision.
    pub fn accept_cloud_resolution_receipt_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
        response: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionOutcome> {
        valid_identifier(actor)?;
        valid_uuid(id)?;
        self.cloud_transaction(scope, target, |tx| {
            receipt::accept(tx, scope, actor, id, response)
        })
    }
    /// Caller must have observed HTTP 409 from the verified resolution endpoint.
    /// Unknown/network failures must keep the prepared request retryable.
    pub fn reject_cloud_resolution_stale_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
        response: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionRecord> {
        valid_identifier(actor)?;
        valid_uuid(id)?;
        self.cloud_transaction(scope, target, |tx| {
            let record = load(tx, scope, actor, id)?;
            if response["detail"]["code"] != "knowledge_sync_resolution_stale"
                || !response["detail"].is_object()
                || response.get("receipt").is_some()
            {
                return Err(KnowledgeError::InvalidInput);
            }
            if record.receipt.is_some() {
                return Err(KnowledgeError::Conflict);
            }
            if let Some(previous) = &record.rejection {
                if previous != &response {
                    return Err(KnowledgeError::IdempotencyConflict);
                }
                return Ok(record);
            }
            tx.execute(
                "UPDATE knowledge_cloud_resolutions SET rejection_json=?2 WHERE resolution_id=?1",
                params![id, response.to_string()],
            )
            .map_err(storage)?;
            load(tx, scope, actor, id)
        })
    }
    pub fn cloud_reconciliation_context_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
    ) -> KnowledgeResult<KnowledgeCloudResolutionContext> {
        valid_identifier(actor)?;
        valid_uuid(id)?;
        self.cloud_transaction(scope, target, |tx| {
            reconcile::context(tx, scope, &load(tx, scope, actor, id)?)
        })
    }
    pub fn reconcile_cloud_resolution_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
        command: KnowledgeCloudReconciliationCommand,
    ) -> KnowledgeResult<KnowledgeCloudResolutionOutcome> {
        valid_identifier(actor)?;
        valid_uuid(id)?;
        command.guard.validate()?;
        if let KnowledgeConflictChoice::Merged { content } = &command.choice {
            content.remote().validate()?;
        }
        self.cloud_transaction(scope, target, |tx| {
            reconcile::explicit(tx, scope, actor, id, command)
        })
    }
}
