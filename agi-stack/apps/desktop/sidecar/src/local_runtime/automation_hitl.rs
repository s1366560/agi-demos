use chrono::{DateTime, Utc};
use rusqlite::{params, Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde_json::{json, Value};

pub(super) use super::automation_hitl_reservation::reserve_authority;
use super::{
    authority_store::{DesktopHitlRequest, DesktopHitlStatus},
    automation_dispatcher::{AutomationClock, AutomationLedgerError, AutomationOperationClaim},
    automation_executor,
    automation_ledger_support::{invalid_record, storage},
    session_store::DesktopSessionStore,
    LocalRuntimeState,
};

pub(super) const AUTOMATION_HITL_EXPIRED_REASON: &str = "local_automation_hitl_expired";

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct AutomationHitlAuthority {
    pub(super) run_id: String,
    pub(super) operation_id: String,
    pub(super) runtime_execution_id: String,
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) conversation_id: String,
    pub(super) request_id: String,
    pub(super) deadline_at: DateTime<Utc>,
    pub(super) response_answer: Option<String>,
    run_status: String,
    operation_status: String,
    request_status: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum AutomationHitlResumeOutcome {
    Requeued,
    AlreadyResumed,
    Expired,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(super) struct AutomationHitlReconcileSummary {
    pub(super) expired: usize,
    pub(super) answered: Vec<AutomationHitlAuthority>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) enum AutomationHitlResponse {
    NotAutomation,
    Queued {
        authority: Box<AutomationHitlAuthority>,
        duplicate: bool,
    },
    Expired {
        run_id: String,
    },
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum AutomationHitlResponseError {
    Checkpoint(&'static str),
    Ledger(AutomationLedgerError),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum AutomationHitlClaimOutcome {
    Claimed,
    DuplicatePending,
    AlreadyResumed,
    Expired,
}

pub(super) async fn respond_to_request(
    state: &LocalRuntimeState,
    request_id: &str,
    answer: &str,
    response_data: &Value,
    idempotency_key: Option<&str>,
    received_at: DateTime<Utc>,
) -> Result<AutomationHitlResponse, AutomationHitlResponseError> {
    let Some((authority, claim_outcome)) = claim_response(
        &state.session_store,
        request_id,
        answer,
        response_data,
        idempotency_key,
        received_at,
    )
    .map_err(AutomationHitlResponseError::Ledger)?
    else {
        return Ok(AutomationHitlResponse::NotAutomation);
    };
    match claim_outcome {
        AutomationHitlClaimOutcome::Expired => {
            return Ok(AutomationHitlResponse::Expired {
                run_id: authority.run_id,
            });
        }
        AutomationHitlClaimOutcome::AlreadyResumed => {
            return Ok(AutomationHitlResponse::Queued {
                authority: Box::new(authority),
                duplicate: true,
            });
        }
        AutomationHitlClaimOutcome::Claimed | AutomationHitlClaimOutcome::DuplicatePending => {}
    }
    automation_executor::accept_human_response(state, &authority, request_id, answer)
        .await
        .map_err(AutomationHitlResponseError::Checkpoint)?;
    let outcome = resume_answered_wait(&state.session_store, request_id, received_at)
        .map_err(AutomationHitlResponseError::Ledger)?;
    match outcome {
        AutomationHitlResumeOutcome::Requeued => Ok(AutomationHitlResponse::Queued {
            authority: Box::new(authority),
            duplicate: claim_outcome == AutomationHitlClaimOutcome::DuplicatePending,
        }),
        AutomationHitlResumeOutcome::AlreadyResumed => Ok(AutomationHitlResponse::Queued {
            authority: Box::new(authority),
            duplicate: true,
        }),
        AutomationHitlResumeOutcome::Expired => Ok(AutomationHitlResponse::Expired {
            run_id: authority.run_id,
        }),
    }
}

pub(super) fn authority_for_request(
    store: &DesktopSessionStore,
    request_id: &str,
) -> Result<Option<AutomationHitlAuthority>, AutomationLedgerError> {
    let connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    query_authority(&connection, request_id)
}

pub(super) fn validate_waiting_outcome(
    store: &DesktopSessionStore,
    claim: &AutomationOperationClaim,
    conversation_id: &str,
    request_id: &str,
) -> Result<(), AutomationLedgerError> {
    let authority =
        authority_for_request(store, request_id)?.ok_or(AutomationLedgerError::NotFound)?;
    if authority.run_id != claim.run_id
        || authority.operation_id != claim.operation_id
        || authority.runtime_execution_id != claim.runtime_execution_id
        || authority.tenant_id != claim.tenant_id
        || authority.project_id != claim.project_id
        || authority.conversation_id != conversation_id
        || authority.deadline_at != claim.deadline_at
        || authority.run_status != "running"
        || authority.operation_status != "running"
        || authority.request_status != "pending"
    {
        return Err(invalid_authority(
            "automation HITL waiting outcome does not match its reserved authority",
        ));
    }
    Ok(())
}

fn claim_response(
    store: &DesktopSessionStore,
    request_id: &str,
    answer: &str,
    response_data: &Value,
    idempotency_key: Option<&str>,
    received_at: DateTime<Utc>,
) -> Result<Option<(AutomationHitlAuthority, AutomationHitlClaimOutcome)>, AutomationLedgerError> {
    if answer.trim().is_empty() {
        return Err(invalid_authority(
            "automation HITL response answer is required",
        ));
    }
    let mut connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let Some(mut authority) = query_authority(&transaction, request_id)? else {
        return Ok(None);
    };
    if received_at >= authority.deadline_at {
        expire_wait(&transaction, &authority, received_at)?;
        transaction.commit().map_err(storage)?;
        return Ok(Some((authority, AutomationHitlClaimOutcome::Expired)));
    }
    let current = hitl_request(&transaction, request_id)?
        .ok_or_else(|| invalid_authority("automation HITL request is missing"))?;
    let waiting =
        authority.run_status == "waiting_human" && authority.operation_status == "waiting_human";
    let outcome = match current.status {
        DesktopHitlStatus::Pending if waiting => {
            mark_request_responded(
                &transaction,
                current,
                response_data,
                "local_user",
                idempotency_key,
                received_at,
            )?;
            let claimed = transaction
                .execute(
                    "UPDATE desktop_automation_hitl_authorities
                     SET response_answer = ?1, response_claimed_at = ?2
                     WHERE request_id = ?3 AND response_answer IS NULL",
                    params![answer, received_at.to_rfc3339(), request_id],
                )
                .map_err(storage)?;
            if claimed != 1 {
                return Err(AutomationLedgerError::IdempotencyConflict);
            }
            authority.response_answer = Some(answer.to_string());
            authority.request_status = "responded".to_string();
            AutomationHitlClaimOutcome::Claimed
        }
        DesktopHitlStatus::Pending => {
            return Err(invalid_authority(
                "pending automation HITL response requires a waiting run and operation",
            ));
        }
        DesktopHitlStatus::Responded => {
            if current.response_data.as_ref() != Some(response_data)
                || (idempotency_key.is_some()
                    && current.idempotency_key.as_deref() != idempotency_key)
                || authority.response_answer.as_deref() != Some(answer)
            {
                return Err(AutomationLedgerError::IdempotencyConflict);
            }
            match (
                authority.run_status.as_str(),
                authority.operation_status.as_str(),
            ) {
                ("waiting_human", "waiting_human") => AutomationHitlClaimOutcome::DuplicatePending,
                ("queued", "queued") | ("running", "running") => {
                    AutomationHitlClaimOutcome::AlreadyResumed
                }
                ("timeout", "timeout") => AutomationHitlClaimOutcome::Expired,
                (run_status, operation_status)
                    if run_status == operation_status
                        && matches!(run_status, "success" | "failed" | "cancelled") =>
                {
                    AutomationHitlClaimOutcome::AlreadyResumed
                }
                _ => {
                    return Err(invalid_authority(
                        "automation HITL run and operation statuses disagree",
                    ));
                }
            }
        }
    };
    transaction.commit().map_err(storage)?;
    Ok(Some((authority, outcome)))
}

#[cfg(test)]
pub(super) fn claim_answered_for_recovery(
    store: &DesktopSessionStore,
    request_id: &str,
    answer: &str,
    response_data: &Value,
    idempotency_key: Option<&str>,
    received_at: DateTime<Utc>,
) -> Result<(), AutomationLedgerError> {
    let (_, outcome) = claim_response(
        store,
        request_id,
        answer,
        response_data,
        idempotency_key,
        received_at,
    )?
    .ok_or(AutomationLedgerError::NotFound)?;
    if outcome != AutomationHitlClaimOutcome::Claimed
        && outcome != AutomationHitlClaimOutcome::DuplicatePending
    {
        return Err(invalid_authority(
            "automation HITL recovery claim is no longer waiting",
        ));
    }
    Ok(())
}

#[cfg(test)]
pub(super) fn commit_answered_wait(
    store: &DesktopSessionStore,
    request_id: &str,
    answer: &str,
    response_data: &Value,
    idempotency_key: Option<&str>,
    received_at: DateTime<Utc>,
) -> Result<AutomationHitlResumeOutcome, AutomationLedgerError> {
    let (_, claim_outcome) = claim_response(
        store,
        request_id,
        answer,
        response_data,
        idempotency_key,
        received_at,
    )?
    .ok_or(AutomationLedgerError::NotFound)?;
    match claim_outcome {
        AutomationHitlClaimOutcome::Expired => Ok(AutomationHitlResumeOutcome::Expired),
        AutomationHitlClaimOutcome::AlreadyResumed => {
            Ok(AutomationHitlResumeOutcome::AlreadyResumed)
        }
        AutomationHitlClaimOutcome::Claimed | AutomationHitlClaimOutcome::DuplicatePending => {
            resume_answered_wait(store, request_id, received_at)
        }
    }
}

pub(super) fn resume_answered_wait(
    store: &DesktopSessionStore,
    request_id: &str,
    received_at: DateTime<Utc>,
) -> Result<AutomationHitlResumeOutcome, AutomationLedgerError> {
    let mut connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let authority =
        query_authority(&transaction, request_id)?.ok_or(AutomationLedgerError::NotFound)?;
    let outcome = if received_at >= authority.deadline_at {
        expire_wait(&transaction, &authority, received_at)?;
        AutomationHitlResumeOutcome::Expired
    } else {
        if authority.request_status != "responded" || authority.response_answer.is_none() {
            return Err(invalid_authority(
                "automation HITL request has no durable response claim",
            ));
        }
        requeue_answered_wait(&transaction, &authority, received_at)?
    };
    transaction.commit().map_err(storage)?;
    Ok(outcome)
}

pub(super) fn reconcile_waiting_human(
    store: &DesktopSessionStore,
    clock: &dyn AutomationClock,
) -> Result<AutomationHitlReconcileSummary, AutomationLedgerError> {
    let mut connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let request_ids = {
        let mut statement = transaction
            .prepare(
                "SELECT authority.request_id
                 FROM desktop_automation_hitl_authorities AS authority
                 INNER JOIN desktop_automation_runs AS run ON run.id = authority.run_id
                 INNER JOIN desktop_automation_operations AS operation
                   ON operation.id = authority.operation_id AND operation.run_id = run.id
                 WHERE run.status = 'waiting_human'
                   AND operation.status = 'waiting_human'
                 ORDER BY run.accepted_at ASC, run.id ASC",
            )
            .map_err(storage)?;
        let rows = statement
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(storage)?;
        let mut request_ids = Vec::new();
        for row in rows {
            request_ids.push(row.map_err(storage)?);
        }
        request_ids
    };

    let now = clock.now();
    let mut summary = AutomationHitlReconcileSummary::default();
    for request_id in request_ids {
        let authority = query_authority(&transaction, &request_id)?
            .ok_or_else(|| invalid_authority("automation HITL authority disappeared"))?;
        if now >= authority.deadline_at {
            expire_wait(&transaction, &authority, now)?;
            summary.expired += 1;
        } else if authority.request_status == "responded" {
            if authority.response_answer.is_none() {
                return Err(invalid_authority(
                    "answered automation HITL request has no durable response claim",
                ));
            }
            summary.answered.push(authority);
        }
    }
    transaction.commit().map_err(storage)?;
    Ok(summary)
}

fn query_authority(
    connection: &Connection,
    request_id: &str,
) -> Result<Option<AutomationHitlAuthority>, AutomationLedgerError> {
    if request_id.trim().is_empty() {
        return Err(invalid_authority("automation HITL request id is required"));
    }
    let mut statement = connection
        .prepare(
            "SELECT authority.run_id, authority.operation_id,
                    authority.runtime_execution_id, authority.tenant_id,
                    authority.project_id, authority.conversation_id,
                    authority.deadline_at_ms, authority.response_answer,
                    run.status, operation.status, hitl.status,
                    CASE
                      WHEN run.id IS NOT NULL
                       AND operation.id IS NOT NULL
                       AND hitl.id IS NOT NULL
                       AND run.runtime_execution_id = authority.runtime_execution_id
                       AND run.tenant_id = authority.tenant_id
                       AND run.project_id = authority.project_id
                       AND run.conversation_id = authority.conversation_id
                       AND run.deadline_at_ms = authority.deadline_at_ms
                       AND hitl.conversation_id = authority.conversation_id
                      THEN 1 ELSE 0
                    END
             FROM desktop_automation_hitl_authorities AS authority
             LEFT JOIN desktop_automation_runs AS run ON run.id = authority.run_id
             LEFT JOIN desktop_automation_operations AS operation
               ON operation.id = authority.operation_id AND operation.run_id = authority.run_id
             LEFT JOIN desktop_hitl_requests AS hitl ON hitl.id = authority.request_id
             WHERE authority.request_id = ?1",
        )
        .map_err(storage)?;
    let record = statement
        .query_row([request_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, i64>(6)?,
                row.get::<_, Option<String>>(7)?,
                row.get::<_, Option<String>>(8)?,
                row.get::<_, Option<String>>(9)?,
                row.get::<_, Option<String>>(10)?,
                row.get::<_, i64>(11)?,
            ))
        })
        .optional()
        .map_err(storage)?;
    let Some((
        run_id,
        operation_id,
        runtime_execution_id,
        tenant_id,
        project_id,
        conversation_id,
        deadline_at_ms,
        response_answer,
        run_status,
        operation_status,
        request_status,
        authority_matches,
    )) = record
    else {
        return Ok(None);
    };
    if authority_matches != 1 {
        return Err(invalid_authority(
            "automation HITL authority does not match its canonical records",
        ));
    }
    let run_status = required_value(run_status, "automation run status is missing")?;
    let operation_status =
        required_value(operation_status, "automation operation status is missing")?;
    let request_status = required_value(request_status, "automation HITL status is missing")?;
    let deadline_at = DateTime::from_timestamp_millis(deadline_at_ms)
        .ok_or_else(|| invalid_authority("automation deadline is invalid"))?;
    Ok(Some(AutomationHitlAuthority {
        run_id,
        operation_id,
        runtime_execution_id,
        tenant_id,
        project_id,
        conversation_id,
        request_id: request_id.to_string(),
        deadline_at,
        response_answer,
        run_status,
        operation_status,
        request_status,
    }))
}

fn requeue_answered_wait(
    transaction: &Transaction<'_>,
    authority: &AutomationHitlAuthority,
    now: DateTime<Utc>,
) -> Result<AutomationHitlResumeOutcome, AutomationLedgerError> {
    match (
        authority.run_status.as_str(),
        authority.operation_status.as_str(),
    ) {
        ("waiting_human", "waiting_human") => {}
        ("queued", "queued") | ("running", "running") => {
            return Ok(AutomationHitlResumeOutcome::AlreadyResumed);
        }
        ("timeout", "timeout") => return Ok(AutomationHitlResumeOutcome::Expired),
        (run_status, operation_status)
            if run_status == operation_status
                && matches!(run_status, "success" | "failed" | "cancelled") =>
        {
            return Ok(AutomationHitlResumeOutcome::AlreadyResumed);
        }
        _ => {
            return Err(invalid_authority(
                "automation HITL run and operation statuses disagree",
            ));
        }
    }
    let now_text = now.to_rfc3339();
    let updated_operation = transaction
        .execute(
            "UPDATE desktop_automation_operations
             SET status = 'queued', available_at_ms = ?1, last_error_code = NULL,
                 lease_owner = NULL, lease_token = NULL, lease_expires_at_ms = NULL,
                 updated_at = ?2
             WHERE id = ?3 AND run_id = ?4 AND status = 'waiting_human'",
            params![
                now.timestamp_millis(),
                now_text,
                authority.operation_id,
                authority.run_id,
            ],
        )
        .map_err(storage)?;
    let updated_run = transaction
        .execute(
            "UPDATE desktop_automation_runs
             SET status = 'queued', error_code = NULL, finished_at = NULL, updated_at = ?1
             WHERE id = ?2 AND status = 'waiting_human'",
            params![now_text, authority.run_id],
        )
        .map_err(storage)?;
    if updated_operation != 1 || updated_run != 1 {
        return Err(AutomationLedgerError::LeaseLost);
    }
    transaction
        .execute(
            "UPDATE desktop_automation_run_receipts SET status = 'queued' WHERE run_id = ?1",
            [authority.run_id.as_str()],
        )
        .map_err(storage)?;
    Ok(AutomationHitlResumeOutcome::Requeued)
}

fn expire_wait(
    transaction: &Transaction<'_>,
    authority: &AutomationHitlAuthority,
    now: DateTime<Utc>,
) -> Result<(), AutomationLedgerError> {
    if authority.run_status == "timeout" && authority.operation_status == "timeout" {
        return Ok(());
    }
    if authority.run_status != "waiting_human" || authority.operation_status != "waiting_human" {
        return Err(invalid_authority(
            "only a waiting automation HITL request can expire",
        ));
    }
    let now_text = now.to_rfc3339();
    let summary = json!({
        "authority": "local_automation_worker",
        "status": "expired",
        "reason_code": AUTOMATION_HITL_EXPIRED_REASON,
        "hitl_request_id": authority.request_id,
        "runtime_execution_id": authority.runtime_execution_id,
    });
    let operation_count = transaction
        .execute(
            "UPDATE desktop_automation_operations
             SET status = 'timeout', last_error_code = ?1,
                 lease_owner = NULL, lease_token = NULL, lease_expires_at_ms = NULL,
                 updated_at = ?2
             WHERE id = ?3 AND run_id = ?4 AND status = 'waiting_human'",
            params![
                AUTOMATION_HITL_EXPIRED_REASON,
                now_text,
                authority.operation_id,
                authority.run_id,
            ],
        )
        .map_err(storage)?;
    let run_count = transaction
        .execute(
            "UPDATE desktop_automation_runs
             SET status = 'timeout', error_code = ?1, result_summary_json = ?2,
                 finished_at = ?3, updated_at = ?3
             WHERE id = ?4 AND status = 'waiting_human'",
            params![
                AUTOMATION_HITL_EXPIRED_REASON,
                serde_json::to_string(&summary).map_err(invalid_record)?,
                now_text,
                authority.run_id,
            ],
        )
        .map_err(storage)?;
    if operation_count != 1 || run_count != 1 {
        return Err(AutomationLedgerError::LeaseLost);
    }
    transaction
        .execute(
            "UPDATE desktop_automation_run_receipts SET status = 'timeout' WHERE run_id = ?1",
            [authority.run_id.as_str()],
        )
        .map_err(storage)?;
    if let Some(request) = hitl_request(transaction, &authority.request_id)? {
        if request.status == DesktopHitlStatus::Pending {
            mark_request_responded(
                transaction,
                request,
                &json!({
                    "status": "expired",
                    "reason_code": AUTOMATION_HITL_EXPIRED_REASON,
                }),
                "local_automation_expiry",
                Some(&format!("automation-expiry:{}", authority.run_id)),
                now,
            )?;
        }
    }
    Ok(())
}

fn hitl_request(
    connection: &Connection,
    request_id: &str,
) -> Result<Option<DesktopHitlRequest>, AutomationLedgerError> {
    let encoded = connection
        .query_row(
            "SELECT value_json FROM desktop_hitl_requests WHERE id = ?1",
            [request_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(storage)?;
    encoded
        .map(|value| serde_json::from_str(&value).map_err(invalid_record))
        .transpose()
}

fn mark_request_responded(
    transaction: &Transaction<'_>,
    mut request: DesktopHitlRequest,
    response_data: &Value,
    actor: &str,
    idempotency_key: Option<&str>,
    now: DateTime<Utc>,
) -> Result<(), AutomationLedgerError> {
    let now_text = now.to_rfc3339();
    request.authority_revision = request
        .authority_revision
        .checked_add(1)
        .ok_or_else(|| invalid_authority("automation HITL authority revision overflowed"))?;
    request.status = DesktopHitlStatus::Responded;
    request.responded_at = Some(now_text.clone());
    request.response_data = Some(response_data.clone());
    request.response_actor = Some(actor.to_string());
    request.response_revision = None;
    request.idempotency_key = idempotency_key.map(ToString::to_string);
    let updated = transaction
        .execute(
            "UPDATE desktop_hitl_requests
             SET status = 'responded', responded_at = ?1, value_json = ?2
             WHERE id = ?3 AND status = 'pending'",
            params![
                now_text,
                serde_json::to_string(&request).map_err(invalid_record)?,
                request.id,
            ],
        )
        .map_err(storage)?;
    if updated != 1 {
        return Err(AutomationLedgerError::IdempotencyConflict);
    }
    Ok(())
}

fn required_value(
    value: Option<String>,
    error: &'static str,
) -> Result<String, AutomationLedgerError> {
    value
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| invalid_authority(error))
}

fn invalid_authority(message: impl Into<String>) -> AutomationLedgerError {
    AutomationLedgerError::InvalidRecord(message.into())
}
