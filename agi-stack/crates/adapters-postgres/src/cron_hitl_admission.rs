//! Atomic admission of a persisted non-secret automation HITL answer.
//!
//! Run revision fencing and PostgreSQL row locks serialize independent hosts.
//! Checkpoint acceptance and queueing commit together; no caller-supplied answer
//! can reach the checkpoint. This admits recovery of an already accepted run,
//! not schedule ownership, generation activation, or tool mutation permission.

use agistack_core::agent::{HitlKind, SessionState, SessionStatus};
use chrono::{DateTime, Utc};
use serde_json::Value;

use crate::{AutomationRuntimeRepositoryError, PgPool};

#[derive(Debug, Clone)]
pub struct AutomationHitlAdmissionCommand {
    pub tenant_id: String,
    pub project_id: String,
    pub job_id: String,
    pub run_id: String,
    pub conversation_id: String,
    pub request_id: String,
    pub expected_runtime_revision: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AutomationHitlAdmissionOutcome {
    Applied { runtime_revision: i64 },
    NotAdmitted,
}

#[derive(Clone)]
pub struct PgAutomationHitlAdmission {
    pool: PgPool,
}

impl PgAutomationHitlAdmission {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn admit(
        &self,
        command: &AutomationHitlAdmissionCommand,
        now: DateTime<Utc>,
    ) -> Result<AutomationHitlAdmissionOutcome, AutomationRuntimeRepositoryError> {
        validate_command(command)?;
        let mut tx = self.pool.begin().await.map_err(storage)?;
        // Match the terminal projector's run -> job -> operation lock order.
        // Runtime claim cannot observe queued until this transaction commits.
        let run = sqlx::query_scalar::<_, String>(
            "SELECT id FROM cron_job_runs \
             WHERE id = $1 AND runtime_execution_id = $1 AND job_id = $2 \
               AND project_id = $3 AND conversation_id = $4 \
               AND status = 'waiting_human' AND runtime_revision = $5 \
               AND deadline_at IS NOT NULL \
               AND deadline_at > GREATEST($6, clock_timestamp()) FOR UPDATE",
        )
        .bind(&command.run_id)
        .bind(&command.job_id)
        .bind(&command.project_id)
        .bind(&command.conversation_id)
        .bind(command.expected_runtime_revision)
        .bind(now)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?;
        if run.is_none() {
            return Ok(AutomationHitlAdmissionOutcome::NotAdmitted);
        }
        let job = sqlx::query_scalar::<_, String>(
            "SELECT id FROM cron_jobs \
             WHERE id = $1 AND tenant_id = $2 AND project_id = $3 FOR UPDATE",
        )
        .bind(&command.job_id)
        .bind(&command.tenant_id)
        .bind(&command.project_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?;
        if job.is_none() {
            return Ok(AutomationHitlAdmissionOutcome::NotAdmitted);
        }
        let operation = sqlx::query_scalar::<_, String>(
            "SELECT id FROM agistack_cron_operations \
             WHERE run_id = $1 AND job_id = $2 AND tenant_id = $3 AND project_id = $4 \
               AND operation_kind = 'execute_run' AND status = 'waiting_runtime' FOR UPDATE",
        )
        .bind(&command.run_id)
        .bind(&command.job_id)
        .bind(&command.tenant_id)
        .bind(&command.project_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?;
        if operation.is_none() {
            return Ok(AutomationHitlAdmissionOutcome::NotAdmitted);
        }
        let answer = sqlx::query_as::<_, (String, String)>(
            "SELECT request_type, response_metadata ->> 'resume_answer' \
             FROM hitl_requests WHERE id = $1 AND tenant_id = $2 AND project_id = $3 \
               AND message_id = $4 AND conversation_id = $5 AND status = 'answered' \
               AND request_type IN ('clarification', 'decision', 'permission') \
               AND expires_at > GREATEST($6, clock_timestamp()) AND answered_at IS NOT NULL \
               AND request_metadata ->> 'automation_run_id' = $4 \
               AND request_metadata ->> 'runtime_execution_id' = $4 \
               AND request_metadata ->> 'checkpoint_session_id' = $4 \
               AND response_metadata ->> 'resume_answer' IS NOT NULL FOR UPDATE",
        )
        .bind(&command.request_id)
        .bind(&command.tenant_id)
        .bind(&command.project_id)
        .bind(&command.run_id)
        .bind(&command.conversation_id)
        .bind(now)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?;
        let Some((request_type, answer)) = answer else {
            return Ok(AutomationHitlAdmissionOutcome::NotAdmitted);
        };
        let original = sqlx::query_scalar::<_, Value>(
            "SELECT state FROM agistack_checkpoints WHERE session_id = $1 FOR UPDATE",
        )
        .bind(&command.run_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?
        .ok_or(AutomationRuntimeRepositoryError::InvalidRunState)?;
        let updated = accepted_checkpoint(&original, command, &request_type, &answer)?;
        let checkpoint_updated = sqlx::query(
            "UPDATE agistack_checkpoints SET state = $2, updated_at = $3 \
             WHERE session_id = $1 AND state = $4",
        )
        .bind(&command.run_id)
        .bind(updated)
        .bind(now)
        .bind(original)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        if checkpoint_updated.rows_affected() != 1 {
            return Err(AutomationRuntimeRepositoryError::LeaseLost);
        }
        let revision = sqlx::query_scalar::<_, i64>(
            "UPDATE cron_job_runs SET status = 'queued', runtime_revision = runtime_revision + 1, \
                 runtime_lease_owner = NULL, runtime_lease_token = NULL, \
                 runtime_lease_expires_at = NULL, last_heartbeat_at = $3 \
             WHERE id = $1 AND status = 'waiting_human' AND runtime_revision = $2 \
               AND deadline_at > GREATEST($3, clock_timestamp()) \
               AND EXISTS (SELECT 1 FROM hitl_requests WHERE id = $4 \
                   AND expires_at > GREATEST($3, clock_timestamp())) \
             RETURNING runtime_revision",
        )
        .bind(&command.run_id)
        .bind(command.expected_runtime_revision)
        .bind(now)
        .bind(&command.request_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?
        .ok_or(AutomationRuntimeRepositoryError::LeaseLost)?;
        tx.commit().await.map_err(storage)?;
        Ok(AutomationHitlAdmissionOutcome::Applied {
            runtime_revision: revision,
        })
    }
}

fn validate_command(
    command: &AutomationHitlAdmissionCommand,
) -> Result<(), AutomationRuntimeRepositoryError> {
    if command.expected_runtime_revision <= 0
        || command.expected_runtime_revision == i64::MAX
        || [
            &command.tenant_id,
            &command.project_id,
            &command.job_id,
            &command.run_id,
            &command.conversation_id,
            &command.request_id,
        ]
        .iter()
        .any(|value| value.trim().is_empty())
    {
        return Err(AutomationRuntimeRepositoryError::InvalidRunState);
    }
    Ok(())
}

fn accepted_checkpoint(
    original: &Value,
    command: &AutomationHitlAdmissionCommand,
    request_type: &str,
    answer: &str,
) -> Result<Value, AutomationRuntimeRepositoryError> {
    let mut state: SessionState = serde_json::from_value(original.clone())
        .map_err(|_| AutomationRuntimeRepositoryError::InvalidRunState)?;
    let expected_kind = match request_type {
        "clarification" => HitlKind::Clarification,
        "decision" => HitlKind::Decision,
        "permission" => HitlKind::Permission,
        _ => return Err(AutomationRuntimeRepositoryError::InvalidRunState),
    };
    if state.session_id != command.run_id
        || state.project_id.as_deref() != Some(command.project_id.as_str())
        || !state.pending_hitl.as_ref().is_some_and(|request| {
            request.id == command.request_id
                && request.kind == expected_kind
                && request.permission_invocation.is_none()
        })
    {
        return Err(AutomationRuntimeRepositoryError::InvalidRunState);
    }
    match state.status {
        SessionStatus::AwaitingInput => {
            if state
                .hitl_answer(&command.request_id)
                .is_some_and(|prior| prior != answer)
            {
                return Err(AutomationRuntimeRepositoryError::InvalidRunState);
            }
            state.record_hitl_answer(&command.request_id, answer);
            state.status = SessionStatus::Running;
        }
        // Recover an old accept-before-queue crash without changing its answer.
        SessionStatus::Running if state.hitl_answer(&command.request_id) == Some(answer) => {}
        _ => return Err(AutomationRuntimeRepositoryError::InvalidRunState),
    }
    let encoded = serde_json::to_value(state)
        .map_err(|_| AutomationRuntimeRepositoryError::InvalidRunState)?;
    // Preserve unknown future fields; only these two fields belong to acceptance.
    let mut updated = original.clone();
    updated["status"] = encoded["status"].clone();
    updated["hitl_responses"] = encoded["hitl_responses"].clone();
    Ok(updated)
}

fn storage(_error: sqlx::Error) -> AutomationRuntimeRepositoryError {
    AutomationRuntimeRepositoryError::Storage("atomic automation HITL admission failed".into())
}
