use agistack_core::knowledge::community::build::*;
use rusqlite::TransactionBehavior;
use uuid::Uuid;

use super::*;

pub(super) mod read;
use read::read_build;

/// Same lock/clock discipline as the existing processing boundary. No callback
/// may reacquire an outer repository lock or perform provider work.
pub(super) fn transact<T>(
    repo: &SqliteKnowledgeRepository,
    clock: &dyn Fn() -> KnowledgeResult<i64>,
    action: impl FnOnce(&Transaction<'_>, i64) -> KnowledgeResult<(T, Option<i64>)>,
) -> KnowledgeResult<T> {
    let mut conn = repo.conn.lock().map_err(storage)?;
    let tx = conn
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let started = clock()?;
    if started < 0 {
        return Err(KnowledgeError::InvalidInput);
    }
    let (result, expiry) = action(&tx, started)?;
    let finished = clock()?;
    if finished < started || expiry.is_some_and(|expires| finished >= expires) {
        return Err(KnowledgeError::Conflict);
    }
    tx.commit().map_err(storage)?;
    Ok(result)
}

fn replay(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    request: &CommunityBuildRequest,
) -> KnowledgeResult<Option<CommunityBuildReceipt>> {
    let row: Option<(String, String)> = tx
        .query_row(
            "SELECT request_json,receipt_json FROM knowledge_community_builds
         WHERE tenant_id=?1 AND project_id=?2 AND actor_id=?3 AND idempotency_key=?4",
            params![
                scope.tenant_id,
                scope.project_id,
                request.actor_id,
                request.idempotency_key
            ],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()
        .map_err(storage)?;
    let Some((original, receipt)) = row else {
        return Ok(None);
    };
    let original: CommunityBuildRequest = serde_json::from_str(&original).map_err(storage)?;
    if original != *request {
        return Err(KnowledgeError::IdempotencyConflict);
    }
    let receipt: CommunityBuildReceipt = serde_json::from_str(&receipt).map_err(storage)?;
    if receipt.tenant_id != scope.tenant_id || receipt.project_id != scope.project_id {
        return Err(KnowledgeError::Conflict);
    }
    Ok(Some(receipt))
}

fn persist(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    request: &CommunityBuildRequest,
    snapshot: &CommunitySnapshot,
    candidates: &[CommunityCandidate],
    now_ms: i64,
) -> KnowledgeResult<CommunityBuildReceipt> {
    if let Some(receipt) = replay(tx, scope, request)? {
        return Ok(receipt);
    }
    // Re-capture under the write lock, fencing edits/deletes/metadata changes
    // and late extraction completion that occurred during lock-free partitioning.
    let current = capture(tx, scope, request.min_community_size)?;
    if fingerprint(&current)? != snapshot.graph_digest {
        return Err(KnowledgeError::Conflict);
    }
    let receipt = CommunityBuildReceipt {
        tenant_id: scope.tenant_id.clone(),
        project_id: scope.project_id.clone(),
        build_id: Uuid::new_v4().to_string(),
        graph_digest: snapshot.graph_digest.clone(),
        candidate_count: u32::try_from(candidates.len())
            .map_err(|_| KnowledgeError::InvalidInput)?,
        state: if candidates.is_empty() {
            CommunityBuildState::CompletedEmpty
        } else {
            CommunityBuildState::Pending
        },
        created_at_ms: now_ms,
    };
    tx.execute(
        "INSERT INTO knowledge_community_builds
         (tenant_id,project_id,build_id,actor_id,idempotency_key,request_json,graph_digest,snapshot_json,receipt_json)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)",
        params![scope.tenant_id,scope.project_id,receipt.build_id,request.actor_id,request.idempotency_key,
            serde_json::to_string(request).map_err(storage)?,receipt.graph_digest,
            serde_json::to_string(snapshot).map_err(storage)?,serde_json::to_string(&receipt).map_err(storage)?],
    ).map_err(storage)?;
    for (position, candidate) in candidates.iter().enumerate() {
        let id = &candidate.membership_digest;
        tx.execute(
            "INSERT INTO knowledge_community_candidates
             (tenant_id,project_id,build_id,candidate_id,position,member_count) VALUES(?1,?2,?3,?4,?5,?6)",
            params![scope.tenant_id,scope.project_id,receipt.build_id,id,position,candidate.members.len()],
        ).map_err(storage)?;
        for (position, member) in candidate.members.iter().enumerate() {
            tx.execute(
                "INSERT INTO knowledge_community_members
                 (tenant_id,project_id,build_id,candidate_id,position,reference_json) VALUES(?1,?2,?3,?4,?5,?6)",
                params![scope.tenant_id,scope.project_id,receipt.build_id,id,position,
                    serde_json::to_string(member).map_err(storage)?],
            ).map_err(storage)?;
        }
        tx.execute(
            "INSERT INTO knowledge_community_jobs
             (tenant_id,project_id,build_id,candidate_id,state) VALUES(?1,?2,?3,?4,'pending')",
            params![scope.tenant_id, scope.project_id, receipt.build_id, id],
        )
        .map_err(storage)?;
    }
    Ok(receipt)
}

impl SqliteKnowledgeRepository {
    /// Captures a fresh snapshot and partitions outside locks. All fixed input,
    /// members and jobs become visible together after a matching-snapshot CAS.
    /// Replayed keys return the original receipt even if live sources changed.
    pub fn create_community_build_durable(
        &self,
        scope: &KnowledgeScope,
        request: &CommunityBuildRequest,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<CommunityBuildReceipt> {
        validate(scope, &request.actor_id)?;
        validate(scope, &request.idempotency_key)?;
        if request.min_community_size < 2 {
            return Err(KnowledgeError::InvalidInput);
        }
        if let Some(receipt) =
            transact(self, clock, |tx, _| Ok((replay(tx, scope, request)?, None)))?
        {
            return Ok(receipt);
        }
        let snapshot = self.community_snapshot_durable(scope, request.min_community_size)?;
        let candidates = Self::community_candidates(&snapshot)?;
        transact(self, clock, |tx, now_ms| {
            Ok((
                persist(tx, scope, request, &snapshot, &candidates, now_ms)?,
                None,
            ))
        })
    }

    pub fn community_build_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
    ) -> KnowledgeResult<Option<CommunityBuildInput>> {
        validate(scope, build_id)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        let input = read_build(&tx, scope, build_id)?;
        tx.commit().map_err(storage)?;
        Ok(input)
    }
}

#[cfg(test)]
mod tests;
