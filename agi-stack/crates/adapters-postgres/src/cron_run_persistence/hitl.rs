use agistack_core::ports::{CoreError, CoreResult};
use chrono::Utc;

use super::PgAutomationRunPersistence;
use crate::hitl_repo::{same_request, HitlRequestRow};
use crate::{HitlRequestRecord, NewHitlRequestRecord};

impl PgAutomationRunPersistence {
    pub async fn insert_pending(&self, request: &NewHitlRequestRecord) -> CoreResult<bool> {
        let context = &self.lease.context;
        let metadata = request.request_metadata.as_ref();
        if request.tenant_id != context.tenant_id
            || request.project_id != context.project_id
            || request.message_id.as_deref() != Some(context.run_id.as_str())
            || request.conversation_id != context.conversation_id
            || request.user_id.as_deref() != Some(context.actor_user_id.as_str())
            || request.expires_at > self.lease.deadline_at
            || !matches!(
                request.request_type.as_str(),
                "clarification" | "decision" | "permission" | "a2ui_action"
            )
            || ![
                "automation_run_id",
                "runtime_execution_id",
                "checkpoint_session_id",
            ]
            .iter()
            .all(|field| {
                metadata
                    .and_then(|metadata| metadata.get(field))
                    .and_then(|value| value.as_str())
                    == Some(context.run_id.as_str())
            })
        {
            return Err(denied());
        }
        let mut tx = self.pool.begin().await.map_err(|_| denied())?;
        if !self
            .lock_authority(&mut tx, Utc::now())
            .await
            .map_err(|_| denied())?
        {
            return Err(denied());
        }
        let result = sqlx::query(
            "INSERT INTO hitl_requests \
                (id, request_type, conversation_id, message_id, tenant_id, project_id, user_id, \
                 question, options, context, request_metadata, status, expires_at) \
             SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending', $12 \
             FROM cron_job_runs WHERE id = $4 AND $12 <= deadline_at AND $12 > clock_timestamp() \
             ON CONFLICT (id) DO NOTHING",
        )
        .bind(&request.id)
        .bind(&request.request_type)
        .bind(&request.conversation_id)
        .bind(&request.message_id)
        .bind(&request.tenant_id)
        .bind(&request.project_id)
        .bind(&request.user_id)
        .bind(&request.question)
        .bind(&request.options)
        .bind(&request.context)
        .bind(&request.request_metadata)
        .bind(request.expires_at)
        .execute(&mut *tx)
        .await
        .map_err(|_| denied())?;
        let inserted = result.rows_affected() == 1;
        if !inserted {
            let existing: HitlRequestRecord = sqlx::query_as::<_, HitlRequestRow>(
                "SELECT id, request_type, conversation_id, message_id, tenant_id, project_id, user_id, \
                        question, options, context, request_metadata, status, response, \
                        response_metadata, expires_at FROM hitl_requests WHERE id = $1 FOR UPDATE",
            ).bind(&request.id).fetch_one(&mut *tx).await.map_err(|_| denied())?.into();
            if !same_request(&existing, request) {
                return Err(denied());
            }
        }
        if !self
            .lock_authority(&mut tx, Utc::now())
            .await
            .map_err(|_| denied())?
        {
            return Err(denied());
        }
        tx.commit().await.map_err(|_| denied())?;
        Ok(inserted)
    }
}

fn denied() -> CoreError {
    CoreError::Storage("automation HITL write was denied or could not be persisted".into())
}
