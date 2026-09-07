use chrono::{DateTime, Utc};
use sqlx::{Postgres, Transaction};

use super::storage;
use crate::{AutomationHitlAdmissionCommand, AutomationRuntimeRepositoryError};

pub(super) async fn lock_scope(
    tx: &mut Transaction<'_, Postgres>,
    s: &AutomationHitlAdmissionCommand,
    now: DateTime<Utc>,
) -> Result<Option<(String, Option<String>)>, AutomationRuntimeRepositoryError> {
    if s.expected_runtime_revision <= 0
        || [
            &s.run_id,
            &s.job_id,
            &s.project_id,
            &s.tenant_id,
            &s.conversation_id,
            &s.request_id,
        ]
        .iter()
        .any(|value| value.trim().is_empty())
    {
        return Ok(None);
    }
    let run = sqlx::query_scalar::<_, String>(
        "SELECT id FROM cron_job_runs WHERE id=$1 AND runtime_execution_id=$1
        AND job_id=$2 AND project_id=$3 AND conversation_id=$4 AND runtime_revision=$5
        AND status='waiting_human' AND deadline_at > GREATEST($6,clock_timestamp()) FOR UPDATE",
    )
    .bind(&s.run_id)
    .bind(&s.job_id)
    .bind(&s.project_id)
    .bind(&s.conversation_id)
    .bind(s.expected_runtime_revision)
    .bind(now)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    if run.is_none() {
        return Ok(None);
    }
    let job = sqlx::query_scalar::<_, String>(
        "SELECT id FROM cron_jobs WHERE id=$1 AND tenant_id=$2 AND project_id=$3 FOR UPDATE",
    )
    .bind(&s.job_id)
    .bind(&s.tenant_id)
    .bind(&s.project_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    if job.is_none() {
        return Ok(None);
    }
    let authority = sqlx::query_as::<_, (String, Option<String>)>("SELECT COALESCE(actor_user_id,(SELECT created_by FROM cron_jobs WHERE id=$2)),actor_api_key_id
        FROM agistack_cron_operations WHERE run_id=$1 AND job_id=$2 AND tenant_id=$3 AND project_id=$4
        AND operation_kind='execute_run' AND status='waiting_runtime' FOR UPDATE")
        .bind(&s.run_id).bind(&s.job_id).bind(&s.tenant_id).bind(&s.project_id)
        .fetch_optional(&mut **tx).await.map_err(storage)?;
    let Some((actor, key)) = authority else {
        return Ok(None);
    };
    if !lock_actor_authority(tx, s, &actor, key.as_deref(), now).await? {
        return Ok(None);
    }
    Ok(Some((actor, key)))
}

pub(super) async fn lock_actor_authority(
    tx: &mut Transaction<'_, Postgres>,
    s: &AutomationHitlAdmissionCommand,
    actor: &str,
    key: Option<&str>,
    now: DateTime<Utc>,
) -> Result<bool, AutomationRuntimeRepositoryError> {
    if !lock_membership(tx, s, actor, true).await? {
        return Ok(false);
    }
    let Some(key) = key else { return Ok(true) };
    // The key id and owner came from the locked operation, never from the answer.
    // Existing auth defines no project/scope grammar for api_keys.permissions.
    let valid_key = sqlx::query_scalar::<_, String>(
        "SELECT id FROM api_keys WHERE id=$1 AND user_id=$2 AND is_active
        AND (expires_at IS NULL OR expires_at > GREATEST($3,clock_timestamp())) FOR SHARE",
    )
    .bind(key)
    .bind(actor)
    .bind(now)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(valid_key.is_some())
}

pub(super) async fn lock_request(
    tx: &mut Transaction<'_, Postgres>,
    s: &AutomationHitlAdmissionCommand,
    responder: Option<&str>,
    permit_answered: bool,
    now: DateTime<Utc>,
) -> Result<bool, AutomationRuntimeRepositoryError> {
    let request = sqlx::query_as::<_, (String, Option<String>)>("SELECT id,user_id FROM hitl_requests WHERE id=$1 AND tenant_id=$2 AND project_id=$3
        AND message_id=$4 AND conversation_id=$5 AND request_type='permission'
        AND (status='pending' OR ($6 AND status='answered')) AND expires_at > GREATEST($7,clock_timestamp())
        AND ($8::text IS NULL OR user_id IS NULL OR user_id=$8)
        AND request_metadata ->> 'automation_run_id'=$4
        AND request_metadata ->> 'runtime_execution_id'=$4
        AND request_metadata ->> 'checkpoint_session_id'=$4 FOR UPDATE")
        .bind(&s.request_id).bind(&s.tenant_id).bind(&s.project_id).bind(&s.run_id)
        .bind(&s.conversation_id).bind(permit_answered).bind(now).bind(responder)
        .fetch_optional(&mut **tx).await.map_err(storage)?;
    let Some((_, expected_user)) = request else {
        return Ok(false);
    };
    if let Some(responder) = responder.filter(|_| expected_user.is_none()) {
        // Preserve the existing HITL audience rule when no user was assigned.
        let owner = sqlx::query_scalar::<_, String>(
            "SELECT id FROM conversations WHERE id=$1 AND tenant_id=$2 AND user_id=$3 FOR SHARE",
        )
        .bind(&s.conversation_id)
        .bind(&s.tenant_id)
        .bind(responder)
        .fetch_optional(&mut **tx)
        .await
        .map_err(storage)?;
        if owner.is_none() {
            return Ok(false);
        }
    }
    let checkpoint = sqlx::query_scalar::<_, String>(
        "SELECT session_id FROM agistack_checkpoints WHERE session_id=$1
        AND state ->> 'session_id'=$1 AND state ->> 'project_id'=$2
        AND state ->> 'status'='awaiting_input'
        AND state -> 'pending_hitl' ->> 'id'=$3
        AND state -> 'pending_hitl' ->> 'kind'='permission' FOR UPDATE",
    )
    .bind(&s.run_id)
    .bind(&s.project_id)
    .bind(&s.request_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(checkpoint.is_some())
}

pub(super) async fn lock_membership(
    tx: &mut Transaction<'_, Postgres>,
    s: &AutomationHitlAdmissionCommand,
    user: &str,
    require_write: bool,
) -> Result<bool, AutomationRuntimeRepositoryError> {
    // SHARE, not KEY SHARE: both role updates and revocation serialize with admission.
    let active_user =
        sqlx::query_scalar::<_, String>("SELECT id FROM users WHERE id=$1 AND is_active FOR SHARE")
            .bind(user)
            .fetch_optional(&mut **tx)
            .await
            .map_err(storage)?;
    let scoped_project = sqlx::query_scalar::<_, String>(
        "SELECT owner_id FROM projects WHERE id=$1 AND tenant_id=$2 FOR SHARE",
    )
    .bind(&s.project_id)
    .bind(&s.tenant_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    let tenant = sqlx::query_scalar::<_, String>(
        "SELECT user_id FROM user_tenants WHERE user_id=$1 AND tenant_id=$2 FOR SHARE",
    )
    .bind(user)
    .bind(&s.tenant_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    let project = sqlx::query_scalar::<_, String>(
        "SELECT user_id FROM user_projects WHERE user_id=$1 AND project_id=$2
         AND (NOT $3 OR role <> 'viewer' OR $4) FOR SHARE",
    )
    .bind(user)
    .bind(&s.project_id)
    .bind(require_write)
    .bind(scoped_project.as_deref() == Some(user))
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(active_user.is_some() && scoped_project.is_some() && tenant.is_some() && project.is_some())
}

/// Recheck time after all potentially blocking writes, without widening locks.
/// INSERT/UPDATE predicates may have been evaluated before a trigger or wait.
pub(super) async fn receipt_scope_is_current(
    tx: &mut Transaction<'_, Postgres>,
    s: &AutomationHitlAdmissionCommand,
    intent_id: &str,
    hitl_status: &str,
    now: DateTime<Utc>,
) -> Result<bool, AutomationRuntimeRepositoryError> {
    sqlx::query_scalar("SELECT EXISTS (
        SELECT 1 FROM cron_job_runs r
        JOIN cron_jobs j ON j.id=r.job_id
        JOIN agistack_cron_operations o ON o.run_id=r.id AND o.job_id=j.id
        JOIN hitl_requests h ON h.id=$6 AND h.message_id=r.id
        JOIN agistack_automation_permission_intents i ON i.id=$7 AND i.request_id=h.id
        JOIN agistack_checkpoints c ON c.session_id=r.id
        LEFT JOIN api_keys k ON k.id=o.actor_api_key_id
        WHERE r.id=$1 AND r.runtime_execution_id=$1 AND r.job_id=$2 AND r.project_id=$3
          AND r.conversation_id=$4 AND r.runtime_revision=$5 AND r.status='waiting_human'
          AND j.tenant_id=$8 AND j.project_id=$3
          AND o.tenant_id=$8 AND o.project_id=$3 AND o.operation_kind='execute_run' AND o.status='waiting_runtime'
          AND i.actor_user_id=COALESCE(o.actor_user_id,j.created_by)
          AND i.actor_api_key_id IS NOT DISTINCT FROM o.actor_api_key_id
          AND (o.actor_api_key_id IS NULL OR (k.user_id=i.actor_user_id AND k.is_active
            AND (k.expires_at IS NULL OR k.expires_at > GREATEST($10,clock_timestamp()))))
          AND h.tenant_id=$8 AND h.project_id=$3 AND h.conversation_id=$4
          AND h.request_type='permission' AND h.status=$9
          AND i.tenant_id=$8 AND i.project_id=$3 AND i.run_id=$1 AND i.job_id=$2
          AND i.conversation_id=$4 AND i.runtime_revision=$5
          AND c.state ->> 'session_id'=$1 AND c.state ->> 'project_id'=$3
          AND c.state ->> 'status'='awaiting_input'
          AND c.state -> 'pending_hitl' ->> 'id'=$6
          AND c.state -> 'pending_hitl' ->> 'kind'='permission'
          AND r.deadline_at > GREATEST($10,clock_timestamp())
          AND h.expires_at > GREATEST($10,clock_timestamp())
          AND i.expires_at > GREATEST($10,clock_timestamp()))")
        .bind(&s.run_id).bind(&s.job_id).bind(&s.project_id).bind(&s.conversation_id)
        .bind(s.expected_runtime_revision).bind(&s.request_id).bind(intent_id)
        .bind(&s.tenant_id).bind(hitl_status).bind(now)
        .fetch_one(&mut **tx).await.map_err(storage)
}
