use agistack_core::knowledge::processing::{audit::*, worker::SUBMIT_PROJECTION_TOOL};
use agistack_core::Memory;

use super::*;

pub(in super::super) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous >= 9 {
        let present: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_processing_audits')",[],|r|r.get(0)).map_err(storage)?;
        return if present {
            Ok(())
        } else {
            Err(KnowledgeError::Storage(
                "processing audit schema is missing".into(),
            ))
        };
    }
    tx.execute_batch(
        "CREATE TABLE knowledge_processing_audits (
        change_sequence INTEGER NOT NULL,
        attempt INTEGER NOT NULL CHECK(attempt>0),
        tenant_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        memory_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        worker_id TEXT NOT NULL,
        lease_token TEXT NOT NULL,
        invocation_json TEXT NOT NULL,
        started_at_ms INTEGER NOT NULL,
        finished_at_ms INTEGER,
        latency_ms INTEGER,
        outcome_json TEXT,
        PRIMARY KEY(change_sequence,attempt),
        CHECK((outcome_json IS NULL AND finished_at_ms IS NULL AND latency_ms IS NULL)
           OR (outcome_json IS NOT NULL AND finished_at_ms IS NOT NULL AND latency_ms>=0))
    );",
    )
    .map_err(storage)
}

impl SqliteKnowledgeRepository {
    pub fn claim_processing_durable(
        &self,
        scope: &KnowledgeScope,
        worker_id: &str,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<Option<ProcessingLease>> {
        leases::claim(self, scope, worker_id, now_ms, lease_ms)
    }
    pub fn renew_processing_durable(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<ProcessingLease> {
        leases::renew(self, scope, lease, now_ms, lease_ms)
    }

    pub fn claim_processing_durable_with_clock(
        &self,
        scope: &KnowledgeScope,
        worker_id: &str,
        lease_ms: u64,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<Option<ProcessingLease>> {
        leases::claim_with_clock(self, scope, worker_id, lease_ms, clock)
    }

    pub fn renew_processing_durable_with_clock(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        lease_ms: u64,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<ProcessingLease> {
        leases::renew_with_clock(self, scope, lease, lease_ms, clock)
    }

    pub fn begin_processing_audit_durable(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        invocation: ProcessingInvocation,
        now_ms: i64,
    ) -> KnowledgeResult<()> {
        self.begin_processing_audit_durable_with_clock(scope, lease, invocation, &|| Ok(now_ms))
    }

    pub fn begin_processing_audit_durable_with_clock(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        invocation: ProcessingInvocation,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<()> {
        if invocation.input.source != lease.source
            || invocation.tool_name != SUBMIT_PROJECTION_TOOL
            || invocation.contract_version != 1
            || invocation.agent_id.trim().is_empty()
            || invocation.provider_id.trim().is_empty()
            || invocation.model_id.trim().is_empty()
        {
            return Err(KnowledgeError::InvalidInput);
        }
        transact_timed(self, clock, |tx, now_ms| {
            let expiry = active_lease(tx, scope, lease, now_ms)?;
            let payload: String = tx
                .query_row(
                    "SELECT payload FROM knowledge_processing_changes WHERE sequence=?1",
                    [lease.source.change_sequence],
                    |r| r.get(0),
                )
                .map_err(storage)?;
            let memory: Memory = serde_json::from_str(&payload).map_err(storage)?;
            if memory.title != invocation.input.title || memory.content != invocation.input.content
            {
                return Err(KnowledgeError::Conflict);
            }
            let changed = tx.execute("INSERT INTO knowledge_processing_audits(change_sequence,attempt,tenant_id,project_id,memory_id,revision,worker_id,lease_token,invocation_json,started_at_ms)
                VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10) ON CONFLICT DO NOTHING",
                params![lease.source.change_sequence,lease.attempt,scope.tenant_id,scope.project_id,lease.source.memory_id,lease.source.revision,lease.worker_id,lease.token,serde_json::to_string(&invocation).map_err(storage)?,now_ms]).map_err(storage)?;
            if changed != 1 {
                return Err(KnowledgeError::Conflict);
            }
            Ok(((), Some(expiry)))
        })
    }

    /// A rejected/expired attempt may terminate its own audit, but only an
    /// active matching lease may publish or change the current processing job.
    pub fn finish_processing_audit_durable(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        outcome: ProcessingAuditOutcome,
        now_ms: i64,
        latency_ms: u64,
    ) -> KnowledgeResult<()> {
        self.finish_processing_audit_durable_with_clock(scope, lease, outcome, latency_ms, &|| {
            Ok(now_ms)
        })
    }

    pub fn finish_processing_audit_durable_with_clock(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        outcome: ProcessingAuditOutcome,
        latency_ms: u64,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<()> {
        validate_source(scope, &lease.source)?;
        let latency = i64::try_from(latency_ms).map_err(|_| KnowledgeError::InvalidInput)?;
        validate_outcome(&outcome, &lease.source)?;
        transact_timed(self, clock, |tx, now_ms| {
            let mut expiry = None;
            let started: i64 = tx.query_row("SELECT started_at_ms FROM knowledge_processing_audits
                WHERE change_sequence=?1 AND attempt=?2 AND tenant_id=?3 AND project_id=?4
                AND worker_id=?5 AND lease_token=?6 AND memory_id=?7 AND revision=?8 AND outcome_json IS NULL",
                params![lease.source.change_sequence,lease.attempt,scope.tenant_id,scope.project_id,lease.worker_id,lease.token,lease.source.memory_id,lease.source.revision],|r|r.get(0)).optional().map_err(storage)?.ok_or(KnowledgeError::Conflict)?;
            if now_ms < started {
                return Err(KnowledgeError::InvalidInput);
            }
            match &outcome {
                ProcessingAuditOutcome::Applied { submission } => {
                    expiry = Some(active_lease(tx, scope, lease, now_ms)?);
                    projection::publish(tx, scope, lease, &submission.projection())?;
                }
                ProcessingAuditOutcome::Failed { code, .. } => {
                    if match active_lease(tx, scope, lease, now_ms) {
                        Ok(_) => true,
                        Err(KnowledgeError::Conflict) => false,
                        Err(error) => return Err(error),
                    } {
                        let failure = match code {
                            ProcessingAuditFailure::ProviderUnavailable => {
                                ProcessingFailure::ProviderUnavailable
                            }
                            ProcessingAuditFailure::InvalidExtraction => {
                                ProcessingFailure::InvalidExtraction
                            }
                            ProcessingAuditFailure::Cancelled => ProcessingFailure::Cancelled,
                            _ => ProcessingFailure::ProcessingFailed,
                        };
                        tx.execute("UPDATE knowledge_processing_jobs SET state='failed',worker_id=NULL,token=NULL,expires_at_ms=NULL,failure_json=?1 WHERE change_sequence=?2",
                            params![serde_json::to_string(&failure).map_err(storage)?,lease.source.change_sequence]).map_err(storage)?;
                    }
                }
            }
            tx.execute("UPDATE knowledge_processing_audits SET outcome_json=?1,finished_at_ms=?2,latency_ms=?3 WHERE change_sequence=?4 AND attempt=?5",
                params![serde_json::to_string(&outcome).map_err(storage)?,now_ms,latency,lease.source.change_sequence,lease.attempt]).map_err(storage)?;
            Ok(((), expiry))
        })
    }

    pub fn processing_audit_durable(
        &self,
        scope: &KnowledgeScope,
        source: &ProcessingSource,
        attempt: u32,
    ) -> KnowledgeResult<Option<ProcessingAuditRecord>> {
        validate_source(scope, source)?;
        let conn = self.conn.lock().map_err(storage)?;
        let stored = conn.query_row("SELECT invocation_json,started_at_ms,finished_at_ms,latency_ms,outcome_json FROM knowledge_processing_audits WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND revision=?4 AND change_sequence=?5 AND attempt=?6",
            params![scope.tenant_id,scope.project_id,source.memory_id,source.revision,source.change_sequence,attempt],|r|Ok((r.get::<_,String>(0)?,r.get::<_,i64>(1)?,r.get::<_,Option<i64>>(2)?,r.get::<_,Option<u64>>(3)?,r.get::<_,Option<String>>(4)?))).optional().map_err(storage)?;
        let Some((invocation, start, finish, latency, outcome)) = stored else {
            return Ok(None);
        };
        Ok(Some(ProcessingAuditRecord {
            invocation: serde_json::from_str(&invocation).map_err(storage)?,
            attempt,
            started_at_ms: start,
            finished_at_ms: finish,
            latency_ms: latency,
            outcome: outcome
                .map(|s| serde_json::from_str(&s).map_err(storage))
                .transpose()?,
        }))
    }
}

fn validate_outcome(
    outcome: &ProcessingAuditOutcome,
    source: &ProcessingSource,
) -> KnowledgeResult<()> {
    let valid = match outcome {
        ProcessingAuditOutcome::Applied { submission } => submission.validate(source),
        ProcessingAuditOutcome::Failed {
            response_digest, ..
        } => response_digest.as_ref().is_none_or(|digest| {
            digest.len() == 64 && digest.bytes().all(|byte| byte.is_ascii_hexdigit())
        }),
    };
    if valid {
        Ok(())
    } else {
        Err(KnowledgeError::InvalidInput)
    }
}
