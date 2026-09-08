use super::*;

type StoredAudit = (CommunityAuditRecord, String, String, Option<String>);

pub(super) fn audit_record(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    build_id: &str,
    candidate_id: &str,
    attempt: u32,
) -> KnowledgeResult<Option<StoredAudit>> {
    let row = tx.query_row(
        "SELECT invocation_json,started_at_ms,finished_at_ms,latency_ms,outcome_json,worker_id,token,request_digest
         FROM knowledge_community_audits WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4 AND attempt=?5",
        params![scope.tenant_id,scope.project_id,build_id,candidate_id,attempt], |row| {
            Ok((row.get::<_,String>(0)?,row.get::<_,i64>(1)?,row.get::<_,Option<i64>>(2)?,
                row.get::<_,Option<u64>>(3)?,row.get::<_,Option<String>>(4)?,row.get::<_,String>(5)?,row.get::<_,String>(6)?,row.get::<_,Option<String>>(7)?))
        }).optional().map_err(storage)?;
    let Some((
        invocation,
        started_at_ms,
        finished_at_ms,
        latency_ms,
        outcome,
        worker,
        token,
        request_digest,
    )) = row
    else {
        return Ok(None);
    };
    let invocation: CommunityInvocation = decode_json(&invocation)?;
    let outcome: Option<CommunityAuditOutcome> = outcome.as_deref().map(decode_json).transpose()?;
    if !invocation.validate()
        || invocation.input.build_id != build_id
        || invocation.input.candidate.membership_digest != candidate_id
        || invocation.input.snapshot.tenant_id != scope.tenant_id
        || invocation.input.snapshot.project_id != scope.project_id
        || started_at_ms < 0
        || finished_at_ms.is_some_and(|finished| finished < started_at_ms)
        || outcome.is_some() != finished_at_ms.is_some()
        || outcome.is_some() != latency_ms.is_some()
        || outcome.is_some() != request_digest.is_some()
        || request_digest.as_ref().is_some_and(|digest| {
            digest.len() != 64 || !digest.bytes().all(|b| b.is_ascii_hexdigit())
        })
        || outcome
            .as_ref()
            .is_some_and(|outcome| !outcome.validate(&invocation.input))
    {
        return Err(KnowledgeError::Conflict);
    }
    Ok(Some((
        CommunityAuditRecord {
            invocation,
            attempt,
            started_at_ms,
            finished_at_ms,
            latency_ms,
            outcome,
        },
        worker,
        token,
        request_digest,
    )))
}

pub(super) fn results(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    build: &CommunityBuildInput,
) -> KnowledgeResult<Vec<CommunityResult>> {
    let mut stmt = tx.prepare("SELECT candidate_id,attempt,graph_digest,submission_json,finished_at_ms
        FROM knowledge_community_results WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 ORDER BY candidate_id").map_err(storage)?;
    let mut rows = stmt
        .query(params![
            scope.tenant_id,
            scope.project_id,
            build.receipt.build_id
        ])
        .map_err(storage)?;
    let mut output = Vec::new();
    while let Some(row) = rows.next().map_err(storage)? {
        let candidate_id: String = row.get(0).map_err(storage)?;
        let attempt: u32 = row.get(1).map_err(storage)?;
        let graph: String = row.get(2).map_err(storage)?;
        let submission: CommunitySubmission =
            decode_json(&row.get::<_, String>(3).map_err(storage)?)?;
        let finished_at_ms: i64 = row.get(4).map_err(storage)?;
        let input = candidate_input(build, &candidate_id)?.ok_or(KnowledgeError::Conflict)?;
        let (audit, _, _, _) =
            audit_record(tx, scope, &build.receipt.build_id, &candidate_id, attempt)?
                .ok_or(KnowledgeError::Conflict)?;
        if graph != build.receipt.graph_digest
            || !submission.validate(&input)
            || audit.invocation.input != input
            || audit.outcome
                != Some(CommunityAuditOutcome::Applied {
                    submission: submission.clone(),
                })
            || audit.finished_at_ms != Some(finished_at_ms)
        {
            return Err(KnowledgeError::Conflict);
        }
        output.push(CommunityResult {
            build_id: build.receipt.build_id.clone(),
            candidate_id,
            attempt,
            submission,
            finished_at_ms,
        });
    }
    Ok(output)
}

pub(super) fn status(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    build: &CommunityBuildInput,
    results: &[CommunityResult],
) -> KnowledgeResult<CommunityBuildStatus> {
    let mut stmt = tx
        .prepare(
            "SELECT candidate_id,state,attempt FROM knowledge_community_jobs
        WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3",
        )
        .map_err(storage)?;
    let mut rows = stmt
        .query(params![
            scope.tenant_id,
            scope.project_id,
            build.receipt.build_id
        ])
        .map_err(storage)?;
    let mut jobs = 0usize;
    let mut completed = 0usize;
    let mut failed = 0u32;
    while let Some(row) = rows.next().map_err(storage)? {
        let candidate: String = row.get(0).map_err(storage)?;
        let state: String = row.get(1).map_err(storage)?;
        let attempt: u32 = row.get(2).map_err(storage)?;
        if !build
            .candidates
            .iter()
            .any(|c| c.membership_digest == candidate)
        {
            return Err(KnowledgeError::Conflict);
        }
        let result = results.iter().find(|r| r.candidate_id == candidate);
        if (state == "completed") != result.is_some()
            || result.is_some_and(|r| r.attempt != attempt)
        {
            return Err(KnowledgeError::Conflict);
        }
        jobs += 1;
        match state.as_str() {
            "completed" => completed += 1,
            "failed" => failed += 1,
            "pending" | "leased" => (),
            _ => return Err(KnowledgeError::Conflict),
        }
    }
    if jobs != build.candidates.len() || completed != results.len() {
        return Err(KnowledgeError::Conflict);
    }
    let ready_count = u32::try_from(
        results
            .iter()
            .filter(|r| matches!(r.submission.decision, CommunityDecision::Ready { .. }))
            .count(),
    )
    .map_err(storage)?;
    Ok(CommunityBuildStatus {
        build_id: build.receipt.build_id.clone(),
        candidate_count: build.receipt.candidate_count,
        ready_count,
        insufficient_evidence_count: u32::try_from(results.len()).map_err(storage)? - ready_count,
        failed_count: failed,
        state: if jobs == 0 {
            CommunityProgressState::CompletedEmpty
        } else if failed > 0 {
            CommunityProgressState::Failed
        } else if completed == jobs {
            CommunityProgressState::Completed
        } else {
            CommunityProgressState::Pending
        },
    })
}

impl SqliteKnowledgeRepository {
    pub fn community_results_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
    ) -> KnowledgeResult<Vec<CommunityResult>> {
        validate(scope, build_id)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        let output = read_build(&tx, scope, build_id)?
            .map(|build| results(&tx, scope, &build))
            .transpose()?
            .unwrap_or_default();
        tx.commit().map_err(storage)?;
        Ok(output)
    }

    pub fn community_build_status_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
    ) -> KnowledgeResult<Option<CommunityBuildStatus>> {
        validate(scope, build_id)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        let output = read_build(&tx, scope, build_id)?
            .map(|build| status(&tx, scope, &build, &results(&tx, scope, &build)?))
            .transpose()?;
        tx.commit().map_err(storage)?;
        Ok(output)
    }

    pub fn community_audit_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        candidate_id: &str,
        attempt: u32,
    ) -> KnowledgeResult<Option<CommunityAuditRecord>> {
        validate(scope, build_id)?;
        validate(scope, candidate_id)?;
        if attempt == 0 {
            return Err(KnowledgeError::InvalidInput);
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        let record = audit_record(&tx, scope, build_id, candidate_id, attempt)?
            .map(|(record, _, _, _)| record);
        tx.commit().map_err(storage)?;
        Ok(record)
    }
}
