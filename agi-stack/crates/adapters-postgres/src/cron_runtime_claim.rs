//! Durable runtime claim selection and lease creation.

use chrono::{DateTime, Duration, Utc};
use serde_json::Value;
use sqlx::{FromRow, Row};

use crate::cron_runtime_repo::{payload_from_parts, timeout_snapshot};
use crate::{
    AutomationRunContext, AutomationRunLease, AutomationRunStatus,
    AutomationRuntimeRepositoryError, AutomationRuntimeScope, PgCronAutomationRuntimeRepository,
};

impl PgCronAutomationRuntimeRepository {
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
