//! Rust-owned minimum Agent conversation API for the desktop client.
//!
//! This surface intentionally implements only the Python-compatible operations
//! the desktop shell needs during the strangler migration: list/create/link
//! conversations and replay a normalized historical timeline.

use std::{
    collections::{BTreeMap, HashMap},
    sync::{Arc, Mutex},
};

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, patch},
    Extension, Json, Router,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use uuid::Uuid;

use agistack_adapters_postgres::{
    AgentConversationRecord, AgentExecutionEventRecord, AgentExecutionTimelineQuery,
    ConversationCreateRecord, ConversationListQuery, ConversationModePatch,
    ConversationMutationAccess, ConversationReplayAccess, HitlRequestRecord,
    PgAgentConversationRepository, PgAgentExecutionEventRepository, PgHitlRequestRepository,
    ToolExecutionRecord,
};
use agistack_core::ports::EventStream;

use crate::agent_events_api::agent_stream_topic;
use crate::auth::Identity;
use crate::conversation_session_api::{
    standalone_projection, ConversationSessionApiError, ConversationSessionProjectionResponse,
    ConversationSessionQuery, PgConversationSessionProjectionService, StandaloneConversationSource,
};
use crate::AppState;

const DEFAULT_CONVERSATION_LIMIT: i64 = 50;
const MAX_CONVERSATION_LIMIT: i64 = 500;
const DEFAULT_TIMELINE_LIMIT: i64 = 50;
const MAX_TIMELINE_LIMIT: i64 = 500;

const TIMELINE_EXCLUDED_EVENT_TYPES: &[&str] = &[
    "status",
    "start",
    "complete",
    "cancelled",
    "message",
    "progress",
    "title_generated",
    "tools_updated",
    "context_status",
    "context_summary_generated",
    "assistant_message_delta",
    "user_message_delta",
    "message_delta",
    "thought_delta",
    "observe_delta",
    "tool_delta",
    "task_delta",
    "work_plan_delta",
    "artifact_delta",
    "a2ui_delta",
    "stream_delta",
];

pub(crate) type SharedAgentConversations = Arc<dyn AgentConversationApiService>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ConversationSocketAccess {
    Allowed,
    Denied,
    NotFound,
}

impl From<ConversationReplayAccess> for ConversationSocketAccess {
    fn from(access: ConversationReplayAccess) -> Self {
        match access {
            ConversationReplayAccess::Allowed => Self::Allowed,
            ConversationReplayAccess::Denied => Self::Denied,
            ConversationReplayAccess::NotFound => Self::NotFound,
        }
    }
}

impl From<ConversationMutationAccess> for ConversationSocketAccess {
    fn from(access: ConversationMutationAccess) -> Self {
        match access {
            ConversationMutationAccess::Allowed => Self::Allowed,
            ConversationMutationAccess::Denied => Self::Denied,
            ConversationMutationAccess::NotFound => Self::NotFound,
        }
    }
}

#[async_trait]
pub(crate) trait AgentConversationApiService: Send + Sync {
    async fn authorize_event_subscription(
        &self,
        user_id: &str,
        conversation_id: &str,
    ) -> Result<ConversationSocketAccess, AgentConversationsApiError>;

    async fn authorize_message_send(
        &self,
        user_id: &str,
        conversation_id: &str,
        project_id: &str,
    ) -> Result<ConversationSocketAccess, AgentConversationsApiError>;

    async fn authorize_session_stop(
        &self,
        user_id: &str,
        conversation_id: &str,
    ) -> Result<ConversationSocketAccess, AgentConversationsApiError>;

    async fn list_conversations(
        &self,
        user_id: &str,
        query: ConversationListRequest,
    ) -> Result<PaginatedConversationsResponse, AgentConversationsApiError>;

    async fn create_conversation(
        &self,
        user_id: &str,
        request: CreateConversationRequest,
    ) -> Result<AgentConversationResponse, AgentConversationsApiError>;

    async fn update_conversation_mode(
        &self,
        user_id: &str,
        conversation_id: &str,
        project_id: &str,
        request: UpdateConversationModeRequest,
    ) -> Result<AgentConversationResponse, AgentConversationsApiError>;

    async fn get_messages(
        &self,
        user_id: &str,
        conversation_id: &str,
        query: ConversationMessagesQuery,
    ) -> Result<ConversationMessagesResponse, AgentConversationsApiError>;

    async fn get_session_projection(
        &self,
        user_id: &str,
        conversation_id: &str,
        query: ConversationSessionQuery,
    ) -> Result<ConversationSessionProjectionResponse, ConversationSessionApiError>;
}

pub(crate) struct PgAgentConversationService {
    conversations: PgAgentConversationRepository,
    events: PgAgentExecutionEventRepository,
    hitl: PgHitlRequestRepository,
    session_projection: PgConversationSessionProjectionService,
}

impl PgAgentConversationService {
    pub(crate) fn new(
        conversations: PgAgentConversationRepository,
        events: PgAgentExecutionEventRepository,
        hitl: PgHitlRequestRepository,
        session_projection: PgConversationSessionProjectionService,
    ) -> Self {
        Self {
            conversations,
            events,
            hitl,
            session_projection,
        }
    }
}

#[async_trait]
impl AgentConversationApiService for PgAgentConversationService {
    async fn authorize_event_subscription(
        &self,
        user_id: &str,
        conversation_id: &str,
    ) -> Result<ConversationSocketAccess, AgentConversationsApiError> {
        self.events
            .replay_access(user_id, conversation_id)
            .await
            .map(ConversationSocketAccess::from)
            .map_err(AgentConversationsApiError::internal)
    }

    async fn authorize_session_stop(
        &self,
        user_id: &str,
        conversation_id: &str,
    ) -> Result<ConversationSocketAccess, AgentConversationsApiError> {
        self.conversations
            .owner_access(user_id, conversation_id)
            .await
            .map(ConversationSocketAccess::from)
            .map_err(AgentConversationsApiError::internal)
    }

    async fn authorize_message_send(
        &self,
        user_id: &str,
        conversation_id: &str,
        project_id: &str,
    ) -> Result<ConversationSocketAccess, AgentConversationsApiError> {
        self.conversations
            .message_send_access(user_id, project_id, conversation_id)
            .await
            .map(ConversationSocketAccess::from)
            .map_err(AgentConversationsApiError::internal)
    }

    async fn list_conversations(
        &self,
        user_id: &str,
        query: ConversationListRequest,
    ) -> Result<PaginatedConversationsResponse, AgentConversationsApiError> {
        let validated = query.validated()?;
        if let Some(workspace_id) = validated.workspace_id.as_deref() {
            match self
                .conversations
                .workspace_access(user_id, &validated.project_id, workspace_id)
                .await
                .map_err(AgentConversationsApiError::internal)?
            {
                ConversationMutationAccess::Allowed => {}
                ConversationMutationAccess::Denied => {
                    return Err(AgentConversationsApiError::forbidden(
                        "Workspace access required",
                    ));
                }
                ConversationMutationAccess::NotFound => {
                    return Err(AgentConversationsApiError::not_found("Workspace not found"));
                }
            }
        }

        let query_ref = ConversationListQuery {
            user_id,
            project_id: &validated.project_id,
            status: validated.status.as_deref(),
            workspace_id: validated.workspace_id.as_deref(),
            limit: validated.limit,
            offset: validated.offset,
        };
        let items = self
            .conversations
            .list_conversations(query_ref)
            .await
            .map_err(AgentConversationsApiError::internal)?
            .into_iter()
            .map(AgentConversationResponse::from)
            .collect::<Vec<_>>();
        let total = self
            .conversations
            .count_conversations(query_ref)
            .await
            .map_err(AgentConversationsApiError::internal)?;
        Ok(PaginatedConversationsResponse::new(
            items,
            total,
            validated.limit,
            validated.offset,
        ))
    }

    async fn create_conversation(
        &self,
        user_id: &str,
        request: CreateConversationRequest,
    ) -> Result<AgentConversationResponse, AgentConversationsApiError> {
        let project_id = required_trimmed(&request.project_id, "project_id")?;
        let title = request
            .title
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .unwrap_or("New conversation")
            .chars()
            .take(500)
            .collect::<String>();
        let record = self
            .conversations
            .create_conversation(ConversationCreateRecord {
                id: Uuid::new_v4().to_string(),
                project_id: project_id.to_string(),
                user_id: user_id.to_string(),
                title,
                agent_config: request.agent_config.unwrap_or_else(|| json!({})),
            })
            .await
            .map_err(AgentConversationsApiError::internal)?
            .ok_or_else(|| AgentConversationsApiError::not_found("Project not found"))?;
        Ok(record.into())
    }

    async fn update_conversation_mode(
        &self,
        user_id: &str,
        conversation_id: &str,
        project_id: &str,
        request: UpdateConversationModeRequest,
    ) -> Result<AgentConversationResponse, AgentConversationsApiError> {
        match self
            .conversations
            .mutation_access(user_id, project_id, conversation_id)
            .await
            .map_err(AgentConversationsApiError::internal)?
        {
            ConversationMutationAccess::Allowed => {}
            ConversationMutationAccess::Denied => {
                return Err(AgentConversationsApiError::forbidden("Access denied"));
            }
            ConversationMutationAccess::NotFound => {
                return Err(AgentConversationsApiError::not_found(
                    "Conversation not found",
                ));
            }
        }
        if let Some(Some(workspace_id)) = request.workspace_id.as_ref() {
            match self
                .conversations
                .workspace_access(user_id, project_id, workspace_id)
                .await
                .map_err(AgentConversationsApiError::internal)?
            {
                ConversationMutationAccess::Allowed => {}
                ConversationMutationAccess::Denied => {
                    return Err(AgentConversationsApiError::forbidden(
                        "Workspace access required",
                    ));
                }
                ConversationMutationAccess::NotFound => {
                    return Err(AgentConversationsApiError::not_found("Workspace not found"));
                }
            }
        }

        let record = self
            .conversations
            .update_mode(
                conversation_id,
                project_id,
                ConversationModePatch {
                    conversation_mode: request.conversation_mode,
                    workspace_id: request.workspace_id,
                    linked_workspace_task_id: request.linked_workspace_task_id,
                },
            )
            .await
            .map_err(AgentConversationsApiError::internal)?
            .ok_or_else(|| AgentConversationsApiError::not_found("Conversation not found"))?;
        Ok(record.into())
    }

    async fn get_messages(
        &self,
        user_id: &str,
        conversation_id: &str,
        query: ConversationMessagesQuery,
    ) -> Result<ConversationMessagesResponse, AgentConversationsApiError> {
        let validated = query.validated()?;
        match self
            .events
            .replay_access(user_id, conversation_id)
            .await
            .map_err(AgentConversationsApiError::internal)?
        {
            ConversationReplayAccess::Allowed => {}
            ConversationReplayAccess::Denied => {
                return Err(AgentConversationsApiError::forbidden(
                    "Access denied to this conversation",
                ));
            }
            ConversationReplayAccess::NotFound => {
                return Err(AgentConversationsApiError::not_found(
                    "Conversation not found",
                ));
            }
        }
        let conversation = self
            .conversations
            .get_conversation(conversation_id, &validated.project_id)
            .await
            .map_err(AgentConversationsApiError::internal)?;
        if conversation.is_none() {
            return Err(AgentConversationsApiError::not_found(
                "Conversation not found",
            ));
        }

        let (before_time_us, before_counter) = self
            .resolve_before_cursor(conversation_id, &validated)
            .await?;
        let excluded_event_types = excluded_event_types();
        let events = self
            .events
            .list_timeline_events(AgentExecutionTimelineQuery {
                conversation_id,
                from_time_us: validated.from_time_us,
                from_counter: validated.from_counter,
                before_time_us,
                before_counter,
                limit: validated.limit,
                include_event_types: &[],
                exclude_event_types: &excluded_event_types,
            })
            .await
            .map_err(AgentConversationsApiError::internal)?;
        let tool_exec_map = tool_execution_map(
            self.events
                .list_tool_executions(conversation_id)
                .await
                .map_err(AgentConversationsApiError::internal)?,
        );
        let hitl_status_map = hitl_status_map(
            self.hitl
                .get_by_conversation(conversation_id)
                .await
                .map_err(AgentConversationsApiError::internal)?,
        );
        let hitl_answered_map = hitl_answered_map(&events);
        let message_context_events = self
            .message_context_events(conversation_id, &events)
            .await?;
        let completion_map = completion_map(&message_context_events);
        let (artifact_ready_map, artifact_error_map) =
            artifact_maps(events.iter().chain(message_context_events.iter()));
        let timeline = build_timeline(
            &events,
            &tool_exec_map,
            &hitl_answered_map,
            &hitl_status_map,
            &artifact_ready_map,
            &artifact_error_map,
            &completion_map,
        );
        let first = timeline.first();
        let last = timeline.last();
        let has_more = match first {
            Some(item) => self
                .events
                .has_events_before(
                    conversation_id,
                    item.event_time_us,
                    item.event_counter,
                    &[],
                    &excluded_event_types,
                )
                .await
                .map_err(AgentConversationsApiError::internal)?,
            None => false,
        };
        Ok(ConversationMessagesResponse {
            conversation_id: conversation_id.to_string(),
            total: timeline.len(),
            has_more,
            first_time_us: first.map(|item| item.event_time_us),
            first_counter: first.map(|item| item.event_counter),
            last_time_us: last.map(|item| item.event_time_us),
            last_counter: last.map(|item| item.event_counter),
            timeline,
        })
    }

    async fn get_session_projection(
        &self,
        user_id: &str,
        conversation_id: &str,
        query: ConversationSessionQuery,
    ) -> Result<ConversationSessionProjectionResponse, ConversationSessionApiError> {
        self.session_projection
            .get_projection(user_id, conversation_id, &query)
            .await?
            .ok_or_else(ConversationSessionApiError::not_found)
    }
}

impl PgAgentConversationService {
    async fn resolve_before_cursor(
        &self,
        conversation_id: &str,
        query: &ValidatedMessagesQuery,
    ) -> Result<(Option<i64>, Option<i64>), AgentConversationsApiError> {
        if query.before_time_us.is_some() {
            return Ok((query.before_time_us, query.before_counter));
        }
        if query.from_time_us > 0 {
            return Ok((None, None));
        }
        let (last_time_us, _last_counter) = self
            .events
            .get_last_event_time(conversation_id)
            .await
            .map_err(AgentConversationsApiError::internal)?;
        if last_time_us > 0 {
            Ok((Some(last_time_us + 1), Some(0)))
        } else {
            Ok((None, None))
        }
    }

    async fn message_context_events(
        &self,
        conversation_id: &str,
        events: &[AgentExecutionEventRecord],
    ) -> Result<Vec<AgentExecutionEventRecord>, AgentConversationsApiError> {
        let mut message_ids = events
            .iter()
            .filter(|event| {
                matches!(
                    event.event_type.as_str(),
                    "assistant_message" | "artifact_created"
                )
            })
            .filter_map(|event| event.message_id.clone())
            .collect::<Vec<_>>();
        message_ids.sort();
        message_ids.dedup();
        if message_ids.is_empty() {
            return Ok(Vec::new());
        }
        let by_message = self
            .events
            .get_events_by_message_ids(conversation_id, &message_ids)
            .await
            .map_err(AgentConversationsApiError::internal)?;
        Ok(by_message.into_values().flatten().collect())
    }
}

pub(crate) struct DevAgentConversationService {
    conversations: Mutex<HashMap<String, AgentConversationResponse>>,
    events: Arc<dyn EventStream>,
}

impl DevAgentConversationService {
    pub(crate) fn new(events: Arc<dyn EventStream>) -> Self {
        Self {
            conversations: Mutex::new(HashMap::new()),
            events,
        }
    }
}

#[async_trait]
impl AgentConversationApiService for DevAgentConversationService {
    async fn authorize_event_subscription(
        &self,
        user_id: &str,
        conversation_id: &str,
    ) -> Result<ConversationSocketAccess, AgentConversationsApiError> {
        let conversations = self
            .conversations
            .lock()
            .map_err(|_| AgentConversationsApiError::internal("conversation lock poisoned"))?;
        Ok(match conversations.get(conversation_id) {
            Some(conversation) if conversation.user_id == user_id => {
                ConversationSocketAccess::Allowed
            }
            Some(_) => ConversationSocketAccess::Denied,
            None => ConversationSocketAccess::NotFound,
        })
    }

    async fn authorize_session_stop(
        &self,
        user_id: &str,
        conversation_id: &str,
    ) -> Result<ConversationSocketAccess, AgentConversationsApiError> {
        let conversations = self
            .conversations
            .lock()
            .map_err(|_| AgentConversationsApiError::internal("conversation lock poisoned"))?;
        Ok(match conversations.get(conversation_id) {
            Some(conversation) if conversation.user_id == user_id => {
                ConversationSocketAccess::Allowed
            }
            Some(_) => ConversationSocketAccess::Denied,
            None => ConversationSocketAccess::NotFound,
        })
    }

    async fn authorize_message_send(
        &self,
        user_id: &str,
        conversation_id: &str,
        project_id: &str,
    ) -> Result<ConversationSocketAccess, AgentConversationsApiError> {
        let conversations = self
            .conversations
            .lock()
            .map_err(|_| AgentConversationsApiError::internal("conversation lock poisoned"))?;
        Ok(match conversations.get(conversation_id) {
            Some(conversation)
                if conversation.user_id == user_id && conversation.project_id == project_id =>
            {
                ConversationSocketAccess::Allowed
            }
            Some(_) => ConversationSocketAccess::Denied,
            None => ConversationSocketAccess::NotFound,
        })
    }

    async fn list_conversations(
        &self,
        _user_id: &str,
        query: ConversationListRequest,
    ) -> Result<PaginatedConversationsResponse, AgentConversationsApiError> {
        let validated = query.validated()?;
        let mut items = self
            .conversations
            .lock()
            .map_err(|_| AgentConversationsApiError::internal("conversation lock poisoned"))?
            .values()
            .filter(|conversation| conversation.project_id == validated.project_id)
            .filter(|conversation| match validated.status.as_deref() {
                Some(status) => conversation.status == status,
                None => true,
            })
            .filter(|conversation| match validated.workspace_id.as_deref() {
                Some(workspace_id) => conversation.workspace_id.as_deref() == Some(workspace_id),
                None => true,
            })
            .cloned()
            .collect::<Vec<_>>();
        items.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        let total = items.len() as i64;
        let start = validated.offset as usize;
        let end = start
            .saturating_add(validated.limit as usize)
            .min(items.len());
        let page = if start < items.len() {
            items[start..end].to_vec()
        } else {
            Vec::new()
        };
        Ok(PaginatedConversationsResponse::new(
            page,
            total,
            validated.limit,
            validated.offset,
        ))
    }

    async fn create_conversation(
        &self,
        user_id: &str,
        request: CreateConversationRequest,
    ) -> Result<AgentConversationResponse, AgentConversationsApiError> {
        let project_id = required_trimmed(&request.project_id, "project_id")?.to_string();
        let now = Utc::now().to_rfc3339();
        let conversation = AgentConversationResponse {
            id: Uuid::new_v4().to_string(),
            project_id,
            user_id: user_id.to_string(),
            tenant_id: "dev-tenant".to_string(),
            title: request
                .title
                .filter(|title| !title.trim().is_empty())
                .unwrap_or_else(|| "New conversation".to_string()),
            status: "active".to_string(),
            message_count: 0,
            created_at: now.clone(),
            updated_at: Some(now),
            summary: None,
            agent_config: request.agent_config,
            metadata: Some(json!({})),
            parent_conversation_id: None,
            branch_point_message_id: None,
            conversation_mode: None,
            workspace_id: None,
            linked_workspace_task_id: None,
            workspace_name: None,
            participant_agents: Vec::new(),
            coordinator_agent_id: None,
            focused_agent_id: None,
        };
        self.conversations
            .lock()
            .map_err(|_| AgentConversationsApiError::internal("conversation lock poisoned"))?
            .insert(conversation.id.clone(), conversation.clone());
        Ok(conversation)
    }

    async fn update_conversation_mode(
        &self,
        _user_id: &str,
        conversation_id: &str,
        _project_id: &str,
        request: UpdateConversationModeRequest,
    ) -> Result<AgentConversationResponse, AgentConversationsApiError> {
        let mut guard = self
            .conversations
            .lock()
            .map_err(|_| AgentConversationsApiError::internal("conversation lock poisoned"))?;
        let conversation = guard
            .get_mut(conversation_id)
            .ok_or_else(|| AgentConversationsApiError::not_found("Conversation not found"))?;
        if let Some(mode) = request.conversation_mode {
            conversation.conversation_mode = mode;
        }
        if let Some(workspace_id) = request.workspace_id {
            conversation.workspace_id = workspace_id;
        }
        if let Some(task_id) = request.linked_workspace_task_id {
            conversation.linked_workspace_task_id = task_id;
        }
        conversation.updated_at = Some(Utc::now().to_rfc3339());
        Ok(conversation.clone())
    }

    async fn get_messages(
        &self,
        _user_id: &str,
        conversation_id: &str,
        query: ConversationMessagesQuery,
    ) -> Result<ConversationMessagesResponse, AgentConversationsApiError> {
        let validated = query.validated()?;
        let entries = self
            .events
            .read_after(
                &agent_stream_topic(conversation_id),
                "",
                MAX_TIMELINE_LIMIT as usize,
            )
            .await
            .map_err(AgentConversationsApiError::internal)?;
        let mut events = entries
            .into_iter()
            .filter_map(|entry| stream_payload_to_record(&entry.payload))
            .filter(|event| {
                !excluded_event_types()
                    .iter()
                    .any(|excluded| excluded == &event.event_type)
            })
            .collect::<Vec<_>>();
        events.sort_by_key(|event| (event.event_time_us, event.event_counter));
        let page = page_dev_events(events, &validated);
        let timeline = build_timeline(
            &page,
            &BTreeMap::new(),
            &hitl_answered_map(&page),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
        );
        let first = timeline.first();
        let last = timeline.last();
        Ok(ConversationMessagesResponse {
            conversation_id: conversation_id.to_string(),
            total: timeline.len(),
            has_more: false,
            first_time_us: first.map(|item| item.event_time_us),
            first_counter: first.map(|item| item.event_counter),
            last_time_us: last.map(|item| item.event_time_us),
            last_counter: last.map(|item| item.event_counter),
            timeline,
        })
    }

    async fn get_session_projection(
        &self,
        user_id: &str,
        conversation_id: &str,
        query: ConversationSessionQuery,
    ) -> Result<ConversationSessionProjectionResponse, ConversationSessionApiError> {
        let conversation = self
            .conversations
            .lock()
            .map_err(|_| ConversationSessionApiError::internal("conversation lock poisoned"))?
            .get(conversation_id)
            .filter(|conversation| {
                conversation.user_id == user_id
                    && conversation.tenant_id == query.tenant_id
                    && conversation.project_id == query.project_id
                    && conversation.workspace_id == query.workspace_id
            })
            .cloned()
            .ok_or_else(ConversationSessionApiError::not_found)?;
        let created_at = DateTime::parse_from_rfc3339(&conversation.created_at)
            .map_err(ConversationSessionApiError::internal)?
            .with_timezone(&Utc);
        let updated_at = conversation
            .updated_at
            .as_deref()
            .map(DateTime::parse_from_rfc3339)
            .transpose()
            .map_err(ConversationSessionApiError::internal)?
            .map(|value| value.with_timezone(&Utc));
        standalone_projection(StandaloneConversationSource {
            id: conversation.id,
            tenant_id: conversation.tenant_id,
            project_id: conversation.project_id,
            workspace_id: conversation.workspace_id,
            linked_workspace_task_id: conversation.linked_workspace_task_id,
            workspace_name: conversation.workspace_name,
            user_id: conversation.user_id,
            title: conversation.title,
            summary: conversation.summary,
            status: conversation.status,
            current_mode: "build".to_string(),
            conversation_mode: conversation.conversation_mode,
            agent_config: conversation.agent_config,
            message_count: conversation.message_count,
            participant_agents: conversation.participant_agents,
            coordinator_agent_id: conversation.coordinator_agent_id,
            focused_agent_id: conversation.focused_agent_id,
            created_at,
            updated_at,
        })
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/agent/conversations",
            get(list_conversations).post(create_conversation),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/mode",
            patch(update_conversation_mode),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/messages",
            get(get_conversation_messages),
        )
}

async fn list_conversations(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<ConversationListRequest>,
) -> Result<Json<PaginatedConversationsResponse>, AgentConversationsApiError> {
    ensure_project_access(&app, &identity, &query.project_id).await?;
    app.agent_conversations
        .list_conversations(&identity.user_id, query)
        .await
        .map(Json)
}

async fn create_conversation(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(request): Json<CreateConversationRequest>,
) -> Result<(StatusCode, Json<AgentConversationResponse>), AgentConversationsApiError> {
    ensure_project_write(&app, &identity, &request.project_id).await?;
    let response = app
        .agent_conversations
        .create_conversation(&identity.user_id, request)
        .await?;
    Ok((StatusCode::CREATED, Json(response)))
}

async fn update_conversation_mode(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(conversation_id): Path<String>,
    Query(query): Query<ModeProjectQuery>,
    Json(request): Json<UpdateConversationModeRequest>,
) -> Result<Json<AgentConversationResponse>, AgentConversationsApiError> {
    ensure_project_write(&app, &identity, &query.project_id).await?;
    app.agent_conversations
        .update_conversation_mode(
            &identity.user_id,
            &conversation_id,
            &query.project_id,
            request,
        )
        .await
        .map(Json)
}

async fn get_conversation_messages(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(conversation_id): Path<String>,
    Query(query): Query<ConversationMessagesQuery>,
) -> Result<Json<ConversationMessagesResponse>, AgentConversationsApiError> {
    ensure_project_access(&app, &identity, &query.project_id).await?;
    app.agent_conversations
        .get_messages(&identity.user_id, &conversation_id, query)
        .await
        .map(Json)
}

async fn ensure_project_access(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> Result<(), AgentConversationsApiError> {
    let project_id = required_trimmed(project_id, "project_id")?;
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await
        .map_err(AgentConversationsApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(AgentConversationsApiError::forbidden("Access denied"))
    }
}

async fn ensure_project_write(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> Result<(), AgentConversationsApiError> {
    let project_id = required_trimmed(project_id, "project_id")?;
    let allowed = app
        .auth
        .can_write_project(&identity.user_id, project_id)
        .await
        .map_err(AgentConversationsApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(AgentConversationsApiError::forbidden("Access denied"))
    }
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ConversationListRequest {
    project_id: String,
    status: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
    workspace_id: Option<String>,
}

impl ConversationListRequest {
    fn validated(&self) -> Result<ValidatedConversationListQuery, AgentConversationsApiError> {
        let project_id = required_trimmed(&self.project_id, "project_id")?.to_string();
        let status = self
            .status
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToString::to_string);
        let workspace_id = self
            .workspace_id
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToString::to_string);
        let limit = self.limit.unwrap_or(DEFAULT_CONVERSATION_LIMIT);
        if !(1..=MAX_CONVERSATION_LIMIT).contains(&limit) {
            return Err(AgentConversationsApiError::unprocessable(
                "limit must be between 1 and 500",
            ));
        }
        let offset = self.offset.unwrap_or_default();
        if offset < 0 {
            return Err(AgentConversationsApiError::unprocessable(
                "offset must be greater than or equal to 0",
            ));
        }
        Ok(ValidatedConversationListQuery {
            project_id,
            status,
            workspace_id,
            limit,
            offset,
        })
    }
}

#[derive(Debug, Clone)]
struct ValidatedConversationListQuery {
    project_id: String,
    status: Option<String>,
    workspace_id: Option<String>,
    limit: i64,
    offset: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct CreateConversationRequest {
    project_id: String,
    title: Option<String>,
    agent_config: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct UpdateConversationModeRequest {
    #[serde(default)]
    conversation_mode: Option<Option<String>>,
    #[serde(default)]
    workspace_id: Option<Option<String>>,
    #[serde(default)]
    linked_workspace_task_id: Option<Option<String>>,
}

#[derive(Debug, Clone, Deserialize)]
struct ModeProjectQuery {
    project_id: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ConversationMessagesQuery {
    project_id: String,
    limit: Option<i64>,
    from_time_us: Option<i64>,
    from_counter: Option<i64>,
    before_time_us: Option<i64>,
    before_counter: Option<i64>,
}

impl ConversationMessagesQuery {
    fn validated(&self) -> Result<ValidatedMessagesQuery, AgentConversationsApiError> {
        let project_id = required_trimmed(&self.project_id, "project_id")?.to_string();
        let limit = self.limit.unwrap_or(DEFAULT_TIMELINE_LIMIT);
        if !(1..=MAX_TIMELINE_LIMIT).contains(&limit) {
            return Err(AgentConversationsApiError::unprocessable(
                "limit must be between 1 and 500",
            ));
        }
        let from_time_us = self.from_time_us.unwrap_or_default();
        let from_counter = self.from_counter.unwrap_or_default();
        let before_time_us = self.before_time_us;
        let before_counter = self.before_counter;
        if from_time_us < 0 || from_counter < 0 {
            return Err(AgentConversationsApiError::unprocessable(
                "from cursors must be greater than or equal to 0",
            ));
        }
        if before_time_us.is_some_and(|value| value < 0)
            || before_counter.is_some_and(|value| value < 0)
        {
            return Err(AgentConversationsApiError::unprocessable(
                "before cursors must be greater than or equal to 0",
            ));
        }
        Ok(ValidatedMessagesQuery {
            project_id,
            limit,
            from_time_us,
            from_counter,
            before_time_us,
            before_counter,
        })
    }
}

#[derive(Debug, Clone)]
struct ValidatedMessagesQuery {
    project_id: String,
    limit: i64,
    from_time_us: i64,
    from_counter: i64,
    before_time_us: Option<i64>,
    before_counter: Option<i64>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct AgentConversationResponse {
    id: String,
    project_id: String,
    user_id: String,
    tenant_id: String,
    title: String,
    status: String,
    message_count: i32,
    created_at: String,
    updated_at: Option<String>,
    summary: Option<String>,
    agent_config: Option<Value>,
    metadata: Option<Value>,
    parent_conversation_id: Option<String>,
    branch_point_message_id: Option<String>,
    conversation_mode: Option<String>,
    workspace_id: Option<String>,
    linked_workspace_task_id: Option<String>,
    workspace_name: Option<String>,
    participant_agents: Vec<String>,
    coordinator_agent_id: Option<String>,
    focused_agent_id: Option<String>,
}

impl From<AgentConversationRecord> for AgentConversationResponse {
    fn from(record: AgentConversationRecord) -> Self {
        Self {
            id: record.id,
            project_id: record.project_id,
            user_id: record.user_id,
            tenant_id: record.tenant_id,
            title: record.title,
            status: record.status,
            message_count: record.message_count,
            created_at: format_optional_time(record.created_at).unwrap_or_default(),
            updated_at: format_optional_time(record.updated_at),
            summary: record.summary,
            agent_config: record.agent_config,
            metadata: record.metadata,
            parent_conversation_id: record.parent_conversation_id,
            branch_point_message_id: record.branch_point_message_id,
            conversation_mode: record.conversation_mode,
            workspace_id: record.workspace_id,
            linked_workspace_task_id: record.linked_workspace_task_id,
            workspace_name: record.workspace_name,
            participant_agents: value_string_array(record.participant_agents.as_ref()),
            coordinator_agent_id: record.coordinator_agent_id,
            focused_agent_id: record.focused_agent_id,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct PaginatedConversationsResponse {
    items: Vec<AgentConversationResponse>,
    total: i64,
    has_more: bool,
    offset: i64,
    limit: i64,
    next_offset: Option<i64>,
}

impl PaginatedConversationsResponse {
    fn new(items: Vec<AgentConversationResponse>, total: i64, limit: i64, offset: i64) -> Self {
        let next_offset = (offset + limit).min(total);
        Self {
            items,
            total,
            has_more: next_offset < total,
            offset,
            limit,
            next_offset: if next_offset < total {
                Some(next_offset)
            } else {
                None
            },
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct ConversationMessagesResponse {
    #[serde(rename = "conversationId")]
    conversation_id: String,
    timeline: Vec<TimelineItem>,
    total: usize,
    has_more: bool,
    first_time_us: Option<i64>,
    first_counter: Option<i64>,
    last_time_us: Option<i64>,
    last_counter: Option<i64>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct TimelineItem {
    id: String,
    #[serde(rename = "type")]
    timeline_type: String,
    #[serde(rename = "eventTimeUs")]
    event_time_us: i64,
    #[serde(rename = "eventCounter")]
    event_counter: i64,
    timestamp: Option<i64>,
    #[serde(flatten)]
    fields: Map<String, Value>,
}

#[derive(Debug)]
pub(crate) struct AgentConversationsApiError {
    status: StatusCode,
    detail: String,
}

impl AgentConversationsApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    pub(crate) fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for AgentConversationsApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

fn build_timeline(
    events: &[AgentExecutionEventRecord],
    tool_exec_map: &BTreeMap<String, ToolExecutionInfo>,
    hitl_answered_map: &BTreeMap<String, Value>,
    hitl_status_map: &BTreeMap<String, HitlStatusInfo>,
    artifact_ready_map: &BTreeMap<String, ArtifactReadyInfo>,
    artifact_error_map: &BTreeMap<String, String>,
    completion_map: &BTreeMap<String, Value>,
) -> Vec<TimelineItem> {
    events
        .iter()
        .filter_map(|event| {
            let mut fields = event_fields(
                event,
                tool_exec_map,
                hitl_answered_map,
                hitl_status_map,
                artifact_ready_map,
                artifact_error_map,
                completion_map,
            )?;
            let timeline_type = fields
                .remove("__timeline_type")
                .and_then(|value| value.as_str().map(ToString::to_string))
                .unwrap_or_else(|| event.event_type.clone());
            Some(TimelineItem {
                id: timeline_event_id(event),
                timeline_type,
                event_time_us: event.event_time_us,
                event_counter: i64::from(event.event_counter),
                timestamp: Some(event.event_time_us / 1000),
                fields,
            })
        })
        .collect()
}

fn event_fields(
    event: &AgentExecutionEventRecord,
    tool_exec_map: &BTreeMap<String, ToolExecutionInfo>,
    hitl_answered_map: &BTreeMap<String, Value>,
    hitl_status_map: &BTreeMap<String, HitlStatusInfo>,
    artifact_ready_map: &BTreeMap<String, ArtifactReadyInfo>,
    artifact_error_map: &BTreeMap<String, String>,
    completion_map: &BTreeMap<String, Value>,
) -> Option<Map<String, Value>> {
    let data = event.event_data.as_object();
    match event.event_type.as_str() {
        "artifact_ready" | "artifact_error" => None,
        "user_message" => Some(fields_from_pairs([
            (
                "message_id",
                optional_string_value(
                    string_value(data, "message_id").or_else(|| event.message_id.clone()),
                ),
            ),
            (
                "content",
                string_value(data, "content").unwrap_or_default().into(),
            ),
            ("role", "user".into()),
        ])),
        "assistant_message" => Some(assistant_fields(event, data, completion_map)),
        "thought" => {
            let content =
                string_value(data, "thought").or_else(|| string_value(data, "content"))?;
            if content.trim().is_empty() {
                None
            } else {
                Some(fields_from_pairs([("content", content.into())]))
            }
        }
        "act" => Some(act_fields(event, data, tool_exec_map, false)),
        "act_delta" => Some(act_fields(event, data, tool_exec_map, true)),
        "observe" => Some(observe_fields(data)),
        "error" => Some(error_fields(event, data)),
        "work_plan" => Some(fields_from_pairs([
            ("steps", value_or(data, "steps", json!([]))),
            ("status", value_or(data, "status", json!("planning"))),
        ])),
        "task_start" => Some(fields_from_pairs([
            (
                "taskId",
                string_value(data, "task_id").unwrap_or_default().into(),
            ),
            (
                "content",
                string_value(data, "content").unwrap_or_default().into(),
            ),
            ("orderIndex", value_or(data, "order_index", json!(0))),
            ("totalTasks", value_or(data, "total_tasks", json!(0))),
        ])),
        "task_complete" => Some(fields_from_pairs([
            (
                "taskId",
                string_value(data, "task_id").unwrap_or_default().into(),
            ),
            ("status", value_or(data, "status", json!("completed"))),
            ("orderIndex", value_or(data, "order_index", json!(0))),
            ("totalTasks", value_or(data, "total_tasks", json!(0))),
        ])),
        "artifact_created" => Some(artifact_created_fields(
            data,
            artifact_ready_map,
            artifact_error_map,
        )),
        "clarification_asked" => Some(hitl_question_fields(
            data,
            hitl_answered_map,
            hitl_status_map,
            "answer",
        )),
        "decision_asked" => Some(hitl_question_fields(
            data,
            hitl_answered_map,
            hitl_status_map,
            "decision",
        )),
        "env_var_requested" => Some(env_var_fields(data, hitl_answered_map, hitl_status_map)),
        "permission_asked" | "permission_requested" => {
            Some(permission_fields(data, hitl_answered_map, hitl_status_map))
        }
        "clarification_answered"
        | "decision_answered"
        | "env_var_provided"
        | "permission_granted"
        | "permission_replied" => Some(generic_with_payload(event)),
        _ => Some(generic_with_payload(event)),
    }
}

fn error_fields(
    event: &AgentExecutionEventRecord,
    data: Option<&Map<String, Value>>,
) -> Map<String, Value> {
    let message = string_value(data, "message")
        .or_else(|| string_value(data, "error"))
        .unwrap_or_else(|| "Agent run failed".to_string());
    fields_from_pairs([
        (
            "message_id",
            optional_string_value(
                string_value(data, "message_id").or_else(|| event.message_id.clone()),
            ),
        ),
        ("content", message.clone().into()),
        ("error", message.into()),
        ("isError", json!(true)),
        ("payload", event.event_data.clone()),
    ])
}

fn assistant_fields(
    event: &AgentExecutionEventRecord,
    data: Option<&Map<String, Value>>,
    completion_map: &BTreeMap<String, Value>,
) -> Map<String, Value> {
    let mut fields = fields_from_pairs([
        (
            "message_id",
            optional_string_value(
                string_value(data, "message_id").or_else(|| event.message_id.clone()),
            ),
        ),
        (
            "content",
            string_value(data, "content").unwrap_or_default().into(),
        ),
        ("role", "assistant".into()),
    ]);
    let completion = completion_map.get(&timeline_event_id(event));
    if let Some(artifacts) = value_from(data, "artifacts").or_else(|| {
        completion
            .and_then(Value::as_object)
            .and_then(|map| map.get("artifacts"))
            .cloned()
    }) {
        fields.insert("artifacts".to_string(), artifacts);
    }
    let mut metadata = Map::new();
    if let Some(trace_url) = string_value(data, "trace_url").or_else(|| {
        completion
            .and_then(Value::as_object)
            .and_then(|map| map.get("trace_url"))
            .and_then(Value::as_str)
            .map(ToString::to_string)
    }) {
        metadata.insert("traceUrl".to_string(), Value::String(trace_url));
    }
    if let Some(execution_summary) = value_from(data, "execution_summary").or_else(|| {
        completion
            .and_then(Value::as_object)
            .and_then(|map| map.get("execution_summary"))
            .cloned()
    }) {
        metadata.insert("executionSummary".to_string(), execution_summary);
    }
    if !metadata.is_empty() {
        fields.insert("metadata".to_string(), Value::Object(metadata));
    }
    fields
}

fn act_fields(
    event: &AgentExecutionEventRecord,
    data: Option<&Map<String, Value>>,
    tool_exec_map: &BTreeMap<String, ToolExecutionInfo>,
    from_delta: bool,
) -> Map<String, Value> {
    let tool_name = string_value(data, "tool_name").unwrap_or_default();
    let execution_id = string_value(data, "tool_execution_id")
        .or_else(|| string_value(data, "execution_id"))
        .or_else(|| string_value(data, "call_id"));
    let tool_input = if from_delta {
        parse_accumulated_arguments(value_from(data, "accumulated_arguments"))
    } else {
        value_from(data, "tool_input").unwrap_or_else(|| json!({}))
    };
    let mut fields = fields_from_pairs([
        ("toolName", tool_name.clone().into()),
        ("toolInput", tool_input),
    ]);
    copy_tool_display_fields(&mut fields, data);
    if let Some(execution_id) = execution_id.clone() {
        fields.insert("execution_id".to_string(), execution_id.into());
    }
    for key in tool_lookup_keys(
        event.message_id.as_deref(),
        execution_id.as_deref(),
        &tool_name,
    ) {
        if let Some(execution) = tool_exec_map.get(&key) {
            fields.insert("execution".to_string(), execution.to_value());
            break;
        }
    }
    if from_delta {
        fields.insert("__timeline_type".to_string(), "act".into());
        fields.insert(
            "metadata".to_string(),
            json!({"sourceEventType": "act_delta", "status": string_value(data, "status").unwrap_or_else(|| "preparing".to_string())}),
        );
    }
    fields
}

fn observe_fields(data: Option<&Map<String, Value>>) -> Map<String, Value> {
    let mut fields = fields_from_pairs([
        (
            "toolName",
            string_value(data, "tool_name").unwrap_or_default().into(),
        ),
        (
            "toolOutput",
            string_value(data, "observation")
                .or_else(|| string_value(data, "tool_output"))
                .unwrap_or_default()
                .into(),
        ),
        ("isError", value_or(data, "is_error", json!(false))),
    ]);
    copy_tool_display_fields(&mut fields, data);
    if let Some(execution_id) = string_value(data, "tool_execution_id")
        .or_else(|| string_value(data, "execution_id"))
        .or_else(|| string_value(data, "call_id"))
    {
        fields.insert("execution_id".to_string(), execution_id.into());
    }
    fields
}

fn copy_tool_display_fields(fields: &mut Map<String, Value>, data: Option<&Map<String, Value>>) {
    copy_object_or_raw_metadata(fields, data, "display", "display", "rawDisplay");
    if value_from(data, "fileMetadata").is_some() {
        copy_object_or_raw_metadata(
            fields,
            data,
            "fileMetadata",
            "fileMetadata",
            "rawFileMetadata",
        );
    } else {
        copy_object_or_raw_metadata(
            fields,
            data,
            "file_metadata",
            "fileMetadata",
            "rawFileMetadata",
        );
    }
}

fn copy_object_or_raw_metadata(
    fields: &mut Map<String, Value>,
    data: Option<&Map<String, Value>>,
    source_key: &str,
    target_key: &str,
    raw_key: &str,
) {
    if let Some(value) = value_from(data, source_key) {
        if value.is_object() {
            fields.insert(target_key.to_string(), value);
        } else {
            insert_metadata_value(fields, raw_key, value);
        }
    }
}

fn insert_metadata_value(fields: &mut Map<String, Value>, key: &str, value: Value) {
    let entry = fields
        .entry("metadata".to_string())
        .or_insert_with(|| Value::Object(Map::new()));
    if let Value::Object(metadata) = entry {
        metadata.insert(key.to_string(), value);
    } else {
        let mut metadata = Map::new();
        metadata.insert(key.to_string(), value);
        *entry = Value::Object(metadata);
    }
}

fn artifact_created_fields(
    data: Option<&Map<String, Value>>,
    ready_map: &BTreeMap<String, ArtifactReadyInfo>,
    error_map: &BTreeMap<String, String>,
) -> Map<String, Value> {
    let artifact_id = string_value(data, "artifact_id").unwrap_or_default();
    let mut fields = fields_from_pairs([
        ("artifactId", artifact_id.clone().into()),
        (
            "filename",
            string_value(data, "filename").unwrap_or_default().into(),
        ),
        (
            "mimeType",
            string_value(data, "mime_type").unwrap_or_default().into(),
        ),
        (
            "category",
            string_value(data, "category")
                .unwrap_or_else(|| "other".to_string())
                .into(),
        ),
        ("sizeBytes", value_or(data, "size_bytes", json!(0))),
        ("url", string_value(data, "url").unwrap_or_default().into()),
        (
            "previewUrl",
            string_value(data, "preview_url").unwrap_or_default().into(),
        ),
        (
            "sourceTool",
            string_value(data, "source_tool").unwrap_or_default().into(),
        ),
        (
            "sourcePath",
            string_value(data, "source_path").unwrap_or_default().into(),
        ),
        ("metadata", value_or(data, "metadata", json!({}))),
    ]);
    if let Some(ready) = ready_map.get(&artifact_id) {
        if let Some(url) = &ready.url {
            fields.insert("url".to_string(), url.clone().into());
        }
        if let Some(preview_url) = &ready.preview_url {
            fields.insert("previewUrl".to_string(), preview_url.clone().into());
        }
    }
    if let Some(error) = error_map.get(&artifact_id) {
        fields.insert("error".to_string(), error.clone().into());
    }
    fields
}

fn hitl_question_fields(
    data: Option<&Map<String, Value>>,
    answered_map: &BTreeMap<String, Value>,
    status_map: &BTreeMap<String, HitlStatusInfo>,
    response_field: &str,
) -> Map<String, Value> {
    let request_id = string_value(data, "request_id").unwrap_or_default();
    let (answered, answer) =
        resolve_hitl_answer(&request_id, response_field, answered_map, status_map);
    let mut fields = fields_from_pairs([
        ("requestId", request_id.into()),
        (
            "question",
            string_value(data, "question").unwrap_or_default().into(),
        ),
        ("options", value_or(data, "options", json!([]))),
        ("allowCustom", value_or(data, "allow_custom", json!(true))),
        ("answered", answered.into()),
    ]);
    if let Some(answer) = answer {
        fields.insert(response_field.to_string(), answer);
    }
    fields
}

fn env_var_fields(
    data: Option<&Map<String, Value>>,
    answered_map: &BTreeMap<String, Value>,
    status_map: &BTreeMap<String, HitlStatusInfo>,
) -> Map<String, Value> {
    let request_id = string_value(data, "request_id").unwrap_or_default();
    let (answered, values) = resolve_hitl_answer(&request_id, "values", answered_map, status_map);
    let mut fields = fields_from_pairs([
        ("requestId", request_id.into()),
        (
            "toolName",
            string_value(data, "tool_name").unwrap_or_default().into(),
        ),
        ("fields", value_or(data, "fields", json!([]))),
        (
            "message",
            string_value(data, "message").unwrap_or_default().into(),
        ),
        ("context", value_or(data, "context", json!({}))),
        ("answered", answered.into()),
    ]);
    if let Some(values) = values {
        fields.insert("values".to_string(), values);
    }
    fields
}

fn permission_fields(
    data: Option<&Map<String, Value>>,
    answered_map: &BTreeMap<String, Value>,
    status_map: &BTreeMap<String, HitlStatusInfo>,
) -> Map<String, Value> {
    let request_id = string_value(data, "request_id").unwrap_or_default();
    let (answered, granted) = resolve_hitl_answer(&request_id, "granted", answered_map, status_map);
    let mut fields = fields_from_pairs([
        ("requestId", request_id.into()),
        (
            "action",
            string_value(data, "action").unwrap_or_default().into(),
        ),
        (
            "resource",
            string_value(data, "resource").unwrap_or_default().into(),
        ),
        (
            "reason",
            string_value(data, "reason").unwrap_or_default().into(),
        ),
        (
            "toolName",
            string_value(data, "tool_name").unwrap_or_default().into(),
        ),
        (
            "riskLevel",
            string_value(data, "risk_level")
                .unwrap_or_else(|| "medium".to_string())
                .into(),
        ),
        ("answered", answered.into()),
    ]);
    if let Some(granted) = granted {
        fields.insert("granted".to_string(), granted);
    }
    fields
}

fn generic_with_payload(event: &AgentExecutionEventRecord) -> Map<String, Value> {
    let mut fields = Map::new();
    fields.insert("payload".to_string(), event.event_data.clone());
    fields
}

fn completion_map(events: &[AgentExecutionEventRecord]) -> BTreeMap<String, Value> {
    let mut by_message: BTreeMap<String, Vec<&AgentExecutionEventRecord>> = BTreeMap::new();
    for event in events {
        if let Some(message_id) = &event.message_id {
            by_message
                .entry(message_id.clone())
                .or_default()
                .push(event);
        }
    }
    let mut completion = BTreeMap::new();
    for events in by_message.values() {
        let assistant = events
            .iter()
            .rev()
            .find(|event| event.event_type == "assistant_message");
        let complete = events
            .iter()
            .rev()
            .find(|event| event.event_type == "complete");
        if let (Some(assistant), Some(complete)) = (assistant, complete) {
            completion.insert(timeline_event_id(assistant), complete.event_data.clone());
        }
    }
    completion
}

fn artifact_maps<'a>(
    events: impl Iterator<Item = &'a AgentExecutionEventRecord>,
) -> (
    BTreeMap<String, ArtifactReadyInfo>,
    BTreeMap<String, String>,
) {
    let mut ready = BTreeMap::new();
    let mut errors = BTreeMap::new();
    for event in events {
        let data = event.event_data.as_object();
        match event.event_type.as_str() {
            "artifact_ready" => {
                if let Some(artifact_id) = string_value(data, "artifact_id") {
                    ready.insert(
                        artifact_id,
                        ArtifactReadyInfo {
                            url: string_value(data, "url"),
                            preview_url: string_value(data, "preview_url"),
                        },
                    );
                }
            }
            "artifact_error" => {
                if let Some(artifact_id) = string_value(data, "artifact_id") {
                    errors.insert(
                        artifact_id,
                        string_value(data, "error").unwrap_or_else(|| "Upload failed".to_string()),
                    );
                }
            }
            _ => {}
        }
    }
    (ready, errors)
}

fn tool_execution_map(records: Vec<ToolExecutionRecord>) -> BTreeMap<String, ToolExecutionInfo> {
    let mut map = BTreeMap::new();
    for record in records {
        let info = ToolExecutionInfo {
            execution_id: Some(record.id.clone()),
            start_time: record.started_at.map(timestamp_millis),
            end_time: record.completed_at.map(timestamp_millis),
            duration: record.duration_ms.map(i64::from),
        };
        map.insert(
            format!("{}:{}", record.message_id, record.call_id),
            info.clone(),
        );
        map.insert(format!("{}:{}", record.message_id, record.id), info.clone());
        map.entry(format!("{}:{}", record.message_id, record.tool_name))
            .or_insert(info);
    }
    map
}

fn hitl_answered_map(events: &[AgentExecutionEventRecord]) -> BTreeMap<String, Value> {
    let mut map = BTreeMap::new();
    for event in events {
        let data = event.event_data.as_object();
        let Some(request_id) = string_value(data, "request_id") else {
            continue;
        };
        let value = match event.event_type.as_str() {
            "clarification_answered" => json!({"answer": value_or(data, "answer", Value::Null)}),
            "decision_answered" => json!({"decision": value_or(data, "decision", Value::Null)}),
            "env_var_provided" => json!({"values": value_or(data, "values", json!({}))}),
            "permission_granted" | "permission_replied" => {
                json!({"granted": value_or(data, "granted", json!(false))})
            }
            _ => continue,
        };
        map.insert(request_id, value);
    }
    map
}

fn hitl_status_map(records: Vec<HitlRequestRecord>) -> BTreeMap<String, HitlStatusInfo> {
    records
        .into_iter()
        .map(|record| {
            (
                record.id,
                HitlStatusInfo {
                    status: record.status,
                    response: record.response,
                    response_metadata: record.response_metadata.unwrap_or_else(|| json!({})),
                },
            )
        })
        .collect()
}

fn resolve_hitl_answer(
    request_id: &str,
    field_name: &str,
    answered_map: &BTreeMap<String, Value>,
    status_map: &BTreeMap<String, HitlStatusInfo>,
) -> (bool, Option<Value>) {
    if let Some(value) = answered_map
        .get(request_id)
        .and_then(Value::as_object)
        .and_then(|map| map.get(field_name))
    {
        return (true, Some(value.clone()));
    }
    if let Some(status) = status_map.get(request_id) {
        if matches!(status.status.as_str(), "answered" | "completed") {
            if let Some(value) = status
                .response_metadata
                .as_object()
                .and_then(|map| map.get(field_name))
            {
                return (true, Some(value.clone()));
            }
            return (true, status.response.clone().map(Value::String));
        }
    }
    (false, None)
}

fn stream_payload_to_record(payload: &str) -> Option<AgentExecutionEventRecord> {
    let parsed: Value = serde_json::from_str(payload).ok()?;
    let event_type = parsed
        .get("type")
        .or_else(|| parsed.get("event_type"))
        .and_then(Value::as_str)?
        .to_string();
    let event_data = parsed
        .get("data")
        .or_else(|| parsed.get("payload"))
        .cloned()
        .unwrap_or(Value::Null);
    let event_time_us = parsed
        .get("event_time_us")
        .or_else(|| parsed.get("time_us"))
        .and_then(Value::as_i64)?;
    let event_counter = parsed
        .get("event_counter")
        .or_else(|| parsed.get("counter"))
        .and_then(Value::as_i64)
        .unwrap_or_default()
        .try_into()
        .ok()?;
    let message_id = parsed
        .get("message_id")
        .or_else(|| parsed.pointer("/data/message_id"))
        .and_then(Value::as_str)
        .map(ToString::to_string);
    Some(AgentExecutionEventRecord {
        message_id,
        event_type,
        event_data,
        event_time_us,
        event_counter,
        created_at: None,
    })
}

fn page_dev_events(
    events: Vec<AgentExecutionEventRecord>,
    query: &ValidatedMessagesQuery,
) -> Vec<AgentExecutionEventRecord> {
    if let Some(before_time_us) = query.before_time_us {
        let before_counter = query.before_counter.unwrap_or_default();
        let mut page = events
            .into_iter()
            .filter(|event| {
                (event.event_time_us, i64::from(event.event_counter))
                    < (before_time_us, before_counter)
            })
            .collect::<Vec<_>>();
        page.sort_by_key(|event| (event.event_time_us, event.event_counter));
        let len = page.len();
        page.into_iter()
            .skip(len.saturating_sub(query.limit as usize))
            .collect()
    } else if query.from_time_us > 0 {
        events
            .into_iter()
            .filter(|event| {
                (event.event_time_us, i64::from(event.event_counter))
                    > (query.from_time_us, query.from_counter)
            })
            .take(query.limit as usize)
            .collect()
    } else {
        let len = events.len();
        events
            .into_iter()
            .skip(len.saturating_sub(query.limit as usize))
            .collect()
    }
}

#[derive(Debug, Clone)]
struct ToolExecutionInfo {
    execution_id: Option<String>,
    start_time: Option<i64>,
    end_time: Option<i64>,
    duration: Option<i64>,
}

impl ToolExecutionInfo {
    fn to_value(&self) -> Value {
        let mut map = Map::new();
        if let Some(execution_id) = &self.execution_id {
            map.insert("_execution_id".to_string(), execution_id.clone().into());
        }
        if let Some(start_time) = self.start_time {
            map.insert("startTime".to_string(), start_time.into());
        }
        if let Some(end_time) = self.end_time {
            map.insert("endTime".to_string(), end_time.into());
        }
        if let Some(duration) = self.duration {
            map.insert("duration".to_string(), duration.into());
        }
        Value::Object(map)
    }
}

#[derive(Debug, Clone)]
struct HitlStatusInfo {
    status: String,
    response: Option<String>,
    response_metadata: Value,
}

#[derive(Debug, Clone)]
struct ArtifactReadyInfo {
    url: Option<String>,
    preview_url: Option<String>,
}

fn fields_from_pairs<const N: usize>(pairs: [(&str, Value); N]) -> Map<String, Value> {
    pairs
        .into_iter()
        .map(|(key, value)| (key.to_string(), value))
        .collect()
}

fn required_trimmed<'a>(
    value: &'a str,
    field: &str,
) -> Result<&'a str, AgentConversationsApiError> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        Err(AgentConversationsApiError::unprocessable(format!(
            "{field} is required"
        )))
    } else {
        Ok(trimmed)
    }
}

fn format_optional_time(value: Option<DateTime<Utc>>) -> Option<String> {
    value.map(|timestamp| timestamp.to_rfc3339())
}

fn timestamp_millis(value: DateTime<Utc>) -> i64 {
    value.timestamp_millis()
}

fn timeline_event_id(event: &AgentExecutionEventRecord) -> String {
    format!(
        "{}-{}-{}",
        event.event_type, event.event_time_us, event.event_counter
    )
}

fn excluded_event_types() -> Vec<String> {
    TIMELINE_EXCLUDED_EVENT_TYPES
        .iter()
        .map(|event_type| (*event_type).to_string())
        .collect()
}

fn value_string_array(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn value_from(data: Option<&Map<String, Value>>, key: &str) -> Option<Value> {
    data.and_then(|map| map.get(key)).cloned()
}

fn value_or(data: Option<&Map<String, Value>>, key: &str, fallback: Value) -> Value {
    value_from(data, key).unwrap_or(fallback)
}

fn string_value(data: Option<&Map<String, Value>>, key: &str) -> Option<String> {
    data.and_then(|map| map.get(key)).and_then(|value| {
        value
            .as_str()
            .map(ToString::to_string)
            .or_else(|| value.as_i64().map(|number| number.to_string()))
            .or_else(|| value.as_u64().map(|number| number.to_string()))
    })
}

fn optional_string_value(value: Option<String>) -> Value {
    value.map(Value::String).unwrap_or(Value::Null)
}

fn parse_accumulated_arguments(value: Option<Value>) -> Value {
    match value {
        Some(Value::String(raw)) => serde_json::from_str::<Value>(&raw)
            .unwrap_or_else(|_| json!({"partial_arguments": raw})),
        Some(value @ (Value::Object(_) | Value::Array(_))) => value,
        Some(other) => json!({"arguments": other}),
        None => json!({}),
    }
}

fn tool_lookup_keys(
    message_id: Option<&str>,
    execution_id: Option<&str>,
    tool_name: &str,
) -> Vec<String> {
    let Some(message_id) = message_id else {
        return Vec::new();
    };
    let mut keys = Vec::new();
    if let Some(execution_id) = execution_id {
        keys.push(format!("{message_id}:{execution_id}"));
    }
    if !tool_name.is_empty() {
        keys.push(format!("{message_id}:{tool_name}"));
    }
    keys
}

#[cfg(test)]
mod tests {
    use agistack_adapters_mem::InMemoryEventStream;

    use super::*;

    fn event(event_type: &str, time: i64, data: Value) -> AgentExecutionEventRecord {
        AgentExecutionEventRecord {
            message_id: Some("m1".to_string()),
            event_type: event_type.to_string(),
            event_data: data,
            event_time_us: time,
            event_counter: 1,
            created_at: None,
        }
    }

    #[test]
    fn agent_timeline_builds_user_and_assistant_messages() {
        let timeline = build_timeline(
            &[
                event("user_message", 10, json!({"content": "hello"})),
                event("assistant_message", 20, json!({"content": "hi"})),
            ],
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
        );

        assert_eq!(timeline.len(), 2);
        assert_eq!(timeline[0].timeline_type, "user_message");
        assert_eq!(timeline[0].fields["role"], "user");
        assert_eq!(timeline[1].fields["content"], "hi");
    }

    #[test]
    fn agent_timeline_merges_tool_execution_metadata() {
        let mut tools = BTreeMap::new();
        tools.insert(
            "m1:call-1".to_string(),
            ToolExecutionInfo {
                execution_id: Some("exec-1".to_string()),
                start_time: Some(100),
                end_time: Some(120),
                duration: Some(20),
            },
        );
        let timeline = build_timeline(
            &[event(
                "act",
                10,
                json!({"tool_name": "shell", "tool_input": {"cmd": "pwd"}, "call_id": "call-1"}),
            )],
            &tools,
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
        );

        assert_eq!(timeline[0].fields["toolName"], "shell");
        assert_eq!(timeline[0].fields["execution"]["duration"], 20);
    }

    #[test]
    fn agent_timeline_passes_through_tool_display_metadata() {
        let display = json!({"title": "Read app.py", "summary": "Inspect the app entry point"});
        let file_metadata = json!({
            "operation": "read",
            "paths": [{"path": "/workspace/src/app.py", "relativePath": "src/app.py"}]
        });
        let timeline = build_timeline(
            &[event(
                "observe",
                10,
                json!({
                    "tool_name": "read",
                    "observation": "content",
                    "display": display,
                    "fileMetadata": file_metadata
                }),
            )],
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
        );

        assert_eq!(timeline[0].fields["display"]["title"], "Read app.py");
        assert_eq!(timeline[0].fields["fileMetadata"]["operation"], "read");
    }

    #[test]
    fn agent_timeline_keeps_invalid_display_raw_metadata() {
        let timeline = build_timeline(
            &[event(
                "act",
                10,
                json!({
                    "tool_name": "read",
                    "tool_input": {"file_path": "src/app.py"},
                    "display": "not an object",
                    "fileMetadata": ["not", "an", "object"]
                }),
            )],
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
        );

        assert!(timeline[0].fields.get("display").is_none());
        assert!(timeline[0].fields.get("fileMetadata").is_none());
        assert_eq!(
            timeline[0].fields["metadata"]["rawDisplay"],
            "not an object"
        );
        assert_eq!(
            timeline[0].fields["metadata"]["rawFileMetadata"],
            json!(["not", "an", "object"])
        );
    }

    #[test]
    fn agent_timeline_marks_hitl_answered_from_status_map() {
        let mut status = BTreeMap::new();
        status.insert(
            "hitl-1".to_string(),
            HitlStatusInfo {
                status: "answered".to_string(),
                response: Some("yes".to_string()),
                response_metadata: json!({}),
            },
        );
        let timeline = build_timeline(
            &[event(
                "clarification_asked",
                10,
                json!({"request_id": "hitl-1", "question": "Continue?"}),
            )],
            &BTreeMap::new(),
            &BTreeMap::new(),
            &status,
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeMap::new(),
        );

        assert_eq!(timeline[0].fields["answered"], true);
        assert_eq!(timeline[0].fields["answer"], "yes");
    }

    #[test]
    fn agent_conversations_pagination_uses_python_shape() {
        let response = PaginatedConversationsResponse::new(Vec::new(), 7, 5, 0);

        assert_eq!(response.total, 7);
        assert!(response.has_more);
        assert_eq!(response.next_offset, Some(5));
    }

    #[tokio::test]
    async fn dev_conversation_event_subscription_access_is_owner_scoped() {
        let events: Arc<dyn EventStream> = Arc::new(InMemoryEventStream::new());
        let service = DevAgentConversationService::new(events);
        let conversation = service
            .create_conversation(
                "user-a",
                CreateConversationRequest {
                    project_id: "project-a".to_string(),
                    title: Some("Private session".to_string()),
                    agent_config: None,
                },
            )
            .await
            .expect("conversation creation succeeds");

        assert_eq!(
            service
                .authorize_event_subscription("user-a", &conversation.id)
                .await
                .expect("owner access resolves"),
            ConversationSocketAccess::Allowed
        );
        assert_eq!(
            service
                .authorize_event_subscription("user-b", &conversation.id)
                .await
                .expect("non-owner access resolves"),
            ConversationSocketAccess::Denied
        );
        assert_eq!(
            service
                .authorize_event_subscription("user-a", "missing-conversation")
                .await
                .expect("missing access resolves"),
            ConversationSocketAccess::NotFound
        );
        assert_eq!(
            service
                .authorize_message_send("user-a", &conversation.id, "project-a")
                .await
                .expect("message access resolves"),
            ConversationSocketAccess::Allowed
        );
        assert_eq!(
            service
                .authorize_message_send("user-a", &conversation.id, "project-b")
                .await
                .expect("project mismatch resolves"),
            ConversationSocketAccess::Denied
        );
        assert_eq!(
            service
                .authorize_session_stop("user-a", &conversation.id)
                .await
                .expect("owner stop access resolves"),
            ConversationSocketAccess::Allowed
        );
        assert_eq!(
            service
                .authorize_session_stop("user-b", &conversation.id)
                .await
                .expect("non-owner stop access resolves"),
            ConversationSocketAccess::Denied
        );
    }

    #[tokio::test]
    async fn dev_session_projection_requires_exact_tenant_project_workspace_scope() {
        let events: Arc<dyn EventStream> = Arc::new(InMemoryEventStream::new());
        let service = DevAgentConversationService::new(events);
        let conversation = service
            .create_conversation(
                "dev-user",
                CreateConversationRequest {
                    project_id: "project-1".to_string(),
                    title: Some("Scoped session".to_string()),
                    agent_config: Some(json!({"capability_mode": "code"})),
                },
            )
            .await
            .expect("conversation must be created");
        let query = ConversationSessionQuery {
            tenant_id: "dev-tenant".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: None,
        };
        let projection = service
            .get_session_projection("dev-user", &conversation.id, query.clone())
            .await
            .expect("exact scope must project");
        let payload = serde_json::to_value(projection).expect("projection must serialize");
        assert_eq!(payload["schema_version"], 2);
        assert_eq!(payload["conversation"]["current_mode"], "build");
        assert_eq!(payload["conversation"]["capability_mode"], "code");

        for denied_query in [
            ConversationSessionQuery {
                tenant_id: "wrong-tenant".to_string(),
                ..query.clone()
            },
            ConversationSessionQuery {
                project_id: "wrong-project".to_string(),
                ..query.clone()
            },
            ConversationSessionQuery {
                workspace_id: Some("wrong-workspace".to_string()),
                ..query
            },
        ] {
            assert!(service
                .get_session_projection("dev-user", &conversation.id, denied_query)
                .await
                .is_err());
        }
    }
}
