use super::*;

pub(super) fn context(
    conn: &Connection,
    scope: &KnowledgeScope,
    record: &KnowledgeCloudResolutionRecord,
) -> KnowledgeResult<KnowledgeCloudResolutionContext> {
    let receipt = record.receipt.as_ref().ok_or(KnowledgeError::Conflict)?;
    if record.reconciliation.is_some() {
        return Err(KnowledgeError::Conflict);
    }
    let mut ctx = record.archive.clone();
    super::context::refresh(conn, scope, &mut ctx, true)?;
    ctx.remote = super::context::latest(
        &ctx.memory_id,
        [
            ctx.remote.clone(),
            (!receipt["version"].is_null()).then(|| receipt["version"].clone()),
            ctx.baseline.clone(),
            super::context::last_seen(conn, scope, &ctx.memory_id)?,
        ],
    )?;
    Ok(ctx)
}
pub(super) fn explicit(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    actor: &str,
    id: &str,
    command: KnowledgeCloudReconciliationCommand,
) -> KnowledgeResult<KnowledgeCloudResolutionOutcome> {
    let record = load(tx, scope, actor, id)?;
    let encoded = serde_json::to_value(&command).map_err(storage)?;
    if record.reconciliation.is_some() {
        let old:String=tx.query_row("SELECT reconciliation_command_json FROM knowledge_cloud_resolutions WHERE resolution_id=?1",[id],|r|r.get(0)).map_err(storage)?;
        if serde_json::from_str::<Value>(&old).map_err(storage)? != encoded {
            return Err(KnowledgeError::IdempotencyConflict);
        }
        return outcome(&record, true);
    }
    let ctx = context(tx, scope, &record)?;
    super::context::guard(&ctx, &command.guard)?;
    apply(tx, scope, actor, &record, &ctx, &command.choice, encoded)?;
    outcome(&load(tx, scope, actor, id)?, false)
}
fn local_content(ctx: &KnowledgeCloudResolutionContext) -> RemoteMemoryContent {
    RemoteMemoryContent {
        title: ctx.local.title.clone(),
        content: ctx.local.content.clone(),
        content_type: ctx.local.content_type.clone(),
        tags: ctx.local.tags.clone(),
        status: ctx.local.status.clone(),
        metadata: ctx.local_metadata.clone(),
    }
}
fn persist(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    memory: &Memory,
    deleted: bool,
    metadata: Option<&Map<String, Value>>,
    creating: bool,
) -> KnowledgeResult<u64> {
    let payload = serde_json::to_string(memory).map_err(storage)?;
    if creating {
        if tx.execute("INSERT INTO knowledge_memories(tenant_id,project_id,id,revision,deleted,created_at_ms,payload) VALUES(?1,?2,?3,?4,?5,?6,?7) ON CONFLICT DO NOTHING",params![scope.tenant_id,scope.project_id,memory.id,memory.version,deleted,memory.created_at_ms,payload]).map_err(storage)?!=1 { return Err(KnowledgeError::Conflict); }
    } else {
        tx.execute("UPDATE knowledge_memories SET revision=?4,deleted=?5,created_at_ms=?6,payload=?7 WHERE tenant_id=?1 AND project_id=?2 AND id=?3",params![scope.tenant_id,scope.project_id,memory.id,memory.version,deleted,memory.created_at_ms,payload]).map_err(storage)?;
    }
    tx.execute("INSERT INTO knowledge_processing_changes(tenant_id,project_id,memory_id,revision,operation,payload) VALUES(?1,?2,?3,?4,?5,?6)",params![scope.tenant_id,scope.project_id,memory.id,memory.version,if deleted{"delete"}else{"upsert"},payload]).map_err(storage)?;
    let sequence = tx.last_insert_rowid() as u64;
    if let Some(metadata) = metadata {
        super::super::sync::enqueue_local(tx, sequence)?;
        tx.execute(
            "INSERT INTO knowledge_sync_outbox_metadata(sequence,metadata_json) VALUES(?1,?2)",
            params![sequence, serde_json::to_string(metadata).map_err(storage)?],
        )
        .map_err(storage)?;
    }
    Ok(sequence)
}
pub(super) fn apply(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    actor: &str,
    record: &KnowledgeCloudResolutionRecord,
    ctx: &KnowledgeCloudResolutionContext,
    choice: &KnowledgeConflictChoice,
    command: Value,
) -> KnowledgeResult<()> {
    let remote = ctx
        .remote
        .as_ref()
        .map(|v| super::context::remote(v, &ctx.memory_id))
        .transpose()?;
    let (content, deleted, enqueue) = match choice {
        KnowledgeConflictChoice::UseRemote {} | KnowledgeConflictChoice::KeepBoth {} => (
            remote
                .as_ref()
                .map(|r| r.content.clone())
                .unwrap_or_else(|| local_content(ctx)),
            remote.as_ref().is_none_or(|r| r.deleted),
            false,
        ),
        KnowledgeConflictChoice::UseLocal {} => (local_content(ctx), ctx.local_deleted, true),
        KnowledgeConflictChoice::Merged { content } => (content.remote(), false, true),
    };
    content.validate()?;
    let memory = Memory {
        id: ctx.memory_id.clone(),
        project_id: scope.project_id.clone(),
        title: content.title,
        content: content.content,
        content_type: content.content_type,
        tags: content.tags,
        status: content.status,
        author_id: remote
            .as_ref()
            .map(|r| r.author_id.clone())
            .unwrap_or_else(|| ctx.local.author_id.clone()),
        created_at_ms: remote
            .as_ref()
            .map(|r| r.created_at_ms)
            .unwrap_or(ctx.local.created_at_ms),
        version: ctx
            .local
            .version
            .checked_add(1)
            .ok_or(KnowledgeError::InvalidInput)?,
        entities: vec![],
        metadata: content.metadata.clone(),
        embedding: None,
    };
    let sequence = persist(
        tx,
        scope,
        &memory,
        deleted,
        enqueue.then_some(&content.metadata),
        false,
    )?;
    let mut result = KnowledgeCloudReconciliationReceipt {
        local_revision: memory.version,
        copy_memory_id: None,
        processing_sequences: vec![sequence],
        pending_push_sequences: if enqueue { vec![sequence] } else { vec![] },
        superseded_sequences: ctx
            .pending_sequences
            .iter()
            .copied()
            .filter(|s| *s != record.local_sequence)
            .collect(),
        conflict_sequences: ctx.conflict_sequences.clone(),
    };
    if matches!(choice, KnowledgeConflictChoice::KeepBoth {}) {
        local_content(ctx).validate()?;
        let copy_id = Uuid::new_v5(
            &Uuid::parse_str(&record.resolution_id).map_err(storage)?,
            b"reconciled-local-copy",
        )
        .to_string();
        let mut copy = ctx.local.clone();
        copy.id = copy_id.clone();
        copy.version = 1;
        copy.author_id = actor.into();
        copy.entities.clear();
        copy.embedding = None;
        let sequence = persist(tx, scope, &copy, false, Some(&ctx.local_metadata), true)?;
        result.copy_memory_id = Some(copy_id);
        result.processing_sequences.push(sequence);
        result.pending_push_sequences.push(sequence);
    }
    super::receipt::update_baseline(tx, scope, &ctx.memory_id, &ctx.remote)?;
    for sequence in &result.superseded_sequences {
        tx.execute(
            "INSERT INTO knowledge_cloud_superseded_outbox(sequence,resolution_id) VALUES(?1,?2)",
            params![sequence, record.resolution_id],
        )
        .map_err(storage)?;
    }
    for sequence in &result.conflict_sequences {
        tx.execute("INSERT INTO knowledge_cloud_resolved_pull_conflicts(tenant_id,project_id,sequence,resolution_id) VALUES(?1,?2,?3,?4)",params![scope.tenant_id,scope.project_id,sequence,record.resolution_id]).map_err(storage)?;
    }
    tx.execute("UPDATE knowledge_cloud_resolutions SET reconciliation_command_json=?2,reconciliation_archive_json=?3,reconciliation_json=?4 WHERE resolution_id=?1",params![record.resolution_id,command.to_string(),serde_json::to_string(ctx).map_err(storage)?,serde_json::to_string(&result).map_err(storage)?]).map_err(storage)?;
    Ok(())
}
