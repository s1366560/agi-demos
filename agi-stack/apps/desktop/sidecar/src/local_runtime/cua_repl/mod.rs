//! Persistent JavaScript cells; every device operation re-enters run authorization.
#[cfg(all(test, target_os = "macos"))]
mod authority_revocation_tests;
#[cfg(all(test, target_os = "macos"))]
mod child_tests;
mod config;
mod external;
mod kernel;
mod local_authority;
mod media;
mod process;
mod runtime;
mod sandbox;
#[cfg(all(test, target_os = "macos"))]
pub(super) mod test_support;
pub(crate) use external::ExternalDispatch;
pub(crate) use runtime::ReplRuntime;

use super::{
    agent_boundary_v2::AgentBoundaryV2,
    authority_store::DesktopRun,
    computer_use_v2::call_identity,
    execution_authority::{ExecutionAuthority, ExecutionScope},
    execution_profile::ExecutionProfile,
    LocalConversation, LocalRuntimeState,
};
use agistack_core::ports::{CoreError, CoreResult, ToolDefinition, ToolHost, ToolResult};
use async_trait::async_trait;
use serde_json::{json, Value};
use std::sync::{Arc, Mutex, Weak};

pub(super) const TOOLS: [&str; 3] = ["cua_repl_js", "cua_repl_reset", "cua_repl_add_module_dir"];
struct ReplToolHost {
    inner: Arc<dyn ToolHost>,
    state: Weak<LocalRuntimeState>,
    authority: Arc<ExecutionAuthority>,
    local: Arc<local_authority::LocalExecution>,
    child_authority: Mutex<Option<Arc<ExecutionAuthority>>>,
    native: Option<super::knowledge_authority_v2::agent_access::PluginNativeIdentityV2>,
    run: DesktopRun,
    exposed: Vec<String>,
}

pub(super) fn wrap_tools(
    state: &Arc<LocalRuntimeState>,
    inner: Arc<dyn ToolHost>,
    conversation: &LocalConversation,
    run: &DesktopRun,
    profile: &ExecutionProfile,
    boundary: Option<Arc<AgentBoundaryV2>>,
) -> Arc<dyn ToolHost> {
    let local = Arc::new(local_authority::LocalExecution {
        state: Arc::downgrade(state),
        owner: super::knowledge_authority_v2::agent_access::current_auth(),
        scope: ExecutionScope {
            tenant_id: conversation.tenant_id.clone(),
            project_id: conversation.project_id.clone(),
            conversation_id: conversation.id.clone(),
            run_id: run.id.clone(),
            run_revision: run.revision,
            // Actual engine identity is supplied by call_identity at each dispatch.
            engine_session_id: String::new(),
            device_id: None,
            connection_epoch: None,
            generation: boundary
                .as_ref()
                .map_or(0, |boundary| boundary.generation()),
        },
        run: run.clone(),
        conversation: conversation.clone(),
        tools: inner.clone(),
        boundary,
        allowed_servers: profile.allowed_mcp_servers.clone(),
        allowed_tools: profile.allowed_tools.clone(),
        agent_id: profile.agent.id.clone(),
        subagent_id: profile
            .subagent
            .as_ref()
            .map(|subagent| subagent.id.clone()),
        child: None,
    });
    let authority = Arc::new(ExecutionAuthority::LocalRun(local.clone()));
    if local.subagent_id.is_none() {
        state
            .mcp_app_automation
            .register_authority(authority.clone());
    }
    let exposed = TOOLS
        .iter()
        .filter(|tool| {
            profile
                .allowed_tools
                .iter()
                .any(|allowed| allowed == "*" || allowed == *tool)
        })
        .map(|tool| (*tool).into())
        .collect();
    Arc::new(ReplToolHost {
        inner,
        state: Arc::downgrade(state),
        authority,
        local,
        child_authority: Mutex::new(None),
        native: super::knowledge_authority_v2::agent_access::PluginNativeIdentityV2::capture(
            state,
            conversation,
            Some(run),
        ),
        run: run.clone(),
        exposed,
    })
}

#[async_trait]
impl ToolHost for ReplToolHost {
    fn list_tools(&self) -> Vec<String> {
        let mut tools = self.inner.list_tools();
        tools.extend(self.exposed.clone());
        tools
    }
    fn can_dispatch(&self, name: &str) -> bool {
        self.exposed.iter().any(|tool| tool == name) || self.inner.can_dispatch(name)
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        if !self.exposed.iter().any(|tool| tool == name) {
            return self.inner.tool_definition(name);
        }
        definition(name)
    }
    async fn call(&self, name: &str, input: &str) -> CoreResult<String> {
        self.call_with_content(name, input)
            .await
            .map(|result| result.output_json)
    }
    async fn call_with_content(&self, name: &str, input: &str) -> CoreResult<ToolResult> {
        let authority = if self.local.subagent_id.is_some() {
            let child = super::local_plugin_tool_host_v2::identity::current_child()
                .ok_or_else(|| CoreError::Tool("repl_child_identity_required".into()))?;
            let authority = Arc::new(ExecutionAuthority::LocalRun(Arc::new(
                self.local.bind_child(child)?,
            )));
            let state = self
                .state
                .upgrade()
                .ok_or_else(|| CoreError::Tool("repl_runtime_stopped".into()))?;
            state
                .mcp_app_automation
                .register_authority(authority.clone());
            *self.child_authority.lock().expect("child REPL authority") = Some(authority.clone());
            authority
        } else {
            self.authority.clone()
        };
        if !TOOLS.contains(&name) {
            return self.inner.call_with_content(name, input).await;
        }
        if !self.exposed.iter().any(|tool| tool == name) {
            return Err(CoreError::Tool("repl_tool_not_allowed".into()));
        }
        let state = self
            .state
            .upgrade()
            .ok_or_else(|| CoreError::Tool("repl_runtime_stopped".into()))?;
        let environment = self
            .run
            .environment
            .as_ref()
            .ok_or_else(|| CoreError::Tool("repl_workspace_required".into()))?;
        let mut result = execute_authorized(
            &state,
            authority.clone(),
            name,
            input,
            std::path::Path::new(&environment.workspace_path),
            self.run.permission_profile,
        )
        .await?;
        if !result.media.is_empty() {
            authority.current()?;
            let native = self
                .native
                .as_ref()
                .ok_or_else(|| CoreError::Tool("repl_artifact_identity_required".into()))?;
            super::computer_use_v2::repl_media::persist_local(
                &state,
                native,
                authority.scope(),
                &mut result,
            )
            .await?;
        }
        Ok(result)
    }
}

pub(super) fn definition(name: &str) -> Option<ToolDefinition> {
    if !TOOLS.contains(&name) {
        return None;
    }
    let (description, mut schema) = match name {
            "cua_repl_js" => ("Execute JavaScript in a persistent, OS-sandboxed Node session with cua and nodeRepl. First call exactly one cua entrypoint; read its documentation before continuing. Supports top-level await, imports, images/audio and managed processes. All browser/native operations use the current run's exact permissions. On permission-required, request the returned approval and resume with identical code: completed steps are never replayed. Native user pause retains the cell; explicit same-code continuation rejects the interrupted operation without retrying it. Reset abandons a paused cell.", json!({"type":"object","properties":{"code":{"type":"string"},"title":{"type":"string"},"timeout_ms":{"type":"integer","minimum":1,"maximum":300000}},"required":["code"],"additionalProperties":false})),
            "cua_repl_reset" => ("Destroy the current Node process, variables and module cache. Keep registered module directories and existing apps/tabs.", json!({"type":"object","properties":{},"additionalProperties":false})),
            _ => ("Register a canonical absolute module directory. Restarts the interpreter to apply the OS sandbox read grant; existing variables are cleared.", json!({"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":false})),
        };
    // Static presentation metadata travels with the registered tool schema.
    schema["x-agistack-display-kind"] = json!("repl_output");
    Some(ToolDefinition::new(name, description, schema))
}

pub(super) async fn execute_authorized(
    state: &Arc<LocalRuntimeState>,
    authority: Arc<ExecutionAuthority>,
    name: &str,
    input: &str,
    workspace: &std::path::Path,
    profile: super::authority_store::DesktopPermissionProfile,
) -> CoreResult<ToolResult> {
    if !TOOLS.contains(&name) {
        return Err(CoreError::Tool("repl_tool_unknown".into()));
    }
    let identity = call_identity::active()?;
    let input: Value =
        serde_json::from_str(input).map_err(|_| CoreError::Tool("repl_invalid_input".into()))?;
    let scope = authority.scope();
    let child =
        super::local_plugin_tool_host_v2::identity::current_child().map(|child| child.execution_id);
    let key = json!([
        child,
        scope.tenant_id,
        scope.project_id,
        scope.conversation_id,
        scope.device_id,
        scope.connection_epoch,
        scope.generation,
        profile,
        workspace
    ])
    .to_string();
    state
        .mcp_app_automation
        .register_authority(authority.clone());
    let result = state
        .cua_repl
        .execute(key, authority.clone(), identity.clone(), name, input, || {
            config::RuntimeConfig::for_run(state, workspace, profile)
        })
        .await;
    if result.is_ok() && (name == "cua_repl_reset" || name == "cua_repl_add_module_dir") {
        state.mcp_app_automation.reset_execution(authority.scope(), identity.engine_session_id());
    }
    result
}

pub(super) fn permission_for_request(
    runtime: &ReplRuntime,
    conversation: &str,
    run: Option<&str>,
    engine: Option<&str>,
    kind: agistack_core::agent::types::HitlKind,
    decision: Option<&agistack_core::agent::types::DecisionContext>,
) -> Result<Option<(String, String)>, String> {
    let Some(decision) = decision.filter(|decision| decision.target.kind == "repl_step") else {
        return Ok(None);
    };
    if kind != agistack_core::agent::types::HitlKind::Permission || !decision.is_complete() {
        return Err("repl_step_permission_context_required".into());
    }
    let run = run.ok_or("repl_step_permission_run_required")?;
    let key = runtime
        .pending_permission_key(
            conversation,
            run,
            engine,
            &decision.target.id,
            &decision.action.name,
        )
        .ok_or("repl_step_permission_expired_or_mismatched")?;
    Ok(Some((run.into(), key)))
}
