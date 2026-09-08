use super::*;

fn validate_lease(scope: &KnowledgeScope, lease: &CommunityJobLease) -> KnowledgeResult<()> {
    validate(scope, &lease.build_id)?;
    validate(scope, &lease.candidate_id)?;
    validate(scope, &lease.worker_id)?;
    if lease.tenant_id != scope.tenant_id
        || lease.project_id != scope.project_id
        || lease.token.is_empty()
        || lease.attempt == 0
    {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

impl SqliteKnowledgeRepository {
    pub fn begin_community_audit_durable(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        invocation: CommunityInvocation,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<()> {
        validate_lease(scope, lease)?;
        if !invocation.validate() {
            return Err(KnowledgeError::InvalidInput);
        }
        let invocation_json = encode(&invocation)?;
        transact(self, clock, |tx, now| {
            let expiry = jobs::active(tx, scope, lease, now)?;
            let build = read_build(tx, scope, &lease.build_id)?.ok_or(KnowledgeError::Conflict)?;
            let expected =
                candidate_input(&build, &lease.candidate_id)?.ok_or(KnowledgeError::Conflict)?;
            if invocation.input != expected || !current_graph(tx, scope, &build)? {
                return Err(KnowledgeError::Conflict);
            }
            let changed = tx.execute("INSERT INTO knowledge_community_audits
                (tenant_id,project_id,build_id,candidate_id,attempt,worker_id,token,invocation_json,started_at_ms)
                VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9) ON CONFLICT DO NOTHING",
                params![scope.tenant_id,scope.project_id,lease.build_id,lease.candidate_id,lease.attempt,
                    lease.worker_id,lease.token,invocation_json,now]).map_err(storage)?;
            if changed != 1 {
                return Err(KnowledgeError::Conflict);
            }
            Ok(((), Some(expiry)))
        })
    }

    /// Returns the durable terminal outcome, which can be a typed rejection of
    /// the submitted result. Lease loss never changes the replacement worker's
    /// job. A duplicate identical terminal output returns the original record.
    pub fn finish_community_audit_durable(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        outcome: CommunityAuditOutcome,
        latency_ms: u64,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<CommunityAuditRecord> {
        validate_lease(scope, lease)?;
        let latency = i64::try_from(latency_ms).map_err(|_| KnowledgeError::InvalidInput)?;
        transact(self, clock, |tx, now| {
            let (mut record, worker, token, original_request_digest) = read::audit_record(
                tx,
                scope,
                &lease.build_id,
                &lease.candidate_id,
                lease.attempt,
            )?
            .ok_or(KnowledgeError::Conflict)?;
            if worker != lease.worker_id
                || token != lease.token
                || record.invocation.input.graph_digest != lease.graph_digest
            {
                return Err(KnowledgeError::Conflict);
            }
            if !outcome.validate(&record.invocation.input) {
                return Err(KnowledgeError::InvalidInput);
            }
            let request_digest = digest("knowledge-community-terminal-request-v1", &outcome)?;
            if let Some(original) = &record.outcome {
                return if original == &outcome
                    || original_request_digest.as_deref() == Some(&request_digest)
                {
                    Ok((record, None))
                } else {
                    Err(KnowledgeError::IdempotencyConflict)
                };
            }
            if now < record.started_at_ms {
                return Err(KnowledgeError::InvalidInput);
            }
            let expiry = match jobs::active(tx, scope, lease, now) {
                Ok(expiry) => Some(expiry),
                Err(KnowledgeError::Conflict) => None,
                Err(error) => return Err(error),
            };
            let terminal = match &outcome {
                CommunityAuditOutcome::Applied { .. } if expiry.is_none() => {
                    CommunityAuditOutcome::Failed {
                        code: CommunityAuditFailure::LeaseLost,
                        response_digest: Some(request_digest.clone()),
                    }
                }
                CommunityAuditOutcome::Applied { .. } => {
                    let build =
                        read_build(tx, scope, &lease.build_id)?.ok_or(KnowledgeError::Conflict)?;
                    if candidate_input(&build, &lease.candidate_id)?.as_ref()
                        != Some(&record.invocation.input)
                    {
                        return Err(KnowledgeError::Conflict);
                    }
                    if current_graph(tx, scope, &build)? {
                        outcome.clone()
                    } else {
                        CommunityAuditOutcome::Failed {
                            code: CommunityAuditFailure::GraphChanged,
                            response_digest: Some(request_digest.clone()),
                        }
                    }
                }
                CommunityAuditOutcome::Failed { .. } => outcome.clone(),
            };
            match &terminal {
                CommunityAuditOutcome::Applied { submission } => {
                    tx.execute("INSERT INTO knowledge_community_results
                        (tenant_id,project_id,build_id,candidate_id,attempt,graph_digest,submission_json,finished_at_ms)
                        VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
                        params![scope.tenant_id,scope.project_id,lease.build_id,lease.candidate_id,lease.attempt,
                            lease.graph_digest,encode(submission)?,now]).map_err(storage)?;
                    tx.execute("UPDATE knowledge_community_jobs SET state='completed',worker_id=NULL,token=NULL,expires_at_ms=NULL,failure_json=NULL
                        WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4",
                        params![scope.tenant_id,scope.project_id,lease.build_id,lease.candidate_id]).map_err(storage)?;
                }
                CommunityAuditOutcome::Failed { code, .. } if expiry.is_some() => {
                    let failure = match code {
                        CommunityAuditFailure::Cancelled => CommunityJobFailure::Cancelled,
                        CommunityAuditFailure::ProviderUnavailable => {
                            CommunityJobFailure::WorkerUnavailable
                        }
                        _ => CommunityJobFailure::ExecutionFailed,
                    };
                    tx.execute("UPDATE knowledge_community_jobs SET state='failed',worker_id=NULL,token=NULL,expires_at_ms=NULL,failure_json=?5
                        WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4",
                        params![scope.tenant_id,scope.project_id,lease.build_id,lease.candidate_id,encode(&failure)?]).map_err(storage)?;
                }
                CommunityAuditOutcome::Failed { .. } => (),
            }
            tx.execute("UPDATE knowledge_community_audits SET outcome_json=?6,finished_at_ms=?7,latency_ms=?8,request_digest=?9
                WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4 AND attempt=?5",
                params![scope.tenant_id,scope.project_id,lease.build_id,lease.candidate_id,lease.attempt,encode(&terminal)?,now,latency,request_digest]).map_err(storage)?;
            record.outcome = Some(terminal);
            record.finished_at_ms = Some(now);
            record.latency_ms = Some(latency_ms);
            Ok((record, expiry))
        })
    }
}
