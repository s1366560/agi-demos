use agistack_core::knowledge::community::build::*;
use uuid::Uuid;

use super::{builds::transact, *};

fn deadline(now_ms: i64, lease_ms: u64) -> KnowledgeResult<i64> {
    if now_ms < 0 || lease_ms == 0 {
        return Err(KnowledgeError::InvalidInput);
    }
    now_ms
        .checked_add(i64::try_from(lease_ms).map_err(|_| KnowledgeError::InvalidInput)?)
        .ok_or(KnowledgeError::InvalidInput)
}

pub(super) fn active(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    lease: &CommunityJobLease,
    now_ms: i64,
) -> KnowledgeResult<i64> {
    validate(scope, &lease.build_id)?;
    validate(scope, &lease.candidate_id)?;
    if lease.tenant_id != scope.tenant_id
        || lease.project_id != scope.project_id
        || lease.worker_id.trim().is_empty()
        || lease.token.is_empty()
        || lease.attempt == 0
    {
        return Err(KnowledgeError::InvalidInput);
    }
    tx.query_row(
        "SELECT j.expires_at_ms FROM knowledge_community_jobs j
         JOIN knowledge_community_builds b ON b.tenant_id=j.tenant_id AND b.project_id=j.project_id AND b.build_id=j.build_id
         WHERE j.tenant_id=?1 AND j.project_id=?2 AND j.build_id=?3 AND j.candidate_id=?4
           AND j.state='leased' AND j.worker_id=?5 AND j.token=?6 AND j.attempt=?7 AND j.expires_at_ms>?8
           AND b.graph_digest=?9",
        params![scope.tenant_id,scope.project_id,lease.build_id,lease.candidate_id,
            lease.worker_id,lease.token,lease.attempt,now_ms,lease.graph_digest],
        |row| row.get(0),
    ).optional().map_err(storage)?.ok_or(KnowledgeError::Conflict)
}

impl SqliteKnowledgeRepository {
    /// Claims pending work or reclaims an expired lease of this exact build.
    /// This grants ownership of frozen input, not permission to publish output.
    pub fn claim_community_job_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        worker_id: &str,
        lease_ms: u64,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<Option<CommunityJobLease>> {
        validate(scope, build_id)?;
        validate(scope, worker_id)?;
        transact(self, clock, |tx, now_ms| {
            let expires_at_ms = deadline(now_ms, lease_ms)?;
            let row: Option<(String,u32,String)> = tx.query_row(
                "SELECT j.candidate_id,j.attempt,b.graph_digest FROM knowledge_community_jobs j
                 JOIN knowledge_community_builds b ON b.tenant_id=j.tenant_id AND b.project_id=j.project_id AND b.build_id=j.build_id
                 JOIN knowledge_community_candidates c ON c.tenant_id=j.tenant_id AND c.project_id=j.project_id
                   AND c.build_id=j.build_id AND c.candidate_id=j.candidate_id
                 WHERE j.tenant_id=?1 AND j.project_id=?2 AND j.build_id=?3
                   AND (j.state='pending' OR (j.state='leased' AND j.expires_at_ms<=?4))
                 ORDER BY c.position LIMIT 1",
                params![scope.tenant_id,scope.project_id,build_id,now_ms],
                |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?)),
            ).optional().map_err(storage)?;
            let Some((candidate_id, attempt, graph_digest)) = row else {
                return Ok((None, None));
            };
            let lease = CommunityJobLease {
                tenant_id: scope.tenant_id.clone(),
                project_id: scope.project_id.clone(),
                build_id: build_id.into(),
                candidate_id,
                graph_digest,
                worker_id: worker_id.into(),
                token: Uuid::new_v4().to_string(),
                attempt: attempt.checked_add(1).ok_or(KnowledgeError::Conflict)?,
                expires_at_ms,
            };
            tx.execute(
                "UPDATE knowledge_community_jobs SET state='leased',attempt=?5,worker_id=?6,token=?7,expires_at_ms=?8
                 WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4",
                params![scope.tenant_id,scope.project_id,build_id,lease.candidate_id,lease.attempt,
                    worker_id,lease.token,expires_at_ms],
            ).map_err(storage)?;
            Ok((Some(lease), Some(expires_at_ms)))
        })
    }

    pub fn renew_community_job_durable(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        lease_ms: u64,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<CommunityJobLease> {
        transact(self, clock, |tx, now_ms| {
            let original_expiry = active(tx, scope, lease, now_ms)?;
            let expires_at_ms = deadline(now_ms, lease_ms)?.max(original_expiry);
            tx.execute(
                "UPDATE knowledge_community_jobs SET expires_at_ms=?5
                 WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4",
                params![
                    scope.tenant_id,
                    scope.project_id,
                    lease.build_id,
                    lease.candidate_id,
                    expires_at_ms
                ],
            )
            .map_err(storage)?;
            Ok((
                CommunityJobLease {
                    expires_at_ms,
                    ..lease.clone()
                },
                Some(original_expiry),
            ))
        })
    }

    pub fn fail_community_job_durable(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        failure: CommunityJobFailure,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<()> {
        transact(self, clock, |tx, now_ms| {
            let expiry = active(tx, scope, lease, now_ms)?;
            tx.execute(
                "UPDATE knowledge_community_jobs SET state='failed',worker_id=NULL,token=NULL,expires_at_ms=NULL,failure_json=?5
                 WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4",
                params![scope.tenant_id,scope.project_id,lease.build_id,lease.candidate_id,
                    serde_json::to_string(&failure).map_err(storage)?],
            ).map_err(storage)?;
            Ok(((), Some(expiry)))
        })
    }

    pub fn retry_community_job_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        candidate_id: &str,
        expected_attempt: u32,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<()> {
        validate(scope, build_id)?;
        validate(scope, candidate_id)?;
        transact(self, clock, |tx, _| {
            let changed = tx.execute(
                "UPDATE knowledge_community_jobs SET state='pending',failure_json=NULL
                 WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4 AND state='failed' AND attempt=?5",
                params![scope.tenant_id,scope.project_id,build_id,candidate_id,expected_attempt],
            ).map_err(storage)?;
            if changed != 1 {
                return Err(KnowledgeError::Conflict);
            }
            Ok(((), None))
        })
    }

    pub fn community_job_status_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        candidate_id: &str,
    ) -> KnowledgeResult<Option<CommunityJobStatus>> {
        validate(scope, build_id)?;
        validate(scope, candidate_id)?;
        let conn = self.conn.lock().map_err(storage)?;
        let row: Option<(String, u32, Option<String>)> = conn
            .query_row(
                "SELECT state,attempt,failure_json FROM knowledge_community_jobs
             WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4",
                params![scope.tenant_id, scope.project_id, build_id, candidate_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .optional()
            .map_err(storage)?;
        row.map(|(state, attempt, failure)| {
            Ok(CommunityJobStatus {
                build_id: build_id.into(),
                candidate_id: candidate_id.into(),
                attempt,
                state: serde_json::from_value(serde_json::Value::String(state)).map_err(storage)?,
                failure: failure
                    .map(|json| serde_json::from_str(&json))
                    .transpose()
                    .map_err(storage)?,
            })
        })
        .transpose()
    }
}
