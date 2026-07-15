use std::collections::BTreeMap;

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
    pub event_types: &'a [String],
}

#[derive(Debug, Clone, Copy)]
pub struct AgentExecutionTimelineQuery<'a> {
    pub conversation_id: &'a str,
    pub from_time_us: i64,
    pub from_counter: i64,
    pub before_time_us: Option<i64>,
    pub before_counter: Option<i64>,
    pub limit: i64,
    pub include_event_types: &'a [String],
    pub exclude_event_types: &'a [String],
}

#[derive(Debug, Clone, FromRow)]
pub struct AgentExecutionEventRecord {
    pub message_id: Option<String>,
    pub event_type: String,
    pub event_data: Value,
    pub event_time_us: i64,
    pub event_counter: i32,
    pub created_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, FromRow)]
pub struct ToolExecutionRecord {
    pub id: String,
    pub message_id: String,
    pub call_id: String,
    pub tool_name: String,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub duration_ms: Option<i32>,
}

#[derive(Debug, Clone, Copy)]
pub struct AgentExecutionEventInsertRecord<'a> {
    pub id: &'a str,
    pub conversation_id: &'a str,
    pub message_id: Option<&'a str>,
    pub event_type: &'a str,
    pub event_data: &'a Value,
    pub event_time_us: i64,
    pub event_counter: i32,
    pub correlation_id: Option<&'a str>,
}

#[derive(Clone)]
pub struct PgAgentExecutionEventRepository {
    pool: PgPool,
}

impl PgAgentExecutionEventRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn insert_event(
        &self,
        record: AgentExecutionEventInsertRecord<'_>,
    ) -> CoreResult<()> {
        sqlx::query(
            "INSERT INTO agent_execution_events \
             (id, conversation_id, message_id, event_type, event_data, event_time_us, event_counter, correlation_id) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8) \
             ON CONFLICT (id) DO NOTHING",
        )
        .bind(record.id)
        .bind(record.conversation_id)
        .bind(record.message_id)
        .bind(record.event_type)
        .bind(record.event_data)
        .bind(record.event_time_us)
        .bind(record.event_counter)
        .bind(record.correlation_id)
        .execute(&self.pool)
        .await
        .map(|_| ())
        .map_err(storage)
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

        let (project_scope_exists, active_project_member, tenant_admin) = self
            .conversation_scope_access(user_id, &conversation.tenant_id, &conversation.project_id)
            .await?;
        if !project_scope_exists {
            return Ok(ConversationReplayAccess::Denied);
        }
        if tenant_admin {
            return Ok(ConversationReplayAccess::Allowed);
        }
        if !active_project_member {
            return Ok(ConversationReplayAccess::Denied);
        }
        if conversation.user_id == user_id {
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
            "SELECT message_id, event_type, event_data, event_time_us, event_counter, created_at \
             FROM agent_execution_events \
             WHERE conversation_id = $1 \
               AND (event_time_us, event_counter::bigint) > ($2, $3) \
               AND (cardinality($4::text[]) = 0 OR event_type = ANY($4)) \
             ORDER BY event_time_us ASC, event_counter ASC \
             LIMIT $5",
        )
        .bind(query.conversation_id)
        .bind(query.from_time_us)
        .bind(query.from_counter)
        .bind(query.event_types)
        .bind(query.limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)
    }

    pub async fn list_timeline_events(
        &self,
        query: AgentExecutionTimelineQuery<'_>,
    ) -> CoreResult<Vec<AgentExecutionEventRecord>> {
        let Some(before_time_us) = query.before_time_us else {
            return sqlx::query_as::<_, AgentExecutionEventRecord>(
                "SELECT message_id, event_type, event_data, event_time_us, event_counter, created_at \
                 FROM agent_execution_events \
                 WHERE conversation_id = $1 \
                   AND (event_time_us, event_counter::bigint) > ($2, $3) \
                   AND (cardinality($4::text[]) = 0 OR event_type = ANY($4)) \
                   AND (cardinality($5::text[]) = 0 OR NOT (event_type = ANY($5))) \
                 ORDER BY event_time_us ASC, event_counter ASC \
                 LIMIT $6",
            )
            .bind(query.conversation_id)
            .bind(query.from_time_us)
            .bind(query.from_counter)
            .bind(query.include_event_types)
            .bind(query.exclude_event_types)
            .bind(query.limit)
            .fetch_all(&self.pool)
            .await
            .map_err(storage);
        };
        let before_counter = query.before_counter.unwrap_or_default();

        let mut records = sqlx::query_as::<_, AgentExecutionEventRecord>(
            "SELECT message_id, event_type, event_data, event_time_us, event_counter, created_at \
             FROM agent_execution_events \
             WHERE conversation_id = $1 \
               AND (event_time_us, event_counter::bigint) > ($2, $3) \
               AND (event_time_us, event_counter::bigint) < ($4, $5) \
               AND (cardinality($6::text[]) = 0 OR event_type = ANY($6)) \
               AND (cardinality($7::text[]) = 0 OR NOT (event_type = ANY($7))) \
             ORDER BY event_time_us DESC, event_counter DESC \
             LIMIT $8",
        )
        .bind(query.conversation_id)
        .bind(query.from_time_us)
        .bind(query.from_counter)
        .bind(before_time_us)
        .bind(before_counter)
        .bind(query.include_event_types)
        .bind(query.exclude_event_types)
        .bind(query.limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        records.reverse();
        Ok(records)
    }

    pub async fn get_last_event_time(&self, conversation_id: &str) -> CoreResult<(i64, i64)> {
        sqlx::query_as::<_, (i64, i64)>(
            "SELECT COALESCE(event_time_us, 0), COALESCE(event_counter::bigint, 0) \
             FROM agent_execution_events \
             WHERE conversation_id = $1 \
             ORDER BY event_time_us DESC, event_counter DESC \
             LIMIT 1",
        )
        .bind(conversation_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.unwrap_or((0, 0)))
        .map_err(storage)
    }

    pub async fn has_events_before(
        &self,
        conversation_id: &str,
        before_time_us: i64,
        before_counter: i64,
        include_event_types: &[String],
        exclude_event_types: &[String],
    ) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM agent_execution_events \
             WHERE conversation_id = $1 \
               AND (event_time_us, event_counter::bigint) < ($2, $3) \
               AND (cardinality($4::text[]) = 0 OR event_type = ANY($4)) \
               AND (cardinality($5::text[]) = 0 OR NOT (event_type = ANY($5))) \
             LIMIT 1",
        )
        .bind(conversation_id)
        .bind(before_time_us)
        .bind(before_counter)
        .bind(include_event_types)
        .bind(exclude_event_types)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(storage)
    }

    pub async fn get_events_by_message_ids(
        &self,
        conversation_id: &str,
        message_ids: &[String],
    ) -> CoreResult<BTreeMap<String, Vec<AgentExecutionEventRecord>>> {
        if message_ids.is_empty() {
            return Ok(BTreeMap::new());
        }

        let records = sqlx::query_as::<_, AgentExecutionEventRecord>(
            "SELECT message_id, event_type, event_data, event_time_us, event_counter, created_at \
             FROM agent_execution_events \
             WHERE conversation_id = $1 \
               AND message_id = ANY($2) \
             ORDER BY event_time_us ASC, event_counter ASC",
        )
        .bind(conversation_id)
        .bind(message_ids)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;

        let mut by_message_id: BTreeMap<String, Vec<AgentExecutionEventRecord>> = BTreeMap::new();
        for record in records {
            if let Some(message_id) = record.message_id.clone() {
                by_message_id.entry(message_id).or_default().push(record);
            }
        }
        Ok(by_message_id)
    }

    pub async fn list_tool_executions(
        &self,
        conversation_id: &str,
    ) -> CoreResult<Vec<ToolExecutionRecord>> {
        sqlx::query_as::<_, ToolExecutionRecord>(
            "SELECT id, message_id, call_id, tool_name, started_at, completed_at, duration_ms \
             FROM tool_execution_records \
             WHERE conversation_id = $1 \
             ORDER BY started_at ASC, sequence_number ASC",
        )
        .bind(conversation_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)
    }

    async fn conversation_scope_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
    ) -> CoreResult<(bool, bool, bool)> {
        sqlx::query_as::<_, (bool, bool, bool)>(
            "SELECT \
                 EXISTS(SELECT 1 FROM projects p \
                        WHERE p.id = $3 AND p.tenant_id = $2), \
                 EXISTS(SELECT 1 FROM projects p \
                        JOIN user_tenants ut \
                          ON ut.tenant_id = p.tenant_id AND ut.user_id = $1 \
                        JOIN user_projects up \
                          ON up.project_id = p.id AND up.user_id = $1 \
                        WHERE p.id = $3 AND p.tenant_id = $2), \
                 EXISTS(SELECT 1 FROM user_tenants ut \
                        WHERE ut.user_id = $1 AND ut.tenant_id = $2 \
                          AND ut.role IN ('admin', 'owner'))",
        )
        .bind(user_id)
        .bind(tenant_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
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
