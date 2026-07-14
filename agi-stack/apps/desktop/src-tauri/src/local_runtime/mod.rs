use std::{
    collections::{HashMap, HashSet},
    io::{Read, Write},
    path::{Path as FsPath, PathBuf},
    sync::{
        atomic::{AtomicU64, AtomicU8, Ordering},
        Arc, Mutex,
    },
};

use agistack_adapters_device::SqliteCheckpointStore;
use agistack_adapters_http_llm::{AnthropicLlm, HttpLlm};
use agistack_adapters_local_tools::LocalToolHost;
use agistack_adapters_mem::SystemClock;
use agistack_core::{
    agent::{
        react::{ReActControl, ReActEngine, ReActObserver, RunDirective, SteeringInstruction},
        types::{AgentAction, HitlKind, Role, SessionState, SessionStatus, TranscriptEntry},
    },
    model::Episode,
    ports::{CheckpointStore, CoreError, CoreResult, LlmPort, MemoryDraft, ToolHost},
};
use async_trait::async_trait;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Extension, Path, Query, State,
    },
    http::{
        header::{AUTHORIZATION, CONTENT_TYPE},
        HeaderMap, HeaderName, HeaderValue, Method, StatusCode,
    },
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::{get, patch, post},
    Json, Router,
};
use chrono::{Duration as ChronoDuration, Utc};
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

#[cfg(test)]
use agistack_core::model::Entity;

mod auth_context;
mod authority_store;
mod authorized_tool_host;
mod changes;
#[cfg(test)]
mod managed_resource_tests;
mod resource_registry;
mod run_control;
mod session_projection;
mod session_store;
mod steering;
mod tool_authority;
mod worktree;

use auth_context::{
    AuthContextError, AuthenticatedContext, ContextSwitchRequest, LocalSessionRequest,
    TrustedSessionResumeRequest,
};
use authority_store::{
    DesktopArtifactStatus, DesktopArtifactVersion, DesktopAuthorityError,
    DesktopExecutionEnvironment, DesktopExecutionEnvironmentKind, DesktopHitlRequest,
    DesktopHitlStatus, DesktopPermissionProfile, DesktopRun, DesktopRunStatus,
};
use authorized_tool_host::AuthorizedRunToolHost;
use changes::{ChangeLineKind, ChangeSnapshot, ChangeSnapshotStatus, GitChangesInspector};
use resource_registry::{ManagedResourceKind, ResourceRegistryError};
use session_store::DesktopSessionStore;
use steering::{ChangeReferenceSide, RunInputDelivery, RunInputReference, RunInputStatus};
use worktree::WorktreeManager;

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
        let session_store_path = app_data_dir.join("agistack-desktop-sessions.db");
        let checkpoints = Arc::new(
            SqliteCheckpointStore::open(&checkpoint_path.to_string_lossy())
                .map_err(|error| error.to_string())?,
        );
        let tool_host = LocalToolHost::new(&workspace_root).map_err(|error| error.to_string())?;
        let api_token = generate_capability_token();
        let session_store = DesktopSessionStore::open(&session_store_path)?;
        let state = Arc::new(LocalRuntimeState::new(
            workspace_root,
            tool_host,
            checkpoints,
            api_token,
            session_store,
        )?);

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
    fn configure(&self, mut config: LocalRuntimeConfig) -> Result<(), String> {
        if !config.workspace_root.trim().is_empty() {
            let root = PathBuf::from(config.workspace_root.trim());
            std::fs::create_dir_all(&root).map_err(|error| error.to_string())?;
            let root = root.canonicalize().map_err(|error| error.to_string())?;
            let host = LocalToolHost::new(&root).map_err(|error| error.to_string())?;
            *self.workspace_root.lock().expect("local workspace root") = root;
            *self.tool_host.lock().expect("local tool host") = host;
        }
        let submitted_credential = normalized_runtime_credential(&config.api_key);
        let binding = if runtime_provider_supported(&config.provider)
            && !config.base_url.trim().is_empty()
            && !config.model.trim().is_empty()
        {
            let bindings = self
                .provider_bindings
                .lock()
                .expect("provider runtime bindings");
            let preserved_credential = bindings.get("local").and_then(|current| {
                (current.provider_id == "local-runtime"
                    && current.provider_type == config.provider
                    && current.base_url == config.base_url)
                    .then(|| current.credential.clone())
                    .flatten()
            });
            Some(ProviderRuntimeBinding {
                provider_id: "local-runtime".to_string(),
                provider_type: config.provider.clone(),
                base_url: config.base_url.clone(),
                model: config.model.clone(),
                auth_method: if submitted_credential.is_some() || preserved_credential.is_some() {
                    "api_key".to_string()
                } else {
                    "none".to_string()
                },
                credential: submitted_credential.or(preserved_credential),
            })
        } else {
            None
        };
        let mut bindings = self
            .provider_bindings
            .lock()
            .expect("provider runtime bindings");
        if let Some(binding) = binding {
            bindings.insert("local".to_string(), binding);
        } else {
            bindings.remove("local");
        }
        config.api_key.clear();
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
            provider: "unconfigured".to_string(),
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

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
enum ConversationRunMode {
    #[default]
    Plan,
    Build,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ConversationCapabilityMode {
    Work,
    Code,
    #[default]
    Unavailable,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct LocalConversation {
    id: String,
    project_id: String,
    tenant_id: String,
    title: String,
    workspace_id: Option<String>,
    #[serde(default)]
    capability_mode: ConversationCapabilityMode,
    #[serde(default)]
    current_mode: ConversationRunMode,
    created_at: String,
    updated_at: String,
}

const PLAN_MODE_TOOL_NAMES: &[&str] = &[
    "read",
    "batch_read",
    "glob",
    "grep",
    "list",
    "list_artifacts",
    "ast_parse",
    "ast_find_symbols",
    "ast_extract_function",
    "ast_get_imports",
    "find_definition",
    "find_references",
    "call_graph",
    "dependency_graph",
    "preview_edit",
    "git_diff",
    "git_log",
];
const SUBMIT_PLAN_TOOL_NAME: &str = "submit_plan";

#[derive(Debug, Deserialize)]
struct SubmitPlanInput {
    tasks: Vec<SubmitPlanTaskInput>,
}

#[derive(Debug, Deserialize)]
struct SubmitPlanTaskInput {
    content: String,
    priority: Option<String>,
}

#[derive(Clone)]
struct PlanModeToolHost {
    inner: LocalToolHost,
    session_store: DesktopSessionStore,
    conversation_id: String,
}

impl PlanModeToolHost {
    fn new(
        inner: LocalToolHost,
        session_store: DesktopSessionStore,
        conversation_id: String,
    ) -> Self {
        Self {
            inner,
            session_store,
            conversation_id,
        }
    }

    fn is_allowed(tool: &str) -> bool {
        PLAN_MODE_TOOL_NAMES.contains(&tool) || tool == SUBMIT_PLAN_TOOL_NAME
    }

    fn submit_plan(&self, input_json: &str) -> CoreResult<String> {
        let input: SubmitPlanInput = serde_json::from_str(input_json)
            .map_err(|error| CoreError::Tool(format!("invalid submit_plan input: {error}")))?;
        if input.tasks.is_empty() {
            return Err(CoreError::Tool(
                "submit_plan requires at least one task".to_string(),
            ));
        }
        if input.tasks.len() > 50 {
            return Err(CoreError::Tool(
                "submit_plan accepts at most 50 tasks".to_string(),
            ));
        }
        let now = now_iso();
        let mut tasks = Vec::with_capacity(input.tasks.len());
        for (index, task) in input.tasks.into_iter().enumerate() {
            let content = task.content.trim();
            if content.is_empty() {
                return Err(CoreError::Tool(format!(
                    "submit_plan task {index} has empty content"
                )));
            }
            let priority = task.priority.as_deref().unwrap_or("medium");
            if !matches!(priority, "high" | "medium" | "low") {
                return Err(CoreError::Tool(format!(
                    "submit_plan task {index} has invalid priority"
                )));
            }
            tasks.push(json!({
                "id": format!("local-plan-task-{}", Uuid::new_v4()),
                "conversation_id": self.conversation_id,
                "content": content,
                "status": "pending",
                "priority": priority,
                "order_index": index,
                "created_at": now,
                "updated_at": now,
            }));
        }
        self.session_store
            .replace_agent_plan_tasks(&self.conversation_id, &tasks)
            .map_err(CoreError::Tool)?;
        serde_json::to_string(&json!({
            "conversation_id": self.conversation_id,
            "tasks": tasks,
            "total_count": tasks.len(),
        }))
        .map_err(|error| CoreError::Tool(error.to_string()))
    }
}

#[async_trait]
impl ToolHost for PlanModeToolHost {
    fn list_tools(&self) -> Vec<String> {
        let mut tools = self
            .inner
            .list_tools()
            .into_iter()
            .filter(|tool| Self::is_allowed(tool))
            .collect::<Vec<_>>();
        tools.push(SUBMIT_PLAN_TOOL_NAME.to_string());
        tools
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        if !Self::is_allowed(tool) {
            return Err(CoreError::Tool(format!(
                "tool '{tool}' is blocked while the conversation is in plan mode"
            )));
        }
        if tool == SUBMIT_PLAN_TOOL_NAME {
            return self.submit_plan(input_json);
        }
        self.inner.call(tool, input_json).await
    }
}

struct LocalRuntimeState {
    api_token: String,
    workspace_root: Mutex<PathBuf>,
    tool_host: Mutex<LocalToolHost>,
    checkpoints: Arc<SqliteCheckpointStore>,
    clock: Arc<SystemClock>,
    config: Mutex<LocalRuntimeConfig>,
    provider_bindings: Mutex<HashMap<String, ProviderRuntimeBinding>>,
    session_store: DesktopSessionStore,
    event_counter: AtomicU64,
    terminal_sessions: Mutex<HashMap<String, TerminalSessionLease>>,
    agent_runs: Mutex<HashMap<String, ActiveAgentRun>>,
    events: broadcast::Sender<Value>,
}

#[derive(Clone, Debug)]
struct ProviderRuntimeBinding {
    provider_id: String,
    provider_type: String,
    base_url: String,
    model: String,
    auth_method: String,
    credential: Option<String>,
}

#[derive(Clone)]
struct ActiveAgentRun {
    run_id: Option<String>,
    control: Arc<LocalRunControl>,
}

#[derive(Clone, Debug, Serialize)]
struct TerminalSessionLease {
    session_id: String,
    run_id: String,
    run_revision: u64,
    conversation_id: String,
    project_id: String,
    environment_id: String,
    auth_session_id: String,
    user_id: String,
    context_revision: u64,
    cwd: PathBuf,
    created_at: String,
    expires_at: String,
}

struct LocalRunControl {
    directive: AtomicU8,
    session_store: DesktopSessionStore,
    run_id: Option<String>,
}

impl LocalRunControl {
    const CONTINUE: u8 = 0;
    const PAUSE: u8 = 1;
    const CANCEL: u8 = 2;

    fn new(session_store: DesktopSessionStore, run_id: Option<&str>) -> Self {
        Self {
            directive: AtomicU8::new(Self::CONTINUE),
            session_store,
            run_id: run_id.map(ToString::to_string),
        }
    }

    fn request_pause(&self) {
        self.directive.store(Self::PAUSE, Ordering::Release);
    }

    fn request_cancel(&self) {
        self.directive.store(Self::CANCEL, Ordering::Release);
    }
}

#[async_trait]
impl ReActControl for LocalRunControl {
    async fn directive(&self, _session_id: &str, _round: u64) -> CoreResult<RunDirective> {
        match self.directive.load(Ordering::Acquire) {
            Self::PAUSE => return Ok(RunDirective::Pause),
            Self::CANCEL => return Ok(RunDirective::Cancel),
            Self::CONTINUE => {}
            _ => return Ok(RunDirective::Cancel),
        }
        let Some(run_id) = self.run_id.as_deref() else {
            return Ok(RunDirective::Continue);
        };
        let pending = self
            .session_store
            .pending_steering(run_id)
            .map_err(CoreError::Tool)?;
        Ok(pending
            .map(|input| {
                let content = input.steering_content();
                RunDirective::Steer(SteeringInstruction {
                    id: input.id,
                    content,
                })
            })
            .unwrap_or(RunDirective::Continue))
    }

    async fn acknowledge_steering(
        &self,
        _session_id: &str,
        instruction_id: &str,
        round: u64,
    ) -> CoreResult<()> {
        self.session_store
            .acknowledge_steering(instruction_id, round, &now_iso())
            .map(|_| ())
            .map_err(CoreError::Tool)
    }
}

impl LocalRuntimeState {
    fn new(
        workspace_root: PathBuf,
        tool_host: LocalToolHost,
        checkpoints: Arc<SqliteCheckpointStore>,
        api_token: String,
        session_store: DesktopSessionStore,
    ) -> Result<Self, String> {
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
        session_store.ensure_workspace(&workspace)?;
        Ok(Self {
            api_token,
            workspace_root: Mutex::new(workspace_root),
            tool_host: Mutex::new(tool_host),
            checkpoints,
            clock: Arc::new(SystemClock),
            config: Mutex::new(LocalRuntimeConfig::default()),
            provider_bindings: Mutex::new(HashMap::new()),
            session_store,
            event_counter: AtomicU64::new(1),
            terminal_sessions: Mutex::new(HashMap::new()),
            agent_runs: Mutex::new(HashMap::new()),
            events,
        })
    }

    fn create_terminal_session(
        &self,
        run: &DesktopRun,
        environment: &DesktopExecutionEnvironment,
        authenticated: &AuthenticatedContext,
        cwd: PathBuf,
        created_at: String,
        expires_at: String,
    ) -> TerminalSessionLease {
        let session_id = format!("local-terminal-{}", Uuid::new_v4());
        let lease = TerminalSessionLease {
            session_id: session_id.clone(),
            run_id: run.id.clone(),
            run_revision: run.revision,
            conversation_id: run.conversation_id.clone(),
            project_id: run.project_id.clone(),
            environment_id: environment.id.clone(),
            auth_session_id: authenticated.session_id.clone(),
            user_id: authenticated.user.user_id.clone(),
            context_revision: authenticated.workspace.revision,
            cwd,
            created_at,
            expires_at,
        };
        self.terminal_sessions
            .lock()
            .expect("local terminal sessions")
            .insert(session_id, lease.clone());
        lease
    }

    fn take_terminal_session(&self, session_id: &str) -> Option<TerminalSessionLease> {
        self.terminal_sessions
            .lock()
            .expect("local terminal sessions")
            .remove(session_id)
    }

    fn next_event_counter(&self) -> u64 {
        self.event_counter.fetch_add(1, Ordering::SeqCst)
    }

    fn claim_agent_run(
        &self,
        conversation_id: &str,
        run_id: Option<&str>,
    ) -> Option<Arc<LocalRunControl>> {
        let mut runs = self.agent_runs.lock().expect("local agent runs");
        if runs.contains_key(conversation_id) {
            return None;
        }
        let control = Arc::new(LocalRunControl::new(self.session_store.clone(), run_id));
        runs.insert(
            conversation_id.to_string(),
            ActiveAgentRun {
                run_id: run_id.map(ToString::to_string),
                control: Arc::clone(&control),
            },
        );
        Some(control)
    }

    fn release_agent_run(&self, conversation_id: &str) {
        self.agent_runs
            .lock()
            .expect("local agent runs")
            .remove(conversation_id);
    }

    fn control_for_run(&self, run: &DesktopRun) -> Option<Arc<LocalRunControl>> {
        self.agent_runs
            .lock()
            .expect("local agent runs")
            .get(&run.conversation_id)
            .filter(|active| active.run_id.as_deref() == Some(run.id.as_str()))
            .map(|active| Arc::clone(&active.control))
    }

    fn append_timeline(&self, conversation_id: &str, item: Value) {
        if let Err(error) = self.session_store.append_timeline(conversation_id, &item) {
            eprintln!("failed to persist local timeline item: {error}");
            return;
        }
        let _ = self.events.send(item);
    }

    fn append_workspace_message(&self, workspace_id: &str, message: Value) {
        if let Err(error) = self
            .session_store
            .append_workspace_message(workspace_id, &message)
        {
            eprintln!("failed to persist local workspace message: {error}");
        }
    }

    fn publish_run_status(&self, run: &DesktopRun) {
        let mut payload = serde_json::to_value(run)
            .unwrap_or_else(|error| json!({ "run_id": run.id, "error": error.to_string() }));
        payload["timestamp"] = json!(run.updated_at);
        payload["source"] = json!("local_agent_runtime");
        payload["execution_id"] = json!(run.id);
        let item = self.timeline_item(
            "run_status",
            run.conversation_id.clone(),
            Some(run.message_id.clone()),
            None,
            None,
            payload,
        );
        self.append_timeline(&run.conversation_id, item);
    }

    async fn run_agent_message(
        self: Arc<Self>,
        conversation_id: String,
        project_id: String,
        message: String,
        message_id: String,
        authoritative_run_id: Option<String>,
        claimed_control: Option<Arc<LocalRunControl>>,
    ) {
        let conversation = match self.session_store.conversation(&conversation_id) {
            Ok(Some(conversation)) => conversation,
            Ok(None) => return,
            Err(error) => {
                eprintln!("failed to read local conversation authority: {error}");
                return;
            }
        };
        if conversation.project_id != project_id {
            let item = self.timeline_item(
                "error",
                conversation_id.clone(),
                None,
                None,
                Some("conversation project mismatch".to_string()),
                json!({ "error": "conversation project mismatch" }),
            );
            self.append_timeline(&conversation_id, item);
            return;
        }
        if conversation.current_mode == ConversationRunMode::Build && authoritative_run_id.is_none()
        {
            let item = self.timeline_item(
                "error",
                conversation_id.clone(),
                None,
                None,
                Some("build mode requires an approved authoritative run".to_string()),
                json!({ "error": "approved run required" }),
            );
            self.append_timeline(&conversation_id, item);
            return;
        }
        let authoritative_run = if let Some(run_id) = authoritative_run_id.as_deref() {
            match self
                .session_store
                .prepare_run_for_execution(run_id, &now_iso())
            {
                Ok(Some(run)) => {
                    self.publish_run_status(&run);
                    if run.status != DesktopRunStatus::Running {
                        return;
                    }
                    Some(run)
                }
                Ok(None) => return,
                Err(error) => {
                    eprintln!("failed to prepare authoritative local run: {error}");
                    return;
                }
            }
        } else {
            None
        };
        let authoritative_revision = authoritative_run.as_ref().map(|run| run.revision);
        let control = if let Some(control) = claimed_control {
            control
        } else {
            let Some(control) =
                self.claim_agent_run(&conversation_id, authoritative_run_id.as_deref())
            else {
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
            };
            control
        };

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
        let engine = match self.agent_engine(&conversation, authoritative_run.as_ref()) {
            Ok(engine) => engine,
            Err(error) => {
                let item = self.timeline_item(
                    "error",
                    conversation_id.clone(),
                    None,
                    None,
                    Some(error.clone()),
                    json!({ "error": error }),
                );
                self.append_timeline(&conversation_id, item);
                if let Some(run) = authoritative_run.as_ref() {
                    if let Ok(failed) = self.session_store.transition_run(
                        &run.id,
                        run.revision,
                        DesktopRunStatus::Failed,
                        Some("execution environment is unavailable".to_string()),
                        &now_iso(),
                    ) {
                        self.publish_run_status(&failed);
                    }
                }
                self.release_agent_run(&conversation_id);
                return;
            }
        };
        let checkpoint_cleanup = match self.checkpoints.load(&conversation_id).await {
            Ok(Some(checkpoint))
                if matches!(
                    checkpoint.status,
                    SessionStatus::Finished | SessionStatus::Failed | SessionStatus::Cancelled
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
                    .run_observed_controlled(
                        &conversation_id,
                        &message,
                        Some(&project_id),
                        observer,
                        control,
                    )
                    .await
            }
            Err(error) => Err(error),
        };
        let mut run_result = match result {
            Ok(state) => Ok(state),
            Err(error) => {
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
                Err(error.to_string())
            }
        };
        let hitl_persistence_error = run_result.as_ref().ok().and_then(|state| {
            self.persist_pending_hitl(&conversation_id, authoritative_run_id.as_deref(), state)
                .err()
        });
        if let Some(error) = hitl_persistence_error {
            eprintln!("failed to persist local HITL request: {error}");
            run_result = Err(format!("failed to persist HITL request: {error}"));
        }
        if let (Some(run_id), Some(expected_revision)) =
            (authoritative_run_id.as_deref(), authoritative_revision)
        {
            let (status, error) = match run_result {
                Ok(state) => desktop_run_outcome(&state),
                Err(error) => (DesktopRunStatus::Failed, Some(error)),
            };
            match self.session_store.transition_run(
                run_id,
                expected_revision,
                status,
                error,
                &now_iso(),
            ) {
                Ok(run) => {
                    if let Err(error) = self.session_store.settle_queued_run_inputs(
                        &run.id,
                        run.status,
                        &run.updated_at,
                    ) {
                        eprintln!("failed to settle queued run inputs: {error}");
                    }
                    self.publish_run_status(&run);
                }
                Err(error) => {
                    eprintln!("failed to persist authoritative local run result: {error}");
                }
            }
        }
        self.release_agent_run(&conversation_id);
    }

    fn worktree_manager(&self) -> WorktreeManager {
        WorktreeManager::new(
            self.workspace_root
                .lock()
                .expect("local workspace root")
                .clone(),
        )
    }

    fn agent_engine(
        &self,
        conversation: &LocalConversation,
        run: Option<&DesktopRun>,
    ) -> Result<ReActEngine, String> {
        let local_tool_host = match run.and_then(|run| run.environment.as_ref()) {
            Some(environment) => {
                self.worktree_manager().validate(environment)?;
                LocalToolHost::new(&environment.workspace_path)
                    .map_err(|error| error.to_string())?
            }
            None => self.tool_host.lock().expect("local tool host").clone(),
        };
        let tool_host: Arc<dyn ToolHost> = match conversation.current_mode {
            ConversationRunMode::Plan => Arc::new(PlanModeToolHost::new(
                local_tool_host,
                self.session_store.clone(),
                conversation.id.clone(),
            )),
            ConversationRunMode::Build => Arc::new(AuthorizedRunToolHost::new(
                local_tool_host,
                self.session_store.clone(),
                run.cloned().ok_or_else(|| {
                    "build mode requires an authoritative run for tool execution".to_string()
                })?,
            )),
        };
        Ok(ReActEngine::new(
            self.llm(&conversation.tenant_id),
            tool_host,
            self.checkpoints.clone(),
            self.clock.clone(),
        )
        .with_max_rounds(8))
    }

    fn persist_pending_hitl(
        &self,
        conversation_id: &str,
        run_id: Option<&str>,
        state: &SessionState,
    ) -> Result<Option<DesktopHitlRequest>, String> {
        if state.status != SessionStatus::AwaitingInput {
            return Ok(None);
        }
        let Some(pending) = state.pending_hitl.as_ref() else {
            return Err("session is awaiting input without a pending HITL request".to_string());
        };
        let request = DesktopHitlRequest {
            id: pending.id.clone(),
            conversation_id: conversation_id.to_string(),
            run_id: run_id.map(ToString::to_string),
            round: state.round,
            kind: pending.kind,
            prompt: pending.prompt.clone(),
            decision: pending.decision.as_deref().cloned(),
            status: DesktopHitlStatus::Pending,
            created_at: now_iso(),
            responded_at: None,
            response_data: None,
            response_actor: None,
            response_revision: None,
            idempotency_key: None,
        };
        if let Some(existing) = self.session_store.hitl_request(&request.id)? {
            if existing.conversation_id == request.conversation_id
                && existing.run_id == request.run_id
                && existing.kind == request.kind
                && existing.prompt == request.prompt
                && existing.decision == request.decision
            {
                return Ok(Some(existing));
            }
            return Err(format!("HITL request id collision: {}", request.id));
        }
        self.session_store.insert_hitl_request(&request)?;
        let mut item = self.timeline_item(
            hitl_timeline_type(request.kind),
            conversation_id.to_string(),
            None,
            None,
            Some(request.prompt.clone()),
            json!({
                "request_id": request.id,
                "requestId": request.id,
                "hitl_type": hitl_kind_name(request.kind),
                "question": request.prompt,
                "answered": false,
                "round": request.round,
                "run_id": request.run_id,
                "decision": request.decision,
            }),
        );
        item["requestId"] = json!(request.id);
        item["question"] = json!(request.prompt);
        item["answered"] = json!(false);
        self.append_timeline(conversation_id, item);
        Ok(Some(request))
    }

    async fn continue_after_hitl(
        self: Arc<Self>,
        conversation: LocalConversation,
        goal: String,
        authoritative_run: Option<DesktopRun>,
        control: Arc<LocalRunControl>,
    ) {
        let conversation_id = conversation.id.clone();
        let observer = Arc::new(LocalTimelineObserver {
            state: Arc::clone(&self),
            conversation_id: conversation_id.clone(),
        });
        let engine = match self.agent_engine(&conversation, authoritative_run.as_ref()) {
            Ok(engine) => engine,
            Err(error) => {
                let item = self.timeline_item(
                    "error",
                    conversation_id.clone(),
                    None,
                    None,
                    Some(error.clone()),
                    json!({ "error": error }),
                );
                self.append_timeline(&conversation_id, item);
                if let Some(run) = authoritative_run {
                    if let Ok(failed) = self.session_store.transition_run(
                        &run.id,
                        run.revision,
                        DesktopRunStatus::Failed,
                        Some("execution environment is unavailable".to_string()),
                        &now_iso(),
                    ) {
                        self.publish_run_status(&failed);
                    }
                }
                self.release_agent_run(&conversation_id);
                return;
            }
        };
        let result = engine
            .run_observed_controlled(
                &conversation_id,
                &goal,
                Some(&conversation.project_id),
                observer,
                control,
            )
            .await;
        let mut run_result = match result {
            Ok(state) => Ok(state),
            Err(error) => {
                let message = error.to_string();
                let item = self.timeline_item(
                    "error",
                    conversation_id.clone(),
                    None,
                    None,
                    Some(message.clone()),
                    json!({ "error": message }),
                );
                self.append_timeline(&conversation_id, item);
                Err(message)
            }
        };
        let hitl_persistence_error = run_result.as_ref().ok().and_then(|state| {
            self.persist_pending_hitl(
                &conversation_id,
                authoritative_run.as_ref().map(|run| run.id.as_str()),
                state,
            )
            .err()
        });
        if let Some(error) = hitl_persistence_error {
            eprintln!("failed to persist resumed HITL request: {error}");
            run_result = Err(format!("failed to persist resumed HITL request: {error}"));
        }
        if let Some(run) = authoritative_run {
            let (status, error) = match run_result {
                Ok(state) => desktop_run_outcome(&state),
                Err(error) => (DesktopRunStatus::Failed, Some(error)),
            };
            match self.session_store.transition_run(
                &run.id,
                run.revision,
                status,
                error,
                &now_iso(),
            ) {
                Ok(run) => {
                    if let Err(error) = self.session_store.settle_queued_run_inputs(
                        &run.id,
                        run.status,
                        &run.updated_at,
                    ) {
                        eprintln!("failed to settle resumed queued run inputs: {error}");
                    }
                    self.publish_run_status(&run);
                }
                Err(error) => eprintln!("failed to persist resumed local run result: {error}"),
            }
        }
        self.release_agent_run(&conversation_id);
    }

    fn llm(&self, tenant_id: &str) -> Arc<dyn LlmPort> {
        let binding = self
            .provider_bindings
            .lock()
            .expect("provider runtime bindings")
            .get(tenant_id)
            .cloned();
        if let Some(binding) = binding {
            if binding.auth_method != "none" && binding.credential.is_none() {
                return Arc::new(UnconfiguredLocalLlm);
            }
            if matches!(
                binding.provider_type.as_str(),
                "openai" | "openai_compatible"
            ) {
                let llm = HttpLlm::new(binding.base_url, binding.model);
                let llm = if let Some(credential) = binding.credential {
                    llm.with_api_key(credential)
                } else {
                    llm
                };
                return Arc::new(llm);
            }
            if binding.provider_type == "anthropic" {
                let llm = AnthropicLlm::new(binding.base_url, binding.model);
                let llm = if let Some(credential) = binding.credential {
                    llm.with_api_key(credential)
                } else {
                    llm
                };
                return Arc::new(AnthropicAgentLlm { inner: llm });
            }
        }
        #[cfg(test)]
        {
            let config = self.config.lock().expect("local runtime config").clone();
            if config.provider == "mock" {
                return Arc::new(MockLocalLlm);
            }
        }
        Arc::new(UnconfiguredLocalLlm)
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
        let latest_run = self
            .session_store
            .list_runs(&conversation.id)
            .ok()
            .and_then(|runs| runs.into_iter().next());
        let status = latest_run
            .as_ref()
            .and_then(|run| serde_json::to_value(run.status).ok())
            .unwrap_or_else(|| json!("active"));
        let run_metadata = latest_run
            .as_ref()
            .and_then(|run| serde_json::to_value(run).ok())
            .unwrap_or(Value::Null);
        let environment_metadata = latest_run
            .as_ref()
            .and_then(|run| run.environment.as_ref())
            .and_then(|environment| serde_json::to_value(environment).ok())
            .unwrap_or_else(|| json!({ "kind": "local", "label": "Local runtime" }));
        json!({
            "id": conversation.id,
            "project_id": conversation.project_id,
            "tenant_id": conversation.tenant_id,
            "user_id": "local-user",
            "title": conversation.title,
            "status": status,
            "message_count": self
                .session_store
                .timeline_count(&conversation.id)
                .unwrap_or(0),
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "summary": null,
            "agent_config": {
                "selected_agent_id": "builtin:all-access",
                "capability_mode": conversation.capability_mode,
            },
            "metadata": {
                "runtime": "local",
                "capability_mode": conversation.capability_mode,
                "run": run_metadata,
                "environment": environment_metadata,
            },
            "conversation_mode": "workspace",
            "current_mode": conversation.current_mode,
            "workspace_id": conversation.workspace_id,
            "linked_workspace_task_id": null,
            "workspace_name": "Local workspace",
            "participant_agents": ["local-agent"],
            "coordinator_agent_id": "local-agent",
            "focused_agent_id": "local-agent",
        })
    }
}

fn desktop_run_outcome(state: &SessionState) -> (DesktopRunStatus, Option<String>) {
    match state.status {
        SessionStatus::Running => (
            DesktopRunStatus::Failed,
            Some("agent run returned while still running".to_string()),
        ),
        SessionStatus::AwaitingInput => {
            let status = match state.pending_hitl.as_ref().map(|request| request.kind) {
                Some(HitlKind::Permission) => DesktopRunStatus::NeedsApproval,
                _ => DesktopRunStatus::NeedsInput,
            };
            (status, None)
        }
        SessionStatus::Paused => (DesktopRunStatus::Paused, None),
        SessionStatus::Finished => (DesktopRunStatus::ReadyReview, None),
        SessionStatus::Failed => {
            let error = state
                .transcript
                .iter()
                .rev()
                .find(|entry| entry.role == Role::Answer)
                .map(|entry| entry.content.clone())
                .or_else(|| state.answer.clone())
                .unwrap_or_else(|| "agent session failed".to_string());
            (DesktopRunStatus::Failed, Some(error))
        }
        SessionStatus::Cancelled => (DesktopRunStatus::Cancelled, None),
    }
}

fn hitl_kind_name(kind: HitlKind) -> &'static str {
    match kind {
        HitlKind::Clarification => "clarification",
        HitlKind::Decision => "decision",
        HitlKind::EnvVar => "env_var",
        HitlKind::Permission => "permission",
    }
}

fn hitl_timeline_type(kind: HitlKind) -> &'static str {
    match kind {
        HitlKind::Clarification => "clarification_asked",
        HitlKind::Decision => "decision_asked",
        HitlKind::EnvVar => "env_var_requested",
        HitlKind::Permission => "permission_asked",
    }
}

fn local_router(state: Arc<LocalRuntimeState>) -> Router {
    let protected = Router::new()
        .route("/api/v1/auth/me", get(auth_me))
        .route("/api/v1/auth/signout", post(sign_out))
        .route("/api/v1/tenants", get(list_tenants))
        .route("/api/v1/projects", get(list_projects))
        .route("/api/v1/workspace-context", get(get_workspace_context))
        .route(
            "/api/v1/workspace-context/switch",
            post(switch_workspace_context),
        )
        .route(
            "/api/v1/llm-providers/",
            get(list_llm_providers).post(create_llm_provider),
        )
        .route("/api/v1/llm-providers/types", get(list_llm_provider_types))
        .route(
            "/api/v1/llm-providers/:provider_id",
            patch(update_llm_provider),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/test",
            post(validate_llm_provider),
        )
        .route("/api/v1/skills/", get(list_managed_skills))
        .route(
            "/api/v1/skills/:skill_id/status",
            patch(set_managed_skill_status),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins",
            get(list_managed_plugins),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins/:plugin_id/enable",
            post(enable_managed_plugin),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins/:plugin_id/disable",
            post(disable_managed_plugin),
        )
        .route("/api/v1/agent/definitions", get(list_managed_agents))
        .route(
            "/api/v1/agent/definitions/:definition_id/enabled",
            patch(set_managed_agent_enabled),
        )
        .route(
            "/api/v1/projects/:project_id/my-work",
            get(list_project_my_work),
        )
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
            "/api/v1/agent/conversations/:conversation_id/session",
            get(session_projection::conversation_session),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/messages",
            get(conversation_messages).post(run_conversation_message),
        )
        .route(
            "/api/v1/agent/plans/approve-and-start",
            post(approve_plan_and_start),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/runs",
            get(list_conversation_runs),
        )
        .route("/api/v1/agent/runs/:run_id", get(get_run))
        .route("/api/v1/agent/runs/:run_id/changes", get(get_run_changes))
        .route(
            "/api/v1/agent/runs/:run_id/inputs",
            get(list_run_inputs).post(create_run_input),
        )
        .route(
            "/api/v1/agent/run-inputs/:input_id/promote-to-plan",
            post(promote_run_input_to_plan),
        )
        .route(
            "/api/v1/agent/runs/:run_id/pause",
            post(run_control::pause_run),
        )
        .route(
            "/api/v1/agent/runs/:run_id/resume",
            post(run_control::resume_run),
        )
        .route(
            "/api/v1/agent/runs/:run_id/fork",
            post(run_control::fork_recovery_run),
        )
        .route(
            "/api/v1/agent/runs/:run_id/cancel",
            post(run_control::cancel_run),
        )
        .route(
            "/api/v1/agent/runs/:run_id/review",
            post(run_control::review_run),
        )
        .route(
            "/api/v1/agent/artifact-versions/:artifact_version_id/review",
            post(review_artifact_version),
        )
        .route(
            "/api/v1/agent/artifact-versions/:artifact_version_id/deliver",
            post(deliver_artifact_version),
        )
        .route("/api/v1/agent/hitl/respond", post(respond_to_hitl))
        .route("/api/v1/agent/plan/mode", post(switch_plan_mode))
        .route(
            "/api/v1/agent/plan/mode/:conversation_id",
            get(get_plan_mode),
        )
        .route(
            "/api/v1/agent/plan/tasks/:conversation_id",
            get(list_agent_plan_tasks),
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
            require_active_scope,
        ))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_user_session,
        ));

    Router::new()
        .route("/api/v1/auth/local-session", post(create_local_session))
        .route(
            "/api/v1/auth/local-session/resume",
            post(resume_local_session),
        )
        .merge(protected)
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_launch_capability,
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
        .allow_headers([
            AUTHORIZATION,
            CONTENT_TYPE,
            HeaderName::from_static("x-agistack-launch"),
        ])
}

type LocalJsonResult = Result<Json<Value>, (StatusCode, Json<Value>)>;

fn local_store_error(error: String) -> (StatusCode, Json<Value>) {
    eprintln!("desktop session store error: {error}");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({ "detail": "desktop session store unavailable" })),
    )
}

fn active_workspace_scope_error() -> (StatusCode, Json<Value>) {
    (
        StatusCode::FORBIDDEN,
        Json(json!({ "detail": "resource is outside the active workspace context" })),
    )
}

fn ensure_active_project(
    authenticated: &AuthenticatedContext,
    project_id: &str,
) -> Result<(), (StatusCode, Json<Value>)> {
    if project_id == authenticated.workspace.project_id {
        Ok(())
    } else {
        Err(active_workspace_scope_error())
    }
}

fn scoped_conversation(
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    conversation_id: &str,
) -> Result<LocalConversation, (StatusCode, Json<Value>)> {
    let conversation = state
        .session_store
        .conversation(conversation_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "conversation not found" })),
            )
        })?;
    ensure_active_project(authenticated, &conversation.project_id)?;
    if conversation.tenant_id != authenticated.workspace.tenant_id {
        return Err(active_workspace_scope_error());
    }
    Ok(conversation)
}

fn ensure_active_workspace(
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    workspace_id: &str,
) -> Result<(), (StatusCode, Json<Value>)> {
    let project_id = state
        .session_store
        .workspace_project_id(workspace_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "workspace not found" })),
            )
        })?;
    ensure_active_project(authenticated, &project_id)
}

fn execution_environment_error(error: String) -> (StatusCode, Json<Value>) {
    (
        StatusCode::CONFLICT,
        Json(json!({
            "detail": error,
            "recovery_action": "fork",
        })),
    )
}

fn authority_error(error: DesktopAuthorityError) -> (StatusCode, Json<Value>) {
    let status = match error {
        DesktopAuthorityError::ConversationNotFound => StatusCode::NOT_FOUND,
        DesktopAuthorityError::ProjectMismatch
        | DesktopAuthorityError::PlanNotReady
        | DesktopAuthorityError::PlanVersionMismatch
        | DesktopAuthorityError::PlanVersionConflict { .. }
        | DesktopAuthorityError::IdempotencyConflict => StatusCode::CONFLICT,
        DesktopAuthorityError::Storage(_) => StatusCode::INTERNAL_SERVER_ERROR,
    };
    (status, Json(json!({ "detail": error.to_string() })))
}

fn auth_context_error(error: AuthContextError) -> (StatusCode, Json<Value>) {
    let status = match error {
        AuthContextError::MembershipRequired => StatusCode::FORBIDDEN,
        AuthContextError::ProjectUnavailable => StatusCode::NOT_FOUND,
        AuthContextError::RevisionConflict { .. } | AuthContextError::IdempotencyConflict => {
            StatusCode::CONFLICT
        }
        AuthContextError::Storage(_) => StatusCode::INTERNAL_SERVER_ERROR,
    };
    (status, Json(json!({ "detail": error.to_string() })))
}

fn resource_registry_error(error: ResourceRegistryError) -> (StatusCode, Json<Value>) {
    let detail = error.to_string();
    match error {
        ResourceRegistryError::NotFound => {
            (StatusCode::NOT_FOUND, Json(json!({ "detail": detail })))
        }
        ResourceRegistryError::Immutable { .. } => (
            StatusCode::CONFLICT,
            Json(json!({
                "code": "immutable_resource",
                "detail": detail,
            })),
        ),
        ResourceRegistryError::RevisionConflict { .. } => {
            (StatusCode::CONFLICT, Json(json!({ "detail": detail })))
        }
        ResourceRegistryError::Storage(_) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({ "detail": detail })),
        ),
    }
}

async fn require_launch_capability(
    State(state): State<Arc<LocalRuntimeState>>,
    request: axum::extract::Request,
    next: Next,
) -> Response {
    if request_has_launch_capability(request.headers(), &state.api_token) {
        next.run(request).await
    } else {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({ "detail": "local runtime launch capability required" })),
        )
            .into_response()
    }
}

async fn require_user_session(
    State(state): State<Arc<LocalRuntimeState>>,
    mut request: axum::extract::Request,
    next: Next,
) -> Response {
    let credential = bearer_credential(request.headers())
        .or_else(|| websocket_protocol_credential(request.headers(), "memstack.auth"));
    let authenticated = credential.and_then(|credential| {
        state
            .session_store
            .validate_session_credential(credential, Utc::now().timestamp_millis())
            .ok()
            .flatten()
    });
    let Some(authenticated) = authenticated else {
        return (
            StatusCode::UNAUTHORIZED,
            Json(json!({ "detail": "authenticated desktop session required" })),
        )
            .into_response();
    };
    request.extensions_mut().insert(authenticated);
    next.run(request).await
}

async fn require_active_scope(
    State(_state): State<Arc<LocalRuntimeState>>,
    request: axum::extract::Request,
    next: Next,
) -> Response {
    let Some(authenticated) = request.extensions().get::<AuthenticatedContext>() else {
        return (
            StatusCode::UNAUTHORIZED,
            Json(json!({ "detail": "authenticated desktop session required" })),
        )
            .into_response();
    };
    let (tenant_id, project_id) = path_workspace_scope(request.uri().path());
    let tenant_matches = tenant_id
        .map(|value| value == authenticated.workspace.tenant_id)
        .unwrap_or(true);
    let project_matches = project_id
        .map(|value| value == authenticated.workspace.project_id)
        .unwrap_or(true);
    if !tenant_matches || !project_matches {
        return (
            StatusCode::FORBIDDEN,
            Json(json!({ "detail": "request is outside the active workspace context" })),
        )
            .into_response();
    }
    next.run(request).await
}

fn request_has_launch_capability(headers: &HeaderMap, expected: &str) -> bool {
    if headers
        .get("x-agistack-launch")
        .and_then(|value| value.to_str().ok())
        == Some(expected)
    {
        return true;
    }
    if websocket_protocol_credential(headers, "memstack.launch") == Some(expected) {
        return true;
    }
    bearer_credential(headers) == Some(expected)
        || websocket_protocol_credential(headers, "memstack.auth") == Some(expected)
}

fn bearer_credential(headers: &HeaderMap) -> Option<&str> {
    headers
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "))
}

fn websocket_protocol_credential<'a>(headers: &'a HeaderMap, marker: &str) -> Option<&'a str> {
    let protocols: Vec<&str> = headers
        .get_all("sec-websocket-protocol")
        .iter()
        .filter_map(|value| value.to_str().ok())
        .flat_map(|value| value.split(',').map(str::trim))
        .collect();
    protocols
        .windows(2)
        .find(|pair| pair[0] == marker)
        .map(|pair| pair[1])
}

fn path_workspace_scope(path: &str) -> (Option<&str>, Option<&str>) {
    let segments = path.trim_matches('/').split('/').collect::<Vec<_>>();
    match segments.as_slice() {
        ["api", "v1", "tenants", tenant_id, "projects", project_id, ..] => {
            (Some(tenant_id), Some(project_id))
        }
        ["api", "v1", "projects", project_id, ..] => (None, Some(project_id)),
        _ => (None, None),
    }
}

async fn create_local_session(
    State(state): State<Arc<LocalRuntimeState>>,
    Json(request): Json<LocalSessionRequest>,
) -> LocalJsonResult {
    let credential = format!(
        "local-session-{}.{}",
        Uuid::new_v4(),
        generate_capability_token()
    );
    let outcome = state
        .session_store
        .create_local_session(
            credential,
            request.trusted_device,
            Utc::now().timestamp_millis(),
        )
        .map_err(auth_context_error)?;
    serde_json::to_value(outcome)
        .map(Json)
        .map_err(|error| local_store_error(error.to_string()))
}

async fn resume_local_session(
    State(state): State<Arc<LocalRuntimeState>>,
    Json(request): Json<TrustedSessionResumeRequest>,
) -> LocalJsonResult {
    let credential = format!(
        "local-session-{}.{}",
        Uuid::new_v4(),
        generate_capability_token()
    );
    let outcome = state
        .session_store
        .resume_trusted_local_session(
            request.session_id.trim(),
            credential,
            Utc::now().timestamp_millis(),
        )
        .map_err(auth_context_error)?;
    let Some(outcome) = outcome else {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({ "detail": "trusted local session unavailable" })),
        ));
    };
    serde_json::to_value(outcome)
        .map(Json)
        .map_err(|error| local_store_error(error.to_string()))
}

async fn sign_out(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> LocalJsonResult {
    state
        .session_store
        .revoke_session(&authenticated.session_id, Utc::now().timestamp_millis())
        .map_err(local_store_error)?;
    Ok(Json(json!({ "success": true })))
}

async fn auth_me(Extension(authenticated): Extension<AuthenticatedContext>) -> LocalJsonResult {
    serde_json::to_value(authenticated.user)
        .map(Json)
        .map_err(|error| local_store_error(error.to_string()))
}

async fn list_tenants(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> LocalJsonResult {
    let tenants = state
        .session_store
        .list_user_tenants(&authenticated.user.user_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({ "items": tenants })))
}

#[derive(Debug, Default, Deserialize)]
struct ProjectListQuery {
    tenant_id: Option<String>,
}

async fn list_projects(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ProjectListQuery>,
) -> LocalJsonResult {
    let tenant_id = query
        .tenant_id
        .as_deref()
        .unwrap_or(&authenticated.workspace.tenant_id);
    let projects = state
        .session_store
        .list_user_projects(&authenticated.user.user_id, tenant_id)
        .map_err(auth_context_error)?;
    Ok(Json(json!({ "items": projects })))
}

async fn get_workspace_context(
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> Json<Value> {
    Json(json!({
        "context": authenticated.workspace,
        "membership_role": authenticated.membership_role,
    }))
}

async fn switch_workspace_context(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<ContextSwitchRequest>,
) -> LocalJsonResult {
    let outcome = state
        .session_store
        .switch_workspace_context(&authenticated, &request, Utc::now().timestamp_millis())
        .map_err(auth_context_error)?;
    serde_json::to_value(outcome)
        .map(Json)
        .map_err(|error| local_store_error(error.to_string()))
}

#[derive(Debug, Default, Deserialize)]
struct ManagedResourceListQuery {
    tenant_id: Option<String>,
    project_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ManagedSkillStatusQuery {
    status: String,
    tenant_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ManagedAgentEnabledBody {
    enabled: bool,
}

#[derive(Debug, Deserialize)]
struct LlmProviderMutation {
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    provider_type: Option<String>,
    #[serde(default)]
    base_url: Option<String>,
    #[serde(default)]
    auth_method: Option<String>,
    #[serde(default)]
    api_key: Option<String>,
    #[serde(default)]
    llm_model: Option<String>,
    #[serde(default)]
    allowed_models: Option<Vec<String>>,
    #[serde(default)]
    is_active: Option<bool>,
    #[serde(default)]
    expected_revision: Option<u64>,
}

#[derive(Debug, Clone, Copy, Serialize)]
struct LlmProviderTypeDescriptor {
    provider_type: &'static str,
    auth_methods: &'static [&'static str],
}

const LOCAL_LLM_PROVIDER_TYPES: &[LlmProviderTypeDescriptor] = &[
    LlmProviderTypeDescriptor {
        provider_type: "openai",
        auth_methods: &["api_key", "none"],
    },
    LlmProviderTypeDescriptor {
        provider_type: "anthropic",
        auth_methods: &["api_key", "none"],
    },
    LlmProviderTypeDescriptor {
        provider_type: "openai_compatible",
        auth_methods: &["api_key", "none"],
    },
];

async fn list_llm_provider_types() -> Json<Vec<LlmProviderTypeDescriptor>> {
    Json(LOCAL_LLM_PROVIDER_TYPES.to_vec())
}

async fn list_llm_providers(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> LocalJsonResult {
    let tenant_id = &authenticated.workspace.tenant_id;
    let providers = state
        .session_store
        .list_managed_resources(ManagedResourceKind::Provider, "tenant", tenant_id)
        .map_err(local_store_error)?;
    let binding = state
        .provider_bindings
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?
        .get(tenant_id)
        .cloned();
    Ok(Json(Value::Array(
        providers
            .into_iter()
            .map(|provider| provider_with_runtime_state(provider, binding.as_ref()))
            .collect(),
    )))
}

async fn create_llm_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<LlmProviderMutation>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    let provider_id = format!("provider-{}", Uuid::new_v4());
    mutate_llm_provider(state, authenticated, provider_id, request, true)
}

async fn update_llm_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(provider_id): Path<String>,
    Json(request): Json<LlmProviderMutation>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    if request.expected_revision.is_none() {
        return Err((
            StatusCode::PRECONDITION_REQUIRED,
            Json(json!({ "detail": "expected_revision is required" })),
        ));
    }
    mutate_llm_provider(state, authenticated, provider_id, request, false)
}

fn mutate_llm_provider(
    state: Arc<LocalRuntimeState>,
    authenticated: AuthenticatedContext,
    provider_id: String,
    request: LlmProviderMutation,
    creating: bool,
) -> LocalJsonResult {
    let tenant_id = &authenticated.workspace.tenant_id;
    let LlmProviderMutation {
        name,
        provider_type,
        base_url,
        auth_method,
        api_key,
        llm_model,
        allowed_models,
        is_active,
        expected_revision,
    } = request;
    let current = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            tenant_id,
            &provider_id,
        )
        .map_err(local_store_error)?;
    if !creating && current.is_none() {
        return Err(resource_registry_error(ResourceRegistryError::NotFound));
    }
    if creating && current.is_some() {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "provider id already exists" })),
        ));
    }
    let mut provider = current.unwrap_or_else(|| {
        json!({
            "id": provider_id,
            "name": "New provider",
            "provider_type": "openai_compatible",
            "tenant_id": tenant_id,
            "is_active": false,
            "base_url": null,
            "auth_method": "api_key",
            "credential_source": "runtime_memory",
            "credential_configured": false,
            "llm_model": null,
            "allowed_models": [],
            "secondary_models": [],
            "health_status": "not_configured",
            "revision": 0,
        })
    });
    let object = provider
        .as_object_mut()
        .ok_or_else(|| local_store_error("managed provider must be an object".to_string()))?;
    if let Some(name) = normalized_optional(name, "provider name")? {
        object.insert("name".to_string(), json!(name));
    }
    if let Some(provider_type) = normalized_optional(provider_type, "provider type")? {
        object.insert("provider_type".to_string(), json!(provider_type));
    }
    if let Some(base_url) = base_url {
        let base_url = base_url.trim().trim_end_matches('/').to_string();
        if !base_url.is_empty()
            && !base_url.starts_with("http://")
            && !base_url.starts_with("https://")
        {
            return Err((
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({ "detail": "provider base URL must use http or https" })),
            ));
        }
        object.insert(
            "base_url".to_string(),
            if base_url.is_empty() {
                Value::Null
            } else {
                json!(base_url)
            },
        );
    }
    if let Some(auth_method) = normalized_optional(auth_method, "auth method")? {
        object.insert("auth_method".to_string(), json!(auth_method));
    }
    if let Some(model) = llm_model {
        let model = model.trim().to_string();
        object.insert(
            "llm_model".to_string(),
            if model.is_empty() {
                Value::Null
            } else {
                json!(model)
            },
        );
    }
    if let Some(models) = allowed_models {
        object.insert(
            "allowed_models".to_string(),
            json!(normalized_model_ids(models)),
        );
    }
    if let Some(is_active) = is_active {
        object.insert("is_active".to_string(), json!(is_active));
    }
    let provider_type = object
        .get("provider_type")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    if !runtime_provider_supported(&provider_type) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": "unsupported local provider type" })),
        ));
    }
    let auth_method = object
        .get("auth_method")
        .and_then(Value::as_str)
        .unwrap_or("api_key")
        .to_string();
    if !matches!(auth_method.as_str(), "api_key" | "none") {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": "unsupported local provider auth method" })),
        ));
    }
    object.insert("credential_source".to_string(), json!("runtime_memory"));
    object.insert("credential_configured".to_string(), json!(false));
    object.insert("health_status".to_string(), json!("not_checked"));

    let is_active = object
        .get("is_active")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let expected_revision = if creating { Some(0) } else { expected_revision };
    let previous_binding = state
        .provider_bindings
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?
        .get(tenant_id)
        .cloned();
    let submitted_credential = api_key.as_deref().and_then(normalized_runtime_credential);
    let provider_base_url = object
        .get("base_url")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let provider_model = object
        .get("llm_model")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let next_binding = if is_active && !provider_base_url.is_empty() && !provider_model.is_empty() {
        let preserved_credential = previous_binding.as_ref().and_then(|current| {
            (current.provider_id == provider_id
                && current.provider_type == provider_type
                && current.base_url == provider_base_url)
                .then(|| current.credential.clone())
                .flatten()
        });
        Some(ProviderRuntimeBinding {
            provider_id: provider_id.clone(),
            provider_type,
            base_url: provider_base_url,
            model: provider_model,
            auth_method: auth_method.clone(),
            credential: if auth_method == "none" {
                None
            } else {
                submitted_credential.or(preserved_credential)
            },
        })
    } else if previous_binding
        .as_ref()
        .is_some_and(|binding| binding.provider_id != provider_id)
    {
        previous_binding.clone()
    } else {
        None
    };
    let stored = state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            tenant_id,
            &provider_id,
            if is_active { "active" } else { "disabled" },
            expected_revision,
            provider,
            Utc::now().timestamp_millis(),
        )
        .map_err(resource_registry_error)?;
    {
        let mut bindings = state
            .provider_bindings
            .lock()
            .map_err(|error| local_store_error(error.to_string()))?;
        if let Some(binding) = next_binding.clone() {
            bindings.insert(tenant_id.to_string(), binding);
        } else {
            bindings.remove(tenant_id);
        }
    }
    if tenant_id == "local" {
        let mut runtime = state
            .config
            .lock()
            .map_err(|error| local_store_error(error.to_string()))?;
        runtime.api_key.clear();
        if let Some(binding) = next_binding.as_ref() {
            runtime.provider.clone_from(&binding.provider_type);
            runtime.base_url.clone_from(&binding.base_url);
            runtime.model.clone_from(&binding.model);
        } else {
            runtime.provider = "unconfigured".to_string();
            runtime.model.clear();
        }
    }
    let active_binding = state
        .provider_bindings
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?
        .get(tenant_id)
        .cloned();
    Ok(Json(provider_with_runtime_state(
        stored,
        active_binding.as_ref(),
    )))
}

async fn validate_llm_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(provider_id): Path<String>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    let tenant_id = &authenticated.workspace.tenant_id;
    let provider = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            tenant_id,
            &provider_id,
        )
        .map_err(local_store_error)?
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))?;
    let binding = state
        .provider_bindings
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?
        .get(tenant_id)
        .cloned();
    let status = provider_configuration_status(&provider, binding.as_ref());
    Ok(Json(json!({
        "provider": provider_with_runtime_state(provider, binding.as_ref()),
        "status": status,
        "probed": false,
        "detail": "configuration validated locally; no external request was sent",
    })))
}

async fn list_managed_skills(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ManagedResourceListQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let items = state
        .session_store
        .list_managed_resources(
            ManagedResourceKind::Skill,
            "tenant",
            &authenticated.workspace.tenant_id,
        )
        .map_err(local_store_error)?;
    Ok(Json(json!({ "items": items })))
}

async fn set_managed_skill_status(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<ManagedSkillStatusQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    ensure_managed_resource_manager(&authenticated)?;
    if !matches!(query.status.as_str(), "active" | "disabled" | "deprecated") {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": "unsupported skill status" })),
        ));
    }
    let mut skill = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Skill,
            "tenant",
            &authenticated.workspace.tenant_id,
            &skill_id,
        )
        .map_err(local_store_error)?
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))?;
    let revision = skill.get("revision").and_then(Value::as_u64).unwrap_or(0);
    if let Some(object) = skill.as_object_mut() {
        object.insert("status".to_string(), json!(query.status));
    }
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Skill,
            "tenant",
            &authenticated.workspace.tenant_id,
            &skill_id,
            &query.status,
            Some(revision),
            skill,
            Utc::now().timestamp_millis(),
        )
        .map(Json)
        .map_err(resource_registry_error)
}

async fn list_managed_plugins(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(tenant_id): Path<String>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, Some(&tenant_id))?;
    let items = state
        .session_store
        .list_managed_resources(ManagedResourceKind::Plugin, "tenant", &tenant_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({ "items": items })))
}

async fn enable_managed_plugin(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, plugin_id)): Path<(String, String)>,
) -> LocalJsonResult {
    set_plugin_enabled(state, authenticated, tenant_id, plugin_id, true)
}

async fn disable_managed_plugin(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, plugin_id)): Path<(String, String)>,
) -> LocalJsonResult {
    set_plugin_enabled(state, authenticated, tenant_id, plugin_id, false)
}

fn set_plugin_enabled(
    state: Arc<LocalRuntimeState>,
    authenticated: AuthenticatedContext,
    tenant_id: String,
    plugin_id: String,
    enabled: bool,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, Some(&tenant_id))?;
    ensure_managed_resource_manager(&authenticated)?;
    state
        .session_store
        .set_managed_resource_enabled(
            ManagedResourceKind::Plugin,
            "tenant",
            &tenant_id,
            &plugin_id,
            enabled,
            Utc::now().timestamp_millis(),
        )
        .map(|plugin| Json(json!({ "item": plugin })))
        .map_err(resource_registry_error)
}

async fn list_managed_agents(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ManagedResourceListQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    ensure_project_scope(&authenticated, query.project_id.as_deref())?;
    let items = state
        .session_store
        .list_managed_resources(
            ManagedResourceKind::Agent,
            "project",
            &authenticated.workspace.project_id,
        )
        .map_err(local_store_error)?;
    Ok(Json(json!({ "items": items })))
}

async fn set_managed_agent_enabled(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(definition_id): Path<String>,
    Query(query): Query<ManagedResourceListQuery>,
    Json(request): Json<ManagedAgentEnabledBody>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    ensure_project_scope(&authenticated, query.project_id.as_deref())?;
    ensure_managed_resource_manager(&authenticated)?;
    state
        .session_store
        .set_managed_resource_enabled(
            ManagedResourceKind::Agent,
            "project",
            &authenticated.workspace.project_id,
            &definition_id,
            request.enabled,
            Utc::now().timestamp_millis(),
        )
        .map(Json)
        .map_err(resource_registry_error)
}

fn ensure_tenant_scope(
    authenticated: &AuthenticatedContext,
    requested: Option<&str>,
) -> Result<(), (StatusCode, Json<Value>)> {
    if requested
        .map(|tenant_id| tenant_id != authenticated.workspace.tenant_id)
        .unwrap_or(false)
    {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({ "detail": "request is outside the active tenant context" })),
        ));
    }
    Ok(())
}

fn ensure_project_scope(
    authenticated: &AuthenticatedContext,
    requested: Option<&str>,
) -> Result<(), (StatusCode, Json<Value>)> {
    if requested
        .map(|project_id| project_id != authenticated.workspace.project_id)
        .unwrap_or(false)
    {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({ "detail": "request is outside the active project context" })),
        ));
    }
    Ok(())
}

fn normalized_optional(
    value: Option<String>,
    label: &str,
) -> Result<Option<String>, (StatusCode, Json<Value>)> {
    value
        .map(|value| {
            let value = value.trim().to_string();
            if value.is_empty() {
                Err((
                    StatusCode::UNPROCESSABLE_ENTITY,
                    Json(json!({ "detail": format!("{label} cannot be empty") })),
                ))
            } else {
                Ok(value)
            }
        })
        .transpose()
}

fn normalized_model_ids(models: Vec<String>) -> Vec<String> {
    let mut seen = HashSet::new();
    models
        .into_iter()
        .map(|model| model.trim().to_string())
        .filter(|model| !model.is_empty() && seen.insert(model.clone()))
        .collect()
}

fn normalized_runtime_credential(value: &str) -> Option<String> {
    let value = value.trim();
    (!value.is_empty()).then(|| value.to_string())
}

fn runtime_provider_supported(provider_type: &str) -> bool {
    matches!(provider_type, "openai" | "openai_compatible" | "anthropic")
}

fn ensure_provider_manager(
    authenticated: &AuthenticatedContext,
) -> Result<(), (StatusCode, Json<Value>)> {
    if matches!(authenticated.membership_role.as_str(), "owner" | "admin") {
        return Ok(());
    }
    Err((
        StatusCode::FORBIDDEN,
        Json(json!({ "detail": "provider management requires tenant owner access" })),
    ))
}

fn ensure_managed_resource_manager(
    authenticated: &AuthenticatedContext,
) -> Result<(), (StatusCode, Json<Value>)> {
    if matches!(authenticated.membership_role.as_str(), "owner" | "admin") {
        return Ok(());
    }
    Err((
        StatusCode::FORBIDDEN,
        Json(json!({
            "code": "resource_manager_required",
            "detail": "managed resource mutation requires tenant owner access",
        })),
    ))
}

fn provider_configuration_status(
    provider: &Value,
    binding: Option<&ProviderRuntimeBinding>,
) -> &'static str {
    if provider.get("is_active").and_then(Value::as_bool) != Some(true) {
        return "disabled";
    }
    let provider_id = provider
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let provider_type = provider
        .get("provider_type")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let base_url = provider
        .get("base_url")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let model = provider
        .get("llm_model")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if !runtime_provider_supported(provider_type) || base_url.is_empty() || model.is_empty() {
        return "not_configured";
    }
    let Some(binding) = binding.filter(|binding| binding.provider_id == provider_id) else {
        return "not_selected";
    };
    let auth_method = provider
        .get("auth_method")
        .and_then(Value::as_str)
        .unwrap_or("api_key");
    if auth_method != "none" && binding.credential.is_none() {
        return "needs_credentials";
    }
    "configuration_valid"
}

fn provider_with_runtime_state(
    mut provider: Value,
    binding: Option<&ProviderRuntimeBinding>,
) -> Value {
    let provider_id = provider
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let selected_binding = binding.filter(|binding| binding.provider_id == provider_id);
    let status = provider_configuration_status(&provider, binding);
    if let Some(object) = provider.as_object_mut() {
        object.insert(
            "credential_configured".to_string(),
            json!(selected_binding.is_some_and(|binding| binding.credential.is_some())),
        );
        object.insert(
            "runtime_selected".to_string(),
            json!(selected_binding.is_some()),
        );
        object.insert("health_status".to_string(), json!(status));
    }
    provider
}

fn my_work_group(status: DesktopRunStatus) -> Option<&'static str> {
    match status {
        DesktopRunStatus::NeedsApproval => Some("needs_approval"),
        DesktopRunStatus::ReadyReview => Some("ready_review"),
        DesktopRunStatus::Queued | DesktopRunStatus::Running => Some("running"),
        DesktopRunStatus::NeedsInput
        | DesktopRunStatus::Paused
        | DesktopRunStatus::Failed
        | DesktopRunStatus::Disconnected
        | DesktopRunStatus::Interrupted => Some("needs_input"),
        DesktopRunStatus::Completed | DesktopRunStatus::Cancelled => None,
    }
}

fn my_work_required_action(status: DesktopRunStatus) -> &'static str {
    match status {
        DesktopRunStatus::NeedsApproval => "review_approval",
        DesktopRunStatus::ReadyReview => "review_result",
        DesktopRunStatus::Queued | DesktopRunStatus::Running => "observe",
        DesktopRunStatus::NeedsInput => "provide_input",
        DesktopRunStatus::Paused => "resume",
        DesktopRunStatus::Disconnected => "reattach",
        DesktopRunStatus::Interrupted | DesktopRunStatus::Failed => "inspect_failure",
        DesktopRunStatus::Completed | DesktopRunStatus::Cancelled => "none",
    }
}

async fn list_project_my_work(
    State(state): State<Arc<LocalRuntimeState>>,
    Path(project_id): Path<String>,
) -> LocalJsonResult {
    let runs = state
        .session_store
        .list_project_attention_runs(&project_id)
        .map_err(local_store_error)?;
    let mut items = Vec::with_capacity(runs.len());
    for run in runs {
        let Some(group) = my_work_group(run.status) else {
            continue;
        };
        let conversation = state
            .session_store
            .conversation(&run.conversation_id)
            .map_err(local_store_error)?
            .ok_or_else(|| {
                (
                    StatusCode::CONFLICT,
                    Json(json!({ "detail": "run conversation is unavailable" })),
                )
            })?;
        if conversation.project_id != project_id {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": "run conversation project mismatch" })),
            ));
        }
        items.push(json!({
            "id": run.id,
            "run_id": run.id,
            "conversation_id": run.conversation_id,
            "workspace_id": conversation.workspace_id,
            "project_id": run.project_id,
            "title": conversation.title,
            "capability_mode": conversation.capability_mode,
            "group": group,
            "status": run.status,
            "required_action": my_work_required_action(run.status),
            "revision": run.revision,
            "permission_profile": run.permission_profile,
            "environment": run.environment,
            "error": run.error,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "last_heartbeat_at": run.last_heartbeat_at,
        }));
    }

    Ok(Json(json!({
        "project_id": project_id,
        "items": items,
        "total": items.len(),
    })))
}

async fn list_workspaces(
    State(state): State<Arc<LocalRuntimeState>>,
    Path((_tenant_id, project_id)): Path<(String, String)>,
) -> LocalJsonResult {
    let workspaces = state
        .session_store
        .list_workspaces(&project_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({ "items": workspaces })))
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
) -> LocalJsonResult {
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
        .session_store
        .insert_workspace(&workspace)
        .map_err(local_store_error)?;
    Ok(Json(workspace))
}

async fn list_workspace_messages(
    State(state): State<Arc<LocalRuntimeState>>,
    Path((_tenant_id, _project_id, workspace_id)): Path<(String, String, String)>,
) -> LocalJsonResult {
    let messages = state
        .session_store
        .list_workspace_messages(&workspace_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({ "items": messages })))
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

async fn list_tasks(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(workspace_id): Path<String>,
) -> LocalJsonResult {
    ensure_active_workspace(&state, &authenticated, &workspace_id)?;
    let snapshot = state
        .session_store
        .workspace_execution_snapshot(
            &workspace_id,
            &authenticated.workspace.project_id,
            &authenticated.workspace.tenant_id,
        )
        .map_err(local_store_error)?;
    let total = snapshot.tasks.len();
    Ok(Json(json!({
        "workspace_id": snapshot.workspace_id,
        "items": snapshot.tasks,
        "total": total,
    })))
}

async fn plan_snapshot(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(workspace_id): Path<String>,
) -> LocalJsonResult {
    ensure_active_workspace(&state, &authenticated, &workspace_id)?;
    let snapshot = state
        .session_store
        .workspace_execution_snapshot(
            &workspace_id,
            &authenticated.workspace.project_id,
            &authenticated.workspace.tenant_id,
        )
        .map_err(local_store_error)?;
    Ok(Json(json!({
        "workspace_id": snapshot.workspace_id,
        "project_id": snapshot.project_id,
        "plan": Value::Null,
        "conversation_plans": snapshot.conversation_plans,
        "plan_history": snapshot.plan_history,
        "run_health": snapshot.run_health,
        "pending_hitl": snapshot.pending_hitl,
        "delivery": snapshot.delivery,
        "artifact_index": snapshot.artifact_index,
    })))
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
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ListConversationsQuery>,
) -> LocalJsonResult {
    let project_id = query
        .project_id
        .unwrap_or_else(|| authenticated.workspace.project_id.clone());
    ensure_active_project(&authenticated, &project_id)?;
    let workspace_id = query.workspace_id;
    if let Some(workspace_id) = workspace_id.as_deref() {
        ensure_active_workspace(&state, &authenticated, workspace_id)?;
    }
    let offset = query.offset.unwrap_or(0);
    let limit = query.limit.unwrap_or(100);
    let values: Vec<Value> = state
        .session_store
        .list_conversations(&project_id, workspace_id.as_deref())
        .map_err(local_store_error)?
        .iter()
        .map(|conversation| state.conversation_value(conversation))
        .collect();
    let total = values.len();
    let items = values
        .into_iter()
        .skip(offset)
        .take(limit)
        .collect::<Vec<_>>();
    Ok(Json(json!({
        "items": items,
        "total": total,
        "has_more": offset + limit < total,
        "offset": offset,
        "limit": limit,
        "next_offset": if offset + limit < total { Some(offset + limit) } else { None },
    })))
}

#[derive(Deserialize)]
struct CreateConversationBody {
    project_id: String,
    title: Option<String>,
    #[serde(default)]
    agent_config: CreateConversationAgentConfig,
}

#[derive(Default, Deserialize)]
struct CreateConversationAgentConfig {
    #[serde(default)]
    capability_mode: ConversationCapabilityMode,
}

async fn create_conversation(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<CreateConversationBody>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &body.project_id)?;
    let now = now_iso();
    let conversation = LocalConversation {
        id: format!("local-conversation-{}", Uuid::new_v4()),
        project_id: authenticated.workspace.project_id.clone(),
        tenant_id: authenticated.workspace.tenant_id.clone(),
        title: body.title.unwrap_or_else(|| "Local session".to_string()),
        workspace_id: None,
        capability_mode: body.agent_config.capability_mode,
        current_mode: ConversationRunMode::Plan,
        created_at: now.clone(),
        updated_at: now,
    };
    let value = state.conversation_value(&conversation);
    state
        .session_store
        .insert_conversation(&conversation)
        .map_err(local_store_error)?;
    Ok(Json(value))
}

#[derive(Deserialize)]
struct ConversationModeBody {
    workspace_id: Option<String>,
    capability_mode: Option<ConversationCapabilityMode>,
}

async fn update_conversation_mode(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
    Json(body): Json<ConversationModeBody>,
) -> LocalJsonResult {
    let value = {
        let mut conversation = scoped_conversation(&state, &authenticated, &conversation_id)?;
        if let Some(workspace_id) = body.workspace_id.as_deref() {
            ensure_active_workspace(&state, &authenticated, workspace_id)?;
        }
        conversation.workspace_id = body.workspace_id;
        if let Some(capability_mode) = body.capability_mode {
            conversation.capability_mode = capability_mode;
        }
        conversation.updated_at = now_iso();
        state
            .session_store
            .update_conversation(&conversation)
            .map_err(local_store_error)?;
        state.conversation_value(&conversation)
    };
    Ok(Json(value))
}

#[derive(Deserialize)]
struct ConversationMessagesQuery {
    limit: Option<usize>,
}

#[derive(Deserialize)]
struct SwitchPlanModeBody {
    conversation_id: String,
    mode: ConversationRunMode,
}

async fn switch_plan_mode(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<SwitchPlanModeBody>,
) -> LocalJsonResult {
    if body.mode == ConversationRunMode::Build {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "build mode requires atomic plan approval and run authorization"
            })),
        ));
    }
    let mut conversation = scoped_conversation(&state, &authenticated, &body.conversation_id)?;
    conversation.current_mode = body.mode;
    conversation.updated_at = now_iso();
    state
        .session_store
        .update_conversation(&conversation)
        .map_err(local_store_error)?;
    Ok(Json(json!({
        "conversation_id": conversation.id,
        "mode": conversation.current_mode,
        "switched_at": conversation.updated_at,
    })))
}

async fn get_plan_mode(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
) -> LocalJsonResult {
    let conversation = scoped_conversation(&state, &authenticated, &conversation_id)?;
    Ok(Json(json!({
        "conversation_id": conversation.id,
        "mode": conversation.current_mode,
    })))
}

async fn list_agent_plan_tasks(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
) -> LocalJsonResult {
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let tasks = state
        .session_store
        .list_agent_plan_tasks(&conversation_id)
        .map_err(local_store_error)?;
    let plan_version = state
        .session_store
        .latest_draft_plan(&conversation_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({
        "conversation_id": conversation_id,
        "total_count": tasks.len(),
        "tasks": tasks,
        "plan_version": plan_version,
        "approval": {
            "kind": "versioned_atomic",
            "plan_version": plan_version,
        },
    })))
}

async fn conversation_messages(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
    Query(query): Query<ConversationMessagesQuery>,
) -> LocalJsonResult {
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let limit = query.limit.unwrap_or(50);
    let items = state
        .session_store
        .timeline(&conversation_id, limit)
        .map_err(local_store_error)?;
    let total = state
        .session_store
        .timeline_count(&conversation_id)
        .map_err(local_store_error)?;
    let approval_requests = state
        .session_store
        .list_hitl_requests(&conversation_id)
        .map_err(local_store_error)?
        .into_iter()
        .filter(|request| {
            request.decision.is_some()
                && matches!(request.kind, HitlKind::Decision | HitlKind::Permission)
        })
        .map(|request| {
            let run_revision = request
                .run_id
                .as_deref()
                .map(|run_id| state.session_store.run(run_id))
                .transpose()?
                .flatten()
                .map(|run| run.revision);
            let mut value = serde_json::to_value(request).map_err(|error| error.to_string())?;
            value["run_revision"] = json!(run_revision);
            Ok::<Value, String>(value)
        })
        .collect::<Result<Vec<_>, _>>()
        .map_err(local_store_error)?;
    let artifact_versions = state
        .session_store
        .list_artifact_versions(&conversation_id)
        .map_err(local_store_error)?;
    let artifact_deliveries = state
        .session_store
        .list_artifact_deliveries(&conversation_id)
        .map_err(local_store_error)?;
    let tool_invocations = state
        .session_store
        .list_tool_invocations(&conversation_id)
        .map_err(local_store_error)?;
    let first = items.first().cloned();
    let last = items.last().cloned();
    Ok(Json(json!({
        "conversationId": conversation_id,
        "timeline": items,
        "approval_requests": approval_requests,
        "artifact_versions": artifact_versions,
        "artifact_deliveries": artifact_deliveries,
        "tool_invocations": tool_invocations,
        "total": total,
        "has_more": total > items.len(),
        "first_time_us": first.as_ref().and_then(|item| item["eventTimeUs"].as_i64()),
        "first_counter": first.as_ref().and_then(|item| item["eventCounter"].as_u64()),
        "last_time_us": last.as_ref().and_then(|item| item["eventTimeUs"].as_i64()),
        "last_counter": last.as_ref().and_then(|item| item["eventCounter"].as_u64()),
    })))
}

#[derive(Deserialize)]
struct RunConversationBody {
    message: String,
    message_id: Option<String>,
    project_id: Option<String>,
}

async fn run_conversation_message(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
    Json(body): Json<RunConversationBody>,
) -> LocalJsonResult {
    let message_id = body
        .message_id
        .unwrap_or_else(|| format!("local-message-{}", Uuid::new_v4()));
    let conversation = scoped_conversation(&state, &authenticated, &conversation_id)?;
    if let Some(project_id) = body.project_id.as_deref() {
        ensure_active_project(&authenticated, project_id)?;
    }
    let project_id = conversation.project_id.clone();
    if conversation.current_mode == ConversationRunMode::Build {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "build messages require /api/v1/agent/plans/approve-and-start"
            })),
        ));
    }
    let run_state = Arc::clone(&state);
    tokio::spawn(async move {
        run_state
            .run_agent_message(
                conversation_id,
                project_id,
                body.message,
                message_id,
                None,
                None,
            )
            .await;
    });
    Ok(Json(json!({ "queued": true })))
}

#[derive(Deserialize)]
struct ApprovePlanAndStartBody {
    conversation_id: String,
    project_id: String,
    plan_version_id: String,
    expected_plan_version: i64,
    permission_profile: DesktopPermissionProfile,
    message: String,
    message_id: String,
    idempotency_key: String,
    #[serde(default)]
    environment: Option<ExecutionEnvironmentBody>,
}

#[derive(Deserialize)]
struct ExecutionEnvironmentBody {
    kind: DesktopExecutionEnvironmentKind,
}

async fn approve_plan_and_start(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<ApprovePlanAndStartBody>,
) -> LocalJsonResult {
    if body.message.trim().is_empty()
        || body.message_id.trim().is_empty()
        || body.idempotency_key.trim().is_empty()
        || body.plan_version_id.trim().is_empty()
        || body.expected_plan_version < 1
    {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "detail": "plan_version_id, expected_plan_version, message, message_id, and idempotency_key are required"
            })),
        ));
    }
    ensure_active_project(&authenticated, &body.project_id)?;
    let conversation = scoped_conversation(&state, &authenticated, &body.conversation_id)?;
    let existing_run = state
        .session_store
        .run_by_idempotency_key(&body.idempotency_key)
        .map_err(local_store_error)?;
    if let Some(existing_run) = existing_run.as_ref() {
        ensure_active_project(&authenticated, &existing_run.project_id)?;
    }
    let prepared = if existing_run.is_some() {
        None
    } else {
        let kind = body
            .environment
            .as_ref()
            .map(|environment| environment.kind)
            .unwrap_or(DesktopExecutionEnvironmentKind::Local);
        if kind == DesktopExecutionEnvironmentKind::Worktree
            && conversation.capability_mode != ConversationCapabilityMode::Code
        {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": "worktree execution requires a Code conversation" })),
            ));
        }
        let environment_id = format!("local-environment-{}", Uuid::new_v4());
        Some(
            state
                .worktree_manager()
                .prepare(kind, &environment_id, &now_iso())
                .map_err(execution_environment_error)?,
        )
    };
    let approved_at = now_iso();
    let outcome = match state.session_store.approve_plan_and_start_in_environment(
        session_store::ApprovePlanStartInput {
            conversation_id: &body.conversation_id,
            project_id: &authenticated.workspace.project_id,
            plan_version_id: &body.plan_version_id,
            expected_plan_version: body.expected_plan_version,
            idempotency_key: &body.idempotency_key,
            message_id: &body.message_id,
            request_message: &body.message,
            environment: prepared
                .as_ref()
                .map(|prepared| prepared.environment.clone()),
            requested_environment_kind: body
                .environment
                .as_ref()
                .map(|environment| environment.kind)
                .unwrap_or(DesktopExecutionEnvironmentKind::Local),
            permission_profile: body.permission_profile,
            now: &approved_at,
        },
    ) {
        Ok(outcome) => outcome,
        Err(error) => {
            if let Some(prepared) = prepared.as_ref() {
                state.worktree_manager().cleanup(&prepared.environment);
            }
            return Err(authority_error(error));
        }
    };
    if !outcome.created {
        if let Some(prepared) = prepared.as_ref() {
            state.worktree_manager().cleanup(&prepared.environment);
        }
    } else if let Some(prepared) = prepared.as_ref() {
        let event_type = if prepared.created_worktree {
            "worktree_created"
        } else {
            "environment_selected"
        };
        let item = state.timeline_item(
            event_type,
            outcome.conversation.id.clone(),
            Some(outcome.run.message_id.clone()),
            None,
            None,
            json!({
                "run_id": outcome.run.id,
                "environment": prepared.environment,
            }),
        );
        state.append_timeline(&outcome.conversation.id, item);
    }
    let should_queue = matches!(
        outcome.run.status,
        DesktopRunStatus::Queued | DesktopRunStatus::Interrupted
    );
    if should_queue {
        let run_state = Arc::clone(&state);
        let conversation_id = outcome.conversation.id.clone();
        let project_id = outcome.conversation.project_id.clone();
        let message = outcome.run.request_message.clone();
        let message_id = outcome.run.message_id.clone();
        let run_id = outcome.run.id.clone();
        tokio::spawn(async move {
            run_state
                .run_agent_message(
                    conversation_id,
                    project_id,
                    message,
                    message_id,
                    Some(run_id),
                    None,
                )
                .await;
        });
    }
    Ok(Json(json!({
        "queued": should_queue,
        "created": outcome.created,
        "conversation": state.conversation_value(&outcome.conversation),
        "plan_version": outcome.plan_version,
        "run": outcome.run,
    })))
}

async fn get_run(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    let events = state
        .session_store
        .run_events(&run_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({ "run": run, "events": events })))
}

#[derive(Deserialize)]
struct RunChangesQuery {
    expected_revision: u64,
}

async fn get_run_changes(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
    Query(query): Query<RunChangesQuery>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    if run.revision != query.expected_revision {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "run revision conflict",
                "expected_revision": query.expected_revision,
                "actual_revision": run.revision,
            })),
        ));
    }
    Ok(Json(
        serde_json::to_value(GitChangesInspector::inspect(&run, &now_iso()))
            .map_err(|error| local_store_error(error.to_string()))?,
    ))
}

#[derive(Deserialize)]
struct CreateRunInputBody {
    expected_run_revision: u64,
    message: String,
    message_id: String,
    idempotency_key: String,
    delivery: RunInputDelivery,
    #[serde(default)]
    references: Vec<RunInputReference>,
}

async fn list_run_inputs(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    let inputs = state
        .session_store
        .list_run_inputs(&run_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({
        "run_id": run.id,
        "run_revision": run.revision,
        "inputs": inputs,
        "total_count": inputs.len(),
    })))
}

async fn create_run_input(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
    Json(body): Json<CreateRunInputBody>,
) -> LocalJsonResult {
    if body.message.trim().is_empty()
        || body.message_id.trim().is_empty()
        || body.idempotency_key.trim().is_empty()
    {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "detail": "message, message_id, and idempotency_key are required"
            })),
        ));
    }
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    if run.revision != body.expected_run_revision {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "run revision conflict",
                "expected_revision": body.expected_run_revision,
                "actual_revision": run.revision,
            })),
        ));
    }
    if run.status != DesktopRunStatus::Running {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run is not accepting steering or queued input" })),
        ));
    }
    if body.delivery == RunInputDelivery::SteerNow && state.control_for_run(&run).is_none() {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run is not attached for steering" })),
        ));
    }
    if !body.references.is_empty() {
        let snapshot = GitChangesInspector::inspect(&run, &now_iso());
        validate_run_input_references(&snapshot, &body.references).map_err(|detail| {
            (
                StatusCode::CONFLICT,
                Json(json!({
                    "detail": detail,
                    "snapshot_id": snapshot.id,
                    "run_revision": run.revision,
                })),
            )
        })?;
    }
    let created_at = now_iso();
    let outcome = state
        .session_store
        .create_run_input(session_store::CreateRunInput {
            run_id: &run.id,
            expected_run_revision: body.expected_run_revision,
            message_id: &body.message_id,
            idempotency_key: &body.idempotency_key,
            delivery: body.delivery,
            content: &body.message,
            references: body.references,
            now: &created_at,
        });
    let (input, created) = match outcome {
        Ok(value) => value,
        Err(error) if error.contains("conflict") || error.contains("not accepting") => {
            return Err((StatusCode::CONFLICT, Json(json!({ "detail": error }))))
        }
        Err(error) => return Err(local_store_error(error)),
    };
    if created {
        let event_type = match input.delivery {
            RunInputDelivery::SteerNow => "user_message",
            RunInputDelivery::QueueNext => "run_input_queued",
        };
        let item = state.timeline_item(
            event_type,
            run.conversation_id.clone(),
            Some(input.message_id.clone()),
            (input.delivery == RunInputDelivery::SteerNow).then_some("user"),
            Some(input.content.clone()),
            json!({
                "run_id": run.id,
                "run_revision": run.revision,
                "run_input_id": input.id,
                "delivery_mode": input.delivery,
                "input_status": input.status,
                "references": input.references,
            }),
        );
        state.append_timeline(&run.conversation_id, item);
    }
    Ok(Json(json!({
        "accepted": true,
        "created": created,
        "action": "send_message",
        "conversation_id": run.conversation_id,
        "message_id": input.message_id,
        "delivery_mode": input.delivery,
        "run_id": run.id,
        "run_revision": run.revision,
        "queue_position": input.queue_position,
        "input": input,
    })))
}

#[derive(Deserialize)]
struct PromoteRunInputBody {
    expected_source_run_revision: u64,
    idempotency_key: String,
}

async fn promote_run_input_to_plan(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(input_id): Path<String>,
    Json(body): Json<PromoteRunInputBody>,
) -> LocalJsonResult {
    if body.idempotency_key.trim().is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "detail": "idempotency_key is required" })),
        ));
    }
    let existing = state
        .session_store
        .run_input(&input_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run input not found" })),
            )
        })?;
    let source_run = state
        .session_store
        .run(&existing.run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "source run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &source_run.project_id)?;

    let claimed_control = if existing.status == RunInputStatus::PromotedToPlan {
        None
    } else {
        Some(
            state
                .claim_agent_run(&existing.conversation_id, None)
                .ok_or_else(|| {
                    (
                        StatusCode::CONFLICT,
                        Json(json!({ "detail": "conversation already running" })),
                    )
                })?,
        )
    };
    let promoted_at = now_iso();
    let outcome = state.session_store.promote_queued_run_input(
        &input_id,
        body.expected_source_run_revision,
        body.idempotency_key.trim(),
        &promoted_at,
    );
    let (input, conversation, created) = match outcome {
        Ok(value) => value,
        Err(error) => {
            if claimed_control.is_some() {
                state.release_agent_run(&existing.conversation_id);
            }
            if error.contains("conflict")
                || error.contains("not ready")
                || error.contains("not completed")
            {
                return Err((StatusCode::CONFLICT, Json(json!({ "detail": error }))));
            }
            return Err(local_store_error(error));
        }
    };
    if created {
        let item = state.timeline_item(
            "run_input_promoted",
            conversation.id.clone(),
            Some(format!("promoted-{}", input.id)),
            None,
            Some(input.content.clone()),
            json!({
                "run_input_id": input.id,
                "source_run_id": source_run.id,
                "source_run_revision": source_run.revision,
                "delivery_mode": input.delivery,
                "input_status": input.status,
                "references": input.references,
            }),
        );
        state.append_timeline(&conversation.id, item);
        let run_state = Arc::clone(&state);
        let conversation_id = conversation.id.clone();
        let project_id = conversation.project_id.clone();
        let message = input.steering_content();
        let message_id = format!("promoted-{}", input.id);
        let control = claimed_control.expect("new promotion reserves the conversation");
        tokio::spawn(async move {
            run_state
                .run_agent_message(
                    conversation_id,
                    project_id,
                    message,
                    message_id,
                    None,
                    Some(control),
                )
                .await;
        });
    }
    Ok(Json(json!({
        "accepted": true,
        "created": created,
        "action": "start_plan_turn",
        "input": input,
        "conversation": state.conversation_value(&conversation),
        "source_run": source_run,
    })))
}

fn validate_run_input_references(
    snapshot: &ChangeSnapshot,
    references: &[RunInputReference],
) -> Result<(), &'static str> {
    if snapshot.status != ChangeSnapshotStatus::Ready {
        return Err("authoritative change snapshot is unavailable");
    }
    let Some(environment_id) = snapshot.environment_id.as_deref() else {
        return Err("change snapshot is not bound to an environment");
    };
    for reference in references {
        match reference {
            RunInputReference::CodeRange {
                snapshot_id,
                environment_id: reference_environment_id,
                path,
                start_line,
                end_line,
                side,
                patch_digest,
            } => {
                if snapshot_id != &snapshot.id {
                    return Err("change snapshot is stale");
                }
                if reference_environment_id != environment_id {
                    return Err("change reference environment mismatch");
                }
                if *start_line == 0 || end_line < start_line {
                    return Err("change reference line range is invalid");
                }
                let Some(file) = snapshot
                    .files
                    .iter()
                    .find(|file| file.path == *path && file.patch_digest == *patch_digest)
                else {
                    return Err("change reference file is stale");
                };
                let line_exists = file.hunks.iter().flat_map(|hunk| &hunk.lines).any(|line| {
                    let line_number = match side {
                        ChangeReferenceSide::Old => line.old_line,
                        ChangeReferenceSide::New => line.new_line,
                    };
                    line_number.is_some_and(|line| line >= *start_line && line <= *end_line)
                        && match side {
                            ChangeReferenceSide::Old => line.kind != ChangeLineKind::Addition,
                            ChangeReferenceSide::New => line.kind != ChangeLineKind::Deletion,
                        }
                });
                if !line_exists {
                    return Err("change reference line is stale");
                }
            }
        }
    }
    Ok(())
}

#[derive(Deserialize)]
struct ReviewArtifactVersionBody {
    action: String,
    expected_revision: u64,
    #[serde(default)]
    run_expected_revision: Option<u64>,
    #[serde(default)]
    feedback: Option<String>,
}

async fn review_artifact_version(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(artifact_version_id): Path<String>,
    Json(body): Json<ReviewArtifactVersionBody>,
) -> LocalJsonResult {
    let version = state
        .session_store
        .artifact_version(&artifact_version_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "artifact version not found" })),
            )
        })?;
    scoped_conversation(&state, &authenticated, &version.conversation_id)?;
    ensure_artifact_revision(&version, body.expected_revision)?;
    match body.action.as_str() {
        "approve" => {
            if !matches!(
                version.status,
                DesktopArtifactStatus::Draft
                    | DesktopArtifactStatus::Ready
                    | DesktopArtifactStatus::Approved
            ) {
                return Err((
                    StatusCode::CONFLICT,
                    Json(json!({ "detail": "artifact version is not ready for approval" })),
                ));
            }
            let reviewed = state
                .session_store
                .review_artifact_version(&version.id, version.revision, "approve", None, &now_iso())
                .map_err(local_store_error)?;
            append_artifact_event(&state, &reviewed, "artifact_approved", None, None);
            Ok(Json(json!({
                "accepted": true,
                "status": "approved",
                "artifact_version": reviewed,
                "run": null,
            })))
        }
        "request_changes" => {
            let feedback = body
                .feedback
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .ok_or_else(|| {
                    (
                        StatusCode::BAD_REQUEST,
                        Json(json!({ "detail": "artifact review feedback is required" })),
                    )
                })?
                .to_string();
            let run_id = version.run_id.as_deref().ok_or_else(|| {
                (
                    StatusCode::CONFLICT,
                    Json(json!({ "detail": "artifact version is not bound to a run" })),
                )
            })?;
            let run = state
                .session_store
                .run(run_id)
                .map_err(local_store_error)?
                .ok_or_else(|| {
                    (
                        StatusCode::NOT_FOUND,
                        Json(json!({ "detail": "artifact run not found" })),
                    )
                })?;
            let run_expected_revision = body.run_expected_revision.ok_or_else(|| {
                (
                    StatusCode::BAD_REQUEST,
                    Json(json!({ "detail": "run_expected_revision is required" })),
                )
            })?;
            ensure_run_revision(&run, run_expected_revision)?;
            if run.status != DesktopRunStatus::ReadyReview {
                return Err((
                    StatusCode::CONFLICT,
                    Json(json!({ "detail": "artifact run is not ready for review" })),
                ));
            }
            let conversation = state
                .session_store
                .conversation(&version.conversation_id)
                .map_err(local_store_error)?
                .ok_or_else(|| {
                    (
                        StatusCode::NOT_FOUND,
                        Json(json!({ "detail": "conversation not found" })),
                    )
                })?;
            let engine = state
                .agent_engine(&conversation, Some(&run))
                .map_err(execution_environment_error)?;
            let Some(control) = state.claim_agent_run(&conversation.id, Some(&run.id)) else {
                return Err((
                    StatusCode::CONFLICT,
                    Json(json!({ "detail": "conversation already running" })),
                ));
            };
            let accepted = match engine
                .accept_review_changes(&conversation.id, &feedback)
                .await
            {
                Ok(accepted) => accepted,
                Err(error) => {
                    state.release_agent_run(&conversation.id);
                    return Err((
                        StatusCode::CONFLICT,
                        Json(json!({ "detail": error.to_string() })),
                    ));
                }
            };
            let (reviewed, running, decision) =
                match state.session_store.request_artifact_changes_and_resume_run(
                    &version.id,
                    version.revision,
                    &run.id,
                    run.revision,
                    &feedback,
                    &now_iso(),
                ) {
                    Ok(outcome) => outcome,
                    Err(error) => {
                        state.release_agent_run(&conversation.id);
                        return Err(local_store_error(error));
                    }
                };
            state.publish_run_status(&running);
            append_review_decision(
                &state,
                &running,
                &decision,
                "request_changes",
                Some(&feedback),
            );
            append_artifact_event(
                &state,
                &reviewed,
                "artifact_changes_requested",
                Some(&feedback),
                None,
            );
            let goal = accepted.goal;
            let runtime = Arc::clone(&state);
            let running_for_task = running.clone();
            tokio::spawn(async move {
                runtime
                    .continue_after_hitl(conversation, goal, Some(running_for_task), control)
                    .await;
            });
            Ok(Json(json!({
                "accepted": true,
                "status": "changes_requested",
                "artifact_version": reviewed,
                "run": running,
            })))
        }
        _ => Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "detail": "artifact review action must be approve or request_changes" })),
        )),
    }
}

#[derive(Deserialize)]
struct DeliverArtifactVersionBody {
    expected_revision: u64,
    idempotency_key: String,
    #[serde(default = "default_local_artifact_destination")]
    destination: String,
}

fn default_local_artifact_destination() -> String {
    "local_workspace".to_string()
}

async fn deliver_artifact_version(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(artifact_version_id): Path<String>,
    Json(body): Json<DeliverArtifactVersionBody>,
) -> LocalJsonResult {
    let version = state
        .session_store
        .artifact_version(&artifact_version_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "artifact version not found" })),
            )
        })?;
    scoped_conversation(&state, &authenticated, &version.conversation_id)?;
    if version.status == DesktopArtifactStatus::Delivered {
        let deliveries = state
            .session_store
            .list_artifact_deliveries(&version.conversation_id)
            .map_err(local_store_error)?;
        if let Some(delivery) = deliveries.into_iter().find(|delivery| {
            delivery.artifact_version_id == version.id
                && delivery.idempotency_key == body.idempotency_key
        }) {
            return Ok(Json(json!({
                "accepted": true,
                "status": "delivered",
                "artifact_version": version,
                "delivery": delivery,
            })));
        }
    }
    ensure_artifact_revision(&version, body.expected_revision)?;
    if version.status != DesktopArtifactStatus::Approved {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "only an approved artifact version can be delivered" })),
        ));
    }
    if body.idempotency_key.trim().is_empty() || body.destination.trim().is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "detail": "idempotency_key and destination are required" })),
        ));
    }
    let metadata = tokio::fs::metadata(&version.path).await.map_err(|_| {
        (
            StatusCode::CONFLICT,
            Json(json!({ "detail": "artifact file is unavailable; delivery was not recorded" })),
        )
    })?;
    if !metadata.is_file() {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "artifact path is not a file; delivery was not recorded" })),
        ));
    }
    let delivered_at = now_iso();
    let receipt = json!({
        "artifact_version_id": version.id,
        "artifact_id": version.artifact_id,
        "destination": body.destination,
        "path": version.path,
        "relative_path": version.relative_path,
        "bytes": metadata.len(),
        "actor": "local_user",
        "delivered_at": delivered_at,
    });
    let (delivered, delivery) = state
        .session_store
        .deliver_artifact_version(
            &version.id,
            version.revision,
            &body.idempotency_key,
            &body.destination,
            receipt,
            &delivered_at,
        )
        .map_err(local_store_error)?;
    append_artifact_event(
        &state,
        &delivered,
        "artifact_delivered",
        None,
        Some(&delivery.receipt),
    );
    Ok(Json(json!({
        "accepted": true,
        "status": "delivered",
        "artifact_version": delivered,
        "delivery": delivery,
    })))
}

fn ensure_artifact_revision(
    version: &DesktopArtifactVersion,
    expected_revision: u64,
) -> Result<(), (StatusCode, Json<Value>)> {
    if version.revision == expected_revision {
        return Ok(());
    }
    Err((
        StatusCode::CONFLICT,
        Json(json!({
            "detail": format!(
                "artifact revision conflict: expected {expected_revision}, found {}",
                version.revision
            )
        })),
    ))
}

fn append_artifact_event(
    state: &LocalRuntimeState,
    version: &DesktopArtifactVersion,
    event_type: &str,
    feedback: Option<&str>,
    receipt: Option<&Value>,
) {
    let item = state.timeline_item(
        event_type,
        version.conversation_id.clone(),
        None,
        Some("user"),
        feedback.map(ToString::to_string),
        json!({
            "artifact_id": version.artifact_id,
            "artifact_version_id": version.id,
            "version": version.version,
            "revision": version.revision,
            "status": version.status,
            "filename": version.filename,
            "feedback": feedback,
            "receipt": receipt,
            "source": "local_user",
        }),
    );
    state.append_timeline(&version.conversation_id, item);
}

fn ensure_run_revision(
    run: &DesktopRun,
    expected_revision: u64,
) -> Result<(), (StatusCode, Json<Value>)> {
    if run.revision == expected_revision {
        return Ok(());
    }
    Err((
        StatusCode::CONFLICT,
        Json(json!({
            "detail": format!(
                "run revision conflict: expected {expected_revision}, found {}",
                run.revision
            )
        })),
    ))
}

fn append_review_decision(
    state: &LocalRuntimeState,
    run: &DesktopRun,
    decision: &Value,
    action: &str,
    feedback: Option<&str>,
) {
    let item = state.timeline_item(
        "review_decision",
        run.conversation_id.clone(),
        Some(run.message_id.clone()),
        Some("user"),
        feedback.map(ToString::to_string),
        json!({
            "run_id": run.id,
            "revision": run.revision,
            "decision_id": decision.get("id"),
            "action": action,
            "feedback": feedback,
            "source": "local_user",
        }),
    );
    state.append_timeline(&run.conversation_id, item);
}

#[derive(Deserialize)]
struct HitlResponseBody {
    request_id: String,
    hitl_type: String,
    #[serde(default)]
    response_data: Value,
    expected_revision: Option<u64>,
    idempotency_key: Option<String>,
}

async fn respond_to_hitl(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<HitlResponseBody>,
) -> LocalJsonResult {
    let request = state
        .session_store
        .hitl_request(&body.request_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "HITL request not found" })),
            )
        })?;
    scoped_conversation(&state, &authenticated, &request.conversation_id)?;
    if body.hitl_type != hitl_kind_name(request.kind) {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "HITL request type mismatch" })),
        ));
    }
    if request.kind == HitlKind::EnvVar {
        return Err((
            StatusCode::NOT_IMPLEMENTED,
            Json(json!({
                "detail": "Secure environment-variable responses are not available in the local runtime"
            })),
        ));
    }
    if request.status == DesktopHitlStatus::Responded {
        let same_payload = request.response_data.as_ref() == Some(&body.response_data);
        let same_key = body.idempotency_key.as_deref().is_none()
            || request.idempotency_key.as_deref() == body.idempotency_key.as_deref();
        if same_payload && same_key {
            return Ok(Json(json!({
                "success": true,
                "status": "responded",
                "request_id": request.id,
                "conversation_id": request.conversation_id,
                "run_id": request.run_id,
                "revision": request.response_revision,
            })));
        }
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "HITL request was already answered with a different payload" })),
        ));
    }
    let answer = hitl_response_answer(request.kind, &body.response_data).ok_or_else(|| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({ "detail": "A valid HITL response is required" })),
        )
    })?;
    if hitl_response_approves(request.kind, &body.response_data)
        && !request
            .decision
            .as_ref()
            .is_some_and(agistack_core::agent::types::DecisionContext::is_complete)
    {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({
                "detail": "Approval requires complete action, target, data, reason, risk, reversibility, scope, and evidence"
            })),
        ));
    }
    if let (Some(run_id), Some(expected_revision)) =
        (request.run_id.as_deref(), body.expected_revision)
    {
        let run = state
            .session_store
            .run(run_id)
            .map_err(local_store_error)?
            .ok_or_else(|| {
                (
                    StatusCode::NOT_FOUND,
                    Json(json!({ "detail": "run not found" })),
                )
            })?;
        if run.revision != expected_revision {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({
                    "detail": "run revision conflict",
                    "expected_revision": expected_revision,
                    "actual_revision": run.revision,
                })),
            ));
        }
    }
    let conversation = state
        .session_store
        .conversation(&request.conversation_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "conversation not found" })),
            )
        })?;
    let engine_run = if let Some(run_id) = request.run_id.as_deref() {
        Some(
            state
                .session_store
                .run(run_id)
                .map_err(local_store_error)?
                .ok_or_else(|| {
                    (
                        StatusCode::NOT_FOUND,
                        Json(json!({ "detail": "run not found" })),
                    )
                })?,
        )
    } else {
        None
    };
    let engine = state
        .agent_engine(&conversation, engine_run.as_ref())
        .map_err(execution_environment_error)?;

    let Some(control) = state.claim_agent_run(&conversation.id, request.run_id.as_deref()) else {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "conversation already running" })),
        ));
    };

    let accepted = match engine
        .accept_human_response(&conversation.id, &request.id, &answer)
        .await
    {
        Ok(accepted) => accepted,
        Err(error) => {
            state.release_agent_run(&conversation.id);
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": error.to_string() })),
            ));
        }
    };
    let authoritative_run = if let Some(run_id) = request.run_id.as_deref() {
        let run = match state.session_store.run(run_id) {
            Ok(Some(run)) => run,
            Ok(None) => {
                state.release_agent_run(&conversation.id);
                return Err((
                    StatusCode::NOT_FOUND,
                    Json(json!({ "detail": "run not found" })),
                ));
            }
            Err(error) => {
                state.release_agent_run(&conversation.id);
                return Err(local_store_error(error));
            }
        };
        let run = if matches!(
            run.status,
            DesktopRunStatus::NeedsInput | DesktopRunStatus::NeedsApproval
        ) {
            match state.session_store.transition_run(
                &run.id,
                run.revision,
                DesktopRunStatus::Running,
                None,
                &now_iso(),
            ) {
                Ok(run) => run,
                Err(error) => {
                    state.release_agent_run(&conversation.id);
                    return Err(local_store_error(error));
                }
            }
        } else if run.status == DesktopRunStatus::Running {
            run
        } else {
            state.release_agent_run(&conversation.id);
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": "run is not awaiting human input" })),
            ));
        };
        state.publish_run_status(&run);
        Some(run)
    } else {
        None
    };

    if let Err(error) = state.session_store.mark_hitl_responded(
        &request.id,
        &body.response_data,
        "local_user",
        authoritative_run.as_ref().map(|run| run.revision),
        body.idempotency_key.as_deref(),
        &now_iso(),
    ) {
        state.release_agent_run(&conversation.id);
        return Err(local_store_error(error));
    }
    let mut item = state.timeline_item(
        "hitl_responded",
        conversation.id.clone(),
        None,
        Some("user"),
        None,
        json!({
            "request_id": request.id,
            "requestId": request.id,
            "hitl_type": hitl_kind_name(request.kind),
            "answered": true,
            "run_id": request.run_id,
            "decision": request.decision,
            "response_actor": "local_user",
            "response_revision": authoritative_run.as_ref().map(|run| run.revision),
        }),
    );
    item["requestId"] = json!(request.id);
    item["answered"] = json!(true);
    state.append_timeline(&conversation.id, item);

    let response = json!({
        "success": true,
        "status": "running",
        "request_id": request.id,
        "conversation_id": conversation.id,
        "run_id": authoritative_run.as_ref().map(|run| run.id.clone()),
        "revision": authoritative_run.as_ref().map(|run| run.revision),
    });
    let goal = accepted.goal;
    let run_state = Arc::clone(&state);
    tokio::spawn(async move {
        run_state
            .continue_after_hitl(conversation, goal, authoritative_run, control)
            .await;
    });
    Ok(Json(response))
}

fn hitl_response_answer(kind: HitlKind, response_data: &Value) -> Option<String> {
    match kind {
        HitlKind::Clarification => response_data
            .get("answer")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|answer| !answer.is_empty())
            .map(ToString::to_string),
        HitlKind::Decision => response_data
            .get("decision")
            .or_else(|| response_data.get("answer"))
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|answer| !answer.is_empty())
            .map(ToString::to_string),
        HitlKind::Permission => response_data
            .get("granted")
            .and_then(Value::as_bool)
            .map(|granted| if granted { "approved" } else { "denied" }.to_string()),
        HitlKind::EnvVar => None,
    }
}

fn hitl_response_approves(kind: HitlKind, response_data: &Value) -> bool {
    match kind {
        HitlKind::Permission => response_data.get("granted").and_then(Value::as_bool) == Some(true),
        HitlKind::Decision => {
            response_data.get("decision").and_then(Value::as_str) == Some("approved")
        }
        HitlKind::Clarification | HitlKind::EnvVar => false,
    }
}

async fn list_conversation_runs(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
) -> LocalJsonResult {
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let runs = state
        .session_store
        .list_runs(&conversation_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({
        "conversation_id": conversation_id,
        "total_count": runs.len(),
        "runs": runs,
    })))
}

async fn agent_ws(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    ws.protocols(["memstack.auth"])
        .on_upgrade(move |socket| agent_socket_loop(socket, state, authenticated))
}

async fn agent_socket_loop(
    socket: WebSocket,
    state: Arc<LocalRuntimeState>,
    authenticated: AuthenticatedContext,
) {
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
                if !state
                    .session_store
                    .session_context_is_current(&authenticated, Utc::now().timestamp_millis())
                    .unwrap_or(false)
                {
                    let error = json!({
                        "type": "error",
                        "code": "stale_workspace_context",
                        "message": "desktop session or workspace context is no longer active",
                    });
                    let _ = sender.send(Message::Text(error.to_string())).await;
                    break;
                }
                let kind = value["type"].as_str().unwrap_or_default();
                if kind == "send_message" {
                    let conversation_id = value["conversation_id"].as_str().unwrap_or_default().to_string();
                    let message = value["message"].as_str().unwrap_or_default().to_string();
                    if conversation_id.is_empty() || message.is_empty() {
                        let error = json!({ "type": "error", "message": "conversation_id and message are required" });
                        if sender.send(Message::Text(error.to_string())).await.is_err() {
                            break;
                        }
                        continue;
                    }
                    let conversation = state
                        .session_store
                        .conversation(&conversation_id)
                        .ok()
                        .flatten();
                    let Some(conversation) = conversation.filter(|conversation| {
                        conversation.project_id == authenticated.workspace.project_id
                            && conversation.tenant_id == authenticated.workspace.tenant_id
                    }) else {
                        let error = json!({
                            "type": "error",
                            "code": "resource_outside_active_context",
                            "message": "conversation is outside the active workspace context",
                            "conversation_id": conversation_id,
                        });
                        if sender.send(Message::Text(error.to_string())).await.is_err() {
                            break;
                        }
                        continue;
                    };
                    if value["project_id"]
                        .as_str()
                        .is_some_and(|project_id| project_id != conversation.project_id)
                    {
                        let error = json!({
                            "type": "error",
                            "code": "project_context_mismatch",
                            "message": "client project does not match the authoritative conversation",
                            "conversation_id": conversation_id,
                        });
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
                    let project_id = conversation.project_id;
                    tokio::spawn(async move {
                        run_state
                            .run_agent_message(
                                conversation_id,
                                project_id,
                                message,
                                message_id,
                                None,
                                None,
                            )
                            .await;
                    });
                } else if kind == "subscribe" {
                    let Some(conversation_id) = value["conversation_id"].as_str() else {
                        continue;
                    };
                    if conversation_id.is_empty() {
                        continue;
                    }
                    let scoped = state
                        .session_store
                        .conversation(conversation_id)
                        .ok()
                        .flatten()
                        .is_some_and(|conversation| {
                            conversation.project_id == authenticated.workspace.project_id
                                && conversation.tenant_id == authenticated.workspace.tenant_id
                        });
                    if !scoped {
                        let error = json!({
                            "type": "error",
                            "code": "resource_outside_active_context",
                            "message": "conversation is outside the active workspace context",
                            "conversation_id": conversation_id,
                        });
                        if sender.send(Message::Text(error.to_string())).await.is_err() {
                            break;
                        }
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
                if !state
                    .session_store
                    .session_context_is_current(&authenticated, Utc::now().timestamp_millis())
                    .unwrap_or(false)
                {
                    let error = json!({
                        "type": "error",
                        "code": "stale_workspace_context",
                        "message": "desktop session or workspace context is no longer active",
                    });
                    let _ = sender.send(Message::Text(error.to_string())).await;
                    break;
                }
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

async fn ensure_sandbox(Path(project_id): Path<String>) -> LocalJsonResult {
    Err((
        StatusCode::NOT_IMPLEMENTED,
        Json(json!({
            "detail": "isolated local sandbox is not configured",
            "sandbox": sandbox_value(project_id),
        })),
    ))
}

async fn proxy_auth_cookie() -> Json<Value> {
    Json(json!({ "ok": true }))
}

async fn start_desktop(Path(project_id): Path<String>) -> LocalJsonResult {
    Err((
        StatusCode::NOT_IMPLEMENTED,
        Json(json!({
            "detail": "isolated local desktop is not configured",
            "sandbox": sandbox_value(project_id),
        })),
    ))
}

async fn desktop_proxy() -> Html<&'static str> {
    Html(
        r#"<!doctype html><html><body style="margin:0;background:#111;color:#ddd;font:14px system-ui;display:grid;place-items:center;height:100vh"><div>Local desktop mode uses the native Tauri window.</div></body></html>"#,
    )
}

#[derive(Deserialize)]
struct StartTerminalBody {
    run_id: String,
    expected_run_revision: u64,
}

async fn start_terminal(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    Json(body): Json<StartTerminalBody>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    let run = state
        .session_store
        .run(&body.run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    if run.project_id != project_id {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "terminal run project mismatch" })),
        ));
    }
    if run.revision != body.expected_run_revision
        || run.status != DesktopRunStatus::Running
        || run.permission_profile != DesktopPermissionProfile::FullAccess
    {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "terminal requires the exact active run revision with full_access permission",
                "actual_revision": run.revision,
                "status": run.status,
                "permission_profile": run.permission_profile,
            })),
        ));
    }
    let environment = run.environment.as_ref().ok_or_else(|| {
        (
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run has no authoritative execution environment" })),
        )
    })?;
    state
        .worktree_manager()
        .validate(environment)
        .map_err(execution_environment_error)?;
    let cwd = PathBuf::from(&environment.workspace_path);
    let created_at = now_iso();
    let expires_at = (Utc::now() + ChronoDuration::seconds(30)).to_rfc3339();
    let lease = state.create_terminal_session(
        &run,
        environment,
        &authenticated,
        cwd.clone(),
        created_at,
        expires_at,
    );
    Ok(Json(json!({
        "success": true,
        "url": null,
        "port": null,
        "session_id": lease.session_id,
        "run_id": run.id,
        "run_revision": run.revision,
        "conversation_id": run.conversation_id,
        "project_id": run.project_id,
        "environment_id": environment.id,
        "created_at": lease.created_at,
        "expires_at": lease.expires_at,
        "resumable": false,
        "cwd": cwd,
        "environment": run.environment,
    })))
}

#[derive(Deserialize)]
struct TerminalSocketQuery {
    session_id: String,
}

async fn terminal_ws(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    Query(query): Query<TerminalSocketQuery>,
    ws: WebSocketUpgrade,
) -> Response {
    if let Err(error) = ensure_active_project(&authenticated, &project_id) {
        return error.into_response();
    }
    let Some(lease) = state.take_terminal_session(&query.session_id) else {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({ "detail": "unknown or consumed terminal session" })),
        )
            .into_response();
    };
    let cwd = match validate_terminal_session_lease(&state, &authenticated, &project_id, &lease) {
        Ok(cwd) => cwd,
        Err(error) => return error.into_response(),
    };
    let state_for_socket = Arc::clone(&state);
    let authenticated_for_socket = authenticated.clone();
    let project_for_socket = project_id.clone();
    let lease_for_socket = lease.clone();
    ws.protocols(["memstack.auth"])
        .on_upgrade(move |socket| {
            terminal_socket_loop(
                socket,
                cwd,
                query.session_id,
                state_for_socket,
                authenticated_for_socket,
                project_for_socket,
                lease_for_socket,
            )
        })
        .into_response()
}

fn validate_terminal_session_lease(
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    project_id: &str,
    lease: &TerminalSessionLease,
) -> Result<PathBuf, (StatusCode, Json<Value>)> {
    let expires_at = chrono::DateTime::parse_from_rfc3339(&lease.expires_at).map_err(|_| {
        (
            StatusCode::CONFLICT,
            Json(json!({ "detail": "terminal session expiry is invalid" })),
        )
    })?;
    if expires_at <= Utc::now() {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "terminal session attach window expired" })),
        ));
    }
    validate_terminal_session_authority(state, authenticated, project_id, lease)
}

fn validate_terminal_session_authority(
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    project_id: &str,
    lease: &TerminalSessionLease,
) -> Result<PathBuf, (StatusCode, Json<Value>)> {
    if lease.project_id != project_id
        || lease.auth_session_id != authenticated.session_id
        || lease.user_id != authenticated.user.user_id
        || lease.context_revision != authenticated.workspace.revision
    {
        return Err(active_workspace_scope_error());
    }
    let run = state
        .session_store
        .run(&lease.run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "terminal source run not found" })),
            )
        })?;
    let environment = run.environment.as_ref();
    let lease_is_current = run.project_id == lease.project_id
        && run.conversation_id == lease.conversation_id
        && run.revision == lease.run_revision
        && run.status == DesktopRunStatus::Running
        && environment.is_some_and(|environment| {
            environment.id == lease.environment_id
                && FsPath::new(&environment.workspace_path) == lease.cwd.as_path()
        });
    if !lease_is_current {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "terminal session is stale for the authoritative run",
                "run_id": run.id,
                "expected_revision": lease.run_revision,
                "actual_revision": run.revision,
                "status": run.status,
            })),
        ));
    }
    Ok(lease.cwd.clone())
}

fn terminal_session_authority_is_current(
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    project_id: &str,
    lease: &TerminalSessionLease,
) -> bool {
    state
        .session_store
        .session_context_is_current(authenticated, Utc::now().timestamp_millis())
        .unwrap_or(false)
        && validate_terminal_session_authority(state, authenticated, project_id, lease).is_ok()
}

async fn terminal_socket_loop(
    socket: WebSocket,
    cwd: PathBuf,
    session_id: String,
    state: Arc<LocalRuntimeState>,
    authenticated: AuthenticatedContext,
    project_id: String,
    lease: TerminalSessionLease,
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
    command.cwd(cwd);
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
            json!({
                "type": "connected",
                "session_id": session_id,
                "conversation_id": lease.conversation_id,
                "run_id": lease.run_id,
                "run_revision": lease.run_revision,
                "environment_id": lease.environment_id,
                "cols": 120,
                "rows": 32,
            })
            .to_string(),
        ))
        .await;
    let mut authority_check = tokio::time::interval(std::time::Duration::from_secs(1));
    loop {
        tokio::select! {
            incoming = receiver.next() => {
                let Some(Ok(Message::Text(text))) = incoming else {
                    break;
                };
                if !terminal_session_authority_is_current(
                    &state,
                    &authenticated,
                    &project_id,
                    &lease,
                ) {
                    let _ = sender
                        .send(Message::Text(
                            json!({
                                "type": "authority_revoked",
                                "code": "terminal_authority_revoked",
                                "message": "terminal authority is no longer current",
                            })
                            .to_string(),
                        ))
                        .await;
                    break;
                }
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
            _ = authority_check.tick() => {
                if !terminal_session_authority_is_current(
                    &state,
                    &authenticated,
                    &project_id,
                    &lease,
                ) {
                    let _ = sender
                        .send(Message::Text(
                            json!({
                                "type": "authority_revoked",
                                "code": "terminal_authority_revoked",
                                "message": "terminal authority is no longer current",
                            })
                            .to_string(),
                        ))
                        .await;
                    break;
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
    State(_state): State<Arc<LocalRuntimeState>>,
    Json(_body): Json<Value>,
) -> LocalJsonResult {
    Err((
        StatusCode::NOT_IMPLEMENTED,
        Json(json!({
            "detail": "sandbox execution is disabled until an isolated runtime is configured"
        })),
    ))
}

async fn mcp_tools_list(State(state): State<Arc<LocalRuntimeState>>) -> Json<Value> {
    let tool_host = state.tool_host.lock().expect("local tool host").clone();
    Json(tool_host.mcp_tools_list_result())
}

#[derive(Deserialize)]
struct McpToolCallBody {
    run_id: String,
    expected_run_revision: u64,
    name: String,
    #[serde(default)]
    arguments: Value,
}

async fn mcp_tools_call(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<McpToolCallBody>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&body.run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    if run.revision != body.expected_run_revision || run.status != DesktopRunStatus::Running {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "MCP tool execution requires the exact active run revision",
                "actual_revision": run.revision,
                "status": run.status,
            })),
        ));
    }
    let environment = run.environment.as_ref().ok_or_else(|| {
        (
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run has no authoritative execution environment" })),
        )
    })?;
    state
        .worktree_manager()
        .validate(environment)
        .map_err(execution_environment_error)?;
    let inner = LocalToolHost::new(&environment.workspace_path)
        .map_err(|error| execution_environment_error(error.to_string()))?;
    let host = AuthorizedRunToolHost::new(inner, state.session_store.clone(), run);
    let input_json = serde_json::to_string(&body.arguments).map_err(|error| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({ "detail": error.to_string() })),
        )
    })?;
    let output = host.call(&body.name, &input_json).await.map_err(|error| {
        (
            StatusCode::CONFLICT,
            Json(json!({ "detail": error.to_string() })),
        )
    })?;
    let value = serde_json::from_str(&output).unwrap_or_else(|_| {
        json!({
            "isError": false,
            "content": [{ "type": "text", "text": output }],
        })
    });
    Ok(Json(value))
}

fn sandbox_value(project_id: String) -> Value {
    json!({
        "sandbox_id": format!("local-{project_id}"),
        "project_id": project_id,
        "tenant_id": "local",
        "status": "unavailable",
        "endpoint": null,
        "websocket_url": null,
        "desktop_port": null,
        "terminal_port": null,
        "desktop_url": null,
        "terminal_url": null,
        "is_healthy": false,
        "error_message": "isolated local sandbox is not configured",
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
        let redacted_input = authorized_tool_host::redact_tool_payload(tool, input_json);
        let mut item = self.state.timeline_item(
            "act",
            self.conversation_id.clone(),
            None,
            None,
            None,
            json!({ "tool_name": tool, "tool_input": redacted_input }),
        );
        item["toolName"] = json!(tool);
        item["toolInput"] = json!(redacted_input);
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
        let redacted_input = authorized_tool_host::redact_tool_payload(tool, input_json);
        let redacted_output = authorized_tool_host::redact_tool_payload(tool, output_json);
        let mut item = self.state.timeline_item(
            "observe",
            self.conversation_id.clone(),
            None,
            None,
            None,
            json!({
                "tool_name": tool,
                "tool_input": redacted_input,
                "tool_output": redacted_output,
                "observation": redacted_output,
                "is_error": false,
            }),
        );
        item["toolName"] = json!(tool);
        item["toolInput"] = json!(redacted_input);
        item["toolOutput"] = json!(redacted_output);
        item["isError"] = json!(false);
        self.state.append_timeline(&self.conversation_id, item);
        if matches!(tool, "export_artifact" | "batch_export_artifacts") {
            let run_id = self
                .state
                .session_store
                .list_runs(&self.conversation_id)
                .ok()
                .and_then(|runs| runs.into_iter().next())
                .map(|run| run.id);
            for output in artifact_tool_outputs(tool, output_json) {
                match self.state.session_store.record_artifact_version(
                    &self.conversation_id,
                    run_id.as_deref(),
                    &output,
                    &now_iso(),
                ) {
                    Ok(version) => {
                        let mut artifact_item = self.state.timeline_item(
                            "artifact_ready",
                            self.conversation_id.clone(),
                            None,
                            Some("agent"),
                            Some(format!(
                                "{} v{} is ready for review",
                                version.filename, version.version
                            )),
                            serde_json::to_value(&version).unwrap_or_else(|_| json!({})),
                        );
                        artifact_item["artifactId"] = json!(version.artifact_id);
                        artifact_item["artifactVersionId"] = json!(version.id);
                        artifact_item["filename"] = json!(version.filename);
                        self.state
                            .append_timeline(&self.conversation_id, artifact_item);
                    }
                    Err(error) => eprintln!("failed to persist artifact version: {error}"),
                }
            }
        }
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

fn artifact_tool_outputs(tool: &str, output_json: &str) -> Vec<Value> {
    let Ok(wrapper) = serde_json::from_str::<Value>(output_json) else {
        return Vec::new();
    };
    if wrapper
        .get("isError")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return Vec::new();
    }
    let Some(text) = wrapper
        .get("content")
        .and_then(Value::as_array)
        .and_then(|content| content.first())
        .and_then(|content| content.get("text"))
        .and_then(Value::as_str)
    else {
        return Vec::new();
    };
    let Ok(value) = serde_json::from_str::<Value>(text) else {
        return Vec::new();
    };
    if tool == "batch_export_artifacts" {
        return value
            .get("artifacts")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
    }
    vec![value]
}

struct UnconfiguredLocalLlm;

#[async_trait]
impl LlmPort for UnconfiguredLocalLlm {
    async fn extract_memory(&self, _episode: &Episode) -> CoreResult<MemoryDraft> {
        Err(CoreError::Llm(
            "model_unconfigured: configure a local LLM provider before starting an agent"
                .to_string(),
        ))
    }

    async fn decide(
        &self,
        _goal: &str,
        _round: u64,
        _transcript: &[TranscriptEntry],
        _available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        Err(CoreError::Llm(
            "model_unconfigured: configure a local LLM provider before starting an agent"
                .to_string(),
        ))
    }
}

#[cfg(test)]
struct MockLocalLlm;

#[cfg(test)]
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
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        if available_tools
            .iter()
            .any(|tool| tool == SUBMIT_PLAN_TOOL_NAME)
            && !transcript
                .iter()
                .any(|entry| entry.role == Role::Observation)
        {
            return Ok(AgentAction::CallTool {
                tool: SUBMIT_PLAN_TOOL_NAME.to_string(),
                input_json: json!({
                    "tasks": [
                        { "content": "Inspect the context required by the objective", "priority": "high" },
                        { "content": "Complete the approved objective within its stated constraints", "priority": "high" },
                        { "content": "Verify the outcome against the stated success criteria", "priority": "medium" }
                    ]
                })
                .to_string(),
            });
        }
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
        let state = test_state_without_session(token);
        state
            .session_store
            .seed_test_session(token)
            .expect("authenticated test session");
        state
    }

    fn test_state_without_session(token: &str) -> Arc<LocalRuntimeState> {
        let root = test_root();
        let tool_host = LocalToolHost::new(&root).expect("tool host");
        let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        let session_store = DesktopSessionStore::in_memory().expect("session store");
        let state = Arc::new(
            LocalRuntimeState::new(
                root,
                tool_host,
                checkpoints,
                token.to_string(),
                session_store,
            )
            .expect("local runtime state"),
        );
        state.config.lock().expect("config").provider = "mock".to_string();
        state
    }

    fn authenticated_json_request(
        method: &str,
        uri: &str,
        credential: &str,
        body: Value,
    ) -> Request<Body> {
        Request::builder()
            .method(method)
            .uri(uri)
            .header("authorization", format!("Bearer {credential}"))
            .header("x-agistack-launch", credential)
            .header("content-type", "application/json")
            .body(Body::from(body.to_string()))
            .expect("authenticated JSON request")
    }

    async fn response_json(response: axum::response::Response) -> Value {
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("response body");
        serde_json::from_slice(&body).expect("response JSON")
    }

    fn test_decision_context() -> agistack_core::agent::types::DecisionContext {
        use agistack_core::agent::types::{
            DecisionAction, DecisionContext, DecisionData, DecisionEvidence, DecisionReversibility,
            DecisionReversibilityMode, DecisionRisk, DecisionRiskLevel, DecisionScope,
            DecisionTarget,
        };

        DecisionContext {
            action: DecisionAction {
                name: "workspace.write".to_string(),
                label: "Apply reviewed patch".to_string(),
            },
            target: DecisionTarget {
                kind: "worktree".to_string(),
                id: "worktree-test".to_string(),
                version_id: Some("checkpoint-test".to_string()),
                path: Some("src/lib.rs".to_string()),
            },
            data: DecisionData {
                summary: "Apply the reviewed source patch".to_string(),
                redacted_fields: vec![],
            },
            reason: "The approved implementation requires this edit".to_string(),
            risk: DecisionRisk {
                level: DecisionRiskLevel::Medium,
                rationale: "The patch changes runtime behavior".to_string(),
            },
            reversibility: DecisionReversibility {
                mode: DecisionReversibilityMode::Reversible,
                recovery: Some("Restore the saved checkpoint".to_string()),
            },
            scope: DecisionScope {
                kind: "files".to_string(),
                ids: vec!["src/lib.rs".to_string()],
            },
            evidence: vec![DecisionEvidence {
                kind: "diff".to_string(),
                id: "diff-test".to_string(),
                label: "Patch preview".to_string(),
                uri: None,
                digest: Some("sha256:test".to_string()),
            }],
        }
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
    async fn local_session_and_workspace_context_require_two_credentials_and_revoke_cleanly() {
        let state = test_state_without_session("launch-secret");
        let app = local_router(state);

        let capability_only = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/auth/me")
                    .header("authorization", "Bearer launch-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(
            capability_only.status(),
            axum::http::StatusCode::UNAUTHORIZED
        );

        let create = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/auth/local-session")
                    .header("x-agistack-launch", "launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(r#"{"trusted_device":true}"#))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(create.status(), axum::http::StatusCode::OK);
        let body = axum::body::to_bytes(create.into_body(), usize::MAX)
            .await
            .expect("session body");
        let created: Value = serde_json::from_slice(&body).expect("session json");
        let credential = created["access_token"]
            .as_str()
            .expect("session credential");
        assert_eq!(created["context"]["tenant_id"], "local");
        assert_eq!(created["context"]["revision"], 0);

        let authenticated = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/auth/me")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(authenticated.status(), axum::http::StatusCode::OK);

        let switched = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/workspace-context/switch")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"tenant_id":"northstar","project_id":"desktop-client","expected_revision":0,"idempotency_key":"switch-desktop-client"}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(switched.status(), axum::http::StatusCode::OK);

        let stale_scope = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/projects/local-project/my-work")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(stale_scope.status(), axum::http::StatusCode::FORBIDDEN);

        let signout = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/auth/signout")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(signout.status(), axum::http::StatusCode::OK);

        let revoked = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/auth/me")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(revoked.status(), axum::http::StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn trusted_local_session_resume_requires_reference_and_rotates_the_bearer() {
        let state = test_state_without_session("launch-secret");
        let app = local_router(state);

        let created = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/auth/local-session")
                    .header("x-agistack-launch", "launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(r#"{"trusted_device":true}"#))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(created.status(), axum::http::StatusCode::OK);
        let body = axum::body::to_bytes(created.into_body(), usize::MAX)
            .await
            .expect("session body");
        let created: Value = serde_json::from_slice(&body).expect("session json");
        let original_credential = created["access_token"]
            .as_str()
            .expect("original credential");
        let session_id = created["session"]["session_id"]
            .as_str()
            .expect("session id");

        let missing_launch = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/auth/local-session/resume")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(r#"{{"session_id":"{session_id}"}}"#)))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(
            missing_launch.status(),
            axum::http::StatusCode::UNAUTHORIZED
        );

        let resumed = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/auth/local-session/resume")
                    .header("x-agistack-launch", "launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(r#"{{"session_id":"{session_id}"}}"#)))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(resumed.status(), axum::http::StatusCode::OK);
        let body = axum::body::to_bytes(resumed.into_body(), usize::MAX)
            .await
            .expect("resume body");
        let resumed: Value = serde_json::from_slice(&body).expect("resume json");
        let rotated_credential = resumed["access_token"]
            .as_str()
            .expect("rotated credential");
        assert_ne!(rotated_credential, original_credential);
        assert_eq!(resumed["session"]["session_id"], session_id);

        let stale_bearer = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/auth/me")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {original_credential}"))
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(stale_bearer.status(), axum::http::StatusCode::UNAUTHORIZED);

        let signout = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/auth/signout")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {rotated_credential}"))
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(signout.status(), axum::http::StatusCode::OK);

        let revoked_resume = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/auth/local-session/resume")
                    .header("x-agistack-launch", "launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(r#"{{"session_id":"{session_id}"}}"#)))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(
            revoked_resume.status(),
            axum::http::StatusCode::UNAUTHORIZED
        );
    }

    #[tokio::test]
    async fn provider_types_declare_supported_local_auth_methods() {
        let state = test_state("provider-types-secret");
        let app = local_router(state);

        let response = app
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/types",
                "provider-types-secret",
                json!({}),
            ))
            .await
            .expect("provider types response");

        assert_eq!(response.status(), axum::http::StatusCode::OK);
        assert_eq!(
            response_json(response).await,
            json!([
                {
                    "provider_type": "openai",
                    "auth_methods": ["api_key", "none"]
                },
                {
                    "provider_type": "anthropic",
                    "auth_methods": ["api_key", "none"]
                },
                {
                    "provider_type": "openai_compatible",
                    "auth_methods": ["api_key", "none"]
                }
            ])
        );
    }

    #[tokio::test]
    async fn provider_mutation_is_revision_guarded_and_never_reuses_another_provider_key() {
        let state = test_state("provider-secret");
        let app = local_router(Arc::clone(&state));

        let missing_revision = app
            .clone()
            .oneshot(authenticated_json_request(
                "PATCH",
                "/api/v1/llm-providers/local-runtime",
                "provider-secret",
                json!({
                    "provider_type": "openai",
                    "base_url": "https://api.example.test/v1",
                    "auth_method": "api_key",
                    "llm_model": "model-a",
                    "is_active": true,
                    "api_key": "provider-key-a"
                }),
            ))
            .await
            .expect("missing revision response");
        assert_eq!(
            missing_revision.status(),
            axum::http::StatusCode::PRECONDITION_REQUIRED
        );

        let activate_a = app
            .clone()
            .oneshot(authenticated_json_request(
                "PATCH",
                "/api/v1/llm-providers/local-runtime",
                "provider-secret",
                json!({
                    "provider_type": "openai",
                    "base_url": "https://api.example.test/v1",
                    "auth_method": "api_key",
                    "llm_model": "model-a",
                    "is_active": true,
                    "api_key": "provider-key-a",
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("activate provider A");
        assert_eq!(activate_a.status(), axum::http::StatusCode::OK);
        let activated_a = response_json(activate_a).await;
        assert_eq!(activated_a["credential_configured"], true);
        assert_eq!(activated_a["revision"], 1);
        assert!(!activated_a.to_string().contains("provider-key-a"));

        let activate_b = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/",
                "provider-secret",
                json!({
                    "name": "Provider B",
                    "provider_type": "openai",
                    "base_url": "https://api-b.example.test/v1",
                    "llm_model": "model-b",
                    "is_active": true
                }),
            ))
            .await
            .expect("activate provider B");
        assert_eq!(activate_b.status(), axum::http::StatusCode::OK);
        let activated_b = response_json(activate_b).await;
        assert_eq!(activated_b["credential_configured"], false);
        assert_eq!(activated_b["health_status"], "needs_credentials");

        let reactivate_a = app
            .clone()
            .oneshot(authenticated_json_request(
                "PATCH",
                "/api/v1/llm-providers/local-runtime",
                "provider-secret",
                json!({
                    "is_active": true,
                    "expected_revision": 1
                }),
            ))
            .await
            .expect("reactivate provider A without a new credential");
        assert_eq!(reactivate_a.status(), axum::http::StatusCode::OK);
        let reactivated_a = response_json(reactivate_a).await;
        assert_eq!(reactivated_a["credential_configured"], false);
        assert_eq!(reactivated_a["health_status"], "needs_credentials");
        assert_eq!(reactivated_a["revision"], 2);

        let validate = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/local-runtime/test",
                "provider-secret",
                json!({}),
            ))
            .await
            .expect("validate provider configuration");
        assert_eq!(validate.status(), axum::http::StatusCode::OK);
        let validation = response_json(validate).await;
        assert_eq!(validation["probed"], false);
        assert_eq!(validation["status"], "needs_credentials");
        assert_eq!(validation["provider"]["revision"], 2);
        assert!(validation.get("last_verified_at").is_none());

        let disable_a = app
            .oneshot(authenticated_json_request(
                "PATCH",
                "/api/v1/llm-providers/local-runtime",
                "provider-secret",
                json!({ "is_active": false, "expected_revision": 2 }),
            ))
            .await
            .expect("disable active provider");
        assert_eq!(disable_a.status(), axum::http::StatusCode::OK);
        let disabled_a = response_json(disable_a).await;
        assert_eq!(disabled_a["health_status"], "disabled");
        assert!(state
            .provider_bindings
            .lock()
            .expect("provider bindings")
            .get("local")
            .is_none());
        assert_eq!(
            state.config.lock().expect("config").provider,
            "unconfigured"
        );

        let persisted = state
            .session_store
            .managed_resource(
                ManagedResourceKind::Provider,
                "tenant",
                "local",
                "local-runtime",
            )
            .expect("persisted provider")
            .expect("local runtime provider");
        assert!(!persisted.to_string().contains("provider-key-a"));
        assert!(persisted.get("api_key").is_none());
    }

    #[tokio::test]
    async fn tenant_members_can_list_but_cannot_mutate_or_validate_providers() {
        let state = test_state("member-provider-secret");
        let authenticated = state
            .session_store
            .validate_session_credential("member-provider-secret", Utc::now().timestamp_millis())
            .expect("validate session")
            .expect("authenticated context");
        state
            .session_store
            .switch_workspace_context(
                &authenticated,
                &ContextSwitchRequest {
                    tenant_id: "orbital".to_string(),
                    project_id: "agent-evals".to_string(),
                    expected_revision: 0,
                    idempotency_key: "switch-member-provider-test".to_string(),
                },
                Utc::now().timestamp_millis(),
            )
            .expect("switch to member tenant");
        let app = local_router(state);

        let list = app
            .clone()
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/",
                "member-provider-secret",
                json!({}),
            ))
            .await
            .expect("member list response");
        assert_eq!(list.status(), axum::http::StatusCode::OK);

        let update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PATCH",
                "/api/v1/llm-providers/local-runtime",
                "member-provider-secret",
                json!({ "is_active": false, "expected_revision": 0 }),
            ))
            .await
            .expect("member update response");
        assert_eq!(update.status(), axum::http::StatusCode::FORBIDDEN);

        let validate = app
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/local-runtime/test",
                "member-provider-secret",
                json!({}),
            ))
            .await
            .expect("member validation response");
        assert_eq!(validate.status(), axum::http::StatusCode::FORBIDDEN);
    }

    #[tokio::test]
    async fn opaque_agent_resources_are_rejected_outside_active_workspace_context() {
        let state = test_state_without_session("launch-secret");
        let app = local_router(state);

        let session = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/auth/local-session")
                    .header("x-agistack-launch", "launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(r#"{"trusted_device":true}"#))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(session.status(), axum::http::StatusCode::OK);
        let body = axum::body::to_bytes(session.into_body(), usize::MAX)
            .await
            .expect("session body");
        let session: Value = serde_json::from_slice(&body).expect("session json");
        let credential = session["access_token"]
            .as_str()
            .expect("session credential");

        let conversation = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/conversations")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"project_id":"local-project","title":"Local context","agent_config":{"capability_mode":"code"}}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(conversation.status(), axum::http::StatusCode::OK);
        let body = axum::body::to_bytes(conversation.into_body(), usize::MAX)
            .await
            .expect("conversation body");
        let conversation: Value = serde_json::from_slice(&body).expect("conversation json");
        let conversation_id = conversation["id"].as_str().expect("conversation id");

        let switched = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/workspace-context/switch")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"tenant_id":"northstar","project_id":"desktop-client","expected_revision":0,"idempotency_key":"switch-resource-scope"}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(switched.status(), axum::http::StatusCode::OK);

        let stale_list = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/agent/conversations?project_id=local-project")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(stale_list.status(), axum::http::StatusCode::FORBIDDEN);

        let stale_create = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/conversations")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .header("content-type", "application/json")
                    .body(Body::from(r#"{"project_id":"local-project"}"#))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(stale_create.status(), axum::http::StatusCode::FORBIDDEN);

        let stale_conversation = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{conversation_id}/messages"
                    ))
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(
            stale_conversation.status(),
            axum::http::StatusCode::FORBIDDEN
        );

        let active_conversation = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/conversations")
                    .header("x-agistack-launch", "launch-secret")
                    .header("authorization", format!("Bearer {credential}"))
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"project_id":"desktop-client","title":"Active context"}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(active_conversation.status(), axum::http::StatusCode::OK);
        let body = axum::body::to_bytes(active_conversation.into_body(), usize::MAX)
            .await
            .expect("active conversation body");
        let active_conversation: Value =
            serde_json::from_slice(&body).expect("active conversation json");
        assert_eq!(active_conversation["tenant_id"], "northstar");
        assert_eq!(active_conversation["project_id"], "desktop-client");
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
        state
            .session_store
            .insert_conversation(&LocalConversation {
                id: conversation_id.clone(),
                project_id: "local-project".to_string(),
                tenant_id: "local".to_string(),
                title: "Sequential plan messages".to_string(),
                workspace_id: Some("local-workspace".to_string()),
                capability_mode: ConversationCapabilityMode::Unavailable,
                current_mode: ConversationRunMode::Plan,
                created_at: now_iso(),
                updated_at: now_iso(),
            })
            .expect("insert conversation");

        Arc::clone(&state)
            .run_agent_message(
                conversation_id.clone(),
                "local-project".to_string(),
                "first".to_string(),
                "message-1".to_string(),
                None,
                None,
            )
            .await;
        Arc::clone(&state)
            .run_agent_message(
                conversation_id.clone(),
                "local-project".to_string(),
                "second".to_string(),
                "message-2".to_string(),
                None,
                None,
            )
            .await;

        let timeline = state
            .session_store
            .timeline(&conversation_id, 100)
            .expect("timeline");
        let assistant_messages = timeline
            .iter()
            .filter(|event| event["type"] == "assistant_message")
            .count();
        assert_eq!(assistant_messages, 2);
    }

    #[tokio::test]
    async fn new_message_starts_after_cancelled_checkpoint() {
        let state = test_state("launch-secret");
        let conversation_id = "conversation-cancelled".to_string();
        state
            .session_store
            .insert_conversation(&LocalConversation {
                id: conversation_id.clone(),
                project_id: "local-project".to_string(),
                tenant_id: "local".to_string(),
                title: "Restart after cancellation".to_string(),
                workspace_id: Some("local-workspace".to_string()),
                capability_mode: ConversationCapabilityMode::Unavailable,
                current_mode: ConversationRunMode::Plan,
                created_at: now_iso(),
                updated_at: now_iso(),
            })
            .expect("insert conversation");
        let mut checkpoint = SessionState::new(
            conversation_id.clone(),
            "cancelled request",
            Some("local-project"),
        );
        checkpoint.status = SessionStatus::Cancelled;
        state
            .checkpoints
            .save(&checkpoint)
            .await
            .expect("save cancelled checkpoint");

        Arc::clone(&state)
            .run_agent_message(
                conversation_id.clone(),
                "local-project".to_string(),
                "start a new request".to_string(),
                "message-after-cancel".to_string(),
                None,
                None,
            )
            .await;

        let restarted = state
            .checkpoints
            .load(&conversation_id)
            .await
            .expect("load checkpoint")
            .expect("checkpoint");
        assert_eq!(restarted.status, SessionStatus::Finished);
        assert_eq!(restarted.goal, "start a new request");
    }

    #[test]
    fn desktop_session_store_restores_workspace_conversation_and_timeline_after_reopen() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create test root");
        let path = root.join("desktop-sessions.db");
        let workspace = json!({
            "id": "workspace-1",
            "project_id": "project-1",
            "name": "Persistent workspace"
        });
        let conversation = LocalConversation {
            id: "conversation-1".to_string(),
            project_id: "project-1".to_string(),
            tenant_id: "tenant-1".to_string(),
            title: "Persistent session".to_string(),
            workspace_id: Some("workspace-1".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Build,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        let timeline_item = json!({
            "id": "event-1",
            "type": "user_message",
            "content": "persist me"
        });
        let plan_task = json!({
            "id": "plan-task-1",
            "conversation_id": "conversation-1",
            "content": "Persist the plan",
            "status": "pending",
            "priority": "high",
            "order_index": 0,
            "created_at": now_iso(),
            "updated_at": now_iso()
        });

        {
            let store = DesktopSessionStore::open(&path).expect("open store");
            store
                .insert_workspace(&workspace)
                .expect("insert workspace");
            store
                .insert_conversation(&conversation)
                .expect("insert conversation");
            store
                .append_timeline(&conversation.id, &timeline_item)
                .expect("append timeline");
            store
                .replace_agent_plan_tasks(&conversation.id, std::slice::from_ref(&plan_task))
                .expect("store plan task");
        }

        let restored = DesktopSessionStore::open(&path).expect("reopen store");
        assert_eq!(
            restored.list_workspaces("project-1").unwrap(),
            vec![workspace]
        );
        assert_eq!(
            restored
                .conversation("conversation-1")
                .unwrap()
                .expect("conversation")
                .title,
            "Persistent session"
        );
        assert_eq!(
            restored.timeline("conversation-1", 20).unwrap(),
            vec![timeline_item]
        );
        assert_eq!(
            restored.list_agent_plan_tasks("conversation-1").unwrap(),
            vec![plan_task]
        );
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[tokio::test]
    async fn plan_mode_tool_host_allows_inspection_and_rejects_workspace_mutation() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create test root");
        std::fs::write(root.join("notes.txt"), "plan context").expect("write fixture");
        let store = DesktopSessionStore::in_memory().expect("session store");
        let host = PlanModeToolHost::new(
            LocalToolHost::new(&root).expect("tool host"),
            store.clone(),
            "conversation-plan".to_string(),
        );

        assert!(host.list_tools().iter().any(|tool| tool == "read"));
        assert!(host
            .list_tools()
            .iter()
            .any(|tool| tool == SUBMIT_PLAN_TOOL_NAME));
        assert!(!host.list_tools().iter().any(|tool| tool == "write"));
        let read_result = host
            .call("read", r#"{"path":"notes.txt"}"#)
            .await
            .expect("read is allowed");
        assert!(read_result.contains("plan context"));
        let write_error = host
            .call(
                "write",
                r#"{"path":"blocked.txt","content":"must not write"}"#,
            )
            .await
            .expect_err("write is blocked");
        assert!(write_error.to_string().contains("blocked"));
        assert!(!root.join("blocked.txt").exists());
        host.call(
            SUBMIT_PLAN_TOOL_NAME,
            r#"{"tasks":[{"content":"Inspect context","priority":"high"},{"content":"Verify outcome"}]}"#,
        )
        .await
        .expect("structured plan is allowed");
        let tasks = store
            .list_agent_plan_tasks("conversation-plan")
            .expect("stored tasks");
        assert_eq!(tasks.len(), 2);
        assert_eq!(tasks[0]["content"], "Inspect context");
        assert_eq!(tasks[1]["priority"], "medium");
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[tokio::test]
    async fn plan_task_route_returns_only_the_requested_conversation_plan() {
        let state = test_state("launch-secret");
        let conversation = LocalConversation {
            id: "conversation-plan-tasks".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Reviewable plan".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Unavailable,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "plan-task-1",
                    "conversation_id": conversation.id,
                    "content": "Inspect the session UI",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .uri("/api/v1/agent/plan/tasks/conversation-plan-tasks")
                    .header("authorization", "Bearer launch-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["total_count"], 1);
        assert_eq!(payload["tasks"][0]["content"], "Inspect the session UI");
        assert_eq!(payload["approval"]["kind"], "versioned_atomic");
        assert_eq!(payload["approval"]["plan_version"]["status"], "draft");
        assert_eq!(payload["approval"]["plan_version"], payload["plan_version"]);
    }

    #[tokio::test]
    async fn workspace_execution_projection_uses_latest_plan_and_run_without_fabricated_root_plan()
    {
        let state = test_state("workspace-projection-secret");
        let conversation = LocalConversation {
            id: "conversation-workspace-projection".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Project the approved plan".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert projected conversation");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "superseded-plan-task",
                    "conversation_id": conversation.id,
                    "content": "Old plan step",
                    "status": "pending",
                    "priority": "low",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store first plan");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "current-plan-task",
                    "conversation_id": conversation.id,
                    "content": "Build the workspace projection",
                    "status": "in_progress",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store latest plan");
        let approved = state
            .session_store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                "workspace-projection-approval",
                "workspace-projection-message",
                "Execute the reviewed workspace plan",
                &now_iso(),
            )
            .expect("approve latest plan");

        let app = local_router(Arc::clone(&state));
        let tasks_response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/workspaces/local-workspace/tasks")
                    .header("authorization", "Bearer workspace-projection-secret")
                    .body(Body::empty())
                    .expect("tasks request"),
            )
            .await
            .expect("tasks response");
        assert_eq!(tasks_response.status(), StatusCode::OK);
        let tasks = response_json(tasks_response).await;
        assert_eq!(tasks["items"].as_array().map(Vec::len), Some(1));
        assert_eq!(tasks["items"][0]["id"], "current-plan-task");
        assert_eq!(tasks["items"][0]["title"], "Build the workspace projection");
        assert_eq!(tasks["items"][0]["status"], "in_progress");
        assert_eq!(tasks["items"][0]["priority"], "high");
        assert_eq!(tasks["items"][0]["conversation_id"], conversation.id);
        assert_eq!(tasks["items"][0]["plan_version"], 2);
        assert_eq!(tasks["items"][0]["plan_status"], "approved");
        assert_eq!(tasks["items"][0]["run_id"], approved.run.id);
        assert_eq!(tasks["items"][0]["run_status"], "queued");
        assert_eq!(tasks["items"][0]["run_revision"], 1);
        assert_eq!(tasks["items"][0]["source"], "agent_plan_task");

        let plan_response = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/workspaces/local-workspace/plan")
                    .header("authorization", "Bearer workspace-projection-secret")
                    .body(Body::empty())
                    .expect("plan request"),
            )
            .await
            .expect("plan response");
        assert_eq!(plan_response.status(), StatusCode::OK);
        let plan = response_json(plan_response).await;
        assert!(plan["plan"].is_null());
        assert_eq!(plan["workspace_id"], "local-workspace");
        assert_eq!(plan["project_id"], "local-project");
        assert_eq!(plan["conversation_plans"].as_array().map(Vec::len), Some(1));
        assert_eq!(
            plan["conversation_plans"][0]["conversation_id"],
            conversation.id
        );
        assert_eq!(plan["conversation_plans"][0]["plan"]["version"], 2);
        assert_eq!(plan["conversation_plans"][0]["run"]["id"], approved.run.id);
        assert_eq!(plan["plan_history"].as_array().map(Vec::len), Some(2));
    }

    #[tokio::test]
    async fn empty_workspace_projection_is_explicit_and_contains_no_fabricated_plan() {
        let state = test_state("empty-workspace-secret");
        state
            .session_store
            .insert_workspace(&json!({
                "id": "empty-workspace",
                "tenant_id": "local",
                "project_id": "local-project",
                "name": "Empty workspace",
                "status": "open",
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "metadata": { "runtime": "local" },
            }))
            .expect("insert empty workspace");
        let app = local_router(state);

        let tasks_response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/workspaces/empty-workspace/tasks")
                    .header("authorization", "Bearer empty-workspace-secret")
                    .body(Body::empty())
                    .expect("tasks request"),
            )
            .await
            .expect("tasks response");
        assert_eq!(tasks_response.status(), StatusCode::OK);
        let tasks = response_json(tasks_response).await;
        assert_eq!(tasks["items"], json!([]));

        let plan_response = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/workspaces/empty-workspace/plan")
                    .header("authorization", "Bearer empty-workspace-secret")
                    .body(Body::empty())
                    .expect("plan request"),
            )
            .await
            .expect("plan response");
        assert_eq!(plan_response.status(), StatusCode::OK);
        let plan = response_json(plan_response).await;
        assert!(plan["plan"].is_null());
        assert_eq!(plan["conversation_plans"], json!([]));
        assert_eq!(plan["plan_history"], json!([]));
        assert_eq!(plan["run_health"], json!([]));
        assert_eq!(plan["pending_hitl"], json!([]));
        assert_eq!(plan["delivery"], json!([]));
        assert_eq!(plan["artifact_index"], json!([]));
    }

    #[tokio::test]
    async fn conversation_session_projection_returns_one_authoritative_snapshot() {
        let state = test_state("session-projection-secret");
        let conversation = LocalConversation {
            id: "conversation-session-projection".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Project the complete session".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "session-projection-task",
                    "conversation_id": conversation.id,
                    "content": "Expose authoritative session state",
                    "status": "in_progress",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let approved = state
            .session_store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                "session-projection-approval",
                "session-projection-message",
                "Execute the reviewed plan",
                &now_iso(),
            )
            .expect("approve plan");

        let response = local_router(state)
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{}/session",
                        conversation.id
                    ))
                    .header("authorization", "Bearer session-projection-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let snapshot = response_json(response).await;

        assert_eq!(snapshot["schema_version"], 1);
        assert_eq!(snapshot["conversation"]["id"], conversation.id);
        assert_eq!(snapshot["current_run"]["id"], approved.run.id);
        assert_eq!(snapshot["run_history"].as_array().map(Vec::len), Some(1));
        assert_eq!(snapshot["current_plan"]["id"], approved.plan_version.id);
        assert_eq!(snapshot["current_plan"]["status"], "approved");
        assert_eq!(snapshot["plan_history"].as_array().map(Vec::len), Some(1));
        assert_eq!(snapshot["tasks"][0]["id"], "session-projection-task");
        assert_eq!(snapshot["pending_hitl"], json!([]));
        assert_eq!(snapshot["artifact_versions"], json!([]));
        assert_eq!(snapshot["artifact_deliveries"], json!([]));
        assert_eq!(snapshot["tool_invocations"], json!([]));
        assert_eq!(snapshot["evidence_summary"]["checks"], Value::Null);
        assert_eq!(snapshot["capabilities"]["can_send_message"], false);
        assert_eq!(snapshot["capabilities"]["can_approve_plan"], false);
        assert_eq!(snapshot["capabilities"]["run_actions"], json!([]));
        assert!(snapshot["snapshot_revision"]
            .as_str()
            .is_some_and(|revision| !revision.is_empty()));
        assert!(snapshot["updated_at"]
            .as_str()
            .is_some_and(|updated_at| !updated_at.is_empty()));
    }

    #[tokio::test]
    async fn workspace_execution_projection_rejects_a_cross_tenant_conversation_record() {
        let state = test_state("tenant-projection-secret");
        let conversation = LocalConversation {
            id: "cross-tenant-workspace-projection".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "outside-tenant".to_string(),
            title: "Must not be projected".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Work,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert invalid cross-tenant conversation");

        let response = local_router(state)
            .oneshot(
                Request::builder()
                    .uri("/api/v1/workspaces/local-workspace/tasks")
                    .header("authorization", "Bearer tenant-projection-secret")
                    .body(Body::empty())
                    .expect("tasks request"),
            )
            .await
            .expect("tasks response");
        assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
        let payload = response_json(response).await;
        assert_eq!(payload["detail"], "desktop session store unavailable");
    }

    #[tokio::test]
    async fn plan_mode_route_persists_the_conversation_authority_boundary() {
        let state = test_state("launch-secret");
        let conversation = LocalConversation {
            id: "conversation-plan".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Plan-first session".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Unavailable,
            current_mode: ConversationRunMode::Build,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        let app = local_router(Arc::clone(&state));
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/plan/mode")
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"conversation_id":"conversation-plan","mode":"plan"}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            state
                .session_store
                .conversation("conversation-plan")
                .expect("load conversation")
                .expect("conversation")
                .current_mode,
            ConversationRunMode::Plan
        );
    }

    #[tokio::test]
    async fn new_conversations_start_in_plan_mode() {
        let state = test_state("launch-secret");
        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/conversations")
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"project_id":"local-project","title":"Plan first","agent_config":{"selected_agent_id":"builtin:all-access","capability_mode":"code"}}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["current_mode"], "plan");
        assert_eq!(payload["agent_config"]["capability_mode"], "code");
        assert_eq!(payload["metadata"]["capability_mode"], "code");
    }

    #[test]
    fn my_work_groups_only_authoritative_attention_states() {
        assert_eq!(
            my_work_group(DesktopRunStatus::NeedsApproval),
            Some("needs_approval")
        );
        assert_eq!(
            my_work_group(DesktopRunStatus::ReadyReview),
            Some("ready_review")
        );
        assert_eq!(my_work_group(DesktopRunStatus::Running), Some("running"));
        assert_eq!(
            my_work_group(DesktopRunStatus::Disconnected),
            Some("needs_input")
        );
        assert_eq!(my_work_group(DesktopRunStatus::Completed), None);
        assert_eq!(my_work_group(DesktopRunStatus::Cancelled), None);
    }

    #[tokio::test]
    async fn my_work_route_is_project_scoped_and_uses_run_status_without_text_inference() {
        let state = test_state("launch-secret");
        let seed =
            |conversation_id: &str, project_id: &str, status: DesktopRunStatus| -> DesktopRun {
                let conversation = LocalConversation {
                    id: conversation_id.to_string(),
                    project_id: project_id.to_string(),
                    tenant_id: "local".to_string(),
                    title: format!("Attention item {conversation_id}"),
                    workspace_id: Some(format!("workspace-{project_id}")),
                    capability_mode: ConversationCapabilityMode::Code,
                    current_mode: ConversationRunMode::Plan,
                    created_at: now_iso(),
                    updated_at: now_iso(),
                };
                state
                    .session_store
                    .insert_conversation(&conversation)
                    .expect("insert conversation");
                state
                    .session_store
                    .replace_agent_plan_tasks(
                        &conversation.id,
                        &[json!({
                            "id": format!("task-{conversation_id}"),
                            "conversation_id": conversation.id,
                            "content": "A title with no status keywords",
                            "status": "pending",
                            "priority": "high",
                            "order_index": 0,
                            "created_at": now_iso(),
                            "updated_at": now_iso(),
                        })],
                    )
                    .expect("store plan");
                let approved = state
                    .session_store
                    .approve_plan_and_start(
                        &conversation.id,
                        project_id,
                        &format!("approval-{conversation_id}"),
                        &format!("message-{conversation_id}"),
                        "Execute the reviewed plan",
                        &now_iso(),
                    )
                    .expect("approve run");
                let running = state
                    .session_store
                    .prepare_run_for_execution(&approved.run.id, &now_iso())
                    .expect("prepare run")
                    .expect("running run");
                if status == DesktopRunStatus::Running {
                    running
                } else {
                    state
                        .session_store
                        .transition_run(&running.id, running.revision, status, None, &now_iso())
                        .expect("transition attention run")
                }
            };
        let expected = seed(
            "conversation-local-project",
            "local-project",
            DesktopRunStatus::NeedsApproval,
        );
        seed(
            "conversation-project-b",
            "project-b",
            DesktopRunStatus::ReadyReview,
        );

        let response = local_router(state)
            .oneshot(
                Request::builder()
                    .uri("/api/v1/projects/local-project/my-work")
                    .header("authorization", "Bearer launch-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["project_id"], "local-project");
        assert_eq!(payload["total"], 1);
        assert_eq!(payload["items"][0]["run_id"], expected.id);
        assert_eq!(payload["items"][0]["group"], "needs_approval");
        assert_eq!(payload["items"][0]["required_action"], "review_approval");
    }

    #[tokio::test]
    async fn conversation_capability_can_switch_without_losing_workspace_linkage() {
        let state = test_state("launch-secret");
        let create_response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/conversations")
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"project_id":"local-project","title":"Research first","agent_config":{"selected_agent_id":"builtin:all-access","capability_mode":"work"}}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        let create_body = axum::body::to_bytes(create_response.into_body(), usize::MAX)
            .await
            .expect("body");
        let created: Value = serde_json::from_slice(&create_body).expect("json");
        let conversation_id = created["id"].as_str().expect("conversation id");

        let switch_response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("PATCH")
                    .uri(format!(
                        "/api/v1/agent/conversations/{conversation_id}/mode?project_id=local-project"
                    ))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"workspace_id":"local-workspace","capability_mode":"code"}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(switch_response.status(), StatusCode::OK);
        let switch_body = axum::body::to_bytes(switch_response.into_body(), usize::MAX)
            .await
            .expect("body");
        let switched: Value = serde_json::from_slice(&switch_body).expect("json");
        assert_eq!(switched["agent_config"]["capability_mode"], "code");
        assert_eq!(switched["metadata"]["capability_mode"], "code");
        assert_eq!(switched["workspace_id"], "local-workspace");

        let stored = state
            .session_store
            .conversation(conversation_id)
            .expect("load stored conversation")
            .expect("stored conversation");
        assert_eq!(stored.capability_mode, ConversationCapabilityMode::Code);
        assert_eq!(stored.workspace_id.as_deref(), Some("local-workspace"));
    }

    #[test]
    fn approve_and_start_is_atomic_idempotent_and_restorable() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create test root");
        let path = root.join("authoritative-runs.db");
        let conversation = LocalConversation {
            id: "conversation-authority".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Authoritative run".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        let task = json!({
            "id": "plan-task-authority",
            "conversation_id": conversation.id,
            "content": "Implement the approved design",
            "status": "pending",
            "priority": "high",
            "order_index": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        });

        let run_id = {
            let store = DesktopSessionStore::open(&path).expect("open store");
            store
                .insert_conversation(&conversation)
                .expect("insert conversation");
            store
                .replace_agent_plan_tasks(&conversation.id, &[task])
                .expect("store versioned plan");
            let first = store
                .approve_plan_and_start(
                    &conversation.id,
                    "local-project",
                    "approval-key-1",
                    "message-1",
                    "Execute the plan",
                    &now_iso(),
                )
                .expect("approve plan");
            let duplicate = store
                .approve_plan_and_start(
                    &conversation.id,
                    "local-project",
                    "approval-key-1",
                    "message-1",
                    "Execute the plan",
                    &now_iso(),
                )
                .expect("repeat approval");
            assert!(first.created);
            assert!(!duplicate.created);
            assert_eq!(first.run.id, duplicate.run.id);
            assert_eq!(store.list_runs(&conversation.id).unwrap().len(), 1);
            assert_eq!(
                store
                    .conversation(&conversation.id)
                    .unwrap()
                    .expect("conversation")
                    .current_mode,
                ConversationRunMode::Build
            );
            first.run.id
        };

        let restored = DesktopSessionStore::open(&path).expect("reopen store");
        let run = restored.run(&run_id).unwrap().expect("restored run");
        assert_eq!(run.status, DesktopRunStatus::Queued);
        assert_eq!(run.revision, 1);
        assert_eq!(restored.run_events(&run_id).unwrap().len(), 1);
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[test]
    fn approval_idempotency_key_cannot_be_reused_with_a_different_authority_profile() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: "conversation-idempotency-authority".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Idempotency authority".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "idempotency-authority-task",
                    "conversation_id": conversation.id,
                    "content": "Execute under the reviewed authority profile",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let plan = store
            .latest_draft_plan(&conversation.id)
            .expect("load plan")
            .expect("plan");
        let approval = |permission_profile| session_store::ApprovePlanStartInput {
            conversation_id: &conversation.id,
            project_id: "local-project",
            plan_version_id: &plan.id,
            expected_plan_version: plan.version,
            idempotency_key: "authority-idempotency-key",
            message_id: "authority-idempotency-message",
            request_message: "Execute reviewed plan",
            environment: None,
            requested_environment_kind: DesktopExecutionEnvironmentKind::Local,
            permission_profile,
            now: "2026-07-13T00:00:00Z",
        };

        store
            .approve_plan_and_start_in_environment(approval(DesktopPermissionProfile::ReadOnly))
            .expect("first approval");
        let error = store
            .approve_plan_and_start_in_environment(approval(
                DesktopPermissionProfile::WorkspaceWrite,
            ))
            .expect_err("changed authority must not replay the idempotency key");

        assert!(matches!(error, DesktopAuthorityError::IdempotencyConflict));
        assert_eq!(store.list_runs(&conversation.id).unwrap().len(), 1);
    }

    #[test]
    fn approval_rejects_a_plan_version_that_changed_after_human_preview() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: "conversation-stale-plan".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Stale plan protection".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        let task = |id: &str, content: &str| {
            json!({
                "id": id,
                "conversation_id": conversation.id,
                "content": content,
                "status": "pending",
                "priority": "high",
                "order_index": 0,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            })
        };
        store
            .replace_agent_plan_tasks(&conversation.id, &[task("plan-v1", "First plan")])
            .expect("store first plan");
        let reviewed = store
            .latest_draft_plan(&conversation.id)
            .expect("load first plan")
            .expect("first plan");
        store
            .replace_agent_plan_tasks(&conversation.id, &[task("plan-v2", "Revised plan")])
            .expect("store revised plan");

        let error = store
            .approve_plan_and_start_in_environment(session_store::ApprovePlanStartInput {
                conversation_id: &conversation.id,
                project_id: "local-project",
                plan_version_id: &reviewed.id,
                expected_plan_version: reviewed.version,
                idempotency_key: "stale-plan-approval",
                message_id: "stale-plan-message",
                request_message: "Execute reviewed plan",
                environment: None,
                requested_environment_kind: DesktopExecutionEnvironmentKind::Local,
                permission_profile: DesktopPermissionProfile::ReadOnly,
                now: &now_iso(),
            })
            .expect_err("stale preview must be rejected");

        assert!(matches!(error, DesktopAuthorityError::PlanVersionMismatch));
        assert!(store.list_runs(&conversation.id).unwrap().is_empty());
        assert_eq!(
            store
                .conversation(&conversation.id)
                .unwrap()
                .expect("conversation")
                .current_mode,
            ConversationRunMode::Plan
        );
    }

    #[test]
    fn recovery_marks_inflight_mutation_unknown_and_blocks_automatic_resume() {
        use tool_authority::{
            canonical_json_digest, InvocationStatus, PermissionGrant, ToolInvocationRequest,
        };

        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: "conversation-unknown-tool".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Unknown tool recovery".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "unknown-tool-task",
                    "conversation_id": conversation.id,
                    "content": "Execute one mutation",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let plan = store
            .latest_draft_plan(&conversation.id)
            .expect("load plan")
            .expect("plan");
        let approved_at = now_iso();
        let approved = store
            .approve_plan_and_start_in_environment(session_store::ApprovePlanStartInput {
                conversation_id: &conversation.id,
                project_id: "local-project",
                plan_version_id: &plan.id,
                expected_plan_version: plan.version,
                idempotency_key: "unknown-tool-approval",
                message_id: "unknown-tool-message",
                request_message: "Run mutation",
                environment: Some(authority_store::DesktopExecutionEnvironment {
                    id: "unknown-tool-environment".to_string(),
                    kind: DesktopExecutionEnvironmentKind::Local,
                    label: "Unknown tool environment".to_string(),
                    workspace_path: std::env::temp_dir().to_string_lossy().into_owned(),
                    repository_root: None,
                    branch: None,
                    base_commit: None,
                    source_run_id: None,
                    created_at: approved_at.clone(),
                }),
                requested_environment_kind: DesktopExecutionEnvironmentKind::Local,
                permission_profile: DesktopPermissionProfile::WorkspaceWrite,
                now: &approved_at,
            })
            .expect("approve run");
        let running = store
            .prepare_run_for_execution(&approved.run.id, &now_iso())
            .expect("prepare run")
            .expect("running run");
        let input = json!({ "path": "src/lib.rs", "content": "changed" });
        let request = ToolInvocationRequest {
            run_id: running.id.clone(),
            plan_version_id: running.plan_version_id.clone(),
            run_revision: running.revision,
            environment_id: "unknown-tool-environment".to_string(),
            tool_name: "write".to_string(),
            target: json!({ "input_digest": canonical_json_digest(&input).expect("digest") }),
            input,
        };
        let now_ms = Utc::now().timestamp_millis();
        let input_digest = request.input_digest().expect("input digest");
        let grant = PermissionGrant {
            grant_id: "unknown-tool-grant".to_string(),
            run_id: running.id.clone(),
            plan_version_id: running.plan_version_id.clone(),
            run_revision: running.revision,
            environment_id: "unknown-tool-environment".to_string(),
            tool_name: "write".to_string(),
            target: request.target.clone(),
            input_digest,
            use_limit: 1,
            uses: 0,
            expires_at_ms: now_ms + 60_000,
        };
        let metadata = authorized_tool_host::tool_metadata("write").expect("metadata");
        store
            .authorize_and_prepare_tool_invocation(
                "unknown-tool-invocation",
                &request,
                &metadata,
                Some(grant),
                "test",
                now_ms,
            )
            .expect("prepare invocation");
        store
            .transition_tool_invocation(
                "unknown-tool-invocation",
                InvocationStatus::Executing,
                now_ms + 1,
            )
            .expect("start invocation");
        {
            let connection = store.connection().expect("connection");
            session_store::recover_inflight_tool_invocations(&connection, now_ms + 2)
                .expect("recover invocation");
        }
        let disconnected = store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::Disconnected,
                None,
                &now_iso(),
            )
            .expect("disconnect run");
        let blocked = store
            .prepare_run_for_execution(&disconnected.id, &now_iso())
            .expect("prepare recovery")
            .expect("blocked run");

        assert_eq!(blocked.status, DesktopRunStatus::NeedsInput);
        assert_eq!(
            blocked.error.as_deref(),
            Some("unknown tool outcome requires human inspection")
        );
        assert_eq!(
            store
                .list_tool_invocations(&conversation.id)
                .expect("invocations")[0]
                .status,
            InvocationStatus::UnknownOutcome
        );
    }

    #[test]
    fn reopening_marks_an_inflight_run_disconnected_and_reattachable() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create test root");
        let path = root.join("recoverable-runs.db");
        let conversation = LocalConversation {
            id: "conversation-recovery".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Recover run".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Unavailable,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        let run_id = {
            let store = DesktopSessionStore::open(&path).expect("open store");
            store
                .insert_conversation(&conversation)
                .expect("insert conversation");
            store
                .replace_agent_plan_tasks(
                    &conversation.id,
                    &[json!({
                        "id": "recovery-task",
                        "conversation_id": conversation.id,
                        "content": "Recover this run",
                        "status": "pending",
                        "priority": "high",
                        "order_index": 0,
                        "created_at": now_iso(),
                        "updated_at": now_iso(),
                    })],
                )
                .expect("store plan");
            let outcome = store
                .approve_plan_and_start(
                    &conversation.id,
                    "local-project",
                    "recovery-key",
                    "recovery-message",
                    "Execute recoverably",
                    &now_iso(),
                )
                .expect("approve plan");
            store
                .prepare_run_for_execution(&outcome.run.id, &now_iso())
                .expect("prepare run")
                .expect("queued run");
            outcome.run.id
        };

        let restored = DesktopSessionStore::open(&path).expect("reopen store");
        let disconnected = restored.run(&run_id).unwrap().expect("restored run");
        assert_eq!(disconnected.status, DesktopRunStatus::Disconnected);
        assert_eq!(disconnected.revision, 3);
        let retry = restored
            .prepare_run_for_execution(&run_id, &now_iso())
            .expect("retry run")
            .expect("disconnected run is reattachable");
        assert_eq!(retry.status, DesktopRunStatus::Running);
        assert_eq!(retry.revision, 4);
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[test]
    fn recovery_fork_preserves_the_source_run_and_is_idempotent() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: "conversation-recovery-fork".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Fork recovery".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "recovery-fork-task",
                    "conversation_id": conversation.id,
                    "content": "Recover in an isolated worktree",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let reviewed_plan = store
            .latest_draft_plan(&conversation.id)
            .expect("load reviewed plan")
            .expect("reviewed plan");
        let source_environment = authority_store::DesktopExecutionEnvironment {
            id: "environment-source".to_string(),
            kind: DesktopExecutionEnvironmentKind::Worktree,
            label: "Worktree · agistack/source".to_string(),
            workspace_path: "/tmp/agistack-source-worktree".to_string(),
            repository_root: Some("/tmp/agistack-source".to_string()),
            branch: Some("agistack/source".to_string()),
            base_commit: Some("source-base".to_string()),
            source_run_id: None,
            created_at: now_iso(),
        };
        let approval_time = now_iso();
        let approved = store
            .approve_plan_and_start_in_environment(session_store::ApprovePlanStartInput {
                conversation_id: &conversation.id,
                project_id: "local-project",
                plan_version_id: &reviewed_plan.id,
                expected_plan_version: reviewed_plan.version,
                idempotency_key: "source-approval",
                message_id: "source-message",
                request_message: "Execute recoverably",
                environment: Some(source_environment),
                requested_environment_kind: DesktopExecutionEnvironmentKind::Worktree,
                permission_profile: DesktopPermissionProfile::WorkspaceWrite,
                now: &approval_time,
            })
            .expect("approve source run");
        let running = store
            .prepare_run_for_execution(&approved.run.id, &now_iso())
            .expect("prepare source run")
            .expect("running source run");
        let disconnected = store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::Disconnected,
                None,
                &now_iso(),
            )
            .expect("disconnect source run");
        let fork_environment = authority_store::DesktopExecutionEnvironment {
            id: "environment-fork".to_string(),
            kind: DesktopExecutionEnvironmentKind::Worktree,
            label: "Worktree · agistack/fork".to_string(),
            workspace_path: "/tmp/agistack-fork-worktree".to_string(),
            repository_root: Some("/tmp/agistack-source".to_string()),
            branch: Some("agistack/fork".to_string()),
            base_commit: Some("fork-base".to_string()),
            source_run_id: Some(disconnected.id.clone()),
            created_at: now_iso(),
        };
        let (forked, created) = store
            .fork_recovery_run(
                &disconnected.id,
                disconnected.revision,
                "fork-recovery-key",
                fork_environment.clone(),
                &now_iso(),
            )
            .expect("fork recovery");
        assert!(created);
        assert_ne!(forked.id, disconnected.id);
        assert_eq!(forked.status, DesktopRunStatus::Queued);
        assert_eq!(forked.environment, Some(fork_environment));
        assert_eq!(
            forked.authorization_snapshot["source_run_id"],
            disconnected.id
        );
        assert_eq!(
            store.run(&disconnected.id).unwrap().unwrap().status,
            DesktopRunStatus::Disconnected
        );

        let (replayed, created) = store
            .fork_recovery_run(
                &disconnected.id,
                disconnected.revision,
                "fork-recovery-key",
                authority_store::DesktopExecutionEnvironment {
                    id: "unused-environment".to_string(),
                    kind: DesktopExecutionEnvironmentKind::Worktree,
                    label: "Unused".to_string(),
                    workspace_path: "/tmp/unused".to_string(),
                    repository_root: None,
                    branch: None,
                    base_commit: None,
                    source_run_id: Some(disconnected.id.clone()),
                    created_at: now_iso(),
                },
                &now_iso(),
            )
            .expect("replay recovery fork");
        assert!(!created);
        assert_eq!(replayed.id, forked.id);
    }

    #[tokio::test]
    async fn authoritative_run_publishes_monotonic_status_and_finishes() {
        let state = test_state("launch-secret");
        let conversation = LocalConversation {
            id: "conversation-live-run".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Live status".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Unavailable,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "live-run-task",
                    "conversation_id": conversation.id,
                    "content": "Publish status",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let outcome = state
            .session_store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                "live-run-key",
                "live-run-message",
                "Execute live run",
                &now_iso(),
            )
            .expect("approve plan");

        Arc::clone(&state)
            .run_agent_message(
                conversation.id.clone(),
                "local-project".to_string(),
                "Execute live run".to_string(),
                "live-run-message".to_string(),
                Some(outcome.run.id.clone()),
                None,
            )
            .await;

        let run = state
            .session_store
            .run(&outcome.run.id)
            .unwrap()
            .expect("finished run");
        assert_eq!(run.status, DesktopRunStatus::ReadyReview);
        assert_eq!(run.revision, 3);
        let timeline = state
            .session_store
            .timeline(&conversation.id, 100)
            .expect("timeline");
        let status_revisions = timeline
            .iter()
            .filter(|event| event["type"] == "run_status")
            .filter_map(|event| event["payload"]["revision"].as_u64())
            .collect::<Vec<_>>();
        assert_eq!(status_revisions, vec![2, 3]);
        let final_status = timeline
            .iter()
            .rev()
            .find(|event| event["type"] == "run_status")
            .expect("final run status");
        assert_eq!(final_status["payload"]["source"], "local_agent_runtime");
        assert_eq!(final_status["payload"]["execution_id"], run.id);
        assert_eq!(final_status["payload"]["timestamp"], run.updated_at);
    }

    #[test]
    fn core_session_outcomes_preserve_attention_and_review_boundaries() {
        let mut state = agistack_core::agent::types::SessionState::new(
            "session-outcome",
            "Verify authoritative outcomes",
            Some("local-project"),
        );

        state.status = SessionStatus::AwaitingInput;
        state.pending_hitl = Some(agistack_core::agent::types::HitlRequest::new(
            "permission-1",
            agistack_core::agent::types::HitlKind::Permission,
            "Allow this write?",
        ));
        assert_eq!(
            desktop_run_outcome(&state),
            (DesktopRunStatus::NeedsApproval, None)
        );

        state.pending_hitl = Some(agistack_core::agent::types::HitlRequest::new(
            "clarification-1",
            agistack_core::agent::types::HitlKind::Clarification,
            "Which workspace?",
        ));
        assert_eq!(
            desktop_run_outcome(&state),
            (DesktopRunStatus::NeedsInput, None)
        );

        state.pending_hitl = None;
        state.status = SessionStatus::Paused;
        assert_eq!(
            desktop_run_outcome(&state),
            (DesktopRunStatus::Paused, None)
        );

        state.status = SessionStatus::Cancelled;
        assert_eq!(
            desktop_run_outcome(&state),
            (DesktopRunStatus::Cancelled, None)
        );

        state.status = SessionStatus::Finished;
        assert_eq!(
            desktop_run_outcome(&state),
            (DesktopRunStatus::ReadyReview, None)
        );

        state.status = SessionStatus::Failed;
        state.transcript.push(TranscriptEntry::new(
            state.round,
            Role::Answer,
            "round budget exhausted",
        ));
        assert_eq!(
            desktop_run_outcome(&state),
            (
                DesktopRunStatus::Failed,
                Some("round budget exhausted".to_string())
            )
        );
    }

    #[test]
    fn run_transition_is_revision_guarded_and_nonterminal_attention_stays_resumable() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: "conversation-needs-input".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Needs input".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "needs-input-task",
                    "conversation_id": conversation.id,
                    "content": "Wait for a decision",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let outcome = store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                "needs-input-key",
                "needs-input-message",
                "Execute with approval",
                &now_iso(),
            )
            .expect("approve plan");
        let running = store
            .prepare_run_for_execution(&outcome.run.id, &now_iso())
            .expect("prepare run")
            .expect("queued run");

        let needs_input = store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::NeedsInput,
                None,
                &now_iso(),
            )
            .expect("transition to needs input");
        assert_eq!(needs_input.status, DesktopRunStatus::NeedsInput);
        assert_eq!(needs_input.revision, running.revision + 1);
        assert!(needs_input.completed_at.is_none());

        let stale = store.transition_run(
            &running.id,
            running.revision,
            DesktopRunStatus::Failed,
            Some("stale writer".to_string()),
            &now_iso(),
        );
        assert!(stale
            .expect_err("stale revision must fail")
            .contains("revision conflict"));
    }

    #[test]
    fn run_transition_supports_pause_resume_cancel_and_review_completion() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: "conversation-control".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Controlled run".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "control-task",
                    "conversation_id": conversation.id,
                    "content": "Control this run",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let outcome = store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                "control-key",
                "control-message",
                "Execute with controls",
                &now_iso(),
            )
            .expect("approve plan");
        let running = store
            .prepare_run_for_execution(&outcome.run.id, &now_iso())
            .expect("prepare run")
            .expect("running run");
        let paused = store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::Paused,
                None,
                &now_iso(),
            )
            .expect("pause run");
        assert!(paused.completed_at.is_none());
        let resumed = store
            .transition_run(
                &paused.id,
                paused.revision,
                DesktopRunStatus::Running,
                None,
                &now_iso(),
            )
            .expect("resume run");
        let review = store
            .transition_run(
                &resumed.id,
                resumed.revision,
                DesktopRunStatus::ReadyReview,
                None,
                &now_iso(),
            )
            .expect("reach review");
        let completed = store
            .transition_run(
                &review.id,
                review.revision,
                DesktopRunStatus::Completed,
                None,
                &now_iso(),
            )
            .expect("complete review");
        assert!(completed.completed_at.is_some());

        let second = store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                "control-key",
                "control-message",
                "Execute with controls",
                &now_iso(),
            )
            .expect("load existing run");
        assert_eq!(second.run.status, DesktopRunStatus::Completed);
    }

    #[test]
    fn artifact_versions_preserve_history_and_require_approval_before_delivery() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: "conversation-artifacts".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Artifact review".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Build,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        let first = store
            .record_artifact_version(
                &conversation.id,
                None,
                &json!({
                    "artifact_id": "release-notes",
                    "artifact_version_id": "release-notes-v1",
                    "filename": "release-notes.md",
                    "path": "/tmp/release-notes-v1.md",
                    "relative_path": ".agistack/artifacts/release-notes/v1/release-notes.md",
                    "bytes": 12,
                    "sources": [{ "kind": "file", "id": "README.md", "label": "README" }],
                    "checks": [{ "kind": "test", "id": "docs-lint", "status": "passed" }]
                }),
                &now_iso(),
            )
            .expect("first artifact version");
        let second = store
            .record_artifact_version(
                &conversation.id,
                None,
                &json!({
                    "artifact_id": "release-notes",
                    "artifact_version_id": "release-notes-v2",
                    "filename": "release-notes.md",
                    "path": "/tmp/release-notes-v2.md",
                    "relative_path": ".agistack/artifacts/release-notes/v2/release-notes.md",
                    "bytes": 18,
                    "sources": [],
                    "checks": []
                }),
                &now_iso(),
            )
            .expect("second artifact version");

        let superseded = store
            .artifact_version(&first.id)
            .expect("load first")
            .expect("first version");
        assert_eq!(superseded.status, DesktopArtifactStatus::Superseded);
        assert_eq!(second.version, 2);
        assert_eq!(second.status, DesktopArtifactStatus::Ready);
        assert_eq!(
            store
                .list_artifact_versions(&conversation.id)
                .unwrap()
                .len(),
            2
        );

        let delivery_before_approval = store.deliver_artifact_version(
            &second.id,
            second.revision,
            "deliver-before-approval",
            "local_workspace",
            json!({ "path": second.path }),
            &now_iso(),
        );
        assert!(delivery_before_approval
            .expect_err("delivery must require approval")
            .contains("approved artifact"));

        let approved = store
            .review_artifact_version(&second.id, second.revision, "approve", None, &now_iso())
            .expect("approve version");
        assert_eq!(approved.status, DesktopArtifactStatus::Approved);
        let (delivered, receipt) = store
            .deliver_artifact_version(
                &approved.id,
                approved.revision,
                "deliver-approved-version",
                "local_workspace",
                json!({ "path": approved.path }),
                &now_iso(),
            )
            .expect("deliver approved version");
        assert_eq!(delivered.status, DesktopArtifactStatus::Delivered);
        assert_eq!(receipt.artifact_version_id, approved.id);
        let replay = store
            .deliver_artifact_version(
                &approved.id,
                approved.revision,
                "deliver-approved-version",
                "local_workspace",
                json!({ "path": approved.path }),
                &now_iso(),
            )
            .expect("idempotent delivery replay");
        assert_eq!(replay.1.id, receipt.id);
    }

    #[test]
    fn artifact_change_request_updates_artifact_and_run_atomically() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: "conversation-artifact-changes".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Artifact changes".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Build,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "artifact-change-task",
                    "conversation_id": conversation.id,
                    "content": "Revise the artifact",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let approved = store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                "artifact-change-key",
                "artifact-change-message",
                "Create the artifact",
                &now_iso(),
            )
            .expect("approve plan");
        let running = store
            .prepare_run_for_execution(&approved.run.id, &now_iso())
            .expect("prepare run")
            .expect("running run");
        let ready = store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::ReadyReview,
                None,
                &now_iso(),
            )
            .expect("ready review");
        let artifact = store
            .record_artifact_version(
                &conversation.id,
                Some(&ready.id),
                &json!({
                    "artifact_id": "review-report",
                    "artifact_version_id": "review-report-v1",
                    "filename": "review-report.md",
                    "path": "/tmp/review-report-v1.md",
                    "relative_path": ".agistack/artifacts/review-report/v1/review-report.md",
                    "bytes": 32,
                    "sources": [],
                    "checks": []
                }),
                &now_iso(),
            )
            .expect("record artifact");

        let stale = store.request_artifact_changes_and_resume_run(
            &artifact.id,
            artifact.revision + 1,
            &ready.id,
            ready.revision,
            "Add verification evidence",
            &now_iso(),
        );
        assert!(stale
            .expect_err("stale artifact revision must fail")
            .contains("artifact revision conflict"));
        assert_eq!(
            store.run(&ready.id).unwrap().unwrap().status,
            DesktopRunStatus::ReadyReview
        );
        assert_eq!(
            store
                .artifact_version(&artifact.id)
                .unwrap()
                .unwrap()
                .status,
            DesktopArtifactStatus::Ready
        );

        let (reviewed, resumed, decision) = store
            .request_artifact_changes_and_resume_run(
                &artifact.id,
                artifact.revision,
                &ready.id,
                ready.revision,
                "Add verification evidence",
                &now_iso(),
            )
            .expect("request artifact changes");
        assert_eq!(reviewed.status, DesktopArtifactStatus::Superseded);
        assert_eq!(
            reviewed.feedback.as_deref(),
            Some("Add verification evidence")
        );
        assert_eq!(resumed.status, DesktopRunStatus::Running);
        assert_eq!(decision["run_id"], resumed.id);
        assert_eq!(decision["artifact_version_id"], reviewed.id);
        assert_eq!(decision["decision"], "request_changes");
    }

    #[tokio::test]
    async fn artifact_api_persists_review_and_records_delivery_only_when_the_file_exists() {
        let state = test_state("artifact-secret");
        let conversation = LocalConversation {
            id: "conversation-artifact-api".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Artifact API".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Build,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        let artifact_path = state
            .workspace_root
            .lock()
            .expect("workspace root")
            .join(".agistack/artifacts/report/v1/report.md");
        let version = state
            .session_store
            .record_artifact_version(
                &conversation.id,
                None,
                &json!({
                    "artifact_id": "report",
                    "artifact_version_id": "report-version-api",
                    "filename": "report.md",
                    "path": artifact_path,
                    "relative_path": ".agistack/artifacts/report/v1/report.md",
                    "bytes": 14,
                    "sources": [],
                    "checks": []
                }),
                &now_iso(),
            )
            .expect("artifact version");

        let messages = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{}/messages",
                        conversation.id
                    ))
                    .header("authorization", "Bearer artifact-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("messages response");
        assert_eq!(messages.status(), StatusCode::OK);
        let body = axum::body::to_bytes(messages.into_body(), usize::MAX)
            .await
            .expect("messages body");
        let payload: Value = serde_json::from_slice(&body).expect("messages json");
        assert_eq!(payload["artifact_versions"][0]["id"], version.id);
        assert_eq!(
            payload["artifact_deliveries"].as_array().map(Vec::len),
            Some(0)
        );

        let approve = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!(
                        "/api/v1/agent/artifact-versions/{}/review",
                        version.id
                    ))
                    .header("authorization", "Bearer artifact-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({ "action": "approve", "expected_revision": version.revision })
                            .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("approve response");
        assert_eq!(approve.status(), StatusCode::OK);
        let approved = state
            .session_store
            .artifact_version(&version.id)
            .expect("load version")
            .expect("approved version");
        assert_eq!(approved.status, DesktopArtifactStatus::Approved);

        let deliver_body = json!({
            "expected_revision": approved.revision,
            "idempotency_key": "report-version-api:deliver",
            "destination": "local_workspace",
        })
        .to_string();
        let unavailable = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!(
                        "/api/v1/agent/artifact-versions/{}/deliver",
                        approved.id
                    ))
                    .header("authorization", "Bearer artifact-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(deliver_body.clone()))
                    .expect("request"),
            )
            .await
            .expect("missing file response");
        assert_eq!(unavailable.status(), StatusCode::CONFLICT);
        assert_eq!(
            state
                .session_store
                .artifact_version(&approved.id)
                .unwrap()
                .unwrap()
                .status,
            DesktopArtifactStatus::Approved
        );

        std::fs::create_dir_all(artifact_path.parent().expect("artifact directory"))
            .expect("create artifact directory");
        std::fs::write(&artifact_path, "reviewed report").expect("write artifact");
        let delivered = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!(
                        "/api/v1/agent/artifact-versions/{}/deliver",
                        approved.id
                    ))
                    .header("authorization", "Bearer artifact-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(deliver_body.clone()))
                    .expect("request"),
            )
            .await
            .expect("delivery response");
        assert_eq!(delivered.status(), StatusCode::OK);
        let replay = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!(
                        "/api/v1/agent/artifact-versions/{}/deliver",
                        approved.id
                    ))
                    .header("authorization", "Bearer artifact-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(deliver_body))
                    .expect("request"),
            )
            .await
            .expect("delivery replay");
        assert_eq!(replay.status(), StatusCode::OK);
        assert_eq!(
            state
                .session_store
                .list_artifact_deliveries(&conversation.id)
                .unwrap()
                .len(),
            1
        );
    }

    #[tokio::test]
    async fn hitl_response_resumes_authoritative_run_and_preserves_status_boundaries() {
        let state = test_state("launch-secret");
        let conversation = LocalConversation {
            id: "conversation-hitl".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Approval required".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "hitl-task",
                    "conversation_id": conversation.id,
                    "content": "Wait for permission",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let outcome = state
            .session_store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                "hitl-key",
                "hitl-message",
                "Execute after approval",
                &now_iso(),
            )
            .expect("approve plan");
        let running = state
            .session_store
            .prepare_run_for_execution(&outcome.run.id, &now_iso())
            .expect("prepare run")
            .expect("running run");
        let mut suspended = SessionState::new(
            conversation.id.clone(),
            "Execute after approval",
            Some("local-project"),
        );
        suspended.status = SessionStatus::AwaitingInput;
        suspended.pending_hitl = Some(
            agistack_core::agent::types::HitlRequest::new(
                "permission-hitl",
                HitlKind::Permission,
                "Allow the approved change?",
            )
            .with_decision(test_decision_context()),
        );
        state
            .checkpoints
            .save(&suspended)
            .await
            .expect("save checkpoint");
        state
            .persist_pending_hitl(&conversation.id, Some(&running.id), &suspended)
            .expect("persist pending HITL");
        let needs_approval = state
            .session_store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::NeedsApproval,
                None,
                &now_iso(),
            )
            .expect("needs approval");
        state.publish_run_status(&needs_approval);

        let messages = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{}/messages",
                        conversation.id
                    ))
                    .header("authorization", "Bearer launch-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(messages.status(), StatusCode::OK);
        let messages_body = axum::body::to_bytes(messages.into_body(), usize::MAX)
            .await
            .expect("messages body");
        let messages_payload: Value =
            serde_json::from_slice(&messages_body).expect("messages json");
        assert_eq!(
            messages_payload["approval_requests"][0]["id"],
            "permission-hitl"
        );
        assert_eq!(
            messages_payload["approval_requests"][0]["run_revision"],
            needs_approval.revision
        );
        assert_eq!(
            messages_payload["approval_requests"][0]["decision"]["risk"]["level"],
            "medium"
        );

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/hitl/respond")
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "request_id": "permission-hitl",
                            "hitl_type": "permission",
                            "response_data": { "granted": true },
                            "expected_revision": needs_approval.revision,
                            "idempotency_key": "permission-hitl:approve",
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);

        let mut final_run = None;
        for _ in 0..100 {
            let run = state
                .session_store
                .run(&running.id)
                .expect("load run")
                .expect("run");
            if run.status == DesktopRunStatus::ReadyReview {
                final_run = Some(run);
                break;
            }
            tokio::task::yield_now().await;
        }
        let final_run = final_run.expect("resumed run reaches review boundary");
        assert_eq!(final_run.revision, needs_approval.revision + 2);
        assert!(final_run.completed_at.is_none());
        let saved = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint")
            .expect("checkpoint");
        assert_eq!(saved.hitl_answer("permission-hitl"), Some("approved"));
        let request = state
            .session_store
            .hitl_request("permission-hitl")
            .expect("load HITL")
            .expect("HITL");
        assert_eq!(request.status, DesktopHitlStatus::Responded);
        assert_eq!(request.response_data, Some(json!({ "granted": true })));
        assert_eq!(request.response_actor.as_deref(), Some("local_user"));
        assert_eq!(request.response_revision, Some(needs_approval.revision + 1));
        assert_eq!(
            request.idempotency_key.as_deref(),
            Some("permission-hitl:approve")
        );

        let replay = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/hitl/respond")
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "request_id": "permission-hitl",
                            "hitl_type": "permission",
                            "response_data": { "granted": true },
                            "expected_revision": needs_approval.revision,
                            "idempotency_key": "permission-hitl:approve",
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(replay.status(), StatusCode::OK);

        let conflicting_replay = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/hitl/respond")
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "request_id": "permission-hitl",
                            "hitl_type": "permission",
                            "response_data": { "granted": false },
                            "idempotency_key": "permission-hitl:deny",
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(conflicting_replay.status(), StatusCode::CONFLICT);
    }

    #[tokio::test]
    async fn env_var_hitl_rejects_plaintext_without_mutating_checkpoint() {
        let state = test_state("launch-secret");
        let conversation = LocalConversation {
            id: "conversation-env-hitl".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Secret required".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Work,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        let mut suspended = SessionState::new(
            conversation.id.clone(),
            "Use a protected token",
            Some("local-project"),
        );
        suspended.status = SessionStatus::AwaitingInput;
        suspended.pending_hitl = Some(agistack_core::agent::types::HitlRequest::new(
            "env-hitl",
            HitlKind::EnvVar,
            "Provide API_TOKEN",
        ));
        state
            .checkpoints
            .save(&suspended)
            .await
            .expect("save checkpoint");
        state
            .persist_pending_hitl(&conversation.id, None, &suspended)
            .expect("persist pending HITL");

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/agent/hitl/respond")
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"request_id":"env-hitl","hitl_type":"env_var","response_data":{"value":"must-not-persist"}}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::NOT_IMPLEMENTED);
        let saved = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint")
            .expect("checkpoint");
        assert_eq!(saved, suspended);
        let request = state
            .session_store
            .hitl_request("env-hitl")
            .expect("load HITL")
            .expect("HITL");
        assert_eq!(request.status, DesktopHitlStatus::Pending);
        assert!(!serde_json::to_string(&request)
            .expect("serialize request")
            .contains("must-not-persist"));
    }

    fn seed_controlled_run(
        state: &Arc<LocalRuntimeState>,
        suffix: &str,
    ) -> (LocalConversation, DesktopRun) {
        let conversation = LocalConversation {
            id: format!("conversation-control-{suffix}"),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Controlled run".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": format!("control-task-{suffix}"),
                    "conversation_id": conversation.id,
                    "content": "Control the run",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let outcome = state
            .session_store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                &format!("control-key-{suffix}"),
                &format!("control-message-{suffix}"),
                "Execute under human control",
                &now_iso(),
            )
            .expect("approve plan");
        let running = state
            .session_store
            .prepare_run_for_execution(&outcome.run.id, &now_iso())
            .expect("prepare run")
            .expect("running run");
        (conversation, running)
    }

    #[tokio::test]
    async fn review_approval_completes_the_same_authoritative_run() {
        let state = test_state("launch-secret");
        let (_conversation, running) = seed_controlled_run(&state, "approve-review");
        let ready = state
            .session_store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::ReadyReview,
                None,
                &now_iso(),
            )
            .expect("ready review");

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/review", ready.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"action":"approve","expected_revision":{}}}"#,
                        ready.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let completed = state
            .session_store
            .run(&ready.id)
            .expect("load run")
            .expect("run");
        assert_eq!(completed.status, DesktopRunStatus::Completed);
        assert_eq!(completed.id, ready.id);
        assert_eq!(completed.revision, ready.revision + 1);
    }

    #[tokio::test]
    async fn paused_run_can_cancel_without_restarting_execution() {
        let state = test_state("launch-secret");
        let (conversation, running) = seed_controlled_run(&state, "cancel-paused");
        let paused = state
            .session_store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::Paused,
                None,
                &now_iso(),
            )
            .expect("pause run");
        let mut checkpoint = SessionState::new(
            conversation.id,
            "Execute under human control",
            Some("local-project"),
        );
        checkpoint.status = SessionStatus::Paused;
        state
            .checkpoints
            .save(&checkpoint)
            .await
            .expect("save paused checkpoint");

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/cancel", paused.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        paused.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let cancelled = state
            .session_store
            .run(&paused.id)
            .expect("load run")
            .expect("run");
        assert_eq!(cancelled.status, DesktopRunStatus::Cancelled);
        assert!(cancelled.completed_at.is_some());
    }

    #[tokio::test]
    async fn pause_rejects_a_running_record_without_an_attached_execution() {
        let state = test_state("launch-secret");
        let (_conversation, running) = seed_controlled_run(&state, "pause-detached");
        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/pause", running.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        running.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::CONFLICT);
        let stored = state
            .session_store
            .run(&running.id)
            .expect("load run")
            .expect("run");
        assert_eq!(stored.status, DesktopRunStatus::Running);
        assert_eq!(stored.revision, running.revision);
    }

    #[tokio::test]
    async fn steer_now_persists_before_ack_and_applies_without_advancing_run_revision() {
        let state = test_state("launch-secret");
        let (conversation, running) = seed_controlled_run(&state, "steer-now");
        let control = state
            .claim_agent_run(&conversation.id, Some(&running.id))
            .expect("attach execution");
        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/inputs", running.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "expected_run_revision": running.revision,
                            "message": "Keep the public API stable",
                            "message_id": "steer-now-message",
                            "idempotency_key": "steer-now-key",
                            "delivery": "steer_now",
                            "references": [],
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["delivery_mode"], "steer_now");
        assert_eq!(payload["input"]["status"], "pending_boundary");
        assert_eq!(payload["run_revision"], running.revision);
        let directive = control
            .directive(&conversation.id, 4)
            .await
            .expect("steering directive");
        let RunDirective::Steer(instruction) = directive else {
            panic!("expected steering directive");
        };
        assert_eq!(instruction.content, "Keep the public API stable");
        control
            .acknowledge_steering(&conversation.id, &instruction.id, 4)
            .await
            .expect("acknowledge steering");
        let inputs = state
            .session_store
            .list_run_inputs(&running.id)
            .expect("list inputs");
        assert_eq!(inputs[0].status, steering::RunInputStatus::Applied);
        assert_eq!(inputs[0].applied_round, Some(4));
        let stored = state
            .session_store
            .run(&running.id)
            .expect("load run")
            .expect("run");
        assert_eq!(stored.revision, running.revision);
        state.release_agent_run(&conversation.id);
    }

    #[tokio::test]
    async fn queue_next_waits_through_review_then_promotes_once_to_a_plan_turn() {
        let state = test_state("launch-secret");
        let (conversation, running) = seed_controlled_run(&state, "queue-next");
        let control = state
            .claim_agent_run(&conversation.id, Some(&running.id))
            .expect("attach execution");
        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/inputs", running.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "expected_run_revision": running.revision,
                            "message": "Run the compatibility matrix next",
                            "message_id": "queue-next-message",
                            "idempotency_key": "queue-next-key",
                            "delivery": "queue_next",
                            "references": [],
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["delivery_mode"], "queue_next");
        assert_eq!(payload["queue_position"], 1);
        assert_eq!(
            control
                .directive(&conversation.id, 0)
                .await
                .expect("control directive"),
            RunDirective::Continue
        );
        let ready = state
            .session_store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::ReadyReview,
                None,
                &now_iso(),
            )
            .expect("review boundary");
        state
            .session_store
            .settle_queued_run_inputs(&ready.id, ready.status, &ready.updated_at)
            .expect("settle queue");
        let reviewing_inputs = state
            .session_store
            .list_run_inputs(&running.id)
            .expect("list inputs");
        assert_eq!(reviewing_inputs[0].status, steering::RunInputStatus::Queued);
        let input_id = reviewing_inputs[0].id.clone();
        state.release_agent_run(&conversation.id);
        let premature = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!(
                        "/api/v1/agent/run-inputs/{input_id}/promote-to-plan"
                    ))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "expected_source_run_revision": ready.revision,
                            "idempotency_key": "promote-queue-next",
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(premature.status(), StatusCode::CONFLICT);
        let completed = state
            .session_store
            .transition_run(
                &ready.id,
                ready.revision,
                DesktopRunStatus::Completed,
                None,
                &now_iso(),
            )
            .expect("complete source run");
        state
            .session_store
            .settle_queued_run_inputs(&completed.id, completed.status, &completed.updated_at)
            .expect("settle completed queue");
        let completed_inputs = state
            .session_store
            .list_run_inputs(&running.id)
            .expect("list completed inputs");
        assert_eq!(completed_inputs[0].status, steering::RunInputStatus::Ready);
        assert_eq!(completed_inputs[0].queue_position, Some(1));

        let promote = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!(
                        "/api/v1/agent/run-inputs/{input_id}/promote-to-plan"
                    ))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "expected_source_run_revision": completed.revision,
                            "idempotency_key": "promote-queue-next",
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(promote.status(), StatusCode::OK);
        let body = axum::body::to_bytes(promote.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["created"], true);
        assert_eq!(payload["action"], "start_plan_turn");
        assert_eq!(payload["input"]["status"], "promoted_to_plan");
        assert_eq!(payload["conversation"]["current_mode"], "plan");

        let replay = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!(
                        "/api/v1/agent/run-inputs/{input_id}/promote-to-plan"
                    ))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "expected_source_run_revision": completed.revision,
                            "idempotency_key": "promote-queue-next",
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(replay.status(), StatusCode::OK);
        let body = axum::body::to_bytes(replay.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["created"], false);

        let conflict = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!(
                        "/api/v1/agent/run-inputs/{input_id}/promote-to-plan"
                    ))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "expected_source_run_revision": completed.revision,
                            "idempotency_key": "different-promotion-key",
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(conflict.status(), StatusCode::CONFLICT);
    }

    #[tokio::test]
    async fn pause_route_signals_the_attached_execution_without_faking_run_state() {
        let state = test_state("launch-secret");
        let (conversation, running) = seed_controlled_run(&state, "pause-attached");
        let control = state
            .claim_agent_run(&conversation.id, Some(&running.id))
            .expect("attach execution");
        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/pause", running.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        running.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            control
                .directive(&conversation.id, 0)
                .await
                .expect("control directive"),
            RunDirective::Pause
        );
        let stored = state
            .session_store
            .run(&running.id)
            .expect("load run")
            .expect("run");
        assert_eq!(stored.status, DesktopRunStatus::Running);
        assert_eq!(stored.revision, running.revision);
        state.release_agent_run(&conversation.id);
    }

    #[tokio::test]
    async fn resume_continues_the_same_paused_run_from_its_checkpoint() {
        let state = test_state("launch-secret");
        let (conversation, running) = seed_controlled_run(&state, "resume-paused");
        let paused = state
            .session_store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::Paused,
                None,
                &now_iso(),
            )
            .expect("pause run");
        let mut checkpoint = SessionState::new(
            conversation.id.clone(),
            "Execute under human control",
            Some("local-project"),
        );
        checkpoint.status = SessionStatus::Paused;
        state
            .checkpoints
            .save(&checkpoint)
            .await
            .expect("save paused checkpoint");

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/resume", paused.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        paused.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["run"]["id"], paused.id);
        assert_eq!(payload["run"]["status"], "running");
        assert_eq!(payload["run"]["revision"], paused.revision + 1);

        let mut final_run = None;
        for _ in 0..100 {
            let run = state
                .session_store
                .run(&paused.id)
                .expect("load run")
                .expect("run");
            if run.status == DesktopRunStatus::ReadyReview {
                final_run = Some(run);
                break;
            }
            tokio::task::yield_now().await;
        }
        assert_eq!(final_run.expect("resumed run reaches review").id, paused.id);
    }

    #[tokio::test]
    async fn review_changes_reopens_the_same_run_with_human_feedback() {
        let state = test_state("launch-secret");
        let (conversation, running) = seed_controlled_run(&state, "review-changes");
        let ready = state
            .session_store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::ReadyReview,
                None,
                &now_iso(),
            )
            .expect("ready review");
        let mut checkpoint = SessionState::new(
            conversation.id.clone(),
            "Execute under human control",
            Some("local-project"),
        );
        checkpoint.status = SessionStatus::Finished;
        checkpoint.answer = Some("initial result".to_string());
        state
            .checkpoints
            .save(&checkpoint)
            .await
            .expect("save review checkpoint");

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/review", ready.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"action":"request_changes","expected_revision":{},"feedback":"Add the missing verification evidence"}}"#,
                        ready.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["run"]["id"], ready.id);
        assert_eq!(payload["run"]["status"], "running");

        let saved = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint")
            .expect("checkpoint");
        assert!(saved.transcript.iter().any(|entry| {
            entry.role == Role::Human && entry.content == "Add the missing verification evidence"
        }));
    }

    #[tokio::test]
    async fn terminal_grant_is_single_use_and_rechecks_authoritative_run_identity() {
        let state = test_state("launch-secret");
        let conversation = LocalConversation {
            id: "conversation-terminal-environment".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Run-scoped terminal".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "terminal-environment-task",
                    "conversation_id": conversation.id,
                    "content": "Open a terminal in the approved environment",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let reviewed_plan = state
            .session_store
            .latest_draft_plan(&conversation.id)
            .expect("load reviewed plan")
            .expect("reviewed plan");
        let approved_at = now_iso();
        let prepared = state
            .worktree_manager()
            .prepare(
                DesktopExecutionEnvironmentKind::Local,
                "terminal-environment",
                &approved_at,
            )
            .expect("prepare environment");
        let expected_cwd = prepared.environment.workspace_path.clone();
        let approved = state
            .session_store
            .approve_plan_and_start_in_environment(session_store::ApprovePlanStartInput {
                conversation_id: &conversation.id,
                project_id: "local-project",
                plan_version_id: &reviewed_plan.id,
                expected_plan_version: reviewed_plan.version,
                idempotency_key: "terminal-environment-approval",
                message_id: "terminal-environment-message",
                request_message: "Run in the approved environment",
                environment: Some(prepared.environment),
                requested_environment_kind: DesktopExecutionEnvironmentKind::Local,
                permission_profile: DesktopPermissionProfile::FullAccess,
                now: &approved_at,
            })
            .expect("approve run");
        let running = state
            .session_store
            .prepare_run_for_execution(&approved.run.id, &now_iso())
            .expect("prepare run")
            .expect("running run");

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/projects/local-project/sandbox/terminal")
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"run_id":"{}","expected_run_revision":{}}}"#,
                        running.id, running.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let payload: Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["run_id"], approved.run.id);
        assert_eq!(payload["run_revision"], running.revision);
        assert_eq!(payload["conversation_id"], conversation.id);
        assert_eq!(payload["project_id"], "local-project");
        assert_eq!(payload["cwd"], expected_cwd);
        assert_eq!(payload["environment"]["id"], "terminal-environment");
        assert_eq!(payload["environment_id"], "terminal-environment");
        assert_eq!(payload["resumable"], false);
        let session_id = payload["session_id"].as_str().expect("session id");
        let uuid = session_id
            .strip_prefix("local-terminal-")
            .expect("terminal prefix");
        Uuid::parse_str(uuid).expect("high entropy terminal identifier");
        let lease = state
            .take_terminal_session(session_id)
            .expect("single-use terminal lease");
        assert_eq!(lease.cwd, PathBuf::from(&expected_cwd));
        assert_eq!(lease.run_id, running.id);
        assert_eq!(lease.run_revision, running.revision);
        assert_eq!(lease.environment_id, "terminal-environment");
        assert!(state.take_terminal_session(session_id).is_none());
        assert!(state.take_terminal_session("missing").is_none());

        let authenticated = state
            .session_store
            .validate_session_credential("launch-secret", Utc::now().timestamp_millis())
            .expect("validate session")
            .expect("authenticated context");
        assert!(
            validate_terminal_session_lease(&state, &authenticated, "local-project", &lease,)
                .is_ok()
        );
        let mut expired = lease.clone();
        expired.expires_at = (Utc::now() - ChronoDuration::seconds(1)).to_rfc3339();
        assert_eq!(
            validate_terminal_session_lease(&state, &authenticated, "local-project", &expired,)
                .expect_err("expired attach lease must fail")
                .0,
            StatusCode::CONFLICT,
        );
        assert!(validate_terminal_session_authority(
            &state,
            &authenticated,
            "local-project",
            &expired,
        )
        .is_ok());
        let ready = state
            .session_store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::ReadyReview,
                None,
                &now_iso(),
            )
            .expect("advance source run revision");
        assert_eq!(ready.revision, running.revision + 1);
        let stale =
            validate_terminal_session_lease(&state, &authenticated, "local-project", &lease)
                .expect_err("stale terminal lease must be rejected");
        assert_eq!(stale.0, StatusCode::CONFLICT);
    }

    #[tokio::test]
    async fn mcp_tool_call_rejects_requests_without_an_authoritative_run_scope() {
        let state = test_state("launch-secret");
        let response = local_router(state)
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/mcp/tools/call")
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"name":"read_file","arguments":{"path":"README.md"}}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
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
    async fn unconfigured_runtime_never_fabricates_a_plan() {
        assert_eq!(LocalRuntimeConfig::default().provider, "unconfigured");
        let error = UnconfiguredLocalLlm
            .decide(
                "Implement an ambiguous product objective",
                0,
                &[],
                &[SUBMIT_PLAN_TOOL_NAME.to_string()],
            )
            .await
            .expect_err("an unconfigured model must not invent a plan");
        assert!(error.to_string().contains("model_unconfigured"));
    }

    #[tokio::test]
    async fn sandbox_execute_never_falls_back_to_the_host_shell() {
        let state = test_state("launch-secret");
        let result = sandbox_execute(
            State(Arc::clone(&state)),
            Json(json!({ "command": "touch must-not-exist", "timeout_ms": 5000 })),
        )
        .await;
        let (status, Json(payload)) = result.expect_err("host shell fallback must be disabled");
        assert_eq!(status, StatusCode::NOT_IMPLEMENTED);
        assert!(payload["detail"].as_str().unwrap().contains("disabled"));
        assert!(!state
            .workspace_root
            .lock()
            .unwrap()
            .join("must-not-exist")
            .exists());
    }
}
