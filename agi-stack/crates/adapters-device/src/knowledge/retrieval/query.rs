use super::*;

pub(super) const CURRENT_PROJECTIONS: &str = "SELECT p.memory_id,p.revision,p.change_sequence,p.projection_json,m.payload,j.attempt,a.outcome_json,a.invocation_json
 FROM knowledge_derived_projections p
 JOIN knowledge_memories m ON m.tenant_id=p.tenant_id AND m.project_id=p.project_id AND m.id=p.memory_id AND m.revision=p.revision AND m.deleted=0
 JOIN knowledge_processing_changes c ON c.sequence=p.change_sequence AND c.tenant_id=p.tenant_id AND c.project_id=p.project_id AND c.memory_id=p.memory_id AND c.revision=p.revision AND c.operation='upsert' AND c.payload=m.payload
 JOIN knowledge_processing_jobs j ON j.change_sequence=p.change_sequence AND j.tenant_id=p.tenant_id AND j.project_id=p.project_id AND j.memory_id=p.memory_id AND j.revision=p.revision AND j.state='completed'
 JOIN knowledge_processing_audits a ON a.change_sequence=j.change_sequence AND a.attempt=j.attempt AND a.tenant_id=j.tenant_id AND a.project_id=j.project_id AND a.memory_id=j.memory_id AND a.revision=j.revision AND a.finished_at_ms IS NOT NULL AND a.latency_ms IS NOT NULL AND json_extract(a.outcome_json,'$.status')='applied'
 WHERE p.tenant_id=?1 AND p.project_id=?2 AND (?3 IS NULL OR (p.memory_id=?3 AND p.revision=?4 AND p.change_sequence=?5))
 AND p.change_sequence<=?6 AND p.change_sequence>=?7
 AND (?8 IS NULL OR instr(json_extract(m.payload,'$.title'),?8)>0 OR instr(json_extract(m.payload,'$.content'),?8)>0)
 ORDER BY p.change_sequence,p.memory_id";

pub(super) fn validate_request(
    scope: &KnowledgeScope,
    request: &RetrievalRequest,
    kind: RetrievalKind,
    literal: Option<&str>,
) -> KnowledgeResult<()> {
    validate(scope, "retrieval")?;
    if request.limit == 0
        || request.limit > MAX_RETRIEVAL_PAGE_SIZE
        || literal.is_some_and(|s| s.is_empty() || s.len() > MAX_LITERAL_QUERY_BYTES)
    {
        return Err(KnowledgeError::InvalidInput);
    }
    if let Some(source) = &request.source {
        validate(scope, &source.memory_id)?;
        if source.tenant_id != scope.tenant_id
            || source.project_id != scope.project_id
            || source.revision == 0
            || source.change_sequence == 0
            || i64::try_from(source.change_sequence).is_err()
        {
            return Err(KnowledgeError::InvalidInput);
        }
    }
    if let Some(cursor) = &request.cursor {
        if cursor.tenant_id != scope.tenant_id
            || cursor.project_id != scope.project_id
            || cursor.kind != kind
            || cursor.source != request.source
            || cursor.literal.as_deref() != literal
            || cursor.after.change_sequence == 0
            || cursor.after.change_sequence > cursor.upper_change_sequence
            || i64::try_from(cursor.upper_change_sequence).is_err()
            || (kind == RetrievalKind::Text && cursor.after.item_index != 0)
        {
            return Err(KnowledgeError::InvalidInput);
        }
    }
    Ok(())
}

pub(super) fn decode(
    row: &rusqlite::Row<'_>,
    scope: &KnowledgeScope,
) -> KnowledgeResult<CurrentProjection> {
    let source = ProcessingSource {
        tenant_id: scope.tenant_id.clone(),
        project_id: scope.project_id.clone(),
        memory_id: row.get(0).map_err(storage)?,
        revision: row.get(1).map_err(storage)?,
        change_sequence: row.get(2).map_err(storage)?,
    };
    let projection: ProcessingProjection =
        serde_json::from_str(&row.get::<_, String>(3).map_err(storage)?).map_err(storage)?;
    let memory: Memory =
        serde_json::from_str(&row.get::<_, String>(4).map_err(storage)?).map_err(storage)?;
    let attempt = row.get(5).map_err(storage)?;
    let outcome: ProcessingAuditOutcome =
        serde_json::from_str(&row.get::<_, String>(6).map_err(storage)?).map_err(storage)?;
    let invocation: ProcessingInvocation =
        serde_json::from_str(&row.get::<_, String>(7).map_err(storage)?).map_err(storage)?;
    let ProcessingAuditOutcome::Applied { submission } = outcome else {
        return Err(KnowledgeError::Conflict);
    };
    if !submission.validate(&source)
        || submission.projection() != projection
        || invocation.input.source != source
        || invocation.input.title != memory.title
        || invocation.input.content != memory.content
        || invocation.tool_name != SUBMIT_PROJECTION_TOOL
        || invocation.contract_version != 1
        || memory.id != source.memory_id
        || memory.project_id != source.project_id
        || memory.version != source.revision
    {
        return Err(KnowledgeError::Storage(
            "current audited projection is inconsistent".into(),
        ));
    }
    Ok(CurrentProjection {
        source,
        attempt,
        memory,
        projection,
    })
}
