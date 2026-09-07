use super::*;

fn read_version(
    conn: &Connection,
    scope: &KnowledgeScope,
    id: &str,
    seen: bool,
) -> KnowledgeResult<Option<Value>> {
    let query = if seen {
        "SELECT version_json FROM knowledge_sync_pull_events WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 ORDER BY sequence DESC LIMIT 1"
    } else {
        "SELECT version_json FROM knowledge_sync_remote_versions WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3"
    };
    let value: Option<String> = conn
        .query_row(
            query,
            params![scope.tenant_id, scope.project_id, id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    value
        .map(|value| serde_json::from_str(&value).map_err(storage))
        .transpose()
}

fn typed(value: &Value) -> KnowledgeResult<RemoteMemoryVersion> {
    serde_json::from_value(value.clone()).map_err(storage)
}

pub(super) fn apply_event(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    target: &KnowledgeSyncTarget,
    event: &Event,
    remote: &RemoteMemoryVersion,
    result: &mut KnowledgePullReceipt,
) -> KnowledgeResult<()> {
    let seen = read_version(tx, scope, &remote.memory_id, true)?;
    if let Some(seen) = &seen {
        let previous = typed(seen)?;
        if remote.revision <= previous.revision
            || remote.author_id != previous.author_id
            || remote.created_at_ms != previous.created_at_ms
        {
            return Err(KnowledgeError::InvalidInput);
        }
    }
    super::super::push::accept_journal_receipt(
        tx,
        scope,
        target,
        &event.change_id,
        event.sequence,
        &event.version,
    )?;
    let baseline = read_version(tx, scope, &remote.memory_id, false)?;
    if let Some(baseline) = &baseline {
        let previous = typed(baseline)?;
        if remote.author_id != previous.author_id || remote.created_at_ms != previous.created_at_ms
        {
            return Err(KnowledgeError::InvalidInput);
        }
        // A push receipt may be ahead of the pull cursor. Consume the older
        // journal event without overwriting either baseline or current content.
        if remote.revision <= previous.revision {
            if remote.revision == previous.revision && &event.version != baseline {
                return Err(KnowledgeError::InvalidInput);
            }
            return Ok(());
        }
    }
    let local: Option<(String, bool)> = tx.query_row(
        "SELECT payload, deleted FROM knowledge_memories WHERE tenant_id=?1 AND project_id=?2 AND id=?3",
        params![scope.tenant_id, scope.project_id, remote.memory_id], |row| Ok((row.get(0)?, row.get(1)?)),
    ).optional().map_err(storage)?;
    let pending: bool = tx
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM knowledge_sync_outbox o
         JOIN knowledge_processing_changes c ON c.sequence=o.sequence
         LEFT JOIN knowledge_sync_pushes p ON p.sequence=o.sequence
         WHERE c.tenant_id=?1 AND c.project_id=?2 AND c.memory_id=?3
           AND (p.receipt_json IS NULL OR p.conflict_json IS NOT NULL))
         OR EXISTS(SELECT 1 FROM knowledge_sync_pull_conflicts
         WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3)",
            params![scope.tenant_id, scope.project_id, remote.memory_id],
            |row| row.get(0),
        )
        .map_err(storage)?;
    if pending || (local.is_some() && baseline.is_none()) {
        let local_value: Value = local
            .as_ref()
            .map(|(payload, _)| serde_json::from_str(payload).map_err(storage))
            .transpose()?
            .unwrap_or(Value::Null);
        let conflict = json!({"sequence":event.sequence,"memory_id":remote.memory_id,"remote":event.version,"local":local_value,"local_deleted":local.as_ref().is_some_and(|(_, deleted)| *deleted),"baseline":baseline});
        tx.execute(
            "INSERT INTO knowledge_sync_pull_conflicts(tenant_id, project_id, sequence, memory_id, conflict_json) VALUES(?1, ?2, ?3, ?4, ?5)",
            params![scope.tenant_id, scope.project_id, event.sequence, remote.memory_id, serde_json::to_string(&conflict).map_err(storage)?],
        ).map_err(storage)?;
        result.conflicts += 1;
        return Ok(());
    }
    let revision = match local {
        Some((payload, _)) => {
            let memory: Memory = serde_json::from_str(&payload).map_err(storage)?;
            memory
                .version
                .checked_add(1)
                .ok_or(KnowledgeError::InvalidInput)?
        }
        None => 1,
    };
    let memory = Memory {
        id: remote.memory_id.clone(),
        project_id: scope.project_id.clone(),
        title: remote.content.title.clone(),
        content: remote.content.content.clone(),
        author_id: remote.author_id.clone(),
        content_type: remote.content.content_type.clone(),
        tags: remote.content.tags.clone(),
        entities: Vec::new(),
        version: revision,
        status: remote.content.status.clone(),
        created_at_ms: remote.created_at_ms,
        embedding: None,
    };
    let payload = serde_json::to_string(&memory).map_err(storage)?;
    tx.execute(
        "INSERT INTO knowledge_memories(tenant_id, project_id, id, revision, deleted, created_at_ms, payload)
         VALUES(?1, ?2, ?3, ?4, ?5, ?6, ?7) ON CONFLICT(tenant_id, project_id, id)
         DO UPDATE SET revision=excluded.revision, deleted=excluded.deleted, created_at_ms=excluded.created_at_ms, payload=excluded.payload",
        params![scope.tenant_id, scope.project_id, memory.id, revision, remote.deleted, memory.created_at_ms, payload],
    ).map_err(storage)?;
    tx.execute(
        "INSERT INTO knowledge_processing_changes(tenant_id, project_id, memory_id, revision, operation, payload)
         VALUES(?1, ?2, ?3, ?4, ?5, ?6)",
        params![scope.tenant_id, scope.project_id, memory.id, revision, if remote.deleted { "delete" } else { "upsert" }, payload],
    ).map_err(storage)?;
    tx.execute(
        "INSERT INTO knowledge_sync_remote_versions(tenant_id, project_id, memory_id, version_json)
         VALUES(?1, ?2, ?3, ?4) ON CONFLICT(tenant_id, project_id, memory_id) DO UPDATE SET version_json=excluded.version_json",
        params![scope.tenant_id, scope.project_id, memory.id, serde_json::to_string(&event.version).map_err(storage)?],
    ).map_err(storage)?;
    result.applied += 1;
    Ok(())
}
