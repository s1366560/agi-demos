use chrono::{DateTime, Utc};
use serde_json::{Map, Value};
use sqlx::FromRow;

use agistack_adapters_postgres::{
    ConversationMutationAccess, ConversationReplayAccess, PgAgentConversationRepository,
    PgAgentExecutionEventRepository, PgPool,
};

use super::{
    build_projection, sanitized_scalar, sanitized_text, string_list, ConversationSessionApiError,
    ConversationSessionAuthoritySnapshot, ConversationSessionProjectionResponse,
    ConversationSessionQuery, SessionArtifactAuthority, SessionArtifactRecordResponse,
    SessionCapabilityMode, SessionConversationResponse, SessionConversationTaskResponse,
    SessionHitlKind, SessionMutationAuthority, SessionPendingHitlResponse,
    SessionPermissionRequestResponse, SessionPermissionRiskLevel, SessionToolExecutionAuthority,
    SessionToolExecutionResponse, SessionWorkspaceAttemptResponse,
    SessionWorkspacePlanContextResponse, SessionWorkspacePlanNodeResponse,
};

const TOOL_RECORD_LIMIT: i64 = 200;
const OPTION_KEYS: &[&str] = &["id", "label", "description", "recommended", "is_default"];
const ENV_CONTEXT_KEYS: &[&str] = &[
    "help_url",
    "hint",
    "project_id",
    "provider",
    "reason",
    "requested_variables",
    "required_for",
    "save_scope",
    "source",
    "step",
    "tool_name",
    "workflow",
];

pub(crate) struct PgConversationSessionProjectionService {
    pool: PgPool,
    conversations: PgAgentConversationRepository,
    events: PgAgentExecutionEventRepository,
}

impl PgConversationSessionProjectionService {
    pub(crate) fn new(pool: PgPool) -> Self {
        Self {
            conversations: PgAgentConversationRepository::new(pool.clone()),
            events: PgAgentExecutionEventRepository::new(pool.clone()),
            pool,
        }
    }

    pub(crate) async fn get_projection(
        &self,
        user_id: &str,
        conversation_id: &str,
        query: &ConversationSessionQuery,
    ) -> Result<Option<ConversationSessionProjectionResponse>, ConversationSessionApiError> {
        let read_access = self
            .events
            .replay_access(user_id, conversation_id)
            .await
            .map_err(ConversationSessionApiError::internal)?;
        if !matches!(read_access, ConversationReplayAccess::Allowed) {
            return Ok(None);
        }

        let can_send_message = matches!(
            self.conversations
                .message_send_access(user_id, &query.project_id, conversation_id)
                .await
                .map_err(ConversationSessionApiError::internal)?,
            ConversationMutationAccess::Allowed
        );
        self.load_projection(user_id, conversation_id, query, can_send_message)
            .await
            .map_err(|error| {
                ConversationSessionApiError::internal(format!(
                    "load conversation session projection: {error}"
                ))
            })
    }

    async fn load_projection(
        &self,
        user_id: &str,
        conversation_id: &str,
        query: &ConversationSessionQuery,
        can_send_message: bool,
    ) -> Result<Option<ConversationSessionProjectionResponse>, sqlx::Error> {
        let Some(conversation_row) = self.load_conversation(conversation_id, query).await? else {
            return Ok(None);
        };
        let conversation = conversation_row.into_response();
        let (
            attempts,
            conversation_tasks,
            workspace_plan_context,
            hitl,
            artifact_records,
            tool_executions,
        ) = tokio::try_join!(
            self.load_attempts(&conversation),
            self.load_conversation_tasks(&conversation.id),
            self.load_workspace_plan_context(&conversation),
            self.load_pending_hitl(&conversation, user_id),
            self.load_artifacts(&conversation),
            self.load_tool_executions(&conversation.id),
        )?;
        build_projection(ConversationSessionAuthoritySnapshot {
            conversation,
            attempts,
            conversation_tasks,
            workspace_plan_context,
            pending_hitl: hitl.items,
            has_blocking_hitl: hitl.has_blocking,
            mutation_authority: SessionMutationAuthority {
                can_send_message,
                can_respond_to_hitl: hitl.can_respond,
                // No concrete pause/resume/cancel action is projected by this schema.
                can_control_execution: false,
            },
            artifact_records,
            tool_executions,
        })
        .map(Some)
        .map_err(|error| sqlx::Error::Protocol(error.into_diagnostic()))
    }

    async fn load_conversation(
        &self,
        conversation_id: &str,
        query: &ConversationSessionQuery,
    ) -> Result<Option<ConversationRow>, sqlx::Error> {
        sqlx::query_as::<_, ConversationRow>(
            "SELECT c.id, c.tenant_id, c.project_id, c.workspace_id, \
                    c.linked_workspace_task_id, w.name AS workspace_name, c.user_id, c.title, \
                    c.summary, c.status, c.current_mode, c.conversation_mode, c.agent_config, \
                    c.message_count, c.participant_agents, c.coordinator_agent_id, \
                    c.focused_agent_id, c.created_at, c.updated_at \
             FROM conversations AS c \
             LEFT JOIN workspaces AS w \
               ON w.id = c.workspace_id \
              AND w.tenant_id = c.tenant_id \
              AND w.project_id = c.project_id \
             WHERE c.id = $1 \
               AND c.tenant_id = $2 \
               AND c.project_id = $3 \
               AND EXISTS ( \
                    SELECT 1 FROM projects AS p \
                    WHERE p.id = c.project_id AND p.tenant_id = c.tenant_id \
               ) \
               AND ( \
                    ($4::text IS NULL AND c.workspace_id IS NULL) \
                    OR ( \
                        $4::text IS NOT NULL \
                        AND c.workspace_id = $4 \
                        AND w.id IS NOT NULL \
                    ) \
               ) \
             LIMIT 1",
        )
        .bind(conversation_id)
        .bind(&query.tenant_id)
        .bind(&query.project_id)
        .bind(query.workspace_id.as_deref())
        .fetch_optional(&self.pool)
        .await
    }

    async fn load_attempts(
        &self,
        conversation: &SessionConversationResponse,
    ) -> Result<Vec<SessionWorkspaceAttemptResponse>, sqlx::Error> {
        let (Some(workspace_id), Some(workspace_task_id)) = (
            conversation.workspace_id.as_deref(),
            conversation.linked_workspace_task_id.as_deref(),
        ) else {
            return Ok(Vec::new());
        };
        let rows = sqlx::query_as::<_, AttemptRow>(
            "SELECT id, workspace_task_id, root_goal_task_id, workspace_id, \
                    conversation_id, attempt_number, status, worker_agent_id, leader_agent_id, \
                    candidate_summary, candidate_artifacts_json, \
                    candidate_verifications_json, leader_feedback, adjudication_reason, \
                    created_at, updated_at, completed_at \
             FROM workspace_task_session_attempts \
             WHERE conversation_id = $1 \
               AND workspace_id = $2 \
               AND workspace_task_id = $3 \
             ORDER BY attempt_number DESC, created_at DESC, id DESC",
        )
        .bind(&conversation.id)
        .bind(workspace_id)
        .bind(workspace_task_id)
        .fetch_all(&self.pool)
        .await?;
        Ok(rows.into_iter().map(AttemptRow::into_response).collect())
    }

    async fn load_conversation_tasks(
        &self,
        conversation_id: &str,
    ) -> Result<Vec<SessionConversationTaskResponse>, sqlx::Error> {
        sqlx::query_as::<_, ConversationTaskRow>(
            "SELECT id, conversation_id, content, status, priority, order_index, \
                    created_at, updated_at \
             FROM agent_tasks \
             WHERE conversation_id = $1 \
             ORDER BY order_index ASC, created_at ASC, id ASC",
        )
        .bind(conversation_id)
        .fetch_all(&self.pool)
        .await
        .map(|rows| {
            rows.into_iter()
                .map(ConversationTaskRow::into_response)
                .collect()
        })
    }

    async fn load_workspace_plan_context(
        &self,
        conversation: &SessionConversationResponse,
    ) -> Result<Option<SessionWorkspacePlanContextResponse>, sqlx::Error> {
        let (Some(workspace_id), Some(workspace_task_id)) = (
            conversation.workspace_id.as_deref(),
            conversation.linked_workspace_task_id.as_deref(),
        ) else {
            return Ok(None);
        };
        let Some(plan) = sqlx::query_as::<_, PlanRow>(
            "SELECT plan.id, plan.workspace_id, plan.goal_id, plan.status, \
                    plan.created_at, plan.updated_at \
             FROM workspace_plans AS plan \
             WHERE plan.workspace_id = $1 \
               AND EXISTS ( \
                    SELECT 1 FROM workspace_plan_nodes AS node \
                    WHERE node.plan_id = plan.id AND node.workspace_task_id = $2 \
               ) \
             ORDER BY plan.created_at DESC, plan.id DESC \
             LIMIT 1",
        )
        .bind(workspace_id)
        .bind(workspace_task_id)
        .fetch_optional(&self.pool)
        .await?
        else {
            return Ok(None);
        };
        let nodes = sqlx::query_as::<_, PlanNodeRow>(
            "SELECT id, plan_id, workspace_task_id, kind, title, description, intent, \
                    execution, progress, assignee_agent_id, current_attempt_id, \
                    created_at, updated_at, completed_at \
             FROM workspace_plan_nodes \
             WHERE plan_id = $1 AND workspace_task_id = $2 \
             ORDER BY created_at ASC, id ASC",
        )
        .bind(&plan.id)
        .bind(workspace_task_id)
        .fetch_all(&self.pool)
        .await?;
        Ok(Some(SessionWorkspacePlanContextResponse {
            id: plan.id,
            workspace_id: plan.workspace_id,
            goal_id: plan.goal_id,
            status: plan.status,
            created_at: plan.created_at,
            updated_at: plan.updated_at,
            linked_nodes: nodes.into_iter().map(PlanNodeRow::into_response).collect(),
        }))
    }

    async fn load_pending_hitl(
        &self,
        conversation: &SessionConversationResponse,
        user_id: &str,
    ) -> Result<PendingHitlProjection, sqlx::Error> {
        let rows = sqlx::query_as::<_, PendingHitlRow>(
            "SELECT id, request_type, conversation_id, message_id, question, options, \
                    context, request_metadata, created_at, expires_at \
             FROM hitl_requests \
             WHERE conversation_id = $1 \
               AND tenant_id = $2 \
               AND project_id = $3 \
               AND status = 'pending' \
               AND (expires_at IS NULL OR expires_at > now()) \
               AND ( \
                    ( \
                        user_id IS NULL \
                        AND $4 = $5 \
                        AND EXISTS ( \
                            SELECT 1 FROM user_tenants AS ut \
                            WHERE ut.tenant_id = $2 AND ut.user_id = $4 \
                        ) \
                    ) \
                    OR ( \
                        user_id = $4 \
                        AND EXISTS ( \
                            SELECT 1 FROM user_tenants AS ut \
                            WHERE ut.tenant_id = $2 AND ut.user_id = $4 \
                        ) \
                        AND EXISTS ( \
                            SELECT 1 FROM user_projects AS up \
                            WHERE up.project_id = $3 AND up.user_id = $4 \
                        ) \
                    ) \
               ) \
             ORDER BY created_at DESC, id DESC",
        )
        .bind(&conversation.id)
        .bind(&conversation.tenant_id)
        .bind(&conversation.project_id)
        .bind(user_id)
        .bind(&conversation.user_id)
        .fetch_all(&self.pool)
        .await?;
        Ok(project_pending_hitl_rows(rows))
    }

    async fn load_artifacts(
        &self,
        conversation: &SessionConversationResponse,
    ) -> Result<Vec<SessionArtifactAuthority>, sqlx::Error> {
        sqlx::query_as::<_, ArtifactRow>(
            "SELECT id, created_at \
             FROM artifacts \
             WHERE conversation_id = $1 \
               AND tenant_id = $2 \
               AND project_id = $3 \
               AND ( \
                    ($4::text IS NULL AND workspace_id IS NULL) \
                    OR ($4::text IS NOT NULL AND workspace_id = $4) \
               ) \
             ORDER BY created_at ASC, id ASC",
        )
        .bind(&conversation.id)
        .bind(&conversation.tenant_id)
        .bind(&conversation.project_id)
        .bind(conversation.workspace_id.as_deref())
        .fetch_all(&self.pool)
        .await
        .map(|rows| {
            rows.into_iter()
                .map(|row| SessionArtifactAuthority {
                    response: SessionArtifactRecordResponse { id: row.id },
                    created_at: row.created_at,
                })
                .collect()
        })
    }

    async fn load_tool_executions(
        &self,
        conversation_id: &str,
    ) -> Result<SessionToolExecutionAuthority, sqlx::Error> {
        let rows = sqlx::query_as::<_, ToolExecutionRow>(
            "SELECT id, message_id, call_id, tool_name, status, step_number, \
                    sequence_number, started_at, completed_at, duration_ms, \
                    count(id) OVER () AS record_total, \
                    count(id) FILTER (WHERE status = 'failed') OVER () AS failed_total \
             FROM tool_execution_records \
             WHERE conversation_id = $1 \
             ORDER BY started_at DESC, id DESC \
             LIMIT $2",
        )
        .bind(conversation_id)
        .bind(TOOL_RECORD_LIMIT)
        .fetch_all(&self.pool)
        .await?;
        let total = rows.first().map_or(0, |row| row.record_total);
        let failed_total = rows.first().map_or(0, |row| row.failed_total);
        Ok(SessionToolExecutionAuthority {
            items: rows
                .into_iter()
                .map(ToolExecutionRow::into_response)
                .collect(),
            total,
            failed_total,
        })
    }
}

#[derive(FromRow)]
struct ConversationRow {
    id: String,
    tenant_id: String,
    project_id: String,
    workspace_id: Option<String>,
    linked_workspace_task_id: Option<String>,
    workspace_name: Option<String>,
    user_id: String,
    title: String,
    summary: Option<String>,
    status: String,
    current_mode: String,
    conversation_mode: Option<String>,
    agent_config: Option<Value>,
    message_count: i32,
    participant_agents: Value,
    coordinator_agent_id: Option<String>,
    focused_agent_id: Option<String>,
    created_at: DateTime<Utc>,
    updated_at: Option<DateTime<Utc>>,
}

impl ConversationRow {
    fn into_response(self) -> SessionConversationResponse {
        SessionConversationResponse {
            id: self.id,
            tenant_id: self.tenant_id,
            project_id: self.project_id,
            workspace_id: self.workspace_id,
            linked_workspace_task_id: self.linked_workspace_task_id,
            workspace_name: self.workspace_name,
            user_id: self.user_id,
            title: self.title,
            summary: self.summary,
            status: self.status,
            current_mode: self.current_mode,
            conversation_mode: self.conversation_mode,
            capability_mode: SessionCapabilityMode::from_config(self.agent_config.as_ref()),
            message_count: self.message_count,
            participant_agents: string_list(&self.participant_agents),
            coordinator_agent_id: self.coordinator_agent_id,
            focused_agent_id: self.focused_agent_id,
            created_at: self.created_at,
            updated_at: self.updated_at,
        }
    }
}

#[derive(FromRow)]
struct AttemptRow {
    id: String,
    workspace_task_id: String,
    root_goal_task_id: String,
    workspace_id: String,
    conversation_id: String,
    attempt_number: i32,
    status: String,
    worker_agent_id: Option<String>,
    leader_agent_id: Option<String>,
    candidate_summary: Option<String>,
    candidate_artifacts_json: Value,
    candidate_verifications_json: Value,
    leader_feedback: Option<String>,
    adjudication_reason: Option<String>,
    created_at: DateTime<Utc>,
    updated_at: Option<DateTime<Utc>>,
    completed_at: Option<DateTime<Utc>>,
}

impl AttemptRow {
    fn into_response(self) -> SessionWorkspaceAttemptResponse {
        SessionWorkspaceAttemptResponse {
            id: self.id,
            workspace_task_id: self.workspace_task_id,
            root_goal_task_id: self.root_goal_task_id,
            workspace_id: self.workspace_id,
            conversation_id: self.conversation_id,
            attempt_number: self.attempt_number,
            status: self.status,
            worker_agent_id: self.worker_agent_id,
            leader_agent_id: self.leader_agent_id,
            candidate_summary: self.candidate_summary,
            candidate_artifact_refs: string_list(&self.candidate_artifacts_json),
            candidate_verification_refs: string_list(&self.candidate_verifications_json),
            leader_feedback: self.leader_feedback,
            adjudication_reason: self.adjudication_reason,
            created_at: self.created_at,
            updated_at: self.updated_at,
            completed_at: self.completed_at,
        }
    }
}

#[derive(FromRow)]
struct ConversationTaskRow {
    id: String,
    conversation_id: String,
    content: String,
    status: String,
    priority: String,
    order_index: i32,
    created_at: DateTime<Utc>,
    updated_at: Option<DateTime<Utc>>,
}

impl ConversationTaskRow {
    fn into_response(self) -> SessionConversationTaskResponse {
        SessionConversationTaskResponse {
            id: self.id,
            conversation_id: self.conversation_id,
            content: self.content,
            status: self.status,
            priority: self.priority,
            order_index: self.order_index,
            created_at: self.created_at,
            updated_at: self.updated_at,
        }
    }
}

#[derive(FromRow)]
struct PlanRow {
    id: String,
    workspace_id: String,
    goal_id: String,
    status: String,
    created_at: DateTime<Utc>,
    updated_at: Option<DateTime<Utc>>,
}

#[derive(FromRow)]
struct PlanNodeRow {
    id: String,
    plan_id: String,
    workspace_task_id: String,
    kind: String,
    title: String,
    description: String,
    intent: String,
    execution: String,
    progress: Value,
    assignee_agent_id: Option<String>,
    current_attempt_id: Option<String>,
    created_at: DateTime<Utc>,
    updated_at: Option<DateTime<Utc>>,
    completed_at: Option<DateTime<Utc>>,
}

impl PlanNodeRow {
    fn into_response(self) -> SessionWorkspacePlanNodeResponse {
        SessionWorkspacePlanNodeResponse {
            id: self.id,
            plan_id: self.plan_id,
            workspace_task_id: self.workspace_task_id,
            kind: self.kind,
            title: self.title,
            description: self.description,
            intent: self.intent,
            execution: self.execution,
            progress: self.progress.as_object().cloned().unwrap_or_default(),
            assignee_agent_id: self.assignee_agent_id,
            current_attempt_id: self.current_attempt_id,
            created_at: self.created_at,
            updated_at: self.updated_at,
            completed_at: self.completed_at,
        }
    }
}

#[derive(FromRow)]
struct PendingHitlRow {
    id: String,
    request_type: String,
    conversation_id: String,
    message_id: Option<String>,
    question: String,
    options: Option<Value>,
    context: Option<Value>,
    request_metadata: Option<Value>,
    created_at: DateTime<Utc>,
    expires_at: Option<DateTime<Utc>>,
}

impl PendingHitlRow {
    fn into_response(self) -> Option<SessionPendingHitlResponse> {
        let metadata_kind = self
            .request_metadata
            .as_ref()
            .and_then(Value::as_object)
            .and_then(|metadata| metadata.get("hitl_type"))
            .and_then(Value::as_str);
        let request_type = SessionHitlKind::parse(metadata_kind.unwrap_or(&self.request_type))?;
        let question = sanitized_text(&self.question);
        let permission = if request_type == SessionHitlKind::Permission {
            safe_permission_request(self.request_metadata.as_ref())
        } else {
            None
        };
        let question = match request_type {
            SessionHitlKind::Permission => {
                question.or_else(|| permission.as_ref().map(|value| value.description.clone()))?
            }
            _ => question?,
        };
        let context = if request_type == SessionHitlKind::EnvVar {
            safe_env_context(self.context.as_ref())
        } else {
            Map::new()
        };
        Some(SessionPendingHitlResponse {
            id: self.id,
            conversation_id: self.conversation_id,
            message_id: self.message_id,
            request_type,
            question,
            options: safe_options(self.options.as_ref()),
            context,
            metadata: Map::from_iter([(
                "hitl_type".to_string(),
                Value::String(request_type.as_str().to_string()),
            )]),
            permission,
            status: "pending",
            created_at: self.created_at,
            expires_at: self.expires_at,
        })
    }
}

pub(super) fn safe_permission_request(
    request_metadata: Option<&Value>,
) -> Option<SessionPermissionRequestResponse> {
    let metadata = request_metadata?.as_object()?;
    let tool_name = sanitized_text(metadata.get("tool_name")?.as_str()?)?;
    let action = sanitized_text(metadata.get("action")?.as_str()?)?;
    let risk_level = SessionPermissionRiskLevel::parse(metadata.get("risk_level")?.as_str()?)?;
    let description = metadata
        .get("description")
        .and_then(Value::as_str)
        .and_then(sanitized_text)
        .unwrap_or_else(|| action.clone());
    let allow_remember = metadata
        .get("allow_remember")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    Some(SessionPermissionRequestResponse {
        tool_name,
        action,
        risk_level,
        description,
        allow_remember,
    })
}

struct PendingHitlProjection {
    items: Vec<SessionPendingHitlResponse>,
    has_blocking: bool,
    can_respond: bool,
}

fn project_pending_hitl_rows(rows: Vec<PendingHitlRow>) -> PendingHitlProjection {
    let has_blocking = !rows.is_empty();
    let items: Vec<_> = rows
        .into_iter()
        .filter_map(PendingHitlRow::into_response)
        .collect();
    let can_respond = !items.is_empty();
    PendingHitlProjection {
        items,
        has_blocking,
        can_respond,
    }
}

#[cfg(test)]
pub(super) fn project_pending_hitl_for_test(
    request_type: &str,
    question: &str,
    request_metadata: Option<Value>,
) -> (Vec<SessionPendingHitlResponse>, bool, bool) {
    let projection = project_pending_hitl_rows(vec![PendingHitlRow {
        id: "hitl-test".to_string(),
        request_type: request_type.to_string(),
        conversation_id: "conversation-test".to_string(),
        message_id: None,
        question: question.to_string(),
        options: None,
        context: None,
        request_metadata,
        created_at: Utc::now(),
        expires_at: None,
    }]);
    (
        projection.items,
        projection.has_blocking,
        projection.can_respond,
    )
}

#[derive(FromRow)]
struct ArtifactRow {
    id: String,
    created_at: DateTime<Utc>,
}

#[derive(FromRow)]
struct ToolExecutionRow {
    id: String,
    message_id: String,
    call_id: String,
    tool_name: String,
    status: String,
    step_number: Option<i32>,
    sequence_number: i32,
    started_at: DateTime<Utc>,
    completed_at: Option<DateTime<Utc>>,
    duration_ms: Option<i32>,
    record_total: i64,
    failed_total: i64,
}

impl ToolExecutionRow {
    fn into_response(self) -> SessionToolExecutionResponse {
        SessionToolExecutionResponse {
            id: self.id,
            message_id: self.message_id,
            call_id: self.call_id,
            tool_name: self.tool_name,
            status: self.status,
            error: None,
            step_number: self.step_number,
            sequence_number: self.sequence_number,
            started_at: self.started_at,
            completed_at: self.completed_at,
            duration_ms: self.duration_ms,
        }
    }
}

fn safe_options(value: Option<&Value>) -> Vec<Map<String, Value>> {
    let Some(options) = value.and_then(Value::as_array) else {
        return Vec::new();
    };
    options
        .iter()
        .filter_map(Value::as_object)
        .filter_map(|source| {
            let safe = OPTION_KEYS
                .iter()
                .filter_map(|key| {
                    source
                        .get(*key)
                        .and_then(sanitized_scalar)
                        .map(|value| ((*key).to_string(), value))
                })
                .collect::<Map<_, _>>();
            (!safe.is_empty()).then_some(safe)
        })
        .collect()
}

fn safe_env_context(value: Option<&Value>) -> Map<String, Value> {
    let Some(source) = value.and_then(Value::as_object) else {
        return Map::new();
    };
    ENV_CONTEXT_KEYS
        .iter()
        .filter_map(|key| {
            let raw = source.get(*key)?;
            let value = sanitized_scalar(raw).or_else(|| sanitized_sequence(raw))?;
            Some(((*key).to_string(), value))
        })
        .collect()
}

fn sanitized_sequence(value: &Value) -> Option<Value> {
    let values = value.as_array()?;
    let safe = values
        .iter()
        .map(sanitized_scalar)
        .collect::<Option<Vec<_>>>()?;
    (!safe.is_empty()).then_some(Value::Array(safe))
}

#[cfg(test)]
pub(super) fn safe_options_for_test(value: Option<&Value>) -> Vec<Map<String, Value>> {
    safe_options(value)
}
