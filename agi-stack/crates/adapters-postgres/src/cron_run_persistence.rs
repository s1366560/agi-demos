//! Checkpoint/HITL persistence bound to one durable automation execution lease.

use agistack_core::agent::SessionState;
use agistack_core::ports::{CheckpointStore, CoreError, CoreResult};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::Value;
use sqlx::{Postgres, Transaction};

use crate::{AutomationRunLease, AutomationRuntimeRepositoryError, PgPool};

mod hitl;

#[derive(Clone)]
pub struct PgAutomationRunPersistence {
    pool: PgPool,
    lease: AutomationRunLease,
}

impl PgAutomationRunPersistence {
    pub fn new(pool: PgPool, lease: AutomationRunLease) -> Self {
        Self { pool, lease }
    }

    /// All write paths lock the run before touching checkpoint or HITL rows.
    /// Compare the database's current expiry, because successful heartbeats may
    /// have extended it beyond the immutable lease originally given to this host.
    pub(crate) async fn lock_authority(
        &self,
        tx: &mut Transaction<'_, Postgres>,
        now: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError> {
        let lease = &self.lease;
        let context = &lease.context;
        if context.run_id != context.runtime_execution_id
            || lease.runtime_revision <= 0
            || [
                &context.tenant_id,
                &context.project_id,
                &context.job_id,
                &context.run_id,
                &context.conversation_id,
                &context.actor_user_id,
                &lease.lease_owner,
                &lease.lease_token,
            ]
            .iter()
            .any(|value| value.trim().is_empty())
        {
            return Ok(false);
        }
        let run = sqlx::query_scalar::<_, String>(
            "SELECT id FROM cron_job_runs \
             WHERE id = $1 AND runtime_execution_id = $1 AND job_id = $2 \
               AND project_id = $3 AND conversation_id = $4 AND status = 'running' \
               AND runtime_revision = $5 AND runtime_lease_owner = $6 \
               AND runtime_lease_token = $7 \
               AND runtime_lease_expires_at > GREATEST($8, clock_timestamp()) \
               AND deadline_at > GREATEST($8, clock_timestamp()) FOR UPDATE",
        )
        .bind(&context.run_id)
        .bind(&context.job_id)
        .bind(&context.project_id)
        .bind(&context.conversation_id)
        .bind(lease.runtime_revision)
        .bind(&lease.lease_owner)
        .bind(&lease.lease_token)
        .bind(now)
        .fetch_optional(&mut **tx)
        .await
        .map_err(storage)?;
        if run.is_none() {
            return Ok(false);
        }
        let job = sqlx::query_scalar::<_, String>(
            "SELECT id FROM cron_jobs WHERE id = $1 AND tenant_id = $2 AND project_id = $3 FOR UPDATE",
        ).bind(&context.job_id).bind(&context.tenant_id).bind(&context.project_id)
            .fetch_optional(&mut **tx).await.map_err(storage)?;
        if job.is_none() {
            return Ok(false);
        }
        let operation = sqlx::query_scalar::<_, String>(
            "SELECT id FROM agistack_cron_operations \
             WHERE run_id = $1 AND job_id = $2 AND tenant_id = $3 AND project_id = $4 \
               AND operation_kind = 'execute_run' AND status = 'waiting_runtime' \
               AND COALESCE(actor_user_id, (SELECT created_by FROM cron_jobs WHERE id = $2)) = $5 \
               AND actor_api_key_id IS NOT DISTINCT FROM $6 FOR UPDATE",
        )
        .bind(&context.run_id)
        .bind(&context.job_id)
        .bind(&context.tenant_id)
        .bind(&context.project_id)
        .bind(&context.actor_user_id)
        .bind(&context.actor_api_key_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(storage)?;
        Ok(operation.is_some())
    }

    pub async fn mark_waiting_human(
        &self,
        observed_at: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError> {
        let mut tx = self.pool.begin().await.map_err(storage)?;
        if !self.lock_authority(&mut tx, observed_at).await? {
            return Ok(false);
        }
        let changed = sqlx::query(
            "UPDATE cron_job_runs SET status = 'waiting_human', runtime_lease_owner = NULL, \
                 runtime_lease_token = NULL, runtime_lease_expires_at = NULL, last_heartbeat_at = $2 \
             WHERE id = $1 AND runtime_lease_expires_at > GREATEST($2, clock_timestamp()) \
               AND deadline_at > GREATEST($2, clock_timestamp())",
        ).bind(&self.lease.context.run_id).bind(observed_at)
            .execute(&mut *tx).await.map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(changed.rows_affected() == 1)
    }
}

#[async_trait]
impl CheckpointStore for PgAutomationRunPersistence {
    async fn save(&self, state: &SessionState) -> CoreResult<()> {
        if state.session_id != self.lease.context.run_id
            || state.project_id.as_deref() != Some(self.lease.context.project_id.as_str())
        {
            return Err(checkpoint_denied());
        }
        let encoded = serde_json::to_value(state).map_err(|_| checkpoint_denied())?;
        let mut tx = self.pool.begin().await.map_err(|_| checkpoint_denied())?;
        if !self
            .lock_authority(&mut tx, Utc::now())
            .await
            .map_err(|_| checkpoint_denied())?
        {
            return Err(checkpoint_denied());
        }
        sqlx::query(
            "INSERT INTO agistack_checkpoints (session_id, state, updated_at) VALUES ($1, $2, now()) \
             ON CONFLICT (session_id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()",
        ).bind(&state.session_id).bind(encoded).execute(&mut *tx).await.map_err(|_| checkpoint_denied())?;
        // A checkpoint row lock may have delayed this write past lease expiry.
        // Recheck before commit; failure rolls the entire transaction back.
        if !self
            .lock_authority(&mut tx, Utc::now())
            .await
            .map_err(|_| checkpoint_denied())?
        {
            return Err(checkpoint_denied());
        }
        tx.commit().await.map_err(|_| checkpoint_denied())?;
        Ok(())
    }

    async fn load(&self, session_id: &str) -> CoreResult<Option<SessionState>> {
        if session_id != self.lease.context.run_id {
            return Err(checkpoint_denied());
        }
        let mut tx = self.pool.begin().await.map_err(|_| checkpoint_denied())?;
        if !self
            .lock_authority(&mut tx, Utc::now())
            .await
            .map_err(|_| checkpoint_denied())?
        {
            return Err(checkpoint_denied());
        }
        let row = sqlx::query_scalar::<_, Value>(
            "SELECT state FROM agistack_checkpoints WHERE session_id = $1",
        )
        .bind(session_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| checkpoint_denied())?;
        let state = row
            .map(serde_json::from_value::<SessionState>)
            .transpose()
            .map_err(|_| checkpoint_denied())?;
        if state.as_ref().is_some_and(|state| {
            state.session_id != session_id
                || state.project_id.as_deref() != Some(self.lease.context.project_id.as_str())
        }) {
            return Err(checkpoint_denied());
        }
        if !self
            .lock_authority(&mut tx, Utc::now())
            .await
            .map_err(|_| checkpoint_denied())?
        {
            return Err(checkpoint_denied());
        }
        tx.commit().await.map_err(|_| checkpoint_denied())?;
        Ok(state)
    }

    async fn delete(&self, _session_id: &str) -> CoreResult<()> {
        // Runtime execution never owns checkpoint retention or deletion.
        Err(checkpoint_denied())
    }
}

fn checkpoint_denied() -> CoreError {
    CoreError::Checkpoint(
        "automation checkpoint access was denied or could not be persisted".into(),
    )
}

fn storage(_error: sqlx::Error) -> AutomationRuntimeRepositoryError {
    AutomationRuntimeRepositoryError::Storage("automation run persistence failed".into())
}
