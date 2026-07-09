use serde_json::{json, Value};
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::FromRow;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConversationMutationAccess {
    Allowed,
    Denied,
    NotFound,
}

#[derive(Debug, Clone, Copy)]
pub struct ConversationListQuery<'a> {
    pub user_id: &'a str,
    pub project_id: &'a str,
    pub status: Option<&'a str>,
    pub workspace_id: Option<&'a str>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone)]
pub struct ConversationCreateRecord {
    pub id: String,
    pub project_id: String,
    pub user_id: String,
    pub title: String,
    pub agent_config: Value,
}

#[derive(Debug, Clone)]
pub struct ConversationModePatch {
    pub conversation_mode: Option<Option<String>>,
    pub workspace_id: Option<Option<String>>,
    pub linked_workspace_task_id: Option<Option<String>>,
}

#[derive(Debug, Clone, FromRow)]
pub struct AgentConversationRecord {
    pub id: String,
    pub project_id: String,
    pub user_id: String,
    pub tenant_id: String,
    pub title: String,
    pub status: String,
    pub message_count: i32,
    pub created_at: Option<DateTime<Utc>>,
    pub updated_at: Option<DateTime<Utc>>,
    pub summary: Option<String>,
    pub agent_config: Option<Value>,
    #[sqlx(rename = "metadata")]
    pub metadata: Option<Value>,
    pub parent_conversation_id: Option<String>,
    pub branch_point_message_id: Option<String>,
    pub conversation_mode: Option<String>,
    pub workspace_id: Option<String>,
    pub linked_workspace_task_id: Option<String>,
    pub workspace_name: Option<String>,
    pub participant_agents: Option<Value>,
    pub coordinator_agent_id: Option<String>,
    pub focused_agent_id: Option<String>,
}

pub struct PgAgentConversationRepository {
    pool: PgPool,
}

impl PgAgentConversationRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_conversations(
        &self,
        query: ConversationListQuery<'_>,
    ) -> CoreResult<Vec<AgentConversationRecord>> {
        sqlx::query_as::<_, AgentConversationRecord>(
            "WITH last_activity AS ( \
                 SELECT conversation_id, max(event_time_us) AS last_event_time_us \
                 FROM agent_execution_events GROUP BY conversation_id \
             ) \
             SELECT c.id, c.project_id, c.user_id, c.tenant_id, c.title, c.status, \
                    c.message_count, c.created_at, c.updated_at, c.summary, c.agent_config, \
                    c.meta AS metadata, c.parent_conversation_id, c.branch_point_message_id, \
                    c.conversation_mode, c.workspace_id, c.linked_workspace_task_id, \
                    w.name AS workspace_name, c.participant_agents, c.coordinator_agent_id, \
                    c.focused_agent_id \
             FROM conversations c \
             LEFT JOIN last_activity la ON la.conversation_id = c.id \
             LEFT JOIN workspaces w ON w.id = c.workspace_id \
             WHERE c.project_id = $1 \
               AND c.tenant_id = (SELECT tenant_id FROM projects WHERE id = $1) \
               AND ($2::text IS NULL OR c.status = $2) \
               AND ( \
                    ($3::text IS NOT NULL AND ( \
                        c.workspace_id = $3 \
                        OR c.meta->>'workspace_id' = $3 \
                        OR c.id LIKE ('workspace-%:' || $3 || ':%') \
                    )) \
                    OR ($3::text IS NULL AND c.user_id = $4) \
               ) \
             ORDER BY COALESCE(la.last_event_time_us, 0) DESC, \
                      COALESCE(c.updated_at, c.created_at) DESC, \
                      c.created_at DESC, c.id ASC \
             LIMIT $5 OFFSET $6",
        )
        .bind(query.project_id)
        .bind(query.status)
        .bind(query.workspace_id)
        .bind(query.user_id)
        .bind(query.limit)
        .bind(query.offset)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)
    }

    pub async fn count_conversations(&self, query: ConversationListQuery<'_>) -> CoreResult<i64> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM conversations c \
             WHERE c.project_id = $1 \
               AND c.tenant_id = (SELECT tenant_id FROM projects WHERE id = $1) \
               AND ($2::text IS NULL OR c.status = $2) \
               AND ( \
                    ($3::text IS NOT NULL AND ( \
                        c.workspace_id = $3 \
                        OR c.meta->>'workspace_id' = $3 \
                        OR c.id LIKE ('workspace-%:' || $3 || ':%') \
                    )) \
                    OR ($3::text IS NULL AND c.user_id = $4) \
               )",
        )
        .bind(query.project_id)
        .bind(query.status)
        .bind(query.workspace_id)
        .bind(query.user_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count)
        .map_err(storage)
    }

    pub async fn create_conversation(
        &self,
        record: ConversationCreateRecord,
    ) -> CoreResult<Option<AgentConversationRecord>> {
        let Some((tenant_id,)) =
            sqlx::query_as::<_, (String,)>("SELECT tenant_id FROM projects WHERE id = $1")
                .bind(&record.project_id)
                .fetch_optional(&self.pool)
                .await
                .map_err(storage)?
        else {
            return Ok(None);
        };

        sqlx::query(
            "INSERT INTO conversations \
                 (id, project_id, tenant_id, user_id, title, status, agent_config, meta, \
                  message_count, current_mode, merge_strategy, created_at, updated_at) \
             VALUES ($1, $2, $3, $4, $5, 'active', $6, '{}'::json, 0, 'build', \
                     'result_only', now(), now())",
        )
        .bind(&record.id)
        .bind(&record.project_id)
        .bind(&tenant_id)
        .bind(&record.user_id)
        .bind(&record.title)
        .bind(&record.agent_config)
        .execute(&self.pool)
        .await
        .map_err(storage)?;

        self.get_conversation(&record.id, &record.project_id).await
    }

    pub async fn get_conversation(
        &self,
        conversation_id: &str,
        project_id: &str,
    ) -> CoreResult<Option<AgentConversationRecord>> {
        sqlx::query_as::<_, AgentConversationRecord>(
            "SELECT c.id, c.project_id, c.user_id, c.tenant_id, c.title, c.status, \
                    c.message_count, c.created_at, c.updated_at, c.summary, c.agent_config, \
                    c.meta AS metadata, c.parent_conversation_id, c.branch_point_message_id, \
                    c.conversation_mode, c.workspace_id, c.linked_workspace_task_id, \
                    w.name AS workspace_name, c.participant_agents, c.coordinator_agent_id, \
                    c.focused_agent_id \
             FROM conversations c \
             LEFT JOIN workspaces w ON w.id = c.workspace_id \
             WHERE c.id = $1 AND c.project_id = $2",
        )
        .bind(conversation_id)
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)
    }

    pub async fn mutation_access(
        &self,
        user_id: &str,
        project_id: &str,
        conversation_id: &str,
    ) -> CoreResult<ConversationMutationAccess> {
        let Some((owner_id,)) = sqlx::query_as::<_, (String,)>(
            "SELECT user_id FROM conversations WHERE id = $1 AND project_id = $2",
        )
        .bind(conversation_id)
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        else {
            return Ok(ConversationMutationAccess::NotFound);
        };
        if owner_id == user_id {
            Ok(ConversationMutationAccess::Allowed)
        } else {
            Ok(ConversationMutationAccess::Denied)
        }
    }

    pub async fn update_mode(
        &self,
        conversation_id: &str,
        project_id: &str,
        patch: ConversationModePatch,
    ) -> CoreResult<Option<AgentConversationRecord>> {
        let Some(mut current) = self.get_conversation(conversation_id, project_id).await? else {
            return Ok(None);
        };
        let mut metadata = current.metadata.take().unwrap_or_else(|| json!({}));
        if !metadata.is_object() {
            metadata = json!({});
        }

        if let Some(workspace_id) = &patch.workspace_id {
            match workspace_id {
                Some(value) => metadata["workspace_id"] = Value::String(value.clone()),
                None => {
                    if let Some(map) = metadata.as_object_mut() {
                        map.remove("workspace_id");
                    }
                }
            }
        }

        let has_conversation_mode = patch.conversation_mode.is_some();
        let conversation_mode = patch.conversation_mode.flatten();
        let has_workspace_id = patch.workspace_id.is_some();
        let workspace_id = patch.workspace_id.flatten();
        let has_linked_workspace_task_id = patch.linked_workspace_task_id.is_some();
        let linked_workspace_task_id = patch.linked_workspace_task_id.flatten();

        sqlx::query(
            "UPDATE conversations \
             SET conversation_mode = CASE WHEN $3 THEN $4 ELSE conversation_mode END, \
                 workspace_id = CASE WHEN $5 THEN $6 ELSE workspace_id END, \
                 linked_workspace_task_id = CASE WHEN $7 THEN $8 ELSE linked_workspace_task_id END, \
                 meta = $9, \
                 updated_at = now() \
             WHERE id = $1 AND project_id = $2",
        )
        .bind(conversation_id)
        .bind(project_id)
        .bind(has_conversation_mode)
        .bind(conversation_mode)
        .bind(has_workspace_id)
        .bind(workspace_id)
        .bind(has_linked_workspace_task_id)
        .bind(linked_workspace_task_id)
        .bind(&metadata)
        .execute(&self.pool)
        .await
        .map_err(storage)?;

        self.get_conversation(conversation_id, project_id).await
    }

    pub async fn workspace_access(
        &self,
        user_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> CoreResult<ConversationMutationAccess> {
        let Some((tenant_id,)) = sqlx::query_as::<_, (String,)>(
            "SELECT tenant_id FROM workspaces WHERE id = $1 AND project_id = $2",
        )
        .bind(workspace_id)
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        else {
            return Ok(ConversationMutationAccess::NotFound);
        };

        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM workspace_members \
             WHERE workspace_id = $1 AND user_id = $2",
        )
        .bind(workspace_id)
        .bind(user_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?
        .0;
        if count > 0 {
            Ok(ConversationMutationAccess::Allowed)
        } else {
            let admin_count = sqlx::query_as::<_, (i64,)>(
                "SELECT count(*) FROM user_tenants \
                 WHERE user_id = $1 AND tenant_id = $2 AND role IN ('admin', 'owner')",
            )
            .bind(user_id)
            .bind(tenant_id)
            .fetch_one(&self.pool)
            .await
            .map_err(storage)?
            .0;
            if admin_count > 0 {
                Ok(ConversationMutationAccess::Allowed)
            } else {
                Ok(ConversationMutationAccess::Denied)
            }
        }
    }
}

fn storage(err: sqlx::Error) -> CoreError {
    CoreError::Storage(err.to_string())
}
