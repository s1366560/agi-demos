use rusqlite::{params, TransactionBehavior};

use super::{
    automation_dispatcher::{AutomationLedgerError, AutomationOperationClaim},
    automation_ledger_support::storage,
    session_store::DesktopSessionStore,
};

pub(super) fn reserve_authority(
    store: &DesktopSessionStore,
    claim: &AutomationOperationClaim,
    conversation_id: &str,
    request_id: &str,
    created_at: &str,
) -> Result<(), AutomationLedgerError> {
    if conversation_id.trim().is_empty()
        || request_id.trim().is_empty()
        || created_at.trim().is_empty()
    {
        return Err(invalid_authority(
            "automation HITL authority requires conversation, request, and creation time",
        ));
    }
    let mut connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let valid_claim = transaction
        .query_row(
            "SELECT COUNT(*)
             FROM desktop_automation_runs AS run
             INNER JOIN desktop_automation_operations AS operation ON operation.run_id = run.id
             WHERE run.id = ?1 AND operation.id = ?2
               AND run.runtime_execution_id = ?3
               AND run.tenant_id = ?4 AND run.project_id = ?5
               AND run.status = 'running' AND operation.status = 'running'
               AND operation.lease_owner = ?6 AND operation.lease_token = ?7
               AND operation.fence_token = ?8",
            params![
                claim.run_id,
                claim.operation_id,
                claim.runtime_execution_id,
                claim.tenant_id,
                claim.project_id,
                claim.worker_id,
                claim.lease_token,
                claim.fence_token,
            ],
            |row| row.get::<_, i64>(0),
        )
        .map_err(storage)?;
    if valid_claim != 1 {
        return Err(AutomationLedgerError::LeaseLost);
    }
    let scoped_conversation = transaction
        .execute(
            "UPDATE desktop_automation_runs
             SET conversation_id = ?1
             WHERE id = ?2 AND status = 'running'
               AND (conversation_id IS NULL OR conversation_id = ?1)",
            params![conversation_id, claim.run_id],
        )
        .map_err(storage)?;
    if scoped_conversation != 1 {
        return Err(invalid_authority(
            "automation HITL conversation conflicts with the claimed run",
        ));
    }
    let mut statement = transaction
        .prepare(
            "SELECT request_id, run_id, operation_id, runtime_execution_id, tenant_id,
                    project_id, conversation_id, deadline_at_ms
             FROM desktop_automation_hitl_authorities
             WHERE request_id = ?1 OR run_id = ?2 OR operation_id = ?3
                OR runtime_execution_id = ?4
             LIMIT 2",
        )
        .map_err(storage)?;
    let rows = statement
        .query_map(
            params![
                request_id,
                claim.run_id,
                claim.operation_id,
                claim.runtime_execution_id,
            ],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, i64>(7)?,
                ))
            },
        )
        .map_err(storage)?;
    let mut existing = Vec::new();
    for row in rows {
        existing.push(row.map_err(storage)?);
    }
    drop(statement);
    if let Some(record) = existing.pop() {
        if !existing.is_empty()
            || record.0 != request_id
            || record.1 != claim.run_id
            || record.2 != claim.operation_id
            || record.3 != claim.runtime_execution_id
            || record.4 != claim.tenant_id
            || record.5 != claim.project_id
            || record.6 != conversation_id
            || record.7 != claim.deadline_at.timestamp_millis()
        {
            return Err(AutomationLedgerError::IdempotencyConflict);
        }
        transaction.commit().map_err(storage)?;
        return Ok(());
    }
    let preexisting_request = transaction
        .query_row(
            "SELECT COUNT(*) FROM desktop_hitl_requests WHERE id = ?1",
            [request_id],
            |row| row.get::<_, i64>(0),
        )
        .map_err(storage)?;
    if preexisting_request != 0 {
        return Err(AutomationLedgerError::IdempotencyConflict);
    }
    transaction
        .execute(
            "INSERT INTO desktop_automation_hitl_authorities (
               request_id, run_id, operation_id, runtime_execution_id, tenant_id,
               project_id, conversation_id, deadline_at_ms, created_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                request_id,
                claim.run_id,
                claim.operation_id,
                claim.runtime_execution_id,
                claim.tenant_id,
                claim.project_id,
                conversation_id,
                claim.deadline_at.timestamp_millis(),
                created_at,
            ],
        )
        .map_err(storage)?;
    transaction.commit().map_err(storage)
}

fn invalid_authority(message: impl Into<String>) -> AutomationLedgerError {
    AutomationLedgerError::InvalidRecord(message.into())
}
