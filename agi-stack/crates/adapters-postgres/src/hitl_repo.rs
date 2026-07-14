//! Shared-DB adapter for Python-owned `hitl_requests`.
//!
//! This repository intentionally mirrors the production HITL response path used
//! by Python: load the persisted request, enforce tenant/project/conversation
//! access, atomically mark a pending request answered, and leave Redis stream
//! delivery to the server layer's `EventStream`.

use serde_json::Value;
use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

#[derive(Debug, Clone)]
pub struct HitlRequestRecord {
    pub id: String,
    pub request_type: String,
    pub conversation_id: String,
    pub message_id: Option<String>,
    pub tenant_id: String,
    pub project_id: String,
    pub user_id: Option<String>,
    pub question: String,
    pub options: Option<Value>,
    pub context: Option<Value>,
    pub request_metadata: Option<Value>,
    pub status: String,
    pub response: Option<String>,
    pub response_metadata: Option<Value>,
    pub expires_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct NewHitlRequestRecord {
    pub id: String,
    pub request_type: String,
    pub conversation_id: String,
    pub message_id: Option<String>,
    pub tenant_id: String,
    pub project_id: String,
    pub user_id: Option<String>,
    pub question: String,
    pub options: Option<Value>,
    pub context: Option<Value>,
    pub request_metadata: Option<Value>,
    pub expires_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AutomationHitlResumeCandidate {
    pub request_id: String,
    pub request_type: String,
    pub tenant_id: String,
    pub project_id: String,
    pub conversation_id: String,
    pub run_id: String,
    pub checkpoint_session_id: String,
    pub answer: String,
}

impl HitlRequestRecord {
    pub fn is_expired_at(&self, now: DateTime<Utc>) -> bool {
        self.expires_at.is_some_and(|expires_at| expires_at <= now)
    }
}

pub struct PgHitlRequestRepository {
    pool: PgPool,
}

impl PgHitlRequestRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Insert one pending request without reopening an answered replay.
    ///
    /// Returns `true` when inserted and `false` for an exact idempotent replay.
    pub async fn insert_pending(&self, request: &NewHitlRequestRecord) -> CoreResult<bool> {
        let result = sqlx::query(
            "INSERT INTO hitl_requests \
                (id, request_type, conversation_id, message_id, tenant_id, project_id, user_id, \
                 question, options, context, request_metadata, status, expires_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending', $12) \
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
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        if result.rows_affected() == 1 {
            return Ok(true);
        }

        let existing = self
            .get_by_id(&request.id)
            .await?
            .ok_or_else(|| CoreError::Storage("HITL insert conflict disappeared".to_string()))?;
        if same_request(&existing, request) {
            Ok(false)
        } else {
            Err(CoreError::Storage(
                "HITL request id conflicts with another request".to_string(),
            ))
        }
    }

    pub async fn get_by_id(&self, request_id: &str) -> CoreResult<Option<HitlRequestRecord>> {
        sqlx::query_as::<_, HitlRequestRow>(
            "SELECT id, request_type, conversation_id, message_id, tenant_id, project_id, \
                    user_id, question, options, context, request_metadata, status, response, \
                    response_metadata, expires_at \
             FROM hitl_requests WHERE id = $1",
        )
        .bind(request_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(Into::into))
        .map_err(storage)
    }

    pub async fn get_by_conversation(
        &self,
        conversation_id: &str,
    ) -> CoreResult<Vec<HitlRequestRecord>> {
        sqlx::query_as::<_, HitlRequestRow>(
            "SELECT id, request_type, conversation_id, message_id, tenant_id, project_id, \
                    user_id, question, options, context, request_metadata, status, response, \
                    response_metadata, expires_at \
             FROM hitl_requests \
             WHERE conversation_id = $1 \
             ORDER BY created_at ASC, id ASC",
        )
        .bind(conversation_id)
        .fetch_all(&self.pool)
        .await
        .map(|rows| rows.into_iter().map(Into::into).collect())
        .map_err(storage)
    }

    /// List answered non-secret automation requests whose run still awaits resume.
    pub async fn list_automation_resume_candidates(
        &self,
        tenant_id: &str,
        project_id: &str,
        limit: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<AutomationHitlResumeCandidate>> {
        sqlx::query_as::<_, AutomationHitlResumeRow>(
            "SELECT hitl.id AS request_id, hitl.request_type, hitl.tenant_id, \
                    hitl.project_id, hitl.conversation_id, run.id AS run_id, \
                    hitl.request_metadata ->> 'checkpoint_session_id' \
                        AS checkpoint_session_id, \
                    hitl.response_metadata ->> 'resume_answer' AS answer \
             FROM hitl_requests AS hitl \
             JOIN cron_job_runs AS run \
               ON run.id = hitl.message_id \
              AND run.runtime_execution_id = run.id \
              AND run.conversation_id = hitl.conversation_id \
             JOIN cron_jobs AS job ON job.id = run.job_id \
             JOIN agistack_cron_operations AS operation \
               ON operation.run_id = run.id \
              AND operation.operation_kind = 'execute_run' \
             WHERE hitl.tenant_id = $1 AND hitl.project_id = $2 \
               AND hitl.status = 'answered' \
               AND hitl.request_type IN ('clarification', 'decision', 'permission') \
               AND hitl.expires_at > $3 \
               AND hitl.request_metadata ->> 'automation_run_id' = run.id \
               AND hitl.request_metadata ->> 'runtime_execution_id' = run.id \
               AND hitl.request_metadata ->> 'checkpoint_session_id' = run.id \
               AND hitl.response_metadata ->> 'resume_answer' IS NOT NULL \
               AND run.project_id = hitl.project_id \
               AND run.status = 'waiting_human' \
               AND run.deadline_at IS NOT NULL AND run.deadline_at > $3 \
               AND job.tenant_id = hitl.tenant_id AND job.project_id = hitl.project_id \
               AND operation.tenant_id = hitl.tenant_id \
               AND operation.project_id = hitl.project_id \
               AND operation.status = 'waiting_runtime' \
             ORDER BY hitl.answered_at, hitl.id LIMIT $4",
        )
        .bind(tenant_id)
        .bind(project_id)
        .bind(now)
        .bind(limit.clamp(1, 100))
        .fetch_all(&self.pool)
        .await
        .map(|rows| rows.into_iter().map(Into::into).collect())
        .map_err(storage)
    }

    pub async fn user_has_tenant_access(&self, user_id: &str, tenant_id: &str) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(storage)
    }

    pub async fn user_has_project_access(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects WHERE user_id = $1 AND project_id = $2",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(storage)
    }

    pub async fn user_has_conversation_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        conversation_id: &str,
    ) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM conversations \
             WHERE id = $1 AND tenant_id = $2 AND user_id = $3",
        )
        .bind(conversation_id)
        .bind(tenant_id)
        .bind(user_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(storage)
    }

    pub async fn mark_timeout(&self, request_id: &str) -> CoreResult<bool> {
        sqlx::query(
            "UPDATE hitl_requests SET status = 'timeout' \
             WHERE id = $1 AND status = 'pending'",
        )
        .bind(request_id)
        .execute(&self.pool)
        .await
        .map(|result| result.rows_affected() > 0)
        .map_err(storage)
    }

    pub async fn update_response(
        &self,
        request_id: &str,
        response: &str,
        response_metadata: Option<&Value>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        sqlx::query(
            "UPDATE hitl_requests \
             SET status = 'answered', response = $2, response_metadata = $3, answered_at = $4 \
             WHERE id = $1 \
               AND status = 'pending' \
               AND (expires_at IS NULL OR expires_at > $4)",
        )
        .bind(request_id)
        .bind(response)
        .bind(response_metadata)
        .bind(now)
        .execute(&self.pool)
        .await
        .map(|result| result.rows_affected() > 0)
        .map_err(storage)
    }
}

fn same_request(existing: &HitlRequestRecord, request: &NewHitlRequestRecord) -> bool {
    existing.request_type == request.request_type
        && existing.conversation_id == request.conversation_id
        && existing.message_id == request.message_id
        && existing.tenant_id == request.tenant_id
        && existing.project_id == request.project_id
        && existing.user_id == request.user_id
        && existing.question == request.question
        && existing.options == request.options
        && existing.context == request.context
        && existing.request_metadata == request.request_metadata
        && existing.expires_at == Some(request.expires_at)
}

#[derive(sqlx::FromRow)]
struct HitlRequestRow {
    id: String,
    request_type: String,
    conversation_id: String,
    message_id: Option<String>,
    tenant_id: String,
    project_id: String,
    user_id: Option<String>,
    question: String,
    options: Option<Value>,
    context: Option<Value>,
    request_metadata: Option<Value>,
    status: String,
    response: Option<String>,
    response_metadata: Option<Value>,
    expires_at: Option<DateTime<Utc>>,
}

#[derive(sqlx::FromRow)]
struct AutomationHitlResumeRow {
    request_id: String,
    request_type: String,
    tenant_id: String,
    project_id: String,
    conversation_id: String,
    run_id: String,
    checkpoint_session_id: String,
    answer: String,
}

impl From<HitlRequestRow> for HitlRequestRecord {
    fn from(row: HitlRequestRow) -> Self {
        Self {
            id: row.id,
            request_type: row.request_type,
            conversation_id: row.conversation_id,
            message_id: row.message_id,
            tenant_id: row.tenant_id,
            project_id: row.project_id,
            user_id: row.user_id,
            question: row.question,
            options: row.options,
            context: row.context,
            request_metadata: row.request_metadata,
            status: row.status,
            response: row.response,
            response_metadata: row.response_metadata,
            expires_at: row.expires_at,
        }
    }
}

impl From<AutomationHitlResumeRow> for AutomationHitlResumeCandidate {
    fn from(row: AutomationHitlResumeRow) -> Self {
        Self {
            request_id: row.request_id,
            request_type: row.request_type,
            tenant_id: row.tenant_id,
            project_id: row.project_id,
            conversation_id: row.conversation_id,
            run_id: row.run_id,
            checkpoint_session_id: row.checkpoint_session_id,
            answer: row.answer,
        }
    }
}

fn storage(err: sqlx::Error) -> CoreError {
    CoreError::Storage(err.to_string())
}
