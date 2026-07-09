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

fn storage(err: sqlx::Error) -> CoreError {
    CoreError::Storage(err.to_string())
}
