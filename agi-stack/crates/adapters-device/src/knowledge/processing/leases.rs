use uuid::Uuid;

use super::*;

pub(super) fn claim(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    worker_id: &str,
    now_ms: i64,
    lease_ms: u64,
) -> KnowledgeResult<Option<ProcessingLease>> {
    validate(scope, worker_id)?;
    let expires_at_ms = deadline(now_ms, lease_ms)?;
    transact(repo, |tx| {
        let candidate = tx.query_row(
            "SELECT j.memory_id,j.revision,j.change_sequence,j.attempt FROM knowledge_processing_jobs j
             JOIN knowledge_memories m ON m.tenant_id=j.tenant_id AND m.project_id=j.project_id
               AND m.id=j.memory_id AND m.revision=j.revision AND m.deleted=0
             JOIN knowledge_processing_changes c ON c.sequence=j.change_sequence
               AND c.tenant_id=j.tenant_id AND c.project_id=j.project_id AND c.memory_id=j.memory_id
               AND c.revision=j.revision AND c.operation='upsert' AND c.payload=m.payload
             WHERE j.tenant_id=?1 AND j.project_id=?2
               AND (j.state='pending' OR (j.state='leased' AND j.expires_at_ms<=?3))
             ORDER BY j.change_sequence LIMIT 1",
            params![scope.tenant_id,scope.project_id,now_ms],
            |row| Ok((row.get::<_,String>(0)?,row.get::<_,u32>(1)?,row.get::<_,u64>(2)?,row.get::<_,u32>(3)?)),
        ).optional().map_err(storage)?;
        let Some((memory_id, revision, change_sequence, attempt)) = candidate else {
            return Ok(None);
        };
        let lease = ProcessingLease {
            source: ProcessingSource {
                tenant_id: scope.tenant_id.clone(),
                project_id: scope.project_id.clone(),
                memory_id,
                revision,
                change_sequence,
            },
            worker_id: worker_id.into(),
            token: Uuid::new_v4().to_string(),
            attempt: attempt.checked_add(1).ok_or(KnowledgeError::Conflict)?,
            expires_at_ms,
        };
        tx.execute(
            "UPDATE knowledge_processing_jobs SET state='leased',worker_id=?2,token=?3,attempt=?4,expires_at_ms=?5,failure_json=NULL
             WHERE change_sequence=?1 AND tenant_id=?6 AND project_id=?7",
            params![change_sequence,worker_id,lease.token,lease.attempt,expires_at_ms,scope.tenant_id,scope.project_id],
        ).map_err(storage)?;
        Ok(Some(lease))
    })
}

pub(super) fn renew(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    lease: &ProcessingLease,
    now_ms: i64,
    lease_ms: u64,
) -> KnowledgeResult<ProcessingLease> {
    let proposed = deadline(now_ms, lease_ms)?;
    transact(repo, |tx| {
        let expires_at_ms = proposed.max(active_lease(tx, scope, lease, now_ms)?);
        tx.execute(
            "UPDATE knowledge_processing_jobs SET expires_at_ms=?1 WHERE change_sequence=?2 AND tenant_id=?3 AND project_id=?4",
            params![expires_at_ms,lease.source.change_sequence,scope.tenant_id,scope.project_id],
        ).map_err(storage)?;
        Ok(ProcessingLease {
            expires_at_ms,
            ..lease.clone()
        })
    })
}

pub(super) fn fail(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    lease: &ProcessingLease,
    failure: ProcessingFailure,
    now_ms: i64,
) -> KnowledgeResult<()> {
    transact(repo, |tx| {
        active_lease(tx, scope, lease, now_ms)?;
        tx.execute(
            "UPDATE knowledge_processing_jobs SET state='failed',worker_id=NULL,token=NULL,expires_at_ms=NULL,failure_json=?1
             WHERE change_sequence=?2 AND tenant_id=?3 AND project_id=?4",
            params![serde_json::to_string(&failure).map_err(storage)?,lease.source.change_sequence,scope.tenant_id,scope.project_id],
        ).map_err(storage)?;
        Ok(())
    })
}

pub(super) fn retry(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    source: &ProcessingSource,
    expected_attempt: u32,
) -> KnowledgeResult<()> {
    validate_source(scope, source)?;
    transact(repo, |tx| {
        if !current_source(tx, source)? {
            return Err(KnowledgeError::Conflict);
        }
        let changed = tx.execute(
            "UPDATE knowledge_processing_jobs SET state='pending',failure_json=NULL
             WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND revision=?4 AND change_sequence=?5
               AND state='failed' AND attempt=?6",
            params![scope.tenant_id,scope.project_id,source.memory_id,source.revision,source.change_sequence,expected_attempt],
        ).map_err(storage)?;
        if changed != 1 {
            return Err(KnowledgeError::Conflict);
        }
        Ok(())
    })
}
