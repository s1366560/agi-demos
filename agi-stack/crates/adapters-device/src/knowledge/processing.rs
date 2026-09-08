//! Processing receipts and current derived output, isolated from portable state.

use agistack_core::knowledge::processing::*;
use async_trait::async_trait;
use rusqlite::{params, OptionalExtension, Transaction, TransactionBehavior};

use super::{
    storage, validate, KnowledgeError, KnowledgeResult, KnowledgeScope, SqliteKnowledgeRepository,
};

pub(super) mod audit;
mod diagnostics;
mod leases;
mod projection;
mod schema;
pub(super) use schema::migrate;

fn transact<T>(
    repo: &SqliteKnowledgeRepository,
    action: impl FnOnce(&Transaction<'_>) -> KnowledgeResult<T>,
) -> KnowledgeResult<T> {
    let mut conn = repo.conn.lock().map_err(storage)?;
    let tx = conn
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let result = action(&tx)?;
    tx.commit().map_err(storage)?;
    Ok(result)
}

/// The clock/admission callback runs only after both repository and SQLite
/// write locks are held, and again immediately before commit. No caller may
/// reacquire an outer auth lock from this callback.
fn transact_timed<T>(
    repo: &SqliteKnowledgeRepository,
    clock: &dyn Fn() -> KnowledgeResult<i64>,
    action: impl FnOnce(&Transaction<'_>, i64) -> KnowledgeResult<(T, Option<i64>)>,
) -> KnowledgeResult<T> {
    transact(repo, |tx| {
        let started = clock()?;
        let (result, lease_deadline) = action(tx, started)?;
        let finished = clock()?;
        if finished < started || lease_deadline.is_some_and(|expiry| finished >= expiry) {
            return Err(KnowledgeError::Conflict);
        }
        Ok(result)
    })
}

fn validate_source(scope: &KnowledgeScope, source: &ProcessingSource) -> KnowledgeResult<()> {
    validate(scope, &source.memory_id)?;
    if source.tenant_id != scope.tenant_id
        || source.project_id != scope.project_id
        || source.revision == 0
        || source.change_sequence == 0
        || i64::try_from(source.change_sequence).is_err()
    {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

fn current_source(tx: &Transaction<'_>, source: &ProcessingSource) -> KnowledgeResult<bool> {
    tx.query_row(
        "SELECT EXISTS(SELECT 1 FROM knowledge_memories m
         JOIN knowledge_processing_changes c ON c.tenant_id=m.tenant_id AND c.project_id=m.project_id
           AND c.memory_id=m.id AND c.revision=m.revision AND c.payload=m.payload
         WHERE m.tenant_id=?1 AND m.project_id=?2 AND m.id=?3 AND m.revision=?4 AND m.deleted=0
           AND c.sequence=?5 AND c.operation='upsert')",
        params![source.tenant_id,source.project_id,source.memory_id,source.revision,source.change_sequence],
        |row| row.get(0),
    ).map_err(storage)
}

fn active_lease(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    lease: &ProcessingLease,
    now_ms: i64,
) -> KnowledgeResult<i64> {
    validate_source(scope, &lease.source)?;
    if now_ms < 0
        || lease.worker_id.trim().is_empty()
        || lease.token.is_empty()
        || lease.attempt == 0
    {
        return Err(KnowledgeError::InvalidInput);
    }
    let source = &lease.source;
    let expiry = tx.query_row(
        "SELECT expires_at_ms FROM knowledge_processing_jobs
         WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND revision=?4 AND change_sequence=?5
           AND state='leased' AND worker_id=?6 AND token=?7 AND attempt=?8 AND expires_at_ms>?9",
        params![source.tenant_id,source.project_id,source.memory_id,source.revision,source.change_sequence,lease.worker_id,lease.token,lease.attempt,now_ms],
        |row| row.get::<_,i64>(0),
    ).optional().map_err(storage)?.ok_or(KnowledgeError::Conflict)?;
    if !current_source(tx, source)? {
        return Err(KnowledgeError::Conflict);
    }
    Ok(expiry)
}

fn deadline(now_ms: i64, lease_ms: u64) -> KnowledgeResult<i64> {
    if now_ms < 0 || lease_ms == 0 {
        return Err(KnowledgeError::InvalidInput);
    }
    now_ms
        .checked_add(i64::try_from(lease_ms).map_err(|_| KnowledgeError::InvalidInput)?)
        .ok_or(KnowledgeError::InvalidInput)
}

#[async_trait]
impl ProcessingRepository for SqliteKnowledgeRepository {
    async fn claim(
        &self,
        scope: &KnowledgeScope,
        worker_id: &str,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<Option<ProcessingLease>> {
        leases::claim(self, scope, worker_id, now_ms, lease_ms)
    }
    async fn renew(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<ProcessingLease> {
        leases::renew(self, scope, lease, now_ms, lease_ms)
    }
    async fn complete(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        output: ProcessingProjection,
        now_ms: i64,
    ) -> KnowledgeResult<()> {
        projection::complete(self, scope, lease, output, now_ms)
    }
    async fn fail(
        &self,
        scope: &KnowledgeScope,
        lease: &ProcessingLease,
        failure: ProcessingFailure,
        now_ms: i64,
    ) -> KnowledgeResult<()> {
        leases::fail(self, scope, lease, failure, now_ms)
    }
    async fn retry(
        &self,
        scope: &KnowledgeScope,
        source: &ProcessingSource,
        expected_attempt: u32,
    ) -> KnowledgeResult<()> {
        leases::retry(self, scope, source, expected_attempt)
    }
    async fn processing_status(
        &self,
        scope: &KnowledgeScope,
        source: &ProcessingSource,
    ) -> KnowledgeResult<Option<ProcessingStatus>> {
        projection::status(self, scope, source)
    }
    async fn projection(
        &self,
        scope: &KnowledgeScope,
        memory_id: &str,
    ) -> KnowledgeResult<Option<DerivedProjection>> {
        projection::read(self, scope, memory_id)
    }
}

#[cfg(test)]
#[path = "processing/clock_tests.rs"]
mod clock_tests;
