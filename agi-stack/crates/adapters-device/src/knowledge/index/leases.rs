use super::*;

fn deadline(now: i64, lease_ms: u64) -> KnowledgeResult<i64> {
    if lease_ms == 0 {
        return Err(KnowledgeError::InvalidInput);
    }
    now.checked_add(i64::try_from(lease_ms).map_err(|_| KnowledgeError::InvalidInput)?)
        .ok_or(KnowledgeError::InvalidInput)
}
fn active(tx: &Transaction<'_>, lease: &IndexLease, now: i64) -> KnowledgeResult<i64> {
    ensure_config(
        tx,
        &DesiredEmbeddingConfig {
            revision: lease.config_revision,
            build: lease.build.clone(),
        },
    )?;
    let current = current_input(tx, &lease.build, &lease.input)?;
    if current.text != lease.input_text
        || lease.worker_id.trim().is_empty()
        || lease.token.is_empty()
        || lease.attempt == 0
    {
        return Err(KnowledgeError::Conflict);
    }
    let b = &lease.build;
    let i = &lease.input;
    tx.query_row("SELECT expires_at_ms FROM knowledge_index_jobs
        WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND change_sequence=?4 AND audit_attempt=?5 AND input_digest=?6
          AND memory_id=?7 AND revision=?8 AND state='leased' AND worker_id=?9 AND token=?10 AND attempt=?11 AND expires_at_ms>?12 AND config_revision=?13",
        params![b.scope.tenant_id,b.scope.project_id,b.build_id,i.source.change_sequence,i.audit_attempt,i.input_digest,i.source.memory_id,i.source.revision,lease.worker_id,lease.token,lease.attempt,now,lease.config_revision],|r|r.get(0)
    ).optional().map_err(storage)?.ok_or(KnowledgeError::Conflict)
}

impl SqliteKnowledgeRepository {
    pub fn claim_index_durable(
        &self,
        config: &DesiredEmbeddingConfig,
        worker_id: &str,
        lease_ms: u64,
        clock: Clock<'_>,
    ) -> KnowledgeResult<Option<IndexLease>> {
        if worker_id.trim().is_empty() {
            return Err(KnowledgeError::InvalidInput);
        }
        let build = &config.build;
        timed(self, clock, |tx, now| {
            ensure_config(tx, config)?;
            let expires_at_ms = deadline(now, lease_ms)?;
            for current in reconcile(tx, build)? {
                let i = &current.identity;
                let available:Option<u32> = tx.query_row("SELECT attempt FROM knowledge_index_jobs
                    WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND change_sequence=?4 AND audit_attempt=?5 AND input_digest=?6
                      AND (state='pending' OR (state='leased' AND expires_at_ms<=?7))",
                    params![build.scope.tenant_id,build.scope.project_id,build.build_id,i.source.change_sequence,i.audit_attempt,i.input_digest,now],|r|r.get(0)).optional().map_err(storage)?;
                let Some(attempt) = available else { continue };
                let attempt = attempt.checked_add(1).ok_or(KnowledgeError::Conflict)?;
                let token = uuid::Uuid::new_v4().to_string();
                tx.execute("UPDATE knowledge_index_jobs SET state='leased',attempt=?1,worker_id=?2,token=?3,expires_at_ms=?4,failure_json=NULL,config_revision=?11
                    WHERE tenant_id=?5 AND project_id=?6 AND build_id=?7 AND change_sequence=?8 AND audit_attempt=?9 AND input_digest=?10",
                    params![attempt,worker_id,token,expires_at_ms,build.scope.tenant_id,build.scope.project_id,build.build_id,i.source.change_sequence,i.audit_attempt,i.input_digest,config.revision]).map_err(storage)?;
                return Ok((
                    Some(IndexLease {
                        config_revision: config.revision,
                        build: build.clone(),
                        input: current.identity,
                        input_text: current.text,
                        worker_id: worker_id.into(),
                        token,
                        attempt,
                        expires_at_ms,
                    }),
                    Some(expires_at_ms),
                ));
            }
            Ok((None, None))
        })
    }

    pub fn renew_index_durable(
        &self,
        lease: &IndexLease,
        lease_ms: u64,
        clock: Clock<'_>,
    ) -> KnowledgeResult<IndexLease> {
        timed(self, clock, |tx, now| {
            let previous = active(tx, lease, now)?;
            let expires_at_ms = deadline(now, lease_ms)?.max(previous);
            let b = &lease.build;
            let i = &lease.input;
            tx.execute("UPDATE knowledge_index_jobs SET expires_at_ms=?1 WHERE tenant_id=?2 AND project_id=?3 AND build_id=?4
                AND change_sequence=?5 AND audit_attempt=?6 AND input_digest=?7",
                params![expires_at_ms,b.scope.tenant_id,b.scope.project_id,b.build_id,i.source.change_sequence,i.audit_attempt,i.input_digest]).map_err(storage)?;
            Ok((
                IndexLease {
                    expires_at_ms,
                    ..lease.clone()
                },
                Some(previous),
            ))
        })
    }

    pub fn complete_index_durable(
        &self,
        lease: &IndexLease,
        vector: &[f32],
        clock: Clock<'_>,
    ) -> KnowledgeResult<()> {
        validate_vector(&lease.build, vector)?;
        timed(self, clock, |tx, now| {
            let expires = active(tx, lease, now)?;
            let b = &lease.build;
            let i = &lease.input;
            tx.execute("INSERT INTO knowledge_index_vectors(tenant_id,project_id,build_id,change_sequence,audit_attempt,input_digest,index_attempt,vector_json)
                VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
                params![b.scope.tenant_id,b.scope.project_id,b.build_id,i.source.change_sequence,i.audit_attempt,i.input_digest,lease.attempt,serde_json::to_string(vector).map_err(storage)?]).map_err(storage)?;
            finish(tx, lease, "completed", None)?;
            Ok(((), Some(expires)))
        })
    }

    pub fn fail_index_durable(
        &self,
        lease: &IndexLease,
        failure: IndexFailure,
        clock: Clock<'_>,
    ) -> KnowledgeResult<()> {
        timed(self, clock, |tx, now| {
            let expires = active(tx, lease, now)?;
            finish(
                tx,
                lease,
                "failed",
                Some(serde_json::to_string(&failure).map_err(storage)?),
            )?;
            Ok(((), Some(expires)))
        })
    }

    pub fn retry_index_durable(
        &self,
        config: &DesiredEmbeddingConfig,
        input: &IndexSource,
        expected_attempt: u32,
        clock: Clock<'_>,
    ) -> KnowledgeResult<()> {
        let build = &config.build;
        timed(self, clock, |tx, _| {
            ensure_config(tx, config)?;
            current_input(tx, build, input)?;
            let Some(status) = job(tx, build, input)? else {
                return Err(KnowledgeError::Conflict);
            };
            if status.state != IndexJobState::Failed || status.attempt != expected_attempt {
                return Err(KnowledgeError::Conflict);
            };
            tx.execute("UPDATE knowledge_index_jobs SET state='pending',failure_json=NULL WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3
                AND change_sequence=?4 AND audit_attempt=?5 AND input_digest=?6",
                params![build.scope.tenant_id,build.scope.project_id,build.build_id,input.source.change_sequence,input.audit_attempt,input.input_digest]).map_err(storage)?;
            Ok(((), None))
        })
    }
}

fn finish(
    tx: &Transaction<'_>,
    lease: &IndexLease,
    state: &str,
    failure: Option<String>,
) -> KnowledgeResult<()> {
    let b = &lease.build;
    let i = &lease.input;
    tx.execute("UPDATE knowledge_index_jobs SET state=?1,worker_id=NULL,token=NULL,expires_at_ms=NULL,failure_json=?2
        WHERE tenant_id=?3 AND project_id=?4 AND build_id=?5 AND change_sequence=?6 AND audit_attempt=?7 AND input_digest=?8",
        params![state,failure,b.scope.tenant_id,b.scope.project_id,b.build_id,i.source.change_sequence,i.audit_attempt,i.input_digest]).map_err(storage)?;
    Ok(())
}
