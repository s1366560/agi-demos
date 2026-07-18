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
    model::{Episode, Memory},
    ports::{
        CheckpointStore, CoreError, CoreResult, LlmPort, MemoryDraft, RelationshipDraft, ToolHost,
    },
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
    routing::{get, patch, post, put},
    Json, Router,
};
use chrono::{Duration as ChronoDuration, Utc};
use futures_util::{SinkExt, StreamExt};
use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use serde::{de::Visitor, Deserialize, Deserializer, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::{
    net::TcpListener,
    sync::{broadcast, mpsc},
};
use tower_http::cors::{AllowOrigin, CorsLayer};
use url::{Host, Url};
use uuid::Uuid;

#[cfg(test)]
use agistack_core::model::Entity;

mod auth_context;
mod authority_store;
mod authorized_tool_host;
mod changes;
#[cfg(test)]
mod managed_resource_tests;
mod provider_credentials;
mod provider_probe;
mod resource_registry;
#[cfg(test)]
mod routing_policy_tests;
mod run_control;
mod session_projection;
mod session_store;
mod steering;
mod task_session;
mod tool_authority;
mod worktree;

const RECOVERED_CHECKPOINT_AUTHORITY_ERROR: &str =
    "recovered checkpoint authority does not match the current run";
const CHECKPOINT_TERMINALIZATION_RECOVERY_ERROR_PREFIX: &str =
    "authoritative checkpoint terminalization failed; checkpoint quarantined";
const CHECKPOINT_CONTROL_AUTHORITY_ERROR: &str =
    "checkpoint authority does not match the requested run";
const DEFAULT_TIMELINE_LIMIT: i64 = 50;
const MAX_TIMELINE_LIMIT: i64 = 500;

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
#[cfg(test)]
use provider_credentials::ProviderCredentialStore;
use provider_credentials::{
    provider_credential_binding_digest, ProviderCredentialBroker, ProviderCredentialStoreError,
};
use provider_probe::{ProviderProbeOutcome, ProviderProbeRequest, ProviderProbeService};
use resource_registry::{ManagedResourceKind, ResourceRegistryError};
use session_store::{
    DesktopClientTurnClaimError, DesktopSessionStore, DesktopTimelineCursor, DesktopTimelinePage,
};
use steering::{ChangeReferenceSide, RunInputDelivery, RunInputReference, RunInputStatus};
use task_session::{
    workspace_value, WorkspaceCollaborationMode, WorkspaceCreateAttributes, WorkspaceUseCase,
};
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
        let provider_credentials =
            ProviderCredentialBroker::native(session_store.installation_id())
                .map_err(|error| error.to_string())?;
        let state = Arc::new(LocalRuntimeState::new_with_provider_credentials(
            workspace_root,
            tool_host,
            checkpoints,
            api_token,
            session_store,
            provider_credentials,
        )?);
        state.reconcile_recovered_runs_from_checkpoints().await?;

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
        let config = self
            .state
            .config
            .lock()
            .expect("local runtime config")
            .clone();
        let mut runtime_providers = {
            let runtime = self
                .state
                .provider_runtime
                .lock()
                .expect("provider runtime state");
            runtime
                .selections
                .iter()
                .filter_map(|(tenant_id, provider_id)| {
                    let key = ProviderRuntimeKey {
                        tenant_id: tenant_id.clone(),
                        provider_id: provider_id.clone(),
                    };
                    runtime
                        .bindings
                        .get(&key)
                        .map(|binding| RuntimeProviderProjection {
                            tenant_id: tenant_id.clone(),
                            provider_id: provider_id.clone(),
                            provider_type: binding.provider_type.clone(),
                            model: binding.model.clone(),
                            credential_configured: binding.auth_method == "none"
                                || runtime.credentials.contains_key(&key),
                        })
                })
                .collect::<Vec<_>>()
        };
        runtime_providers.sort_by(|left, right| {
            (&left.tenant_id, &left.provider_id).cmp(&(&right.tenant_id, &right.provider_id))
        });
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
            runtime_providers,
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
            config.workspace_root = root.to_string_lossy().to_string();
            *self.workspace_root.lock().expect("local workspace root") = root;
            *self.tool_host.lock().expect("local tool host") = host;
        }
        let mut current = self.config.lock().expect("local runtime config");
        *current = config;
        Ok(())
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalRuntimeConfig {
    #[serde(default)]
    pub workspace_root: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RuntimeProviderProjection {
    pub tenant_id: String,
    pub provider_id: String,
    pub provider_type: String,
    pub model: String,
    pub credential_configured: bool,
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
    pub runtime_providers: Vec<RuntimeProviderProjection>,
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

const LOCAL_DEMO_HIERARCHY_SEED_ID: &str = "northstar-desktop-client-local-demo-v1";
const LOCAL_DEMO_SESSION_CONTENT_SEED_ID: &str =
    "northstar-desktop-client-local-demo-session-content-v1";
const LOCAL_DEMO_DESKTOP_WORKSPACE_ID: &str = "local-demo-desktop-client-main";
const LOCAL_DEMO_RELIABILITY_WORKSPACE_ID: &str = "local-demo-release-reliability";
const LOCAL_DEMO_PRIMARY_CONVERSATION_ID: &str = "local-demo-flaky-data-pipeline-test";
const LOCAL_DEMO_CONVERSATION_IDS: &[&str] = &[
    LOCAL_DEMO_PRIMARY_CONVERSATION_ID,
    "local-demo-auth-middleware-review",
    "local-demo-task-search-shortcuts",
    "local-demo-agent-sdk-upgrade",
];

struct LocalDemoHierarchySeed {
    workspaces: Vec<Value>,
    conversations: Vec<LocalConversation>,
}

struct LocalDemoSessionContentSeed {
    conversation_id: &'static str,
    timeline: Vec<Value>,
}

fn local_demo_hierarchy_seed(now: &str) -> LocalDemoHierarchySeed {
    let provenance = json!({
        "kind": "local_demo_seed",
        "seed_id": LOCAL_DEMO_HIERARCHY_SEED_ID,
        "catalog_scope": "northstar/desktop-client",
    });
    let workspaces = vec![
        json!({
            "id": LOCAL_DEMO_DESKTOP_WORKSPACE_ID,
            "tenant_id": "northstar",
            "project_id": "desktop-client",
            "name": "Desktop Client",
            "description": "Local demo workspace for application UX, frontend, and Rust runtime delivery.",
            "status": "open",
            "created_at": now,
            "updated_at": now,
            "metadata": {
                "runtime": "local",
                "demo": true,
                "provenance": provenance,
            },
        }),
        json!({
            "id": LOCAL_DEMO_RELIABILITY_WORKSPACE_ID,
            "tenant_id": "northstar",
            "project_id": "desktop-client",
            "name": "Release Reliability",
            "description": "Local demo workspace for CI health, releases, and verification evidence.",
            "status": "open",
            "created_at": now,
            "updated_at": now,
            "metadata": {
                "runtime": "local",
                "demo": true,
                "provenance": provenance,
            },
        }),
    ];
    let conversations = [
        (
            "local-demo-flaky-data-pipeline-test",
            LOCAL_DEMO_DESKTOP_WORKSPACE_ID,
            "Fix flaky data-pipeline test",
        ),
        (
            "local-demo-auth-middleware-review",
            LOCAL_DEMO_DESKTOP_WORKSPACE_ID,
            "Review auth middleware refactor",
        ),
        (
            "local-demo-task-search-shortcuts",
            LOCAL_DEMO_DESKTOP_WORKSPACE_ID,
            "Add task search shortcuts",
        ),
        (
            "local-demo-agent-sdk-upgrade",
            LOCAL_DEMO_RELIABILITY_WORKSPACE_ID,
            "Plan agent SDK upgrade",
        ),
    ]
    .into_iter()
    .map(|(id, workspace_id, title)| LocalConversation {
        id: id.to_string(),
        project_id: "desktop-client".to_string(),
        tenant_id: "northstar".to_string(),
        title: title.to_string(),
        workspace_id: Some(workspace_id.to_string()),
        capability_mode: ConversationCapabilityMode::Code,
        current_mode: ConversationRunMode::Plan,
        created_at: now.to_string(),
        updated_at: now.to_string(),
    })
    .collect();
    LocalDemoHierarchySeed {
        workspaces,
        conversations,
    }
}

fn local_demo_session_content_seed() -> LocalDemoSessionContentSeed {
    let conversation_id = LOCAL_DEMO_PRIMARY_CONVERSATION_ID;
    let timeline = vec![
        local_demo_timeline_event(
            conversation_id,
            "user-goal",
            "user_message",
            1,
            Some("user"),
            Some(
                "Please reproduce the flaky pipeline test, isolate the race without changing \
                 the public API, and leave verification evidence in this session.",
            ),
            json!({}),
        ),
        local_demo_timeline_event(
            conversation_id,
            "agent-plan",
            "assistant_message",
            2,
            Some("assistant"),
            Some(
                "I’ll inspect the shared runner, reproduce the race in an isolated worktree, \
                 then verify the smallest safe fix.\n\n- Inspect fixture ownership\n- Reproduce \
                 concurrently\n- Patch and verify",
            ),
            json!({}),
        ),
        local_demo_timeline_event(
            conversation_id,
            "worktree-ready",
            "sandbox_ready",
            3,
            None,
            Some("Isolated worktree ready"),
            json!({
                "display": {
                    "title": "Isolated worktree ready",
                    "summary": "worktree/agent-fix · Local sandbox",
                    "status": "Ready"
                },
                "environment": {
                    "kind": "worktree",
                    "label": "worktree/agent-fix"
                }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "search-files-call",
            "act",
            4,
            None,
            None,
            json!({
                "toolName": "search_files",
                "toolInput": { "query": "shared_runner", "path": "src/pipeline" },
                "display": { "title": "Search files", "summary": "src/pipeline · shared_runner" }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "search-files-result",
            "observe",
            5,
            None,
            None,
            json!({
                "toolName": "search_files",
                "toolOutput": { "matches": 4 },
                "display": { "title": "Search files", "summary": "4 results", "status": "Completed" }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "read-code-call",
            "act",
            6,
            None,
            None,
            json!({
                "toolName": "read_code",
                "toolInput": { "paths": ["runner.py", "shared.py", "test_pipeline.py"] },
                "display": { "title": "Read code", "summary": "runner.py · shared.py · test_pipeline.py" }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "read-code-result",
            "observe",
            7,
            None,
            None,
            json!({
                "toolName": "read_code",
                "toolOutput": { "files": 3 },
                "display": { "title": "Read code", "summary": "3 files", "status": "Completed" }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "run-tests-call",
            "act",
            8,
            None,
            None,
            json!({
                "toolName": "run_tests",
                "toolInput": { "command": "pytest --count=50" },
                "display": { "title": "Run tests", "summary": "pytest --count=50" }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "run-tests-result",
            "observe",
            9,
            None,
            None,
            json!({
                "toolName": "run_tests",
                "toolOutput": { "result": "1 failure reproduced" },
                "display": { "title": "Run tests", "summary": "1 failure reproduced", "status": "Completed" }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "apply-patch-call",
            "act",
            10,
            None,
            None,
            json!({
                "toolName": "apply_patch",
                "toolInput": { "scope": "Fixture ownership scoped to job ID" },
                "display": { "title": "Apply patch", "summary": "Fixture ownership scoped to job ID" }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "apply-patch-result",
            "observe",
            11,
            None,
            None,
            json!({
                "toolName": "apply_patch",
                "toolOutput": { "files_changed": 4, "additions": 138, "deletions": 29 },
                "display": { "title": "Apply patch", "summary": "+138 −29", "status": "Completed" }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "agent-result",
            "assistant_message",
            12,
            Some("assistant"),
            Some(
                "I found the race: shared mutable state kept the previous job’s runner alive. \
                 I scoped the fixture to the job ID and added concurrent regression coverage.",
            ),
            json!({
                "display": {
                    "title": "Review changed files",
                    "summary": "4 files · +138 −29"
                }
            }),
        ),
        local_demo_timeline_event(
            conversation_id,
            "verification-progress",
            "task_updated",
            13,
            None,
            Some("18 tests passed · 50 race runs passed · static checks"),
            json!({
                "display": {
                    "title": "Verifying the isolated fix",
                    "summary": "18 tests passed · 50 race runs passed · static checks",
                    "checkpoint": "Patch applied",
                    "evidence": "18 tests · 50 race runs"
                },
                "progress": { "completed": 3, "total": 4 }
            }),
        ),
    ];
    LocalDemoSessionContentSeed {
        conversation_id,
        timeline,
    }
}

fn local_demo_timeline_event(
    conversation_id: &str,
    suffix: &str,
    event_type: &str,
    event_counter: i64,
    role: Option<&str>,
    content: Option<&str>,
    fields: Value,
) -> Value {
    const BASE_EVENT_TIME_US: i64 = 1_784_282_040_000_000;
    let event_time_us = BASE_EVENT_TIME_US + event_counter * 1_000_000;
    let payload = fields.clone();
    let mut event = json!({
        "id": format!("{conversation_id}:{suffix}"),
        "type": event_type,
        "event_type": event_type,
        "conversation_id": conversation_id,
        "eventTimeUs": event_time_us,
        "eventCounter": event_counter,
        "event_time_us": event_time_us,
        "event_counter": event_counter,
        "time_us": event_time_us,
        "counter": event_counter,
        "timestamp": event_time_us / 1_000,
        "payload": payload,
        "data": fields,
    });
    if let Some(role) = role {
        event["role"] = json!(role);
        event["data"]["role"] = json!(role);
    }
    if let Some(content) = content {
        event["content"] = json!(content);
        event["data"]["content"] = json!(content);
    }
    let additional_fields = event["payload"].as_object().cloned();
    if let (Some(event_fields), Some(additional_fields)) =
        (event.as_object_mut(), additional_fields)
    {
        event_fields.extend(additional_fields);
    }
    event
}

fn is_local_demo_conversation(conversation_id: &str) -> bool {
    LOCAL_DEMO_CONVERSATION_IDS.contains(&conversation_id)
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
    checkpoints: Arc<dyn CheckpointStore>,
    clock: Arc<SystemClock>,
    config: Mutex<LocalRuntimeConfig>,
    provider_runtime: Mutex<ProviderRuntimeState>,
    provider_credentials: ProviderCredentialBroker,
    provider_probe: ProviderProbeService,
    session_store: DesktopSessionStore,
    event_counter: AtomicU64,
    terminal_sessions: Mutex<HashMap<String, TerminalSessionLease>>,
    agent_runs: Mutex<HashMap<String, ActiveAgentRun>>,
    #[cfg(test)]
    agent_run_claim_attempts: AtomicU64,
    #[cfg(test)]
    agent_engine_attempts: AtomicU64,
    #[cfg(test)]
    recovery_fork_prepare_attempts: AtomicU64,
    #[cfg(test)]
    mock_llm_enabled: AtomicU8,
    events: broadcast::Sender<Value>,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct ProviderRuntimeKey {
    tenant_id: String,
    provider_id: String,
}

#[derive(Clone, Debug)]
struct ProviderRuntimeBinding {
    provider_type: String,
    base_url: String,
    model: String,
    auth_method: String,
}

#[derive(Clone, Debug)]
struct ProviderProbeSnapshot {
    provider_revision: u64,
    binding_digest: String,
    status: String,
    detail: String,
    last_check: String,
    response_time_ms: u64,
    error_code: Option<String>,
}

#[derive(Clone)]
struct ProviderProbeBindingSnapshot {
    provider_type: String,
    base_url: String,
    auth_method: String,
    binding_digest: String,
}

#[derive(Default)]
struct ProviderRuntimeState {
    bindings: HashMap<ProviderRuntimeKey, ProviderRuntimeBinding>,
    credentials: HashMap<ProviderRuntimeKey, String>,
    configured_credentials: HashSet<ProviderRuntimeKey>,
    selections: HashMap<String, String>,
    probes: HashMap<ProviderRuntimeKey, ProviderProbeSnapshot>,
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
    #[cfg(test)]
    fn new(
        workspace_root: PathBuf,
        tool_host: LocalToolHost,
        checkpoints: Arc<dyn CheckpointStore>,
        api_token: String,
        session_store: DesktopSessionStore,
    ) -> Result<Self, String> {
        let provider_credentials =
            ProviderCredentialBroker::in_memory(session_store.installation_id())
                .map_err(|error| error.to_string())?;
        Self::new_with_provider_credentials(
            workspace_root,
            tool_host,
            checkpoints,
            api_token,
            session_store,
            provider_credentials,
        )
    }

    fn new_with_provider_credentials(
        workspace_root: PathBuf,
        tool_host: LocalToolHost,
        checkpoints: Arc<dyn CheckpointStore>,
        api_token: String,
        session_store: DesktopSessionStore,
        provider_credentials: ProviderCredentialBroker,
    ) -> Result<Self, String> {
        if provider_credentials.installation_id() != session_store.installation_id() {
            return Err(
                "provider credential storage does not match this desktop installation".to_string(),
            );
        }
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
        let local_demo_seed = local_demo_hierarchy_seed(&now);
        session_store.ensure_local_demo_hierarchy_seed(
            LOCAL_DEMO_HIERARCHY_SEED_ID,
            &local_demo_seed.workspaces,
            &local_demo_seed.conversations,
            &now,
        )?;
        let local_demo_session_content = local_demo_session_content_seed();
        session_store.ensure_local_demo_session_content_seed(
            LOCAL_DEMO_SESSION_CONTENT_SEED_ID,
            local_demo_session_content.conversation_id,
            &local_demo_session_content.timeline,
            &now,
        )?;
        let mut provider_bindings = HashMap::new();
        let mut provider_values = HashMap::new();
        let mut provider_credential_records = Vec::new();
        for (tenant_id, provider) in session_store.list_runtime_provider_connections()? {
            let Some(provider_id) = provider.get("id").and_then(Value::as_str) else {
                continue;
            };
            let key = ProviderRuntimeKey {
                tenant_id,
                provider_id: provider_id.to_string(),
            };
            if let Some(binding_digest) = provider_credential_binding(&provider) {
                let provider_revision = provider
                    .get("revision")
                    .and_then(Value::as_u64)
                    .unwrap_or(0);
                provider_credential_records.push((key.clone(), provider_revision, binding_digest));
            }
            let Some(binding) = runtime_binding_from_provider(&provider) else {
                continue;
            };
            provider_values.insert(key.clone(), provider);
            provider_bindings.insert(key, binding);
        }
        let mut provider_selections = HashMap::new();
        for (tenant_id, provider_id) in session_store.list_selected_llm_providers()? {
            let key = ProviderRuntimeKey {
                tenant_id: tenant_id.clone(),
                provider_id: provider_id.clone(),
            };
            if provider_bindings.contains_key(&key) {
                provider_selections.insert(tenant_id, provider_id);
            } else {
                session_store.clear_llm_provider_selection_if_matches(&tenant_id, &provider_id)?;
            }
        }
        for (tenant_id, policy) in session_store.list_llm_routing_policies()? {
            let Some(default_target) = policy.get("roles").and_then(|roles| roles.get("default"))
            else {
                continue;
            };
            let Some(provider_id) = default_target.get("provider_id").and_then(Value::as_str)
            else {
                continue;
            };
            let Some(model_id) = default_target.get("model_id").and_then(Value::as_str) else {
                continue;
            };
            if provider_selections.get(&tenant_id).map(String::as_str) != Some(provider_id) {
                continue;
            }
            let key = ProviderRuntimeKey {
                tenant_id,
                provider_id: provider_id.to_string(),
            };
            if provider_values
                .get(&key)
                .is_some_and(|provider| provider_supports_route_model(provider, model_id))
            {
                if let Some(binding) = provider_bindings.get_mut(&key) {
                    binding.model = model_id.to_string();
                }
            }
        }
        let mut runtime_credentials = HashMap::new();
        let mut configured_credentials = HashSet::new();
        for (key, provider_revision, binding_digest) in provider_credential_records {
            if let Ok(Some(credential)) = provider_credentials.load(
                &key.tenant_id,
                &key.provider_id,
                provider_revision,
                &binding_digest,
            ) {
                configured_credentials.insert(key.clone());
                if provider_bindings.contains_key(&key) {
                    runtime_credentials.insert(key, credential);
                }
            }
        }
        Ok(Self {
            api_token,
            workspace_root: Mutex::new(workspace_root),
            tool_host: Mutex::new(tool_host),
            checkpoints,
            clock: Arc::new(SystemClock),
            config: Mutex::new(LocalRuntimeConfig::default()),
            provider_runtime: Mutex::new(ProviderRuntimeState {
                bindings: provider_bindings,
                credentials: runtime_credentials,
                configured_credentials,
                selections: provider_selections,
                probes: HashMap::new(),
            }),
            provider_credentials,
            provider_probe: ProviderProbeService::default(),
            session_store,
            event_counter: AtomicU64::new(1),
            terminal_sessions: Mutex::new(HashMap::new()),
            agent_runs: Mutex::new(HashMap::new()),
            #[cfg(test)]
            agent_run_claim_attempts: AtomicU64::new(0),
            #[cfg(test)]
            agent_engine_attempts: AtomicU64::new(0),
            #[cfg(test)]
            recovery_fork_prepare_attempts: AtomicU64::new(0),
            #[cfg(test)]
            mock_llm_enabled: AtomicU8::new(0),
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
        #[cfg(test)]
        self.agent_run_claim_attempts.fetch_add(1, Ordering::SeqCst);
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

    fn release_agent_run_if_control(&self, conversation_id: &str, control: &Arc<LocalRunControl>) {
        let mut runs = self.agent_runs.lock().expect("local agent runs");
        let owns_claim = runs
            .get(conversation_id)
            .is_some_and(|active| Arc::ptr_eq(&active.control, control));
        if owns_claim {
            runs.remove(conversation_id);
        }
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

    fn append_workspace_message(&self, workspace_id: &str, message: Value) -> Result<(), String> {
        self.session_store
            .append_workspace_message(workspace_id, &message)
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

    async fn ensure_authoritative_launch_checkpoint(
        &self,
        run: &DesktopRun,
    ) -> Result<bool, String> {
        let conversation_id = run.conversation_id.as_str();
        // Persist round zero before exposing Running. A crash after the database transition can
        // then use the ordinary disconnected-run resume path without repeating any agent work.
        let existing = self
            .checkpoints
            .load(conversation_id)
            .await
            .map_err(|error| error.to_string())?;
        let authority = self.session_store.checkpoint_authority(conversation_id)?;
        let needs_seed = match existing {
            Some(checkpoint)
                if matches!(
                    checkpoint.status,
                    SessionStatus::Finished | SessionStatus::Failed | SessionStatus::Cancelled
                ) =>
            {
                if run.status == DesktopRunStatus::Queued {
                    // A still-queued run has not launched yet, so a terminal checkpoint belongs to
                    // the previous authoritative run and can be retired before seeding round zero.
                    self.delete_checkpoint_and_authority(conversation_id, None)
                        .await?;
                    true
                } else {
                    return Err(
                        "recovered launch checkpoint is already terminal and must be reconciled"
                            .to_string(),
                    );
                }
            }
            Some(checkpoint)
                if checkpoint.status == SessionStatus::Running
                    && checkpoint_matches_run(&checkpoint, run)
                    && authority
                        .as_ref()
                        .is_some_and(|authority| authority.matches_run(run)) =>
            {
                false
            }
            Some(checkpoint) => {
                return Err(format!(
                    "authoritative launch checkpoint conflicts with {:?} session state",
                    checkpoint.status
                ));
            }
            None => true,
        };
        if needs_seed {
            let checkpoint = SessionState::new(
                conversation_id,
                run.request_message.as_str(),
                Some(run.project_id.as_str()),
            );
            self.checkpoints
                .save(&checkpoint)
                .await
                .map_err(|error| error.to_string())?;
            if let Err(error) = self
                .session_store
                .bind_checkpoint_authority(run, &now_iso())
            {
                return match self
                    .delete_checkpoint_and_authority(conversation_id, None)
                    .await
                {
                    Ok(()) => Err(format!(
                        "failed to persist authoritative checkpoint attribution: {error}"
                    )),
                    Err(cleanup_error) => Err(format!(
                        "failed to persist authoritative checkpoint attribution: {error}; \
                         failed to quarantine unattributed checkpoint: {cleanup_error}"
                    )),
                };
            }
        }
        Ok(needs_seed)
    }

    async fn delete_checkpoint_and_authority(
        &self,
        conversation_id: &str,
        expected_run_id: Option<&str>,
    ) -> Result<(), String> {
        self.checkpoints
            .delete(conversation_id)
            .await
            .map_err(|error| error.to_string())?;
        self.session_store
            .clear_checkpoint_authority(conversation_id, expected_run_id)?;
        Ok(())
    }

    async fn load_authoritative_checkpoint_for_run(
        &self,
        run: &DesktopRun,
    ) -> Result<Option<SessionState>, String> {
        let authority = self
            .session_store
            .checkpoint_authority(&run.conversation_id)?;
        if !authority
            .as_ref()
            .is_some_and(|authority| authority.matches_run(run))
        {
            return Ok(None);
        }
        let checkpoint = self
            .checkpoints
            .load(&run.conversation_id)
            .await
            .map_err(|error| error.to_string())?;
        Ok(checkpoint.filter(|checkpoint| checkpoint_matches_run(checkpoint, run)))
    }

    async fn terminalize_authoritative_checkpoint(
        &self,
        run: &DesktopRun,
        status: SessionStatus,
    ) -> Result<(), String> {
        let Some(mut checkpoint) = self.load_authoritative_checkpoint_for_run(run).await? else {
            return Err(
                "authoritative launch checkpoint is missing or does not match the run".to_string(),
            );
        };
        if checkpoint.status == status {
            return Ok(());
        }
        if matches!(
            checkpoint.status,
            SessionStatus::Finished | SessionStatus::Failed | SessionStatus::Cancelled
        ) {
            return Err(format!(
                "authoritative launch checkpoint is already {:?}, cannot commit {status:?}",
                checkpoint.status
            ));
        }
        checkpoint.status = status;
        self.checkpoints
            .save(&checkpoint)
            .await
            .map_err(|error| error.to_string())
    }

    async fn has_terminal_authoritative_checkpoint(
        &self,
        run: &DesktopRun,
    ) -> Result<bool, String> {
        let checkpoint = self.load_authoritative_checkpoint_for_run(run).await?;
        Ok(checkpoint.is_some_and(|checkpoint| {
            matches!(
                checkpoint.status,
                SessionStatus::Finished | SessionStatus::Failed | SessionStatus::Cancelled
            )
        }))
    }

    async fn persist_authoritative_run_outcome(
        &self,
        run: &DesktopRun,
        status: DesktopRunStatus,
        error: Option<String>,
        now: &str,
    ) -> Result<DesktopRun, String> {
        let checkpoint_status = match status {
            DesktopRunStatus::ReadyReview => Some(SessionStatus::Finished),
            DesktopRunStatus::Failed => Some(SessionStatus::Failed),
            DesktopRunStatus::Cancelled => Some(SessionStatus::Cancelled),
            _ => None,
        };
        if let Some(checkpoint_status) = checkpoint_status {
            if let Err(checkpoint_error) = self
                .terminalize_authoritative_checkpoint(run, checkpoint_status)
                .await
            {
                let recovery_error = format!(
                    "{CHECKPOINT_TERMINALIZATION_RECOVERY_ERROR_PREFIX}: {checkpoint_error}"
                );
                let disconnected = self.session_store.transition_run(
                    &run.id,
                    run.revision,
                    DesktopRunStatus::Disconnected,
                    Some(recovery_error.clone()),
                    now,
                );
                if let Ok(disconnected) = disconnected.as_ref() {
                    self.publish_run_status(disconnected);
                }
                let cleanup = self
                    .delete_checkpoint_and_authority(&run.conversation_id, None)
                    .await;
                return match (disconnected, cleanup) {
                    (Ok(_), Ok(())) => Err(recovery_error),
                    (Ok(_), Err(cleanup_error)) => Err(format!(
                        "{recovery_error}; failed to quarantine stale checkpoint: {cleanup_error}"
                    )),
                    (Err(transition_error), Ok(())) => Err(format!(
                        "{recovery_error}; failed to preserve disconnected run: {transition_error}"
                    )),
                    (Err(transition_error), Err(cleanup_error)) => Err(format!(
                        "{recovery_error}; failed to preserve disconnected run: {transition_error}; \
                         failed to quarantine stale checkpoint: {cleanup_error}"
                    )),
                };
            }
        }
        self.session_store
            .transition_run(&run.id, run.revision, status, error, now)
    }

    async fn reconcile_recovered_runs_from_checkpoints(&self) -> Result<(), String> {
        // The desktop run and the core checkpoint live in separate SQLite stores. A crash after
        // persisting the quarantine but before deleting the checkpoint must retry cleanup on the
        // next startup.
        for quarantined in self.session_store.list_current_checkpoint_quarantines(
            RECOVERED_CHECKPOINT_AUTHORITY_ERROR,
            CHECKPOINT_TERMINALIZATION_RECOVERY_ERROR_PREFIX,
        )? {
            // This also repairs a database written by the pre-atomic implementation where the
            // terminal quarantine committed before its queued inputs were settled.
            self.session_store.settle_queued_run_inputs(
                &quarantined.id,
                quarantined.status,
                &quarantined.updated_at,
            )?;
            self.delete_checkpoint_and_authority(&quarantined.conversation_id, None)
                .await?;
        }
        for run in self.session_store.list_recoverable_runs()? {
            let checkpoint = self
                .checkpoints
                .load(&run.conversation_id)
                .await
                .map_err(|error| error.to_string())?;
            let authority = self
                .session_store
                .checkpoint_authority(&run.conversation_id)?;
            let Some(checkpoint) = checkpoint else {
                if authority.is_some() {
                    self.session_store
                        .clear_checkpoint_authority(&run.conversation_id, None)?;
                }
                continue;
            };
            if !checkpoint_matches_run(&checkpoint, &run)
                || !authority
                    .as_ref()
                    .is_some_and(|authority| authority.matches_run(&run))
            {
                // Checkpoints are conversation-scoped. Quarantine a stale or externally replaced
                // checkpoint before serving routes so it cannot later inherit this run's tool
                // authority through reconnect, fork, or cancel.
                let reconciled = self.session_store.reconcile_recovered_run(
                    &run.id,
                    run.revision,
                    DesktopRunStatus::Failed,
                    Some(RECOVERED_CHECKPOINT_AUTHORITY_ERROR.to_string()),
                    &now_iso(),
                )?;
                self.delete_checkpoint_and_authority(&run.conversation_id, None)
                    .await?;
                self.publish_run_status(&reconciled);
                continue;
            }
            if checkpoint.status == SessionStatus::Running {
                continue;
            }
            if run.started_at.is_none()
                && !matches!(
                    checkpoint.status,
                    SessionStatus::Finished | SessionStatus::Failed | SessionStatus::Cancelled
                )
            {
                continue;
            }
            if checkpoint.status == SessionStatus::AwaitingInput {
                self.persist_pending_hitl(&run.conversation_id, Some(&run.id), &checkpoint)?;
            }
            let (status, error) = desktop_run_outcome(&checkpoint);
            let reconciled = self.session_store.reconcile_recovered_run(
                &run.id,
                run.revision,
                status,
                error,
                &now_iso(),
            )?;
            self.publish_run_status(&reconciled);
        }
        Ok(())
    }

    async fn prepare_authoritative_run_for_execution(
        &self,
        run_id: &str,
        conversation_id: &str,
        project_id: &str,
        message: &str,
        now: &str,
    ) -> Result<Option<DesktopRun>, String> {
        let Some(run) = self.session_store.run(run_id)? else {
            return Ok(None);
        };
        if run.conversation_id != conversation_id
            || run.project_id != project_id
            || run.request_message != message
        {
            return Err("authoritative run request does not match persisted authority".to_string());
        }
        let needs_launch_checkpoint = run.started_at.is_none()
            && matches!(
                run.status,
                DesktopRunStatus::Queued | DesktopRunStatus::Interrupted
            );
        let seeded_checkpoint = if needs_launch_checkpoint {
            self.ensure_authoritative_launch_checkpoint(&run).await?
        } else {
            false
        };
        match self.session_store.prepare_run_for_execution(run_id, now) {
            Ok(Some(prepared)) if prepared.status == DesktopRunStatus::Running => {
                Ok(Some(prepared))
            }
            Ok(prepared) => {
                if seeded_checkpoint {
                    self.delete_checkpoint_and_authority(conversation_id, Some(&run.id))
                        .await?;
                }
                Ok(prepared)
            }
            Err(error) => {
                if seeded_checkpoint {
                    self.delete_checkpoint_and_authority(conversation_id, Some(&run.id))
                        .await
                        .map_err(|cleanup_error| {
                            format!("{error}; failed to clean launch checkpoint: {cleanup_error}")
                        })?;
                }
                Err(error)
            }
        }
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
            Ok(None) => {
                if let Some(control) = claimed_control.as_ref() {
                    self.release_agent_run_if_control(&conversation_id, control);
                }
                return;
            }
            Err(error) => {
                eprintln!("failed to read local conversation authority: {error}");
                if let Some(control) = claimed_control.as_ref() {
                    self.release_agent_run_if_control(&conversation_id, control);
                }
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
            if let Some(control) = claimed_control.as_ref() {
                self.release_agent_run_if_control(&conversation_id, control);
            }
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
            if let Some(control) = claimed_control.as_ref() {
                self.release_agent_run_if_control(&conversation_id, control);
            }
            return;
        }
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
        let authoritative_run = if let Some(run_id) = authoritative_run_id.as_deref() {
            match self
                .prepare_authoritative_run_for_execution(
                    run_id,
                    &conversation_id,
                    &project_id,
                    &message,
                    &now_iso(),
                )
                .await
            {
                Ok(Some(run)) => {
                    self.publish_run_status(&run);
                    if run.status != DesktopRunStatus::Running {
                        self.release_agent_run(&conversation_id);
                        return;
                    }
                    Some(run)
                }
                Ok(None) => {
                    self.release_agent_run(&conversation_id);
                    return;
                }
                Err(error) => {
                    eprintln!("failed to prepare authoritative local run: {error}");
                    self.release_agent_run(&conversation_id);
                    return;
                }
            }
        } else {
            None
        };
        let authoritative_revision = authoritative_run.as_ref().map(|run| run.revision);

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
                    match self
                        .persist_authoritative_run_outcome(
                            run,
                            DesktopRunStatus::Failed,
                            Some("execution environment is unavailable".to_string()),
                            &now_iso(),
                        )
                        .await
                    {
                        Ok(failed) => self.publish_run_status(&failed),
                        Err(error) => {
                            eprintln!("failed to persist authoritative launch failure: {error}")
                        }
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
                self.delete_checkpoint_and_authority(&conversation_id, None)
                    .await
                    .map_err(CoreError::Checkpoint)
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
        if let (Some(run), Some(expected_revision)) =
            (authoritative_run.as_ref(), authoritative_revision)
        {
            debug_assert_eq!(run.revision, expected_revision);
            let (status, error) = match run_result {
                Ok(state) => desktop_run_outcome(&state),
                Err(error) => (DesktopRunStatus::Failed, Some(error)),
            };
            match self
                .persist_authoritative_run_outcome(run, status, error, &now_iso())
                .await
            {
                Ok(run) => self.publish_run_status(&run),
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
        #[cfg(test)]
        self.agent_engine_attempts.fetch_add(1, Ordering::SeqCst);
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
            self.llm_for_capability(&conversation.tenant_id, conversation.capability_mode),
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
                    match self
                        .persist_authoritative_run_outcome(
                            &run,
                            DesktopRunStatus::Failed,
                            Some("execution environment is unavailable".to_string()),
                            &now_iso(),
                        )
                        .await
                    {
                        Ok(failed) => self.publish_run_status(&failed),
                        Err(error) => {
                            eprintln!("failed to persist resumed launch failure: {error}")
                        }
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
            match self
                .persist_authoritative_run_outcome(&run, status, error, &now_iso())
                .await
            {
                Ok(run) => self.publish_run_status(&run),
                Err(error) => eprintln!("failed to persist resumed local run result: {error}"),
            }
        }
        self.release_agent_run(&conversation_id);
    }

    #[cfg(test)]
    fn llm(&self, tenant_id: &str) -> Arc<dyn LlmPort> {
        self.llm_for_role(tenant_id, LlmWorkloadRole::Default)
    }

    fn llm_for_capability(
        &self,
        tenant_id: &str,
        capability: ConversationCapabilityMode,
    ) -> Arc<dyn LlmPort> {
        self.llm_for_role(tenant_id, workload_role_for_capability(capability))
    }

    fn llm_for_role(&self, tenant_id: &str, role: LlmWorkloadRole) -> Arc<dyn LlmPort> {
        let runtime = self
            .provider_runtime
            .lock()
            .expect("provider runtime state");
        let policy = match self
            .session_store
            .llm_routing_policy(tenant_id, Utc::now().timestamp_millis())
        {
            Ok(policy) => policy,
            Err(_) => return Arc::new(UnconfiguredLocalLlm),
        };
        let mut targets = match routing_targets_for_role(&policy, role) {
            Ok(targets) => targets,
            Err(_) => return Arc::new(UnconfiguredLocalLlm),
        };
        if targets.is_empty() {
            if let Some(provider_id) = runtime.selections.get(tenant_id) {
                if let Some(binding) = runtime.bindings.get(&ProviderRuntimeKey {
                    tenant_id: tenant_id.to_string(),
                    provider_id: provider_id.clone(),
                }) {
                    targets.push(LlmRouteTarget {
                        provider_id: provider_id.clone(),
                        model_id: binding.model.clone(),
                    });
                }
            }
        }
        let candidates = targets
            .into_iter()
            .filter_map(|target| {
                let key = ProviderRuntimeKey {
                    tenant_id: tenant_id.to_string(),
                    provider_id: target.provider_id,
                };
                let mut binding = runtime.bindings.get(&key)?.clone();
                binding.model = target.model_id;
                llm_from_runtime_binding(binding, runtime.credentials.get(&key).cloned())
            })
            .collect::<Vec<_>>();
        drop(runtime);
        if !candidates.is_empty() {
            return FailoverLlm::from_candidates(candidates);
        }
        #[cfg(test)]
        if self.mock_llm_enabled.load(Ordering::Acquire) != 0 {
            return Arc::new(MockLocalLlm);
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
        let run_metadata = latest_run
            .as_ref()
            .and_then(|run| serde_json::to_value(run).ok())
            .unwrap_or(Value::Null);
        let environment_metadata = latest_run
            .as_ref()
            .and_then(|run| run.environment.as_ref())
            .and_then(|environment| serde_json::to_value(environment).ok())
            .unwrap_or_else(|| json!({ "kind": "local", "label": "Local runtime" }));
        let workspace_name = conversation
            .workspace_id
            .as_deref()
            .and_then(|workspace_id| {
                self.session_store
                    .workspace_name(workspace_id)
                    .ok()
                    .flatten()
            });
        json!({
            "id": conversation.id,
            "project_id": conversation.project_id,
            "tenant_id": conversation.tenant_id,
            "user_id": "local-user",
            "title": conversation.title,
            "status": "active",
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
            "workspace_name": workspace_name,
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

fn checkpoint_matches_run(checkpoint: &SessionState, run: &DesktopRun) -> bool {
    checkpoint.session_id == run.conversation_id
        && checkpoint.goal == run.request_message
        && checkpoint.project_id.as_deref() == Some(run.project_id.as_str())
}

fn has_checkpoint_terminalization_recovery_error(run: &DesktopRun) -> bool {
    run.error
        .as_deref()
        .is_some_and(|error| error.starts_with(CHECKPOINT_TERMINALIZATION_RECOVERY_ERROR_PREFIX))
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
            "/api/v1/llm-providers/models/:provider_type",
            get(list_llm_provider_models),
        )
        .route(
            "/api/v1/llm-providers/test-connection",
            post(validate_llm_provider_draft),
        )
        .route(
            "/api/v1/llm-providers/routing-policy",
            get(get_llm_routing_policy).put(put_llm_routing_policy),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/runtime-selection",
            put(select_llm_provider_runtime),
        )
        .route(
            "/api/v1/llm-providers/:provider_id",
            patch(update_llm_provider).put(update_llm_provider),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/health-check",
            post(validate_llm_provider),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/models/discover",
            post(discover_llm_provider_models),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/usage",
            get(get_llm_provider_usage),
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
            "/api/v1/tenants/:tenant_id/projects/:project_id/task-sessions",
            post(task_session::create_task_session),
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
        .allow_methods([Method::GET, Method::POST, Method::PATCH, Method::PUT])
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

fn ensure_checkpoint_run_ownership(
    state: &LocalRuntimeState,
    run: &DesktopRun,
) -> Result<(), (StatusCode, Json<Value>)> {
    let authority = state
        .session_store
        .checkpoint_authority(&run.conversation_id)
        .map_err(local_store_error)?;
    if authority
        .as_ref()
        .is_some_and(|authority| !authority.matches_run(run))
    {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": CHECKPOINT_CONTROL_AUTHORITY_ERROR })),
        ));
    }
    Ok(())
}

async fn ensure_checkpoint_control_authority(
    state: &LocalRuntimeState,
    run: &DesktopRun,
) -> Result<(), (StatusCode, Json<Value>)> {
    ensure_checkpoint_run_ownership(state, run)?;
    if state
        .load_authoritative_checkpoint_for_run(run)
        .await
        .map_err(local_store_error)?
        .is_some()
    {
        return Ok(());
    }
    Err((
        StatusCode::CONFLICT,
        Json(json!({ "detail": CHECKPOINT_CONTROL_AUTHORITY_ERROR })),
    ))
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
    ensure_workspace_scope(
        state,
        authenticated,
        &authenticated.workspace.tenant_id,
        &authenticated.workspace.project_id,
        workspace_id,
    )
}

fn ensure_workspace_scope(
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<(), (StatusCode, Json<Value>)> {
    if tenant_id != authenticated.workspace.tenant_id {
        return Err(active_workspace_scope_error());
    }
    ensure_active_project(authenticated, project_id)?;

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
    let tenant_id = state
        .session_store
        .workspace_tenant_id(workspace_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "workspace not found" })),
            )
        })?;
    if project_id != authenticated.workspace.project_id
        || tenant_id != authenticated.workspace.tenant_id
    {
        return Err(active_workspace_scope_error());
    }
    Ok(())
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
        ResourceRegistryError::InvalidRoutingPolicy(_) => (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": detail })),
        ),
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

#[derive(Deserialize)]
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LlmProviderDraftProbe {
    name: String,
    provider_type: String,
    base_url: String,
    #[serde(default = "default_provider_auth_method")]
    auth_method: String,
    #[serde(default)]
    api_key: Option<String>,
    #[serde(default, rename = "is_active")]
    _is_active: Option<bool>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LlmProviderProbeAction {
    expected_revision: u64,
}

fn default_provider_auth_method() -> String {
    "api_key".to_string()
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq, Hash)]
#[serde(deny_unknown_fields)]
struct LlmRouteTarget {
    provider_id: String,
    model_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct LlmRoutingRoles {
    default: Option<LlmRouteTarget>,
    fast: Option<LlmRouteTarget>,
    coding: Option<LlmRouteTarget>,
    vision: Option<LlmRouteTarget>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LlmRoutingPolicyMutation {
    expected_revision: u64,
    roles: LlmRoutingRolesMutation,
    fallbacks: Vec<LlmRouteTarget>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LlmRoutingRolesMutation {
    default: Value,
    fast: Value,
    coding: Value,
    vision: Value,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum LlmWorkloadRole {
    Default,
    Fast,
    Coding,
    Vision,
}

#[derive(Debug, Clone, Copy, Serialize)]
struct LlmProviderTypeDescriptor {
    provider_type: &'static str,
    operation_type: &'static str,
    probe_supported: bool,
    auth_methods: &'static [&'static str],
}

const LOCAL_LLM_PROVIDER_TYPES: &[LlmProviderTypeDescriptor] = &[
    LlmProviderTypeDescriptor {
        provider_type: "openai",
        operation_type: "llm",
        probe_supported: true,
        auth_methods: &["api_key", "none"],
    },
    LlmProviderTypeDescriptor {
        provider_type: "anthropic",
        operation_type: "llm",
        probe_supported: true,
        auth_methods: &["api_key", "none"],
    },
    LlmProviderTypeDescriptor {
        provider_type: "openai_compatible",
        operation_type: "llm",
        probe_supported: true,
        auth_methods: &["api_key", "none"],
    },
];

#[derive(Debug, Default, Serialize)]
struct LocalLlmProviderModels {
    chat: Vec<String>,
    embedding: Vec<String>,
    rerank: Vec<String>,
}

#[derive(Debug, Serialize)]
struct LocalLlmProviderModelsResponse {
    provider_type: String,
    models: LocalLlmProviderModels,
    source: Option<&'static str>,
}

async fn list_llm_provider_types() -> Json<Vec<LlmProviderTypeDescriptor>> {
    Json(LOCAL_LLM_PROVIDER_TYPES.to_vec())
}

async fn list_llm_provider_models(
    Path(provider_type): Path<String>,
) -> Result<Json<LocalLlmProviderModelsResponse>, (StatusCode, Json<Value>)> {
    let provider_type = provider_type.trim().to_lowercase();
    let (models, source) = match provider_type.as_str() {
        "openai" => (
            LocalLlmProviderModels {
                chat: local_model_ids(&["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]),
                embedding: local_model_ids(&["text-embedding-3-small", "text-embedding-3-large"]),
                rerank: Vec::new(),
            },
            Some("static-fallback"),
        ),
        "anthropic" => (
            LocalLlmProviderModels {
                chat: local_model_ids(&[
                    "claude-3-5-sonnet-20241022",
                    "claude-3-5-haiku-20241022",
                    "claude-3-opus-20240229",
                ]),
                embedding: Vec::new(),
                rerank: Vec::new(),
            },
            Some("static-fallback"),
        ),
        "openai_compatible" => (LocalLlmProviderModels::default(), None),
        _ => {
            return Err((
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({ "detail": "unsupported local provider type" })),
            ));
        }
    };
    Ok(Json(LocalLlmProviderModelsResponse {
        provider_type,
        models,
        source,
    }))
}

fn local_model_ids(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}

async fn list_llm_providers(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> LocalJsonResult {
    let tenant_id = &authenticated.workspace.tenant_id;
    let runtime = state
        .provider_runtime
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?;
    let providers = state
        .session_store
        .list_managed_resources(ManagedResourceKind::Provider, "tenant", tenant_id)
        .map_err(local_store_error)?;
    let selected_provider_id = runtime.selections.get(tenant_id);
    let providers = providers
        .into_iter()
        .map(|provider| {
            let provider_id = provider
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            let key = ProviderRuntimeKey {
                tenant_id: tenant_id.clone(),
                provider_id: provider_id.clone(),
            };
            provider_with_runtime_state(
                provider,
                selected_provider_id.map(String::as_str) == Some(provider_id.as_str()),
                runtime.bindings.get(&key),
                runtime.configured_credentials.contains(&key),
                runtime.probes.get(&key),
            )
        })
        .collect();
    Ok(Json(Value::Array(providers)))
}

async fn get_llm_routing_policy(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> LocalJsonResult {
    state
        .session_store
        .llm_routing_policy(
            &authenticated.workspace.tenant_id,
            Utc::now().timestamp_millis(),
        )
        .map(Json)
        .map_err(resource_registry_error)
}

async fn put_llm_routing_policy(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<LlmRoutingPolicyMutation>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    let tenant_id = &authenticated.workspace.tenant_id;
    let expected_revision = request.expected_revision;
    let (roles, fallbacks) = normalized_routing_policy(request)?;
    let default_target = roles
        .default
        .as_ref()
        .ok_or_else(|| routing_policy_validation_error("default routing target is required"))?;
    let mut runtime = state
        .provider_runtime
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?;
    let current_policy = state
        .session_store
        .llm_routing_policy(tenant_id, Utc::now().timestamp_millis())
        .map_err(resource_registry_error)?;
    let actual_revision = current_policy
        .get("revision")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    if expected_revision != actual_revision {
        return Err(resource_registry_error(
            ResourceRegistryError::RevisionConflict {
                expected: expected_revision,
                actual: actual_revision,
            },
        ));
    }
    let mut default_binding = None;
    for target in [
        LlmWorkloadRole::Default,
        LlmWorkloadRole::Fast,
        LlmWorkloadRole::Coding,
        LlmWorkloadRole::Vision,
    ]
    .into_iter()
    .filter_map(|role| configured_routing_target(&roles, role))
    .chain(fallbacks.iter())
    {
        let provider = state
            .session_store
            .managed_resource(
                ManagedResourceKind::Provider,
                "tenant",
                tenant_id,
                &target.provider_id,
            )
            .map_err(local_store_error)?
            .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))?;
        let binding = runtime_binding_for_route_target(&provider, target)?;
        let key = ProviderRuntimeKey {
            tenant_id: tenant_id.clone(),
            provider_id: target.provider_id.clone(),
        };
        if binding.auth_method != "none" && !runtime.credentials.contains_key(&key) {
            return Err(routing_policy_validation_error(format!(
                "provider {} requires credentials before it can be routed",
                target.provider_id
            )));
        }
        if target == default_target {
            default_binding = Some(binding);
        }
    }
    let default_binding = default_binding
        .ok_or_else(|| routing_policy_validation_error("default routing target is required"))?;
    let roles_json =
        serde_json::to_value(&roles).map_err(|error| local_store_error(error.to_string()))?;
    let fallbacks_json =
        serde_json::to_value(&fallbacks).map_err(|error| local_store_error(error.to_string()))?;
    let policy = state
        .session_store
        .put_llm_routing_policy(
            tenant_id,
            expected_revision,
            roles_json,
            fallbacks_json,
            Utc::now().timestamp_millis(),
        )
        .map_err(resource_registry_error)?;
    let key = ProviderRuntimeKey {
        tenant_id: tenant_id.clone(),
        provider_id: default_target.provider_id.clone(),
    };
    runtime.bindings.insert(key, default_binding);
    runtime
        .selections
        .insert(tenant_id.clone(), default_target.provider_id.clone());
    Ok(Json(policy))
}

fn normalized_routing_policy(
    request: LlmRoutingPolicyMutation,
) -> Result<(LlmRoutingRoles, Vec<LlmRouteTarget>), (StatusCode, Json<Value>)> {
    if request.fallbacks.len() > 8 {
        return Err(routing_policy_validation_error(
            "routing fallbacks cannot contain more than 8 targets",
        ));
    }
    let roles = LlmRoutingRoles {
        default: normalized_nullable_route_target(request.roles.default, "default")?,
        fast: normalized_nullable_route_target(request.roles.fast, "fast")?,
        coding: normalized_nullable_route_target(request.roles.coding, "coding")?,
        vision: normalized_nullable_route_target(request.roles.vision, "vision")?,
    };
    if roles.default.is_none() {
        return Err(routing_policy_validation_error(
            "default routing target is required",
        ));
    }
    if roles.fast.is_some() {
        return Err(routing_policy_validation_error(
            "fast routing target is not supported by the current conversation protocol",
        ));
    }
    if roles.vision.is_some() {
        return Err(routing_policy_validation_error(
            "vision routing target is not supported by the current conversation protocol",
        ));
    }
    let mut seen = HashSet::with_capacity(request.fallbacks.len());
    let mut fallbacks = Vec::with_capacity(request.fallbacks.len());
    for target in request.fallbacks {
        let target = normalized_route_target(target)?;
        if !seen.insert(target.clone()) {
            return Err(routing_policy_validation_error(
                "routing fallbacks cannot contain duplicate targets",
            ));
        }
        fallbacks.push(target);
    }
    Ok((roles, fallbacks))
}

fn normalized_nullable_route_target(
    value: Value,
    role: &str,
) -> Result<Option<LlmRouteTarget>, (StatusCode, Json<Value>)> {
    if value.is_null() {
        return Ok(None);
    }
    let target = serde_json::from_value::<LlmRouteTarget>(value)
        .map_err(|_| routing_policy_validation_error(format!("invalid {role} routing target")))?;
    normalized_route_target(target).map(Some)
}

fn normalized_route_target(
    target: LlmRouteTarget,
) -> Result<LlmRouteTarget, (StatusCode, Json<Value>)> {
    let provider_id = target.provider_id.trim().to_string();
    if provider_id.is_empty() {
        return Err(routing_policy_validation_error(
            "routing target provider_id cannot be empty",
        ));
    }
    let model_id = target.model_id.trim().to_string();
    if model_id.is_empty() {
        return Err(routing_policy_validation_error(
            "routing target model_id cannot be empty",
        ));
    }
    Ok(LlmRouteTarget {
        provider_id,
        model_id,
    })
}

fn routing_policy_validation_error(detail: impl Into<String>) -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({ "detail": detail.into() })),
    )
}

async fn create_llm_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<LlmProviderMutation>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    let provider_id = format!("provider-{}", Uuid::new_v4());
    mutate_llm_provider_blocking(state, authenticated, provider_id, request, true).await
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
    mutate_llm_provider_blocking(state, authenticated, provider_id, request, false).await
}

async fn mutate_llm_provider_blocking(
    state: Arc<LocalRuntimeState>,
    authenticated: AuthenticatedContext,
    provider_id: String,
    request: LlmProviderMutation,
    creating: bool,
) -> LocalJsonResult {
    tokio::task::spawn_blocking(move || {
        mutate_llm_provider(state, authenticated, provider_id, request, creating)
    })
    .await
    .map_err(|_| local_store_error("provider credential storage task failed".to_string()))?
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeProviderSelectionRequest {
    expected_revision: u64,
    expected_policy_revision: u64,
}

async fn select_llm_provider_runtime(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(provider_id): Path<String>,
    Json(request): Json<RuntimeProviderSelectionRequest>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    let tenant_id = &authenticated.workspace.tenant_id;
    let mut runtime = state
        .provider_runtime
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?;
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
    let binding = runtime_binding_from_provider(&provider).ok_or_else(|| {
        (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({
                "detail": "provider connection must be active and configured before runtime selection"
            })),
        )
    })?;
    let key = ProviderRuntimeKey {
        tenant_id: tenant_id.clone(),
        provider_id: provider_id.clone(),
    };
    if binding.auth_method != "none" && !runtime.credentials.contains_key(&key) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({
                "detail": "provider credentials are required before runtime selection"
            })),
        ));
    }
    let stored = state
        .session_store
        .select_llm_provider(
            tenant_id,
            &provider_id,
            request.expected_revision,
            request.expected_policy_revision,
            Utc::now().timestamp_millis(),
        )
        .map_err(resource_registry_error)?;
    runtime.bindings.insert(key.clone(), binding.clone());
    runtime.selections.insert(tenant_id.clone(), provider_id);
    let credential_configured = runtime.configured_credentials.contains(&key);
    Ok(Json(provider_with_runtime_state(
        stored,
        true,
        Some(&binding),
        credential_configured,
        runtime.probes.get(&key),
    )))
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
    // Provider mutations are serialized before reading the current DB revision. This keeps the
    // versioned credential pre-write aligned with the SQLite compare-and-swap in this process;
    // the session store's exclusive SQLite ownership provides the cross-process boundary.
    let mut runtime = state
        .provider_runtime
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?;
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
    let current_revision = current
        .as_ref()
        .and_then(|provider| provider.get("revision"))
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let previous_credential_binding = current.as_ref().and_then(provider_credential_binding);
    let mut provider = current.unwrap_or_else(|| {
        json!({
            "id": provider_id,
            "name": "New provider",
            "provider_type": "openai_compatible",
            "tenant_id": tenant_id,
            "is_active": false,
            "base_url": null,
            "auth_method": "api_key",
            "credential_source": "system_vault",
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
    if let Some(base_url) = object.get("base_url").and_then(Value::as_str) {
        let base_url = normalized_runtime_provider_base_url(&provider_type, base_url)?;
        object.insert("base_url".to_string(), json!(base_url));
    }
    object.insert(
        "credential_source".to_string(),
        json!(if auth_method == "none" {
            "none"
        } else {
            "system_vault"
        }),
    );
    object.insert("credential_configured".to_string(), json!(false));
    object.insert("health_status".to_string(), json!("not_checked"));

    let is_active = object.get("is_active").and_then(Value::as_bool) == Some(true);
    let expected_revision = if creating { Some(0) } else { expected_revision };
    if expected_revision != Some(current_revision) {
        return Err(resource_registry_error(
            ResourceRegistryError::RevisionConflict {
                expected: expected_revision.unwrap_or(0),
                actual: current_revision,
            },
        ));
    }
    let next_revision = if creating {
        0
    } else {
        current_revision.saturating_add(1)
    };
    let next_credential_binding = provider_credential_binding(&provider);
    let key = ProviderRuntimeKey {
        tenant_id: tenant_id.clone(),
        provider_id: provider_id.clone(),
    };
    let previous_binding = runtime.bindings.get(&key).cloned();
    let previous_credential = if let Some(credential) = runtime.credentials.get(&key).cloned() {
        Some(credential)
    } else if runtime.configured_credentials.contains(&key) {
        let binding_digest = previous_credential_binding.as_deref().ok_or_else(|| {
            provider_credential_store_error(ProviderCredentialStoreError::InvalidRecord)
        })?;
        let credential = state
            .provider_credentials
            .load(
                &key.tenant_id,
                &key.provider_id,
                current_revision,
                binding_digest,
            )
            .map_err(provider_credential_store_error)?;
        if credential.is_none() {
            runtime.configured_credentials.remove(&key);
        }
        credential
    } else {
        None
    };
    let was_selected = runtime
        .selections
        .get(tenant_id)
        .is_some_and(|selected| selected == &provider_id);
    let submitted_credential = api_key.as_deref().and_then(normalized_runtime_credential);
    let next_binding = runtime_binding_from_provider(&provider).map(|mut next| {
        if was_selected {
            if let Some(previous) = previous_binding
                .as_ref()
                .filter(|previous| provider_supports_route_model(&provider, &previous.model))
            {
                next.model.clone_from(&previous.model);
            }
        }
        next
    });
    let next_credential = if next_credential_binding.is_none() {
        None
    } else if submitted_credential.is_some() {
        submitted_credential
    } else if previous_credential_binding == next_credential_binding {
        previous_credential.clone()
    } else {
        None
    };
    if let Some(object) = provider.as_object_mut() {
        object.insert(
            "credential_configured".to_string(),
            json!(auth_method == "none" || next_credential.is_some()),
        );
    }
    let wrote_next_credential = if let (Some(binding_digest), Some(credential)) = (
        next_credential_binding.as_deref(),
        next_credential.as_deref(),
    ) {
        state
            .provider_credentials
            .save(
                &key.tenant_id,
                &key.provider_id,
                next_revision,
                binding_digest,
                credential,
            )
            .map_err(provider_credential_store_error)?;
        true
    } else {
        false
    };
    let stored = match state.session_store.put_managed_resource(
        ManagedResourceKind::Provider,
        "tenant",
        tenant_id,
        &provider_id,
        if is_active { "active" } else { "disabled" },
        expected_revision,
        provider,
        Utc::now().timestamp_millis(),
    ) {
        Ok(stored) => stored,
        Err(error) => {
            if wrote_next_credential {
                clear_provider_credential(
                    &state.provider_credentials,
                    &key,
                    next_revision,
                    next_credential_binding.as_deref(),
                )?;
            }
            return Err(resource_registry_error(error));
        }
    };
    if previous_credential.is_some() {
        let _ = clear_provider_credential(
            &state.provider_credentials,
            &key,
            current_revision,
            previous_credential_binding.as_deref(),
        );
    }
    runtime.probes.remove(&key);
    if was_selected && next_binding.is_none() {
        runtime.selections.remove(tenant_id);
    }
    if let Some(binding) = next_binding.clone() {
        runtime.bindings.insert(key.clone(), binding);
    } else {
        runtime.bindings.remove(&key);
    }
    if let Some(credential) = next_credential {
        runtime.configured_credentials.insert(key.clone());
        if next_binding.is_some() {
            runtime.credentials.insert(key.clone(), credential);
        } else {
            runtime.credentials.remove(&key);
        }
    } else {
        runtime.credentials.remove(&key);
        runtime.configured_credentials.remove(&key);
    }
    let selected = runtime
        .selections
        .get(tenant_id)
        .is_some_and(|selected| selected == &provider_id);
    let credential_configured = runtime.configured_credentials.contains(&key);
    Ok(Json(provider_with_runtime_state(
        stored,
        selected,
        next_binding.as_ref(),
        credential_configured,
        None,
    )))
}

fn clear_provider_credential(
    broker: &ProviderCredentialBroker,
    key: &ProviderRuntimeKey,
    provider_revision: u64,
    binding_digest: Option<&str>,
) -> Result<(), (StatusCode, Json<Value>)> {
    let result = match binding_digest {
        Some(binding_digest) => broker.clear(
            &key.tenant_id,
            &key.provider_id,
            provider_revision,
            binding_digest,
        ),
        None => Ok(()),
    };
    result.map_err(provider_credential_store_error)
}

fn provider_credential_store_error(
    error: ProviderCredentialStoreError,
) -> (StatusCode, Json<Value>) {
    let status = match error {
        ProviderCredentialStoreError::Unavailable => StatusCode::SERVICE_UNAVAILABLE,
        ProviderCredentialStoreError::InvalidKey
        | ProviderCredentialStoreError::InvalidRecord
        | ProviderCredentialStoreError::UnsupportedVersion
        | ProviderCredentialStoreError::CorruptRecord => StatusCode::INTERNAL_SERVER_ERROR,
    };
    (
        status,
        Json(json!({
            "code": "provider_credential_store_unavailable",
            "detail": "the provider credential could not be saved securely; unlock the operating system credential store and retry",
        })),
    )
}

async fn validate_llm_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(provider_id): Path<String>,
    Json(request): Json<LlmProviderProbeAction>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    let result = probe_saved_llm_provider(
        Arc::clone(&state),
        &authenticated,
        &provider_id,
        request.expected_revision,
    )
    .await?;
    let runtime = state
        .provider_runtime
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?;
    let key = ProviderRuntimeKey {
        tenant_id: authenticated.workspace.tenant_id.clone(),
        provider_id,
    };
    let binding = runtime.bindings.get(&key);
    let credential_configured = runtime.configured_credentials.contains(&key);
    let selected = runtime
        .selections
        .get(&authenticated.workspace.tenant_id)
        .is_some_and(|selected| selected == &key.provider_id);
    Ok(Json(json!({
        "provider": provider_with_runtime_state(
            result.provider,
            selected,
            binding,
            credential_configured,
            runtime.probes.get(&key),
        ),
        "status": result.outcome.status,
        "probed": result.probed,
        "detail": result.outcome.detail,
        "last_check": result.last_check,
        "response_time_ms": result.outcome.response_time_ms,
        "error_code": result.outcome.error_code,
        "error_message": result.outcome.error_code.map(|_| result.outcome.detail),
        "catalog": provider_probe_catalog(
            &result.provider_type,
            Some(&key.provider_id),
            &result.outcome,
            &result.last_check,
        ),
    })))
}

async fn validate_llm_provider_draft(
    Extension(authenticated): Extension<AuthenticatedContext>,
    State(state): State<Arc<LocalRuntimeState>>,
    Json(request): Json<LlmProviderDraftProbe>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    if request.name.trim().is_empty() {
        return Err(provider_probe_request_error("provider name is required"));
    }
    let provider_type = request.provider_type.trim().to_lowercase();
    if !runtime_provider_supported(&provider_type) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": "unsupported local provider type" })),
        ));
    }

    let base_url = normalized_runtime_provider_base_url(&provider_type, &request.base_url)?;
    let auth_method = request.auth_method.trim().to_lowercase();
    if !matches!(auth_method.as_str(), "api_key" | "none") {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": "unsupported local provider auth method" })),
        ));
    }
    let credential = request
        .api_key
        .as_deref()
        .and_then(normalized_runtime_credential);
    if auth_method == "api_key" && credential.is_none() {
        return Ok(Json(json!({
            "provider": null,
            "status": "needs_credentials",
            "probed": false,
            "detail": "Enter a provider credential before testing this connection.",
            "last_check": null,
            "response_time_ms": null,
            "error_code": "credential_unavailable",
            "error_message": "Enter a provider credential before testing this connection.",
            "catalog": null,
        })));
    }
    let last_check = now_iso();
    let outcome = state
        .provider_probe
        .probe(ProviderProbeRequest {
            provider_type: provider_type.clone(),
            base_url,
            auth_method,
            credential,
        })
        .await;
    Ok(Json(json!({
        "provider": null,
        "status": outcome.status,
        "probed": true,
        "detail": outcome.detail,
        "last_check": last_check,
        "response_time_ms": outcome.response_time_ms,
        "error_code": outcome.error_code,
        "error_message": outcome.error_code.map(|_| outcome.detail),
        "catalog": provider_probe_catalog(
            &provider_type,
            None,
            &outcome,
            &last_check,
        ),
    })))
}

async fn discover_llm_provider_models(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(provider_id): Path<String>,
    Json(request): Json<LlmProviderProbeAction>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    let result = probe_saved_llm_provider(
        state,
        &authenticated,
        &provider_id,
        request.expected_revision,
    )
    .await?;
    Ok(Json(provider_probe_catalog(
        &result.provider_type,
        Some(&provider_id),
        &result.outcome,
        &result.last_check,
    )))
}

struct SavedProviderProbeResult {
    provider: Value,
    provider_type: String,
    outcome: ProviderProbeOutcome,
    last_check: String,
    probed: bool,
}

async fn probe_saved_llm_provider(
    state: Arc<LocalRuntimeState>,
    authenticated: &AuthenticatedContext,
    provider_id: &str,
    expected_revision: u64,
) -> Result<SavedProviderProbeResult, (StatusCode, Json<Value>)> {
    let tenant_id = authenticated.workspace.tenant_id.clone();
    let provider = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            &tenant_id,
            provider_id,
        )
        .map_err(local_store_error)?
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))?;
    let revision = provider
        .get("revision")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    if revision != expected_revision {
        return Err(provider_probe_revision_conflict(
            expected_revision,
            revision,
        ));
    }
    let binding_snapshot = provider_probe_binding(&provider)?;
    let provider_type = binding_snapshot.provider_type.clone();
    let base_url = binding_snapshot.base_url.clone();
    let auth_method = binding_snapshot.auth_method.clone();
    let binding_digest = binding_snapshot.binding_digest.clone();
    let credential = if auth_method == "api_key" {
        let broker = state.provider_credentials.clone();
        let tenant_id = tenant_id.clone();
        let provider_id = provider_id.to_string();
        let binding_digest = binding_digest.clone();
        tokio::task::spawn_blocking(move || {
            broker.load(&tenant_id, &provider_id, revision, &binding_digest)
        })
        .await
        .map_err(|_| provider_credential_store_error(ProviderCredentialStoreError::Unavailable))?
        .map_err(provider_credential_store_error)?
    } else {
        None
    };
    let (outcome, probed) = if auth_method == "api_key" && credential.is_none() {
        (
            ProviderProbeOutcome {
                status: "needs_credentials",
                detail:
                    "The saved provider credential is unavailable. Enter it again before testing.",
                error_code: Some("credential_unavailable"),
                response_time_ms: 0,
                models: Vec::new(),
            },
            false,
        )
    } else {
        (
            state
                .provider_probe
                .probe(ProviderProbeRequest {
                    provider_type: provider_type.clone(),
                    base_url,
                    auth_method,
                    credential,
                })
                .await,
            true,
        )
    };
    // Provider mutations acquire the same runtime mutex before changing SQLite. Holding it for
    // this final synchronous compare-and-store closes the revision recheck/write race without
    // ever carrying a std::sync::MutexGuard across an await.
    let mut runtime = state
        .provider_runtime
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?;
    let current = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            &tenant_id,
            provider_id,
        )
        .map_err(local_store_error)?
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))?;
    let current_revision = current.get("revision").and_then(Value::as_u64).unwrap_or(0);
    let current_digest = provider_probe_binding(&current)
        .ok()
        .map(|binding| binding.binding_digest);
    if current_revision != revision || current_digest.as_deref() != Some(&binding_digest) {
        return Err(provider_probe_revision_conflict(revision, current_revision));
    }
    let last_check = now_iso();
    let key = ProviderRuntimeKey {
        tenant_id,
        provider_id: provider_id.to_string(),
    };
    runtime.probes.insert(
        key,
        ProviderProbeSnapshot {
            provider_revision: revision,
            binding_digest,
            status: outcome.status.to_string(),
            detail: outcome.detail.to_string(),
            last_check: last_check.clone(),
            response_time_ms: outcome.response_time_ms,
            error_code: outcome.error_code.map(str::to_string),
        },
    );
    drop(runtime);
    Ok(SavedProviderProbeResult {
        provider: current,
        provider_type,
        outcome,
        last_check,
        probed,
    })
}

fn provider_probe_binding(
    provider: &Value,
) -> Result<ProviderProbeBindingSnapshot, (StatusCode, Json<Value>)> {
    let provider_type = provider
        .get("provider_type")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_lowercase();
    if !runtime_provider_supported(&provider_type) {
        return Err(provider_probe_request_error(
            "unsupported local provider type",
        ));
    }
    let base_url = provider
        .get("base_url")
        .and_then(Value::as_str)
        .ok_or_else(|| provider_probe_request_error("provider base URL is required"))?;
    let base_url = normalized_runtime_provider_base_url(&provider_type, base_url)?;
    let auth_method = provider
        .get("auth_method")
        .and_then(Value::as_str)
        .unwrap_or("api_key")
        .trim()
        .to_lowercase();
    if !matches!(auth_method.as_str(), "api_key" | "none") {
        return Err(provider_probe_request_error(
            "unsupported local provider auth method",
        ));
    }
    let digest = provider_credential_binding_digest(&provider_type, &base_url, &auth_method);
    Ok(ProviderProbeBindingSnapshot {
        provider_type,
        base_url,
        auth_method,
        binding_digest: digest,
    })
}

fn provider_probe_catalog(
    provider_type: &str,
    provider_id: Option<&str>,
    outcome: &ProviderProbeOutcome,
    discovered_at: &str,
) -> Value {
    json!({
        "provider_type": provider_type,
        "provider_id": provider_id,
        "availability": if outcome.healthy() { "available" } else { "unavailable" },
        "source": outcome.healthy().then_some("provider-api"),
        "discovered_at": discovered_at,
        "detail": outcome.detail,
        "models": {
            "chat": outcome.models.iter().map(|model| model.id.as_str()).collect::<Vec<_>>(),
            "embedding": [],
            "rerank": [],
        },
    })
}

fn provider_probe_request_error(detail: &'static str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({ "detail": detail })),
    )
}

fn provider_probe_revision_conflict(expected: u64, actual: u64) -> (StatusCode, Json<Value>) {
    (
        StatusCode::CONFLICT,
        Json(json!({
            "code": "provider_revision_changed",
            "detail": "the provider changed while the connection test was running; retry with the latest configuration",
            "expected_revision": expected,
            "actual_revision": actual,
        })),
    )
}

async fn get_llm_provider_usage(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(provider_id): Path<String>,
) -> LocalJsonResult {
    let tenant_id = &authenticated.workspace.tenant_id;
    state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            tenant_id,
            &provider_id,
        )
        .map_err(local_store_error)?
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))?;
    Ok(Json(json!({
        "provider_id": provider_id,
        "tenant_id": tenant_id,
        "statistics": [],
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

fn validated_local_provider_base_url(raw_url: &str) -> Result<String, (StatusCode, Json<Value>)> {
    let raw_url = raw_url.trim().trim_end_matches('/');
    let url = Url::parse(raw_url).map_err(|_| invalid_local_provider_base_url())?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.host_str().is_none()
        || url.port() == Some(0)
        || url.query().is_some()
        || url.fragment().is_some()
        || (url.scheme() == "http" && !local_provider_host(&url))
    {
        return Err(invalid_local_provider_base_url());
    }
    Ok(raw_url.to_string())
}

fn normalized_runtime_provider_base_url(
    provider_type: &str,
    raw_url: &str,
) -> Result<String, (StatusCode, Json<Value>)> {
    let base_url = validated_local_provider_base_url(raw_url)?;
    if provider_type != "anthropic" {
        return Ok(base_url);
    }
    let mut url = Url::parse(&base_url).map_err(|_| invalid_local_provider_base_url())?;
    if url.path().is_empty() || url.path() == "/" {
        url.set_path("/v1");
    }
    Ok(url.as_str().trim_end_matches('/').to_string())
}

fn local_provider_host(url: &Url) -> bool {
    match url.host() {
        Some(Host::Domain(domain)) => domain.eq_ignore_ascii_case("localhost"),
        Some(Host::Ipv4(address)) => address.is_loopback(),
        Some(Host::Ipv6(address)) => address.is_loopback(),
        None => false,
    }
}

fn invalid_local_provider_base_url() -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({
            "detail": "provider base URL must be a valid HTTPS endpoint or a loopback HTTP endpoint without userinfo, query, or fragment"
        })),
    )
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

fn provider_credential_binding(provider: &Value) -> Option<String> {
    let provider_type = provider.get("provider_type")?.as_str()?.trim();
    let base_url = provider.get("base_url")?.as_str()?.trim();
    let auth_method = provider
        .get("auth_method")
        .and_then(Value::as_str)
        .unwrap_or("api_key")
        .trim();
    if !runtime_provider_supported(provider_type) || auth_method != "api_key" {
        return None;
    }
    let base_url = normalized_runtime_provider_base_url(provider_type, base_url).ok()?;
    Some(provider_credential_binding_digest(
        provider_type,
        &base_url,
        auth_method,
    ))
}

fn runtime_provider_supported(provider_type: &str) -> bool {
    matches!(provider_type, "openai" | "openai_compatible" | "anthropic")
}

fn runtime_binding_from_provider(provider: &Value) -> Option<ProviderRuntimeBinding> {
    if provider.get("is_active").and_then(Value::as_bool) != Some(true) {
        return None;
    }
    let provider_type = provider.get("provider_type")?.as_str()?.trim();
    let base_url = provider.get("base_url")?.as_str()?.trim();
    let model = provider.get("llm_model")?.as_str()?.trim();
    let auth_method = provider
        .get("auth_method")
        .and_then(Value::as_str)
        .unwrap_or("api_key")
        .trim();
    let base_url = normalized_runtime_provider_base_url(provider_type, base_url).ok()?;
    if !runtime_provider_supported(provider_type)
        || base_url.is_empty()
        || model.is_empty()
        || !matches!(auth_method, "api_key" | "none")
    {
        return None;
    }
    Some(ProviderRuntimeBinding {
        provider_type: provider_type.to_string(),
        base_url,
        model: model.to_string(),
        auth_method: auth_method.to_string(),
    })
}

fn runtime_binding_for_route_target(
    provider: &Value,
    target: &LlmRouteTarget,
) -> Result<ProviderRuntimeBinding, (StatusCode, Json<Value>)> {
    let mut binding = runtime_binding_from_provider(provider).ok_or_else(|| {
        routing_policy_validation_error(format!(
            "provider {} must be active and configured",
            target.provider_id
        ))
    })?;
    if !provider_supports_route_model(provider, &target.model_id) {
        return Err(routing_policy_validation_error(format!(
            "model {} is not configured for provider {}",
            target.model_id, target.provider_id
        )));
    }
    binding.model.clone_from(&target.model_id);
    Ok(binding)
}

fn provider_supports_route_model(provider: &Value, model_id: &str) -> bool {
    provider
        .get("llm_model")
        .and_then(Value::as_str)
        .is_some_and(|model| model.trim() == model_id)
        || provider
            .get("allowed_models")
            .and_then(Value::as_array)
            .is_some_and(|models| {
                models
                    .iter()
                    .any(|model| model.as_str().is_some_and(|model| model.trim() == model_id))
            })
}

fn routing_targets_for_role(
    policy: &Value,
    role: LlmWorkloadRole,
) -> Result<Vec<LlmRouteTarget>, String> {
    let roles_value = policy
        .get("roles")
        .and_then(Value::as_object)
        .ok_or_else(|| "routing policy roles must be an object".to_string())?;
    if roles_value.len() != 4
        || ["default", "fast", "coding", "vision"]
            .into_iter()
            .any(|role| !roles_value.contains_key(role))
    {
        return Err("routing policy roles must contain every supported role".to_string());
    }
    let roles = serde_json::from_value::<LlmRoutingRoles>(Value::Object(roles_value.clone()))
        .map_err(|error| error.to_string())?;
    let primary = configured_routing_target(&roles, role)
        .cloned()
        .or_else(|| roles.default.clone());
    let mut seen = HashSet::new();
    let mut targets = Vec::new();
    if let Some(primary) = primary {
        ensure_stored_route_target(&primary)?;
        seen.insert(primary.clone());
        targets.push(primary);
    }
    let fallbacks = policy
        .get("fallbacks")
        .and_then(Value::as_array)
        .ok_or_else(|| "routing policy fallbacks must be an array".to_string())?;
    for fallback in fallbacks {
        let fallback = serde_json::from_value::<LlmRouteTarget>(fallback.clone())
            .map_err(|error| error.to_string())?;
        ensure_stored_route_target(&fallback)?;
        if seen.insert(fallback.clone()) {
            targets.push(fallback);
        }
    }
    Ok(targets)
}

fn ensure_stored_route_target(target: &LlmRouteTarget) -> Result<(), String> {
    if target.provider_id.trim().is_empty() || target.model_id.trim().is_empty() {
        return Err("routing policy target identifiers cannot be empty".to_string());
    }
    Ok(())
}

fn workload_role_for_capability(capability: ConversationCapabilityMode) -> LlmWorkloadRole {
    match capability {
        ConversationCapabilityMode::Code => LlmWorkloadRole::Coding,
        ConversationCapabilityMode::Work | ConversationCapabilityMode::Unavailable => {
            LlmWorkloadRole::Default
        }
    }
}

fn configured_routing_target(
    roles: &LlmRoutingRoles,
    role: LlmWorkloadRole,
) -> Option<&LlmRouteTarget> {
    match role {
        LlmWorkloadRole::Default => roles.default.as_ref(),
        LlmWorkloadRole::Fast => roles.fast.as_ref(),
        LlmWorkloadRole::Coding => roles.coding.as_ref(),
        LlmWorkloadRole::Vision => roles.vision.as_ref(),
    }
}

fn llm_from_runtime_binding(
    binding: ProviderRuntimeBinding,
    credential: Option<String>,
) -> Option<Arc<dyn LlmPort>> {
    if binding.auth_method != "none" && credential.is_none() {
        return None;
    }
    if matches!(
        binding.provider_type.as_str(),
        "openai" | "openai_compatible"
    ) {
        let llm = HttpLlm::new(binding.base_url, binding.model);
        let llm = if let Some(credential) = credential {
            llm.with_api_key(credential)
        } else {
            llm
        };
        return Some(Arc::new(llm));
    }
    if binding.provider_type == "anthropic" {
        let llm = AnthropicLlm::new(binding.base_url, binding.model);
        let llm = if let Some(credential) = credential {
            llm.with_api_key(credential)
        } else {
            llm
        };
        return Some(Arc::new(AnthropicAgentLlm { inner: llm }));
    }
    None
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
    credential_configured: bool,
) -> &'static str {
    if provider.get("is_active").and_then(Value::as_bool) != Some(true) {
        return "disabled";
    }
    if runtime_binding_from_provider(provider).is_none() {
        return "not_configured";
    }
    let Some(binding) = binding else {
        return "not_configured";
    };
    let auth_method = provider
        .get("auth_method")
        .and_then(Value::as_str)
        .unwrap_or("api_key");
    if auth_method != "none" && !credential_configured {
        return "needs_credentials";
    }
    debug_assert_eq!(binding.auth_method, auth_method);
    "configuration_valid"
}

fn provider_with_runtime_state(
    mut provider: Value,
    selected: bool,
    binding: Option<&ProviderRuntimeBinding>,
    credential_configured: bool,
    probe: Option<&ProviderProbeSnapshot>,
) -> Value {
    let credential_configured =
        binding.is_some_and(|binding| binding.auth_method == "none") || credential_configured;
    let status = provider_configuration_status(&provider, binding, credential_configured);
    let provider_revision = provider
        .get("revision")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let current_binding_digest = provider_probe_binding(&provider)
        .ok()
        .map(|binding| binding.binding_digest);
    let probe = probe.filter(|probe| {
        probe.provider_revision == provider_revision
            && current_binding_digest.as_deref() == Some(probe.binding_digest.as_str())
    });
    let credential_source = if provider
        .get("auth_method")
        .and_then(Value::as_str)
        .unwrap_or("api_key")
        == "none"
    {
        "none"
    } else {
        "system_vault"
    };
    if let Some(object) = provider.as_object_mut() {
        object.insert("credential_source".to_string(), json!(credential_source));
        object.insert(
            "credential_configured".to_string(),
            json!(credential_configured),
        );
        object.insert("runtime_selected".to_string(), json!(selected));
        object.insert(
            "health_status".to_string(),
            json!(probe.map_or(status, |probe| probe.status.as_str())),
        );
        if let Some(probe) = probe {
            object.insert("health_last_check".to_string(), json!(probe.last_check));
            object.insert(
                "response_time_ms".to_string(),
                json!(probe.response_time_ms),
            );
            object.insert("health_detail".to_string(), json!(probe.detail));
            object.insert("error_code".to_string(), json!(probe.error_code));
            object.insert(
                "error_message".to_string(),
                json!(probe.error_code.as_ref().map(|_| probe.detail.as_str())),
            );
        }
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

fn my_work_capability_mode(
    capability_mode: ConversationCapabilityMode,
) -> Option<ConversationCapabilityMode> {
    match capability_mode {
        ConversationCapabilityMode::Work | ConversationCapabilityMode::Code => {
            Some(capability_mode)
        }
        ConversationCapabilityMode::Unavailable => None,
    }
}

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
enum DesktopMyWorkAuthorityKind {
    DesktopRun,
}

#[derive(Debug, Serialize)]
struct DesktopMyWorkItem {
    id: String,
    authority_kind: DesktopMyWorkAuthorityKind,
    authority_id: String,
    attempt_number: Option<u64>,
    run_id: String,
    conversation_id: String,
    workspace_id: Option<String>,
    project_id: String,
    title: String,
    capability_mode: Option<ConversationCapabilityMode>,
    group: &'static str,
    status: DesktopRunStatus,
    required_action: &'static str,
    revision: u64,
    permission_profile: DesktopPermissionProfile,
    environment: Option<DesktopExecutionEnvironment>,
    error: Option<String>,
    created_at: String,
    updated_at: String,
    last_heartbeat_at: Option<String>,
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
        items.push(DesktopMyWorkItem {
            id: run.id.clone(),
            authority_kind: DesktopMyWorkAuthorityKind::DesktopRun,
            authority_id: run.id.clone(),
            attempt_number: None,
            run_id: run.id,
            conversation_id: run.conversation_id,
            workspace_id: conversation.workspace_id,
            project_id: run.project_id,
            title: conversation.title,
            capability_mode: my_work_capability_mode(conversation.capability_mode),
            group,
            status: run.status,
            required_action: my_work_required_action(run.status),
            revision: run.revision,
            permission_profile: run.permission_profile,
            environment: run.environment,
            error: run.error,
            created_at: run.created_at,
            updated_at: run.updated_at,
            last_heartbeat_at: run.last_heartbeat_at,
        });
    }

    Ok(Json(json!({
        "project_id": project_id,
        "items": items,
        "total": items.len(),
    })))
}

async fn list_workspaces(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id)): Path<(String, String)>,
) -> LocalJsonResult {
    if tenant_id != authenticated.workspace.tenant_id {
        return Err(active_workspace_scope_error());
    }
    ensure_active_project(&authenticated, &project_id)?;
    let workspaces = state
        .session_store
        .list_workspaces(&project_id)
        .map_err(local_store_error)?
        .into_iter()
        .filter(|workspace| workspace["tenant_id"] == tenant_id)
        .collect::<Vec<_>>();
    Ok(Json(json!({ "items": workspaces })))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CreateWorkspaceBody {
    name: Option<String>,
    description: Option<String>,
    metadata: Option<serde_json::Map<String, Value>>,
    use_case: Option<WorkspaceUseCase>,
    collaboration_mode: Option<WorkspaceCollaborationMode>,
    sandbox_code_root: Option<String>,
}

async fn create_workspace(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Json(body): Json<CreateWorkspaceBody>,
) -> LocalJsonResult {
    if tenant_id != authenticated.workspace.tenant_id {
        return Err(active_workspace_scope_error());
    }
    ensure_active_project(&authenticated, &project_id)?;
    let now = now_iso();
    let name = body
        .name
        .map(|name| name.trim().to_string())
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| "Local workspace".to_string());
    let workspace = workspace_value(
        format!("local-workspace-{}", Uuid::new_v4()),
        &tenant_id,
        &project_id,
        WorkspaceCreateAttributes {
            name,
            description: body.description,
            metadata: body.metadata,
            use_case: body.use_case.unwrap_or_default(),
            collaboration_mode: body.collaboration_mode.unwrap_or_default(),
            sandbox_code_root: body.sandbox_code_root,
        },
        &now,
    );
    state
        .session_store
        .insert_workspace(&workspace)
        .map_err(local_store_error)?;
    Ok(Json(workspace))
}

async fn list_workspace_messages(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
) -> LocalJsonResult {
    ensure_workspace_scope(
        &state,
        &authenticated,
        &tenant_id,
        &project_id,
        &workspace_id,
    )?;
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
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<WorkspaceMessageBody>,
) -> LocalJsonResult {
    ensure_workspace_scope(
        &state,
        &authenticated,
        &tenant_id,
        &project_id,
        &workspace_id,
    )?;
    let message = json!({
        "id": format!("local-message-{}", Uuid::new_v4()),
        "workspace_id": &workspace_id,
        "parent_message_id": body.parent_message_id,
        "sender_type": "human",
        "sender_id": "local-user",
        "content": body.content,
        "mentions": body.mentions.unwrap_or_default(),
        "created_at": now_iso(),
        "metadata": { "runtime": "local" },
    });
    state
        .append_workspace_message(&workspace_id, message.clone())
        .map_err(local_store_error)?;
    Ok(Json(message))
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

#[derive(Debug, Default, PartialEq, Eq)]
enum WorkspaceIdPatch {
    #[default]
    Missing,
    Null,
    Value(String),
}

impl<'de> Deserialize<'de> for WorkspaceIdPatch {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct WorkspaceIdPatchVisitor;

        impl<'de> Visitor<'de> for WorkspaceIdPatchVisitor {
            type Value = WorkspaceIdPatch;

            fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str("a workspace ID string or null")
            }

            fn visit_none<E>(self) -> Result<Self::Value, E> {
                Ok(WorkspaceIdPatch::Null)
            }

            fn visit_unit<E>(self) -> Result<Self::Value, E> {
                Ok(WorkspaceIdPatch::Null)
            }

            fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
            where
                D: Deserializer<'de>,
            {
                String::deserialize(deserializer).map(WorkspaceIdPatch::Value)
            }
        }

        deserializer.deserialize_option(WorkspaceIdPatchVisitor)
    }
}

#[derive(Deserialize)]
struct ConversationModeBody {
    #[serde(default)]
    workspace_id: WorkspaceIdPatch,
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
        let changes_workspace_scope = match &body.workspace_id {
            WorkspaceIdPatch::Missing => false,
            WorkspaceIdPatch::Null => conversation.workspace_id.is_some(),
            WorkspaceIdPatch::Value(workspace_id) => {
                conversation.workspace_id.as_deref() != Some(workspace_id.as_str())
            }
        };
        if is_local_demo_conversation(&conversation.id) && changes_workspace_scope {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({
                    "detail": "local demo conversation workspace scope is immutable"
                })),
            ));
        }
        match body.workspace_id {
            WorkspaceIdPatch::Missing => {}
            WorkspaceIdPatch::Null => conversation.workspace_id = None,
            WorkspaceIdPatch::Value(workspace_id) => {
                ensure_active_workspace(&state, &authenticated, &workspace_id)?;
                conversation.workspace_id = Some(workspace_id);
            }
        }
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
    project_id: String,
    limit: Option<i64>,
    from_time_us: Option<i64>,
    from_counter: Option<i64>,
    before_time_us: Option<i64>,
    before_counter: Option<i64>,
}

struct ValidatedConversationMessagesQuery {
    project_id: String,
    limit: usize,
    from: Option<DesktopTimelineCursor>,
    before: Option<DesktopTimelineCursor>,
}

impl ConversationMessagesQuery {
    fn validated(&self) -> Result<ValidatedConversationMessagesQuery, (StatusCode, Json<Value>)> {
        let project_id = self.project_id.trim();
        if project_id.is_empty() {
            return Err(conversation_messages_query_error("project_id is required"));
        }
        let limit = self.limit.unwrap_or(DEFAULT_TIMELINE_LIMIT);
        if !(1..=MAX_TIMELINE_LIMIT).contains(&limit) {
            return Err(conversation_messages_query_error(
                "limit must be between 1 and 500",
            ));
        }
        let from_time_us = self.from_time_us.unwrap_or_default();
        let from_counter = self.from_counter.unwrap_or_default();
        if from_time_us < 0 || from_counter < 0 {
            return Err(conversation_messages_query_error(
                "from cursors must be greater than or equal to 0",
            ));
        }
        if self.before_time_us.is_some_and(|value| value < 0)
            || self.before_counter.is_some_and(|value| value < 0)
        {
            return Err(conversation_messages_query_error(
                "before cursors must be greater than or equal to 0",
            ));
        }
        let limit = usize::try_from(limit)
            .map_err(|_| conversation_messages_query_error("limit must be between 1 and 500"))?;
        let before = self.before_time_us.map(|time_us| DesktopTimelineCursor {
            time_us,
            counter: self.before_counter.unwrap_or_default(),
        });
        let from = (from_time_us > 0).then_some(DesktopTimelineCursor {
            time_us: from_time_us,
            counter: from_counter,
        });
        Ok(ValidatedConversationMessagesQuery {
            project_id: project_id.to_string(),
            limit,
            from,
            before,
        })
    }
}

fn conversation_messages_query_error(detail: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({ "detail": detail })),
    )
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
    let query = query.validated()?;
    ensure_active_project(&authenticated, &query.project_id)?;
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let DesktopTimelinePage {
        items,
        has_more,
        first_cursor,
        last_cursor,
    } = state
        .session_store
        .timeline_page(&conversation_id, query.limit, query.from, query.before)
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
    let total = items.len();
    Ok(Json(json!({
        "conversationId": conversation_id,
        "timeline": items,
        "approval_requests": approval_requests,
        "artifact_versions": artifact_versions,
        "artifact_deliveries": artifact_deliveries,
        "tool_invocations": tool_invocations,
        "total": total,
        "has_more": has_more,
        "first_time_us": first_cursor.map(|cursor| cursor.time_us),
        "first_counter": first_cursor.map(|cursor| cursor.counter),
        "last_time_us": last_cursor.map(|cursor| cursor.time_us),
        "last_counter": last_cursor.map(|cursor| cursor.counter),
    })))
}

#[derive(Deserialize)]
struct RunConversationBody {
    message: String,
    message_id: Option<String>,
    project_id: Option<String>,
}

fn client_turn_payload_hash(conversation_id: &str, project_id: &str, message: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"agistack-local-client-turn:v1\0");
    for value in [conversation_id, project_id, message] {
        hasher.update((value.len() as u64).to_be_bytes());
        hasher.update(value.as_bytes());
    }
    format!("{:x}", hasher.finalize())
}

async fn run_conversation_message(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
    Json(body): Json<RunConversationBody>,
) -> LocalJsonResult {
    let message_id = match body.message_id {
        Some(message_id) if message_id.trim().is_empty() || message_id.chars().count() > 255 => {
            return Err((
                StatusCode::BAD_REQUEST,
                Json(json!({
                    "code": "INVALID_MESSAGE_ID",
                    "detail": "message_id must be a non-empty string of at most 255 characters",
                })),
            ));
        }
        Some(message_id) => message_id,
        None => format!("local-message-{}", Uuid::new_v4()),
    };
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
    let payload_hash = client_turn_payload_hash(&conversation_id, &project_id, &body.message);
    let created = state
        .session_store
        .claim_client_turn(&conversation_id, &message_id, &payload_hash, &now_iso())
        .map_err(|error| match error {
            DesktopClientTurnClaimError::PayloadConflict => (
                StatusCode::CONFLICT,
                Json(json!({
                    "code": "MESSAGE_ID_CONFLICT",
                    "detail": "message_id is already bound to a different request",
                    "message_id": message_id,
                })),
            ),
            DesktopClientTurnClaimError::Storage(error) => local_store_error(error),
        })?;
    if !created {
        return Ok(Json(json!({
            "queued": false,
            "created": false,
            "replayed": true,
            "message_id": message_id,
        })));
    }
    let run_state = Arc::clone(&state);
    let response_message_id = message_id.clone();
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
    Ok(Json(json!({
        "queued": true,
        "created": true,
        "replayed": false,
        "message_id": response_message_id,
    })))
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
            ensure_checkpoint_run_ownership(&state, &run)?;
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
            if let Err(error) = ensure_checkpoint_control_authority(&state, &run).await {
                state.release_agent_run_if_control(&conversation.id, &control);
                return Err(error);
            }
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
    if let Some(run) = engine_run.as_ref() {
        if let Err(error) = ensure_checkpoint_control_authority(&state, run).await {
            state.release_agent_run_if_control(&conversation.id, &control);
            return Err(error);
        }
    }

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

struct FailoverLlm {
    candidates: Vec<Arc<dyn LlmPort>>,
    candidate_timeout: std::time::Duration,
}

impl FailoverLlm {
    const CANDIDATE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(45);

    fn from_candidates(candidates: Vec<Arc<dyn LlmPort>>) -> Arc<dyn LlmPort> {
        Arc::new(Self {
            candidates,
            candidate_timeout: Self::CANDIDATE_TIMEOUT,
        })
    }

    #[cfg(test)]
    fn from_candidates_with_timeout(
        candidates: Vec<Arc<dyn LlmPort>>,
        candidate_timeout: std::time::Duration,
    ) -> Arc<dyn LlmPort> {
        Arc::new(Self {
            candidates,
            candidate_timeout,
        })
    }

    async fn attempt<T, F, Fut>(&self, mut operation: F) -> CoreResult<T>
    where
        F: FnMut(Arc<dyn LlmPort>) -> Fut,
        Fut: std::future::Future<Output = CoreResult<T>>,
    {
        let mut last_error = None;
        for candidate in &self.candidates {
            match tokio::time::timeout(self.candidate_timeout, operation(Arc::clone(candidate)))
                .await
            {
                Ok(Ok(value)) => return Ok(value),
                Ok(Err(error)) => last_error = Some(error),
                Err(_) => {
                    last_error = Some(CoreError::Llm(format!(
                        "model_timeout: LLM routing candidate exceeded {} ms",
                        self.candidate_timeout.as_millis()
                    )));
                }
            }
        }
        Err(last_error.unwrap_or_else(|| {
            CoreError::Llm("model_unconfigured: no usable LLM routing targets".to_string())
        }))
    }
}

#[async_trait]
impl LlmPort for FailoverLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        self.attempt(|candidate| async move { candidate.extract_memory(episode).await })
            .await
    }

    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        self.attempt(|candidate| async move { candidate.extract_relationships(memory).await })
            .await
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        self.attempt(|candidate| async move {
            candidate
                .decide(goal, round, transcript, available_tools)
                .await
        })
        .await
    }
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

    #[derive(Debug, PartialEq, Eq)]
    struct CheckpointOperationCounts {
        loads: u64,
        saves: u64,
        deletes: u64,
    }

    struct CountingCheckpointStore {
        inner: Arc<dyn CheckpointStore>,
        loads: AtomicU64,
        saves: AtomicU64,
        deletes: AtomicU64,
    }

    impl CountingCheckpointStore {
        fn new(inner: Arc<dyn CheckpointStore>) -> Self {
            Self {
                inner,
                loads: AtomicU64::new(0),
                saves: AtomicU64::new(0),
                deletes: AtomicU64::new(0),
            }
        }

        fn reset(&self) {
            self.loads.store(0, Ordering::SeqCst);
            self.saves.store(0, Ordering::SeqCst);
            self.deletes.store(0, Ordering::SeqCst);
        }

        fn operation_counts(&self) -> CheckpointOperationCounts {
            CheckpointOperationCounts {
                loads: self.loads.load(Ordering::SeqCst),
                saves: self.saves.load(Ordering::SeqCst),
                deletes: self.deletes.load(Ordering::SeqCst),
            }
        }
    }

    #[async_trait]
    impl CheckpointStore for CountingCheckpointStore {
        async fn save(&self, state: &SessionState) -> CoreResult<()> {
            self.saves.fetch_add(1, Ordering::SeqCst);
            self.inner.save(state).await
        }

        async fn load(&self, session_id: &str) -> CoreResult<Option<SessionState>> {
            self.loads.fetch_add(1, Ordering::SeqCst);
            self.inner.load(session_id).await
        }

        async fn delete(&self, session_id: &str) -> CoreResult<()> {
            self.deletes.fetch_add(1, Ordering::SeqCst);
            self.inner.delete(session_id).await
        }
    }

    struct UnavailableProviderCredentialStore;

    impl ProviderCredentialStore for UnavailableProviderCredentialStore {
        fn save(&self, _account: &str, _value: &str) -> Result<(), ProviderCredentialStoreError> {
            Err(ProviderCredentialStoreError::Unavailable)
        }

        fn load(&self, _account: &str) -> Result<Option<String>, ProviderCredentialStoreError> {
            Err(ProviderCredentialStoreError::Unavailable)
        }

        fn clear(&self, _account: &str) -> Result<(), ProviderCredentialStoreError> {
            Err(ProviderCredentialStoreError::Unavailable)
        }
    }

    fn test_root() -> PathBuf {
        std::env::temp_dir().join(format!("agistack-local-runtime-{}", Uuid::new_v4()))
    }

    fn run_test_git(root: &FsPath, args: &[&str]) -> String {
        let output = std::process::Command::new("git")
            .arg("-C")
            .arg(root)
            .args(args)
            .output()
            .expect("run git test command");
        assert!(
            output.status.success(),
            "git {:?} failed: {}",
            args,
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).expect("git output must be UTF-8")
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
        state.mock_llm_enabled.store(1, Ordering::Release);
        state
    }

    fn test_state_with_counting_checkpoints(
        token: &str,
    ) -> (Arc<LocalRuntimeState>, Arc<CountingCheckpointStore>) {
        let root = test_root();
        let tool_host = LocalToolHost::new(&root).expect("tool host");
        let inner: Arc<dyn CheckpointStore> =
            Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        let checkpoints = Arc::new(CountingCheckpointStore::new(inner));
        let checkpoint_store: Arc<dyn CheckpointStore> = checkpoints.clone();
        let session_store = DesktopSessionStore::in_memory().expect("session store");
        let state = Arc::new(
            LocalRuntimeState::new(
                root,
                tool_host,
                checkpoint_store,
                token.to_string(),
                session_store,
            )
            .expect("local runtime state"),
        );
        state.mock_llm_enabled.store(1, Ordering::Release);
        state
            .session_store
            .seed_test_session(token)
            .expect("authenticated test session");
        (state, checkpoints)
    }

    fn test_state_with_file_checkpoint(token: &str) -> (Arc<LocalRuntimeState>, PathBuf, PathBuf) {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create test root");
        let checkpoint_path = root.join("checkpoints.db");
        let tool_host = LocalToolHost::new(&root).expect("tool host");
        let checkpoints = Arc::new(
            SqliteCheckpointStore::open(&checkpoint_path.to_string_lossy())
                .expect("file checkpoint store"),
        );
        let session_store = DesktopSessionStore::in_memory().expect("session store");
        let state = Arc::new(
            LocalRuntimeState::new(
                root.clone(),
                tool_host,
                checkpoints,
                token.to_string(),
                session_store,
            )
            .expect("local runtime state"),
        );
        state.mock_llm_enabled.store(1, Ordering::Release);
        state
            .session_store
            .seed_test_session(token)
            .expect("authenticated test session");
        (state, checkpoint_path, root)
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

    fn seed_plan_conversation(state: &LocalRuntimeState, conversation_id: &str) {
        state
            .session_store
            .insert_conversation(&LocalConversation {
                id: conversation_id.to_string(),
                project_id: "local-project".to_string(),
                tenant_id: "local".to_string(),
                title: "Client turn idempotency".to_string(),
                workspace_id: Some("local-workspace".to_string()),
                capability_mode: ConversationCapabilityMode::Unavailable,
                current_mode: ConversationRunMode::Plan,
                created_at: now_iso(),
                updated_at: now_iso(),
            })
            .expect("insert plan conversation");
    }

    fn conversation_message_request(
        credential: &str,
        conversation_id: &str,
        message_id: &str,
        message: &str,
    ) -> Request<Body> {
        authenticated_json_request(
            "POST",
            &format!("/api/v1/agent/conversations/{conversation_id}/messages"),
            credential,
            json!({
                "project_id": "local-project",
                "message": message,
                "message_id": message_id,
            }),
        )
    }

    async fn wait_for_agent_message_completion(
        state: &LocalRuntimeState,
        conversation_id: &str,
    ) -> Vec<Value> {
        for _ in 0..200 {
            let timeline = state
                .session_store
                .timeline(conversation_id, 100)
                .expect("timeline");
            let has_assistant = timeline
                .iter()
                .any(|event| event["type"] == "assistant_message");
            let is_active = state
                .agent_runs
                .lock()
                .expect("active agent runs")
                .contains_key(conversation_id);
            if has_assistant && !is_active {
                return timeline;
            }
            tokio::task::yield_now().await;
        }
        panic!("agent message did not finish");
    }

    async fn response_json(response: axum::response::Response) -> Value {
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("response body");
        serde_json::from_slice(&body).expect("response JSON")
    }

    async fn spawn_provider_model_server(
        model_ids: &[&str],
    ) -> (String, tokio::sync::oneshot::Sender<()>) {
        let payload = Arc::new(json!({
            "data": model_ids
                .iter()
                .map(|id| json!({ "id": id }))
                .collect::<Vec<_>>()
        }));
        let app = Router::new().route(
            "/v1/models",
            get({
                let payload = Arc::clone(&payload);
                move || {
                    let payload = Arc::clone(&payload);
                    async move { Json((*payload).clone()) }
                }
            }),
        );
        let listener = TcpListener::bind(("127.0.0.1", 0))
            .await
            .expect("provider model listener");
        let address = listener.local_addr().expect("provider model address");
        let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();
        tokio::spawn(async move {
            axum::serve(listener, app)
                .with_graceful_shutdown(async move {
                    shutdown_rx.await.ok();
                })
                .await
                .ok();
        });
        (format!("http://{address}/v1"), shutdown_tx)
    }

    fn timeline_test_item(id: &str, time_us: i64, counter: i64) -> Value {
        json!({
            "id": id,
            "type": "assistant_message",
            "eventTimeUs": time_us,
            "eventCounter": counter,
        })
    }

    fn timeline_response_ids(payload: &Value) -> Vec<&str> {
        payload["timeline"]
            .as_array()
            .expect("timeline array")
            .iter()
            .map(|item| item["id"].as_str().expect("timeline item id"))
            .collect()
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
    async fn conversation_messages_api_paginates_with_exclusive_tuple_cursors() {
        let state = test_state("timeline-secret");
        let conversation_id = "conversation-timeline-pagination";
        seed_plan_conversation(&state, conversation_id);
        for item in [
            timeline_test_item("event-1", 100, 0),
            timeline_test_item("event-2", 200, 0),
            timeline_test_item("event-3", 300, 0),
            timeline_test_item("event-4", 400, 0),
            timeline_test_item("event-5", 400, 1),
        ] {
            state
                .session_store
                .append_timeline(conversation_id, &item)
                .expect("append timeline item");
        }
        let app = local_router(Arc::clone(&state));

        let latest = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{conversation_id}/messages?project_id=local-project&limit=2"
                    ))
                    .header("authorization", "Bearer timeline-secret")
                    .body(Body::empty())
                    .expect("latest page request"),
            )
            .await
            .expect("latest page response");
        assert_eq!(latest.status(), StatusCode::OK);
        let latest = response_json(latest).await;
        assert_eq!(timeline_response_ids(&latest), vec!["event-4", "event-5"]);
        assert_eq!(latest["total"], 2);
        assert_eq!(latest["has_more"], true);
        assert_eq!(latest["first_time_us"], 400);
        assert_eq!(latest["first_counter"], 0);
        assert_eq!(latest["last_time_us"], 400);
        assert_eq!(latest["last_counter"], 1);

        let middle = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{conversation_id}/messages?project_id=local-project&limit=2&before_time_us=400&before_counter=0&from_time_us=100&from_counter=0"
                    ))
                    .header("authorization", "Bearer timeline-secret")
                    .body(Body::empty())
                    .expect("middle page request"),
            )
            .await
            .expect("middle page response");
        assert_eq!(middle.status(), StatusCode::OK);
        let middle = response_json(middle).await;
        assert_eq!(timeline_response_ids(&middle), vec!["event-2", "event-3"]);
        assert_eq!(middle["total"], 2);
        assert_eq!(middle["has_more"], true);

        let oldest = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{conversation_id}/messages?project_id=local-project&limit=2&before_time_us=200&before_counter=0"
                    ))
                    .header("authorization", "Bearer timeline-secret")
                    .body(Body::empty())
                    .expect("oldest page request"),
            )
            .await
            .expect("oldest page response");
        assert_eq!(oldest.status(), StatusCode::OK);
        let oldest = response_json(oldest).await;
        assert_eq!(timeline_response_ids(&oldest), vec!["event-1"]);
        assert_eq!(oldest["total"], 1);
        assert_eq!(oldest["has_more"], false);

        let forward = app
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{conversation_id}/messages?project_id=local-project&limit=2&from_time_us=200&from_counter=0"
                    ))
                    .header("authorization", "Bearer timeline-secret")
                    .body(Body::empty())
                    .expect("forward page request"),
            )
            .await
            .expect("forward page response");
        assert_eq!(forward.status(), StatusCode::OK);
        let forward = response_json(forward).await;
        assert_eq!(timeline_response_ids(&forward), vec!["event-3", "event-4"]);
        assert_eq!(forward["has_more"], true);
    }

    #[tokio::test]
    async fn conversation_messages_api_validates_project_limit_and_cursors() {
        let state = test_state("timeline-validation-secret");
        let conversation_id = "conversation-timeline-validation";
        seed_plan_conversation(&state, conversation_id);
        let app = local_router(state);
        let invalid_queries = [
            "project_id=local-project&limit=0",
            "project_id=local-project&limit=501",
            "project_id=local-project&from_time_us=-1",
            "project_id=local-project&from_counter=-1",
            "project_id=local-project&before_time_us=-1",
            "project_id=local-project&before_counter=-1",
            "project_id=%20",
        ];
        for query in invalid_queries {
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .uri(format!(
                            "/api/v1/agent/conversations/{conversation_id}/messages?{query}"
                        ))
                        .header("authorization", "Bearer timeline-validation-secret")
                        .body(Body::empty())
                        .expect("invalid query request"),
                )
                .await
                .expect("invalid query response");
            assert_eq!(
                response.status(),
                StatusCode::UNPROCESSABLE_ENTITY,
                "query should be rejected: {query}"
            );
        }

        let wrong_project = app
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{conversation_id}/messages?project_id=desktop-client"
                    ))
                    .header("authorization", "Bearer timeline-validation-secret")
                    .body(Body::empty())
                    .expect("wrong project request"),
            )
            .await
            .expect("wrong project response");
        assert_eq!(wrong_project.status(), StatusCode::FORBIDDEN);
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
        assert_eq!(created["context"]["tenant_id"], "northstar");
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
                    "operation_type": "llm",
                    "probe_supported": true,
                    "auth_methods": ["api_key", "none"]
                },
                {
                    "provider_type": "anthropic",
                    "operation_type": "llm",
                    "probe_supported": true,
                    "auth_methods": ["api_key", "none"]
                },
                {
                    "provider_type": "openai_compatible",
                    "operation_type": "llm",
                    "probe_supported": true,
                    "auth_methods": ["api_key", "none"]
                }
            ])
        );
    }

    #[tokio::test]
    async fn provider_model_catalog_is_static_structured_and_source_attributed() {
        let state = test_state("provider-catalog-secret");
        let app = local_router(state);

        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/models/openai",
                "provider-catalog-secret",
                json!({}),
            ))
            .await
            .expect("provider catalog response");

        assert_eq!(response.status(), axum::http::StatusCode::OK);
        assert_eq!(
            response_json(response).await,
            json!({
                "provider_type": "openai",
                "models": {
                    "chat": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
                    "embedding": ["text-embedding-3-small", "text-embedding-3-large"],
                    "rerank": []
                },
                "source": "static-fallback"
            })
        );

        let compatible = app
            .clone()
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/models/openai_compatible",
                "provider-catalog-secret",
                json!({}),
            ))
            .await
            .expect("OpenAI-compatible catalog response");
        assert_eq!(compatible.status(), axum::http::StatusCode::OK);
        assert_eq!(
            response_json(compatible).await,
            json!({
                "provider_type": "openai_compatible",
                "models": { "chat": [], "embedding": [], "rerank": [] },
                "source": null
            })
        );

        let unsupported = app
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/models/unknown-provider",
                "provider-catalog-secret",
                json!({}),
            ))
            .await
            .expect("unsupported catalog response");
        assert_eq!(
            unsupported.status(),
            axum::http::StatusCode::UNPROCESSABLE_ENTITY
        );
    }

    #[tokio::test]
    async fn provider_put_health_and_usage_routes_match_desktop_client_contract() {
        let (provider_base_url, provider_shutdown) =
            spawn_provider_model_server(&["model-a", "model-b"]).await;
        let state = test_state("provider-contract-secret");
        state
            .session_store
            .put_managed_resource(
                ManagedResourceKind::Provider,
                "tenant",
                "another-tenant",
                "other-tenant-provider",
                "active",
                None,
                json!({
                    "id": "other-tenant-provider",
                    "tenant_id": "another-tenant",
                    "provider_type": "openai",
                    "is_active": true,
                    "revision": 0
                }),
                Utc::now().timestamp_millis(),
            )
            .expect("seed another tenant provider");
        let app = local_router(state);

        let update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "provider-contract-secret",
                json!({
                    "provider_type": "openai_compatible",
                    "base_url": provider_base_url,
                    "auth_method": "none",
                    "llm_model": "model-a",
                    "is_active": true,
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("PUT provider response");
        assert_eq!(update.status(), axum::http::StatusCode::OK);
        let updated = response_json(update).await;
        assert_eq!(updated["revision"], 1);
        assert!(!updated.to_string().contains("provider-contract-key"));

        let health = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/local-runtime/health-check",
                "provider-contract-secret",
                json!({ "expected_revision": 1 }),
            ))
            .await
            .expect("provider health response");
        assert_eq!(health.status(), axum::http::StatusCode::OK);
        let health = response_json(health).await;
        assert_eq!(health["status"], "healthy");
        assert_eq!(health["probed"], true);
        assert!(health["last_check"].is_string());
        assert_eq!(health["provider"]["health_status"], "healthy");
        assert_eq!(
            health["catalog"]["models"]["chat"],
            json!(["model-a", "model-b"])
        );

        let discovery = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/local-runtime/models/discover",
                "provider-contract-secret",
                json!({ "expected_revision": 1 }),
            ))
            .await
            .expect("provider model discovery response");
        assert_eq!(discovery.status(), axum::http::StatusCode::OK);
        let discovery = response_json(discovery).await;
        assert_eq!(discovery["source"], "provider-api");
        assert_eq!(discovery["provider_id"], "local-runtime");
        assert_eq!(discovery["models"]["chat"], json!(["model-a", "model-b"]));

        let usage = app
            .clone()
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/local-runtime/usage",
                "provider-contract-secret",
                json!({}),
            ))
            .await
            .expect("provider usage response");
        assert_eq!(usage.status(), axum::http::StatusCode::OK);
        assert_eq!(
            response_json(usage).await,
            json!({
                "provider_id": "local-runtime",
                "tenant_id": "local",
                "statistics": []
            })
        );

        let unknown_usage = app
            .clone()
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/missing-provider/usage",
                "provider-contract-secret",
                json!({}),
            ))
            .await
            .expect("unknown provider usage response");
        assert_eq!(unknown_usage.status(), axum::http::StatusCode::NOT_FOUND);

        let cross_tenant_usage = app
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/other-tenant-provider/usage",
                "provider-contract-secret",
                json!({}),
            ))
            .await
            .expect("cross-tenant provider usage response");
        assert_eq!(
            cross_tenant_usage.status(),
            axum::http::StatusCode::NOT_FOUND
        );
        provider_shutdown.send(()).ok();
    }

    #[tokio::test]
    async fn draft_provider_probe_discovers_models_without_persisting() {
        let (provider_base_url, provider_shutdown) =
            spawn_provider_model_server(&["draft-model-a", "draft-model-b"]).await;
        let state = test_state("provider-draft-secret");
        let app = local_router(state);

        let valid = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/test-connection",
                "provider-draft-secret",
                json!({
                    "name": "Draft provider",
                    "provider_type": "openai_compatible",
                    "base_url": provider_base_url,
                    "auth_method": "none",
                    "is_active": true
                }),
            ))
            .await
            .expect("valid draft response");
        assert_eq!(valid.status(), axum::http::StatusCode::OK);
        let validation = response_json(valid).await;
        assert_eq!(validation["provider"], Value::Null);
        assert_eq!(validation["status"], "healthy");
        assert_eq!(validation["probed"], true);
        assert!(!validation.to_string().contains("draft-provider-key"));
        assert!(validation["last_check"].is_string());
        assert_eq!(validation["catalog"]["source"], "provider-api");
        assert_eq!(
            validation["catalog"]["models"]["chat"],
            json!(["draft-model-a", "draft-model-b"])
        );

        let missing_credential = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/test-connection",
                "provider-draft-secret",
                json!({
                    "name": "Draft provider",
                    "provider_type": "openai",
                    "base_url": "https://api.example.test/v1",
                    "auth_method": "api_key",
                    "is_active": true
                }),
            ))
            .await
            .expect("missing credential draft response");
        assert_eq!(missing_credential.status(), axum::http::StatusCode::OK);
        let missing_credential = response_json(missing_credential).await;
        assert_eq!(missing_credential["status"], "needs_credentials");
        assert_eq!(missing_credential["probed"], false);

        let invalid_endpoint = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/test-connection",
                "provider-draft-secret",
                json!({
                    "name": "Draft provider",
                    "provider_type": "openai",
                    "base_url": "file:///tmp/not-an-http-endpoint",
                    "auth_method": "api_key",
                    "api_key": "draft-provider-key",
                    "is_active": true
                }),
            ))
            .await
            .expect("invalid endpoint draft response");
        assert_eq!(
            invalid_endpoint.status(),
            axum::http::StatusCode::UNPROCESSABLE_ENTITY
        );

        let providers = app
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/",
                "provider-draft-secret",
                json!({}),
            ))
            .await
            .expect("provider list response");
        assert_eq!(providers.status(), axum::http::StatusCode::OK);
        let providers = response_json(providers).await;
        assert_eq!(providers.as_array().map(Vec::len), Some(1));
        assert!(!providers.to_string().contains("Draft provider"));
        provider_shutdown.send(()).ok();
    }

    #[tokio::test]
    async fn unavailable_credential_store_rejects_provider_update_without_mutating_runtime_or_db() {
        let root = test_root();
        let tool_host = LocalToolHost::new(&root).expect("tool host");
        let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        let session_store = DesktopSessionStore::in_memory().expect("session store");
        let provider_credentials = ProviderCredentialBroker::new(
            Arc::new(UnavailableProviderCredentialStore),
            session_store.installation_id(),
        )
        .expect("unavailable credential broker");
        let state = Arc::new(
            LocalRuntimeState::new_with_provider_credentials(
                root,
                tool_host,
                checkpoints,
                "unavailable-vault-session".to_string(),
                session_store,
                provider_credentials,
            )
            .expect("local runtime state"),
        );
        state
            .session_store
            .seed_test_session("unavailable-vault-session")
            .expect("authenticated test session");

        let response = local_router(Arc::clone(&state))
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "unavailable-vault-session",
                json!({
                    "provider_type": "openai",
                    "base_url": "https://api.example.test/v1",
                    "auth_method": "api_key",
                    "api_key": "must-never-be-persisted",
                    "llm_model": "model-a",
                    "is_active": true,
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("provider update response");

        assert_eq!(
            response.status(),
            axum::http::StatusCode::SERVICE_UNAVAILABLE
        );
        let error = response_json(response).await;
        assert_eq!(error["code"], "provider_credential_store_unavailable");
        assert!(!error.to_string().contains("must-never-be-persisted"));
        let persisted = state
            .session_store
            .managed_resource(
                ManagedResourceKind::Provider,
                "tenant",
                "local",
                "local-runtime",
            )
            .expect("persisted provider")
            .expect("seeded provider");
        assert_eq!(persisted["revision"], 0);
        assert_eq!(persisted["is_active"], false);
        assert!(!persisted.to_string().contains("must-never-be-persisted"));
        assert!(state
            .provider_runtime
            .lock()
            .expect("provider runtime")
            .credentials
            .is_empty());
    }

    #[tokio::test]
    async fn concurrent_provider_updates_keep_the_winning_revision_and_credential_together() {
        let state = test_state("concurrent-provider-session");
        let app = local_router(Arc::clone(&state));
        let request = |model: &str, api_key: &str| {
            authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "concurrent-provider-session",
                json!({
                    "provider_type": "openai",
                    "base_url": "https://api.example.test/v1",
                    "auth_method": "api_key",
                    "api_key": api_key,
                    "llm_model": model,
                    "is_active": true,
                    "expected_revision": 0
                }),
            )
        };

        let (first, second) = tokio::join!(
            app.clone()
                .oneshot(request("winner-a-model", "winner-a-secret")),
            app.oneshot(request("winner-b-model", "winner-b-secret")),
        );
        let first = first.expect("first provider response");
        let second = second.expect("second provider response");
        let (winner, conflict) = match (first.status(), second.status()) {
            (StatusCode::OK, StatusCode::CONFLICT) => (first, second),
            (StatusCode::CONFLICT, StatusCode::OK) => (second, first),
            statuses => panic!("expected one winner and one revision conflict, got {statuses:?}"),
        };
        let winner = response_json(winner).await;
        let conflict = response_json(conflict).await;
        assert_eq!(winner["revision"], 1);
        assert!(!winner.to_string().contains("winner-a-secret"));
        assert!(!winner.to_string().contains("winner-b-secret"));
        assert!(!conflict.to_string().contains("winner-a-secret"));
        assert!(!conflict.to_string().contains("winner-b-secret"));

        let expected_credential = match winner["llm_model"].as_str() {
            Some("winner-a-model") => "winner-a-secret",
            Some("winner-b-model") => "winner-b-secret",
            model => panic!("unexpected winning provider model {model:?}"),
        };
        let key = ProviderRuntimeKey {
            tenant_id: "local".to_string(),
            provider_id: "local-runtime".to_string(),
        };
        assert_eq!(
            state
                .provider_runtime
                .lock()
                .expect("provider runtime")
                .credentials
                .get(&key)
                .map(String::as_str),
            Some(expected_credential)
        );
        let binding_digest =
            provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
        assert_eq!(
            state
                .provider_credentials
                .load("local", "local-runtime", 1, &binding_digest)
                .expect("winning provider credential")
                .as_deref(),
            Some(expected_credential)
        );
    }

    #[tokio::test]
    async fn provider_endpoints_reject_invalid_or_unsafe_transport_before_persistence() {
        let state = test_state("provider-endpoint-secret");
        let app = local_router(state);

        for invalid_base_url in [
            "https://",
            "https://user:password@example.test/v1",
            "https://api.example.test/v1?token=secret",
            "https://api.example.test/v1#fragment",
            "http://api.example.test/v1",
        ] {
            let response = app
                .clone()
                .oneshot(authenticated_json_request(
                    "POST",
                    "/api/v1/llm-providers/test-connection",
                    "provider-endpoint-secret",
                    json!({
                        "name": "Unsafe draft",
                        "provider_type": "openai",
                        "base_url": invalid_base_url,
                        "auth_method": "api_key",
                        "api_key": "provider-endpoint-key",
                        "is_active": true
                    }),
                ))
                .await
                .expect("unsafe draft response");
            assert_eq!(
                response.status(),
                axum::http::StatusCode::UNPROCESSABLE_ENTITY,
                "unsafe endpoint should be rejected: {invalid_base_url}"
            );
            assert!(!response_json(response)
                .await
                .to_string()
                .contains("provider-endpoint-key"));
        }

        let local_http = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/test-connection",
                "provider-endpoint-secret",
                json!({
                    "name": "Local runtime",
                    "provider_type": "openai_compatible",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "auth_method": "none",
                    "is_active": true
                }),
            ))
            .await
            .expect("local HTTP draft response");
        assert_eq!(local_http.status(), axum::http::StatusCode::OK);

        let unsafe_update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "provider-endpoint-secret",
                json!({
                    "base_url": "https://user:password@example.test/v1",
                    "auth_method": "api_key",
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("unsafe update response");
        assert_eq!(
            unsafe_update.status(),
            axum::http::StatusCode::UNPROCESSABLE_ENTITY
        );

        let unsafe_create = app
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/",
                "provider-endpoint-secret",
                json!({
                    "name": "Unsafe provider",
                    "provider_type": "openai_compatible",
                    "base_url": "http://api.example.test/v1",
                    "auth_method": "none",
                    "llm_model": "model-a",
                    "is_active": true
                }),
            ))
            .await
            .expect("unsafe create response");
        assert_eq!(
            unsafe_create.status(),
            axum::http::StatusCode::UNPROCESSABLE_ENTITY
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
        let provider_b_id = activated_b["id"].as_str().expect("provider B id");
        let select_b = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                &format!("/api/v1/llm-providers/{provider_b_id}/runtime-selection"),
                "provider-secret",
                json!({ "expected_revision": 0, "expected_policy_revision": 0 }),
            ))
            .await
            .expect("select provider B without credentials");
        assert_eq!(
            select_b.status(),
            axum::http::StatusCode::UNPROCESSABLE_ENTITY
        );

        let select_a = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime/runtime-selection",
                "provider-secret",
                json!({ "expected_revision": 1, "expected_policy_revision": 0 }),
            ))
            .await
            .expect("select provider A");
        assert_eq!(select_a.status(), axum::http::StatusCode::OK);
        assert_eq!(response_json(select_a).await["credential_configured"], true);

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
        assert_eq!(reactivated_a["credential_configured"], true);
        assert_eq!(reactivated_a["health_status"], "configuration_valid");
        assert_eq!(reactivated_a["runtime_selected"], true);
        assert_eq!(reactivated_a["revision"], 2);

        let disable_a = app
            .oneshot(authenticated_json_request(
                "PATCH",
                "/api/v1/llm-providers/local-runtime",
                "provider-secret",
                json!({ "is_active": false, "expected_revision": 2 }),
            ))
            .await
            .expect("disable active provider");
        assert_eq!(
            disable_a.status(),
            axum::http::StatusCode::UNPROCESSABLE_ENTITY
        );
        assert!(response_json(disable_a).await["detail"]
            .as_str()
            .is_some_and(|detail| detail.contains("invalidate routing policy")));
        let runtime = state.provider_runtime.lock().expect("provider runtime");
        let key = ProviderRuntimeKey {
            tenant_id: "local".to_string(),
            provider_id: "local-runtime".to_string(),
        };
        assert!(runtime.bindings.contains_key(&key));
        assert!(runtime.credentials.contains_key(&key));
        assert_eq!(
            runtime.selections.get("local"),
            Some(&"local-runtime".to_string())
        );
        drop(runtime);
        assert_eq!(
            state
                .session_store
                .list_selected_llm_providers()
                .expect("persisted provider selections"),
            vec![("local".to_string(), "local-runtime".to_string())]
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
        assert_eq!(persisted["is_active"], true);
        assert_eq!(persisted["revision"], 2);
        assert!(!persisted.to_string().contains("provider-key-a"));
        assert!(persisted.get("api_key").is_none());
    }

    #[test]
    fn local_runtime_config_accepts_only_workspace_root() {
        let workspace_only = serde_json::from_value::<LocalRuntimeConfig>(json!({
            "workspace_root": "/tmp/agistack-workspace"
        }));
        assert!(workspace_only.is_ok());

        for legacy_field in ["provider", "base_url", "model", "api_key"] {
            let mut value = json!({ "workspace_root": "/tmp/agistack-workspace" });
            value[legacy_field] = json!("legacy-runtime-value");
            assert!(
                serde_json::from_value::<LocalRuntimeConfig>(value).is_err(),
                "legacy runtime field must be rejected: {legacy_field}"
            );
        }
    }

    #[tokio::test]
    async fn provider_connection_update_requires_explicit_idempotent_runtime_selection() {
        let state = test_state("explicit-provider-selection-secret");
        let app = local_router(Arc::clone(&state));

        let update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "explicit-provider-selection-secret",
                json!({
                    "provider_type": "openai",
                    "base_url": "https://api.example.test/v1",
                    "auth_method": "api_key",
                    "llm_model": "model-a",
                    "is_active": true,
                    "api_key": "explicit-provider-key",
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("update provider connection");
        assert_eq!(update.status(), axum::http::StatusCode::OK);
        let updated = response_json(update).await;
        assert_eq!(updated["runtime_selected"], false);
        assert_eq!(updated["credential_configured"], true);

        for expected_policy_revision in [0, 1] {
            let selection = app
                .clone()
                .oneshot(authenticated_json_request(
                    "PUT",
                    "/api/v1/llm-providers/local-runtime/runtime-selection",
                    "explicit-provider-selection-secret",
                    json!({
                        "expected_revision": 1,
                        "expected_policy_revision": expected_policy_revision
                    }),
                ))
                .await
                .expect("select provider runtime");
            assert_eq!(selection.status(), axum::http::StatusCode::OK);
            let selected = response_json(selection).await;
            assert_eq!(selected["id"], "local-runtime");
            assert_eq!(selected["runtime_selected"], true);
            assert_eq!(selected["revision"], 1);
        }
        let stale_selection = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime/runtime-selection",
                "explicit-provider-selection-secret",
                json!({ "expected_revision": 0, "expected_policy_revision": 1 }),
            ))
            .await
            .expect("stale selection response");
        assert_eq!(stale_selection.status(), axum::http::StatusCode::CONFLICT);

        let create_other = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/",
                "explicit-provider-selection-secret",
                json!({
                    "name": "Provider B",
                    "provider_type": "openai",
                    "base_url": "https://api-b.example.test/v1",
                    "auth_method": "api_key",
                    "api_key": "provider-b-key",
                    "llm_model": "model-b",
                    "is_active": true
                }),
            ))
            .await
            .expect("create another active connection");
        assert_eq!(create_other.status(), axum::http::StatusCode::OK);
        let other = response_json(create_other).await;
        assert_eq!(other["runtime_selected"], false);

        let providers = app
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/",
                "explicit-provider-selection-secret",
                json!({}),
            ))
            .await
            .expect("list providers");
        let providers = response_json(providers).await;
        let local = providers
            .as_array()
            .expect("provider array")
            .iter()
            .find(|provider| provider["id"] == "local-runtime")
            .expect("selected provider");
        assert_eq!(local["runtime_selected"], true);
    }

    #[tokio::test]
    async fn runtime_status_is_sorted_and_never_exposes_provider_transport_or_credentials() {
        let state = test_state("runtime-provider-projection-secret");
        let app = local_router(Arc::clone(&state));

        let local_update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "runtime-provider-projection-secret",
                json!({
                    "provider_type": "openai",
                    "base_url": "https://local.example.test/v1",
                    "auth_method": "api_key",
                    "llm_model": "local-model",
                    "is_active": true,
                    "api_key": "local-projection-key",
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("configure local tenant provider");
        assert_eq!(local_update.status(), axum::http::StatusCode::OK);
        let local_selection = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime/runtime-selection",
                "runtime-provider-projection-secret",
                json!({ "expected_revision": 1, "expected_policy_revision": 0 }),
            ))
            .await
            .expect("select local tenant provider");
        assert_eq!(local_selection.status(), axum::http::StatusCode::OK);

        let authenticated = state
            .session_store
            .validate_session_credential(
                "runtime-provider-projection-secret",
                Utc::now().timestamp_millis(),
            )
            .expect("validate session")
            .expect("authenticated context");
        state
            .session_store
            .switch_workspace_context(
                &authenticated,
                &ContextSwitchRequest {
                    tenant_id: "northstar".to_string(),
                    project_id: "desktop-client".to_string(),
                    expected_revision: 0,
                    idempotency_key: "runtime-provider-projection-switch".to_string(),
                },
                Utc::now().timestamp_millis(),
            )
            .expect("switch tenant context");

        let northstar_update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "runtime-provider-projection-secret",
                json!({
                    "provider_type": "anthropic",
                    "base_url": "https://northstar.example.test/v1",
                    "auth_method": "api_key",
                    "llm_model": "northstar-model",
                    "is_active": true,
                    "api_key": "northstar-projection-key",
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("configure northstar provider with the same provider id");
        assert_eq!(northstar_update.status(), axum::http::StatusCode::OK);
        let northstar_selection = app
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime/runtime-selection",
                "runtime-provider-projection-secret",
                json!({ "expected_revision": 1, "expected_policy_revision": 0 }),
            ))
            .await
            .expect("select northstar tenant provider");
        assert_eq!(northstar_selection.status(), axum::http::StatusCode::OK);

        let service = LocalRuntimeService {
            state,
            api_base_url: "http://127.0.0.1:1".to_string(),
        };
        assert_eq!(
            service
                .state
                .session_store
                .list_selected_llm_providers()
                .expect("tenant provider selections"),
            vec![
                ("local".to_string(), "local-runtime".to_string()),
                ("northstar".to_string(), "local-runtime".to_string()),
            ]
        );
        let status = serde_json::to_value(service.status()).expect("serialize runtime status");
        assert_eq!(
            status["runtime_providers"],
            json!([
                {
                    "tenant_id": "local",
                    "provider_id": "local-runtime",
                    "provider_type": "openai",
                    "model": "local-model",
                    "credential_configured": true
                },
                {
                    "tenant_id": "northstar",
                    "provider_id": "local-runtime",
                    "provider_type": "anthropic",
                    "model": "northstar-model",
                    "credential_configured": true
                }
            ])
        );
        let serialized = status["runtime_providers"].to_string();
        for forbidden in [
            "base_url",
            "api_key",
            "local-projection-key",
            "northstar-projection-key",
            "local.example.test",
            "northstar.example.test",
        ] {
            assert!(
                !serialized.contains(forbidden),
                "runtime status leaked forbidden provider data: {forbidden}"
            );
        }
    }

    #[tokio::test]
    async fn signout_preserves_runtime_selection_for_the_next_local_session() {
        let state = test_state("selection-signout-secret");
        let app = local_router(state);

        let update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "selection-signout-secret",
                json!({
                    "provider_type": "openai_compatible",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "auth_method": "none",
                    "llm_model": "local-model",
                    "is_active": true,
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("update provider");
        assert_eq!(update.status(), axum::http::StatusCode::OK);
        let select = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime/runtime-selection",
                "selection-signout-secret",
                json!({ "expected_revision": 1, "expected_policy_revision": 0 }),
            ))
            .await
            .expect("select provider");
        assert_eq!(select.status(), axum::http::StatusCode::OK);

        let signout = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/auth/signout",
                "selection-signout-secret",
                json!({}),
            ))
            .await
            .expect("sign out");
        assert_eq!(signout.status(), axum::http::StatusCode::OK);

        let next_session = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/auth/local-session")
                    .header("x-agistack-launch", "selection-signout-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(r#"{"trusted_device":false}"#))
                    .expect("new local session request"),
            )
            .await
            .expect("new local session");
        assert_eq!(next_session.status(), axum::http::StatusCode::OK);
        let next_session = response_json(next_session).await;
        let next_credential = next_session["access_token"]
            .as_str()
            .expect("next session credential");
        let providers = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/llm-providers/")
                    .header("x-agistack-launch", "selection-signout-secret")
                    .header("authorization", format!("Bearer {next_credential}"))
                    .body(Body::empty())
                    .expect("list providers request"),
            )
            .await
            .expect("list providers in next session");
        assert_eq!(providers.status(), axum::http::StatusCode::OK);
        let providers = response_json(providers).await;
        assert_eq!(
            providers[0]["runtime_selected"], true,
            "unexpected provider list: {providers}"
        );
    }

    #[tokio::test]
    async fn active_provider_connection_does_not_appear_in_runtime_status_before_selection() {
        let state = test_state("unselected-runtime-status-secret");
        let app = local_router(Arc::clone(&state));
        let update = app
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "unselected-runtime-status-secret",
                json!({
                    "provider_type": "openai_compatible",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "auth_method": "none",
                    "llm_model": "local-model",
                    "is_active": true,
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("enable provider connection");
        assert_eq!(update.status(), axum::http::StatusCode::OK);

        let service = LocalRuntimeService {
            state,
            api_base_url: "http://127.0.0.1:1".to_string(),
        };
        let status = serde_json::to_value(service.status()).expect("serialize runtime status");
        assert_eq!(status["runtime_providers"], json!([]));
        service.state.mock_llm_enabled.store(0, Ordering::Release);
        let error = service
            .state
            .llm("local")
            .decide("must remain unconfigured", 0, &[], &[])
            .await
            .expect_err("an unselected active connection must fail closed");
        assert!(error.to_string().contains("model_unconfigured"));
    }

    #[tokio::test]
    async fn stale_provider_update_cannot_clear_authoritative_runtime_selection() {
        let state = test_state("stale-provider-selection-secret");
        let app = local_router(Arc::clone(&state));
        let update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "stale-provider-selection-secret",
                json!({
                    "provider_type": "openai_compatible",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "auth_method": "none",
                    "llm_model": "local-model",
                    "is_active": true,
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("configure provider");
        assert_eq!(update.status(), axum::http::StatusCode::OK);
        let selection = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime/runtime-selection",
                "stale-provider-selection-secret",
                json!({ "expected_revision": 1, "expected_policy_revision": 0 }),
            ))
            .await
            .expect("select provider");
        assert_eq!(selection.status(), axum::http::StatusCode::OK);

        let stale_disable = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "stale-provider-selection-secret",
                json!({ "is_active": false, "expected_revision": 0 }),
            ))
            .await
            .expect("stale disable response");
        assert_eq!(stale_disable.status(), axum::http::StatusCode::CONFLICT);

        assert_eq!(
            state
                .session_store
                .list_selected_llm_providers()
                .expect("persisted selections"),
            vec![("local".to_string(), "local-runtime".to_string())]
        );
        {
            let runtime = state.provider_runtime.lock().expect("provider runtime");
            assert_eq!(
                runtime.selections.get("local").map(String::as_str),
                Some("local-runtime")
            );
        }

        let providers = app
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/",
                "stale-provider-selection-secret",
                json!({}),
            ))
            .await
            .expect("list providers");
        let providers = response_json(providers).await;
        assert_eq!(providers[0]["runtime_selected"], true);
        assert_eq!(providers[0]["is_active"], true);
    }

    #[tokio::test]
    async fn routed_endpoint_change_requires_replacement_credential_atomically() {
        let state = test_state("atomic-provider-credential-secret");
        let app = local_router(Arc::clone(&state));
        let update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "atomic-provider-credential-secret",
                json!({
                    "provider_type": "openai",
                    "base_url": "https://old.example.test/v1",
                    "auth_method": "api_key",
                    "api_key": "old-provider-key",
                    "llm_model": "model-a",
                    "is_active": true,
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("configure old endpoint");
        assert_eq!(update.status(), axum::http::StatusCode::OK);
        let selection = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime/runtime-selection",
                "atomic-provider-credential-secret",
                json!({ "expected_revision": 1, "expected_policy_revision": 0 }),
            ))
            .await
            .expect("select provider");
        assert_eq!(selection.status(), axum::http::StatusCode::OK);

        let endpoint_change = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "atomic-provider-credential-secret",
                json!({
                    "base_url": "https://new.example.test/v1",
                    "expected_revision": 1
                }),
            ))
            .await
            .expect("change endpoint without credential");
        assert_eq!(
            endpoint_change.status(),
            axum::http::StatusCode::UNPROCESSABLE_ENTITY
        );
        assert!(response_json(endpoint_change).await["detail"]
            .as_str()
            .is_some_and(|detail| detail.contains("invalidate routing policy")));

        let key = ProviderRuntimeKey {
            tenant_id: "local".to_string(),
            provider_id: "local-runtime".to_string(),
        };
        {
            let runtime = state.provider_runtime.lock().expect("provider runtime");
            assert_eq!(
                runtime
                    .bindings
                    .get(&key)
                    .map(|binding| binding.base_url.as_str()),
                Some("https://old.example.test/v1")
            );
            assert!(runtime.credentials.contains_key(&key));
        }

        let replacement = app
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "atomic-provider-credential-secret",
                json!({
                    "base_url": "https://new.example.test/v1",
                    "api_key": "new-provider-key",
                    "expected_revision": 1
                }),
            ))
            .await
            .expect("replace credential");
        assert_eq!(replacement.status(), axum::http::StatusCode::OK);
        let replacement = response_json(replacement).await;
        assert_eq!(replacement["credential_configured"], true);
        assert_eq!(replacement["health_status"], "configuration_valid");

        let persisted = state
            .session_store
            .managed_resource(
                ManagedResourceKind::Provider,
                "tenant",
                "local",
                "local-runtime",
            )
            .expect("persisted provider")
            .expect("provider");
        assert!(!persisted.to_string().contains("old-provider-key"));
        assert!(!persisted.to_string().contains("new-provider-key"));
    }

    #[tokio::test]
    async fn runtime_selection_route_allows_tauri_put_preflight() {
        let response = local_router(test_state("selection-cors-secret"))
            .oneshot(
                Request::builder()
                    .method(Method::OPTIONS)
                    .uri("/api/v1/llm-providers/local-runtime/runtime-selection")
                    .header("origin", "tauri://localhost")
                    .header("access-control-request-method", "PUT")
                    .header(
                        "access-control-request-headers",
                        "authorization,content-type,x-agistack-launch",
                    )
                    .body(Body::empty())
                    .expect("selection preflight request"),
            )
            .await
            .expect("selection preflight response");
        assert_eq!(response.status(), axum::http::StatusCode::OK);
        assert!(response
            .headers()
            .get("access-control-allow-methods")
            .and_then(|value| value.to_str().ok())
            .is_some_and(|methods| methods.split(',').any(|method| method.trim() == "PUT")));
    }

    #[tokio::test]
    async fn workspace_reconfigure_preserves_provider_credentials_and_selection_state() {
        let state = test_state("workspace-config-provider-secret");
        let app = local_router(Arc::clone(&state));
        let update = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "workspace-config-provider-secret",
                json!({
                    "provider_type": "openai",
                    "base_url": "https://api.example.test/v1",
                    "auth_method": "api_key",
                    "api_key": "workspace-config-provider-key",
                    "llm_model": "model-a",
                    "is_active": true,
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("configure provider connection");
        assert_eq!(update.status(), axum::http::StatusCode::OK);

        let key = ProviderRuntimeKey {
            tenant_id: "local".to_string(),
            provider_id: "local-runtime".to_string(),
        };
        let before = {
            let runtime = state.provider_runtime.lock().expect("provider runtime");
            let binding = runtime.bindings.get(&key).expect("provider binding");
            (
                runtime.bindings.len(),
                binding.provider_type.clone(),
                binding.base_url.clone(),
                binding.model.clone(),
                runtime.credentials.contains_key(&key),
                runtime.selections.clone(),
            )
        };

        let workspace_root = test_root();
        let config = serde_json::from_value::<LocalRuntimeConfig>(json!({
            "workspace_root": workspace_root
        }))
        .expect("workspace-only runtime config");
        state.configure(config).expect("reconfigure workspace");
        let after = {
            let runtime = state.provider_runtime.lock().expect("provider runtime");
            let binding = runtime.bindings.get(&key).expect("provider binding");
            (
                runtime.bindings.len(),
                binding.provider_type.clone(),
                binding.base_url.clone(),
                binding.model.clone(),
                runtime.credentials.contains_key(&key),
                runtime.selections.clone(),
            )
        };
        assert_eq!(after, before);

        let select = app
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime/runtime-selection",
                "workspace-config-provider-secret",
                json!({ "expected_revision": 1, "expected_policy_revision": 0 }),
            ))
            .await
            .expect("select provider after workspace reconfigure");
        assert_eq!(select.status(), axum::http::StatusCode::OK);
        let selected = response_json(select).await;
        assert_eq!(selected["credential_configured"], true);
        assert_eq!(selected["runtime_selected"], true);
    }

    #[tokio::test]
    async fn runtime_selection_and_provider_credential_survive_restart_without_secret_exposure() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create restart test root");
        let store_path = root.join("sessions.db");
        let workspace_root = root.join("workspace");
        std::fs::create_dir_all(&workspace_root).expect("create workspace root");
        let credential = "restart-provider-selection-secret";
        let first_store = DesktopSessionStore::open(&store_path).expect("open session store");
        let provider_credentials =
            ProviderCredentialBroker::in_memory(first_store.installation_id())
                .expect("provider credential broker");

        {
            let tool_host = LocalToolHost::new(&workspace_root).expect("tool host");
            let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
            let state = Arc::new(
                LocalRuntimeState::new_with_provider_credentials(
                    workspace_root.clone(),
                    tool_host,
                    checkpoints,
                    credential.to_string(),
                    first_store,
                    provider_credentials.clone(),
                )
                .expect("runtime state"),
            );
            state
                .session_store
                .seed_test_session(credential)
                .expect("test session");
            let app = local_router(state);
            let update = app
                .clone()
                .oneshot(authenticated_json_request(
                    "PUT",
                    "/api/v1/llm-providers/local-runtime",
                    credential,
                    json!({
                        "provider_type": "openai",
                        "base_url": "https://api.example.test/v1",
                        "auth_method": "api_key",
                        "api_key": "ephemeral-restart-key",
                        "llm_model": "model-a",
                        "is_active": true,
                        "expected_revision": 0
                    }),
                ))
                .await
                .expect("configure provider");
            assert_eq!(update.status(), axum::http::StatusCode::OK);
            let select = app
                .oneshot(authenticated_json_request(
                    "PUT",
                    "/api/v1/llm-providers/local-runtime/runtime-selection",
                    credential,
                    json!({ "expected_revision": 1, "expected_policy_revision": 0 }),
                ))
                .await
                .expect("select provider");
            assert_eq!(select.status(), axum::http::StatusCode::OK);
            let selected = response_json(select).await;
            assert_eq!(selected["credential_configured"], true);
        }

        let binding_digest =
            provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
        provider_credentials
            .save(
                "local",
                "local-runtime",
                2,
                &binding_digest,
                "uncommitted-crash-window-secret",
            )
            .expect("simulate a credential pre-write before a process crash");

        let store = DesktopSessionStore::open(&store_path).expect("reopen session store");
        let tool_host = LocalToolHost::new(&workspace_root).expect("restored tool host");
        let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        let state = Arc::new(
            LocalRuntimeState::new_with_provider_credentials(
                workspace_root,
                tool_host,
                checkpoints,
                credential.to_string(),
                store,
                provider_credentials,
            )
            .expect("restored runtime state"),
        );
        let service = LocalRuntimeService {
            state: Arc::clone(&state),
            api_base_url: "http://127.0.0.1:1".to_string(),
        };
        let status = serde_json::to_value(service.status()).expect("restored status");
        let runtime_key = ProviderRuntimeKey {
            tenant_id: "local".to_string(),
            provider_id: "local-runtime".to_string(),
        };
        assert_eq!(
            state
                .provider_runtime
                .lock()
                .expect("provider runtime")
                .credentials
                .get(&runtime_key)
                .map(String::as_str),
            Some("ephemeral-restart-key")
        );
        assert_eq!(status["runtime_providers"][0]["tenant_id"], "local");
        assert_eq!(
            status["runtime_providers"][0]["provider_id"],
            "local-runtime"
        );
        assert_eq!(
            status["runtime_providers"][0]["credential_configured"],
            true
        );
        assert!(!status.to_string().contains("ephemeral-restart-key"));

        let providers = local_router(state)
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/",
                credential,
                json!({}),
            ))
            .await
            .expect("list restored providers");
        assert_eq!(providers.status(), axum::http::StatusCode::OK);
        let providers = response_json(providers).await;
        assert_eq!(providers[0]["runtime_selected"], true);
        assert_eq!(providers[0]["credential_configured"], true);
        assert_eq!(providers[0]["health_status"], "configuration_valid");
        assert_eq!(providers[0]["credential_source"], "system_vault");
        assert!(!providers.to_string().contains("ephemeral-restart-key"));
        assert!(!providers
            .to_string()
            .contains("uncommitted-crash-window-secret"));

        drop(service);
        for path in [
            store_path.clone(),
            store_path.with_extension("db-wal"),
            store_path.with_extension("db-shm"),
        ] {
            if !path.exists() {
                continue;
            }
            let bytes = std::fs::read(&path).expect("read provider database artifact");
            assert!(
                !bytes
                    .windows(b"ephemeral-restart-key".len())
                    .any(|window| window == b"ephemeral-restart-key"),
                "provider credential leaked into {}",
                path.display()
            );
        }
        std::fs::remove_dir_all(root).expect("remove restart test root");
    }

    #[tokio::test]
    async fn active_provider_without_selection_row_is_not_inferred_as_runtime() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create inference test root");
        let store_path = root.join("sessions.db");
        let workspace_root = root.join("workspace");
        std::fs::create_dir_all(&workspace_root).expect("create workspace root");
        let credential = "no-provider-selection-secret";
        let store = DesktopSessionStore::open(&store_path).expect("open session store");
        store
            .put_managed_resource(
                ManagedResourceKind::Provider,
                "tenant",
                "local",
                "local-runtime",
                "active",
                Some(0),
                json!({
                    "id": "local-runtime",
                    "name": "Active but unselected",
                    "provider_type": "openai_compatible",
                    "tenant_id": "local",
                    "is_active": true,
                    "base_url": "http://127.0.0.1:11434/v1",
                    "auth_method": "none",
                    "credential_source": "none",
                    "credential_configured": false,
                    "llm_model": "local-model",
                    "allowed_models": ["local-model"],
                    "secondary_models": [],
                    "health_status": "not_checked",
                    "revision": 0
                }),
                Utc::now().timestamp_millis(),
            )
            .expect("enable provider directly without selection");
        store
            .seed_test_session(credential)
            .expect("authenticated session");
        drop(store);

        let store = DesktopSessionStore::open(&store_path).expect("reopen session store");
        let tool_host = LocalToolHost::new(&workspace_root).expect("tool host");
        let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        let state = Arc::new(
            LocalRuntimeState::new(
                workspace_root,
                tool_host,
                checkpoints,
                credential.to_string(),
                store,
            )
            .expect("runtime state"),
        );
        let service = LocalRuntimeService {
            state: Arc::clone(&state),
            api_base_url: "http://127.0.0.1:1".to_string(),
        };
        let status = serde_json::to_value(service.status()).expect("runtime status");
        assert_eq!(status["runtime_providers"], json!([]));

        let providers = local_router(state)
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/llm-providers/",
                credential,
                json!({}),
            ))
            .await
            .expect("list providers");
        let providers = response_json(providers).await;
        assert_eq!(providers[0]["runtime_selected"], false);
        assert_eq!(providers[0]["health_status"], "configuration_valid");

        drop(service);
        std::fs::remove_dir_all(root).expect("remove inference test root");
    }

    #[test]
    fn session_store_migrates_provider_selection_schema_without_downgrading_future_versions() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create schema test root");
        let old_path = root.join("old.db");
        {
            let connection = rusqlite::Connection::open(&old_path).expect("open old database");
            connection
                .execute_batch("PRAGMA user_version = 10;")
                .expect("mark old schema version");
        }
        let migrated = DesktopSessionStore::open(&old_path).expect("migrate old store");
        let installation_id = migrated.installation_id().to_string();
        drop(migrated);
        let connection = rusqlite::Connection::open(&old_path).expect("inspect migrated store");
        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .expect("migrated schema version");
        assert_eq!(version, 14);
        let selection_table: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master
                 WHERE type = 'table' AND name = 'desktop_llm_provider_selections'",
                [],
                |row| row.get(0),
            )
            .expect("provider selection table count");
        assert_eq!(selection_table, 1);
        let task_session_table: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master
                 WHERE type = 'table' AND name = 'desktop_new_task_sessions'",
                [],
                |row| row.get(0),
            )
            .expect("task session table count");
        assert_eq!(task_session_table, 1);
        let task_session_response_column: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM pragma_table_info('desktop_new_task_sessions')
                 WHERE name = 'response_json' AND \"notnull\" = 1",
                [],
                |row| row.get(0),
            )
            .expect("task session response column count");
        assert_eq!(task_session_response_column, 1);
        let stored_installation_id: String = connection
            .query_row(
                "SELECT value_text FROM desktop_runtime_metadata WHERE key = 'installation_id'",
                [],
                |row| row.get(0),
            )
            .expect("installation id");
        assert_eq!(stored_installation_id, installation_id);
        drop(connection);

        let reopened = DesktopSessionStore::open(&old_path).expect("reopen migrated store");
        assert_eq!(reopened.installation_id(), installation_id);
        drop(reopened);

        let other_path = root.join("other.db");
        let other = DesktopSessionStore::open(&other_path).expect("open another profile store");
        assert_ne!(other.installation_id(), installation_id);
        drop(other);

        let future_path = root.join("future.db");
        {
            let connection =
                rusqlite::Connection::open(&future_path).expect("open future database");
            connection
                .execute_batch("PRAGMA user_version = 15;")
                .expect("mark future schema version");
        }
        let error = DesktopSessionStore::open(&future_path)
            .err()
            .expect("future schema must be rejected");
        assert!(error.contains("newer than supported schema version 14"));

        std::fs::remove_dir_all(root).expect("remove schema test root");
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
                "/api/v1/llm-providers/local-runtime/health-check",
                "member-provider-secret",
                json!({ "expected_revision": 0 }),
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
                        r#"{"project_id":"desktop-client","title":"Prototype context","agent_config":{"capability_mode":"code"}}"#,
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
                        r#"{"tenant_id":"local","project_id":"local-project","expected_revision":0,"idempotency_key":"switch-resource-scope"}"#,
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
                    .uri("/api/v1/agent/conversations?project_id=desktop-client")
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
                    .body(Body::from(r#"{"project_id":"desktop-client"}"#))
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
                        "/api/v1/agent/conversations/{conversation_id}/messages?project_id=desktop-client"
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
                        r#"{"project_id":"local-project","title":"Active context"}"#,
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
        assert_eq!(active_conversation["tenant_id"], "local");
        assert_eq!(active_conversation["project_id"], "local-project");
    }

    #[tokio::test]
    async fn cors_allows_tauri_origin_and_rejects_web_origin() {
        let app = local_router(test_state("launch-secret"));
        let provider_put_preflight = app
            .clone()
            .oneshot(
                Request::builder()
                    .method(Method::OPTIONS)
                    .uri("/api/v1/llm-providers/local-runtime")
                    .header("origin", "tauri://localhost")
                    .header("access-control-request-method", "PUT")
                    .header(
                        "access-control-request-headers",
                        "authorization,content-type,x-agistack-launch",
                    )
                    .body(Body::empty())
                    .expect("provider PUT preflight request"),
            )
            .await
            .expect("provider PUT preflight response");
        assert_eq!(provider_put_preflight.status(), axum::http::StatusCode::OK);
        assert_eq!(
            provider_put_preflight
                .headers()
                .get("access-control-allow-origin")
                .and_then(|value| value.to_str().ok()),
            Some("tauri://localhost")
        );
        assert!(provider_put_preflight
            .headers()
            .get("access-control-allow-methods")
            .and_then(|value| value.to_str().ok())
            .is_some_and(|methods| methods.split(',').any(|method| method.trim() == "PUT")));
        let allowed_headers = provider_put_preflight
            .headers()
            .get("access-control-allow-headers")
            .and_then(|value| value.to_str().ok())
            .expect("allowed provider PUT headers");
        for expected in ["authorization", "content-type", "x-agistack-launch"] {
            assert!(allowed_headers
                .split(',')
                .any(|header| header.trim().eq_ignore_ascii_case(expected)));
        }

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
    async fn lost_response_retry_replays_without_a_second_agent_execution() {
        let state = test_state("client-turn-retry-secret");
        let conversation_id = "conversation-client-turn-retry";
        seed_plan_conversation(&state, conversation_id);
        let app = local_router(Arc::clone(&state));

        let first = app
            .clone()
            .oneshot(conversation_message_request(
                "client-turn-retry-secret",
                conversation_id,
                "stable-client-message",
                "prepare the release plan",
            ))
            .await
            .expect("first response");
        assert_eq!(first.status(), StatusCode::OK);
        drop(first);

        let timeline = wait_for_agent_message_completion(&state, conversation_id).await;
        let initial_timeline_count = timeline.len();
        assert_eq!(
            timeline
                .iter()
                .filter(|event| event["type"] == "user_message")
                .count(),
            1
        );
        assert_eq!(
            timeline
                .iter()
                .filter(|event| event["type"] == "assistant_message")
                .count(),
            1
        );
        assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 1);
        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 1);
        assert!(state
            .session_store
            .list_runs(conversation_id)
            .expect("runs")
            .is_empty());

        let replay = app
            .clone()
            .oneshot(conversation_message_request(
                "client-turn-retry-secret",
                conversation_id,
                "stable-client-message",
                "prepare the release plan",
            ))
            .await
            .expect("replay response");
        assert_eq!(replay.status(), StatusCode::OK);
        let replay_payload = response_json(replay).await;
        assert_eq!(replay_payload["queued"], false);
        assert_eq!(replay_payload["created"], false);
        assert_eq!(replay_payload["replayed"], true);
        assert_eq!(replay_payload["message_id"], "stable-client-message");

        let conflict = app
            .oneshot(conversation_message_request(
                "client-turn-retry-secret",
                conversation_id,
                "stable-client-message",
                "prepare a different release plan",
            ))
            .await
            .expect("conflict response");
        assert_eq!(conflict.status(), StatusCode::CONFLICT);
        let conflict_payload = response_json(conflict).await;
        assert_eq!(conflict_payload["code"], "MESSAGE_ID_CONFLICT");
        assert_eq!(conflict_payload["message_id"], "stable-client-message");

        for _ in 0..10 {
            tokio::task::yield_now().await;
        }
        assert_eq!(
            state
                .session_store
                .timeline_count(conversation_id)
                .expect("timeline count"),
            initial_timeline_count
        );
        assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 1);
        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 1);
        assert!(state
            .session_store
            .list_runs(conversation_id)
            .expect("runs")
            .is_empty());
    }

    #[tokio::test]
    async fn concurrent_client_turn_replays_start_one_agent_execution() {
        let state = test_state("client-turn-concurrent-secret");
        let conversation_id = "conversation-client-turn-concurrent";
        seed_plan_conversation(&state, conversation_id);
        let app = local_router(Arc::clone(&state));

        let first = app.clone().oneshot(conversation_message_request(
            "client-turn-concurrent-secret",
            conversation_id,
            "concurrent-message",
            "draft one plan",
        ));
        let second = app.oneshot(conversation_message_request(
            "client-turn-concurrent-secret",
            conversation_id,
            "concurrent-message",
            "draft one plan",
        ));
        let (first, second) = tokio::join!(first, second);
        let first = first.expect("first concurrent response");
        let second = second.expect("second concurrent response");
        assert_eq!(first.status(), StatusCode::OK);
        assert_eq!(second.status(), StatusCode::OK);
        let first_payload = response_json(first).await;
        let second_payload = response_json(second).await;
        assert_ne!(first_payload["created"], second_payload["created"]);
        assert!(first_payload["created"] == true || second_payload["created"] == true);

        let timeline = wait_for_agent_message_completion(&state, conversation_id).await;
        assert_eq!(
            timeline
                .iter()
                .filter(|event| event["type"] == "user_message")
                .count(),
            1
        );
        assert_eq!(
            timeline
                .iter()
                .filter(|event| event["type"] == "assistant_message")
                .count(),
            1
        );
        assert!(!timeline.iter().any(|event| event["type"] == "error"));
        assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 1);
        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn invalid_client_message_ids_have_no_side_effects() {
        let state = test_state("client-turn-validation-secret");
        let conversation_id = "conversation-client-turn-validation";
        seed_plan_conversation(&state, conversation_id);
        let app = local_router(Arc::clone(&state));

        for message_id in ["   ".to_string(), "x".repeat(256)] {
            let response = app
                .clone()
                .oneshot(conversation_message_request(
                    "client-turn-validation-secret",
                    conversation_id,
                    &message_id,
                    "must not execute",
                ))
                .await
                .expect("validation response");
            assert_eq!(response.status(), StatusCode::BAD_REQUEST);
            assert_eq!(response_json(response).await["code"], "INVALID_MESSAGE_ID");
        }

        assert_eq!(
            state
                .session_store
                .timeline_count(conversation_id)
                .expect("timeline count"),
            0
        );
        let client_turn_count: i64 = state
            .session_store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_client_turns WHERE conversation_id = ?1",
                [conversation_id],
                |row| row.get(0),
            )
            .expect("client turn count");
        assert_eq!(client_turn_count, 0);
        assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 0);
        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 0);
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
            assert!(store
                .claim_client_turn(
                    &conversation.id,
                    "persistent-message-id",
                    "payload-hash",
                    &now_iso(),
                )
                .expect("claim client turn"));
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
        assert!(!restored
            .claim_client_turn(
                "conversation-1",
                "persistent-message-id",
                "payload-hash",
                &now_iso(),
            )
            .expect("replay durable client turn"));
        assert_eq!(
            restored.claim_client_turn(
                "conversation-1",
                "persistent-message-id",
                "different-payload-hash",
                &now_iso(),
            ),
            Err(DesktopClientTurnClaimError::PayloadConflict)
        );
        drop(restored);
        let connection = rusqlite::Connection::open(&path).expect("inspect schema version");
        let schema_version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .expect("schema version");
        assert_eq!(schema_version, 14);
        drop(connection);
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[test]
    fn local_demo_hierarchy_seed_creates_the_expected_fresh_scope() {
        let state = test_state_without_session("local-demo-fresh-secret");

        let default_context = state
            .session_store
            .workspace_context("local-user")
            .expect("default workspace context");
        assert_eq!(default_context.tenant_id, "northstar");
        assert_eq!(default_context.project_id, "desktop-client");

        let workspaces = state
            .session_store
            .list_workspaces("desktop-client")
            .expect("desktop client workspaces");
        assert_eq!(workspaces.len(), 2);
        assert_eq!(
            workspaces
                .iter()
                .map(|workspace| workspace["id"].as_str().expect("workspace id"))
                .collect::<Vec<_>>(),
            vec![
                "local-demo-desktop-client-main",
                "local-demo-release-reliability",
            ]
        );
        for workspace in &workspaces {
            assert_eq!(workspace["tenant_id"], "northstar");
            assert_eq!(workspace["project_id"], "desktop-client");
            assert_eq!(
                workspace["metadata"]["provenance"]["kind"],
                "local_demo_seed"
            );
        }

        let desktop_sessions = state
            .session_store
            .list_conversations("desktop-client", Some("local-demo-desktop-client-main"))
            .expect("desktop client demo sessions");
        let reliability_sessions = state
            .session_store
            .list_conversations("desktop-client", Some("local-demo-release-reliability"))
            .expect("release reliability demo sessions");
        assert_eq!(desktop_sessions.len(), 3);
        assert_eq!(reliability_sessions.len(), 1);
        for conversation in desktop_sessions.iter().chain(&reliability_sessions) {
            assert_eq!(conversation.tenant_id, "northstar");
            assert_eq!(conversation.project_id, "desktop-client");
            assert_eq!(
                conversation.capability_mode,
                ConversationCapabilityMode::Code
            );
            assert_eq!(conversation.current_mode, ConversationRunMode::Plan);
            let expected_timeline_count = if conversation.id == LOCAL_DEMO_PRIMARY_CONVERSATION_ID {
                13
            } else {
                0
            };
            assert_eq!(
                state
                    .session_store
                    .timeline_count(&conversation.id)
                    .expect("demo timeline count"),
                expected_timeline_count
            );
            assert!(state
                .session_store
                .list_runs(&conversation.id)
                .expect("empty demo run history")
                .is_empty());
        }
        let seed_marker_count: i64 = state
            .session_store
            .connection()
            .expect("seed marker connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_seed_migrations
                 WHERE seed_id = 'northstar-desktop-client-local-demo-v1'
                   AND seed_kind = 'local_demo_hierarchy'",
                [],
                |row| row.get(0),
            )
            .expect("local demo seed marker count");
        assert_eq!(seed_marker_count, 1);
    }

    #[test]
    fn local_demo_session_content_seed_creates_authoritative_narrative_and_workspace_names() {
        let state = test_state_without_session("local-demo-content-secret");
        let timeline = state
            .session_store
            .timeline("local-demo-flaky-data-pipeline-test", 50)
            .expect("seeded demo timeline");
        assert_eq!(timeline.len(), 13);
        assert_eq!(
            timeline.first().and_then(|item| item["id"].as_str()),
            Some("local-demo-flaky-data-pipeline-test:user-goal")
        );
        assert_eq!(
            timeline.first().and_then(|item| item["role"].as_str()),
            Some("user")
        );
        assert_eq!(
            timeline.last().and_then(|item| item["id"].as_str()),
            Some("local-demo-flaky-data-pipeline-test:verification-progress")
        );
        assert!(timeline.iter().any(|item| {
            item["type"] == "assistant_message"
                && item["content"]
                    .as_str()
                    .is_some_and(|content| content.contains("shared mutable state"))
        }));
        assert_eq!(
            timeline.iter().filter(|item| item["type"] == "act").count(),
            4
        );

        let desktop_conversation = state
            .session_store
            .conversation("local-demo-flaky-data-pipeline-test")
            .expect("load desktop demo conversation")
            .expect("desktop demo conversation");
        assert_eq!(
            state.conversation_value(&desktop_conversation)["workspace_name"],
            "Desktop Client"
        );
        let reliability_conversation = state
            .session_store
            .conversation("local-demo-agent-sdk-upgrade")
            .expect("load reliability demo conversation")
            .expect("reliability demo conversation");
        assert_eq!(
            state.conversation_value(&reliability_conversation)["workspace_name"],
            "Release Reliability"
        );
    }

    #[test]
    fn local_demo_session_content_seed_is_idempotent_after_reopen() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create local demo content root");
        let path = root.join("desktop-sessions.db");

        for token in ["local-demo-content-first", "local-demo-content-second"] {
            let store = DesktopSessionStore::open(&path).expect("open local demo content store");
            let tool_host = LocalToolHost::new(&root).expect("local demo content tool host");
            let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
            let state = LocalRuntimeState::new(
                root.clone(),
                tool_host,
                checkpoints,
                token.to_string(),
                store,
            )
            .expect("seed local demo content state");
            let timeline = state
                .session_store
                .timeline("local-demo-flaky-data-pipeline-test", 50)
                .expect("reopened local demo timeline");
            assert_eq!(timeline.len(), 13);
            assert_eq!(
                timeline
                    .iter()
                    .filter(|item| {
                        item["id"] == "local-demo-flaky-data-pipeline-test:user-goal"
                    })
                    .count(),
                1
            );
        }

        std::fs::remove_dir_all(root).expect("remove local demo content root");
    }

    #[test]
    fn local_demo_session_content_seed_fails_closed_on_event_conflict() {
        let store = DesktopSessionStore::in_memory().expect("local demo content conflict store");
        let now = now_iso();
        let hierarchy = local_demo_hierarchy_seed(&now);
        store
            .ensure_local_demo_hierarchy_seed(
                LOCAL_DEMO_HIERARCHY_SEED_ID,
                &hierarchy.workspaces,
                &hierarchy.conversations,
                &now,
            )
            .expect("seed hierarchy before content conflict");
        store
            .append_timeline(
                "local-demo-flaky-data-pipeline-test",
                &json!({
                    "id": "local-demo-flaky-data-pipeline-test:user-goal",
                    "type": "user_message",
                    "conversation_id": "local-demo-flaky-data-pipeline-test",
                    "role": "user",
                    "content": "Conflicting user-authored local content",
                }),
            )
            .expect("insert conflicting timeline event");
        let root = test_root();
        let error = LocalRuntimeState::new(
            root.clone(),
            LocalToolHost::new(&root).expect("content conflict tool host"),
            Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints")),
            "local-demo-content-conflict".to_string(),
            store,
        )
        .err()
        .expect("local demo content conflict must fail startup");
        assert!(error.contains("local demo session content event conflict"));
    }

    #[test]
    fn local_demo_hierarchy_seed_is_idempotent_across_reopen_without_overwrite() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create demo seed root");
        let path = root.join("desktop-sessions.db");
        let user_updated_at = "2042-05-06T07:08:09Z";

        {
            let store = DesktopSessionStore::open(&path).expect("open first demo store");
            let tool_host = LocalToolHost::new(&root).expect("first demo tool host");
            let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
            let state = LocalRuntimeState::new(
                root.clone(),
                tool_host,
                checkpoints,
                "first-demo-token".to_string(),
                store,
            )
            .expect("seed first demo state");
            let mut conversation = state
                .session_store
                .conversation("local-demo-flaky-data-pipeline-test")
                .expect("load demo conversation")
                .expect("seeded demo conversation");
            conversation.title = "User renamed this local demo session".to_string();
            conversation.current_mode = ConversationRunMode::Build;
            conversation.updated_at = user_updated_at.to_string();
            state
                .session_store
                .update_conversation(&conversation)
                .expect("persist user demo changes");
        }

        {
            let store = DesktopSessionStore::open(&path).expect("reopen demo store");
            let tool_host = LocalToolHost::new(&root).expect("second demo tool host");
            let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
            let state = LocalRuntimeState::new(
                root.clone(),
                tool_host,
                checkpoints,
                "second-demo-token".to_string(),
                store,
            )
            .expect("reopen seeded demo state");
            assert_eq!(
                state
                    .session_store
                    .list_workspaces("desktop-client")
                    .expect("reopened workspaces")
                    .len(),
                2
            );
            assert_eq!(
                state
                    .session_store
                    .list_conversations("desktop-client", None)
                    .expect("reopened conversations")
                    .len(),
                4
            );
            let conversation = state
                .session_store
                .conversation("local-demo-flaky-data-pipeline-test")
                .expect("load reopened conversation")
                .expect("reopened demo conversation");
            assert_eq!(conversation.title, "User renamed this local demo session");
            assert_eq!(conversation.current_mode, ConversationRunMode::Build);
            assert_eq!(conversation.updated_at, user_updated_at);
            let seed_marker_count: i64 = state
                .session_store
                .connection()
                .expect("reopened seed marker connection")
                .query_row(
                    "SELECT COUNT(*) FROM desktop_seed_migrations
                     WHERE seed_id = 'northstar-desktop-client-local-demo-v1'",
                    [],
                    |row| row.get(0),
                )
                .expect("reopened local demo seed marker count");
            assert_eq!(seed_marker_count, 1);
        }

        std::fs::remove_dir_all(root).expect("remove demo seed root");
    }

    #[test]
    fn local_demo_hierarchy_seed_fails_closed_on_immutable_scope_conflicts() {
        let workspace_store = DesktopSessionStore::in_memory().expect("workspace conflict store");
        workspace_store
            .insert_workspace(&json!({
                "id": "local-demo-desktop-client-main",
                "tenant_id": "orbital",
                "project_id": "desktop-client",
                "name": "Conflicting workspace",
            }))
            .expect("insert conflicting workspace");
        let workspace_root = test_root();
        let workspace_error = LocalRuntimeState::new(
            workspace_root.clone(),
            LocalToolHost::new(&workspace_root).expect("workspace conflict tool host"),
            Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints")),
            "workspace-conflict-token".to_string(),
            workspace_store,
        )
        .err()
        .expect("workspace scope conflict must fail startup");
        assert!(workspace_error.contains("local demo workspace scope conflict"));

        let conversation_store =
            DesktopSessionStore::in_memory().expect("conversation conflict store");
        conversation_store
            .insert_conversation(&LocalConversation {
                id: "local-demo-flaky-data-pipeline-test".to_string(),
                tenant_id: "northstar".to_string(),
                project_id: "desktop-client".to_string(),
                workspace_id: Some("local-demo-release-reliability".to_string()),
                title: "Conflicting conversation".to_string(),
                capability_mode: ConversationCapabilityMode::Code,
                current_mode: ConversationRunMode::Plan,
                created_at: now_iso(),
                updated_at: now_iso(),
            })
            .expect("insert conflicting conversation");
        let conversation_root = test_root();
        let conversation_error = LocalRuntimeState::new(
            conversation_root.clone(),
            LocalToolHost::new(&conversation_root).expect("conversation conflict tool host"),
            Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints")),
            "conversation-conflict-token".to_string(),
            conversation_store,
        )
        .err()
        .expect("conversation scope conflict must fail startup");
        assert!(conversation_error.contains("local demo conversation scope conflict"));
    }

    #[test]
    fn local_demo_hierarchy_seed_rejects_structural_column_scope_conflicts() {
        let store = DesktopSessionStore::in_memory().expect("column conflict store");
        let now = now_iso();
        let seed = local_demo_hierarchy_seed(&now);
        store
            .ensure_local_demo_hierarchy_seed(
                LOCAL_DEMO_HIERARCHY_SEED_ID,
                &seed.workspaces,
                &seed.conversations,
                &now,
            )
            .expect("apply local demo seed");
        store
            .connection()
            .expect("column conflict connection")
            .execute(
                "UPDATE desktop_conversations
                 SET workspace_id = 'local-demo-release-reliability'
                 WHERE id = 'local-demo-flaky-data-pipeline-test'",
                [],
            )
            .expect("corrupt structural workspace column");

        let error = store
            .ensure_local_demo_hierarchy_seed(
                LOCAL_DEMO_HIERARCHY_SEED_ID,
                &seed.workspaces,
                &seed.conversations,
                &now,
            )
            .expect_err("structural scope conflict must fail closed");
        assert!(error.contains("local demo conversation column scope conflict"));
    }

    #[tokio::test]
    async fn local_demo_hierarchy_rejects_conversation_workspace_reassignment() {
        let state = test_state("local-demo-reassignment-secret");
        let authenticated = state
            .session_store
            .validate_session_credential(
                "local-demo-reassignment-secret",
                Utc::now().timestamp_millis(),
            )
            .expect("validate local demo session")
            .expect("authenticated local demo session");
        state
            .session_store
            .switch_workspace_context(
                &authenticated,
                &ContextSwitchRequest {
                    tenant_id: "northstar".to_string(),
                    project_id: "desktop-client".to_string(),
                    expected_revision: 0,
                    idempotency_key: "switch-local-demo-reassignment".to_string(),
                },
                Utc::now().timestamp_millis(),
            )
            .expect("switch to local demo hierarchy");

        let response = local_router(Arc::clone(&state))
            .oneshot(authenticated_json_request(
                "PATCH",
                "/api/v1/agent/conversations/local-demo-flaky-data-pipeline-test/mode",
                "local-demo-reassignment-secret",
                json!({ "workspace_id": "local-demo-release-reliability" }),
            ))
            .await
            .expect("seeded conversation reassignment response");
        assert_eq!(response.status(), StatusCode::CONFLICT);

        let conversation = state
            .session_store
            .conversation("local-demo-flaky-data-pipeline-test")
            .expect("load seeded conversation")
            .expect("seeded conversation");
        assert_eq!(
            conversation.workspace_id.as_deref(),
            Some(LOCAL_DEMO_DESKTOP_WORKSPACE_ID)
        );
        let now = now_iso();
        let seed = local_demo_hierarchy_seed(&now);
        state
            .session_store
            .ensure_local_demo_hierarchy_seed(
                LOCAL_DEMO_HIERARCHY_SEED_ID,
                &seed.workspaces,
                &seed.conversations,
                &now,
            )
            .expect("reopen invariant remains valid after rejected patch");
    }

    #[tokio::test]
    async fn local_demo_hierarchy_routes_follow_the_exact_switched_scope() {
        let state = test_state("local-demo-route-secret");
        let authenticated = state
            .session_store
            .validate_session_credential("local-demo-route-secret", Utc::now().timestamp_millis())
            .expect("validate local demo session")
            .expect("authenticated local demo session");
        state
            .session_store
            .switch_workspace_context(
                &authenticated,
                &ContextSwitchRequest {
                    tenant_id: "northstar".to_string(),
                    project_id: "desktop-client".to_string(),
                    expected_revision: 0,
                    idempotency_key: "switch-local-demo-hierarchy".to_string(),
                },
                Utc::now().timestamp_millis(),
            )
            .expect("switch to local demo hierarchy");
        let app = local_router(state);

        let workspaces_response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/tenants/northstar/projects/desktop-client/workspaces")
                    .header("authorization", "Bearer local-demo-route-secret")
                    .body(Body::empty())
                    .expect("workspace list request"),
            )
            .await
            .expect("workspace list response");
        assert_eq!(workspaces_response.status(), StatusCode::OK);
        let workspaces = response_json(workspaces_response).await;
        assert_eq!(workspaces["items"].as_array().map(Vec::len), Some(2));

        let conversations_response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/agent/conversations?project_id=desktop-client&workspace_id=local-demo-desktop-client-main")
                    .header("authorization", "Bearer local-demo-route-secret")
                    .body(Body::empty())
                    .expect("conversation list request"),
            )
            .await
            .expect("conversation list response");
        assert_eq!(conversations_response.status(), StatusCode::OK);
        let conversations = response_json(conversations_response).await;
        assert_eq!(conversations["items"].as_array().map(Vec::len), Some(3));
        for conversation in conversations["items"]
            .as_array()
            .expect("conversation items")
        {
            assert_eq!(conversation["tenant_id"], "northstar");
            assert_eq!(conversation["project_id"], "desktop-client");
            assert_eq!(
                conversation["workspace_id"],
                "local-demo-desktop-client-main"
            );
        }

        let projection_response = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/agent/conversations/local-demo-flaky-data-pipeline-test/session?tenant_id=northstar&project_id=desktop-client&workspace_id=local-demo-desktop-client-main")
                    .header("authorization", "Bearer local-demo-route-secret")
                    .body(Body::empty())
                    .expect("exact session projection request"),
            )
            .await
            .expect("exact session projection response");
        assert_eq!(projection_response.status(), StatusCode::OK);
        let projection = response_json(projection_response).await;
        assert_eq!(projection["conversation"]["tenant_id"], "northstar");
        assert_eq!(projection["conversation"]["project_id"], "desktop-client");
        assert_eq!(
            projection["conversation"]["workspace_id"],
            "local-demo-desktop-client-main"
        );
    }

    fn create_task_session_request(idempotency_key: &str, title: &str) -> Value {
        json!({
            "idempotency_key": idempotency_key,
            "workspace": {
                "kind": "create",
                "name": title,
                "description": "An atomic desktop task session",
                "metadata": {
                    "source": "desktop",
                    "retained": true,
                    "use_case": "research",
                    "collaboration_mode": "autonomous",
                    "sandbox_code_root": "/tmp/untrusted-task-root",
                },
                "use_case": "programming",
                "collaboration_mode": "multi_agent_shared",
                "sandbox_code_root": "/tmp/atomic-task-session",
            },
            "conversation": {
                "title": title,
                "capability_mode": "code",
            },
            "initial_message": {
                "content": "Build the approved desktop task flow",
            },
        })
    }

    #[tokio::test]
    async fn task_session_route_creates_bound_metadata_complete_session_and_replays() {
        let state = test_state("task-session-replay-secret");
        let app = local_router(Arc::clone(&state));
        let request = create_task_session_request("task-session-replay", "Atomic task session");

        let first = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/task-sessions",
                "task-session-replay-secret",
                request.clone(),
            ))
            .await
            .expect("first task session response");
        assert_eq!(first.status(), StatusCode::OK);
        let first = response_json(first).await;
        assert_eq!(first["replayed"], false);
        assert_eq!(first["workspace"]["name"], "Atomic task session");
        assert_eq!(
            first["workspace"]["description"],
            "An atomic desktop task session"
        );
        assert_eq!(first["workspace"]["metadata"]["source"], "desktop");
        assert_eq!(first["workspace"]["metadata"]["retained"], true);
        assert_eq!(first["workspace"]["metadata"]["use_case"], "programming");
        assert_eq!(
            first["workspace"]["metadata"]["collaboration_mode"],
            "multi_agent_shared"
        );
        assert_eq!(
            first["workspace"]["metadata"]["sandbox_code_root"],
            "/tmp/atomic-task-session"
        );
        assert_eq!(first["workspace"]["use_case"], "programming");
        assert_eq!(
            first["workspace"]["collaboration_mode"],
            "multi_agent_shared"
        );
        assert_eq!(
            first["workspace"]["sandbox_code_root"],
            "/tmp/atomic-task-session"
        );
        assert_eq!(first["conversation"]["current_mode"], "plan");
        assert_eq!(
            first["conversation"]["workspace_id"],
            first["workspace"]["id"]
        );
        assert_eq!(
            first["initial_message"]["workspace_id"],
            first["workspace"]["id"]
        );
        assert_eq!(
            first["initial_message"]["content"],
            "Build the approved desktop task flow"
        );
        let original_conversation = first["conversation"].clone();

        let conversation_id = first["conversation"]["id"]
            .as_str()
            .expect("created conversation id");
        let mut persisted_conversation = state
            .session_store
            .conversation(conversation_id)
            .expect("query created conversation")
            .expect("created conversation");
        persisted_conversation.current_mode = ConversationRunMode::Build;
        persisted_conversation.updated_at = now_iso();
        state
            .session_store
            .update_conversation(&persisted_conversation)
            .expect("mutate conversation after task session creation");

        let replay = app
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/task-sessions",
                "task-session-replay-secret",
                request,
            ))
            .await
            .expect("replayed task session response");
        assert_eq!(replay.status(), StatusCode::OK);
        let replay = response_json(replay).await;
        assert_eq!(replay["replayed"], true);
        assert_eq!(replay["workspace"]["id"], first["workspace"]["id"]);
        assert_eq!(replay["conversation"]["id"], first["conversation"]["id"]);
        assert_eq!(replay["conversation"]["current_mode"], "plan");
        assert_eq!(replay["conversation"], original_conversation);
        assert_eq!(
            replay["initial_message"]["id"],
            first["initial_message"]["id"]
        );
        assert_eq!(
            state
                .session_store
                .conversation(conversation_id)
                .expect("query mutated conversation")
                .expect("mutated conversation")
                .current_mode,
            ConversationRunMode::Build
        );

        assert_eq!(
            state
                .session_store
                .list_workspaces("local-project")
                .expect("workspaces")
                .iter()
                .filter(|workspace| workspace["name"] == "Atomic task session")
                .count(),
            1
        );
        assert_eq!(
            state
                .session_store
                .list_conversations("local-project", None)
                .expect("conversations")
                .iter()
                .filter(|conversation| conversation.title == "Atomic task session")
                .count(),
            1
        );
    }

    #[tokio::test]
    async fn task_session_route_rejects_changed_payload_for_idempotency_key() {
        let state = test_state("task-session-conflict-secret");
        let app = local_router(Arc::clone(&state));
        let first_request = create_task_session_request("task-session-conflict", "First title");
        let first = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/task-sessions",
                "task-session-conflict-secret",
                first_request,
            ))
            .await
            .expect("first conflict fixture response");
        assert_eq!(first.status(), StatusCode::OK);

        let conflict = app
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/task-sessions",
                "task-session-conflict-secret",
                create_task_session_request("task-session-conflict", "Changed title"),
            ))
            .await
            .expect("task session conflict response");
        assert_eq!(conflict.status(), StatusCode::CONFLICT);
        assert_eq!(
            response_json(conflict).await["code"],
            "TASK_SESSION_IDEMPOTENCY_CONFLICT"
        );
        assert_eq!(
            state
                .session_store
                .list_conversations("local-project", None)
                .expect("conversations")
                .iter()
                .filter(|conversation| {
                    matches!(conversation.title.as_str(), "First title" | "Changed title")
                })
                .count(),
            1
        );
    }

    #[tokio::test]
    async fn task_session_receipt_replays_and_conflicts_after_store_reopen() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create task session restart root");
        let store_path = root.join("task-session-restart.db");
        let credential = "task-session-restart-secret";
        let request = create_task_session_request("task-session-restart", "Restart-safe task");

        let (workspace_id, conversation_id, initial_message_id) = {
            let state = Arc::new(
                LocalRuntimeState::new(
                    root.clone(),
                    LocalToolHost::new(&root).expect("restart tool host"),
                    Arc::new(SqliteCheckpointStore::in_memory().expect("restart checkpoint store")),
                    credential.to_string(),
                    DesktopSessionStore::open(&store_path).expect("open restart session store"),
                )
                .expect("restart local runtime state"),
            );
            state
                .session_store
                .seed_test_session(credential)
                .expect("seed restart session");
            let response = local_router(state)
                .oneshot(authenticated_json_request(
                    "POST",
                    "/api/v1/tenants/local/projects/local-project/task-sessions",
                    credential,
                    request.clone(),
                ))
                .await
                .expect("create restart task session");
            assert_eq!(response.status(), StatusCode::OK);
            let response = response_json(response).await;
            (
                response["workspace"]["id"]
                    .as_str()
                    .expect("restart workspace id")
                    .to_string(),
                response["conversation"]["id"]
                    .as_str()
                    .expect("restart conversation id")
                    .to_string(),
                response["initial_message"]["id"]
                    .as_str()
                    .expect("restart initial message id")
                    .to_string(),
            )
        };

        {
            let state = Arc::new(
                LocalRuntimeState::new(
                    root.clone(),
                    LocalToolHost::new(&root).expect("reopened tool host"),
                    Arc::new(
                        SqliteCheckpointStore::in_memory().expect("reopened checkpoint store"),
                    ),
                    credential.to_string(),
                    DesktopSessionStore::open(&store_path).expect("reopen task session store"),
                )
                .expect("reopened local runtime state"),
            );
            let app = local_router(state);
            let replay = app
                .clone()
                .oneshot(authenticated_json_request(
                    "POST",
                    "/api/v1/tenants/local/projects/local-project/task-sessions",
                    credential,
                    request,
                ))
                .await
                .expect("replay reopened task session");
            assert_eq!(replay.status(), StatusCode::OK);
            let replay = response_json(replay).await;
            assert_eq!(replay["replayed"], true);
            assert_eq!(replay["workspace"]["id"], workspace_id);
            assert_eq!(replay["conversation"]["id"], conversation_id);
            assert_eq!(replay["initial_message"]["id"], initial_message_id);

            let conflict = app
                .oneshot(authenticated_json_request(
                    "POST",
                    "/api/v1/tenants/local/projects/local-project/task-sessions",
                    credential,
                    create_task_session_request("task-session-restart", "Changed after restart"),
                ))
                .await
                .expect("conflict reopened task session");
            assert_eq!(conflict.status(), StatusCode::CONFLICT);
        }

        std::fs::remove_dir_all(root).expect("remove task session restart root");
    }

    #[tokio::test]
    async fn task_session_route_rejects_unknown_request_fields() {
        let state = test_state("task-session-strict-secret");
        let app = local_router(state);
        for object_pointer in ["", "/workspace", "/conversation", "/initial_message"] {
            let mut request = create_task_session_request("task-session-strict", "Strict request");
            request
                .pointer_mut(object_pointer)
                .expect("strict request object")["unexpected"] = json!(true);
            let response = app
                .clone()
                .oneshot(authenticated_json_request(
                    "POST",
                    "/api/v1/tenants/local/projects/local-project/task-sessions",
                    "task-session-strict-secret",
                    request,
                ))
                .await
                .expect("strict task session response");
            assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
        }

        let mut request = create_task_session_request("task-session-strict", "Strict request");
        request["conversation"]["capability_mode"] = json!("unavailable");
        let response = app
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/task-sessions",
                "task-session-strict-secret",
                request,
            ))
            .await
            .expect("strict task session capability response");
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn task_session_route_supports_existing_workspace_without_duplicate_workspace() {
        let state = test_state("task-session-existing-secret");
        let workspace_count = state
            .session_store
            .list_workspaces("local-project")
            .expect("workspaces before task session")
            .len();
        let response = local_router(Arc::clone(&state))
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/task-sessions",
                "task-session-existing-secret",
                json!({
                    "idempotency_key": "task-session-existing",
                    "workspace": {
                        "kind": "existing",
                        "workspace_id": "local-workspace",
                    },
                    "conversation": {
                        "title": "Existing workspace task",
                        "capability_mode": "work",
                    },
                    "initial_message": {
                        "content": "Continue in the selected workspace",
                    },
                }),
            ))
            .await
            .expect("existing workspace task session response");
        assert_eq!(response.status(), StatusCode::OK);
        let payload = response_json(response).await;
        assert_eq!(payload["workspace"]["id"], "local-workspace");
        assert_eq!(payload["conversation"]["workspace_id"], "local-workspace");
        assert_eq!(payload["conversation"]["current_mode"], "plan");
        assert_eq!(
            state
                .session_store
                .list_workspaces("local-project")
                .expect("workspaces after task session")
                .len(),
            workspace_count
        );
    }

    #[tokio::test]
    async fn task_session_and_workspace_routes_reject_inactive_scope_without_writes() {
        let state = test_state("task-session-scope-secret");
        state
            .session_store
            .insert_workspace(&json!({
                "id": "outside-tenant-same-project",
                "tenant_id": "outside",
                "project_id": "local-project",
                "name": "Outside tenant workspace",
            }))
            .expect("insert outside tenant workspace");
        let app = local_router(Arc::clone(&state));
        let wrong_tenant = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/outside/projects/local-project/task-sessions",
                "task-session-scope-secret",
                create_task_session_request("wrong-tenant-task-session", "Wrong tenant"),
            ))
            .await
            .expect("wrong tenant task session response");
        assert_eq!(wrong_tenant.status(), StatusCode::FORBIDDEN);

        let wrong_project = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/outside/task-sessions",
                "task-session-scope-secret",
                create_task_session_request("wrong-project-task-session", "Wrong project"),
            ))
            .await
            .expect("wrong project task session response");
        assert_eq!(wrong_project.status(), StatusCode::FORBIDDEN);

        let foreign_existing_workspace = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/task-sessions",
                "task-session-scope-secret",
                json!({
                    "idempotency_key": "foreign-existing-workspace",
                    "workspace": {
                        "kind": "existing",
                        "workspace_id": "outside-tenant-same-project",
                    },
                    "conversation": {
                        "title": "Foreign existing workspace task",
                        "capability_mode": "work",
                    },
                    "initial_message": { "content": "Must remain tenant scoped" },
                }),
            ))
            .await
            .expect("foreign existing workspace response");
        assert_eq!(foreign_existing_workspace.status(), StatusCode::FORBIDDEN);

        let wrong_workspace_create = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/outside/projects/local-project/workspaces",
                "task-session-scope-secret",
                json!({ "name": "Wrong scoped workspace" }),
            ))
            .await
            .expect("wrong scope workspace create response");
        assert_eq!(wrong_workspace_create.status(), StatusCode::FORBIDDEN);

        let wrong_workspace_list = app
            .clone()
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/tenants/local/projects/outside/workspaces",
                "task-session-scope-secret",
                json!({}),
            ))
            .await
            .expect("wrong scope workspace list response");
        assert_eq!(wrong_workspace_list.status(), StatusCode::FORBIDDEN);

        let active_workspace_list = app
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/tenants/local/projects/local-project/workspaces",
                "task-session-scope-secret",
                json!({}),
            ))
            .await
            .expect("active scope workspace list response");
        assert_eq!(active_workspace_list.status(), StatusCode::OK);
        assert!(!response_json(active_workspace_list).await["items"]
            .as_array()
            .expect("workspace items")
            .iter()
            .any(|workspace| workspace["id"] == "outside-tenant-same-project"));

        assert!(!state
            .session_store
            .list_workspaces("local-project")
            .expect("workspaces")
            .iter()
            .any(|workspace| workspace["name"] == "Wrong scoped workspace"));
        assert!(!state
            .session_store
            .list_conversations("local-project", None)
            .expect("conversations")
            .iter()
            .any(|conversation| {
                matches!(
                    conversation.title.as_str(),
                    "Wrong tenant" | "Wrong project" | "Foreign existing workspace task"
                )
            }));

        let stale_context = state
            .session_store
            .validate_session_credential("task-session-scope-secret", Utc::now().timestamp_millis())
            .expect("validate stale context fixture")
            .expect("stale context fixture");
        state
            .session_store
            .connection()
            .expect("workspace context connection")
            .execute(
                "UPDATE desktop_workspace_contexts SET revision = revision + 1 WHERE user_id = ?1",
                [&stale_context.user.user_id],
            )
            .expect("advance authoritative workspace context revision");
        let stale_body = serde_json::from_value(create_task_session_request(
            "stale-context-task-session",
            "Stale context task",
        ))
        .expect("deserialize stale task session body");
        let stale_response = task_session::create_task_session(
            State(Arc::clone(&state)),
            Extension(stale_context),
            Path(("local".to_string(), "local-project".to_string())),
            Json(stale_body),
        )
        .await
        .expect_err("stale context must fail transaction validation");
        assert_eq!(stale_response.0, StatusCode::FORBIDDEN);
        assert!(!state
            .session_store
            .list_conversations("local-project", None)
            .expect("conversations after stale context")
            .iter()
            .any(|conversation| conversation.title == "Stale context task"));
        assert!(!state
            .session_store
            .list_workspaces("local-project")
            .expect("workspaces after stale context")
            .iter()
            .any(|workspace| workspace["name"] == "Stale context task"));
        let stale_receipt_count: i64 = state
            .session_store
            .connection()
            .expect("stale receipt connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_new_task_sessions WHERE idempotency_key = ?1",
                ["stale-context-task-session"],
                |row| row.get(0),
            )
            .expect("count stale context receipts");
        assert_eq!(stale_receipt_count, 0);
    }

    #[tokio::test]
    async fn workspace_create_route_preserves_typed_metadata_and_rejects_unknown_fields() {
        let state = test_state("workspace-create-contract-secret");
        let app = local_router(state);
        let created = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/workspaces",
                "workspace-create-contract-secret",
                json!({
                    "name": "Typed workspace",
                    "description": "Preserve the desktop contract",
                    "metadata": {
                        "source": "desktop",
                        "retained": true,
                        "use_case": "general",
                        "collaboration_mode": "autonomous",
                        "sandbox_code_root": "/tmp/untrusted-workspace-root",
                    },
                    "use_case": "research",
                    "collaboration_mode": "multi_agent_shared",
                    "sandbox_code_root": "/tmp/typed-workspace",
                }),
            ))
            .await
            .expect("typed workspace response");
        assert_eq!(created.status(), StatusCode::OK);
        let created = response_json(created).await;
        assert_eq!(created["use_case"], "research");
        assert_eq!(created["collaboration_mode"], "multi_agent_shared");
        assert_eq!(created["sandbox_code_root"], "/tmp/typed-workspace");
        assert_eq!(created["metadata"]["retained"], true);
        assert_eq!(created["metadata"]["use_case"], "research");
        assert_eq!(
            created["metadata"]["collaboration_mode"],
            "multi_agent_shared"
        );
        assert_eq!(
            created["metadata"]["sandbox_code_root"],
            "/tmp/typed-workspace"
        );

        let without_sandbox = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/workspaces",
                "workspace-create-contract-secret",
                json!({
                    "name": "Workspace without sandbox",
                    "metadata": { "sandbox_code_root": "/tmp/untrusted-workspace-root" },
                    "use_case": "conversation",
                    "collaboration_mode": "single_agent",
                }),
            ))
            .await
            .expect("workspace without sandbox response");
        assert_eq!(without_sandbox.status(), StatusCode::OK);
        let without_sandbox = response_json(without_sandbox).await;
        assert!(without_sandbox["sandbox_code_root"].is_null());
        assert!(without_sandbox["metadata"]["sandbox_code_root"].is_null());

        let invalid = app
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/workspaces",
                "workspace-create-contract-secret",
                json!({
                    "name": "Invalid workspace",
                    "unexpected": true,
                }),
            ))
            .await
            .expect("strict workspace response");
        assert_eq!(invalid.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn task_session_transaction_rolls_back_workspace_when_conversation_insert_fails() {
        let state = test_state("task-session-conversation-failure-secret");
        {
            let connection = state.session_store.connection().expect("connection");
            connection
                .execute_batch(
                    "CREATE TEMP TRIGGER fail_task_session_conversation
                     BEFORE INSERT ON desktop_conversations
                     WHEN NEW.id LIKE 'local-conversation-%'
                     BEGIN
                       SELECT RAISE(ABORT, 'forced task session conversation failure');
                     END;",
                )
                .expect("install conversation failure");
        }

        let response = local_router(Arc::clone(&state))
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/task-sessions",
                "task-session-conversation-failure-secret",
                create_task_session_request(
                    "task-session-conversation-failure",
                    "Rolled back workspace",
                ),
            ))
            .await
            .expect("conversation failure response");
        assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
        assert!(!state
            .session_store
            .list_workspaces("local-project")
            .expect("workspaces")
            .iter()
            .any(|workspace| workspace["name"] == "Rolled back workspace"));
        assert!(!state
            .session_store
            .list_conversations("local-project", None)
            .expect("conversations")
            .iter()
            .any(|conversation| conversation.title == "Rolled back workspace"));
    }

    #[tokio::test]
    async fn task_session_transaction_rolls_back_all_rows_when_receipt_insert_fails() {
        let state = test_state("task-session-receipt-failure-secret");
        {
            let connection = state.session_store.connection().expect("connection");
            connection
                .execute_batch(
                    "CREATE TEMP TRIGGER fail_task_session_receipt
                     BEFORE INSERT ON desktop_new_task_sessions
                     BEGIN
                       SELECT RAISE(ABORT, 'forced task session receipt failure');
                     END;",
                )
                .expect("install receipt failure");
        }

        let response = local_router(Arc::clone(&state))
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/task-sessions",
                "task-session-receipt-failure-secret",
                create_task_session_request(
                    "task-session-receipt-failure",
                    "Receipt rollback task",
                ),
            ))
            .await
            .expect("receipt failure response");
        assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
        assert!(!state
            .session_store
            .list_workspaces("local-project")
            .expect("workspaces")
            .iter()
            .any(|workspace| workspace["name"] == "Receipt rollback task"));
        assert!(!state
            .session_store
            .list_conversations("local-project", None)
            .expect("conversations")
            .iter()
            .any(|conversation| conversation.title == "Receipt rollback task"));
        let connection = state.session_store.connection().expect("connection");
        let initial_message_count: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM desktop_workspace_messages
                 WHERE json_extract(value_json, '$.content') = ?1",
                ["Build the approved desktop task flow"],
                |row| row.get(0),
            )
            .expect("count rolled back initial messages");
        let receipt_count: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM desktop_new_task_sessions
                 WHERE idempotency_key = ?1",
                ["task-session-receipt-failure"],
                |row| row.get(0),
            )
            .expect("count rolled back receipts");
        assert_eq!(initial_message_count, 0);
        assert_eq!(receipt_count, 0);
    }

    #[test]
    fn client_turn_message_ids_are_scoped_to_the_conversation() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        for conversation_id in ["conversation-a", "conversation-b"] {
            store
                .insert_conversation(&LocalConversation {
                    id: conversation_id.to_string(),
                    project_id: "local-project".to_string(),
                    tenant_id: "local".to_string(),
                    title: conversation_id.to_string(),
                    workspace_id: Some("local-workspace".to_string()),
                    capability_mode: ConversationCapabilityMode::Unavailable,
                    current_mode: ConversationRunMode::Plan,
                    created_at: now_iso(),
                    updated_at: now_iso(),
                })
                .expect("insert conversation");
        }

        assert!(store
            .claim_client_turn(
                "conversation-a",
                "shared-message-id",
                "payload-a",
                &now_iso(),
            )
            .expect("claim first conversation"));
        assert!(store
            .claim_client_turn(
                "conversation-b",
                "shared-message-id",
                "payload-b",
                &now_iso(),
            )
            .expect("claim second conversation"));
    }

    #[tokio::test]
    async fn workspace_message_routes_require_full_path_and_active_workspace_scope() {
        let state = test_state("workspace-message-scope-secret");
        state
            .session_store
            .insert_workspace(&json!({
                "id": "foreign-tenant-workspace",
                "tenant_id": "foreign-tenant",
                "project_id": "local-project",
                "name": "Foreign tenant workspace",
            }))
            .expect("insert foreign tenant workspace");
        state
            .session_store
            .insert_workspace(&json!({
                "id": "foreign-project-workspace",
                "tenant_id": "local",
                "project_id": "foreign-project",
                "name": "Foreign project workspace",
            }))
            .expect("insert foreign project workspace");
        let app = local_router(Arc::clone(&state));

        let wrong_tenant_path = app
            .clone()
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/tenants/foreign-tenant/projects/local-project/workspaces/local-workspace/messages",
                "workspace-message-scope-secret",
                json!({}),
            ))
            .await
            .expect("wrong tenant path response");
        assert_eq!(wrong_tenant_path.status(), StatusCode::FORBIDDEN);

        let wrong_project_path = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/foreign-project/workspaces/local-workspace/messages",
                "workspace-message-scope-secret",
                json!({ "content": "must be rejected" }),
            ))
            .await
            .expect("wrong project path response");
        assert_eq!(wrong_project_path.status(), StatusCode::FORBIDDEN);

        let foreign_tenant_workspace = app
            .clone()
            .oneshot(authenticated_json_request(
                "GET",
                "/api/v1/tenants/local/projects/local-project/workspaces/foreign-tenant-workspace/messages",
                "workspace-message-scope-secret",
                json!({}),
            ))
            .await
            .expect("foreign tenant workspace response");
        assert_eq!(foreign_tenant_workspace.status(), StatusCode::FORBIDDEN);

        let foreign_project_workspace = app
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/workspaces/foreign-project-workspace/messages",
                "workspace-message-scope-secret",
                json!({ "content": "must not persist" }),
            ))
            .await
            .expect("foreign project workspace response");
        assert_eq!(foreign_project_workspace.status(), StatusCode::FORBIDDEN);
        assert!(state
            .session_store
            .list_workspace_messages("foreign-project-workspace")
            .expect("list rejected workspace messages")
            .is_empty());
    }

    #[tokio::test]
    async fn workspace_message_create_propagates_persistence_failure() {
        let state = test_state("workspace-message-store-secret");
        {
            let connection = state
                .session_store
                .connection()
                .expect("desktop session connection");
            connection
                .execute("DROP TABLE desktop_workspace_messages", [])
                .expect("drop workspace message table");
        }

        let response = local_router(state)
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/tenants/local/projects/local-project/workspaces/local-workspace/messages",
                "workspace-message-store-secret",
                json!({ "content": "cannot persist" }),
            ))
            .await
            .expect("workspace message persistence response");

        assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(
            response_json(response).await,
            json!({ "detail": "desktop session store unavailable" })
        );
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

    #[test]
    fn conversation_projection_separates_lifecycle_status_from_latest_run() {
        let state = test_state("conversation-status-contract-secret");
        let conversation = LocalConversation {
            id: "conversation-status-contract".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Separate lifecycle and execution status".to_string(),
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
                    "id": "conversation-status-task",
                    "conversation_id": conversation.id,
                    "content": "Verify the status contract",
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
                "local-project",
                "conversation-status-approval",
                "conversation-status-message",
                "Execute the reviewed plan",
                &now_iso(),
            )
            .expect("approve plan");

        let projected = state.conversation_value(&conversation);
        assert_eq!(projected["status"], "active");
        assert_eq!(projected["metadata"]["run"]["id"], approved.run.id);
        assert_eq!(projected["metadata"]["run"]["status"], "queued");
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
                        "/api/v1/agent/conversations/{}/session?tenant_id=local&project_id=local-project&workspace_id=local-workspace",
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
    async fn conversation_session_projection_requires_the_exact_query_scope() {
        let state = test_state("session-scope-secret");
        let conversation = LocalConversation {
            id: "conversation-session-scope".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Sensitive session title".to_string(),
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
        let app = local_router(state);

        let missing_scope = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{}/session",
                        conversation.id
                    ))
                    .header("authorization", "Bearer session-scope-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(missing_scope.status(), StatusCode::BAD_REQUEST);

        let mismatched_scopes = [
            "tenant_id=outside&project_id=local-project&workspace_id=local-workspace",
            "tenant_id=local&project_id=outside-project&workspace_id=local-workspace",
            "tenant_id=local&project_id=local-project&workspace_id=outside-workspace",
        ];
        for query in mismatched_scopes {
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .uri(format!(
                            "/api/v1/agent/conversations/{}/session?{query}",
                            conversation.id
                        ))
                        .header("authorization", "Bearer session-scope-secret")
                        .body(Body::empty())
                        .expect("request"),
                )
                .await
                .expect("response");
            assert_eq!(response.status(), StatusCode::FORBIDDEN);
            let payload = response_json(response).await;
            assert_eq!(
                payload["detail"],
                "resource is outside the active workspace context"
            );
            assert!(!payload.to_string().contains(&conversation.title));
        }
    }

    #[tokio::test]
    async fn conversation_session_projection_supports_standalone_scope() {
        let state = test_state("standalone-session-secret");
        let conversation = LocalConversation {
            id: "conversation-session-standalone".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Standalone session".to_string(),
            workspace_id: None,
            capability_mode: ConversationCapabilityMode::Work,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .expect("insert conversation");

        let response = local_router(state)
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{}/session?tenant_id=local&project_id=local-project",
                        conversation.id
                    ))
                    .header("authorization", "Bearer standalone-session-secret")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let snapshot = response_json(response).await;
        assert_eq!(snapshot["conversation"]["id"], conversation.id);
        assert_eq!(snapshot["conversation"]["workspace_id"], Value::Null);
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
        assert_eq!(
            my_work_capability_mode(ConversationCapabilityMode::Code),
            Some(ConversationCapabilityMode::Code)
        );
        assert_eq!(
            my_work_capability_mode(ConversationCapabilityMode::Unavailable),
            None
        );
    }

    #[tokio::test]
    async fn my_work_route_is_project_scoped_and_uses_run_status_without_text_inference() {
        let state = test_state("launch-secret");
        let seed = |conversation_id: &str,
                    project_id: &str,
                    capability_mode: ConversationCapabilityMode,
                    status: DesktopRunStatus|
         -> DesktopRun {
            let conversation = LocalConversation {
                id: conversation_id.to_string(),
                project_id: project_id.to_string(),
                tenant_id: "local".to_string(),
                title: format!("Attention item {conversation_id}"),
                workspace_id: Some(format!("workspace-{project_id}")),
                capability_mode,
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
            ConversationCapabilityMode::Unavailable,
            DesktopRunStatus::NeedsApproval,
        );
        seed(
            "conversation-project-b",
            "project-b",
            ConversationCapabilityMode::Code,
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
        assert_eq!(payload["items"][0]["authority_kind"], "desktop_run");
        assert_eq!(payload["items"][0]["authority_id"], expected.id);
        assert!(payload["items"][0]
            .as_object()
            .expect("my work item")
            .contains_key("attempt_number"));
        assert!(payload["items"][0]["attempt_number"].is_null());
        assert!(payload["items"][0]["capability_mode"].is_null());
        assert_eq!(payload["items"][0]["revision"], expected.revision);
        assert_eq!(
            payload["items"][0]["permission_profile"],
            serde_json::to_value(expected.permission_profile).expect("permission profile json")
        );
        assert_eq!(
            payload["items"][0]["environment"],
            serde_json::to_value(expected.environment).expect("environment json")
        );
        assert_eq!(
            payload["items"][0]["last_heartbeat_at"],
            serde_json::to_value(expected.last_heartbeat_at).expect("heartbeat json")
        );
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

    #[tokio::test]
    async fn conversation_mode_patch_distinguishes_missing_null_and_value_workspace_id() {
        let state = test_state("conversation-mode-patch-secret");
        let conversation = LocalConversation {
            id: "conversation-mode-patch".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Patch workspace linkage".to_string(),
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
        let app = local_router(Arc::clone(&state));

        let capability_only = app
            .clone()
            .oneshot(authenticated_json_request(
                "PATCH",
                "/api/v1/agent/conversations/conversation-mode-patch/mode",
                "conversation-mode-patch-secret",
                json!({ "capability_mode": "code" }),
            ))
            .await
            .expect("capability-only patch response");
        assert_eq!(capability_only.status(), StatusCode::OK);
        let capability_only_payload = response_json(capability_only).await;
        assert_eq!(capability_only_payload["workspace_id"], "local-workspace");
        assert_eq!(
            capability_only_payload["agent_config"]["capability_mode"],
            "code"
        );

        let clear_workspace = app
            .oneshot(authenticated_json_request(
                "PATCH",
                "/api/v1/agent/conversations/conversation-mode-patch/mode",
                "conversation-mode-patch-secret",
                json!({ "workspace_id": null }),
            ))
            .await
            .expect("clear workspace patch response");
        assert_eq!(clear_workspace.status(), StatusCode::OK);
        assert!(response_json(clear_workspace).await["workspace_id"].is_null());

        let stored = state
            .session_store
            .conversation("conversation-mode-patch")
            .expect("load patched conversation")
            .expect("patched conversation");
        assert_eq!(stored.capability_mode, ConversationCapabilityMode::Code);
        assert!(stored.workspace_id.is_none());
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
        assert_eq!(run.status, DesktopRunStatus::Interrupted);
        assert_eq!(run.revision, 2);
        assert_eq!(
            run.error.as_deref(),
            Some(authority_store::QUEUED_RUN_RECOVERY_ERROR)
        );
        assert_eq!(restored.run_events(&run_id).unwrap().len(), 2);
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
    fn reopening_marks_an_approved_unstarted_run_interrupted_exactly_once() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create test root");
        let path = root.join("queued-run-recovery.db");
        let conversation = LocalConversation {
            id: "conversation-queued-recovery".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Recover queued run".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        let queued = {
            let store = DesktopSessionStore::open(&path).expect("open store");
            store
                .insert_conversation(&conversation)
                .expect("insert conversation");
            store
                .replace_agent_plan_tasks(
                    &conversation.id,
                    &[json!({
                        "id": "queued-recovery-task",
                        "conversation_id": conversation.id,
                        "content": "Start this approved run after recovery",
                        "status": "pending",
                        "priority": "high",
                        "order_index": 0,
                        "created_at": now_iso(),
                        "updated_at": now_iso(),
                    })],
                )
                .expect("store plan");
            store
                .approve_plan_and_start(
                    &conversation.id,
                    "local-project",
                    "queued-recovery-key",
                    "queued-recovery-message",
                    "Execute the recovered approved plan",
                    &now_iso(),
                )
                .expect("approve plan")
                .run
        };
        assert_eq!(queued.status, DesktopRunStatus::Queued);
        assert_eq!(queued.revision, 1);
        assert!(queued.started_at.is_none());

        let restored = DesktopSessionStore::open(&path).expect("reopen store");
        let interrupted = restored.run(&queued.id).unwrap().expect("restored run");
        assert_eq!(interrupted.status, DesktopRunStatus::Interrupted);
        assert_eq!(interrupted.revision, 2);
        assert!(interrupted.started_at.is_none());
        assert_eq!(
            interrupted.error.as_deref(),
            Some(authority_store::QUEUED_RUN_RECOVERY_ERROR)
        );
        assert_eq!(
            restored
                .run_events(&queued.id)
                .expect("run events")
                .iter()
                .filter(|event| event["type"] == "interrupted")
                .count(),
            1
        );
        drop(restored);

        let reopened = DesktopSessionStore::open(&path).expect("reopen store again");
        let stable = reopened.run(&queued.id).unwrap().expect("stable run");
        assert_eq!(stable.status, DesktopRunStatus::Interrupted);
        assert_eq!(stable.revision, interrupted.revision);
        assert_eq!(
            reopened
                .run_events(&queued.id)
                .expect("run events")
                .iter()
                .filter(|event| event["type"] == "interrupted")
                .count(),
            1
        );
        drop(reopened);
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

        store
            .bind_checkpoint_authority(&disconnected, &now_iso())
            .expect("bind source checkpoint authority");
        store
            .transfer_checkpoint_authority(&disconnected, &forked, &now_iso())
            .expect("transfer checkpoint authority");
        assert!(store
            .rollback_recovery_fork(&disconnected, &forked, &now_iso())
            .expect("roll back recovery fork"));
        assert!(store
            .run(&forked.id)
            .expect("load rolled back fork")
            .is_none());
        assert!(store
            .run_events(&forked.id)
            .expect("load rolled back fork events")
            .is_empty());
        let decision_count: i64 = store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_decisions WHERE run_id = ?1",
                [&forked.id],
                |row| row.get(0),
            )
            .expect("count rolled back decisions");
        assert_eq!(decision_count, 0);
        assert!(store
            .checkpoint_authority(&conversation.id)
            .expect("load restored checkpoint authority")
            .is_some_and(|authority| authority.matches_run(&disconnected)));

        let (recreated, created) = store
            .fork_recovery_run(
                &disconnected.id,
                disconnected.revision,
                "fork-recovery-key",
                authority_store::DesktopExecutionEnvironment {
                    id: "recreated-environment".to_string(),
                    kind: DesktopExecutionEnvironmentKind::Worktree,
                    label: "Recreated".to_string(),
                    workspace_path: "/tmp/recreated".to_string(),
                    repository_root: None,
                    branch: None,
                    base_commit: None,
                    source_run_id: Some(disconnected.id.clone()),
                    created_at: now_iso(),
                },
                &now_iso(),
            )
            .expect("recreate rolled back recovery fork");
        assert!(created);
        assert_ne!(recreated.id, forked.id);
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
                        "/api/v1/agent/conversations/{}/messages?project_id=local-project",
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
            .session_store
            .bind_checkpoint_authority(&running, &now_iso())
            .expect("bind HITL checkpoint authority");
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
                        "/api/v1/agent/conversations/{}/messages?project_id=local-project",
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

    fn seed_queued_authoritative_run(
        state: &Arc<LocalRuntimeState>,
        suffix: &str,
    ) -> (LocalConversation, DesktopRun) {
        let conversation = LocalConversation {
            id: format!("conversation-queued-{suffix}"),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Queued authoritative run".to_string(),
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
                    "id": format!("queued-task-{suffix}"),
                    "conversation_id": conversation.id,
                    "content": "Execute once after recovery",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let queued = state
            .session_store
            .approve_plan_and_start(
                &conversation.id,
                "local-project",
                &format!("queued-key-{suffix}"),
                &format!("queued-message-{suffix}"),
                "Execute the recovered plan once",
                &now_iso(),
            )
            .expect("approve plan")
            .run;
        (conversation, queued)
    }

    async fn seed_transferred_recovery_fork(
        state: &Arc<LocalRuntimeState>,
        suffix: &str,
    ) -> (LocalConversation, DesktopRun, DesktopRun) {
        let (conversation, queued_source) = seed_queued_authoritative_run(state, suffix);
        let running_source = state
            .prepare_authoritative_run_for_execution(
                &queued_source.id,
                &conversation.id,
                &conversation.project_id,
                &queued_source.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare recovery source")
            .expect("running recovery source");
        let disconnected_source = state
            .session_store
            .transition_run(
                &running_source.id,
                running_source.revision,
                DesktopRunStatus::Disconnected,
                None,
                &now_iso(),
            )
            .expect("disconnect recovery source");
        let (forked, created) = state
            .session_store
            .fork_recovery_run(
                &disconnected_source.id,
                disconnected_source.revision,
                &format!("transferred-fork-key-{suffix}"),
                DesktopExecutionEnvironment {
                    id: format!("transferred-fork-environment-{suffix}"),
                    kind: DesktopExecutionEnvironmentKind::Worktree,
                    label: format!("Transferred recovery fork {suffix}"),
                    workspace_path: format!("/tmp/agistack-transferred-fork-{suffix}"),
                    repository_root: None,
                    branch: Some(format!("agistack/transferred-fork-{suffix}")),
                    base_commit: None,
                    source_run_id: Some(disconnected_source.id.clone()),
                    created_at: now_iso(),
                },
                &now_iso(),
            )
            .expect("create recovery fork");
        assert!(created);
        state
            .session_store
            .transfer_checkpoint_authority(&disconnected_source, &forked, &now_iso())
            .expect("transfer checkpoint authority");
        assert!(state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load transferred checkpoint authority")
            .is_some_and(|authority| authority.matches_run(&forked)));
        (conversation, disconnected_source, forked)
    }

    async fn seed_transferred_unstarted_recovery_fork(
        state: &Arc<LocalRuntimeState>,
        suffix: &str,
    ) -> (LocalConversation, DesktopRun, DesktopRun) {
        let (conversation, queued_source) = seed_queued_authoritative_run(state, suffix);
        assert!(state
            .ensure_authoritative_launch_checkpoint(&queued_source)
            .await
            .expect("seed unstarted recovery checkpoint"));
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover queued source");
        }
        let interrupted_source = state
            .session_store
            .run(&queued_source.id)
            .expect("load interrupted source")
            .expect("interrupted source");
        assert!(authority_store::is_recovered_unstarted_run(
            &interrupted_source
        ));
        let (forked, created) = state
            .session_store
            .fork_recovery_run(
                &interrupted_source.id,
                interrupted_source.revision,
                &format!("transferred-unstarted-fork-key-{suffix}"),
                DesktopExecutionEnvironment {
                    id: format!("transferred-unstarted-fork-environment-{suffix}"),
                    kind: DesktopExecutionEnvironmentKind::Worktree,
                    label: format!("Transferred unstarted recovery fork {suffix}"),
                    workspace_path: format!("/tmp/agistack-transferred-unstarted-fork-{suffix}"),
                    repository_root: None,
                    branch: Some(format!("agistack/transferred-unstarted-fork-{suffix}")),
                    base_commit: None,
                    source_run_id: Some(interrupted_source.id.clone()),
                    created_at: now_iso(),
                },
                &now_iso(),
            )
            .expect("create unstarted recovery fork");
        assert!(created);
        state
            .session_store
            .transfer_checkpoint_authority(&interrupted_source, &forked, &now_iso())
            .expect("transfer unstarted checkpoint authority");
        (conversation, interrupted_source, forked)
    }

    async fn assert_transferred_source_controls_stop_before_core(
        state: &Arc<LocalRuntimeState>,
        checkpoints: &CountingCheckpointStore,
        conversation: &LocalConversation,
        source: &DesktopRun,
        forked: &DesktopRun,
    ) {
        let checkpoint_before = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load fork checkpoint")
            .expect("fork checkpoint");
        let authority_before = state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load fork checkpoint authority")
            .expect("fork checkpoint authority");
        assert!(authority_before.matches_run(forked));
        let source_events_before = state
            .session_store
            .run_events(&source.id)
            .expect("load source events")
            .len();
        let fork_events_before = state
            .session_store
            .run_events(&forked.id)
            .expect("load fork events")
            .len();
        let timeline_before = state
            .session_store
            .timeline(&conversation.id, 100)
            .expect("load timeline")
            .len();
        let event_counter_before = state.event_counter.load(Ordering::SeqCst);
        checkpoints.reset();
        state.agent_run_claim_attempts.store(0, Ordering::SeqCst);
        state.agent_engine_attempts.store(0, Ordering::SeqCst);

        for action in ["pause", "resume", "cancel"] {
            let response = local_router(Arc::clone(state))
                .oneshot(
                    Request::builder()
                        .method("POST")
                        .uri(format!("/api/v1/agent/runs/{}/{action}", source.id))
                        .header("authorization", "Bearer launch-secret")
                        .header("content-type", "application/json")
                        .body(Body::from(format!(
                            r#"{{"expected_revision":{}}}"#,
                            source.revision
                        )))
                        .expect("request"),
                )
                .await
                .expect("response");
            assert_eq!(response.status(), StatusCode::CONFLICT, "{action}");
            assert_eq!(
                response_json(response).await["detail"],
                CHECKPOINT_CONTROL_AUTHORITY_ERROR,
                "{action}"
            );
        }

        assert_eq!(
            checkpoints.operation_counts(),
            CheckpointOperationCounts {
                loads: 0,
                saves: 0,
                deletes: 0,
            }
        );
        assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 0);
        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 0);
        assert_eq!(
            state.event_counter.load(Ordering::SeqCst),
            event_counter_before
        );
        assert!(state
            .agent_runs
            .lock()
            .expect("local agent runs")
            .is_empty());
        assert_eq!(
            state
                .session_store
                .run_events(&source.id)
                .expect("reload source events")
                .len(),
            source_events_before
        );
        assert_eq!(
            state
                .session_store
                .run_events(&forked.id)
                .expect("reload fork events")
                .len(),
            fork_events_before
        );
        assert_eq!(
            state
                .session_store
                .timeline(&conversation.id, 100)
                .expect("reload timeline")
                .len(),
            timeline_before
        );
        let stored_source = state
            .session_store
            .run(&source.id)
            .expect("load source")
            .expect("source");
        assert_eq!(stored_source.status, source.status);
        assert_eq!(stored_source.revision, source.revision);
        assert_eq!(stored_source.error, source.error);
        let stored_fork = state
            .session_store
            .run(&forked.id)
            .expect("load fork")
            .expect("fork");
        assert_eq!(stored_fork.status, forked.status);
        assert_eq!(stored_fork.revision, forked.revision);
        assert_eq!(stored_fork.error, forked.error);
        assert_eq!(
            state
                .session_store
                .checkpoint_authority(&conversation.id)
                .expect("reload fork checkpoint authority")
                .expect("fork checkpoint authority"),
            authority_before
        );
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("reload fork checkpoint")
                .expect("fork checkpoint"),
            checkpoint_before
        );
    }

    fn queue_next_input(
        state: &Arc<LocalRuntimeState>,
        run: &DesktopRun,
        suffix: &str,
    ) -> steering::DesktopRunInput {
        state
            .session_store
            .create_run_input(session_store::CreateRunInput {
                run_id: &run.id,
                expected_run_revision: run.revision,
                message_id: &format!("queue-message-{suffix}"),
                idempotency_key: &format!("queue-key-{suffix}"),
                delivery: RunInputDelivery::QueueNext,
                content: "Run this after the authoritative execution settles",
                references: Vec::new(),
                now: &now_iso(),
            })
            .expect("queue next input")
            .0
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
        state
            .session_store
            .bind_checkpoint_authority(&paused, &now_iso())
            .expect("bind paused checkpoint authority");

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
        state
            .checkpoints
            .save(&SessionState::new(
                conversation.id.clone(),
                running.request_message.clone(),
                Some(running.project_id.as_str()),
            ))
            .await
            .expect("save running checkpoint");
        state
            .session_store
            .bind_checkpoint_authority(&running, &now_iso())
            .expect("bind running checkpoint authority");
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

        state
            .session_store
            .bind_checkpoint_authority(&paused, &now_iso())
            .expect("bind resume checkpoint authority");
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
    async fn reconnect_starts_a_recovered_unstarted_run_once_with_the_original_authority() {
        let state = test_state("launch-secret");
        let (conversation, queued) = seed_queued_authoritative_run(&state, "reconnect");
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover queued run");
        }
        let interrupted = state
            .session_store
            .run(&queued.id)
            .expect("load run")
            .expect("recovered run");
        assert_eq!(interrupted.status, DesktopRunStatus::Interrupted);
        assert!(interrupted.started_at.is_none());

        let recovery_projection = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/agent/conversations/{}/session?tenant_id=local&project_id=local-project&workspace_id=local-workspace",
                        conversation.id
                    ))
                    .header("authorization", "Bearer launch-secret")
                    .body(Body::empty())
                    .expect("projection request"),
            )
            .await
            .expect("projection response");
        assert_eq!(recovery_projection.status(), StatusCode::OK);
        let recovery_projection = response_json(recovery_projection).await;
        assert_eq!(
            recovery_projection["capabilities"]["run_actions"],
            json!(["reconnect", "fork", "cancel"])
        );
        assert!(recovery_projection["capabilities"]["allowed_actions"]
            .as_array()
            .is_some_and(|actions| actions.iter().any(|action| action == "reconnect")));

        let held_control = state
            .claim_agent_run(&conversation.id, Some(&interrupted.id))
            .expect("hold conversation execution claim");
        Arc::clone(&state)
            .run_agent_message(
                conversation.id.clone(),
                conversation.project_id.clone(),
                interrupted.request_message.clone(),
                interrupted.message_id.clone(),
                Some(interrupted.id.clone()),
                None,
            )
            .await;
        let still_interrupted = state
            .session_store
            .run(&interrupted.id)
            .expect("load run after rejected concurrent start")
            .expect("run after rejected concurrent start");
        assert_eq!(still_interrupted.status, DesktopRunStatus::Interrupted);
        assert_eq!(still_interrupted.revision, interrupted.revision);
        assert!(Arc::ptr_eq(
            &held_control,
            &state
                .control_for_run(&interrupted)
                .expect("original control remains attached")
        ));
        state.release_agent_run(&conversation.id);

        let app = local_router(Arc::clone(&state));
        let first = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/resume", interrupted.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        interrupted.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(first.status(), StatusCode::OK);
        let payload = response_json(first).await;
        assert_eq!(payload["accepted"], true);
        assert_eq!(payload["status"], "restart_requested");
        assert_eq!(payload["run"]["id"], interrupted.id);

        let replay = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/resume", interrupted.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        interrupted.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(replay.status(), StatusCode::CONFLICT);

        let mut final_run = None;
        for _ in 0..100 {
            let run = state
                .session_store
                .run(&interrupted.id)
                .expect("load run")
                .expect("run");
            if run.status == DesktopRunStatus::ReadyReview {
                final_run = Some(run);
                break;
            }
            tokio::task::yield_now().await;
        }
        let completed = final_run.expect("restarted run reaches review");
        assert_eq!(completed.id, interrupted.id);
        assert_eq!(completed.plan_version_id, interrupted.plan_version_id);
        assert_eq!(completed.idempotency_key, interrupted.idempotency_key);
        let run_events = state
            .session_store
            .run_events(&interrupted.id)
            .expect("run events");
        let restarted = run_events
            .iter()
            .find(|event| event["type"] == "running")
            .expect("running event after reconnect");
        assert!(restarted["error"].is_null());
        assert_eq!(
            state
                .session_store
                .timeline(&conversation.id, 100)
                .expect("timeline")
                .iter()
                .filter(|item| {
                    item["type"] == "user_message" && item["message_id"] == interrupted.message_id
                })
                .count(),
            1
        );
    }

    #[tokio::test]
    async fn recovered_unstarted_run_cancels_without_a_core_checkpoint() {
        let state = test_state("launch-secret");
        let (conversation, queued) = seed_queued_authoritative_run(&state, "cancel");
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover queued run");
        }
        let interrupted = state
            .session_store
            .run(&queued.id)
            .expect("load run")
            .expect("recovered run");
        assert_eq!(interrupted.status, DesktopRunStatus::Interrupted);
        assert!(state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint")
            .is_none());

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/cancel", interrupted.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        interrupted.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let payload = response_json(response).await;
        assert_eq!(payload["status"], "cancelled");
        assert_eq!(payload["run"]["id"], interrupted.id);
        assert_eq!(payload["run"]["status"], "cancelled");
        assert_eq!(payload["run"]["revision"], interrupted.revision + 1);
        assert!(payload["run"]["error"].is_null());
        let checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint")
            .expect("cancel checkpoint was seeded before the desktop commit");
        assert_eq!(checkpoint.status, SessionStatus::Cancelled);
        assert_eq!(checkpoint.goal, interrupted.request_message);
    }

    #[tokio::test]
    async fn recovered_unstarted_run_cancels_a_seeded_launch_checkpoint() {
        let state = test_state("launch-secret");
        let (conversation, queued) = seed_queued_authoritative_run(&state, "cancel-seeded");
        assert!(state
            .ensure_authoritative_launch_checkpoint(&queued)
            .await
            .expect("seed launch checkpoint"));
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover queued run");
        }
        let interrupted = state
            .session_store
            .run(&queued.id)
            .expect("load run")
            .expect("recovered run");
        assert_eq!(interrupted.status, DesktopRunStatus::Interrupted);

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/cancel", interrupted.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        interrupted.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let payload = response_json(response).await;
        assert_eq!(payload["run"]["status"], "cancelled");
        let checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint")
            .expect("cancelled checkpoint");
        assert_eq!(checkpoint.status, SessionStatus::Cancelled);
        assert_eq!(checkpoint.goal, interrupted.request_message);
    }

    #[tokio::test]
    async fn environment_validation_failure_terminalizes_the_seeded_launch_checkpoint() {
        let state = test_state("launch-secret");
        let conversation = LocalConversation {
            id: "conversation-invalid-launch-environment".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Invalid launch environment".to_string(),
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
                    "id": "invalid-launch-environment-task",
                    "conversation_id": conversation.id,
                    "content": "Validate the launch environment",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("store plan");
        let plan = state
            .session_store
            .latest_draft_plan(&conversation.id)
            .expect("load plan")
            .expect("plan");
        let queued = state
            .session_store
            .approve_plan_and_start_in_environment(session_store::ApprovePlanStartInput {
                conversation_id: &conversation.id,
                project_id: "local-project",
                plan_version_id: &plan.id,
                expected_plan_version: plan.version,
                idempotency_key: "invalid-launch-environment-key",
                message_id: "invalid-launch-environment-message",
                request_message: "Execute with an invalid environment",
                environment: Some(authority_store::DesktopExecutionEnvironment {
                    id: "invalid-launch-environment".to_string(),
                    kind: DesktopExecutionEnvironmentKind::Local,
                    label: "Missing local workspace".to_string(),
                    workspace_path: test_root().join("missing").to_string_lossy().into_owned(),
                    repository_root: None,
                    branch: None,
                    base_commit: None,
                    source_run_id: None,
                    created_at: now_iso(),
                }),
                requested_environment_kind: DesktopExecutionEnvironmentKind::Local,
                permission_profile: DesktopPermissionProfile::WorkspaceWrite,
                now: &now_iso(),
            })
            .expect("approve run")
            .run;

        Arc::clone(&state)
            .run_agent_message(
                conversation.id.clone(),
                conversation.project_id.clone(),
                queued.request_message.clone(),
                queued.message_id.clone(),
                Some(queued.id.clone()),
                None,
            )
            .await;

        let failed = state
            .session_store
            .run(&queued.id)
            .expect("load run")
            .expect("failed run");
        assert_eq!(failed.status, DesktopRunStatus::Failed);
        let checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint")
            .expect("failed checkpoint");
        assert_eq!(checkpoint.status, SessionStatus::Failed);
        assert_eq!(checkpoint.goal, queued.request_message);
    }

    #[tokio::test]
    async fn preclaimed_control_is_released_when_agent_message_fails_authority_preflight() {
        let state = test_state("launch-secret");
        let missing_conversation_id = "missing-preclaimed-conversation";
        let missing_control = state
            .claim_agent_run(missing_conversation_id, Some("missing-run"))
            .expect("claim missing conversation");
        Arc::clone(&state)
            .run_agent_message(
                missing_conversation_id.to_string(),
                "local-project".to_string(),
                "Execute".to_string(),
                "missing-message".to_string(),
                Some("missing-run".to_string()),
                Some(missing_control),
            )
            .await;
        let reclaimed = state
            .claim_agent_run(missing_conversation_id, Some("missing-run"))
            .expect("missing conversation claim was released");
        state.release_agent_run_if_control(missing_conversation_id, &reclaimed);

        let conversation = LocalConversation {
            id: "conversation-preflight-project-mismatch".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Project mismatch".to_string(),
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
        let mismatched_control = state
            .claim_agent_run(&conversation.id, None)
            .expect("claim mismatched conversation");
        Arc::clone(&state)
            .run_agent_message(
                conversation.id.clone(),
                "another-project".to_string(),
                "Execute".to_string(),
                "mismatched-message".to_string(),
                None,
                Some(mismatched_control),
            )
            .await;
        let reclaimed = state
            .claim_agent_run(&conversation.id, None)
            .expect("project mismatch claim was released");
        state.release_agent_run_if_control(&conversation.id, &reclaimed);
    }

    #[tokio::test]
    async fn disconnect_after_running_commit_reconnects_from_seeded_launch_checkpoint() {
        let state = test_state("launch-secret");
        let (conversation, queued) = seed_queued_authoritative_run(&state, "launch-checkpoint");
        let running = state
            .prepare_authoritative_run_for_execution(
                &queued.id,
                &conversation.id,
                &conversation.project_id,
                &queued.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare authoritative run")
            .expect("running run");
        assert_eq!(running.status, DesktopRunStatus::Running);
        let initial_checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load launch checkpoint")
            .expect("launch checkpoint");
        assert_eq!(initial_checkpoint.status, SessionStatus::Running);
        assert_eq!(initial_checkpoint.round, 0);
        assert_eq!(initial_checkpoint.goal, queued.request_message);

        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover running launch");
        }
        let disconnected = state
            .session_store
            .run(&running.id)
            .expect("load disconnected run")
            .expect("disconnected run");
        assert_eq!(disconnected.status, DesktopRunStatus::Disconnected);

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/resume", disconnected.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        disconnected.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let payload = response_json(response).await;
        assert_eq!(payload["run"]["id"], disconnected.id);
        assert_eq!(payload["run"]["status"], "running");

        let mut final_run = None;
        for _ in 0..100 {
            let run = state
                .session_store
                .run(&disconnected.id)
                .expect("load run")
                .expect("run");
            if run.status == DesktopRunStatus::ReadyReview {
                final_run = Some(run);
                break;
            }
            tokio::task::yield_now().await;
        }
        assert_eq!(
            final_run.expect("reconnected launch reaches review").id,
            disconnected.id
        );
    }

    #[tokio::test]
    async fn startup_reconciles_terminal_core_checkpoints_into_desktop_runs() {
        let state = test_state("launch-secret");
        let cases = [
            (
                "terminal-failed",
                SessionStatus::Failed,
                DesktopRunStatus::Failed,
            ),
            (
                "terminal-finished",
                SessionStatus::Finished,
                DesktopRunStatus::ReadyReview,
            ),
            (
                "terminal-cancelled",
                SessionStatus::Cancelled,
                DesktopRunStatus::Cancelled,
            ),
        ];
        let mut runs = Vec::with_capacity(cases.len());
        for (suffix, checkpoint_status, expected_status) in cases {
            let (conversation, queued) = seed_queued_authoritative_run(&state, suffix);
            let running = state
                .prepare_authoritative_run_for_execution(
                    &queued.id,
                    &conversation.id,
                    &conversation.project_id,
                    &queued.request_message,
                    &now_iso(),
                )
                .await
                .expect("prepare authoritative run")
                .expect("running run");
            let mut checkpoint = state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("load checkpoint")
                .expect("launch checkpoint");
            checkpoint.status = checkpoint_status;
            checkpoint.answer = (checkpoint_status == SessionStatus::Failed)
                .then(|| "checkpoint failed before desktop settlement".to_string());
            state
                .checkpoints
                .save(&checkpoint)
                .await
                .expect("save terminal checkpoint");
            runs.push((running, expected_status));
        }
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover running records");
        }
        for (run, _) in &runs {
            assert_eq!(
                state
                    .session_store
                    .run(&run.id)
                    .expect("load disconnected run")
                    .expect("disconnected run")
                    .status,
                DesktopRunStatus::Disconnected
            );
        }

        state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect("reconcile recovered runs");

        for (run, expected_status) in runs {
            let reconciled = state
                .session_store
                .run(&run.id)
                .expect("load reconciled run")
                .expect("reconciled run");
            assert_eq!(reconciled.status, expected_status);
            assert_eq!(reconciled.revision, run.revision + 2);
            if expected_status == DesktopRunStatus::Failed {
                assert_eq!(
                    reconciled.error.as_deref(),
                    Some("checkpoint failed before desktop settlement")
                );
            }
        }
    }

    #[tokio::test]
    async fn startup_reconciles_only_the_current_recovery_fork() {
        let state = test_state("launch-secret");
        let (conversation, queued_source) =
            seed_queued_authoritative_run(&state, "current-recovery-fork");
        let running_source = state
            .prepare_authoritative_run_for_execution(
                &queued_source.id,
                &conversation.id,
                &conversation.project_id,
                &queued_source.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare source run")
            .expect("running source run");
        let disconnected_source = state
            .session_store
            .transition_run(
                &running_source.id,
                running_source.revision,
                DesktopRunStatus::Disconnected,
                None,
                &now_iso(),
            )
            .expect("disconnect source run");
        let (queued_fork, created) = state
            .session_store
            .fork_recovery_run(
                &disconnected_source.id,
                disconnected_source.revision,
                "current-recovery-fork-key",
                authority_store::DesktopExecutionEnvironment {
                    id: "current-recovery-fork-environment".to_string(),
                    kind: DesktopExecutionEnvironmentKind::Worktree,
                    label: "Current recovery fork".to_string(),
                    workspace_path: "/tmp/agistack-current-recovery-fork".to_string(),
                    repository_root: Some("/tmp/agistack-current-recovery-source".to_string()),
                    branch: Some("agistack/current-recovery-fork".to_string()),
                    base_commit: Some("current-recovery-base".to_string()),
                    source_run_id: Some(disconnected_source.id.clone()),
                    created_at: now_iso(),
                },
                &now_iso(),
            )
            .expect("fork recovery run");
        assert!(created);
        state
            .session_store
            .transfer_checkpoint_authority(&disconnected_source, &queued_fork, &now_iso())
            .expect("transfer checkpoint authority to recovery fork");
        let running_fork = state
            .prepare_authoritative_run_for_execution(
                &queued_fork.id,
                &conversation.id,
                &conversation.project_id,
                &queued_fork.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare recovery fork")
            .expect("running recovery fork");
        let mut checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load recovery checkpoint")
            .expect("recovery checkpoint");
        checkpoint.status = SessionStatus::Finished;
        checkpoint.answer = Some("recovery fork completed".to_string());
        state
            .checkpoints
            .save(&checkpoint)
            .await
            .expect("save finished recovery checkpoint");
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover running fork");
        }

        state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect("reconcile current recovery fork");

        let stored_source = state
            .session_store
            .run(&disconnected_source.id)
            .expect("load source run")
            .expect("source run");
        assert_eq!(stored_source.status, DesktopRunStatus::Disconnected);
        assert_eq!(stored_source.revision, disconnected_source.revision);
        let stored_fork = state
            .session_store
            .run(&running_fork.id)
            .expect("load recovery fork")
            .expect("recovery fork");
        assert_eq!(stored_fork.status, DesktopRunStatus::ReadyReview);
        assert_eq!(stored_fork.revision, running_fork.revision + 2);
    }

    #[tokio::test]
    async fn startup_quarantines_checkpoint_authority_mismatch_before_reconnect() {
        let state = test_state("launch-secret");
        let (conversation, queued) =
            seed_queued_authoritative_run(&state, "checkpoint-authority-mismatch");
        let running = state
            .prepare_authoritative_run_for_execution(
                &queued.id,
                &conversation.id,
                &conversation.project_id,
                &queued.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare authoritative run")
            .expect("running authoritative run");
        let mut mismatched_checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load launch checkpoint")
            .expect("launch checkpoint");
        mismatched_checkpoint.goal = "execute an unrelated stale checkpoint".to_string();
        state
            .checkpoints
            .save(&mismatched_checkpoint)
            .await
            .expect("save mismatched checkpoint");
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover running record");
        }

        state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect("quarantine mismatched checkpoint");

        let failed = state
            .session_store
            .run(&running.id)
            .expect("load quarantined run")
            .expect("quarantined run");
        assert_eq!(failed.status, DesktopRunStatus::Failed);
        assert_eq!(
            failed.error.as_deref(),
            Some("recovered checkpoint authority does not match the current run")
        );
        assert!(state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load quarantined checkpoint")
            .is_none());

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/resume", failed.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        failed.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::CONFLICT);
    }

    #[tokio::test]
    async fn startup_retries_checkpoint_cleanup_after_quarantine_commit() {
        let state = test_state("launch-secret");
        let (conversation, queued) =
            seed_queued_authoritative_run(&state, "checkpoint-quarantine-retry");
        let running = state
            .prepare_authoritative_run_for_execution(
                &queued.id,
                &conversation.id,
                &conversation.project_id,
                &queued.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare authoritative run")
            .expect("running authoritative run");
        let mut mismatched_checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load launch checkpoint")
            .expect("launch checkpoint");
        mismatched_checkpoint.project_id = Some("unrelated-project".to_string());
        state
            .checkpoints
            .save(&mismatched_checkpoint)
            .await
            .expect("save mismatched checkpoint");
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover running record");
        }
        let disconnected = state
            .session_store
            .run(&running.id)
            .expect("load recovered run")
            .expect("recovered run");
        let quarantined = state
            .session_store
            .reconcile_recovered_run(
                &disconnected.id,
                disconnected.revision,
                DesktopRunStatus::Failed,
                Some(RECOVERED_CHECKPOINT_AUTHORITY_ERROR.to_string()),
                &now_iso(),
            )
            .expect("commit quarantine before simulated crash");
        assert!(state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint before retry")
            .is_some());

        state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect("retry checkpoint quarantine cleanup");

        assert!(state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint after retry")
            .is_none());
        let stored = state
            .session_store
            .run(&quarantined.id)
            .expect("load quarantined run")
            .expect("quarantined run");
        assert_eq!(stored.status, DesktopRunStatus::Failed);
        assert_eq!(stored.revision, quarantined.revision);
        assert_eq!(stored.error, quarantined.error);
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
        state
            .session_store
            .bind_checkpoint_authority(&ready, &now_iso())
            .expect("bind review checkpoint authority");

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
        let key = ProviderRuntimeKey {
            tenant_id: "local".to_string(),
            provider_id: "provider-a".to_string(),
        };
        {
            let mut runtime = state.provider_runtime.lock().expect("provider runtime");
            runtime.bindings.insert(
                key.clone(),
                ProviderRuntimeBinding {
                    provider_type: "openai".to_string(),
                    base_url: "https://secret-endpoint.example.test/v1".to_string(),
                    model: "model-a".to_string(),
                    auth_method: "api_key".to_string(),
                },
            );
            runtime.credentials.insert(key, "llm-secret".to_string());
            runtime
                .selections
                .insert("local".to_string(), "provider-a".to_string());
        }
        let service = LocalRuntimeService {
            state,
            api_base_url: "http://127.0.0.1:1".to_string(),
        };
        let status = service.status();
        assert_eq!(status.api_token, first);
        assert_eq!(status.runtime_providers.len(), 1);
        assert!(status.runtime_providers[0].credential_configured);
        assert!(!status
            .tools
            .iter()
            .any(|name| name.starts_with("mcp_server_")));
        assert!(!status.tools.iter().any(|name| name == "plugin_tool_exec"));
        let serialized = serde_json::to_value(status).expect("serialized status");
        assert!(serialized["config"].get("api_key").is_none());
        assert!(!serialized.to_string().contains("llm-secret"));
        assert!(!serialized.to_string().contains("secret-endpoint"));
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
        assert!(LocalRuntimeConfig::default().workspace_root.is_empty());
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

    #[test]
    fn desktop_session_store_rejects_a_second_same_file_owner() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create store root");
        let path = root.join("exclusive-sessions.db");
        let first = DesktopSessionStore::open(&path).expect("first store owner");

        let error = match DesktopSessionStore::open(&path) {
            Ok(_) => panic!("a second store owner must not open the same authority database"),
            Err(error) => error,
        };
        assert!(error.contains("already owned"), "unexpected error: {error}");

        drop(first);
        let reopened = DesktopSessionStore::open(&path).expect("ownership released on drop");
        drop(reopened);
        std::fs::remove_dir_all(root).expect("remove store root");
    }

    #[test]
    fn terminal_run_transition_and_queued_input_settlement_are_atomic() {
        let state = test_state("launch-secret");
        let (_conversation, running) = seed_controlled_run(&state, "atomic-transition");
        let input = queue_next_input(&state, &running, "atomic-transition");
        {
            let connection = state.session_store.connection().expect("connection");
            connection
                .execute_batch(
                    "CREATE TEMP TRIGGER fail_terminal_input_settlement
                     BEFORE UPDATE OF status ON desktop_run_inputs
                     WHEN NEW.status = 'blocked'
                     BEGIN
                       SELECT RAISE(ABORT, 'forced queued input settlement failure');
                     END;",
                )
                .expect("install settlement failure");
        }

        let error = state
            .session_store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::Failed,
                Some("forced run failure".to_string()),
                &now_iso(),
            )
            .expect_err("terminal transaction must roll back when input settlement fails");
        assert!(error.contains("forced queued input settlement failure"));
        let unchanged = state
            .session_store
            .run(&running.id)
            .expect("load run")
            .expect("run");
        assert_eq!(unchanged.status, DesktopRunStatus::Running);
        assert_eq!(unchanged.revision, running.revision);
        assert_eq!(
            state
                .session_store
                .run_input(&input.id)
                .expect("load queued input")
                .expect("queued input")
                .status,
            RunInputStatus::Queued
        );
        assert!(!state
            .session_store
            .run_events(&running.id)
            .expect("run events")
            .iter()
            .any(|event| event["type"] == "failed"));

        {
            let connection = state.session_store.connection().expect("connection");
            connection
                .execute_batch("DROP TRIGGER fail_terminal_input_settlement;")
                .expect("remove settlement failure");
        }
        let failed = state
            .session_store
            .transition_run(
                &running.id,
                running.revision,
                DesktopRunStatus::Failed,
                Some("forced run failure".to_string()),
                &now_iso(),
            )
            .expect("terminal transaction");
        assert_eq!(failed.status, DesktopRunStatus::Failed);
        assert_eq!(
            state
                .session_store
                .run_input(&input.id)
                .expect("load settled input")
                .expect("settled input")
                .status,
            RunInputStatus::Blocked
        );
    }

    #[tokio::test]
    async fn startup_reconcile_rolls_back_run_when_input_settlement_fails() {
        let state = test_state("launch-secret");
        let (conversation, queued) = seed_queued_authoritative_run(&state, "atomic-reconcile");
        let running = state
            .prepare_authoritative_run_for_execution(
                &queued.id,
                &conversation.id,
                &conversation.project_id,
                &queued.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare run")
            .expect("running run");
        let input = queue_next_input(&state, &running, "atomic-reconcile");
        let mut checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint")
            .expect("checkpoint");
        checkpoint.status = SessionStatus::Failed;
        checkpoint.answer = Some("checkpoint failed".to_string());
        state
            .checkpoints
            .save(&checkpoint)
            .await
            .expect("save failed checkpoint");
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover running run");
            connection
                .execute_batch(
                    "CREATE TEMP TRIGGER fail_recovered_input_settlement
                     BEFORE UPDATE OF status ON desktop_run_inputs
                     WHEN NEW.status = 'blocked'
                     BEGIN
                       SELECT RAISE(ABORT, 'forced recovered input settlement failure');
                     END;",
                )
                .expect("install recovered settlement failure");
        }
        let disconnected = state
            .session_store
            .run(&running.id)
            .expect("load disconnected run")
            .expect("disconnected run");

        let error = state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect_err("reconciliation must roll back as one transaction");
        assert!(error.contains("forced recovered input settlement failure"));
        let unchanged = state
            .session_store
            .run(&running.id)
            .expect("load unchanged run")
            .expect("unchanged run");
        assert_eq!(unchanged.status, DesktopRunStatus::Disconnected);
        assert_eq!(unchanged.revision, disconnected.revision);
        assert_eq!(
            state
                .session_store
                .run_input(&input.id)
                .expect("load unchanged input")
                .expect("unchanged input")
                .status,
            RunInputStatus::Queued
        );

        {
            let connection = state.session_store.connection().expect("connection");
            connection
                .execute_batch("DROP TRIGGER fail_recovered_input_settlement;")
                .expect("remove recovered settlement failure");
        }
        state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect("retry reconciliation");
        assert_eq!(
            state
                .session_store
                .run(&running.id)
                .expect("load reconciled run")
                .expect("reconciled run")
                .status,
            DesktopRunStatus::Failed
        );
        assert_eq!(
            state
                .session_store
                .run_input(&input.id)
                .expect("load reconciled input")
                .expect("reconciled input")
                .status,
            RunInputStatus::Blocked
        );
    }

    #[tokio::test]
    async fn checkpoint_terminalization_failure_keeps_run_recoverable_and_input_queued() {
        let (state, checkpoint_path, root) = test_state_with_file_checkpoint("launch-secret");
        let (conversation, queued) =
            seed_queued_authoritative_run(&state, "checkpoint-save-failure");
        let running = state
            .prepare_authoritative_run_for_execution(
                &queued.id,
                &conversation.id,
                &conversation.project_id,
                &queued.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare run")
            .expect("running run");
        let input = queue_next_input(&state, &running, "checkpoint-save-failure");
        let checkpoint_connection =
            rusqlite::Connection::open(&checkpoint_path).expect("checkpoint failure connection");
        checkpoint_connection
            .execute_batch(
                "CREATE TRIGGER fail_checkpoint_terminalization
                 BEFORE INSERT ON checkpoints
                 BEGIN
                   SELECT RAISE(ABORT, 'forced checkpoint terminalization failure');
                 END;",
            )
            .expect("install checkpoint failure");

        let error = state
            .persist_authoritative_run_outcome(
                &running,
                DesktopRunStatus::Failed,
                Some("engine failed".to_string()),
                &now_iso(),
            )
            .await
            .expect_err("desktop run must not terminal-commit");
        assert!(error.contains(CHECKPOINT_TERMINALIZATION_RECOVERY_ERROR_PREFIX));
        let recovered = state
            .session_store
            .run(&running.id)
            .expect("load recoverable run")
            .expect("recoverable run");
        assert_eq!(recovered.status, DesktopRunStatus::Disconnected);
        assert!(recovered.completed_at.is_none());
        assert!(has_checkpoint_terminalization_recovery_error(&recovered));
        assert_eq!(
            state
                .session_store
                .run_input(&input.id)
                .expect("load queued input")
                .expect("queued input")
                .status,
            RunInputStatus::Queued
        );
        assert!(state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load quarantined checkpoint")
            .is_none());
        assert!(!state
            .session_store
            .run_events(&running.id)
            .expect("run events")
            .iter()
            .any(|event| event["type"] == "failed"));

        drop(checkpoint_connection);
        drop(state);
        std::fs::remove_dir_all(root).expect("remove checkpoint failure root");
    }

    #[tokio::test]
    async fn startup_finishes_cancel_after_checkpoint_commit_before_run_commit() {
        let state = test_state("launch-secret");
        let (conversation, queued) = seed_queued_authoritative_run(&state, "cancel-crash-window");
        assert!(state
            .ensure_authoritative_launch_checkpoint(&queued)
            .await
            .expect("seed launch checkpoint"));
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover queued run");
        }
        let interrupted = state
            .session_store
            .run(&queued.id)
            .expect("load interrupted run")
            .expect("interrupted run");
        state
            .terminalize_authoritative_checkpoint(&interrupted, SessionStatus::Cancelled)
            .await
            .expect("commit cancelled checkpoint before simulated crash");

        state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect("finish cancellation during startup");
        let cancelled = state
            .session_store
            .run(&queued.id)
            .expect("load cancelled run")
            .expect("cancelled run");
        assert_eq!(cancelled.status, DesktopRunStatus::Cancelled);
        assert!(cancelled.started_at.is_none());
        assert!(cancelled.completed_at.is_some());
        assert_eq!(cancelled.revision, interrupted.revision + 1);
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("load cancelled checkpoint")
                .expect("cancelled checkpoint")
                .status,
            SessionStatus::Cancelled
        );
    }

    #[tokio::test]
    async fn reconnect_never_restarts_a_terminalized_launch_checkpoint() {
        let state = test_state("launch-secret");
        let (conversation, queued) =
            seed_queued_authoritative_run(&state, "terminalized-reconnect");
        assert!(state
            .ensure_authoritative_launch_checkpoint(&queued)
            .await
            .expect("seed launch checkpoint"));
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover queued run");
        }
        let interrupted = state
            .session_store
            .run(&queued.id)
            .expect("load interrupted run")
            .expect("interrupted run");
        state
            .terminalize_authoritative_checkpoint(&interrupted, SessionStatus::Cancelled)
            .await
            .expect("terminalize launch checkpoint");

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/resume", interrupted.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        interrupted.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::CONFLICT);
        let stored = state
            .session_store
            .run(&interrupted.id)
            .expect("load stored run")
            .expect("stored run");
        assert_eq!(stored.status, DesktopRunStatus::Interrupted);
        assert_eq!(stored.revision, interrupted.revision);
        assert!(!state
            .session_store
            .run_events(&stored.id)
            .expect("run events")
            .iter()
            .any(|event| event["type"] == "running"));
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("load checkpoint")
                .expect("checkpoint")
                .status,
            SessionStatus::Cancelled
        );
    }

    #[tokio::test]
    async fn startup_reconciles_latest_inserted_fork_when_clock_moves_backwards() {
        let state = test_state("launch-secret");
        let (conversation, queued_source) =
            seed_queued_authoritative_run(&state, "clock-rollback-fork");
        let running_source = state
            .prepare_authoritative_run_for_execution(
                &queued_source.id,
                &conversation.id,
                &conversation.project_id,
                &queued_source.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare source")
            .expect("running source");
        let disconnected_source = state
            .session_store
            .transition_run(
                &running_source.id,
                running_source.revision,
                DesktopRunStatus::Disconnected,
                None,
                &now_iso(),
            )
            .expect("disconnect source");
        let clock_moved_back = "2000-01-01T00:00:00Z";
        let (queued_fork, created) = state
            .session_store
            .fork_recovery_run(
                &disconnected_source.id,
                disconnected_source.revision,
                "clock-rollback-fork-key",
                authority_store::DesktopExecutionEnvironment {
                    id: "clock-rollback-environment".to_string(),
                    kind: DesktopExecutionEnvironmentKind::Worktree,
                    label: "Clock rollback fork".to_string(),
                    workspace_path: "/tmp/agistack-clock-rollback-fork".to_string(),
                    repository_root: Some("/tmp/agistack-clock-rollback-source".to_string()),
                    branch: Some("agistack/clock-rollback-fork".to_string()),
                    base_commit: Some("clock-rollback-base".to_string()),
                    source_run_id: Some(disconnected_source.id.clone()),
                    created_at: clock_moved_back.to_string(),
                },
                clock_moved_back,
            )
            .expect("fork recovery run");
        assert!(created);
        state
            .session_store
            .transfer_checkpoint_authority(&disconnected_source, &queued_fork, clock_moved_back)
            .expect("transfer checkpoint authority to recovery fork");
        assert!(queued_fork.created_at < disconnected_source.created_at);
        let running_fork = state
            .prepare_authoritative_run_for_execution(
                &queued_fork.id,
                &conversation.id,
                &conversation.project_id,
                &queued_fork.request_message,
                clock_moved_back,
            )
            .await
            .expect("prepare fork")
            .expect("running fork");
        let mut checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load fork checkpoint")
            .expect("fork checkpoint");
        checkpoint.status = SessionStatus::Finished;
        state
            .checkpoints
            .save(&checkpoint)
            .await
            .expect("finish fork checkpoint");
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, "2000-01-01T00:00:01Z")
                .expect("recover running fork");
        }

        state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect("reconcile latest inserted fork");
        let stored_source = state
            .session_store
            .run(&disconnected_source.id)
            .expect("load source")
            .expect("source");
        assert_eq!(stored_source.status, DesktopRunStatus::Disconnected);
        assert_eq!(stored_source.revision, disconnected_source.revision);
        let stored_fork = state
            .session_store
            .run(&running_fork.id)
            .expect("load fork")
            .expect("fork");
        assert_eq!(stored_fork.status, DesktopRunStatus::ReadyReview);
        assert_eq!(stored_fork.revision, running_fork.revision + 2);
    }

    #[tokio::test]
    async fn startup_retry_settles_legacy_quarantine_before_checkpoint_cleanup() {
        let state = test_state("launch-secret");
        let (conversation, queued) =
            seed_queued_authoritative_run(&state, "legacy-quarantine-settlement");
        let running = state
            .prepare_authoritative_run_for_execution(
                &queued.id,
                &conversation.id,
                &conversation.project_id,
                &queued.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare run")
            .expect("running run");
        let input = queue_next_input(&state, &running, "legacy-quarantine-settlement");
        let mut checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint")
            .expect("checkpoint");
        checkpoint.goal = "mismatched checkpoint goal".to_string();
        state
            .checkpoints
            .save(&checkpoint)
            .await
            .expect("save mismatched checkpoint");
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover running run");
        }
        let disconnected = state
            .session_store
            .run(&running.id)
            .expect("load disconnected run")
            .expect("disconnected run");
        let quarantined = state
            .session_store
            .reconcile_recovered_run(
                &disconnected.id,
                disconnected.revision,
                DesktopRunStatus::Failed,
                Some(RECOVERED_CHECKPOINT_AUTHORITY_ERROR.to_string()),
                &now_iso(),
            )
            .expect("commit quarantine");
        let mut legacy_input = state
            .session_store
            .run_input(&input.id)
            .expect("load settled input")
            .expect("settled input");
        assert_eq!(legacy_input.status, RunInputStatus::Blocked);
        legacy_input.status = RunInputStatus::Queued;
        legacy_input.updated_at = now_iso();
        {
            let connection = state.session_store.connection().expect("connection");
            connection
                .execute(
                    "UPDATE desktop_run_inputs
                     SET status = 'queued', updated_at = ?2, value_json = ?3 WHERE id = ?1",
                    rusqlite::params![
                        legacy_input.id,
                        legacy_input.updated_at,
                        serde_json::to_string(&legacy_input).expect("serialize legacy input")
                    ],
                )
                .expect("simulate pre-atomic quarantine database");
        }

        state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect("retry quarantine cleanup");
        assert_eq!(
            state
                .session_store
                .run_input(&input.id)
                .expect("load repaired input")
                .expect("repaired input")
                .status,
            RunInputStatus::Blocked
        );
        assert!(state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load cleaned checkpoint")
            .is_none());
        let stored = state
            .session_store
            .run(&quarantined.id)
            .expect("load quarantined run")
            .expect("quarantined run");
        assert_eq!(stored.status, DesktopRunStatus::Failed);
        assert_eq!(stored.revision, quarantined.revision);
    }

    #[tokio::test]
    async fn transferred_started_source_controls_never_cross_the_core_checkpoint_boundary() {
        let (state, checkpoints) = test_state_with_counting_checkpoints("launch-secret");
        let (conversation, source, forked) =
            seed_transferred_recovery_fork(&state, "started-control-preflight").await;

        assert_transferred_source_controls_stop_before_core(
            &state,
            &checkpoints,
            &conversation,
            &source,
            &forked,
        )
        .await;
    }

    #[tokio::test]
    async fn transferred_unstarted_source_controls_never_cross_the_core_checkpoint_boundary() {
        let (state, checkpoints) = test_state_with_counting_checkpoints("launch-secret");
        let (conversation, source, forked) =
            seed_transferred_unstarted_recovery_fork(&state, "unstarted-control-preflight").await;

        assert_transferred_source_controls_stop_before_core(
            &state,
            &checkpoints,
            &conversation,
            &source,
            &forked,
        )
        .await;
    }

    #[tokio::test]
    async fn transferred_source_new_recovery_key_has_zero_prepare_db_or_event_side_effects() {
        let (state, checkpoints) = test_state_with_counting_checkpoints("launch-secret");
        let (conversation, source, forked) =
            seed_transferred_recovery_fork(&state, "different-key-preflight").await;
        let idempotency_key = "different-key-after-authority-transfer";
        let run_ids_before: Vec<String> = state
            .session_store
            .list_runs(&conversation.id)
            .expect("list runs before rejected fork")
            .into_iter()
            .map(|run| run.id)
            .collect();
        let source_events_before = state
            .session_store
            .run_events(&source.id)
            .expect("source events before rejected fork")
            .len();
        let fork_events_before = state
            .session_store
            .run_events(&forked.id)
            .expect("fork events before rejected fork")
            .len();
        let timeline_before = state
            .session_store
            .timeline_count(&conversation.id)
            .expect("timeline count before rejected fork");
        let decision_count_before: i64 = state
            .session_store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_decisions WHERE conversation_id = ?1",
                [&conversation.id],
                |row| row.get(0),
            )
            .expect("decision count before rejected fork");
        let authority_before = state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load authority before rejected fork")
            .expect("checkpoint authority");
        let checkpoint_before = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint before rejected fork")
            .expect("checkpoint");
        let event_counter_before = state.event_counter.load(Ordering::SeqCst);
        checkpoints.reset();
        state.agent_run_claim_attempts.store(0, Ordering::SeqCst);
        state.agent_engine_attempts.store(0, Ordering::SeqCst);
        state
            .recovery_fork_prepare_attempts
            .store(0, Ordering::SeqCst);

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/fork", source.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{},"idempotency_key":"{idempotency_key}"}}"#,
                        source.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::CONFLICT);
        assert_eq!(
            response_json(response).await["detail"],
            CHECKPOINT_CONTROL_AUTHORITY_ERROR
        );
        assert_eq!(
            checkpoints.operation_counts(),
            CheckpointOperationCounts {
                loads: 0,
                saves: 0,
                deletes: 0,
            }
        );
        assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 0);
        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 0);
        assert_eq!(
            state.recovery_fork_prepare_attempts.load(Ordering::SeqCst),
            0
        );
        assert!(state
            .agent_runs
            .lock()
            .expect("local agent runs")
            .is_empty());
        assert!(state
            .session_store
            .run_by_idempotency_key(idempotency_key)
            .expect("load rejected fork key")
            .is_none());
        assert_eq!(
            state
                .session_store
                .list_runs(&conversation.id)
                .expect("list runs after rejected fork")
                .into_iter()
                .map(|run| run.id)
                .collect::<Vec<_>>(),
            run_ids_before
        );
        assert_eq!(
            state
                .session_store
                .run_events(&source.id)
                .expect("source events after rejected fork")
                .len(),
            source_events_before
        );
        assert_eq!(
            state
                .session_store
                .run_events(&forked.id)
                .expect("fork events after rejected fork")
                .len(),
            fork_events_before
        );
        assert_eq!(
            state
                .session_store
                .timeline_count(&conversation.id)
                .expect("timeline count after rejected fork"),
            timeline_before
        );
        let decision_count_after: i64 = state
            .session_store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_decisions WHERE conversation_id = ?1",
                [&conversation.id],
                |row| row.get(0),
            )
            .expect("decision count after rejected fork");
        assert_eq!(decision_count_after, decision_count_before);
        assert_eq!(
            state.event_counter.load(Ordering::SeqCst),
            event_counter_before
        );
        assert_eq!(
            state
                .session_store
                .checkpoint_authority(&conversation.id)
                .expect("load authority after rejected fork")
                .expect("checkpoint authority"),
            authority_before
        );
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("load checkpoint after rejected fork")
                .expect("checkpoint"),
            checkpoint_before
        );
    }

    #[tokio::test]
    async fn busy_conversation_recovery_fork_claim_fails_before_prepare_or_insert() {
        let (state, checkpoints) = test_state_with_counting_checkpoints("launch-secret");
        let (conversation, queued_source) =
            seed_queued_authoritative_run(&state, "busy-recovery-claim");
        let running_source = state
            .prepare_authoritative_run_for_execution(
                &queued_source.id,
                &conversation.id,
                &conversation.project_id,
                &queued_source.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare source")
            .expect("running source");
        let source = state
            .session_store
            .transition_run(
                &running_source.id,
                running_source.revision,
                DesktopRunStatus::Disconnected,
                None,
                &now_iso(),
            )
            .expect("disconnect source");
        let blocker = state
            .claim_agent_run(&conversation.id, Some("blocking-run"))
            .expect("claim blocking run");
        let idempotency_key = "busy-conversation-recovery-key";
        let runs_before = state
            .session_store
            .list_runs(&conversation.id)
            .expect("list runs before busy fork")
            .len();
        let source_events_before = state
            .session_store
            .run_events(&source.id)
            .expect("source events before busy fork")
            .len();
        let timeline_before = state
            .session_store
            .timeline_count(&conversation.id)
            .expect("timeline before busy fork");
        let decision_count_before: i64 = state
            .session_store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_decisions WHERE conversation_id = ?1",
                [&conversation.id],
                |row| row.get(0),
            )
            .expect("decisions before busy fork");
        let event_counter_before = state.event_counter.load(Ordering::SeqCst);
        checkpoints.reset();
        state.agent_run_claim_attempts.store(0, Ordering::SeqCst);
        state.agent_engine_attempts.store(0, Ordering::SeqCst);
        state
            .recovery_fork_prepare_attempts
            .store(0, Ordering::SeqCst);

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/fork", source.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{},"idempotency_key":"{idempotency_key}"}}"#,
                        source.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::CONFLICT);
        assert_eq!(
            response_json(response).await["detail"],
            "conversation already running"
        );
        assert_eq!(
            checkpoints.operation_counts(),
            CheckpointOperationCounts {
                loads: 1,
                saves: 0,
                deletes: 0,
            }
        );
        assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 1);
        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 0);
        assert_eq!(
            state.recovery_fork_prepare_attempts.load(Ordering::SeqCst),
            0
        );
        assert!(state
            .session_store
            .run_by_idempotency_key(idempotency_key)
            .expect("load busy fork key")
            .is_none());
        assert_eq!(
            state
                .session_store
                .list_runs(&conversation.id)
                .expect("list runs after busy fork")
                .len(),
            runs_before
        );
        assert_eq!(
            state
                .session_store
                .run_events(&source.id)
                .expect("source events after busy fork")
                .len(),
            source_events_before
        );
        assert_eq!(
            state
                .session_store
                .timeline_count(&conversation.id)
                .expect("timeline after busy fork"),
            timeline_before
        );
        let decision_count_after: i64 = state
            .session_store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_decisions WHERE conversation_id = ?1",
                [&conversation.id],
                |row| row.get(0),
            )
            .expect("decisions after busy fork");
        assert_eq!(decision_count_after, decision_count_before);
        assert_eq!(
            state.event_counter.load(Ordering::SeqCst),
            event_counter_before
        );
        state.release_agent_run_if_control(&conversation.id, &blocker);
    }

    #[tokio::test]
    async fn recovery_fork_rollback_restores_source_authority_and_preserves_core_checkpoint() {
        let state = test_state("launch-secret");
        let (conversation, source, forked) =
            seed_transferred_recovery_fork(&state, "rollback-authority").await;
        let checkpoint_before = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint before rollback")
            .expect("checkpoint");
        assert!(state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load fork authority")
            .is_some_and(|authority| authority.matches_run(&forked)));

        assert!(state
            .session_store
            .rollback_recovery_fork(&source, &forked, &now_iso())
            .expect("roll back recovery fork"));

        assert!(state
            .session_store
            .run(&forked.id)
            .expect("load rolled back fork")
            .is_none());
        assert!(state
            .session_store
            .run_events(&forked.id)
            .expect("load rolled back events")
            .is_empty());
        assert!(state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load restored authority")
            .is_some_and(|authority| authority.matches_run(&source)));
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("load checkpoint after rollback")
                .expect("checkpoint"),
            checkpoint_before
        );
        let stored_source = state
            .session_store
            .run(&source.id)
            .expect("load source after rollback")
            .expect("source");
        assert_eq!(stored_source.status, source.status);
        assert_eq!(stored_source.revision, source.revision);
    }

    #[tokio::test]
    async fn recovery_fork_cleanup_failure_is_reported_after_database_rollback() {
        let state = test_state("launch-secret");
        let (conversation, source, forked) =
            seed_transferred_recovery_fork(&state, "rollback-cleanup-error").await;
        let checkpoint_before = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load checkpoint before failed cleanup")
            .expect("checkpoint");
        let environment = forked.environment.as_ref().expect("fork environment");

        let (status, detail) = run_control::rollback_created_recovery_fork(
            &state,
            &source,
            &forked,
            Some(environment),
        )
        .expect_err("missing repository root must report cleanup failure");

        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(
            detail.0["detail"],
            "recovery fork rolled back but its worktree cleanup failed"
        );
        assert!(state
            .session_store
            .run(&forked.id)
            .expect("load rolled back fork")
            .is_none());
        assert!(state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load restored authority")
            .is_some_and(|authority| authority.matches_run(&source)));
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("load checkpoint after failed cleanup")
                .expect("checkpoint"),
            checkpoint_before
        );
    }

    #[tokio::test]
    async fn post_transfer_resume_failure_removes_created_worktree_run_and_events() {
        let state = test_state("launch-secret");
        let root = state.workspace_root.lock().expect("workspace root").clone();
        run_test_git(&root, &["init"]);
        run_test_git(
            &root,
            &["config", "user.email", "desktop-tests@example.invalid"],
        );
        run_test_git(&root, &["config", "user.name", "Desktop Tests"]);
        std::fs::write(root.join("README.md"), "recovery rollback fixture\n")
            .expect("write rollback fixture");
        run_test_git(&root, &["add", "README.md"]);
        run_test_git(&root, &["commit", "-m", "recovery rollback fixture"]);

        let (conversation, queued_source) =
            seed_queued_authoritative_run(&state, "post-transfer-rollback");
        let running_source = state
            .prepare_authoritative_run_for_execution(
                &queued_source.id,
                &conversation.id,
                &conversation.project_id,
                &queued_source.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare source")
            .expect("running source");
        let source = state
            .session_store
            .transition_run(
                &running_source.id,
                running_source.revision,
                DesktopRunStatus::Disconnected,
                None,
                &now_iso(),
            )
            .expect("disconnect source");
        let mut checkpoint_before = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load source checkpoint")
            .expect("source checkpoint");
        checkpoint_before.status = SessionStatus::AwaitingInput;
        state
            .checkpoints
            .save(&checkpoint_before)
            .await
            .expect("save non-resumable checkpoint");
        let idempotency_key = "post-transfer-resume-failure";
        let run_ids_before: Vec<String> = state
            .session_store
            .list_runs(&conversation.id)
            .expect("list runs before failed recovery")
            .into_iter()
            .map(|run| run.id)
            .collect();
        let source_events_before = state
            .session_store
            .run_events(&source.id)
            .expect("source events before failed recovery")
            .len();
        let timeline_before = state
            .session_store
            .timeline_count(&conversation.id)
            .expect("timeline before failed recovery");
        let decision_count_before: i64 = state
            .session_store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_decisions WHERE conversation_id = ?1",
                [&conversation.id],
                |row| row.get(0),
            )
            .expect("decisions before failed recovery");
        let event_counter_before = state.event_counter.load(Ordering::SeqCst);
        state.agent_run_claim_attempts.store(0, Ordering::SeqCst);
        state.agent_engine_attempts.store(0, Ordering::SeqCst);
        state
            .recovery_fork_prepare_attempts
            .store(0, Ordering::SeqCst);

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/fork", source.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{},"idempotency_key":"{idempotency_key}"}}"#,
                        source.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::CONFLICT);
        assert!(response_json(response).await["detail"]
            .as_str()
            .is_some_and(|detail| detail.contains("AwaitingInput")));
        assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 1);
        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 1);
        assert_eq!(
            state.recovery_fork_prepare_attempts.load(Ordering::SeqCst),
            2
        );
        assert!(state
            .agent_runs
            .lock()
            .expect("local agent runs")
            .is_empty());
        assert!(state
            .session_store
            .run_by_idempotency_key(idempotency_key)
            .expect("load failed recovery key")
            .is_none());
        assert_eq!(
            state
                .session_store
                .list_runs(&conversation.id)
                .expect("list runs after failed recovery")
                .into_iter()
                .map(|run| run.id)
                .collect::<Vec<_>>(),
            run_ids_before
        );
        assert_eq!(
            state
                .session_store
                .run_events(&source.id)
                .expect("source events after failed recovery")
                .len(),
            source_events_before
        );
        assert_eq!(
            state
                .session_store
                .timeline_count(&conversation.id)
                .expect("timeline after failed recovery"),
            timeline_before
        );
        let decision_count_after: i64 = state
            .session_store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT COUNT(*) FROM desktop_decisions WHERE conversation_id = ?1",
                [&conversation.id],
                |row| row.get(0),
            )
            .expect("decisions after failed recovery");
        assert_eq!(decision_count_after, decision_count_before);
        assert_eq!(
            state.event_counter.load(Ordering::SeqCst),
            event_counter_before
        );
        assert!(state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load restored authority")
            .is_some_and(|authority| authority.matches_run(&source)));
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("load checkpoint after failed recovery")
                .expect("checkpoint"),
            checkpoint_before
        );
        let worktree_list = run_test_git(&root, &["worktree", "list", "--porcelain"]);
        assert_eq!(
            worktree_list
                .lines()
                .filter(|line| line.starts_with("worktree "))
                .count(),
            1
        );
        assert!(
            !run_test_git(&root, &["branch", "--list", "agistack/local-environment-*"])
                .lines()
                .any(|line| !line.trim().is_empty())
        );

        let worktrees_root = root
            .parent()
            .expect("repository parent")
            .join(".agistack-worktrees")
            .join(root.file_name().expect("repository name"));
        std::fs::remove_dir_all(worktrees_root).unwrap_or(());
        std::fs::remove_dir_all(root).expect("remove rollback fixture");
    }

    #[tokio::test]
    async fn transferred_source_same_queued_recovery_key_replays_without_source_preflight() {
        let (state, checkpoints) = test_state_with_counting_checkpoints("launch-secret");
        let (conversation, queued_source) =
            seed_queued_authoritative_run(&state, "same-queued-key-replay");
        let running_source = state
            .prepare_authoritative_run_for_execution(
                &queued_source.id,
                &conversation.id,
                &conversation.project_id,
                &queued_source.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare source")
            .expect("running source");
        let source = state
            .session_store
            .transition_run(
                &running_source.id,
                running_source.revision,
                DesktopRunStatus::Disconnected,
                None,
                &now_iso(),
            )
            .expect("disconnect source");
        let workspace_path = state
            .workspace_root
            .lock()
            .expect("workspace root")
            .to_string_lossy()
            .into_owned();
        let idempotency_key = "same-queued-recovery-key";
        let (forked, created) = state
            .session_store
            .fork_recovery_run(
                &source.id,
                source.revision,
                idempotency_key,
                DesktopExecutionEnvironment {
                    id: "same-queued-recovery-environment".to_string(),
                    kind: DesktopExecutionEnvironmentKind::Local,
                    label: "Same queued recovery environment".to_string(),
                    workspace_path,
                    repository_root: None,
                    branch: None,
                    base_commit: None,
                    source_run_id: Some(source.id.clone()),
                    created_at: now_iso(),
                },
                &now_iso(),
            )
            .expect("create queued recovery fork");
        assert!(created);
        state
            .session_store
            .transfer_checkpoint_authority(&source, &forked, &now_iso())
            .expect("transfer checkpoint authority");
        checkpoints.reset();
        state.agent_run_claim_attempts.store(0, Ordering::SeqCst);
        state.agent_engine_attempts.store(0, Ordering::SeqCst);
        state
            .recovery_fork_prepare_attempts
            .store(0, Ordering::SeqCst);

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/fork", source.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{},"idempotency_key":"{idempotency_key}"}}"#,
                        source.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let payload = response_json(response).await;
        assert_eq!(payload["created"], false);
        assert_eq!(payload["run"]["id"], forked.id);
        assert_eq!(payload["run"]["status"], "running");
        assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 1);
        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 1);
        assert_eq!(
            state.recovery_fork_prepare_attempts.load(Ordering::SeqCst),
            0
        );
        assert!(state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load replay checkpoint authority")
            .is_some_and(|authority| authority.matches_run(&forked)));
    }

    #[tokio::test]
    async fn old_source_cancel_never_terminalizes_fork_checkpoint_after_authority_transfer() {
        let state = test_state("launch-secret");
        let (conversation, source, forked) =
            seed_transferred_recovery_fork(&state, "old-source-cancel").await;
        let checkpoint_before = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load fork checkpoint")
            .expect("fork checkpoint");
        let authority_before = state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load fork checkpoint authority")
            .expect("fork checkpoint authority");

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/cancel", source.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        source.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::CONFLICT);
        assert_eq!(
            response_json(response).await["detail"],
            CHECKPOINT_CONTROL_AUTHORITY_ERROR
        );
        let stored_source = state
            .session_store
            .run(&source.id)
            .expect("load source")
            .expect("source");
        assert_eq!(stored_source.status, DesktopRunStatus::Disconnected);
        assert_eq!(stored_source.revision, source.revision);
        let stored_fork = state
            .session_store
            .run(&forked.id)
            .expect("load fork")
            .expect("fork");
        assert_eq!(stored_fork.status, DesktopRunStatus::Queued);
        assert_eq!(stored_fork.revision, forked.revision);
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("reload fork checkpoint")
                .expect("fork checkpoint"),
            checkpoint_before
        );
        assert_eq!(
            state
                .session_store
                .checkpoint_authority(&conversation.id)
                .expect("reload fork checkpoint authority")
                .expect("fork checkpoint authority"),
            authority_before
        );
        let control = state
            .claim_agent_run(&conversation.id, Some(&forked.id))
            .expect("failed cancel released the conversation claim");
        state.release_agent_run_if_control(&conversation.id, &control);
    }

    #[tokio::test]
    async fn old_source_resume_never_reopens_fork_checkpoint_after_authority_transfer() {
        let state = test_state("launch-secret");
        let (conversation, source, forked) =
            seed_transferred_recovery_fork(&state, "old-source-resume").await;
        let checkpoint_before = state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load fork checkpoint")
            .expect("fork checkpoint");
        let authority_before = state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load fork checkpoint authority")
            .expect("fork checkpoint authority");
        let source_events_before = state
            .session_store
            .run_events(&source.id)
            .expect("load source events")
            .len();

        let response = local_router(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(format!("/api/v1/agent/runs/{}/resume", source.id))
                    .header("authorization", "Bearer launch-secret")
                    .header("content-type", "application/json")
                    .body(Body::from(format!(
                        r#"{{"expected_revision":{}}}"#,
                        source.revision
                    )))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::CONFLICT);
        assert_eq!(
            response_json(response).await["detail"],
            CHECKPOINT_CONTROL_AUTHORITY_ERROR
        );
        let stored_source = state
            .session_store
            .run(&source.id)
            .expect("load source")
            .expect("source");
        assert_eq!(stored_source.status, DesktopRunStatus::Disconnected);
        assert_eq!(stored_source.revision, source.revision);
        assert_eq!(
            state
                .session_store
                .run_events(&source.id)
                .expect("reload source events")
                .len(),
            source_events_before
        );
        let stored_fork = state
            .session_store
            .run(&forked.id)
            .expect("load fork")
            .expect("fork");
        assert_eq!(stored_fork.status, DesktopRunStatus::Queued);
        assert_eq!(stored_fork.revision, forked.revision);
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("reload fork checkpoint")
                .expect("fork checkpoint"),
            checkpoint_before
        );
        assert_eq!(
            state
                .session_store
                .checkpoint_authority(&conversation.id)
                .expect("reload fork checkpoint authority")
                .expect("fork checkpoint authority"),
            authority_before
        );
        let control = state
            .claim_agent_run(&conversation.id, Some(&forked.id))
            .expect("failed resume released the conversation claim");
        state.release_agent_run_if_control(&conversation.id, &control);
    }

    #[tokio::test]
    async fn fresh_queued_run_never_reuses_a_running_checkpoint() {
        let state = test_state("launch-secret");
        let (conversation, first_queued) =
            seed_queued_authoritative_run(&state, "stale-running-checkpoint");
        let first_running = state
            .prepare_authoritative_run_for_execution(
                &first_queued.id,
                &conversation.id,
                &conversation.project_id,
                &first_queued.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare first run")
            .expect("first run");
        let disconnected = state
            .session_store
            .transition_run(
                &first_running.id,
                first_running.revision,
                DesktopRunStatus::Disconnected,
                Some("checkpoint requires inspection".to_string()),
                &now_iso(),
            )
            .expect("disconnect first run");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "stale-running-checkpoint-second-task",
                    "conversation_id": conversation.id,
                    "content": "Repeat the same request under new authority",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("create second plan");
        let second = state
            .session_store
            .approve_plan_and_start(
                &conversation.id,
                &conversation.project_id,
                "stale-running-checkpoint-second-key",
                "stale-running-checkpoint-second-message",
                &first_running.request_message,
                &now_iso(),
            )
            .expect("approve second plan")
            .run;

        let error = state
            .prepare_authoritative_run_for_execution(
                &second.id,
                &conversation.id,
                &conversation.project_id,
                &second.request_message,
                &now_iso(),
            )
            .await
            .expect_err("a fresh run must not inherit a prior running checkpoint");
        assert!(error.contains("conflicts with Running session state"));
        let unchanged = state
            .session_store
            .run(&second.id)
            .expect("load second run")
            .expect("second run");
        assert_eq!(unchanged.status, DesktopRunStatus::Queued);
        assert_eq!(unchanged.revision, second.revision);
        assert_eq!(
            state
                .checkpoints
                .load(&conversation.id)
                .await
                .expect("load prior checkpoint")
                .expect("prior checkpoint")
                .status,
            SessionStatus::Running
        );
        assert_eq!(disconnected.status, DesktopRunStatus::Disconnected);
        let authority = state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load checkpoint authority")
            .expect("checkpoint authority");
        assert_eq!(authority.run_id, disconnected.id);
    }

    #[tokio::test]
    async fn recovered_fresh_run_never_reuses_prior_running_checkpoint() {
        let state = test_state("launch-secret");
        let (conversation, first_queued) =
            seed_queued_authoritative_run(&state, "recovered-fresh-checkpoint");
        let first_running = state
            .prepare_authoritative_run_for_execution(
                &first_queued.id,
                &conversation.id,
                &conversation.project_id,
                &first_queued.request_message,
                &now_iso(),
            )
            .await
            .expect("prepare first run")
            .expect("first run");
        let disconnected = state
            .session_store
            .transition_run(
                &first_running.id,
                first_running.revision,
                DesktopRunStatus::Disconnected,
                Some("checkpoint requires inspection".to_string()),
                &now_iso(),
            )
            .expect("disconnect first run");
        state
            .session_store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "recovered-fresh-checkpoint-second-task",
                    "conversation_id": conversation.id,
                    "content": "Repeat the same request under new authority",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("create second plan");
        let second = state
            .session_store
            .approve_plan_and_start(
                &conversation.id,
                &conversation.project_id,
                "recovered-fresh-checkpoint-second-key",
                "recovered-fresh-checkpoint-second-message",
                &first_running.request_message,
                &now_iso(),
            )
            .expect("approve second plan")
            .run;
        {
            let connection = state.session_store.connection().expect("connection");
            authority_store::recover_interrupted_runs(&connection, &now_iso())
                .expect("recover second queued run");
        }
        let interrupted = state
            .session_store
            .run(&second.id)
            .expect("load recovered second run")
            .expect("recovered second run");
        assert_eq!(interrupted.status, DesktopRunStatus::Interrupted);

        state
            .reconcile_recovered_runs_from_checkpoints()
            .await
            .expect("quarantine stale checkpoint attribution");

        let failed = state
            .session_store
            .run(&second.id)
            .expect("load quarantined second run")
            .expect("quarantined second run");
        assert_eq!(failed.status, DesktopRunStatus::Failed);
        assert_eq!(
            failed.error.as_deref(),
            Some(RECOVERED_CHECKPOINT_AUTHORITY_ERROR)
        );
        assert!(!state
            .session_store
            .run_events(&second.id)
            .expect("second run events")
            .iter()
            .any(|event| event["type"] == "running"));
        assert_eq!(
            state
                .session_store
                .run(&disconnected.id)
                .expect("load first run")
                .expect("first run")
                .status,
            DesktopRunStatus::Disconnected
        );
        assert!(state
            .checkpoints
            .load(&conversation.id)
            .await
            .expect("load quarantined checkpoint")
            .is_none());
        assert!(state
            .session_store
            .checkpoint_authority(&conversation.id)
            .expect("load quarantined authority")
            .is_none());
    }
}
