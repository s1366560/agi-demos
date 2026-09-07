use super::*;

fn validate(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    record: &KnowledgeCloudResolutionRecord,
    receipt: &Value,
) -> KnowledgeResult<Option<Value>> {
    if receipt["change_id"] != record.resolution_id {
        return Err(KnowledgeError::InvalidInput);
    }
    let value = receipt.get("version").ok_or(KnowledgeError::InvalidInput)?;
    let previous = &record.archive.remote;
    if matches!(record.command.choice, KnowledgeCloudChoice::KeepCurrent {}) {
        if receipt["status"] != "resolved"
            || receipt["conflict_id"] != record.command.conflict_id
            || receipt.get("sequence").is_some()
            || value != previous.as_ref().unwrap_or(&Value::Null)
        {
            return Err(KnowledgeError::InvalidInput);
        }
        return Ok(previous.clone());
    }
    if receipt["status"] != "applied"
        || receipt["sequence"]
            .as_i64()
            .filter(|s| *s > 0 && (*s as u64) > record.archive.observed_cursor)
            .is_none()
    {
        return Err(KnowledgeError::InvalidInput);
    }
    let remote = context::remote(value, &record.command.memory_id)?;
    if remote.revision
        != record
            .command
            .guard
            .expected_remote_revision
            .checked_add(1)
            .ok_or(KnowledgeError::InvalidInput)?
    {
        return Err(KnowledgeError::InvalidInput);
    }
    if let Some(previous) = previous {
        let old = context::remote(previous, &record.command.memory_id)?;
        if old.author_id != remote.author_id || old.created_at_ms != remote.created_at_ms {
            return Err(KnowledgeError::InvalidInput);
        }
    } else {
        let actor:String=tx.query_row("SELECT remote_actor_id FROM knowledge_sync_links WHERE tenant_id=?1 AND project_id=?2",params![scope.tenant_id,scope.project_id],|r|r.get(0)).map_err(storage)?;
        if remote.author_id != actor {
            return Err(KnowledgeError::InvalidInput);
        }
    }
    let deleting = matches!(record.command.choice, KnowledgeCloudChoice::UseProposed {})
        && record.archive.original_request["operation"] == "delete";
    let expected = match &record.command.choice {
        KnowledgeCloudChoice::Merged { content } => content.remote(),
        KnowledgeCloudChoice::UseProposed {} if deleting => {
            context::remote(
                previous.as_ref().ok_or(KnowledgeError::InvalidInput)?,
                &record.command.memory_id,
            )?
            .content
        }
        KnowledgeCloudChoice::UseProposed {} => {
            serde_json::from_value(record.archive.original_request["content"].clone())
                .map_err(|_| KnowledgeError::InvalidInput)?
        }
        KnowledgeCloudChoice::KeepCurrent {} => return Err(KnowledgeError::InvalidInput),
    };
    if remote.deleted != deleting || remote.content != expected {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(Some(value.clone()))
}
pub(super) fn update_baseline(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    id: &str,
    value: &Option<Value>,
) -> KnowledgeResult<()> {
    let old = context::baseline(tx, scope, id)?;
    let best = context::latest(id, [old.clone(), value.clone()])?;
    if best != old {
        tx.execute("INSERT INTO knowledge_sync_remote_versions(tenant_id,project_id,memory_id,version_json) VALUES(?1,?2,?3,?4) ON CONFLICT(tenant_id,project_id,memory_id) DO UPDATE SET version_json=excluded.version_json",params![scope.tenant_id,scope.project_id,id,best.ok_or(KnowledgeError::InvalidInput)?.to_string()]).map_err(storage)?;
    }
    Ok(())
}
pub(super) fn accept(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    actor: &str,
    id: &str,
    response: Value,
) -> KnowledgeResult<KnowledgeCloudResolutionOutcome> {
    let record = load(tx, scope, actor, id)?;
    if !response["replayed"].is_boolean() || !response["receipt"].is_object() {
        return Err(KnowledgeError::InvalidInput);
    }
    let receipt = &response["receipt"];
    if let Some(previous) = &record.receipt {
        if previous != receipt {
            return Err(KnowledgeError::IdempotencyConflict);
        }
        return outcome(&record, true);
    }
    if record.rejection.is_some() {
        return Err(KnowledgeError::Conflict);
    }
    let remote = validate(tx, scope, &record, receipt)?;
    let mut now = record.archive.clone();
    context::refresh(tx, scope, &mut now, false)?;
    let newest = context::latest(
        &now.memory_id,
        [
            remote.clone(),
            now.baseline.clone(),
            context::last_seen(tx, scope, &now.memory_id)?,
        ],
    )?;
    let unchanged = now.local.version == record.archive.local.version
        && now.local_deleted == record.archive.local_deleted
        && now.baseline == record.archive.baseline
        && now.conflict_sequences == record.archive.conflict_sequences
        && now.pending_sequences == record.archive.pending_sequences
        && newest == remote
        && now.local.version < u32::MAX;
    tx.execute(
        "UPDATE knowledge_cloud_resolutions SET receipt_json=?2 WHERE resolution_id=?1",
        params![id, receipt.to_string()],
    )
    .map_err(storage)?;
    tx.execute(
        "INSERT INTO knowledge_cloud_resolved_pushes(sequence,resolution_id) VALUES(?1,?2)",
        params![record.local_sequence, id],
    )
    .map_err(storage)?;
    update_baseline(tx, scope, &now.memory_id, &remote)?;
    if unchanged {
        now.remote = remote;
        reconcile::apply(
            tx,
            scope,
            actor,
            &record,
            &now,
            &KnowledgeConflictChoice::UseRemote {},
            json!({"source":"cloud_receipt"}),
        )?;
    }
    outcome(&load(tx, scope, actor, id)?, false)
}
