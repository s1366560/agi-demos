//! Durable Agent runtime ownership for automation runs.
//!
//! The operation queue owns dispatch acceptance; this repository owns the
//! longer-lived Agent execution lease. A process may disappear after dispatch
//! without losing the run: queued runs remain claimable and expired running
//! leases resume from the shared ReAct checkpoint.

use chrono::{DateTime, Duration, Utc};
use serde_json::Value;
use sqlx::{FromRow, Postgres, Row, Transaction};

use agistack_core::ports::{CoreError, CoreResult};

use crate::cron_runtime_projection_support::{
    context_from_expired, lock_job, lock_operation, lock_run, next_job_state, operation_policy,
    terminal_summary, validate_terminal_authority, ExpiredRunRow,
};
use crate::cron_runtime_types::{
    AutomationPayload, AutomationRunContext, AutomationRunLease, AutomationRunStatus,
    AutomationRuntimeRepositoryError, AutomationRuntimeScope, AutomationTerminalObservation,
    AutomationTerminalOutcome, AutomationTerminalProjection,
};
use crate::{CronOperationKind, CronOperationRecord, CronOperationStatus, PgPool};

const NON_TERMINAL_STATUSES: &[&str] = &["queued", "running", "waiting_human"];

#[derive(Clone)]
pub struct PgCronAutomationRuntimeRepository {
    pub(crate) pool: PgPool,
}

impl PgCronAutomationRuntimeRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Validate the claimed operation and resolve one deterministic conversation.
    pub async fn prepare_dispatch(
        &self,
        operation: &CronOperationRecord,
        fresh_conversation_id: &str,
        now: DateTime<Utc>,
    ) -> Result<AutomationRunContext, AutomationRuntimeRepositoryError> {
        if operation.kind != CronOperationKind::ExecuteRun
            || operation.status != CronOperationStatus::Processing
        {
            return Err(AutomationRuntimeRepositoryError::InvalidRunState);
        }
        let run_id = operation
            .run_id
            .as_deref()
            .filter(|value| !value.trim().is_empty())
            .ok_or(AutomationRuntimeRepositoryError::InvalidRunState)?;
        let lease_owner = operation
            .lease_owner
            .as_deref()
            .ok_or(AutomationRuntimeRepositoryError::LeaseLost)?;
        let lease_token = operation
            .lease_token
            .as_deref()
            .ok_or(AutomationRuntimeRepositoryError::LeaseLost)?;

        let mut tx = self.pool.begin().await.map_err(storage)?;
        let row = sqlx::query_as::<_, DispatchRow>(
            "SELECT operation.actor_user_id, operation.actor_api_key_id, \
                    operation.input_json, operation.job_revision AS operation_job_revision, \
                    job.name AS job_name, job.created_by, job.revision AS job_revision, \
                    job.payload_type, job.payload_config, job.conversation_mode, \
                    job.conversation_id AS job_conversation_id, job.timeout_seconds, \
                    run.status AS run_status, run.runtime_execution_id, \
                    run.conversation_id AS run_conversation_id \
             FROM agistack_cron_operations AS operation \
             JOIN cron_jobs AS job ON job.id = operation.job_id \
             JOIN cron_job_runs AS run ON run.id = operation.run_id AND run.job_id = job.id \
             WHERE operation.id = $1 AND operation.tenant_id = $2 \
               AND operation.project_id = $3 AND operation.job_id = $4 \
               AND operation.run_id = $5 AND operation.operation_kind = 'execute_run' \
               AND operation.status = 'processing' \
               AND operation.lease_owner = $6 AND operation.lease_token = $7 \
               AND operation.lease_expires_at > $8 \
               AND job.tenant_id = operation.tenant_id \
               AND job.project_id = operation.project_id \
               AND run.project_id = operation.project_id \
             FOR UPDATE OF operation, job, run",
        )
        .bind(&operation.id)
        .bind(&operation.tenant_id)
        .bind(&operation.project_id)
        .bind(&operation.job_id)
        .bind(run_id)
        .bind(lease_owner)
        .bind(lease_token)
        .bind(now)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?
        .ok_or(AutomationRuntimeRepositoryError::LeaseLost)?;

        if row.job_revision != operation.job_revision
            || row.operation_job_revision != operation.job_revision
        {
            return Err(AutomationRuntimeRepositoryError::StaleRevision);
        }
        if row.runtime_execution_id.as_deref() != Some(run_id) {
            return Err(AutomationRuntimeRepositoryError::InvalidRunState);
        }
        let actor_user_id = row
            .actor_user_id
            .clone()
            .or(row.created_by.clone())
            .filter(|value| !value.trim().is_empty())
            .ok_or(AutomationRuntimeRepositoryError::MissingActor)?;
        let payload = payload_from_row(&row)?;
        let timeout_seconds = timeout_snapshot(&row.input_json, row.timeout_seconds);
        let conversation_id = resolve_conversation(
            &mut tx,
            operation,
            &actor_user_id,
            &row,
            fresh_conversation_id,
        )
        .await?;
        tx.commit().await.map_err(storage)?;

        Ok(AutomationRunContext {
            tenant_id: operation.tenant_id.clone(),
            project_id: operation.project_id.clone(),
            job_id: operation.job_id.clone(),
            run_id: run_id.to_string(),
            runtime_execution_id: run_id.to_string(),
            conversation_id,
            actor_user_id,
            actor_api_key_id: row.actor_api_key_id,
            payload,
            timeout_seconds,
            status: AutomationRunStatus::try_from(row.run_status.as_str())?,
        })
    }

    /// Discover tenant/project scopes with operation or runtime work.
    pub async fn active_scopes(&self, limit: i64) -> CoreResult<Vec<AutomationRuntimeScope>> {
        sqlx::query_as::<_, ScopeRow>(
            "SELECT DISTINCT tenant_id, project_id \
             FROM agistack_cron_operations \
             WHERE status IN ('pending', 'failed', 'processing', 'waiting_runtime') \
             ORDER BY tenant_id, project_id LIMIT $1",
        )
        .bind(limit.clamp(1, 1_000))
        .fetch_all(&self.pool)
        .await
        .map(|rows| {
            rows.into_iter()
                .map(|row| AutomationRuntimeScope {
                    tenant_id: row.tenant_id,
                    project_id: row.project_id,
                })
                .collect()
        })
        .map_err(|error| CoreError::Storage(format!("cron runtime scopes: {error}")))
    }

    /// Claim queued or crash-interrupted Agent runs behind accepted operations.
    pub async fn claim_due(
        &self,
        scope: &AutomationRuntimeScope,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Vec<AutomationRunLease>, AutomationRuntimeRepositoryError> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let candidates = sqlx::query_as::<_, RuntimeCandidateRow>(
            "SELECT run.id AS run_id, run.runtime_execution_id, run.status AS run_status, \
                    run.runtime_revision, run.deadline_at, run.conversation_id, \
                    operation.tenant_id, operation.project_id, operation.job_id, \
                    operation.actor_user_id, operation.actor_api_key_id, operation.input_json, \
                    job.created_by, job.payload_type, job.payload_config, job.timeout_seconds \
             FROM cron_job_runs AS run \
             JOIN agistack_cron_operations AS operation \
               ON operation.run_id = run.id AND operation.operation_kind = 'execute_run' \
             JOIN cron_jobs AS job ON job.id = run.job_id \
             WHERE operation.tenant_id = $1 AND operation.project_id = $2 \
               AND operation.status = 'waiting_runtime' \
               AND run.project_id = operation.project_id \
               AND job.tenant_id = operation.tenant_id \
               AND job.project_id = operation.project_id \
               AND (run.status = 'queued' OR ( \
                    run.status = 'running' \
                    AND run.runtime_lease_expires_at IS NOT NULL \
                    AND run.runtime_lease_expires_at <= $3 \
                    AND (run.deadline_at IS NULL OR run.deadline_at > $3) \
               )) \
             ORDER BY run.accepted_at, run.id \
             LIMIT $4 FOR UPDATE OF run SKIP LOCKED",
        )
        .bind(&scope.tenant_id)
        .bind(&scope.project_id)
        .bind(now)
        .bind(limit.clamp(1, 100))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;

        let mut leases = Vec::with_capacity(candidates.len());
        for candidate in candidates {
            let context = context_from_candidate(&candidate)?;
            let timeout_seconds = context.timeout_seconds.max(1);
            let lease_expires_at = now + Duration::seconds(lease_seconds.max(1));
            let deadline_at = candidate
                .deadline_at
                .unwrap_or_else(|| now + Duration::seconds(timeout_seconds));
            let row = sqlx::query(
                "UPDATE cron_job_runs \
                 SET status = 'running', runtime_revision = runtime_revision + 1, \
                     runtime_lease_owner = $2, \
                     runtime_lease_token = concat(id, ':', runtime_revision + 1, ':', txid_current()), \
                     runtime_lease_expires_at = $3, deadline_at = $4, \
                     last_heartbeat_at = $5, started_at = CASE \
                         WHEN status = 'queued' THEN $5 ELSE started_at END \
                 WHERE id = $1 AND status IN ('queued', 'running') \
                 RETURNING runtime_revision, runtime_lease_token, runtime_lease_expires_at, deadline_at",
            )
            .bind(&candidate.run_id)
            .bind(lease_owner)
            .bind(lease_expires_at)
            .bind(deadline_at)
            .bind(now)
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
            leases.push(AutomationRunLease {
                context: AutomationRunContext {
                    status: AutomationRunStatus::Running,
                    ..context
                },
                runtime_revision: row.try_get("runtime_revision").map_err(storage)?,
                lease_owner: lease_owner.to_string(),
                lease_token: row.try_get("runtime_lease_token").map_err(storage)?,
                lease_expires_at: row.try_get("runtime_lease_expires_at").map_err(storage)?,
                deadline_at: row.try_get("deadline_at").map_err(storage)?,
            });
        }
        tx.commit().await.map_err(storage)?;
        Ok(leases)
    }

    pub async fn renew(
        &self,
        lease: &AutomationRunLease,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        sqlx::query(
            "UPDATE cron_job_runs AS run \
             SET runtime_lease_expires_at = $8 + ($9 * interval '1 second'), \
                 last_heartbeat_at = $8 \
             FROM cron_jobs AS job \
             WHERE run.id = $1 AND run.runtime_execution_id = $2 \
               AND run.project_id = $3 AND run.job_id = $4 \
               AND run.status = 'running' AND run.runtime_revision = $5 \
               AND run.runtime_lease_owner = $6 AND run.runtime_lease_token = $7 \
               AND run.runtime_lease_expires_at > $8 \
               AND job.id = run.job_id AND job.tenant_id = $10 \
               AND job.project_id = run.project_id",
        )
        .bind(&lease.context.run_id)
        .bind(&lease.context.runtime_execution_id)
        .bind(&lease.context.project_id)
        .bind(&lease.context.job_id)
        .bind(lease.runtime_revision)
        .bind(&lease.lease_owner)
        .bind(&lease.lease_token)
        .bind(now)
        .bind(lease_seconds.max(1))
        .bind(&lease.context.tenant_id)
        .execute(&self.pool)
        .await
        .map(|result| result.rows_affected() == 1)
        .map_err(|error| CoreError::Storage(format!("renew cron runtime lease: {error}")))
    }

    pub async fn mark_waiting_human(
        &self,
        lease: &AutomationRunLease,
        observed_at: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError> {
        sqlx::query(
            "UPDATE cron_job_runs AS run \
             SET status = 'waiting_human', runtime_lease_owner = NULL, \
                 runtime_lease_token = NULL, runtime_lease_expires_at = NULL, \
                 last_heartbeat_at = $8, conversation_id = $9 \
             FROM cron_jobs AS job \
             WHERE run.id = $1 AND run.runtime_execution_id = $2 \
               AND run.project_id = $3 AND run.job_id = $4 \
               AND run.status = 'running' AND run.runtime_revision = $5 \
               AND run.runtime_lease_owner = $6 AND run.runtime_lease_token = $7 \
               AND job.id = run.job_id AND job.tenant_id = $10 \
               AND job.project_id = run.project_id",
        )
        .bind(&lease.context.run_id)
        .bind(&lease.context.runtime_execution_id)
        .bind(&lease.context.project_id)
        .bind(&lease.context.job_id)
        .bind(lease.runtime_revision)
        .bind(&lease.lease_owner)
        .bind(&lease.lease_token)
        .bind(observed_at)
        .bind(&lease.context.conversation_id)
        .bind(&lease.context.tenant_id)
        .execute(&self.pool)
        .await
        .map(|result| result.rows_affected() == 1)
        .map_err(storage)
    }

    /// Queue an answered non-secret HITL run for durable checkpoint resume.
    pub async fn queue_resume(
        &self,
        tenant_id: &str,
        project_id: &str,
        run_id: &str,
        conversation_id: &str,
        observed_at: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError> {
        sqlx::query(
            "UPDATE cron_job_runs AS run \
             SET status = 'queued', runtime_lease_owner = NULL, runtime_lease_token = NULL, \
                 runtime_lease_expires_at = NULL, last_heartbeat_at = $5 \
             FROM cron_jobs AS job, agistack_cron_operations AS operation \
             WHERE run.id = $1 AND run.runtime_execution_id = $1 \
               AND run.project_id = $2 AND run.conversation_id = $3 \
               AND run.status = 'waiting_human' \
               AND job.id = run.job_id AND job.tenant_id = $4 \
               AND job.project_id = run.project_id \
               AND operation.run_id = run.id AND operation.operation_kind = 'execute_run' \
               AND operation.tenant_id = $4 AND operation.project_id = $2 \
               AND operation.status = 'waiting_runtime'",
        )
        .bind(run_id)
        .bind(project_id)
        .bind(conversation_id)
        .bind(tenant_id)
        .bind(observed_at)
        .execute(&self.pool)
        .await
        .map(|result| result.rows_affected() == 1)
        .map_err(storage)
    }

    /// Project the first terminal result and job accounting in one transaction.
    pub async fn project_terminal(
        &self,
        lease: &AutomationRunLease,
        outcome: AutomationTerminalOutcome,
        error_code: Option<&str>,
        event_count: u64,
        execution_time_ms: u64,
        observed_at: DateTime<Utc>,
    ) -> Result<AutomationTerminalProjection, AutomationRuntimeRepositoryError> {
        let observation = AutomationTerminalObservation {
            outcome,
            error_code,
            event_count,
            execution_time_ms,
            observed_at,
        };
        self.project_terminal_inner(&lease.context, Some(lease), observation)
            .await
    }

    /// Convert expired running/waiting runs to timeout using the same projector.
    pub async fn recover_expired(
        &self,
        scope: &AutomationRuntimeScope,
        limit: i64,
        now: DateTime<Utc>,
    ) -> Result<usize, AutomationRuntimeRepositoryError> {
        let rows = sqlx::query_as::<_, ExpiredRunRow>(
            "SELECT run.id AS run_id, run.runtime_execution_id, run.conversation_id, \
                    run.status AS run_status, operation.job_id, operation.actor_user_id, \
                    operation.actor_api_key_id, operation.input_json, \
                    job.created_by, job.payload_type, job.payload_config, job.timeout_seconds \
             FROM cron_job_runs AS run \
             JOIN cron_jobs AS job ON job.id = run.job_id \
             JOIN agistack_cron_operations AS operation \
               ON operation.run_id = run.id AND operation.operation_kind = 'execute_run' \
             WHERE operation.tenant_id = $1 AND operation.project_id = $2 \
               AND run.project_id = $2 AND run.status IN ('running', 'waiting_human') \
               AND run.deadline_at IS NOT NULL AND run.deadline_at <= $3 \
             ORDER BY run.deadline_at, run.id LIMIT $4",
        )
        .bind(&scope.tenant_id)
        .bind(&scope.project_id)
        .bind(now)
        .bind(limit.clamp(1, 100))
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;

        let mut recovered = 0;
        for row in rows {
            let context = context_from_expired(scope, row)?;
            let observation = AutomationTerminalObservation {
                outcome: AutomationTerminalOutcome::Timeout,
                error_code: Some("execution_timed_out"),
                event_count: 0,
                execution_time_ms: 0,
                observed_at: now,
            };
            let projection = self
                .project_terminal_inner(&context, None, observation)
                .await?;
            if projection.matched && !projection.duplicate {
                recovered += 1;
            }
        }
        Ok(recovered)
    }

    async fn project_terminal_inner(
        &self,
        context: &AutomationRunContext,
        lease: Option<&AutomationRunLease>,
        observation: AutomationTerminalObservation<'_>,
    ) -> Result<AutomationTerminalProjection, AutomationRuntimeRepositoryError> {
        let AutomationTerminalObservation {
            outcome,
            error_code,
            event_count,
            execution_time_ms,
            observed_at,
        } = observation;
        let desired = outcome.status();
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let run = lock_run(&mut tx, context).await?;
        let Some(run) = run else {
            return Ok(AutomationTerminalProjection {
                matched: false,
                duplicate: false,
                run_status: None,
                operation_status: None,
                delivery_ack_pending: true,
            });
        };
        let current = AutomationRunStatus::try_from(run.status.as_str())?;
        if current.is_terminal() {
            if current != desired {
                return Err(AutomationRuntimeRepositoryError::TerminalConflict);
            }
            tx.commit().await.map_err(storage)?;
            return Ok(AutomationTerminalProjection {
                matched: true,
                duplicate: true,
                run_status: Some(current),
                operation_status: None,
                delivery_ack_pending: false,
            });
        }
        if !NON_TERMINAL_STATUSES.contains(&current.as_str()) {
            return Err(AutomationRuntimeRepositoryError::InvalidRunState);
        }
        validate_terminal_authority(&run, lease, outcome, observed_at)?;
        let job = lock_job(&mut tx, context).await?;
        let operation = lock_operation(&mut tx, context).await?;
        let result_summary =
            terminal_summary(context, desired, error_code, event_count, execution_time_ms);
        sqlx::query(
            "UPDATE cron_job_runs SET status = $2, finished_at = $3, duration_ms = $4, \
                    error_message = $5, result_summary = $6, conversation_id = $7, \
                    runtime_lease_owner = NULL, runtime_lease_token = NULL, \
                    runtime_lease_expires_at = NULL, last_heartbeat_at = $3 \
             WHERE id = $1",
        )
        .bind(&context.run_id)
        .bind(desired.as_str())
        .bind(observed_at)
        .bind(i32::try_from(execution_time_ms).unwrap_or(i32::MAX))
        .bind(error_code)
        .bind(&result_summary)
        .bind(&context.conversation_id)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;

        let policy = operation_policy(&operation.input_json, &job);
        let job_state = next_job_state(&job.state, outcome, error_code, observed_at, &policy);
        let retire = outcome == AutomationTerminalOutcome::Success
            && (policy.delete_after_run || policy.one_shot);
        sqlx::query(
            "UPDATE cron_jobs SET state = $2, enabled = CASE WHEN $3 THEN false ELSE enabled END, \
                    updated_at = $4 WHERE id = $1",
        )
        .bind(&context.job_id)
        .bind(&job_state)
        .bind(retire || policy.disable_after_failure)
        .bind(observed_at)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;

        let mut operation_status = operation.status.clone();
        let mut delivery_ack_pending = true;
        if operation.status == "waiting_runtime" {
            sqlx::query(
                "UPDATE agistack_cron_operations \
                 SET status = 'completed', result_json = result_json || $2, \
                     next_attempt_at = NULL, last_error_code = NULL, \
                     last_error_redacted = NULL, completed_at = $3, updated_at = $3 \
                 WHERE id = $1 AND status = 'waiting_runtime'",
            )
            .bind(&operation.id)
            .bind(&result_summary)
            .bind(observed_at)
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
            operation_status = "completed".to_string();
            delivery_ack_pending = false;
        } else if operation.status == "completed" {
            delivery_ack_pending = false;
        }
        tx.commit().await.map_err(storage)?;
        Ok(AutomationTerminalProjection {
            matched: true,
            duplicate: false,
            run_status: Some(desired),
            operation_status: Some(operation_status),
            delivery_ack_pending,
        })
    }
}

#[derive(Debug, FromRow)]
struct DispatchRow {
    actor_user_id: Option<String>,
    actor_api_key_id: Option<String>,
    input_json: Value,
    operation_job_revision: i64,
    job_name: String,
    created_by: Option<String>,
    job_revision: i64,
    payload_type: String,
    payload_config: Value,
    conversation_mode: String,
    job_conversation_id: Option<String>,
    timeout_seconds: i32,
    run_status: String,
    runtime_execution_id: Option<String>,
    run_conversation_id: Option<String>,
}

#[derive(Debug, FromRow)]
struct RuntimeCandidateRow {
    run_id: String,
    runtime_execution_id: Option<String>,
    run_status: String,
    #[allow(dead_code)]
    runtime_revision: i64,
    deadline_at: Option<DateTime<Utc>>,
    conversation_id: Option<String>,
    tenant_id: String,
    project_id: String,
    job_id: String,
    actor_user_id: Option<String>,
    actor_api_key_id: Option<String>,
    input_json: Value,
    created_by: Option<String>,
    payload_type: String,
    payload_config: Value,
    timeout_seconds: i32,
}

#[derive(Debug, FromRow)]
struct ScopeRow {
    tenant_id: String,
    project_id: String,
}

async fn resolve_conversation(
    tx: &mut Transaction<'_, Postgres>,
    operation: &CronOperationRecord,
    actor_user_id: &str,
    row: &DispatchRow,
    fresh_conversation_id: &str,
) -> Result<String, AutomationRuntimeRepositoryError> {
    let tenant_id = &operation.tenant_id;
    let project_id = &operation.project_id;
    let job_id = &operation.job_id;
    let run_id = operation
        .run_id
        .as_deref()
        .ok_or(AutomationRuntimeRepositoryError::InvalidRunState)?;
    let explicit = row
        .run_conversation_id
        .clone()
        .or_else(|| string_field(&row.input_json, "conversation_id"));
    let candidate = explicit.clone().or_else(|| {
        (row.conversation_mode == "reuse")
            .then(|| row.job_conversation_id.clone())
            .flatten()
    });
    if let Some(candidate) = candidate {
        let valid = sqlx::query_scalar::<_, bool>(
            "SELECT EXISTS(SELECT 1 FROM conversations \
             WHERE id = $1 AND tenant_id = $2 AND project_id = $3 AND user_id = $4)",
        )
        .bind(&candidate)
        .bind(tenant_id)
        .bind(project_id)
        .bind(actor_user_id)
        .fetch_one(&mut **tx)
        .await
        .map_err(storage)?;
        if valid {
            sqlx::query("UPDATE cron_job_runs SET conversation_id = $2 WHERE id = $1")
                .bind(run_id)
                .bind(&candidate)
                .execute(&mut **tx)
                .await
                .map_err(storage)?;
            return Ok(candidate);
        }
        if explicit.is_some() {
            return Err(AutomationRuntimeRepositoryError::InvalidConversation);
        }
    }
    if fresh_conversation_id.trim().is_empty() {
        return Err(AutomationRuntimeRepositoryError::InvalidConversation);
    }
    sqlx::query(
        "INSERT INTO conversations \
            (id, project_id, tenant_id, user_id, title, status, agent_config, meta, \
             message_count, current_mode, merge_strategy, created_at, updated_at) \
         VALUES ($1, $2, $3, $4, $5, 'active', '{}'::json, \
                 json_build_object('automation_run_id', $6), 0, 'build', \
                 'result_only', now(), now()) \
         ON CONFLICT (id) DO NOTHING",
    )
    .bind(fresh_conversation_id)
    .bind(project_id)
    .bind(tenant_id)
    .bind(actor_user_id)
    .bind(format!("[Cron] {}", row.job_name))
    .bind(run_id)
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    let valid = sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS(SELECT 1 FROM conversations \
         WHERE id = $1 AND tenant_id = $2 AND project_id = $3 AND user_id = $4)",
    )
    .bind(fresh_conversation_id)
    .bind(tenant_id)
    .bind(project_id)
    .bind(actor_user_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(storage)?;
    if !valid {
        return Err(AutomationRuntimeRepositoryError::InvalidConversation);
    }
    sqlx::query("UPDATE cron_job_runs SET conversation_id = $2 WHERE id = $1")
        .bind(run_id)
        .bind(fresh_conversation_id)
        .execute(&mut **tx)
        .await
        .map_err(storage)?;
    if row.conversation_mode == "reuse" {
        sqlx::query("UPDATE cron_jobs SET conversation_id = $2 WHERE id = $1")
            .bind(job_id)
            .bind(fresh_conversation_id)
            .execute(&mut **tx)
            .await
            .map_err(storage)?;
    }
    Ok(fresh_conversation_id.to_string())
}

fn payload_from_row(
    row: &DispatchRow,
) -> Result<AutomationPayload, AutomationRuntimeRepositoryError> {
    payload_from_parts(&row.payload_type, &row.payload_config)
}

pub(crate) fn payload_from_parts(
    payload_type: &str,
    config: &Value,
) -> Result<AutomationPayload, AutomationRuntimeRepositoryError> {
    match payload_type {
        "agent_turn" => required_string(config, "message")
            .map(|message| AutomationPayload::AgentTurn { message }),
        "system_event" => required_string(config, "content")
            .map(|content| AutomationPayload::SystemEvent { content }),
        _ => Err(AutomationRuntimeRepositoryError::InvalidPayload),
    }
}

fn required_string(value: &Value, key: &str) -> Result<String, AutomationRuntimeRepositoryError> {
    string_field(value, key).ok_or(AutomationRuntimeRepositoryError::InvalidPayload)
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
}

pub(crate) fn timeout_snapshot(input: &Value, fallback: i32) -> i64 {
    input
        .get("timeout_seconds")
        .and_then(Value::as_i64)
        .unwrap_or(i64::from(fallback))
        .max(1)
}

fn context_from_candidate(
    row: &RuntimeCandidateRow,
) -> Result<AutomationRunContext, AutomationRuntimeRepositoryError> {
    let runtime_execution_id = row
        .runtime_execution_id
        .clone()
        .filter(|value| value == &row.run_id)
        .ok_or(AutomationRuntimeRepositoryError::InvalidRunState)?;
    let actor_user_id = row
        .actor_user_id
        .clone()
        .or(row.created_by.clone())
        .filter(|value| !value.trim().is_empty())
        .ok_or(AutomationRuntimeRepositoryError::MissingActor)?;
    Ok(AutomationRunContext {
        tenant_id: row.tenant_id.clone(),
        project_id: row.project_id.clone(),
        job_id: row.job_id.clone(),
        run_id: row.run_id.clone(),
        runtime_execution_id,
        conversation_id: row
            .conversation_id
            .clone()
            .ok_or(AutomationRuntimeRepositoryError::InvalidConversation)?,
        actor_user_id,
        actor_api_key_id: row.actor_api_key_id.clone(),
        payload: payload_from_parts(&row.payload_type, &row.payload_config)?,
        timeout_seconds: timeout_snapshot(&row.input_json, row.timeout_seconds),
        status: AutomationRunStatus::try_from(row.run_status.as_str())?,
    })
}

fn storage(error: sqlx::Error) -> AutomationRuntimeRepositoryError {
    AutomationRuntimeRepositoryError::Storage(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn statuses_and_payloads_are_closed() {
        assert_eq!(
            AutomationRunStatus::try_from("waiting_human").expect("known status"),
            AutomationRunStatus::WaitingHuman
        );
        assert!(AutomationRunStatus::try_from("arbitrary").is_err());
        assert!(payload_from_parts("arbitrary", &json!({})).is_err());
        assert_eq!(
            payload_from_parts("agent_turn", &json!({"message": "ship"}))
                .expect("valid payload")
                .goal(),
            "ship"
        );
    }

    #[test]
    fn timeout_snapshot_is_positive_and_uses_operation_policy() {
        assert_eq!(timeout_snapshot(&json!({"timeout_seconds": 45}), 300), 45);
        assert_eq!(timeout_snapshot(&json!({"timeout_seconds": 0}), 300), 1);
        assert_eq!(timeout_snapshot(&json!({}), 300), 300);
    }
}
