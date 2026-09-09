use super::*;
pub(super) fn prepare(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    actor: &str,
    key: &str,
    command: KnowledgeCloudResolutionCommand,
    verified: Value,
) -> KnowledgeResult<KnowledgeCloudResolutionRecord> {
    let encoded = serde_json::to_value(&command).map_err(storage)?;
    let previous:Option<String>=tx.query_row("SELECT resolution_id FROM knowledge_cloud_resolutions WHERE tenant_id=?1 AND project_id=?2 AND actor_id=?3 AND idempotency_key=?4",params![scope.tenant_id,scope.project_id,actor,key],|r|r.get(0)).optional().map_err(storage)?;
    if let Some(id) = previous {
        let record = load(tx, scope, actor, &id)?;
        if serde_json::to_value(&record.command).map_err(storage)? != encoded {
            return Err(KnowledgeError::IdempotencyConflict);
        }
        return Ok(record);
    }
    let ctx = context::current(tx, scope, command.local_sequence, verified)?;
    if command.conflict_id != ctx.conflict_id || command.memory_id != ctx.memory_id {
        return Err(KnowledgeError::Conflict);
    }
    context::guard(&ctx, &command.guard)?;
    let blocked:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM knowledge_cloud_resolutions WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND rejection_json IS NULL AND reconciliation_json IS NULL)
        OR EXISTS(SELECT 1 FROM knowledge_unsettled_pushes WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND sequence!=?4)",params![scope.tenant_id,scope.project_id,command.memory_id,command.local_sequence],|r|r.get(0)).map_err(storage)?;
    if blocked {
        return Err(KnowledgeError::Conflict);
    }
    if !matches!(
        command.choice,
        KnowledgeCloudChoice::KeepCurrent {} | KnowledgeCloudChoice::KeepBoth {}
    ) && command.guard.expected_remote_revision >= MAX_REMOTE_REVISION
    {
        return Err(KnowledgeError::InvalidInput);
    }
    if matches!(command.choice, KnowledgeCloudChoice::UseProposed {})
        && ctx.original_request["operation"] == "delete"
        && ctx.remote.is_none()
    {
        return Err(KnowledgeError::InvalidInput);
    }
    if matches!(command.choice, KnowledgeCloudChoice::KeepBoth {})
        && ctx.original_request["operation"] == "delete"
    {
        return Err(KnowledgeError::InvalidInput);
    }
    let replica: String = tx
        .query_row("SELECT replica_id FROM knowledge_replica", [], |r| r.get(0))
        .map_err(storage)?;
    let name = serde_json::to_vec(&json!([
        "cloud-resolution",
        scope.tenant_id,
        scope.project_id,
        actor,
        key
    ]))
    .map_err(storage)?;
    let id = Uuid::new_v5(&Uuid::parse_str(&replica).map_err(storage)?, &name).to_string();
    let (decision, content) = match &command.choice {
        KnowledgeCloudChoice::KeepCurrent {} => ("keep_current", Value::Null),
        KnowledgeCloudChoice::UseProposed {} => ("use_proposed", Value::Null),
        KnowledgeCloudChoice::KeepBoth {} => ("keep_both", Value::Null),
        KnowledgeCloudChoice::Merged { content } => {
            ("merged", serde_json::to_value(content).map_err(storage)?)
        }
    };
    let request=json!({"change_id":id,"expected_current_revision":command.guard.expected_remote_revision,"decision":decision,"content":content}).to_string();
    tx.execute("INSERT INTO knowledge_cloud_resolutions(resolution_id,tenant_id,project_id,actor_id,idempotency_key,memory_id,local_sequence,command_json,request_json,archive_json) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",params![id,scope.tenant_id,scope.project_id,actor,key,command.memory_id,command.local_sequence,encoded.to_string(),request,serde_json::to_string(&ctx).map_err(storage)?]).map_err(storage)?;
    load(tx, scope, actor, &id)
}
