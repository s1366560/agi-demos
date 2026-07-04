use serde_json::Value;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::FromRow;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConversationReplayAccess {
    Allowed,
    Denied,
    NotFound,
}

#[derive(Debug, Clone, Copy)]
pub struct AgentExecutionEventListQuery<'a> {
    pub conversation_id: &'a str,
    pub from_time_us: i64,
    pub from_counter: i64,
    pub limit: i64,
}

#[derive(Debug, Clone, FromRow)]
pub struct AgentExecutionEventRecord {
    pub event_type: String,
    pub event_data: Value,
    pub event_time_us: i64,
    pub event_counter: i32,
    pub created_at: Option<DateTime<Utc>>,
}

pub struct PgAgentExecutionEventRepository {
    pool: PgPool,
}

impl PgAgentExecutionEventRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn replay_access(
        &self,
        user_id: &str,
        conversation_id: &str,
    ) -> CoreResult<ConversationReplayAccess> {
        let Some(conversation) = sqlx::query_as::<_, ConversationAccessRow>(
            "SELECT id, user_id, tenant_id, project_id, workspace_id, meta AS metadata \
             FROM conversations WHERE id = $1",
        )
        .bind(conversation_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        else {
            return Ok(ConversationReplayAccess::NotFound);
        };

        if conversation.user_id == user_id
            || self
                .user_is_tenant_admin(user_id, &conversation.tenant_id)
                .await?
        {
            return Ok(ConversationReplayAccess::Allowed);
        }

        if let Some(workspace_id) = conversation.workspace_id() {
            if self
                .user_has_workspace_access(
                    user_id,
                    &conversation.tenant_id,
                    &conversation.project_id,
                    &workspace_id,
                )
                .await?
            {
                return Ok(ConversationReplayAccess::Allowed);
            }
        }

        Ok(ConversationReplayAccess::Denied)
    }

    pub async fn list_events(
        &self,
        query: AgentExecutionEventListQuery<'_>,
    ) -> CoreResult<Vec<AgentExecutionEventRecord>> {
        sqlx::query_as::<_, AgentExecutionEventRecord>(
            "SELECT event_type, event_data, event_time_us, event_counter, created_at \
             FROM agent_execution_events \
             WHERE conversation_id = $1 \
               AND (event_time_us, event_counter::bigint) > ($2, $3) \
             ORDER BY event_time_us ASC, event_counter ASC \
             LIMIT $4",
        )
        .bind(query.conversation_id)
        .bind(query.from_time_us)
        .bind(query.from_counter)
        .bind(query.limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)
    }

    async fn user_is_tenant_admin(&self, user_id: &str, tenant_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants \
             WHERE user_id = $1 AND tenant_id = $2 AND role IN ('admin', 'owner')",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?
        .0;
        Ok(count > 0)
    }

    async fn user_has_workspace_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM workspace_members wm \
             JOIN workspaces w ON wm.workspace_id = w.id \
             WHERE wm.user_id = $1 \
               AND wm.workspace_id = $2 \
               AND w.tenant_id = $3 \
               AND w.project_id = $4",
        )
        .bind(user_id)
        .bind(workspace_id)
        .bind(tenant_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?
        .0;
        Ok(count > 0)
    }
}

#[derive(Debug, Clone, FromRow)]
struct ConversationAccessRow {
    id: String,
    user_id: String,
    tenant_id: String,
    project_id: String,
    workspace_id: Option<String>,
    metadata: Option<Value>,
}

impl ConversationAccessRow {
    fn workspace_id(&self) -> Option<String> {
        if let Some(workspace_id) = self
            .workspace_id
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
        {
            return Some(workspace_id.to_string());
        }

        if let Some(workspace_id) = self
            .metadata
            .as_ref()
            .and_then(|value| value.get("workspace_id"))
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
        {
            return Some(workspace_id.to_string());
        }

        self.id
            .strip_prefix("workspace-chat:")
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToString::to_string)
    }
}

fn storage(err: sqlx::Error) -> CoreError {
    CoreError::Storage(err.to_string())
}
