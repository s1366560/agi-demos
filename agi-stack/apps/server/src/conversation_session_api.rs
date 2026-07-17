//! Authoritative schema-v2 conversation session projection for the desktop client.
//!
//! This surface projects persisted protocol facts only. It does not infer run
//! stages, environment details, permissions, or semantic state from free-form
//! text. PostgreSQL reads are isolated in [`pg`]; response composition remains a
//! deterministic, testable projection.

mod pg;

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use crate::{auth::Identity, AppState};

pub(crate) use pg::PgConversationSessionProjectionService;

const SCHEMA_VERSION: u8 = 2;

pub(crate) fn router() -> Router<AppState> {
    Router::new().route(
        "/api/v1/agent/conversations/:conversation_id/session",
        get(get_conversation_session),
    )
}

async fn get_conversation_session(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(conversation_id): Path<String>,
    Query(query): Query<ConversationSessionQuery>,
) -> Result<Json<ConversationSessionProjectionResponse>, ConversationSessionApiError> {
    app.agent_conversations
        .get_session_projection(&identity.user_id, &conversation_id, query)
        .await
        .map(Json)
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ConversationSessionQuery {
    pub(crate) tenant_id: String,
    pub(crate) project_id: String,
    pub(crate) workspace_id: Option<String>,
}

#[derive(Debug)]
pub(crate) struct ConversationSessionApiError {
    status: StatusCode,
    detail: String,
    diagnostic: Option<String>,
}

impl ConversationSessionApiError {
    pub(crate) fn not_found() -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            detail: "Conversation not found".to_string(),
            diagnostic: None,
        }
    }

    pub(crate) fn internal(diagnostic: impl std::fmt::Display) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            detail: "Internal server error".to_string(),
            diagnostic: Some(diagnostic.to_string()),
        }
    }

    fn into_diagnostic(self) -> String {
        self.diagnostic.unwrap_or(self.detail)
    }
}

impl IntoResponse for ConversationSessionApiError {
    fn into_response(self) -> Response {
        if let Some(diagnostic) = self.diagnostic.as_deref() {
            eprintln!("[agistack] conversation session projection failed: {diagnostic}");
        }
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum ProjectionKind {
    WorkspaceSession,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum SessionAuthorityKind {
    WorkspaceAttempt,
    ConversationRecord,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum SessionCapabilityMode {
    Work,
    Code,
}

impl SessionCapabilityMode {
    pub(super) fn from_config(config: Option<&Value>) -> Option<Self> {
        match config
            .and_then(Value::as_object)
            .and_then(|values| values.get("capability_mode"))
            .and_then(Value::as_str)
        {
            Some("work") => Some(Self::Work),
            Some("code") => Some(Self::Code),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum SessionHitlKind {
    Clarification,
    Decision,
    EnvVar,
    Permission,
    A2uiAction,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum SessionPermissionRiskLevel {
    Low,
    Medium,
    High,
}

impl SessionPermissionRiskLevel {
    pub(super) fn parse(value: &str) -> Option<Self> {
        match value {
            "low" => Some(Self::Low),
            "medium" => Some(Self::Medium),
            "high" => Some(Self::High),
            _ => None,
        }
    }
}

impl SessionHitlKind {
    pub(super) fn parse(value: &str) -> Option<Self> {
        match value {
            "clarification" => Some(Self::Clarification),
            "decision" => Some(Self::Decision),
            "env_var" => Some(Self::EnvVar),
            "permission" => Some(Self::Permission),
            "a2ui_action" => Some(Self::A2uiAction),
            _ => None,
        }
    }

    pub(super) const fn as_str(self) -> &'static str {
        match self {
            Self::Clarification => "clarification",
            Self::Decision => "decision",
            Self::EnvVar => "env_var",
            Self::Permission => "permission",
            Self::A2uiAction => "a2ui_action",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum SessionAllowedAction {
    SendMessage,
    RespondToHitl,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(crate) struct ConversationSessionProjectionResponse {
    schema_version: u8,
    projection_kind: ProjectionKind,
    authority_kind: SessionAuthorityKind,
    authority_id: String,
    conversation: SessionConversationResponse,
    execution: SessionExecutionResponse,
    conversation_tasks: Vec<SessionConversationTaskResponse>,
    workspace_plan_context: Option<SessionWorkspacePlanContextResponse>,
    pending_hitl: Vec<SessionPendingHitlResponse>,
    artifact_records: Vec<SessionArtifactRecordResponse>,
    tool_execution_records: SessionToolExecutionPageResponse,
    evidence_summary: SessionEvidenceSummaryResponse,
    capabilities: SessionCapabilitiesResponse,
    snapshot_revision: String,
    updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct SessionConversationResponse {
    pub(super) id: String,
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) workspace_id: Option<String>,
    pub(super) linked_workspace_task_id: Option<String>,
    pub(super) workspace_name: Option<String>,
    pub(super) user_id: String,
    pub(super) title: String,
    pub(super) summary: Option<String>,
    pub(super) status: String,
    pub(super) current_mode: String,
    pub(super) conversation_mode: Option<String>,
    pub(super) capability_mode: Option<SessionCapabilityMode>,
    pub(super) message_count: i32,
    pub(super) participant_agents: Vec<String>,
    pub(super) coordinator_agent_id: Option<String>,
    pub(super) focused_agent_id: Option<String>,
    pub(super) created_at: DateTime<Utc>,
    pub(super) updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
struct SessionExecutionResponse {
    current_attempt: Option<SessionWorkspaceAttemptResponse>,
    attempt_history: Vec<SessionWorkspaceAttemptResponse>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct SessionWorkspaceAttemptResponse {
    pub(super) id: String,
    pub(super) workspace_task_id: String,
    pub(super) root_goal_task_id: String,
    pub(super) workspace_id: String,
    pub(super) conversation_id: String,
    pub(super) attempt_number: i32,
    pub(super) status: String,
    pub(super) worker_agent_id: Option<String>,
    pub(super) leader_agent_id: Option<String>,
    pub(super) candidate_summary: Option<String>,
    pub(super) candidate_artifact_refs: Vec<String>,
    pub(super) candidate_verification_refs: Vec<String>,
    pub(super) leader_feedback: Option<String>,
    pub(super) adjudication_reason: Option<String>,
    pub(super) created_at: DateTime<Utc>,
    pub(super) updated_at: Option<DateTime<Utc>>,
    pub(super) completed_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct SessionConversationTaskResponse {
    pub(super) id: String,
    pub(super) conversation_id: String,
    pub(super) content: String,
    pub(super) status: String,
    pub(super) priority: String,
    pub(super) order_index: i32,
    pub(super) created_at: DateTime<Utc>,
    pub(super) updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct SessionWorkspacePlanNodeResponse {
    pub(super) id: String,
    pub(super) plan_id: String,
    pub(super) workspace_task_id: String,
    pub(super) kind: String,
    pub(super) title: String,
    pub(super) description: String,
    pub(super) intent: String,
    pub(super) execution: String,
    pub(super) progress: Map<String, Value>,
    pub(super) assignee_agent_id: Option<String>,
    pub(super) current_attempt_id: Option<String>,
    pub(super) created_at: DateTime<Utc>,
    pub(super) updated_at: Option<DateTime<Utc>>,
    pub(super) completed_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct SessionWorkspacePlanContextResponse {
    pub(super) id: String,
    pub(super) workspace_id: String,
    pub(super) goal_id: String,
    pub(super) status: String,
    pub(super) created_at: DateTime<Utc>,
    pub(super) updated_at: Option<DateTime<Utc>>,
    pub(super) linked_nodes: Vec<SessionWorkspacePlanNodeResponse>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct SessionPendingHitlResponse {
    pub(super) id: String,
    pub(super) conversation_id: String,
    pub(super) message_id: Option<String>,
    pub(super) request_type: SessionHitlKind,
    pub(super) question: String,
    pub(super) options: Vec<Map<String, Value>>,
    pub(super) context: Map<String, Value>,
    pub(super) metadata: Map<String, Value>,
    pub(super) permission: Option<SessionPermissionRequestResponse>,
    pub(super) status: &'static str,
    pub(super) created_at: DateTime<Utc>,
    pub(super) expires_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct SessionPermissionRequestResponse {
    pub(super) tool_name: String,
    pub(super) action: String,
    pub(super) risk_level: SessionPermissionRiskLevel,
    pub(super) description: String,
    pub(super) allow_remember: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct SessionArtifactRecordResponse {
    pub(super) id: String,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct SessionToolExecutionResponse {
    pub(super) id: String,
    pub(super) message_id: String,
    pub(super) call_id: String,
    pub(super) tool_name: String,
    pub(super) status: String,
    pub(super) error: Option<String>,
    pub(super) step_number: Option<i32>,
    pub(super) sequence_number: i32,
    pub(super) started_at: DateTime<Utc>,
    pub(super) completed_at: Option<DateTime<Utc>>,
    pub(super) duration_ms: Option<i32>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
struct SessionToolExecutionPageResponse {
    items: Vec<SessionToolExecutionResponse>,
    total: i64,
    truncated: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
struct SessionEvidenceSummaryResponse {
    candidate_artifact_ref_count: usize,
    candidate_verification_ref_count: usize,
    artifact_record_count: usize,
    tool_execution_record_count: i64,
    failed_tool_execution_count: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
struct SessionCapabilitiesResponse {
    can_send_message: bool,
    can_respond_to_hitl: bool,
    can_approve_plan: bool,
    can_control_execution: bool,
    can_review_artifacts: bool,
    can_deliver_artifacts: bool,
    allowed_actions: Vec<SessionAllowedAction>,
}

pub(super) struct SessionArtifactAuthority {
    pub(super) response: SessionArtifactRecordResponse,
    pub(super) created_at: DateTime<Utc>,
}

pub(super) struct SessionToolExecutionAuthority {
    pub(super) items: Vec<SessionToolExecutionResponse>,
    pub(super) total: i64,
    pub(super) failed_total: i64,
}

pub(super) struct SessionMutationAuthority {
    pub(super) can_send_message: bool,
    pub(super) can_respond_to_hitl: bool,
    pub(super) can_control_execution: bool,
}

pub(super) struct ConversationSessionAuthoritySnapshot {
    pub(super) conversation: SessionConversationResponse,
    pub(super) attempts: Vec<SessionWorkspaceAttemptResponse>,
    pub(super) conversation_tasks: Vec<SessionConversationTaskResponse>,
    pub(super) workspace_plan_context: Option<SessionWorkspacePlanContextResponse>,
    pub(super) pending_hitl: Vec<SessionPendingHitlResponse>,
    pub(super) has_blocking_hitl: bool,
    pub(super) mutation_authority: SessionMutationAuthority,
    pub(super) artifact_records: Vec<SessionArtifactAuthority>,
    pub(super) tool_executions: SessionToolExecutionAuthority,
}

pub(crate) struct StandaloneConversationSource {
    pub(crate) id: String,
    pub(crate) tenant_id: String,
    pub(crate) project_id: String,
    pub(crate) workspace_id: Option<String>,
    pub(crate) linked_workspace_task_id: Option<String>,
    pub(crate) workspace_name: Option<String>,
    pub(crate) user_id: String,
    pub(crate) title: String,
    pub(crate) summary: Option<String>,
    pub(crate) status: String,
    pub(crate) current_mode: String,
    pub(crate) conversation_mode: Option<String>,
    pub(crate) agent_config: Option<Value>,
    pub(crate) message_count: i32,
    pub(crate) participant_agents: Vec<String>,
    pub(crate) coordinator_agent_id: Option<String>,
    pub(crate) focused_agent_id: Option<String>,
    pub(crate) created_at: DateTime<Utc>,
    pub(crate) updated_at: Option<DateTime<Utc>>,
}

pub(crate) fn standalone_projection(
    source: StandaloneConversationSource,
) -> Result<ConversationSessionProjectionResponse, ConversationSessionApiError> {
    build_projection(ConversationSessionAuthoritySnapshot {
        conversation: SessionConversationResponse {
            id: source.id,
            tenant_id: source.tenant_id,
            project_id: source.project_id,
            workspace_id: source.workspace_id,
            linked_workspace_task_id: source.linked_workspace_task_id,
            workspace_name: source.workspace_name,
            user_id: source.user_id,
            title: source.title,
            summary: source.summary,
            status: source.status,
            current_mode: source.current_mode,
            conversation_mode: source.conversation_mode,
            capability_mode: SessionCapabilityMode::from_config(source.agent_config.as_ref()),
            message_count: source.message_count,
            participant_agents: source.participant_agents,
            coordinator_agent_id: source.coordinator_agent_id,
            focused_agent_id: source.focused_agent_id,
            created_at: source.created_at,
            updated_at: source.updated_at,
        },
        attempts: Vec::new(),
        conversation_tasks: Vec::new(),
        workspace_plan_context: None,
        pending_hitl: Vec::new(),
        has_blocking_hitl: false,
        mutation_authority: SessionMutationAuthority {
            can_send_message: true,
            can_respond_to_hitl: false,
            can_control_execution: false,
        },
        artifact_records: Vec::new(),
        tool_executions: SessionToolExecutionAuthority {
            items: Vec::new(),
            total: 0,
            failed_total: 0,
        },
    })
}

pub(super) fn build_projection(
    snapshot: ConversationSessionAuthoritySnapshot,
) -> Result<ConversationSessionProjectionResponse, ConversationSessionApiError> {
    let current_attempt = snapshot.attempts.first().cloned();
    let (authority_kind, authority_id) = current_attempt.as_ref().map_or_else(
        || {
            (
                SessionAuthorityKind::ConversationRecord,
                snapshot.conversation.id.clone(),
            )
        },
        |attempt| (SessionAuthorityKind::WorkspaceAttempt, attempt.id.clone()),
    );
    let can_send_message =
        snapshot.mutation_authority.can_send_message && !snapshot.has_blocking_hitl;
    let can_respond_to_hitl =
        snapshot.mutation_authority.can_respond_to_hitl && !snapshot.pending_hitl.is_empty();
    let mut allowed_actions = Vec::with_capacity(2);
    if can_send_message {
        allowed_actions.push(SessionAllowedAction::SendMessage);
    }
    if can_respond_to_hitl {
        allowed_actions.push(SessionAllowedAction::RespondToHitl);
    }
    let candidate_artifact_ref_count = snapshot
        .attempts
        .iter()
        .map(|attempt| attempt.candidate_artifact_refs.len())
        .sum();
    let candidate_verification_ref_count = snapshot
        .attempts
        .iter()
        .map(|attempt| attempt.candidate_verification_refs.len())
        .sum();
    let updated_at = projection_updated_at(&snapshot);
    let artifact_record_count = snapshot.artifact_records.len();
    let tool_item_count = i64::try_from(snapshot.tool_executions.items.len()).unwrap_or(i64::MAX);

    let mut projection = ConversationSessionProjectionResponse {
        schema_version: SCHEMA_VERSION,
        projection_kind: ProjectionKind::WorkspaceSession,
        authority_kind,
        authority_id,
        conversation: snapshot.conversation,
        execution: SessionExecutionResponse {
            current_attempt,
            attempt_history: snapshot.attempts,
        },
        conversation_tasks: snapshot.conversation_tasks,
        workspace_plan_context: snapshot.workspace_plan_context,
        pending_hitl: snapshot.pending_hitl,
        artifact_records: snapshot
            .artifact_records
            .into_iter()
            .map(|record| record.response)
            .collect(),
        tool_execution_records: SessionToolExecutionPageResponse {
            items: snapshot.tool_executions.items,
            total: snapshot.tool_executions.total,
            truncated: snapshot.tool_executions.total > tool_item_count,
        },
        evidence_summary: SessionEvidenceSummaryResponse {
            candidate_artifact_ref_count,
            candidate_verification_ref_count,
            artifact_record_count,
            tool_execution_record_count: snapshot.tool_executions.total,
            failed_tool_execution_count: snapshot.tool_executions.failed_total,
        },
        capabilities: SessionCapabilitiesResponse {
            can_send_message,
            can_respond_to_hitl,
            can_approve_plan: false,
            can_control_execution: snapshot.mutation_authority.can_control_execution,
            can_review_artifacts: false,
            can_deliver_artifacts: false,
            allowed_actions,
        },
        snapshot_revision: "pending".to_string(),
        updated_at,
    };
    projection.snapshot_revision = projection_revision(&projection)?;
    Ok(projection)
}

fn projection_revision(
    projection: &ConversationSessionProjectionResponse,
) -> Result<String, ConversationSessionApiError> {
    let mut value = serde_json::to_value(projection)
        .map_err(|error| ConversationSessionApiError::internal(error.to_string()))?;
    let Value::Object(fields) = &mut value else {
        return Err(ConversationSessionApiError::internal(
            "session projection serialization did not produce an object",
        ));
    };
    fields.remove("snapshot_revision");
    let canonical = serde_json::to_vec(&value)
        .map_err(|error| ConversationSessionApiError::internal(error.to_string()))?;
    Ok(format!("{:x}", Sha256::digest(canonical)))
}

fn projection_updated_at(snapshot: &ConversationSessionAuthoritySnapshot) -> DateTime<Utc> {
    let mut latest = snapshot
        .conversation
        .updated_at
        .unwrap_or(snapshot.conversation.created_at);
    for attempt in &snapshot.attempts {
        latest = latest.max(
            attempt
                .completed_at
                .or(attempt.updated_at)
                .unwrap_or(attempt.created_at),
        );
    }
    for task in &snapshot.conversation_tasks {
        latest = latest.max(task.updated_at.unwrap_or(task.created_at));
    }
    if let Some(plan) = &snapshot.workspace_plan_context {
        latest = latest.max(plan.updated_at.unwrap_or(plan.created_at));
        for node in &plan.linked_nodes {
            latest = latest.max(
                node.completed_at
                    .or(node.updated_at)
                    .unwrap_or(node.created_at),
            );
        }
    }
    for request in &snapshot.pending_hitl {
        latest = latest.max(request.created_at);
    }
    for artifact in &snapshot.artifact_records {
        latest = latest.max(artifact.created_at);
    }
    for tool in &snapshot.tool_executions.items {
        latest = latest.max(tool.completed_at.unwrap_or(tool.started_at));
    }
    latest
}

pub(super) fn sanitized_text(raw: &str) -> Option<String> {
    let stripped = raw
        .chars()
        .filter(|character| {
            !matches!(*character as u32, 0x00..=0x08 | 0x0b | 0x0c | 0x0e..=0x1f | 0x7f)
        })
        .collect::<String>();
    let trimmed = stripped.trim();
    if trimmed.is_empty() {
        return None;
    }
    let mut escaped = String::with_capacity(trimmed.len());
    for character in trimmed.chars() {
        match character {
            '&' => escaped.push_str("&amp;"),
            '<' => escaped.push_str("&lt;"),
            '>' => escaped.push_str("&gt;"),
            '"' => escaped.push_str("&quot;"),
            '\'' => escaped.push_str("&#x27;"),
            _ => escaped.push(character),
        }
    }
    Some(escaped)
}

pub(super) fn sanitized_scalar(value: &Value) -> Option<Value> {
    match value {
        Value::Bool(_) | Value::Number(_) => Some(value.clone()),
        Value::String(raw) => sanitized_text(raw).map(Value::String),
        _ => None,
    }
}

pub(super) fn string_list(value: &Value) -> Vec<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .filter(|item| !item.is_empty())
        .map(ToString::to_string)
        .collect()
}

#[cfg(test)]
mod tests;
