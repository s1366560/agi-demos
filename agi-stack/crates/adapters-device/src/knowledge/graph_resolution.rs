//! Atomic, explicit resolution of local graph pull conflicts. Mirrors memory
//! resolution semantics: use_remote advances the remote version, use_local
//! re-bases the pending push, merged applies and pushes the merged content,
//! and keep_both keeps both versions under a deterministic copy id. Cloud
//! guards are untouched; no choice implies a cloud receipt.

use agistack_core::knowledge::sync::graph::RemoteGraphVersion;
use agistack_core::knowledge::sync::graph_resolution::*;
use agistack_core::knowledge::sync::push::{valid_identifier, KnowledgeSyncTarget};
use rusqlite::{Transaction, TransactionBehavior};
use serde_json::{json, Value};
use uuid::Uuid;

use super::*;

fn version(value: &Value) -> KnowledgeResult<RemoteGraphVersion> {
    let version: RemoteGraphVersion = serde_json::from_value(value.clone()).map_err(storage)?;
    version.validate()?;
    Ok(version)
}

struct Snapshot {
    context: GraphPullConflictContext,
    local: super::graph_sync::LocalGraphObject,
    remote: RemoteGraphVersion,
}

fn snapshot(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    object_id: &str,
) -> KnowledgeResult<Option<Snapshot>> {
    let local = super::graph_sync::local_object(tx, scope, object_id)?;
    let Some(local) = local else {
        return Ok(None);
    };
    let mut statement = tx
        .prepare(
            "SELECT sequence, conflict_json FROM knowledge_active_graph_pull_conflicts
             WHERE tenant_id=?1 AND project_id=?2 AND object_id=?3 ORDER BY sequence",
        )
        .map_err(storage)?;
    let rows = statement
        .query_map(
            params![scope.tenant_id, scope.project_id, object_id],
            |row| Ok((row.get::<_, u64>(0)?, row.get::<_, String>(1)?)),
        )
        .map_err(storage)?;
    let mut sequences = Vec::new();
    let mut remote: Option<RemoteGraphVersion> = None;
    let mut remote_value = Value::Null;
    for row in rows {
        let (sequence, conflict) = row.map_err(storage)?;
        let conflict: Value = serde_json::from_str(&conflict).map_err(storage)?;
        let candidate = version(&conflict["remote"])?;
        if let Some(previous) = &remote {
            if candidate.revision <= previous.revision {
                return Err(KnowledgeError::Storage(
                    "active graph pull conflicts are inconsistent".into(),
                ));
            }
        }
        sequences.push(sequence);
        remote = Some(candidate);
        remote_value = conflict["remote"].clone();
    }
    let Some(remote) = remote else {
        return Ok(None);
    };
    let baseline = super::graph_push::baseline(tx, scope, object_id)?;
    Ok(Some(Snapshot {
        context: GraphPullConflictContext {
            object_id: object_id.into(),
            conflict_sequences: sequences,
            local: Some(serde_json::to_value(&local.version).map_err(storage)?),
            local_deleted: local.deleted,
            baseline,
            remote: remote_value,
        },
        local,
        remote,
    }))
}

fn validate_guard(
    command: &GraphPullConflictResolution,
    snapshot: &Snapshot,
) -> KnowledgeResult<()> {
    if command.conflict_sequences != snapshot.context.conflict_sequences
        || command.expected_local_revision != snapshot.local.revision
        || command.expected_remote_revision != snapshot.remote.revision
    {
        return Err(KnowledgeError::Conflict);
    }
    let baseline_revision = snapshot
        .context
        .baseline
        .as_ref()
        .map(version)
        .transpose()?
        .map_or(0, |baseline| baseline.revision);
    if command.expected_baseline_revision != baseline_revision {
        return Err(KnowledgeError::Conflict);
    }
    Ok(())
}

fn apply(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    resolution_id: &str,
    command: &GraphPullConflictResolution,
    snapshot: Snapshot,
) -> KnowledgeResult<GraphResolutionReceipt> {
    let pending: Vec<u64> = {
        let mut statement = tx
            .prepare(
                "SELECT sequence FROM knowledge_pending_graph_outbox
                 WHERE tenant_id=?1 AND project_id=?2 AND object_id=?3 ORDER BY sequence",
            )
            .map_err(storage)?;
        let rows = statement
            .query_map(
                params![scope.tenant_id, scope.project_id, command.object_id],
                |row| row.get::<_, u64>(0),
            )
            .map_err(storage)?;
        rows.collect::<Result<Vec<_>, _>>().map_err(storage)?
    };
    let next_revision = snapshot
        .local
        .revision
        .checked_add(1)
        .ok_or(KnowledgeError::InvalidInput)?;
    let mut receipt = GraphResolutionReceipt {
        resolution_id: resolution_id.into(),
        object_id: command.object_id.clone(),
        local_revision: snapshot.local.revision,
        remote_baseline_revision: snapshot.remote.revision,
        copy_object_id: None,
        conflict_sequences: snapshot.context.conflict_sequences.clone(),
        superseded_sequences: Vec::new(),
        pending_push_sequences: Vec::new(),
    };
    let baseline_json = serde_json::to_string(
        &snapshot
            .context
            .remote,
    )
    .map_err(storage)?;
    let rebase = |tx: &Transaction<'_>| -> KnowledgeResult<()> {
        tx.execute(
            "INSERT INTO knowledge_sync_graph_remote_versions(tenant_id, project_id, object_id, version_json)
             VALUES(?1, ?2, ?3, ?4) ON CONFLICT(tenant_id, project_id, object_id) DO UPDATE SET version_json=excluded.version_json",
            params![scope.tenant_id, scope.project_id, command.object_id, baseline_json],
        )
        .map_err(storage)?;
        Ok(())
    };
    let supersede = |tx: &Transaction<'_>, receipt: &mut GraphResolutionReceipt| -> KnowledgeResult<()> {
        for sequence in &pending {
            tx.execute(
                "INSERT INTO knowledge_sync_graph_superseded_outbox(sequence, resolution_id) VALUES(?1, ?2)",
                params![sequence, resolution_id],
            )
            .map_err(storage)?;
        }
        receipt.superseded_sequences = pending.clone();
        Ok(())
    };
    match &command.choice {
        GraphConflictChoice::UseRemote {} => {
            supersede(tx, &mut receipt)?;
            super::graph_sync::store_object(tx, scope, &snapshot.remote, next_revision)?;
            rebase(tx)?;
            receipt.local_revision = next_revision;
        }
        GraphConflictChoice::UseLocal {} => {
            // The local record stays; the remote version becomes the push
            // baseline so the pending (or re-enqueued) push updates the cloud.
            rebase(tx)?;
            if pending.is_empty() {
                let sequence = super::graph_sync::enqueue_named(
                    tx,
                    scope,
                    &command.object_id,
                    &snapshot.local.version.content,
                    &format!("graph-resolution:{resolution_id}"),
                )?;
                receipt.pending_push_sequences = vec![sequence];
            } else {
                receipt.pending_push_sequences = pending.clone();
            }
        }
        GraphConflictChoice::Merged { content } => {
            supersede(tx, &mut receipt)?;
            let merged = RemoteGraphVersion {
                object_id: command.object_id.clone(),
                revision: next_revision,
                deleted: false,
                author_id: snapshot.local.version.author_id.clone(),
                created_at_ms: snapshot.local.version.created_at_ms,
                content: content.clone(),
            };
            super::graph_sync::store_object(tx, scope, &merged, next_revision)?;
            rebase(tx)?;
            let sequence = super::graph_sync::enqueue_named(
                tx,
                scope,
                &command.object_id,
                content,
                &format!("graph-resolution:{resolution_id}"),
            )?;
            receipt.pending_push_sequences = vec![sequence];
            receipt.local_revision = next_revision;
        }
        GraphConflictChoice::KeepBoth {} => {
            supersede(tx, &mut receipt)?;
            super::graph_sync::store_object(tx, scope, &snapshot.remote, next_revision)?;
            rebase(tx)?;
            // The local version survives as a detached copy pushed as a create.
            let copy_id = super::graph_sync::change_id_for(
                tx,
                &format!("graph-keep-both:{resolution_id}"),
            )?;
            let copy = RemoteGraphVersion {
                object_id: copy_id.clone(),
                revision: 1,
                deleted: false,
                author_id: snapshot.local.version.author_id.clone(),
                created_at_ms: snapshot.local.version.created_at_ms,
                content: snapshot.local.version.content.clone(),
            };
            super::graph_sync::store_object(tx, scope, &copy, 1)?;
            let sequence = super::graph_sync::enqueue_named(
                tx,
                scope,
                &copy_id,
                &copy.content,
                &format!("graph-keep-both-copy:{resolution_id}"),
            )?;
            receipt.copy_object_id = Some(copy_id);
            receipt.pending_push_sequences = vec![sequence];
            receipt.local_revision = next_revision;
        }
    }
    Ok(receipt)
}

impl SqliteKnowledgeRepository {
    /// Holds no network or async work; trusted authorities keep their session
    /// fence through commit.
    pub fn resolve_graph_pull_conflicts_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        key: &str,
        command: GraphPullConflictResolution,
    ) -> KnowledgeResult<GraphResolutionOutcome> {
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
                "SELECT request_json, receipt_json FROM knowledge_sync_graph_resolutions
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
            return Ok(GraphResolutionOutcome {
                receipt: serde_json::from_str(&receipt).map_err(storage)?,
                replayed: true,
            });
        }
        let snapshot =
            snapshot(&tx, scope, &command.object_id)?.ok_or(KnowledgeError::Conflict)?;
        validate_guard(&command, &snapshot)?;
        let replica = super::sync::replica(&tx)?;
        let identity = serde_json::to_vec(&json!([scope.tenant_id, scope.project_id, actor, key]))
            .map_err(storage)?;
        let id = Uuid::new_v5(&replica, &identity).to_string();
        let receipt = apply(&tx, scope, &id, &command, snapshot)?;
        tx.execute("INSERT INTO knowledge_sync_graph_resolutions(resolution_id,tenant_id,project_id,actor_id,idempotency_key,object_id,request_json,receipt_json,archive_json)
            VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)",params![id,scope.tenant_id,scope.project_id,actor,key,command.object_id,request.to_string(),serde_json::to_string(&receipt).map_err(storage)?,serde_json::to_string(&json!({"object_id":command.object_id,"conflict_sequences":receipt.conflict_sequences})).map_err(storage)?]).map_err(storage)?;
        for sequence in &receipt.conflict_sequences {
            tx.execute("INSERT INTO knowledge_sync_graph_resolved_pull_conflicts(tenant_id,project_id,sequence,resolution_id) VALUES(?1,?2,?3,?4)",params![scope.tenant_id,scope.project_id,sequence,id]).map_err(storage)?;
        }
        tx.commit().map_err(storage)?;
        Ok(GraphResolutionOutcome {
            receipt,
            replayed: false,
        })
    }
}

#[async_trait]
impl KnowledgeGraphResolutionRepository for SqliteKnowledgeRepository {
    async fn graph_pull_conflict_context(
        &self,
        scope: &KnowledgeScope,
        object_id: &str,
    ) -> KnowledgeResult<Option<GraphPullConflictContext>> {
        validate(scope, object_id)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        let context = snapshot(&tx, scope, object_id)?.map(|snapshot| snapshot.context);
        tx.commit().map_err(storage)?;
        Ok(context)
    }

    async fn resolve_graph_pull_conflicts(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        key: &str,
        command: GraphPullConflictResolution,
    ) -> KnowledgeResult<GraphResolutionOutcome> {
        self.resolve_graph_pull_conflicts_durable(scope, target, actor, key, command)
    }

    async fn graph_resolution_history(
        &self,
        scope: &KnowledgeScope,
        object_id: &str,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>> {
        validate(scope, object_id)?;
        if !(1..=200).contains(&limit) {
            return Err(KnowledgeError::InvalidInput);
        }
        let conn = self.conn.lock().map_err(storage)?;
        let mut statement = conn
            .prepare(
                "SELECT request_json, receipt_json, archive_json FROM knowledge_sync_graph_resolutions WHERE tenant_id=?1 AND project_id=?2 AND object_id=?3 ORDER BY rowid LIMIT ?4",
            )
            .map_err(storage)?;
        let rows = statement
            .query_map(
                params![scope.tenant_id, scope.project_id, object_id, limit as i64],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                },
            )
            .map_err(storage)?;
        rows.map(|row| {
            let (request, receipt, archive) = row.map_err(storage)?;
            Ok(json!({
                "request": serde_json::from_str::<Value>(&request).map_err(storage)?,
                "receipt": serde_json::from_str::<Value>(&receipt).map_err(storage)?,
                "archive": serde_json::from_str::<Value>(&archive).map_err(storage)?,
            }))
        })
        .collect()
    }
}
