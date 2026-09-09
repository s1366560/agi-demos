//! Content-free durable reads behind the sanitized diagnostics export. Every
//! field is a counter, cursor, receipt position or timestamp: conflict
//! payloads, memory content and provider invocations are never selected.
use rusqlite::{Transaction, TransactionBehavior};

use super::*;

/// Last durable success per stage. Index completions are only timestamped from
/// knowledge schema version 19; older completions report `None` rather than a
/// fabricated time.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DiagnosticsSuccessTimestamps {
    pub processing_ms: Option<i64>,
    pub index_ms: Option<i64>,
}

/// Content-free synchronization state for triage: pending outbox depth, open
/// conflict counts and cursor/receipt positions.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SyncDiagnostics {
    pub linked: bool,
    pub pending_changes: u64,
    pub pending_graph_changes: u64,
    pub pull_conflicts: u64,
    pub push_conflicts: u64,
    pub graph_pull_conflicts: u64,
    pub graph_push_conflicts: u64,
    pub pull_cursor: u64,
    pub graph_pull_cursor: u64,
    pub last_receipt_sequence: Option<u64>,
}

fn timed_read<T>(
    repository: &SqliteKnowledgeRepository,
    clock: &dyn Fn() -> KnowledgeResult<i64>,
    action: impl FnOnce(&Transaction<'_>) -> KnowledgeResult<T>,
) -> KnowledgeResult<T> {
    let mut connection = repository.conn.lock().map_err(storage)?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Deferred)
        .map_err(storage)?;
    let started = clock()?;
    let result = action(&tx)?;
    let finished = clock()?;
    if finished < started {
        return Err(KnowledgeError::Conflict);
    }
    tx.commit().map_err(storage)?;
    Ok(result)
}

fn count(tx: &Transaction<'_>, sql: &str, scope: &KnowledgeScope) -> KnowledgeResult<u64> {
    tx.query_row(sql, params![scope.tenant_id, scope.project_id], |row| {
        row.get(0)
    })
    .map_err(storage)
}

fn cursor(tx: &Transaction<'_>, table: &str, scope: &KnowledgeScope) -> KnowledgeResult<u64> {
    Ok(tx
        .query_row(
            &format!(
                "SELECT cursor FROM {table} WHERE tenant_id=?1 AND project_id=?2"
            ),
            params![scope.tenant_id, scope.project_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?
        .unwrap_or(0))
}

impl SqliteKnowledgeRepository {
    /// Last applied extraction audit and, when a build is selected, the last
    /// recorded index completion for that exact build.
    pub fn diagnostics_success_timestamps_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: Option<&str>,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<DiagnosticsSuccessTimestamps> {
        validate(scope, "diagnostics-success")?;
        timed_read(self, clock, |tx| {
            let processing_ms: Option<i64> = tx
                .query_row(
                    "SELECT MAX(finished_at_ms) FROM knowledge_processing_audits
                     WHERE tenant_id=?1 AND project_id=?2
                       AND outcome_json LIKE '{\"status\":\"applied\"%'",
                    params![scope.tenant_id, scope.project_id],
                    |row| row.get(0),
                )
                .map_err(storage)?;
            let index_ms: Option<i64> = match build_id {
                Some(build_id) if !build_id.trim().is_empty() => tx
                    .query_row(
                        "SELECT MAX(completed_at_ms) FROM knowledge_index_jobs
                         WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3
                           AND completed_at_ms IS NOT NULL",
                        params![scope.tenant_id, scope.project_id, build_id],
                        |row| row.get(0),
                    )
                    .map_err(storage)?,
                _ => None,
            };
            Ok(DiagnosticsSuccessTimestamps {
                processing_ms,
                index_ms,
            })
        })
    }

    /// Pending outbox depth, open conflict counts and cursor/receipt positions.
    pub fn sync_diagnostics_durable(
        &self,
        scope: &KnowledgeScope,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<SyncDiagnostics> {
        validate(scope, "sync-diagnostics")?;
        timed_read(self, clock, |tx| {
            let linked: bool = tx
                .query_row(
                    "SELECT EXISTS(SELECT 1 FROM knowledge_sync_links
                     WHERE tenant_id=?1 AND project_id=?2)",
                    params![scope.tenant_id, scope.project_id],
                    |row| row.get(0),
                )
                .map_err(storage)?;
            let last_receipt_sequence: Option<u64> = tx
                .query_row(
                    "SELECT MAX(p.sequence) FROM knowledge_sync_pushes p
                     JOIN knowledge_processing_changes c ON c.sequence=p.sequence
                     WHERE c.tenant_id=?1 AND c.project_id=?2 AND p.receipt_json IS NOT NULL",
                    params![scope.tenant_id, scope.project_id],
                    |row| row.get(0),
                )
                .map_err(storage)?;
            Ok(SyncDiagnostics {
                linked,
                pending_changes: count(
                    tx,
                    "SELECT count(*) FROM knowledge_pending_outbox
                     WHERE tenant_id=?1 AND project_id=?2",
                    scope,
                )?,
                pending_graph_changes: graph_sync::pending_count(tx, scope)?,
                pull_conflicts: count(
                    tx,
                    "SELECT count(*) FROM knowledge_active_pull_conflicts
                     WHERE tenant_id=?1 AND project_id=?2",
                    scope,
                )?,
                push_conflicts: count(
                    tx,
                    "SELECT count(*) FROM knowledge_unsettled_pushes
                     WHERE tenant_id=?1 AND project_id=?2 AND conflict_json IS NOT NULL",
                    scope,
                )?,
                graph_pull_conflicts: count(
                    tx,
                    "SELECT count(*) FROM knowledge_active_graph_pull_conflicts
                     WHERE tenant_id=?1 AND project_id=?2",
                    scope,
                )?,
                graph_push_conflicts: count(
                    tx,
                    "SELECT count(*) FROM knowledge_unsettled_graph_pushes
                     WHERE tenant_id=?1 AND project_id=?2 AND conflict_json IS NOT NULL",
                    scope,
                )?,
                pull_cursor: cursor(tx, "knowledge_sync_pull_cursors", scope)?,
                graph_pull_cursor: cursor(tx, "knowledge_sync_graph_pull_cursors", scope)?,
                last_receipt_sequence,
            })
        })
    }
}
