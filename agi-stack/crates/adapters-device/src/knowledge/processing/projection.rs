use super::*;

pub(super) fn validate_projection(output: &ProcessingProjection) -> KnowledgeResult<()> {
    if output
        .entities
        .iter()
        .any(|entity| entity.name.trim().is_empty() || entity.kind.trim().is_empty())
        || output.relationships.iter().any(|relation| {
            usize::try_from(relation.source_index)
                .map_or(true, |index| index >= output.entities.len())
                || usize::try_from(relation.target_index)
                    .map_or(true, |index| index >= output.entities.len())
                || relation.relation_type.trim().is_empty()
                || relation.fact.trim().is_empty()
                || !relation.score.is_finite()
                || !(0.0..=1.0).contains(&relation.score)
        })
    {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

pub(super) fn complete(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    lease: &ProcessingLease,
    output: ProcessingProjection,
    now_ms: i64,
) -> KnowledgeResult<()> {
    validate_projection(&output)?;
    transact(repo, |tx| {
        active_lease(tx, scope, lease, now_ms)?;
        let audited: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM knowledge_processing_audits WHERE change_sequence=?1 AND attempt=?2)",
            params![lease.source.change_sequence,lease.attempt], |row| row.get(0),
        ).map_err(storage)?;
        if audited {
            return Err(KnowledgeError::Conflict);
        }
        publish(tx, scope, lease, &output)
    })
}

pub(super) fn publish(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    lease: &ProcessingLease,
    output: &ProcessingProjection,
) -> KnowledgeResult<()> {
    validate_projection(output)?;
    let json = serde_json::to_string(output).map_err(storage)?;
    let result =
        serde_json::to_string(&ProcessingResult::Projection(output.clone())).map_err(storage)?;
    let source = &lease.source;
    tx.execute(
        "UPDATE knowledge_processing_jobs SET state='completed',worker_id=NULL,token=NULL,expires_at_ms=NULL,failure_json=NULL,result_json=?1
         WHERE change_sequence=?2 AND tenant_id=?3 AND project_id=?4",
        params![result,source.change_sequence,scope.tenant_id,scope.project_id],
    ).map_err(storage)?;
    tx.execute(
        "INSERT INTO knowledge_derived_projections(tenant_id,project_id,memory_id,revision,change_sequence,projection_json)
         VALUES(?1,?2,?3,?4,?5,?6) ON CONFLICT(tenant_id,project_id,memory_id)
         DO UPDATE SET revision=excluded.revision,change_sequence=excluded.change_sequence,projection_json=excluded.projection_json",
        params![scope.tenant_id,scope.project_id,source.memory_id,source.revision,source.change_sequence,json],
    ).map_err(storage)?;
    Ok(())
}

pub(super) fn status(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    source: &ProcessingSource,
) -> KnowledgeResult<Option<ProcessingStatus>> {
    validate_source(scope, source)?;
    let conn = repo.conn.lock().map_err(storage)?;
    let stored = conn.query_row(
        "SELECT state,attempt,failure_json,result_json FROM knowledge_processing_jobs
         WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND revision=?4 AND change_sequence=?5",
        params![scope.tenant_id,scope.project_id,source.memory_id,source.revision,source.change_sequence],
        |row| Ok((row.get::<_,String>(0)?,row.get::<_,u32>(1)?,row.get::<_,Option<String>>(2)?,row.get::<_,Option<String>>(3)?)),
    ).optional().map_err(storage)?;
    let Some((state, attempt, failure, result)) = stored else {
        return Ok(None);
    };
    let state = match state.as_str() {
        "pending" => ProcessingState::Pending,
        "leased" => ProcessingState::Leased,
        "completed" => ProcessingState::Completed,
        "failed" => ProcessingState::Failed,
        "superseded" => ProcessingState::Superseded,
        _ => return Err(KnowledgeError::Storage("invalid processing state".into())),
    };
    Ok(Some(ProcessingStatus {
        source: source.clone(),
        state,
        attempt,
        failure: failure
            .map(|value| serde_json::from_str(&value).map_err(storage))
            .transpose()?,
        result: result
            .map(|value| serde_json::from_str(&value).map_err(storage))
            .transpose()?,
    }))
}

pub(super) fn read(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    memory_id: &str,
) -> KnowledgeResult<Option<DerivedProjection>> {
    validate(scope, memory_id)?;
    let conn = repo.conn.lock().map_err(storage)?;
    let stored = conn.query_row(
        "SELECT p.revision,p.change_sequence,p.projection_json FROM knowledge_derived_projections p
         JOIN knowledge_memories m ON m.tenant_id=p.tenant_id AND m.project_id=p.project_id
           AND m.id=p.memory_id AND m.revision=p.revision AND m.deleted=0
         JOIN knowledge_processing_changes c ON c.sequence=p.change_sequence AND c.tenant_id=p.tenant_id
           AND c.project_id=p.project_id AND c.memory_id=p.memory_id AND c.revision=p.revision
           AND c.operation='upsert' AND c.payload=m.payload
         WHERE p.tenant_id=?1 AND p.project_id=?2 AND p.memory_id=?3",
        params![scope.tenant_id,scope.project_id,memory_id],
        |row| Ok((row.get::<_,u32>(0)?,row.get::<_,u64>(1)?,row.get::<_,String>(2)?)),
    ).optional().map_err(storage)?;
    let Some((revision, change_sequence, json)) = stored else {
        return Ok(None);
    };
    let projection = serde_json::from_str(&json).map_err(storage)?;
    validate_projection(&projection)?;
    Ok(Some(DerivedProjection {
        source: ProcessingSource {
            tenant_id: scope.tenant_id.clone(),
            project_id: scope.project_id.clone(),
            memory_id: memory_id.into(),
            revision,
            change_sequence,
        },
        projection,
    }))
}
