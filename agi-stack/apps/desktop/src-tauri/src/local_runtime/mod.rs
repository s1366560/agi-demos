use std::{
    collections::{HashMap, HashSet},
    io::{Read, Write},
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
};

use agistack_adapters_device::SqliteCheckpointStore;
use agistack_adapters_http_llm::{AnthropicLlm, HttpLlm};
use agistack_adapters_local_tools::LocalToolHost;
use agistack_adapters_mem::SystemClock;
use agistack_core::{
    agent::{
        react::{ReActEngine, ReActObserver},
        types::{AgentAction, Role, SessionStatus, TranscriptEntry},
    },
    model::{Entity, Episode},
    ports::{CheckpointStore, CoreError, CoreResult, LlmPort, MemoryDraft, ToolHost},
};
use async_trait::async_trait;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Path, Query, State,
    },
    http::{
        header::{AUTHORIZATION, CONTENT_TYPE},
        HeaderMap, HeaderValue, Method, StatusCode,
    },
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::{get, patch, post},
    Json, Router,
};
use chrono::Utc;
use futures_util::{SinkExt, StreamExt};
use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::{
    net::TcpListener,
    sync::{broadcast, mpsc},
};
use tower_http::cors::{AllowOrigin, CorsLayer};
use uuid::Uuid;

#[derive(Clone)]
pub struct LocalRuntimeService {
    state: Arc<LocalRuntimeState>,
    api_base_url: String,
}

impl LocalRuntimeService {
    pub async fn start(app_data_dir: PathBuf, workspace_root: PathBuf) -> Result<Self, String> {
        std::fs::create_dir_all(&app_data_dir).map_err(|error| error.to_string())?;
        std::fs::create_dir_all(&workspace_root).map_err(|error| error.to_string())?;
        let checkpoint_path = app_data_dir.join("agistack-local-agent-checkpoints.db");
        let checkpoints = Arc::new(
            SqliteCheckpointStore::open(&checkpoint_path.to_string_lossy())
                .map_err(|error| error.to_string())?,
        );
        let tool_host = LocalToolHost::new(&workspace_root).map_err(|error| error.to_string())?;
        let api_token = generate_capability_token();
        let state = Arc::new(LocalRuntimeState::new(
            workspace_root,
            tool_host,
            checkpoints,
            api_token,
        ));

        let app = local_router(Arc::clone(&state));
        let listener = TcpListener::bind(("127.0.0.1", 0))
            .await
            .map_err(|error| error.to_string())?;
        let addr = listener.local_addr().map_err(|error| error.to_string())?;
        let api_base_url = format!("http://{addr}");
        tauri::async_runtime::spawn(async move {
            if let Err(error) = axum::serve(listener, app).await {
                eprintln!("agistack local runtime stopped: {error}");
            }
        });

        Ok(Self {
            state,
            api_base_url,
        })
    }

    pub fn status(&self) -> LocalRuntimeStatus {
        let mut config = self
            .state
            .config
            .lock()
            .expect("local runtime config")
            .clone();
        config.api_key.clear();
        let workspace_root = self
            .state
            .workspace_root
            .lock()
            .expect("local workspace root")
            .to_string_lossy()
            .to_string();
        let tools = self
            .state
            .tool_host
            .lock()
            .expect("local tool host")
            .list_tools();
        LocalRuntimeStatus {
            running: true,
            api_base_url: self.api_base_url.clone(),
            api_token: self.state.api_token.clone(),
            workspace_root,
            tool_count: tools.len(),
            tools,
            config,
        }
    }

    pub fn configure(&self, config: LocalRuntimeConfig) -> Result<LocalRuntimeStatus, String> {
        self.state.configure(config)?;
        Ok(self.status())
    }
}

impl LocalRuntimeState {
    fn configure(&self, config: LocalRuntimeConfig) -> Result<(), String> {
        if !config.workspace_root.trim().is_empty() {
            let root = PathBuf::from(config.workspace_root.trim());
            std::fs::create_dir_all(&root).map_err(|error| error.to_string())?;
            let root = root.canonicalize().map_err(|error| error.to_string())?;
            let host = LocalToolHost::new(&root).map_err(|error| error.to_string())?;
            *self.workspace_root.lock().expect("local workspace root") = root;
            *self.tool_host.lock().expect("local tool host") = host;
        }
        let mut current = self.config.lock().expect("local runtime config");
        *current = config;
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LocalRuntimeConfig {
    pub provider: String,
    pub base_url: String,
    pub model: String,
    #[serde(default, skip_serializing)]
    pub api_key: String,
    pub workspace_root: String,
}

impl Default for LocalRuntimeConfig {
    fn default() -> Self {
        Self {
            provider: "mock".to_string(),
            base_url: "http://127.0.0.1:11434/v1".to_string(),
            model: String::new(),
            api_key: String::new(),
            workspace_root: String::new(),
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct LocalRuntimeStatus {
    pub running: bool,
    pub api_base_url: String,
    pub api_token: String,
    pub workspace_root: String,
    pub tool_count: usize,
    pub tools: Vec<String>,
    pub config: LocalRuntimeConfig,
}

#[derive(Clone, Debug)]
struct LocalConversation {
    id: String,
    project_id: String,
    tenant_id: String,
    title: String,
    workspace_id: Option<String>,
    created_at: String,
    updated_at: String,
}

struct LocalRuntimeState {
    api_token: String,
    workspace_root: Mutex<PathBuf>,
    tool_host: Mutex<LocalToolHost>,
    checkpoints: Arc<SqliteCheckpointStore>,
    clock: Arc<SystemClock>,
    config: Mutex<LocalRuntimeConfig>,
    workspaces: Mutex<Vec<Value>>,
    messages: Mutex<HashMap<String, Vec<Value>>>,
    conversations: Mutex<HashMap<String, LocalConversation>>,
    timelines: Mutex<HashMap<String, Vec<Value>>>,
    event_counter: AtomicU64,
    terminal_counter: AtomicU64,
    terminal_sessions: Mutex<HashSet<String>>,
    agent_runs: Mutex<HashSet<String>>,
    events: broadcast::Sender<Value>,
}

impl LocalRuntimeState {
    fn new(
        workspace_root: PathBuf,
        tool_host: LocalToolHost,
        checkpoints: Arc<SqliteCheckpointStore>,
        api_token: String,
    ) -> Self {
        let (events, _) = broadcast::channel(256);
        let workspace_id = "local-workspace".to_string();
        let now = now_iso();
        let workspace = json!({
            "id": workspace_id,
            "tenant_id": "local",
            "project_id": "local-project",
            "name": "Local workspace",
            "description": "Local desktop runtime workspace",
            "status": "open",
            "created_at": now,
            "updated_at": now,
            "metadata": { "runtime": "local" },
        });
        Self {
            api_token,
            workspace_root: Mutex::new(workspace_root),
            tool_host: Mutex::new(tool_host),
            checkpoints,
            clock: Arc::new(SystemClock),
            config: Mutex::new(LocalRuntimeConfig::default()),
            workspaces: Mutex::new(vec![workspace]),
            messages: Mutex::new(HashMap::new()),
            conversations: Mutex::new(HashMap::new()),
            timelines: Mutex::new(HashMap::new()),
            event_counter: AtomicU64::new(1),
            terminal_counter: AtomicU64::new(1),
            terminal_sessions: Mutex::new(HashSet::new()),
            agent_runs: Mutex::new(HashSet::new()),
            events,
        }
    }

    fn create_terminal_session(&self) -> String {
        let id = self.terminal_counter.fetch_add(1, Ordering::SeqCst);
        let session_id = format!("local-terminal-{id}");
        self.terminal_sessions
            .lock()
            .expect("local terminal sessions")
            .insert(session_id.clone());
        session_id
    }

    fn take_terminal_session(&self, session_id: &str) -> bool {
        self.terminal_sessions
            .lock()
            .expect("local terminal sessions")
            .remove(session_id)
    }

    fn next_event_counter(&self) -> u64 {
        self.event_counter.fetch_add(1, Ordering::SeqCst)
    }

    fn append_timeline(&self, conversation_id: &str, item: Value) {
        let mut timelines = self.timelines.lock().expect("local timelines");
        timelines
            .entry(conversation_id.to_string())
            .or_default()
            .push(item.clone());
        let _ = self.events.send(item);
    }

    fn append_workspace_message(&self, workspace_id: &str, message: Value) {
        let mut messages = self.messages.lock().expect("local messages");
        messages
            .entry(workspace_id.to_string())
            .or_default()
            .push(message);
    }

    async fn run_agent_message(
        self: Arc<Self>,
        conversation_id: String,
        project_id: String,
        message: String,
        message_id: String,
    ) {
        let started = self
            .agent_runs
            .lock()
            .expect("local agent runs")
            .insert(conversation_id.clone());
        if !started {
            let item = self.timeline_item(
                "error",
                conversation_id.clone(),
                None,
                None,
                Some("a local run is already active for this conversation".to_string()),
                json!({ "error": "conversation already running" }),
            );
            self.append_timeline(&conversation_id, item);
            return;
        }

        let user_item = self.timeline_item(
            "user_message",
            conversation_id.clone(),
            Some(message_id),
            Some("user"),
            Some(message.clone()),
            json!({}),
        );
        self.append_timeline(&conversation_id, user_item);

        let observer = Arc::new(LocalTimelineObserver {
            state: Arc::clone(&self),
            conversation_id: conversation_id.clone(),
        });
        let llm = self.llm();
        let tool_host = self.tool_host.lock().expect("local tool host").clone();
        let engine = ReActEngine::new(
            llm,
            Arc::new(tool_host),
            self.checkpoints.clone(),
            self.clock.clone(),
        )
        .with_max_rounds(8);
        let checkpoint_cleanup = match self.checkpoints.load(&conversation_id).await {
            Ok(Some(checkpoint))
                if matches!(
                    checkpoint.status,
                    SessionStatus::Finished | SessionStatus::Failed
                ) =>
            {
                self.checkpoints.delete(&conversation_id).await
            }
            Ok(_) => Ok(()),
            Err(error) => Err(error),
        };
        let result = match checkpoint_cleanup {
            Ok(()) => {
                engine
                    .run_observed(&conversation_id, &message, Some(&project_id), observer)
                    .await
            }
            Err(error) => Err(error),
        };
        if let Err(error) = result {
            let conversation_id_for_error = conversation_id.clone();
            let item = self.timeline_item(
                "error",
                conversation_id.clone(),
                None,
                None,
                Some(error.to_string()),
                json!({ "error": error.to_string() }),
            );
            self.append_timeline(&conversation_id_for_error, item);
        }
        self.agent_runs
            .lock()
            .expect("local agent runs")
            .remove(&conversation_id);
    }

    fn llm(&self) -> Arc<dyn LlmPort> {
        let config = self.config.lock().expect("local runtime config").clone();
        if config.provider == "openai"
            && !config.base_url.trim().is_empty()
            && !config.model.trim().is_empty()
        {
            let llm = HttpLlm::new(config.base_url, config.model);
            let llm = if config.api_key.trim().is_empty() {
                llm
            } else {
                llm.with_api_key(config.api_key)
            };
            return Arc::new(llm);
        }
        if config.provider == "anthropic"
            && !config.base_url.trim().is_empty()
            && !config.model.trim().is_empty()
        {
            let llm = AnthropicLlm::new(config.base_url, config.model);
            let llm = if config.api_key.trim().is_empty() {
                llm
            } else {
                llm.with_api_key(config.api_key)
            };
            return Arc::new(AnthropicAgentLlm { inner: llm });
        }
        Arc::new(MockLocalLlm)
    }

    fn timeline_item(
        &self,
        kind: &str,
        conversation_id: String,
        message_id: Option<String>,
        role: Option<&str>,
        content: Option<String>,
        payload: Value,
    ) -> Value {
        let event_time_us = Utc::now().timestamp_micros();
        let event_counter = self.next_event_counter();
        let mut item = json!({
            "id": format!("{kind}-{event_time_us}-{event_counter}"),
            "type": kind,
            "event_type": kind,
            "conversation_id": conversation_id,
            "eventTimeUs": event_time_us,
            "eventCounter": event_counter,
            "event_time_us": event_time_us,
            "event_counter": event_counter,
            "time_us": event_time_us,
            "counter": event_counter,
            "timestamp": event_time_us / 1000,
            "message_id": message_id,
            "payload": payload.clone(),
            "data": payload,
        });
        if let Some(role) = role {
            item["role"] = json!(role);
            item["data"]["role"] = json!(role);
        }
        if let Some(content) = content {
            item["content"] = json!(content);
            item["data"]["content"] = json!(item["content"].clone());
        }
        item
    }

    fn conversation_value(&self, conversation: &LocalConversation) -> Value {
        json!({
            "id": conversation.id,
            "project_id": conversation.project_id,
            "tenant_id": conversation.tenant_id,
            "user_id": "local-user",
            "title": conversation.title,
            "status": "active",
            "message_count": self
                .timelines
                .lock()
                .expect("local timelines")
                .get(&conversation.id)
                .map(|items| items.len())
                .unwrap_or(0),
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "summary": null,
            "agent_config": { "selected_agent_id": "builtin:all-access" },
            "metadata": { "runtime": "local" },
            "conversation_mode": "workspace",
            "workspace_id": conversation.workspace_id,
            "linked_workspace_task_id": null,
            "workspace_name": "Local workspace",
            "participant_agents": ["local-agent"],
            "coordinator_agent_id": "local-agent",
            "focused_agent_id": "local-agent",
        })
    }
}

fn local_router(state: Arc<LocalRuntimeState>) -> Router {
    Router::new()
        .route("/api/v1/auth/me", get(auth_me))
        .route("/api/v1/tenants", get(list_tenants))
        .route("/api/v1/projects", get(list_projects))
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces",
            get(list_workspaces).post(create_workspace),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/messages",
            get(list_workspace_messages).post(create_workspace_message),
        )
        .route("/api/v1/workspaces/:workspace_id/tasks", get(list_tasks))
        .route("/api/v1/workspaces/:workspace_id/plan", get(plan_snapshot))
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
            get(conversation_messages).post(run_conversation_message),
        )
        .route("/api/v1/agent/ws", get(agent_ws))
        .route(
            "/api/v1/projects/:project_id/sandbox",
            get(get_sandbox).post(ensure_sandbox),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/proxy-auth-cookie",
            post(proxy_auth_cookie),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop",
            post(start_desktop),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop/proxy/",
            get(desktop_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal",
            post(start_terminal),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal/proxy/ws",
            get(terminal_ws),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/execute",
            post(sandbox_execute),
        )
        .route("/mcp/tools/list", get(mcp_tools_list))
        .route("/mcp/tools/call", post(mcp_tools_call))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_capability,
        ))
        .layer(local_cors_layer())
        .with_state(state)
}

fn local_cors_layer() -> CorsLayer {
    CorsLayer::new()
        .allow_origin(AllowOrigin::list([
            HeaderValue::from_static("tauri://localhost"),
            HeaderValue::from_static("http://tauri.localhost"),
            HeaderValue::from_static("http://localhost:1420"),
            HeaderValue::from_static("http://127.0.0.1:1420"),
            HeaderValue::from_static("http://localhost:5173"),
            HeaderValue::from_static("http://127.0.0.1:5173"),
        ]))
        .allow_methods([Method::GET, Method::POST, Method::PATCH])
        .allow_headers([AUTHORIZATION, CONTENT_TYPE])
}

async fn require_capability(
    State(state): State<Arc<LocalRuntimeState>>,
    request: axum::extract::Request,
    next: Next,
) -> Response {
    if request_has_capability(request.headers(), &state.api_token) {
        next.run(request).await
    } else {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({ "detail": "local runtime authorization required" })),
        )
            .into_response()
    }
}

fn request_has_capability(headers: &HeaderMap, expected: &str) -> bool {
    if websocket_protocol_has_capability(headers, expected) {
        return true;
    }
    let bearer = headers
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));
    bearer == Some(expected)
}

fn websocket_protocol_has_capability(headers: &HeaderMap, expected: &str) -> bool {
    let protocols: Vec<&str> = headers
        .get_all("sec-websocket-protocol")
        .iter()
        .filter_map(|value| value.to_str().ok())
        .flat_map(|value| value.split(',').map(str::trim))
        .collect();
    protocols
        .windows(2)
        .any(|pair| pair[0] == "memstack.auth" && pair[1] == expected)
}

async fn auth_me() -> Json<Value> {
    Json(json!({
        "user_id": "local-user",
        "email": "local@desktop",
        "name": "Local Desktop",
        "roles": ["admin"],
        "is_active": true,
        "created_at": now_iso(),
        "profile": {},
        "preferred_language": null,
    }))
}

async fn list_tenants() -> Json<Value> {
    Json(json!({
        "items": [{
            "id": "local",
            "name": "Local Desktop",
            "slug": "local",
            "plan": "local",
            "created_at": now_iso(),
        }]
    }))
}

async fn list_projects() -> Json<Value> {
    Json(json!({
        "items": [{
            "id": "local-project",
            "tenant_id": "local",
            "name": "Local project",
            "description": "Desktop local runtime project",
            "agent_conversation_mode": "workspace",
            "created_at": now_iso(),
            "stats": {},
        }]
    }))
}

async fn list_workspaces(
    State(state): State<Arc<LocalRuntimeState>>,
    Path((_tenant_id, project_id)): Path<(String, String)>,
) -> Json<Value> {
    let workspaces: Vec<Value> = state
        .workspaces
        .lock()
        .expect("local workspaces")
        .iter()
        .filter(|workspace| workspace["project_id"].as_str() == Some(project_id.as_str()))
        .cloned()
        .collect();
    Json(json!({ "items": workspaces }))
}

#[derive(Deserialize)]
struct CreateWorkspaceBody {
    name: Option<String>,
    description: Option<String>,
    metadata: Option<Value>,
}

async fn create_workspace(
    State(state): State<Arc<LocalRuntimeState>>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Json(body): Json<CreateWorkspaceBody>,
) -> Json<Value> {
    let now = now_iso();
    let workspace = json!({
        "id": format!("local-workspace-{}", Uuid::new_v4()),
        "tenant_id": tenant_id,
        "project_id": project_id,
        "name": body.name.unwrap_or_else(|| "Local workspace".to_string()),
        "description": body.description,
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "metadata": body.metadata.unwrap_or_else(|| json!({ "runtime": "local" })),
    });
    state
        .workspaces
        .lock()
        .expect("local workspaces")
        .push(workspace.clone());
    Json(workspace)
}

async fn list_workspace_messages(
    State(state): State<Arc<LocalRuntimeState>>,
    Path((_tenant_id, _project_id, workspace_id)): Path<(String, String, String)>,
) -> Json<Value> {
    let messages = state
        .messages
        .lock()
        .expect("local messages")
        .get(&workspace_id)
        .cloned()
        .unwrap_or_default();
    Json(json!({ "items": messages }))
}

#[derive(Deserialize)]
struct WorkspaceMessageBody {
    content: String,
    parent_message_id: Option<String>,
    mentions: Option<Vec<String>>,
}

async fn create_workspace_message(
    State(state): State<Arc<LocalRuntimeState>>,
    Path((_tenant_id, _project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<WorkspaceMessageBody>,
) -> Json<Value> {
    let message = json!({
        "id": format!("local-message-{}", Uuid::new_v4()),
        "workspace_id": workspace_id,
        "parent_message_id": body.parent_message_id,
        "sender_type": "human",
        "sender_id": "local-user",
        "content": body.content,
        "mentions": body.mentions.unwrap_or_default(),
        "created_at": now_iso(),
        "metadata": { "runtime": "local" },
    });
    state.append_workspace_message(
        message["workspace_id"].as_str().unwrap_or_default(),
        message.clone(),
    );
    Json(message)
}

async fn list_tasks() -> Json<Value> {
    Json(json!({ "items": [] }))
}

async fn plan_snapshot() -> Json<Value> {
    Json(json!({
        "status": "local",
        "title": "Local desktop runtime",
        "items": [],
    }))
}

#[derive(Deserialize)]
struct ListConversationsQuery {
    project_id: Option<String>,
    workspace_id: Option<String>,
    limit: Option<usize>,
    offset: Option<usize>,
}

async fn list_conversations(
    State(state): State<Arc<LocalRuntimeState>>,
    Query(query): Query<ListConversationsQuery>,
) -> Json<Value> {
    let project_id = query
        .project_id
        .unwrap_or_else(|| "local-project".to_string());
    let workspace_id = query.workspace_id;
    let offset = query.offset.unwrap_or(0);
    let limit = query.limit.unwrap_or(100);
    let values: Vec<Value> = state
        .conversations
        .lock()
        .expect("local conversations")
        .values()
        .filter(|conversation| conversation.project_id == project_id)
        .filter(|conversation| {
            workspace_id
                .as_ref()
                .map(|workspace_id| {
                    conversation.workspace_id.as_deref() == Some(workspace_id.as_str())
                })
                .unwrap_or(true)
        })
        .map(|conversation| state.conversation_value(conversation))
        .collect();
    let total = values.len();
    let items = values
        .into_iter()
        .skip(offset)
        .take(limit)
        .collect::<Vec<_>>();
    Json(json!({
        "items": items,
        "total": total,
        "has_more": offset + limit < total,
        "offset": offset,
        "limit": limit,
        "next_offset": if offset + limit < total { Some(offset + limit) } else { None },
    }))
}

#[derive(Deserialize)]
struct CreateConversationBody {
    project_id: String,
    title: Option<String>,
}

async fn create_conversation(
    State(state): State<Arc<LocalRuntimeState>>,
    Json(body): Json<CreateConversationBody>,
) -> Json<Value> {
    let now = now_iso();
    let conversation = LocalConversation {
        id: format!("local-conversation-{}", Uuid::new_v4()),
        project_id: body.project_id,
        tenant_id: "local".to_string(),
        title: body.title.unwrap_or_else(|| "Local session".to_string()),
        workspace_id: None,
        created_at: now.clone(),
        updated_at: now,
    };
    let value = state.conversation_value(&conversation);
    state
        .conversations
        .lock()
        .expect("local conversations")
        .insert(conversation.id.clone(), conversation);
    Json(value)
}

#[derive(Deserialize)]
struct ConversationModeBody {
    workspace_id: Option<String>,
}

async fn update_conversation_mode(
    State(state): State<Arc<LocalRuntimeState>>,
    Path(conversation_id): Path<String>,
    Json(body): Json<ConversationModeBody>,
) -> Json<Value> {
    let mut conversations = state.conversations.lock().expect("local conversations");
    let value = if let Some(conversation) = conversations.get_mut(&conversation_id) {
        conversation.workspace_id = body.workspace_id;
        conversation.updated_at = now_iso();
        state.conversation_value(conversation)
    } else {
        json!({ "detail": "conversation not found" })
    };
    Json(value)
}

#[derive(Deserialize)]
struct ConversationMessagesQuery {
    limit: Option<usize>,
}

async fn conversation_messages(
    State(state): State<Arc<LocalRuntimeState>>,
    Path(conversation_id): Path<String>,
    Query(query): Query<ConversationMessagesQuery>,
) -> Json<Value> {
    let limit = query.limit.unwrap_or(50);
    let mut items = state
        .timelines
        .lock()
        .expect("local timelines")
        .get(&conversation_id)
        .cloned()
        .unwrap_or_default();
    if items.len() > limit {
        items = items[items.len() - limit..].to_vec();
    }
    let first = items.first().cloned();
    let last = items.last().cloned();
    Json(json!({
        "conversationId": conversation_id,
        "timeline": items,
        "total": state
            .timelines
            .lock()
            .expect("local timelines")
            .get(&conversation_id)
            .map(|items| items.len())
            .unwrap_or(0),
        "has_more": false,
        "first_time_us": first.as_ref().and_then(|item| item["eventTimeUs"].as_i64()),
        "first_counter": first.as_ref().and_then(|item| item["eventCounter"].as_u64()),
        "last_time_us": last.as_ref().and_then(|item| item["eventTimeUs"].as_i64()),
        "last_counter": last.as_ref().and_then(|item| item["eventCounter"].as_u64()),
    }))
}

#[derive(Deserialize)]
struct RunConversationBody {
    message: String,
    message_id: Option<String>,
    project_id: Option<String>,
}

async fn run_conversation_message(
    State(state): State<Arc<LocalRuntimeState>>,
    Path(conversation_id): Path<String>,
    Json(body): Json<RunConversationBody>,
) -> Json<Value> {
    let message_id = body
        .message_id
        .unwrap_or_else(|| format!("local-message-{}", Uuid::new_v4()));
    let project_id = body
        .project_id
        .unwrap_or_else(|| "local-project".to_string());
    let run_state = Arc::clone(&state);
    tokio::spawn(async move {
        run_state
            .run_agent_message(conversation_id, project_id, body.message, message_id)
            .await;
    });
    Json(json!({ "queued": true }))
}

async fn agent_ws(
    State(state): State<Arc<LocalRuntimeState>>,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    ws.protocols(["memstack.auth"])
        .on_upgrade(move |socket| agent_socket_loop(socket, state))
}

async fn agent_socket_loop(socket: WebSocket, state: Arc<LocalRuntimeState>) {
    let (mut sender, mut receiver) = socket.split();
    let mut events = state.events.subscribe();
    let mut conversations = HashSet::new();
    loop {
        tokio::select! {
            incoming = receiver.next() => {
                let Some(Ok(Message::Text(text))) = incoming else {
                    break;
                };
                let Ok(value) = serde_json::from_str::<Value>(&text) else {
                    continue;
                };
                let kind = value["type"].as_str().unwrap_or_default();
                if kind == "send_message" {
                    let conversation_id = value["conversation_id"].as_str().unwrap_or_default().to_string();
                    let project_id = value["project_id"].as_str().unwrap_or("local-project").to_string();
                    let message = value["message"].as_str().unwrap_or_default().to_string();
                    if conversation_id.is_empty() || message.is_empty() {
                        let error = json!({ "type": "error", "message": "conversation_id and message are required" });
                        if sender.send(Message::Text(error.to_string())).await.is_err() {
                            break;
                        }
                        continue;
                    }
                    let message_id = value["message_id"].as_str().map(ToString::to_string).unwrap_or_else(|| format!("local-message-{}", Uuid::new_v4()));
                    conversations.insert(conversation_id.clone());
                    let ack = json!({
                        "type": "ack",
                        "action": "send_message",
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                    });
                    if sender.send(Message::Text(ack.to_string())).await.is_err() {
                        break;
                    }
                    let run_state = Arc::clone(&state);
                    tokio::spawn(async move {
                        run_state.run_agent_message(conversation_id, project_id, message, message_id).await;
                    });
                } else if kind == "subscribe" {
                    let Some(conversation_id) = value["conversation_id"].as_str() else {
                        continue;
                    };
                    if conversation_id.is_empty() {
                        continue;
                    }
                    conversations.insert(conversation_id.to_string());
                    let ack = json!({
                        "type": "ack",
                        "action": "subscribe",
                        "conversation_id": conversation_id,
                    });
                    let _ = sender.send(Message::Text(ack.to_string())).await;
                }
            }
            event = events.recv() => {
                let Ok(event) = event else {
                    continue;
                };
                if !is_subscribed_event(&event, &conversations) {
                    continue;
                }
                if sender.send(Message::Text(event.to_string())).await.is_err() {
                    break;
                }
            }
        }
    }
}

fn is_subscribed_event(event: &Value, conversations: &HashSet<String>) -> bool {
    event["conversation_id"]
        .as_str()
        .is_some_and(|conversation_id| conversations.contains(conversation_id))
}

async fn get_sandbox(Path(project_id): Path<String>) -> Json<Value> {
    Json(sandbox_value(project_id))
}

async fn ensure_sandbox(Path(project_id): Path<String>) -> Json<Value> {
    Json(sandbox_value(project_id))
}

async fn proxy_auth_cookie() -> Json<Value> {
    Json(json!({ "ok": true }))
}

async fn start_desktop(Path(project_id): Path<String>) -> Json<Value> {
    Json(json!({
        "success": true,
        "url": format!("/api/v1/projects/{project_id}/sandbox/desktop/proxy/"),
        "display": "native",
        "resolution": "1440x900",
        "port": null,
        "audio_enabled": false,
        "dynamic_resize": true,
        "encoding": "native",
    }))
}

async fn desktop_proxy() -> Html<&'static str> {
    Html(
        r#"<!doctype html><html><body style="margin:0;background:#111;color:#ddd;font:14px system-ui;display:grid;place-items:center;height:100vh"><div>Local desktop mode uses the native Tauri window.</div></body></html>"#,
    )
}

async fn start_terminal(
    State(state): State<Arc<LocalRuntimeState>>,
    Path(_project_id): Path<String>,
) -> Json<Value> {
    let session_id = state.create_terminal_session();
    Json(json!({
        "success": true,
        "url": null,
        "port": null,
        "session_id": session_id,
    }))
}

#[derive(Deserialize)]
struct TerminalSocketQuery {
    session_id: String,
}

async fn terminal_ws(
    State(state): State<Arc<LocalRuntimeState>>,
    Query(query): Query<TerminalSocketQuery>,
    ws: WebSocketUpgrade,
) -> Response {
    if !state.take_terminal_session(&query.session_id) {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({ "detail": "unknown or consumed terminal session" })),
        )
            .into_response();
    }
    ws.protocols(["memstack.auth"])
        .on_upgrade(move |socket| terminal_socket_loop(socket, state, query.session_id))
        .into_response()
}

async fn terminal_socket_loop(
    socket: WebSocket,
    state: Arc<LocalRuntimeState>,
    session_id: String,
) {
    let (mut sender, mut receiver) = socket.split();
    let pty_system = native_pty_system();
    let pair = match pty_system.openpty(PtySize {
        rows: 32,
        cols: 120,
        pixel_width: 0,
        pixel_height: 0,
    }) {
        Ok(pair) => pair,
        Err(error) => {
            let _ = sender
                .send(Message::Text(
                    json!({ "type": "error", "message": error.to_string() }).to_string(),
                ))
                .await;
            return;
        }
    };
    let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/sh".to_string());
    let mut command = CommandBuilder::new(shell);
    command.cwd(
        state
            .workspace_root
            .lock()
            .expect("local workspace root")
            .clone(),
    );
    let mut child = match pair.slave.spawn_command(command) {
        Ok(child) => child,
        Err(error) => {
            let _ = sender
                .send(Message::Text(
                    json!({ "type": "error", "message": error.to_string() }).to_string(),
                ))
                .await;
            return;
        }
    };
    drop(pair.slave);
    let mut reader = match pair.master.try_clone_reader() {
        Ok(reader) => reader,
        Err(error) => {
            let _ = sender
                .send(Message::Text(
                    json!({ "type": "error", "message": error.to_string() }).to_string(),
                ))
                .await;
            let _ = child.kill();
            return;
        }
    };
    let mut writer = match pair.master.take_writer() {
        Ok(writer) => writer,
        Err(error) => {
            let _ = sender
                .send(Message::Text(
                    json!({ "type": "error", "message": error.to_string() }).to_string(),
                ))
                .await;
            let _ = child.kill();
            return;
        }
    };
    let (output_tx, mut output_rx) = mpsc::channel::<String>(32);
    std::thread::spawn(move || {
        let mut buffer = [0_u8; 4096];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(size) => {
                    let text = String::from_utf8_lossy(&buffer[..size]).to_string();
                    if output_tx.blocking_send(text).is_err() {
                        break;
                    }
                }
                Err(error) => {
                    let _ = output_tx.blocking_send(format!("[terminal read error] {error}\n"));
                    break;
                }
            }
        }
    });
    let _ = sender
        .send(Message::Text(
            json!({ "type": "connected", "session_id": session_id, "cols": 120, "rows": 32 })
                .to_string(),
        ))
        .await;
    loop {
        tokio::select! {
            incoming = receiver.next() => {
                let Some(Ok(Message::Text(text))) = incoming else {
                    break;
                };
                let Ok(value) = serde_json::from_str::<Value>(&text) else {
                    continue;
                };
                match value["type"].as_str() {
                    Some("input") => {
                        let data = value["data"].as_str().unwrap_or_default();
                        if writer.write_all(data.as_bytes()).is_err() || writer.flush().is_err() {
                            break;
                        }
                    }
                    Some("resize") => {
                        let cols = value["cols"].as_u64().unwrap_or(120).clamp(1, 400) as u16;
                        let rows = value["rows"].as_u64().unwrap_or(32).clamp(1, 200) as u16;
                        let _ = pair.master.resize(PtySize {
                            rows,
                            cols,
                            pixel_width: 0,
                            pixel_height: 0,
                        });
                    }
                    _ => {}
                }
            }
            output = output_rx.recv() => {
                let Some(output) = output else {
                    break;
                };
                if sender
                    .send(Message::Text(json!({ "type": "output", "data": output }).to_string()))
                    .await
                    .is_err()
                {
                    break;
                }
            }
        }
    }
    let _ = child.kill();
}

async fn sandbox_execute(
    State(state): State<Arc<LocalRuntimeState>>,
    Json(body): Json<Value>,
) -> Json<Value> {
    let command = body["command"].as_str().unwrap_or_default();
    let args = json!({
        "command": command,
        "timeout_ms": body["timeout_ms"].as_u64().unwrap_or(30_000),
    });
    let tool_host = state.tool_host.lock().expect("local tool host").clone();
    let result = tool_host.mcp_tools_call_result("bash", args).await;
    let payload = result
        .content
        .first()
        .and_then(|content| serde_json::from_str::<Value>(&content.text).ok())
        .unwrap_or_else(|| json!({}));
    let success = !result.is_error && payload["success"].as_bool().unwrap_or(false);
    Json(json!({
        "success": success,
        "output": payload["stdout"].as_str().unwrap_or_default(),
        "stdout": payload["stdout"].as_str().unwrap_or_default(),
        "stderr": payload["stderr"].as_str().unwrap_or_default(),
        "exit_code": payload["exit_code"].clone(),
        "timed_out": payload["timed_out"].as_bool().unwrap_or(false),
    }))
}

async fn mcp_tools_list(State(state): State<Arc<LocalRuntimeState>>) -> Json<Value> {
    let tool_host = state.tool_host.lock().expect("local tool host").clone();
    Json(tool_host.mcp_tools_list_result())
}

async fn mcp_tools_call(
    State(state): State<Arc<LocalRuntimeState>>,
    Json(body): Json<Value>,
) -> Json<Value> {
    let name = body["name"].as_str().unwrap_or_default();
    let arguments = body.get("arguments").cloned().unwrap_or_else(|| json!({}));
    let tool_host = state.tool_host.lock().expect("local tool host").clone();
    let result = tool_host.mcp_tools_call_result(name, arguments).await;
    Json(serde_json::to_value(result).unwrap_or_else(|error| json!({ "isError": true, "content": [{ "type": "text", "text": error.to_string() }] })))
}

fn sandbox_value(project_id: String) -> Value {
    json!({
        "sandbox_id": format!("local-{project_id}"),
        "project_id": project_id,
        "tenant_id": "local",
        "status": "running",
        "endpoint": null,
        "websocket_url": null,
        "desktop_port": null,
        "terminal_port": null,
        "desktop_url": null,
        "terminal_url": null,
        "is_healthy": true,
        "error_message": null,
    })
}

struct LocalTimelineObserver {
    state: Arc<LocalRuntimeState>,
    conversation_id: String,
}

#[async_trait]
impl ReActObserver for LocalTimelineObserver {
    async fn on_tool_call(
        &self,
        _session_id: &str,
        _round: u64,
        tool: &str,
        input_json: &str,
    ) -> CoreResult<()> {
        let mut item = self.state.timeline_item(
            "act",
            self.conversation_id.clone(),
            None,
            None,
            None,
            json!({ "tool_name": tool, "tool_input": input_json }),
        );
        item["toolName"] = json!(tool);
        item["toolInput"] = json!(input_json);
        self.state.append_timeline(&self.conversation_id, item);
        Ok(())
    }

    async fn on_tool_result(
        &self,
        _session_id: &str,
        _round: u64,
        tool: &str,
        input_json: &str,
        output_json: &str,
    ) -> CoreResult<()> {
        let mut item = self.state.timeline_item(
            "observe",
            self.conversation_id.clone(),
            None,
            None,
            None,
            json!({
                "tool_name": tool,
                "tool_input": input_json,
                "tool_output": output_json,
                "observation": output_json,
                "is_error": false,
            }),
        );
        item["toolName"] = json!(tool);
        item["toolInput"] = json!(input_json);
        item["toolOutput"] = json!(output_json);
        item["isError"] = json!(false);
        self.state.append_timeline(&self.conversation_id, item);
        Ok(())
    }

    async fn on_finish(&self, _session_id: &str, _round: u64, answer: &str) -> CoreResult<()> {
        let item = self.state.timeline_item(
            "assistant_message",
            self.conversation_id.clone(),
            Some(format!("local-assistant-{}", Uuid::new_v4())),
            Some("assistant"),
            Some(answer.to_string()),
            json!({}),
        );
        self.state.append_timeline(&self.conversation_id, item);
        Ok(())
    }
}

struct MockLocalLlm;

#[async_trait]
impl LlmPort for MockLocalLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        Ok(MemoryDraft {
            title: "Local memory".to_string(),
            content: episode.content.clone(),
            tags: vec!["local".to_string()],
            entities: Vec::<Entity>::new(),
        })
    }

    async fn decide(
        &self,
        goal: &str,
        _round: u64,
        transcript: &[TranscriptEntry],
        _available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        let observed = transcript
            .iter()
            .rev()
            .find(|entry| entry.role == Role::Observation)
            .map(|entry| format!("\n\nLast tool output:\n{}", entry.content))
            .unwrap_or_default();
        Ok(AgentAction::Finish {
            answer: format!("Local runtime received: {goal}{observed}"),
        })
    }
}

struct AnthropicAgentLlm {
    inner: AnthropicLlm,
}

#[async_trait]
impl LlmPort for AnthropicAgentLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        Ok(MemoryDraft {
            title: "Anthropic local memory".to_string(),
            content: episode.content.clone(),
            tags: Vec::new(),
            entities: Vec::new(),
        })
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        let user = json!({
            "goal": goal,
            "round": round,
            "transcript": transcript,
            "available_tools": available_tools,
        })
        .to_string();
        let raw = self
            .inner
            .stream_complete(
                "You are a ReAct agent. Respond with ONLY JSON: {\"kind\":\"finish\",\"answer\":string} or {\"kind\":\"call_tool\",\"tool\":string,\"input_json\":string}.",
                user,
                |_| {},
            )
            .await?;
        parse_agent_action(&raw)
    }
}

fn parse_agent_action(raw: &str) -> CoreResult<AgentAction> {
    let cleaned = raw
        .trim()
        .trim_start_matches("```json")
        .trim_start_matches("```")
        .trim_end_matches("```")
        .trim();
    serde_json::from_str(cleaned).map_err(|error| CoreError::Llm(error.to_string()))
}

fn now_iso() -> String {
    Utc::now().to_rfc3339()
}

fn generate_capability_token() -> String {
    format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{body::Body, http::Request};
    use tower::ServiceExt;

    fn test_root() -> PathBuf {
        std::env::temp_dir().join(format!("agistack-local-runtime-{}", Uuid::new_v4()))
    }

    fn test_state(token: &str) -> Arc<LocalRuntimeState> {
        let root = test_root();
        let tool_host = LocalToolHost::new(&root).expect("tool host");
        let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        Arc::new(LocalRuntimeState::new(
            root,
            tool_host,
            checkpoints,
            token.to_string(),
        ))
    }

    #[tokio::test]
    async fn router_requires_launch_capability_for_http_and_websocket_upgrade() {
        let state = test_state("launch-secret");
        let app = local_router(state);

        let missing = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/auth/me")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(missing.status(), axum::http::StatusCode::UNAUTHORIZED);

        let wrong_ws = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/agent/ws?token=wrong")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(wrong_ws.status(), axum::http::StatusCode::UNAUTHORIZED);

        let query_token_ws = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/agent/ws?token=launch-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(
            query_token_ws.status(),
            axum::http::StatusCode::UNAUTHORIZED
        );

        let protocol_ws = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/agent/ws")
                    .header("sec-websocket-protocol", "memstack.auth, launch-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_ne!(protocol_ws.status(), axum::http::StatusCode::UNAUTHORIZED);

        let authorized = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/auth/me")
                    .header("authorization", "Bearer launch-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(authorized.status(), axum::http::StatusCode::OK);
    }

    #[tokio::test]
    async fn cors_allows_tauri_origin_and_rejects_web_origin() {
        let app = local_router(test_state("launch-secret"));
        let allowed = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/auth/me")
                    .header("authorization", "Bearer launch-secret")
                    .header("origin", "tauri://localhost")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(
            allowed
                .headers()
                .get("access-control-allow-origin")
                .and_then(|v| v.to_str().ok()),
            Some("tauri://localhost")
        );

        let rejected = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/auth/me")
                    .header("authorization", "Bearer launch-secret")
                    .header("origin", "https://attacker.example")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert!(rejected
            .headers()
            .get("access-control-allow-origin")
            .is_none());

        let vite = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/auth/me")
                    .header("authorization", "Bearer launch-secret")
                    .header("origin", "http://127.0.0.1:5173")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(
            vite.headers()
                .get("access-control-allow-origin")
                .and_then(|v| v.to_str().ok()),
            Some("http://127.0.0.1:5173")
        );
    }

    #[tokio::test]
    async fn second_message_starts_after_finished_checkpoint() {
        let state = test_state("launch-secret");
        let conversation_id = "conversation-1".to_string();

        Arc::clone(&state)
            .run_agent_message(
                conversation_id.clone(),
                "local-project".to_string(),
                "first".to_string(),
                "message-1".to_string(),
            )
            .await;
        Arc::clone(&state)
            .run_agent_message(
                conversation_id.clone(),
                "local-project".to_string(),
                "second".to_string(),
                "message-2".to_string(),
            )
            .await;

        let timelines = state.timelines.lock().expect("timelines");
        let assistant_messages = timelines[&conversation_id]
            .iter()
            .filter(|event| event["type"] == "assistant_message")
            .count();
        assert_eq!(assistant_messages, 2);
    }

    #[test]
    fn terminal_session_is_single_use() {
        let state = test_state("launch-secret");
        let session_id = state.create_terminal_session();
        assert!(state.take_terminal_session(&session_id));
        assert!(!state.take_terminal_session(&session_id));
        assert!(!state.take_terminal_session("missing"));
    }

    #[test]
    fn websocket_events_are_filtered_by_conversation_subscription() {
        let conversations = HashSet::from(["conversation-1".to_string()]);
        assert!(is_subscribed_event(
            &json!({ "conversation_id": "conversation-1" }),
            &conversations,
        ));
        assert!(!is_subscribed_event(
            &json!({ "conversation_id": "conversation-2" }),
            &conversations,
        ));
        assert!(!is_subscribed_event(
            &json!({ "type": "status" }),
            &conversations,
        ));
    }

    #[test]
    fn status_redacts_llm_key_and_returns_unique_high_entropy_token() {
        let first = generate_capability_token();
        let second = generate_capability_token();
        assert_ne!(first, second);
        assert!(first.len() >= 64);

        let state = test_state(&first);
        state.config.lock().expect("config").api_key = "llm-secret".to_string();
        let service = LocalRuntimeService {
            state,
            api_base_url: "http://127.0.0.1:1".to_string(),
        };
        let status = service.status();
        assert_eq!(status.api_token, first);
        assert!(status.config.api_key.is_empty());
        assert!(!status
            .tools
            .iter()
            .any(|name| name.starts_with("mcp_server_")));
        assert!(!status.tools.iter().any(|name| name == "plugin_tool_exec"));
        let serialized = serde_json::to_value(status).expect("serialized status");
        assert!(serialized["config"].get("api_key").is_none());
    }

    #[tokio::test]
    async fn mock_llm_never_routes_text_to_shell() {
        let action = MockLocalLlm
            .decide("bash: touch should-not-run", 0, &[], &["bash".to_string()])
            .await
            .expect("mock decision");
        assert!(matches!(action, AgentAction::Finish { .. }));
    }

    #[tokio::test]
    async fn sandbox_execute_reports_real_exit_status() {
        let state = test_state("launch-secret");
        let Json(failed) = sandbox_execute(
            State(Arc::clone(&state)),
            Json(json!({ "command": "exit 7", "timeout_ms": 5000 })),
        )
        .await;
        assert_eq!(failed["success"], false);
        assert_eq!(failed["exit_code"], 7);
        assert_eq!(failed["timed_out"], false);

        let Json(succeeded) = sandbox_execute(
            State(state),
            Json(json!({ "command": "printf ok", "timeout_ms": 5000 })),
        )
        .await;
        assert_eq!(succeeded["success"], true);
        assert_eq!(succeeded["exit_code"], 0);
        assert_eq!(succeeded["stdout"], "ok");
    }
}
