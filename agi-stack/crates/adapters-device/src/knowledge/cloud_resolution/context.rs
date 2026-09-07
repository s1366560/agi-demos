use super::*;

pub(super) fn remote(value: &Value, id: &str) -> KnowledgeResult<RemoteMemoryVersion> {
    let v: RemoteMemoryVersion =
        serde_json::from_value(value.clone()).map_err(|_| KnowledgeError::InvalidInput)?;
    v.validate()?;
    if v.memory_id != id {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(v)
}
pub(super) fn baseline(
    conn: &Connection,
    scope: &KnowledgeScope,
    id: &str,
) -> KnowledgeResult<Option<Value>> {
    let v: Option<String> = conn.query_row("SELECT version_json FROM knowledge_sync_remote_versions WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3",params![scope.tenant_id,scope.project_id,id],|r|r.get(0)).optional().map_err(storage)?;
    v.map(|v| serde_json::from_str(&v).map_err(storage))
        .transpose()
}
pub(super) fn revision(value: &Option<Value>, id: &str) -> KnowledgeResult<u32> {
    value
        .as_ref()
        .map(|v| remote(v, id).map(|v| v.revision))
        .transpose()
        .map(|v| v.unwrap_or(0))
}
pub(super) fn latest(
    id: &str,
    values: impl IntoIterator<Item = Option<Value>>,
) -> KnowledgeResult<Option<Value>> {
    let mut best: Option<Value> = None;
    for value in values.into_iter().flatten() {
        let next = remote(&value, id)?;
        if let Some(current) = &best {
            let current = remote(current, id)?;
            if current.author_id != next.author_id || current.created_at_ms != next.created_at_ms {
                return Err(KnowledgeError::InvalidInput);
            }
            if current.revision == next.revision && best.as_ref() != Some(&value) {
                return Err(KnowledgeError::InvalidInput);
            }
            if current.revision >= next.revision {
                continue;
            }
        }
        best = Some(value);
    }
    Ok(best)
}
pub(super) fn refresh(
    conn: &Connection,
    scope: &KnowledgeScope,
    ctx: &mut KnowledgeCloudResolutionContext,
    preserve_metadata: bool,
) -> KnowledgeResult<()> {
    let (payload,deleted):(String,bool)=conn.query_row("SELECT payload,deleted FROM knowledge_memories WHERE tenant_id=?1 AND project_id=?2 AND id=?3",params![scope.tenant_id,scope.project_id,ctx.memory_id],|r|Ok((r.get(0)?,r.get(1)?))).map_err(storage)?;
    ctx.local = serde_json::from_str(&payload).map_err(storage)?;
    ctx.local_deleted = deleted;
    ctx.baseline = baseline(conn, scope, &ctx.memory_id)?;
    let metadata:Option<String>=conn.query_row("SELECT m.metadata_json FROM knowledge_sync_outbox_metadata m JOIN knowledge_pending_outbox o ON o.sequence=m.sequence WHERE o.tenant_id=?1 AND o.project_id=?2 AND o.memory_id=?3 ORDER BY o.sequence DESC LIMIT 1",params![scope.tenant_id,scope.project_id,ctx.memory_id],|r|r.get(0)).optional().map_err(storage)?;
    let fallback = if preserve_metadata {
        ctx.local_metadata.clone()
    } else {
        ctx.baseline
            .as_ref()
            .map(|v| remote(v, &ctx.memory_id).map(|v| v.content.metadata))
            .transpose()?
            .unwrap_or_default()
    };
    ctx.local_metadata = metadata
        .map(|v| serde_json::from_str(&v).map_err(storage))
        .transpose()?
        .unwrap_or(fallback);
    ctx.conflict_sequences=sequences(conn,scope,&ctx.memory_id,"SELECT sequence FROM knowledge_active_pull_conflicts WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 ORDER BY sequence LIMIT 10001")?;
    ctx.pending_sequences=sequences(conn,scope,&ctx.memory_id,"SELECT sequence FROM knowledge_pending_outbox WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 ORDER BY sequence LIMIT 10001")?;
    ctx.observed_cursor = conn
        .query_row(
            "SELECT cursor FROM knowledge_sync_pull_cursors WHERE tenant_id=?1 AND project_id=?2",
            params![scope.tenant_id, scope.project_id],
            |r| r.get(0),
        )
        .optional()
        .map_err(storage)?
        .unwrap_or(0);
    Ok(())
}
fn sequences(
    conn: &Connection,
    scope: &KnowledgeScope,
    id: &str,
    sql: &str,
) -> KnowledgeResult<Vec<u64>> {
    let mut stmt = conn.prepare(sql).map_err(storage)?;
    let result = stmt
        .query_map(params![scope.tenant_id, scope.project_id, id], |r| r.get(0))
        .map_err(storage)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(storage)?;
    if result.len() > 10_000 {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(result)
}
pub(super) fn current(
    conn: &Connection,
    scope: &KnowledgeScope,
    sequence: u64,
    verified: Value,
) -> KnowledgeResult<KnowledgeCloudResolutionContext> {
    let (request,conflict):(String,String)=conn.query_row("SELECT request_json,conflict_json FROM knowledge_unsettled_pushes WHERE tenant_id=?1 AND project_id=?2 AND sequence=?3 AND conflict_json IS NOT NULL",params![scope.tenant_id,scope.project_id,sequence],|r|Ok((r.get(0)?,r.get(1)?))).optional().map_err(storage)?.ok_or(KnowledgeError::Conflict)?;
    let original_request: Value = serde_json::from_str(&request).map_err(storage)?;
    let original: Value = serde_json::from_str(&conflict).map_err(storage)?;
    for key in ["id", "memory_id", "proposed", "current"] {
        if verified.get(key).is_none() || verified[key] != original[key] {
            return Err(KnowledgeError::InvalidInput);
        }
    }
    if verified.get("resolved_change_id") != Some(&Value::Null) {
        return Err(KnowledgeError::Conflict);
    }
    let id = original_request["memory_id"]
        .as_str()
        .ok_or(KnowledgeError::InvalidInput)?
        .to_owned();
    let observed = verified
        .get("observed_current")
        .ok_or(KnowledgeError::InvalidInput)?;
    let observed = (!observed.is_null()).then(|| observed.clone());
    let placeholder:Memory=serde_json::from_str(&conn.query_row::<String,_,_>("SELECT payload FROM knowledge_memories WHERE tenant_id=?1 AND project_id=?2 AND id=?3",params![scope.tenant_id,scope.project_id,id],|r|r.get(0)).map_err(storage)?).map_err(storage)?;
    let mut ctx = KnowledgeCloudResolutionContext {
        local_sequence: sequence,
        memory_id: id.clone(),
        conflict_id: original["id"]
            .as_str()
            .ok_or(KnowledgeError::InvalidInput)?
            .into(),
        original_request,
        cloud_conflict: verified,
        local: placeholder,
        local_deleted: false,
        local_metadata: Map::new(),
        baseline: None,
        remote: observed.clone(),
        conflict_sequences: vec![],
        pending_sequences: vec![],
        observed_cursor: 0,
    };
    refresh(conn, scope, &mut ctx, false)?;
    let known = latest(
        &id,
        [
            ctx.baseline.clone(),
            (!original["current"].is_null()).then(|| original["current"].clone()),
            last_seen(conn, scope, &id)?,
            observed.clone(),
        ],
    )?;
    if revision(&known, &id)? != revision(&observed, &id)? {
        return Err(KnowledgeError::Conflict);
    }
    Ok(ctx)
}
pub(super) fn last_seen(
    conn: &Connection,
    scope: &KnowledgeScope,
    id: &str,
) -> KnowledgeResult<Option<Value>> {
    let v:Option<String>=conn.query_row("SELECT version_json FROM knowledge_sync_pull_events WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 ORDER BY sequence DESC LIMIT 1",params![scope.tenant_id,scope.project_id,id],|r|r.get(0)).optional().map_err(storage)?;
    v.map(|v| serde_json::from_str(&v).map_err(storage))
        .transpose()
}
pub(super) fn guard(
    ctx: &KnowledgeCloudResolutionContext,
    g: &KnowledgeCloudResolutionGuard,
) -> KnowledgeResult<()> {
    g.validate()?;
    if ctx.local.version != g.expected_local_revision
        || revision(&ctx.remote, &ctx.memory_id)? != g.expected_remote_revision
        || revision(&ctx.baseline, &ctx.memory_id)? != g.expected_baseline_revision
        || ctx.conflict_sequences != g.conflict_sequences
    {
        return Err(KnowledgeError::Conflict);
    }
    Ok(())
}
