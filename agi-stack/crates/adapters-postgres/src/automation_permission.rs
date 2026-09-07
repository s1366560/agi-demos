//! Persist exact permission intent and atomically admit an answer. No dispatch.

mod locking;

use agistack_core::{
    automation_permission::{HostPermissionBinding, PermissionAnswer},
    DecisionContext,
};
use chrono::{DateTime, Utc};
use serde_json::Value;

use crate::{AutomationHitlAdmissionCommand, AutomationRuntimeRepositoryError, PgPool};

pub struct AutomationPermissionIntentCommand {
    pub id: String,
    pub scope: AutomationHitlAdmissionCommand,
    pub binding: Option<HostPermissionBinding>,
    pub decision: DecisionContext,
    pub expires_at: DateTime<Utc>,
}

pub struct AutomationPermissionAnswerCommand {
    pub intent_id: String,
    pub scope: AutomationHitlAdmissionCommand,
    pub responder_user_id: String,
    pub idempotency_key: String,
    pub answer: PermissionAnswer,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AutomationPermissionOutcome {
    /// A receipt was committed. This is not dispatch eligibility or a reservation.
    Applied,
    /// The same receipt exists. Replay never resets a consumed or revoked ledger.
    Replayed,
    NotAdmitted,
}

#[derive(Clone)]
pub struct PgAutomationPermissionStore {
    pool: PgPool,
}

impl PgAutomationPermissionStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn record_intent(
        &self,
        command: &AutomationPermissionIntentCommand,
        now: DateTime<Utc>,
    ) -> Result<AutomationPermissionOutcome, AutomationRuntimeRepositoryError> {
        let Some(binding) = command.binding.as_ref() else {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        };
        if command.id.trim().is_empty()
            || !command.decision.is_complete()
            || command.expires_at <= now
        {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let Some((actor, api_key)) = locking::lock_scope(&mut tx, &command.scope, now).await?
        else {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        };
        if !locking::lock_request(&mut tx, &command.scope, None, false, now).await? {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        let decision = serde_json::to_value(&command.decision)
            .map_err(|_| AutomationRuntimeRepositoryError::InvalidRunState)?;
        let s = &command.scope;
        let inserted = sqlx::query(
            "INSERT INTO agistack_automation_permission_intents
            (id, request_id, tenant_id, project_id, job_id, run_id, conversation_id,
             actor_user_id, actor_api_key_id, runtime_revision, invocation_id, tool_name,
             tool_version, input_sha256, decision_context, created_at, expires_at)
            SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                GREATEST($16, clock_timestamp()), $17
            WHERE $17 > GREATEST($16, clock_timestamp())
              AND $17 <= (SELECT expires_at FROM hitl_requests WHERE id=$2)
              AND $17 <= (SELECT deadline_at FROM cron_job_runs WHERE id=$6)
            ON CONFLICT DO NOTHING",
        )
        .bind(&command.id)
        .bind(&s.request_id)
        .bind(&s.tenant_id)
        .bind(&s.project_id)
        .bind(&s.job_id)
        .bind(&s.run_id)
        .bind(&s.conversation_id)
        .bind(&actor)
        .bind(&api_key)
        .bind(s.expected_runtime_revision)
        .bind(binding.invocation_id())
        .bind(binding.tool_name())
        .bind(binding.tool_version())
        .bind(binding.input_sha256())
        .bind(decision)
        .bind(now)
        .bind(command.expires_at)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        if inserted.rows_affected() != 1 {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        if !locking::lock_actor_authority(&mut tx, s, &actor, api_key.as_deref(), now).await? {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        if !locking::receipt_scope_is_current(&mut tx, s, &command.id, "pending", now).await? {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        tx.commit().await.map_err(storage)?;
        Ok(AutomationPermissionOutcome::Applied)
    }

    pub async fn answer(
        &self,
        command: &AutomationPermissionAnswerCommand,
        now: DateTime<Utc>,
    ) -> Result<AutomationPermissionOutcome, AutomationRuntimeRepositoryError> {
        if [
            &command.intent_id,
            &command.responder_user_id,
            &command.idempotency_key,
        ]
        .iter()
        .any(|value| value.trim().is_empty())
            || command.idempotency_key.len() > 255
        {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let Some((actor, api_key)) = locking::lock_scope(&mut tx, &command.scope, now).await?
        else {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        };
        if !locking::lock_request(
            &mut tx,
            &command.scope,
            Some(&command.responder_user_id),
            true,
            now,
        )
        .await?
            || !locking::lock_membership(
                &mut tx,
                &command.scope,
                &command.responder_user_id,
                command.answer == PermissionAnswer::AllowOnce,
            )
            .await?
        {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        let s = &command.scope;
        let invocation = sqlx::query_scalar::<_, String>(
            "SELECT invocation_id FROM agistack_automation_permission_intents
            WHERE id=$1 AND request_id=$2 AND tenant_id=$3 AND project_id=$4 AND job_id=$5
              AND run_id=$6 AND conversation_id=$7 AND runtime_revision=$8
              AND actor_user_id=$9 AND actor_api_key_id IS NOT DISTINCT FROM $10
              AND expires_at > GREATEST($11, clock_timestamp()) FOR UPDATE",
        )
        .bind(&command.intent_id)
        .bind(&s.request_id)
        .bind(&s.tenant_id)
        .bind(&s.project_id)
        .bind(&s.job_id)
        .bind(&s.run_id)
        .bind(&s.conversation_id)
        .bind(s.expected_runtime_revision)
        .bind(&actor)
        .bind(&api_key)
        .bind(now)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?;
        let Some(invocation) = invocation else {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        };
        let prior = sqlx::query_as::<_, (String,String,String)>("SELECT responder_user_id,idempotency_key,answer FROM agistack_automation_permission_receipts WHERE intent_id=$1")
            .bind(&command.intent_id).fetch_optional(&mut *tx).await.map_err(storage)?;
        if let Some(prior) = prior {
            if !locking::lock_actor_authority(&mut tx, s, &actor, api_key.as_deref(), now).await? {
                return Ok(AutomationPermissionOutcome::NotAdmitted);
            }
            if !locking::receipt_scope_is_current(&mut tx, s, &command.intent_id, "answered", now)
                .await?
            {
                return Ok(AutomationPermissionOutcome::NotAdmitted);
            }
            return Ok(
                if prior
                    == (
                        command.responder_user_id.clone(),
                        command.idempotency_key.clone(),
                        command.answer.as_str().to_owned(),
                    )
                {
                    AutomationPermissionOutcome::Replayed
                } else {
                    AutomationPermissionOutcome::NotAdmitted
                },
            );
        }
        let receipt = sqlx::query(
            "INSERT INTO agistack_automation_permission_receipts
            (intent_id,responder_user_id,idempotency_key,answer,authority_revision,accepted_at)
            VALUES ($1,$2,$3,$4,$5,GREATEST($6,clock_timestamp())) ON CONFLICT DO NOTHING",
        )
        .bind(&command.intent_id)
        .bind(&command.responder_user_id)
        .bind(&command.idempotency_key)
        .bind(command.answer.as_str())
        .bind(s.expected_runtime_revision)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        if receipt.rows_affected() != 1 {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        if command.answer == PermissionAnswer::AllowOnce {
            sqlx::query(
                "INSERT INTO agistack_automation_permission_consumptions
                (intent_id,invocation_id,status,max_uses,use_count,updated_at)
                VALUES ($1,$2,'awaiting_dispatch_binding',1,0,GREATEST($3,clock_timestamp()))",
            )
            .bind(&command.intent_id)
            .bind(invocation)
            .bind(now)
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        }
        // Deliberately no resume_answer: a permission receipt is not chat text.
        let metadata: Value = serde_json::json!({"permission_intent_id": command.intent_id, "permission_answer": command.answer});
        let updated = sqlx::query("UPDATE hitl_requests SET status='answered', answered_at=GREATEST($2,clock_timestamp()), response_metadata=$3
            WHERE id=$1 AND status='pending' AND expires_at > GREATEST($2,clock_timestamp())
              AND EXISTS (SELECT 1 FROM cron_job_runs WHERE id=$4 AND deadline_at > GREATEST($2,clock_timestamp()))
              AND EXISTS (SELECT 1 FROM agistack_automation_permission_intents WHERE id=$5 AND expires_at > GREATEST($2,clock_timestamp()))")
            .bind(&s.request_id).bind(now).bind(metadata).bind(&s.run_id).bind(&command.intent_id)
            .execute(&mut *tx).await.map_err(storage)?;
        if updated.rows_affected() != 1 {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        if !locking::lock_actor_authority(&mut tx, s, &actor, api_key.as_deref(), now).await? {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        if !locking::receipt_scope_is_current(&mut tx, s, &command.intent_id, "answered", now)
            .await?
        {
            return Ok(AutomationPermissionOutcome::NotAdmitted);
        }
        tx.commit().await.map_err(storage)?;
        Ok(AutomationPermissionOutcome::Applied)
    }
}

fn storage(_: sqlx::Error) -> AutomationRuntimeRepositoryError {
    AutomationRuntimeRepositoryError::Storage("automation permission persistence failed".into())
}
