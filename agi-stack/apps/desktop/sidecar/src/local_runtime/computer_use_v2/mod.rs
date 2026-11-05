//! Local device admission and run leases for the managed computer-use plugin.
pub(in crate::local_runtime) mod accounts;
mod api;
mod artifacts;
pub(in crate::local_runtime) mod call_identity;
pub(in crate::local_runtime) mod cloud;
mod cloud_cleanup;
#[cfg(test)]
mod cloud_tests;
mod connectors;
mod consent;
#[cfg(test)]
mod consent_tests;
pub(in crate::local_runtime) mod denials;
mod host;
pub(super) mod local_control;
mod locked_use;
pub(super) mod repl_media;
mod user_control;
#[cfg(test)]
use host::capability_for;
use host::ScopedComputerUseHost;
pub(super) mod hitl;
pub(super) mod hitl_validation;
mod input;
#[cfg(test)]
mod management_lifecycle_tests;
mod module;
mod presentation;
mod recordings;
mod recordings_export;
mod recordings_read;
mod recordings_store;
#[cfg(test)]
mod recordings_tests;
mod resource_lease;
pub(in crate::local_runtime) mod store;
#[cfg(test)]
mod tests;
pub(super) use api::native_operation;
pub(super) use api::operation as apply_management;
pub(super) use api::router;
pub(super) use module::definition;
pub(in crate::local_runtime) fn declared_connector_tool(
    server: &super::mcp_supervisor::McpServerDefinition,
    tool: &str,
) -> bool {
    connectors::declares_tool(server, tool)
}
tokio::task_local! {static ADMITTED_EFFECT:agistack_adapters_cua::CuaToolEffect;}
pub(super) fn input_effect(
    host: &dyn ToolHost,
    tool: &str,
    input: &str,
) -> CoreResult<agistack_adapters_cua::CuaToolEffect> {
    if tool == "computer_connector_call" {
        let input: Value = serde_json::from_str(input)
            .map_err(|_| CoreError::Tool("cua_invalid_params".into()))?;
        Ok(host
            .tool_definition(tool)
            .and_then(|definition| definition.input_schema)
            .map(|schema| agistack_adapters_cua::connector_operation_effect(&schema, &input))
            .unwrap_or(agistack_adapters_cua::CuaToolEffect::Mutate))
    } else {
        agistack_adapters_cua::tool_effects()
            .get(tool)
            .copied()
            .ok_or_else(|| CoreError::Tool("cua_tool_unknown".into()))
    }
}
pub(super) fn has_read_operation(host: &dyn ToolHost, tool: &str) -> bool {
    tool == "computer_connector_call"
        && host
            .tool_definition(tool)
            .and_then(|definition| definition.input_schema)
            .is_some_and(|schema| agistack_adapters_cua::has_read_connector_operation(&schema))
}
pub(super) async fn with_effect<F: std::future::Future>(
    effect: agistack_adapters_cua::CuaToolEffect,
    future: F,
) -> F::Output {
    ADMITTED_EFFECT.scope(effect, future).await
}
pub(in crate::local_runtime) fn apply_guidance(
    profile: &mut super::execution_profile::ExecutionProfile,
    tools: &dyn ToolHost,
) {
    if tools
        .list_tools()
        .iter()
        .any(|name| agistack_adapters_cua::tool_effects().contains_key(name.as_str()))
    {
        profile
            .instructions
            .push_str("\n\n[Computer Use runtime skill]\n");
        profile.instructions.push_str(include_str!(
            "../../../../cua-plugin/skills/computer-use/SKILL.md"
        ));
    }
}
pub(super) fn migrate_schema(db: &rusqlite::Connection) -> Result<(), String> {
    store::initialize(db)?;
    store::pending_schema(db)?;
    accounts::initialize(db)?;
    call_identity::initialize(db)?;
    artifacts::initialize(db)?;
    denials::initialize(db)?;
    user_control::initialize(db).and_then(|_| recordings_store::initialize(db))
}

use super::{
    knowledge_authority_v2::agent_access::PluginNativeIdentityV2, DesktopRun, LocalConversation,
    LocalRuntimeState,
};
use agistack_adapters_cua::{CuaCallContext, CuaClient, CuaToolHost};
use agistack_core::ports::{CoreError, CoreResult, ToolDefinition, ToolHost, ToolResult};
use agistack_plugin_host::protocol_v2::{ScopeKindV2, ScopeV2};
use serde::Serialize;
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex, OnceLock,
    },
};
use store::{Instance, Owner};
use uuid::Uuid;

#[derive(Clone, Serialize)]
pub(super) struct PendingConsent {
    pub request_id: String,
    pub session_id: String,
    /// The sealed cloud engine scope; native grants remain bound to `session_id` above.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub engine_session_id: Option<String>,
    pub app: String,
    pub identity_digest: String,
    pub capability: String,
    pub tool_name: String,
    pub input_digest: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub app_icon: Option<Value>,
    #[serde(skip)]
    owner: Owner,
}

struct Session {
    resources: resource_lease::ResourceLease,
    dispatch: tokio::sync::Mutex<()>,
    owner: Owner,
    context: CuaCallContext,
    revision: u64,
    stopped: AtomicBool,
    paused: AtomicBool,
    user_control: Arc<user_control::Control>,
    presentation: Mutex<Value>,
    child: Option<super::local_plugin_tool_host_v2::identity::ChildIdentityV2>,
    cloud: Option<cloud::SessionBinding>,
}

#[derive(Clone)]
enum NativeIdentity {
    Local(PluginNativeIdentityV2),
    Cloud(cloud::CloudLease),
}
impl NativeIdentity {
    fn current(&self, state: &LocalRuntimeState) -> bool {
        match self {
            Self::Local(identity) => identity.current(state),
            Self::Cloud(identity) => identity.current(state),
        }
    }
    fn permits(&self, tool: &str, effect: agistack_adapters_cua::CuaToolEffect) -> bool {
        match self {
            Self::Local(_) => true,
            Self::Cloud(identity) => identity.permits(tool, effect),
        }
    }
    fn allowed_mcp_servers(&self, state: &LocalRuntimeState, conversation_id: &str) -> Vec<String> {
        match self {
            Self::Local(_) => {
                let Some(conversation) = state
                    .session_store
                    .conversation(conversation_id)
                    .ok()
                    .flatten()
                else {
                    return vec![];
                };
                let parent = state
                    .execution_profile(&conversation)
                    .map(|profile| profile.allowed_mcp_servers)
                    .unwrap_or_default();
                let Some(child) = super::local_plugin_tool_host_v2::identity::current_child()
                else {
                    return parent;
                };
                let Some(resource) = state
                    .session_store
                    .managed_resource(
                        super::ManagedResourceKind::SubAgent,
                        "tenant",
                        &conversation.tenant_id,
                        &child.subagent_id,
                    )
                    .ok()
                    .flatten()
                else {
                    return vec![];
                };
                let Some(values) = resource["allowed_mcp_servers"].as_array() else {
                    return vec![];
                };
                let Some(child) = values
                    .iter()
                    .map(|value| value.as_str().map(str::to_owned))
                    .collect::<Option<Vec<_>>>()
                else {
                    return vec![];
                };
                if child.iter().any(|server| server == "*") {
                    parent
                } else if parent.iter().any(|server| server == "*") {
                    child
                } else {
                    child
                        .into_iter()
                        .filter(|server| parent.contains(server))
                        .collect()
                }
            }
            Self::Cloud(identity) => identity.allowed_mcp_servers.clone(),
        }
    }
}

pub(super) struct ComputerUseRuntimeV2 {
    locked_use: locked_use::Leases,
    client: OnceLock<Arc<CuaClient>>,
    sessions: Mutex<BTreeMap<String, Arc<Session>>>,
    pending: Mutex<BTreeMap<String, PendingConsent>>,
    helper_closing: AtomicBool,
    shutting_down: AtomicBool,
    shutdown_gate: tokio::sync::Mutex<()>,
    permissions: Mutex<Option<Value>>,
    cloud_connections: Mutex<BTreeMap<String, cloud::Connection>>,
    cloud_cleanup: cloud_cleanup::Bindings,
    cloud_requests: Mutex<BTreeMap<String, cloud::RequestBinding>>,
    stopped_cloud_runs: Mutex<BTreeSet<(Owner, String)>>,
    local_controls: Mutex<BTreeMap<(String, String), local_control::Receipt>>,
    management: tokio::sync::Mutex<()>,
    recordings_gate: tokio::sync::Mutex<()>,
    status_listener: AtomicBool,
    input_support: Mutex<Option<Value>>,
    input_support_probe: AtomicBool,
    pub(in crate::local_runtime) input_events: tokio::sync::watch::Sender<BTreeMap<String, Value>>,
}

impl Default for ComputerUseRuntimeV2 {
    fn default() -> Self {
        Self {
            locked_use: Default::default(),
            client: OnceLock::new(),
            sessions: Mutex::new(BTreeMap::new()),
            pending: Mutex::new(BTreeMap::new()),
            helper_closing: AtomicBool::new(false),
            shutting_down: AtomicBool::new(false),
            shutdown_gate: tokio::sync::Mutex::new(()),
            permissions: Mutex::new(None),
            cloud_connections: Mutex::new(BTreeMap::new()),
            cloud_cleanup: cloud_cleanup::Bindings::default(),
            cloud_requests: Mutex::new(BTreeMap::new()),
            stopped_cloud_runs: Mutex::new(BTreeSet::new()),
            local_controls: Mutex::new(BTreeMap::new()),
            management: tokio::sync::Mutex::new(()),
            recordings_gate: tokio::sync::Mutex::new(()),
            status_listener: AtomicBool::new(false),
            input_support: Mutex::new(None),
            input_support_probe: AtomicBool::new(false),
            input_events: tokio::sync::watch::channel(BTreeMap::new()).0,
        }
    }
}

impl ComputerUseRuntimeV2 {
    async fn shutdown_if_idle(&self) {
        let close = {
            let sessions = self.sessions.lock().expect("computer-use sessions");
            sessions.is_empty()
                && self
                    .helper_closing
                    .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
                    .is_ok()
        };
        if close {
            if let Some(client) = self.client.get() {
                client.shutdown_if_audio_idle().await;
            }
            self.helper_closing.store(false, Ordering::SeqCst);
        }
    }
    fn child_session(
        &self,
        parent: &Arc<Session>,
        child: super::local_plugin_tool_host_v2::identity::ChildIdentityV2,
    ) -> CoreResult<Arc<Session>> {
        let mut sessions = self.sessions.lock().expect("computer-use sessions");
        if self.shutting_down.load(Ordering::SeqCst)
            || self.helper_closing.load(Ordering::SeqCst)
            || parent.stopped.load(Ordering::SeqCst)
        {
            return Err(CoreError::Tool("cua_device_stopping".into()));
        }
        if let Some(existing) = sessions.values().find(|session| {
            session.owner == parent.owner
                && session.context.run_id == child.run_id
                && session.revision == parent.revision
                && session
                    .child
                    .as_ref()
                    .is_some_and(|bound| bound.execution_id == child.execution_id)
                && !session.stopped.load(Ordering::SeqCst)
        }) {
            return Ok(existing.clone());
        }
        let mut context = parent.context.clone();
        context.session_id = format!("cua-child-{}", Uuid::new_v4());
        let session = Arc::new(Session {
            resources: Default::default(),
            dispatch: tokio::sync::Mutex::new(()),
            owner: parent.owner.clone(),
            context,
            revision: parent.revision,
            stopped: AtomicBool::new(false),
            paused: AtomicBool::new(false),
            user_control: Default::default(),
            presentation: Mutex::new(json!({"phase":"idle","can_resume":false})),
            child: Some(child),
            cloud: parent.cloud.clone(),
        });
        sessions.insert(session.context.session_id.clone(), session.clone());
        Ok(session)
    }
    pub(super) fn client(&self) -> Result<Arc<CuaClient>, String> {
        if self.shutting_down.load(Ordering::SeqCst) {
            return Err("cua_device_stopping".into());
        }
        if let Some(client) = self.client.get() {
            return Ok(client.clone());
        }
        let path = helper_path().ok_or("cua_helper_unavailable")?;
        let client = Arc::new(CuaClient::builder().helper_path(path).build());
        let _ = self.client.set(client);
        let client = self.client.get().expect("client initialized").clone();
        if self.shutting_down.load(Ordering::SeqCst) {
            client.begin_shutdown();
            return Err("cua_device_stopping".into());
        }
        Ok(client)
    }

    pub(super) fn invalidate_run(&self, run_id: &str) -> Vec<String> {
        self.local_controls
            .lock()
            .expect("local control receipts")
            .retain(|_, receipt| !receipt.belongs_to_run(run_id));
        let sessions = self.sessions.lock().expect("computer-use sessions");
        sessions
            .iter()
            .filter(|(_, session)| session.context.run_id == run_id)
            .map(|(id, session)| {
                session.stopped.store(true, Ordering::SeqCst);
                self.locked_use.invalidate(id);
                id.clone()
            })
            .collect()
    }

    /// Revoke continuity without destroying a suspended REPL/HITL session.
    pub(super) async fn release_locked_run(
        &self,
        state: &LocalRuntimeState,
        run_id: &str,
        reason: &str,
    ) {
        let sessions: Vec<_> = self
            .sessions
            .lock()
            .expect("computer-use sessions")
            .values()
            .filter(|session| session.context.run_id == run_id)
            .cloned()
            .collect();
        // Revoke every binding before performing any native I/O.
        let releases: Vec<_> = sessions
            .into_iter()
            .filter_map(|session| {
                self.locked_use
                    .invalidate(&session.context.session_id)
                    .map(|generation| (session, generation))
            })
            .collect();
        for (session, generation) in releases {
            locked_use::release(state, &session, &generation, reason).await;
        }
    }

    pub(super) async fn stop_run(&self, state: &LocalRuntimeState, run_id: &str) {
        for id in self.invalidate_run(run_id) {
            self.close_session(state, &id).await;
        }
    }

    async fn stop_owner(&self, state: &LocalRuntimeState, owner: &Owner, reason: &str) {
        let ids: Vec<_> = self
            .sessions
            .lock()
            .expect("computer-use sessions")
            .iter()
            .filter(|(_, session)| session.owner == *owner)
            .map(|(id, session)| {
                session.stopped.store(true, Ordering::SeqCst);
                id.clone()
            })
            .collect();
        for id in ids {
            self.close_session_with_reason(state, &id, reason).await;
        }
    }

    pub(super) async fn stop_conversation(&self, state: &LocalRuntimeState, conversation_id: &str) {
        let ids: Vec<_> = self
            .sessions
            .lock()
            .expect("computer-use sessions")
            .iter()
            .filter(|(_, session)| session.context.conversation_id == conversation_id)
            .map(|(id, session)| {
                session.stopped.store(true, Ordering::SeqCst);
                id.clone()
            })
            .collect();
        for id in ids {
            self.close_session(state, &id).await;
        }
    }

    /// Explicit Stop revokes the run; expiry and transport cleanup only close resources.
    async fn user_stop(
        &self,
        state: &LocalRuntimeState,
        owner: &Owner,
        id: Option<&str>,
    ) -> Result<(), String> {
        let (ids, runs) = {
            let sessions = self.sessions.lock().expect("computer-use sessions");
            let runs: BTreeSet<_> = sessions
                .values()
                .filter(|session| {
                    session.owner == *owner && id.is_none_or(|id| id == session.context.session_id)
                })
                .map(|session| session.context.run_id.clone())
                .collect();
            self.stopped_cloud_runs
                .lock()
                .expect("stopped cloud runs")
                .extend(runs.iter().map(|run| (owner.clone(), run.clone())));
            let ids = sessions
                .values()
                .filter(|session| {
                    session.owner == *owner
                        && (id.is_none_or(|id| id == session.context.session_id)
                            || (session.cloud.is_some() && runs.contains(&session.context.run_id)))
                })
                .map(|session| {
                    session.user_control.stop();
                    session.stopped.store(true, Ordering::SeqCst);
                    session.context.session_id.clone()
                })
                .collect::<Vec<_>>();
            (ids, runs)
        };
        let persisted = state.session_store.connection().and_then(|db| {
            for run in runs {
                user_control::persist_stop(&db, owner, &run)?;
            }
            Ok(())
        });
        // The in-memory fence remains effective even if persistence fails.
        for id in ids {
            self.close_session_with_reason(state, &id, "user_stopped")
                .await;
        }
        persisted
    }

    async fn close_session(&self, state: &LocalRuntimeState, id: &str) {
        self.close_session_with_reason(state, id, "session_ended")
            .await;
    }

    async fn close_session_with_reason(&self, state: &LocalRuntimeState, id: &str, reason: &str) {
        let (session, last) = {
            let mut sessions = self.sessions.lock().expect("computer-use sessions");
            let session = sessions.remove(id);
            let last = session.is_some() && sessions.is_empty();
            if last {
                self.helper_closing.store(true, Ordering::SeqCst);
            }
            (session, last)
        };
        if let Some(session) = session {
            input::terminal(self, id, reason);
            session.stopped.store(true, Ordering::SeqCst);
            self.locked_use.invalidate(id);
            self.locked_use.forget_display(id);
            presentation::update(&session, "stopped", None);
            presentation::record(state, &session);
            session.resources.invalidate();
            let pending_ids: Vec<_> = self
                .pending_for(&session.owner)
                .into_iter()
                .filter(|pending| pending.session_id == id)
                .map(|pending| pending.request_id)
                .collect();
            self.pending
                .lock()
                .expect("computer-use consent")
                .retain(|_, pending| pending.session_id != id);
            if let Ok(db) = state.session_store.connection() {
                let _ = store::end_session(&db, &session.owner, id);
            }
            if let Ok(db) = state.session_store.connection() {
                for id in pending_ids {
                    let _ = store::remove_pending(&db, &session.owner, &id);
                }
            }
            if let Some(client) = self.client.get() {
                // The native stop path preempts input and seals audio before any
                // export lock or reset/resume teardown may delay durable copying.
                let _ = client.stop_session_with_reason(id, reason).await;
                let _resources = session.resources.gate.lock().await;
                recordings::refresh_session(state, &session).await;
                let _ = client.end_session(id).await;
                if last && !recordings::has_pending(state, &session.owner) {
                    client.shutdown().await;
                }
            }
        }
        if last {
            self.helper_closing.store(false, Ordering::SeqCst);
        }
    }

    pub(super) fn begin_shutdown(&self) {
        self.shutting_down.store(true, Ordering::SeqCst);
        if let Some(client) = self.client.get() {
            client.begin_shutdown();
        }
    }

    pub(super) async fn shutdown(&self, state: &LocalRuntimeState) {
        let _shutdown = self.shutdown_gate.lock().await;
        for session in self
            .sessions
            .lock()
            .expect("computer-use sessions")
            .values()
        {
            session.stopped.store(true, Ordering::SeqCst);
        }
        let ids: Vec<_> = self
            .sessions
            .lock()
            .expect("computer-use sessions")
            .keys()
            .cloned()
            .collect();
        if let Some(client) = self.client.get() {
            client.stop_all_sessions("session_ended").await;
        }
        for id in ids {
            self.close_session(state, &id).await;
        }
        self.pending.lock().expect("computer-use consent").clear();
        if let Some(client) = self.client.get() {
            client.shutdown().await;
        }
    }

    fn pending_for(&self, owner: &Owner) -> Vec<PendingConsent> {
        self.pending
            .lock()
            .expect("computer-use consent")
            .values()
            .filter(|pending| pending.owner == *owner)
            .cloned()
            .collect()
    }

    fn sessions_for(&self, owner: &Owner) -> Vec<Value> {
        self.sessions.lock().expect("computer-use sessions").iter().filter(|(_, session)| session.owner == *owner)
            .map(|(id, session)| json!({"session_id":id,"run_id":session.context.run_id,
                "conversation_id":session.context.conversation_id,"input_mode":session.context.input_mode,"input_generation":self.client.get().and_then(|client|client.current_input_generation(id)),"stopped":session.stopped.load(Ordering::SeqCst),
                "presentation":session.presentation.lock().ok().map(|p|p.clone()).unwrap_or(Value::Null)})).collect()
    }
}

fn helper_path() -> Option<PathBuf> {
    #[cfg(debug_assertions)]
    if let Some(path) = std::env::var_os("MEMSTACK_CUA_HELPER_PATH")
        .map(PathBuf::from)
        .filter(|path| path.is_file())
    {
        return Some(path);
    }
    let exe = std::env::current_exe().ok()?;
    let name = if cfg!(target_os = "macos") {
        "Memstack Computer Use.app/Contents/MacOS/cua-helper"
    } else if cfg!(windows) {
        "cua-helper.exe"
    } else {
        "cua-helper"
    };
    let path = exe.parent()?.join(name);
    path.is_file().then_some(path)
}

pub(super) fn tool_host(
    state: &Arc<LocalRuntimeState>,
    conversation: &LocalConversation,
    run: Option<&DesktopRun>,
) -> Option<Arc<dyn ToolHost>> {
    let native = PluginNativeIdentityV2::capture(state, conversation, run)?;
    let owner = Owner {
        user_id: native.auth().user.user_id.clone(),
        tenant_id: conversation.tenant_id.clone(),
        project_id: conversation.project_id.clone(),
        device_id: state.session_store.installation_id().into(),
    };
    let instance = store::instance(&*state.session_store.connection().ok()?, &owner).ok()?;
    if !instance.installed || !instance.enabled {
        return None;
    }
    let run_id = run
        .map(|run| run.id.as_str())
        .unwrap_or(native.message_id())
        .to_string();
    if denials::ensure(&*state.session_store.connection().ok()?, &owner, &run_id).is_err() {
        return Some(Arc::new(denials::DeniedHost));
    }
    if user_control::stopped(state, &owner, &run_id).ok()? {
        return Some(Arc::new(user_control::StoppedHost));
    }
    let generation = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .ok()?;
    generation
        .resolve_service::<module::ComputerUseFactoryV2>(
            module::SERVICE,
            module::VERSION,
            &ScopeV2 {
                kind: ScopeKindV2::Project,
                tenant_id: Some(owner.tenant_id.clone()),
                project_id: Some(owner.project_id.clone()),
                session_id: None,
            },
            None,
        )
        .ok()?;
    let client = state.computer_use.client().ok()?;
    presentation::listen(state, &client);
    let mut sessions = state
        .computer_use
        .sessions
        .lock()
        .expect("computer-use sessions");
    if state.computer_use.shutting_down.load(Ordering::SeqCst)
        || state.computer_use.helper_closing.load(Ordering::SeqCst)
    {
        return None;
    }
    let existing = sessions
        .values()
        .find(|session| {
            session.owner == owner
                && session.child.is_none()
                && session.cloud.is_none()
                && session.context.run_id == run_id
                && session.context.conversation_id == conversation.id
                && session.revision == instance.revision
                && !session.stopped.load(Ordering::SeqCst)
        })
        .cloned();
    if let Some(session) = existing {
        return Some(Arc::new(ScopedComputerUseHost {
            state: Arc::downgrade(state),
            native: NativeIdentity::Local(native),
            session: session.clone(),
            client: client.clone(),
            inner: Arc::new(CuaToolHost::new(client).with_context(session.context.clone())),
        }));
    }
    let session_id = format!("cua-{}", Uuid::new_v4());
    let context = CuaCallContext {
        user_id: owner.user_id.clone(),
        tenant_id: owner.tenant_id.clone(),
        project_id: owner.project_id.clone(),
        device_id: owner.device_id.clone(),
        conversation_id: conversation.id.clone(),
        run_id,
        session_id: session_id.clone(),
        input_mode: instance.input_mode,
    };
    let session = Arc::new(Session {
        resources: Default::default(),
        dispatch: tokio::sync::Mutex::new(()),
        owner,
        context: context.clone(),
        revision: instance.revision,
        stopped: AtomicBool::new(false),
        paused: AtomicBool::new(false),
        user_control: Default::default(),
        presentation: Mutex::new(json!({"phase":"idle","can_resume":false})),
        child: None,
        cloud: None,
    });
    sessions.insert(session_id, session.clone());
    Some(Arc::new(ScopedComputerUseHost {
        state: Arc::downgrade(state),
        native: NativeIdentity::Local(native),
        session,
        client: client.clone(),
        inner: Arc::new(CuaToolHost::new(client).with_context(context)),
    }))
}
