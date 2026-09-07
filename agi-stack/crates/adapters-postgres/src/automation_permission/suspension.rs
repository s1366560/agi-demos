//! A producer boundary: all four durable effects commit under the running lease.
use agistack_core::{
    automation_permission::HostPermissionBinding, HitlKind, SessionState, SessionStatus,
};
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::{
    locking, storage, AutomationPermissionOutcome as Outcome, PgAutomationPermissionStore,
};
use crate::{
    AutomationHitlAdmissionCommand, AutomationRunLease, AutomationRuntimeRepositoryError as Error,
    PgAutomationRunPersistence,
};

/// Host-only command; no deserialization path for the binding or execution lease.
pub struct AutomationPermissionSuspensionCommand {
    pub intent_id: String,
    pub binding: HostPermissionBinding,
    pub state: SessionState,
    pub expires_at: DateTime<Utc>,
}

impl PgAutomationPermissionStore {
    pub async fn suspend_with_lease(
        &self,
        lease: &AutomationRunLease,
        command: &AutomationPermissionSuspensionCommand,
        now: DateTime<Utc>,
    ) -> Result<Outcome, Error> {
        let c = &lease.context;
        let state = &command.state;
        let Some(request) = state.pending_hitl.as_ref() else {
            return Ok(Outcome::NotAdmitted);
        };
        let Some(proposal) = request.permission_invocation.as_ref() else {
            return Ok(Outcome::NotAdmitted);
        };
        let Some(decision) = request.decision.as_ref() else {
            return Ok(Outcome::NotAdmitted);
        };
        let canonical = serde_jcs::to_vec(&proposal.input).map_err(|_| Error::InvalidRunState)?;
        if state.session_id != c.run_id
            || state.project_id.as_deref() != Some(c.project_id.as_str())
            || state.status != SessionStatus::AwaitingInput
            || request.kind != HitlKind::Permission
            || request.id.trim().is_empty()
            || request.prompt.trim().is_empty()
            || command.intent_id.trim().is_empty()
            || !decision.is_complete()
            || decision.action.name != proposal.tool
            || proposal.tool != command.binding.tool_name()
            || format!("{:x}", Sha256::digest(canonical)) != command.binding.input_sha256()
            || state.hitl_answer(&request.id).is_some()
            || command.expires_at <= now
        {
            return Ok(Outcome::NotAdmitted);
        }
        let s = AutomationHitlAdmissionCommand {
            tenant_id: c.tenant_id.clone(),
            project_id: c.project_id.clone(),
            job_id: c.job_id.clone(),
            run_id: c.run_id.clone(),
            conversation_id: c.conversation_id.clone(),
            request_id: request.id.clone(),
            expected_runtime_revision: lease.runtime_revision,
        };
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let persistence = PgAutomationRunPersistence::new(self.pool.clone(), lease.clone());
        if !persistence.lock_authority(&mut tx, now).await?
            || !locking::lock_actor_authority(
                &mut tx,
                &s,
                &c.actor_user_id,
                c.actor_api_key_id.as_deref(),
                now,
            )
            .await?
        {
            return Ok(Outcome::NotAdmitted);
        }
        // Read the expiry currently held in PostgreSQL; heartbeat renewal can
        // make the immutable caller's expiry older than the real lease.
        let lease_cutoff: DateTime<Utc> =
            sqlx::query_scalar("SELECT runtime_lease_expires_at FROM cron_job_runs WHERE id=$1")
                .bind(&c.run_id)
                .fetch_one(&mut *tx)
                .await
                .map_err(storage)?;
        let prior: Option<Value> = sqlx::query_scalar(
            "SELECT state FROM agistack_checkpoints WHERE session_id=$1 FOR UPDATE",
        )
        .bind(&c.run_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?;
        if let Some(prior) = prior {
            let prior: SessionState =
                serde_json::from_value(prior).map_err(|_| Error::InvalidRunState)?;
            if prior.session_id != state.session_id
                || prior.project_id != state.project_id
                || prior.status != SessionStatus::Running
                || prior.round > state.round
                || prior.pending_hitl.is_some()
            {
                return Ok(Outcome::NotAdmitted);
            }
        }
        let metadata = json!({"automation_run_id": c.run_id, "runtime_execution_id": c.run_id,
            "checkpoint_session_id": c.run_id, "permission_intent_id": command.intent_id});
        let hitl = sqlx::query("INSERT INTO hitl_requests
            (id,request_type,conversation_id,message_id,tenant_id,project_id,user_id,
             question,context,request_metadata,status,expires_at)
            SELECT $1,'permission',$2,$3,$4,$5,$6,$7,$8,$9,'pending',$10
            FROM cron_job_runs WHERE id=$3 AND $10<=deadline_at AND $10>GREATEST($11,clock_timestamp())
            ON CONFLICT DO NOTHING")
            .bind(&request.id).bind(&c.conversation_id).bind(&c.run_id).bind(&c.tenant_id)
            .bind(&c.project_id).bind(&c.actor_user_id).bind(&request.prompt)
            .bind(serde_json::to_value(request).map_err(|_| Error::InvalidRunState)?)
            .bind(metadata).bind(command.expires_at).bind(now)
            .execute(&mut *tx).await.map_err(storage)?;
        if hitl.rows_affected() != 1 {
            return Ok(Outcome::NotAdmitted);
        }
        let b = &command.binding;
        let intent = sqlx::query("INSERT INTO agistack_automation_permission_intents
            (id,request_id,tenant_id,project_id,job_id,run_id,conversation_id,actor_user_id,actor_api_key_id,
             runtime_revision,invocation_id,tool_name,tool_version,input_sha256,decision_context,created_at,expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,GREATEST($16,clock_timestamp()),$17)
            ON CONFLICT DO NOTHING")
            .bind(&command.intent_id).bind(&request.id).bind(&c.tenant_id).bind(&c.project_id)
            .bind(&c.job_id).bind(&c.run_id).bind(&c.conversation_id).bind(&c.actor_user_id)
            .bind(&c.actor_api_key_id).bind(lease.runtime_revision).bind(b.invocation_id())
            .bind(b.tool_name()).bind(b.tool_version()).bind(b.input_sha256())
            .bind(serde_json::to_value(decision).map_err(|_| Error::InvalidRunState)?)
            .bind(now).bind(command.expires_at).execute(&mut *tx).await.map_err(storage)?;
        if intent.rows_affected() != 1 {
            return Ok(Outcome::NotAdmitted);
        }
        sqlx::query("INSERT INTO agistack_checkpoints (session_id,state,updated_at) VALUES ($1,$2,clock_timestamp())
            ON CONFLICT (session_id) DO UPDATE SET state=EXCLUDED.state,updated_at=EXCLUDED.updated_at")
            .bind(&c.run_id).bind(serde_json::to_value(state).map_err(|_| Error::InvalidRunState)?)
            .execute(&mut *tx).await.map_err(storage)?;
        let parked = sqlx::query("UPDATE cron_job_runs SET status='waiting_human',runtime_lease_owner=NULL,
            runtime_lease_token=NULL,runtime_lease_expires_at=NULL,last_heartbeat_at=GREATEST($5,clock_timestamp())
            WHERE id=$1 AND status='running' AND runtime_revision=$2 AND runtime_lease_owner=$3
            AND runtime_lease_token=$4 AND runtime_lease_expires_at>GREATEST($5,clock_timestamp())
            AND deadline_at>GREATEST($5,clock_timestamp())")
            .bind(&c.run_id).bind(lease.runtime_revision).bind(&lease.lease_owner).bind(&lease.lease_token)
            .bind(now).execute(&mut *tx).await.map_err(storage)?;
        if parked.rows_affected() != 1
            || !locking::receipt_scope_is_current(&mut tx, &s, &command.intent_id, "pending", now)
                .await?
        {
            return Ok(Outcome::NotAdmitted);
        }
        // The running lease columns have been cleared by parking. Retain their
        // locked pre-update value for the final post-write expiry check.
        let lease_current: bool = sqlx::query_scalar("SELECT $1>GREATEST($2,clock_timestamp())")
            .bind(lease_cutoff)
            .bind(now)
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if !lease_current {
            return Ok(Outcome::NotAdmitted);
        }
        tx.commit().await.map_err(storage)?;
        Ok(Outcome::Applied)
    }
}
