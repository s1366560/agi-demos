use super::*;
pub(super) fn context(
    conn: &Connection,
    scope: &KnowledgeScope,
    id: &str,
) -> KnowledgeResult<Option<KnowledgePullConflictContext>> {
    let mut stmt = conn
        .prepare(
            "SELECT c.sequence FROM knowledge_active_pull_conflicts c
        WHERE c.tenant_id=?1 AND c.project_id=?2 AND c.memory_id=?3
        ORDER BY c.sequence LIMIT 10001",
        )
        .map_err(storage)?;
    let sequences: Vec<u64> = stmt
        .query_map(params![scope.tenant_id, scope.project_id, id], |row| {
            row.get(0)
        })
        .map_err(storage)?
        .collect::<Result<_, _>>()
        .map_err(storage)?;
    let Some(last) = sequences.last() else {
        return Ok(None);
    };
    if sequences.len() > 10_000 {
        return Err(KnowledgeError::InvalidInput);
    }
    let conflict:String=conn.query_row("SELECT conflict_json FROM knowledge_sync_pull_conflicts WHERE tenant_id=?1 AND project_id=?2 AND sequence=?3",params![scope.tenant_id,scope.project_id,last],|row|row.get(0)).map_err(storage)?;
    let conflict: Value = serde_json::from_str(&conflict).map_err(storage)?;
    let (local,deleted):(String,bool)=conn.query_row("SELECT payload,deleted FROM knowledge_memories WHERE tenant_id=?1 AND project_id=?2 AND id=?3",params![scope.tenant_id,scope.project_id,id],|row|Ok((row.get(0)?,row.get(1)?))).map_err(storage)?;
    let local: Memory = serde_json::from_str(&local).map_err(storage)?;
    let baseline:Option<String>=conn.query_row("SELECT version_json FROM knowledge_sync_remote_versions WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3",params![scope.tenant_id,scope.project_id,id],|row|row.get(0)).optional().map_err(storage)?;
    let baseline: Option<Value> = baseline
        .map(|v| serde_json::from_str(&v).map_err(storage))
        .transpose()?;
    let local_metadata = local.metadata.clone();
    Ok(Some(KnowledgePullConflictContext {
        memory_id: id.into(),
        conflict_sequences: sequences,
        local,
        local_deleted: deleted,
        local_metadata,
        baseline,
        remote: conflict["remote"].clone(),
    }))
}
pub(super) fn validate_guard(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    command: &KnowledgePullConflictResolution,
    context: &KnowledgePullConflictContext,
) -> KnowledgeResult<Vec<u64>> {
    let base = context
        .baseline
        .as_ref()
        .map(version)
        .transpose()?
        .map_or(0, |v| v.revision);
    if command.conflict_sequences != context.conflict_sequences
        || command.expected_local_revision != context.local.version
        || command.expected_remote_revision != version(&context.remote)?.revision
        || command.expected_baseline_revision != base
    {
        return Err(KnowledgeError::Conflict);
    }
    let unresolved_push: bool = tx
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM knowledge_unsettled_pushes WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3)
        OR EXISTS(SELECT 1 FROM knowledge_cloud_resolutions WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND rejection_json IS NULL AND reconciliation_json IS NULL)",
            params![scope.tenant_id, scope.project_id, command.memory_id],
            |row| row.get(0),
        )
        .map_err(storage)?;
    if unresolved_push {
        return Err(KnowledgeError::Conflict);
    }
    let mut statement = tx
        .prepare(
            "SELECT sequence FROM knowledge_pending_outbox
        WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND receipt_json IS NULL
        ORDER BY sequence",
        )
        .map_err(storage)?;
    let sequences = statement
        .query_map(
            params![scope.tenant_id, scope.project_id, command.memory_id],
            |row| row.get(0),
        )
        .map_err(storage)?;
    sequences.collect::<Result<_, _>>().map_err(storage)
}
