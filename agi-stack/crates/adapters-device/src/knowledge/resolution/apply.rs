use super::*;
fn local_content(context: &KnowledgePullConflictContext) -> RemoteMemoryContent {
    RemoteMemoryContent {
        title: context.local.title.clone(),
        content: context.local.content.clone(),
        content_type: context.local.content_type.clone(),
        tags: context.local.tags.clone(),
        metadata: context.local_metadata.clone(),
        status: context.local.status.clone(),
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
        if tx.execute("INSERT INTO knowledge_memories(tenant_id,project_id,id,revision,deleted,created_at_ms,payload)
            VALUES(?1,?2,?3,?4,?5,?6,?7) ON CONFLICT DO NOTHING",params![scope.tenant_id,scope.project_id,memory.id,memory.version,deleted,memory.created_at_ms,payload]).map_err(storage)?!=1 { return Err(KnowledgeError::Conflict); }
    } else {
        tx.execute(
            "UPDATE knowledge_memories SET revision=?4,deleted=?5,payload=?6,created_at_ms=?7
            WHERE tenant_id=?1 AND project_id=?2 AND id=?3",
            params![
                scope.tenant_id,
                scope.project_id,
                memory.id,
                memory.version,
                deleted,
                payload,
                memory.created_at_ms
            ],
        )
        .map_err(storage)?;
    }
    tx.execute("INSERT INTO knowledge_processing_changes(tenant_id,project_id,memory_id,revision,operation,payload)
        VALUES(?1,?2,?3,?4,?5,?6)",params![scope.tenant_id,scope.project_id,memory.id,memory.version,if deleted {"delete"} else {"upsert"},payload]).map_err(storage)?;
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
    id: &str,
    command: &KnowledgePullConflictResolution,
    context: &KnowledgePullConflictContext,
    superseded: Vec<u64>,
) -> KnowledgeResult<KnowledgeResolutionReceipt> {
    let remote = version(&context.remote)?;
    let (content, deleted, enqueue) = match &command.choice {
        KnowledgeConflictChoice::UseRemote {} | KnowledgeConflictChoice::KeepBoth {} => {
            (remote.content.clone(), remote.deleted, false)
        }
        KnowledgeConflictChoice::UseLocal {} => {
            (local_content(context), context.local_deleted, true)
        }
        KnowledgeConflictChoice::Merged { content } => (content.remote(), false, true),
    };
    content.validate()?;
    let memory = Memory {
        id: context.memory_id.clone(),
        project_id: scope.project_id.clone(),
        title: content.title,
        content: content.content,
        content_type: content.content_type,
        tags: content.tags,
        status: content.status,
        author_id: remote.author_id.clone(),
        created_at_ms: remote.created_at_ms,
        version: context
            .local
            .version
            .checked_add(1)
            .ok_or(KnowledgeError::InvalidInput)?,
        entities: vec![],
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
    let mut processing_sequences = vec![sequence];
    let mut pending_push_sequences = if enqueue { vec![sequence] } else { vec![] };
    let copy_memory_id = if matches!(command.choice, KnowledgeConflictChoice::KeepBoth {}) {
        local_content(context).validate()?;
        let namespace = Uuid::parse_str(id).map_err(storage)?;
        let copy_id = Uuid::new_v5(&namespace, b"local-copy").to_string();
        let mut copy = context.local.clone();
        copy.id = copy_id.clone();
        copy.version = 1;
        copy.author_id = actor.into();
        copy.entities.clear();
        copy.embedding = None;
        // keep_both explicitly creates a live copy even when the preserved local side is a tombstone.
        let sequence = persist(tx, scope, &copy, false, Some(&context.local_metadata), true)?;
        processing_sequences.push(sequence);
        pending_push_sequences.push(sequence);
        Some(copy_id)
    } else {
        None
    };
    tx.execute("INSERT INTO knowledge_sync_remote_versions(tenant_id,project_id,memory_id,version_json)
        VALUES(?1,?2,?3,?4) ON CONFLICT(tenant_id,project_id,memory_id) DO UPDATE SET version_json=excluded.version_json",params![scope.tenant_id,scope.project_id,context.memory_id,serde_json::to_string(&context.remote).map_err(storage)?]).map_err(storage)?;
    Ok(KnowledgeResolutionReceipt {
        resolution_id: id.into(),
        memory_id: context.memory_id.clone(),
        local_revision: memory.version,
        remote_baseline_revision: remote.revision,
        copy_memory_id,
        processing_sequences,
        pending_push_sequences,
        superseded_sequences: superseded,
        conflict_sequences: context.conflict_sequences.clone(),
    })
}
