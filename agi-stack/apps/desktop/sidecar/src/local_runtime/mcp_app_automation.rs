//! Opaque MCP App surfaces bound to the host's live execution authority.
use std::{
    collections::{BTreeSet, HashMap, VecDeque},
    sync::{Arc, Mutex, Weak},
};

use agistack_core::ports::{CoreError, CoreResult};
use serde_json::{json, Value};

use super::{
    computer_use_v2::call_identity::{self, CallIdentity},
    execution_authority::{ExecutionAuthority, ExecutionScope},
    local_plugin_tool_host_v2::identity::{current_child, ChildIdentityV2},
    mcp_supervisor::{McpAppDefinition, McpToolBinding},
    LocalRuntimeService, LocalRuntimeState,
};
#[cfg(test)]
use super::mcp_supervisor::McpScope;
mod callback;
mod callback_origin;
mod continuation;
mod generic_permission;
mod host;
mod mount;
pub(super) use callback_origin::is_callback_result;
pub(crate) use host::wrap_tools;
#[cfg(test)]
mod callback_lifecycle_tests;
#[cfg(test)]
mod tests;

#[derive(Default)]
pub(crate) struct McpAppAutomationRegistry {
    authorities: Mutex<HashMap<(String, String), Weak<ExecutionAuthority>>>,
    tabs: Mutex<HashMap<String, AppTab>>,
    cloud_authorities: Mutex<VecDeque<Arc<ExecutionAuthority>>>,
}

#[derive(Clone)]
struct AppTab {
    scope: ExecutionScope,
    /// Captured from the host authority variant; never inferred from scope shape.
    local_origin: bool,
    /// Only host-committed permission continuations can extend this lineage.
    continuation_revisions: BTreeSet<u64>,
    app: McpAppDefinition,
    binding: McpToolBinding,
    attached: bool,
    mount_nonce: Option<String>,
    mount_cancelled: bool,
    cancelled_mounts: BTreeSet<String>,
    /// A browser handle identifies one attachment, never the reusable renderer slot.
    registration: Option<String>,
    identity: CallIdentity,
    child: Option<ChildIdentityV2>,
}

fn denied(reason: &str) -> CoreError {
    CoreError::Tool(reason.into())
}
#[cfg(test)]
fn mcp_scope(scope: &ExecutionScope) -> McpScope {
    McpScope {
        tenant_id: scope.tenant_id.clone(),
        project_id: scope.project_id.clone(),
    }
}

impl McpAppAutomationRegistry {
    pub(super) fn revoke_run(&self, run_id: &str) {
        self.authorities.lock().expect("MCP app authorities")
            .retain(|(owner, _), _| owner != run_id);
        self.tabs.lock().expect("MCP app tabs")
            .retain(|_, tab| tab.scope.run_id != run_id);
        self.cloud_authorities.lock().expect("MCP app cloud authorities")
            .retain(|authority| authority.scope().run_id != run_id);
    }

    pub(crate) fn register_authority(&self, authority: Arc<ExecutionAuthority>) {
        let mut authorities = self.authorities.lock().expect("MCP app authorities");
        authorities.retain(|_, value| value.strong_count() > 0);
        authorities.insert(
            (
                authority.scope().run_id.clone(),
                authority.scope().engine_session_id.clone(),
            ),
            Arc::downgrade(&authority),
        );
        if matches!(&*authority, ExecutionAuthority::CloudClaim(_)) {
            let mut retained = self
                .cloud_authorities
                .lock()
                .expect("MCP app cloud authorities");
            retained.retain(|prior| {
                prior.current().is_ok()
                    && (prior.scope().run_id != authority.scope().run_id
                        || prior.scope().engine_session_id != authority.scope().engine_session_id)
            });
            while retained.len() >= 64 {
                retained.pop_front();
            }
            retained.push_back(authority);
        }
    }

    fn registered(&self, run_id: &str, engine: &str) -> Option<Arc<ExecutionAuthority>> {
        let authorities = self.authorities.lock().ok()?;
        authorities
            .get(&(run_id.to_string(), engine.to_string()))
            .and_then(Weak::upgrade)
            .or_else(|| {
                authorities
                    .get(&(run_id.to_string(), String::new()))
                    .and_then(Weak::upgrade)
            })
    }

    /// Called only while publishing a host-resolved MCP App result.
    pub(super) fn open(
        &self,
        state: &LocalRuntimeState,
        run_id: &str,
        conversation_id: &str,
        app: &McpAppDefinition,
    ) -> CoreResult<String> {
        let identity = call_identity::active()?;
        let child = current_child();
        let authority = self
            .registered(run_id, identity.engine_session_id())
            .ok_or_else(|| denied("mcp_app_execution_unavailable"))?;
        authority.current()?;
        let scope = authority.scope();
        if (!scope.engine_session_id.is_empty()
            && scope.engine_session_id != identity.engine_session_id())
            || (child.is_some() && scope.engine_session_id != identity.engine_session_id())
        {
            return Err(denied("mcp_app_child_authority_unregistered"));
        }
        if scope.conversation_id != conversation_id {
            return Err(denied("mcp_app_scope_mismatch"));
        }
        let server = state
            .mcp_supervisor
            .server(&authority.mcp_scope(), &app.server_id)
            .map_err(|error| denied(error.reason_code()))?
            .ok_or_else(|| denied("mcp_app_server_missing"))?;
        if !authority
            .allowed_mcp_servers()
            .iter()
            .any(|id| id == "*" || id == &server.id || id == &server.name)
        {
            return Err(denied("mcp_app_server_forbidden"));
        }
        let binding = state
            .mcp_supervisor
            .resolve_tool(&authority.mcp_scope(), &app.server_id, &app.tool_name)
            .map_err(|error| denied(error.reason_code()))?;
        let id = format!("mcpapp-{}", uuid::Uuid::new_v4());
        let mut tabs = self.tabs.lock().expect("MCP app tabs");
        tabs.retain(|_, tab| {
            self.registered(&tab.scope.run_id, &tab.scope.engine_session_id)
                .is_some_and(|authority| {
                    authority.scope() == &tab.scope && authority.current().is_ok()
                })
        });
        tabs.insert(
            id.clone(),
            AppTab {
                scope: scope.clone(),
                local_origin: matches!(&*authority, ExecutionAuthority::LocalRun(_)),
                continuation_revisions: BTreeSet::new(),
                app: app.clone(),
                binding,
                attached: false,
                mount_nonce: None,
                mount_cancelled: false,
                cancelled_mounts: BTreeSet::new(),
                registration: None,
                identity,
                child,
            },
        );
        Ok(id)
    }

    fn require(
        &self,
        state: &LocalRuntimeState,
        id: &str,
        requester: Option<&ExecutionScope>,
    ) -> CoreResult<(AppTab, Arc<ExecutionAuthority>)> {
        let tab = self
            .tabs
            .lock()
            .expect("MCP app tabs")
            .get(id)
            .cloned()
            .ok_or_else(|| denied("mcp_app_frame_expired"))?;
        let authority = self
            .registered(&tab.scope.run_id, &tab.scope.engine_session_id)
            .ok_or_else(|| denied("mcp_app_execution_unavailable"))?;
        authority.current()?;
        if let Some(child) = &tab.child {
            let run = state
                .session_store
                .run(&child.run_id)
                .map_err(CoreError::Storage)?
                .ok_or_else(|| denied("mcp_app_child_authority_revoked"))?;
            if child.run_id != tab.scope.run_id
                || child.revision != tab.scope.run_revision
                || child.execution_id != tab.identity.engine_session_id()
                || !state.subagent_controls.plugin_execution_current(
                    &child.execution_id,
                    &tab.scope.conversation_id,
                    &run,
                    &child.subagent_id,
                    state.control_for_run(&run).as_ref(),
                )
            {
                return Err(denied("mcp_app_child_authority_revoked"));
            }
        }
        if authority.scope() != &tab.scope || requester.is_some_and(|scope| scope != &tab.scope) {
            return Err(denied("mcp_app_scope_mismatch"));
        }
        let scope = authority.mcp_scope();
        let binding = state
            .mcp_supervisor
            .resolve_tool(&scope, &tab.app.server_id, &tab.app.tool_name)
            .map_err(|error| denied(error.reason_code()))?;
        if binding.server_revision != tab.binding.server_revision
            || binding.catalog_digest != tab.binding.catalog_digest
        {
            return Err(denied("mcp_app_catalog_changed"));
        }
        let server = state
            .mcp_supervisor
            .server(&scope, &tab.app.server_id)
            .map_err(|error| denied(error.reason_code()))?
            .ok_or_else(|| denied("mcp_app_server_missing"))?;
        if !authority
            .allowed_mcp_servers()
            .iter()
            .any(|id| id == "*" || id == &server.id || id == &server.name)
        {
            return Err(denied("mcp_app_server_forbidden"));
        }
        Ok((tab, authority))
    }

    fn require_browser(
        &self,
        state: &LocalRuntimeState,
        handle: &str,
        scope: &ExecutionScope,
    ) -> CoreResult<(String, AppTab)> {
        let renderer_id = self
            .tabs
            .lock()
            .expect("MCP app tabs")
            .iter()
            .find(|(_, tab)| tab.registration.as_deref() == Some(handle))
            .map(|(id, _)| id.clone())
            .ok_or_else(|| denied("mcp_app_frame_expired"))?;
        let (tab, _) = self.require(state, &renderer_id, Some(scope))?;
        if !tab.attached || tab.registration.as_deref() != Some(handle) {
            return Err(denied("mcp_app_frame_expired"));
        }
        Ok((renderer_id, tab))
    }

    pub(crate) fn list(&self, state: &LocalRuntimeState, scope: &ExecutionScope) -> Value {
        let ids: Vec<String> = self
            .tabs
            .lock()
            .expect("MCP app tabs")
            .iter()
            .filter(|(_, tab)| tab.attached && &tab.scope == scope)
            .map(|(id, _)| id.clone())
            .collect();
        json!(ids.into_iter().filter_map(|id| self.require(state, &id, Some(scope)).ok().and_then(|(tab, _)| {
            let handle = tab.attached.then_some(tab.registration).flatten()?;
            Some(json!({"id":handle,"tabId":handle,"providerTabId":handle,"browserId":"mcpapps","title":tab.app.tool_name,"url":tab.app.resource_uri}))
        })).collect::<Vec<_>>())
    }

    /// Browser policy admission happens before this method; scope is supplied by the host.
    pub(crate) async fn browser_operation(
        &self,
        state: &LocalRuntimeState,
        authority: &ExecutionAuthority,
        id: &str,
        operation: &str,
        args: Value,
    ) -> CoreResult<Value> {
        let (renderer_id, tab) = self.require_browser(state, id, authority.scope())?;
        match operation {
            "tab.claim" => {
                return Ok(
                    json!({"id":id,"tabId":id,"providerTabId":id,"browserId":"mcpapps","title":tab.app.tool_name,"url":tab.app.resource_uri}),
                )
            }
            "tab.title" => return Ok(json!(tab.app.tool_name)),
            "tab.url" => return Ok(json!(tab.app.resource_uri)),
            "capabilities.list" => return Ok(json!([])),
            "playwright.domSnapshot"
            | "playwright.locator"
            | "playwright.evaluate"
            | "playwright.elementInfo"
            | "tab.screenshot" => {}
            _ => return Err(denied("mcp_app_operation_unsupported")),
        }
        let expression = if operation == "tab.screenshot" {
            None
        } else {
            Some(agistack_adapters_browser::facade::dom_expression(
                operation, &args,
            )?)
        };
        let bridge = state
            .browser_bridge
            .lock()
            .expect("browser bridge runtime")
            .as_ref()
            .map(|runtime| runtime.server())
            .ok_or_else(|| denied("mcp_app_frame_unavailable"))?;
        let output = bridge
            .request_on(
                "iab",
                "mcpAppsExecute",
                json!({"tabId":renderer_id,"mountNonce":tab.mount_nonce,
                    "operation":operation,"expression":expression}),
            )
            .await?;
        self.require_browser(state, id, authority.scope())
            .map_err(|_| {
                denied("mcp_app_authority_revoked_after_dispatch: outcome may already exist")
            })?;
        Ok(output)
    }

    pub(crate) fn validate_operation_for_run(
        &self,
        state: &LocalRuntimeState,
        run_id: &str,
        input: &Value,
    ) -> CoreResult<()> {
        let identity = call_identity::active()?;
        let authority = self
            .registered(run_id, identity.engine_session_id())
            .ok_or_else(|| denied("mcp_app_execution_unavailable"))?;
        authority.current()?;
        let operation = input["operation"]
            .as_str()
            .ok_or_else(|| denied("mcp_app_operation_required"))?;
        if operation == "tabs.list"
            || (operation == "capabilities.list" && input.get("tabId").is_none())
        {
            return Ok(());
        }
        if !matches!(
            operation,
            "tab.claim"
                | "tab.title"
                | "tab.url"
                | "capabilities.list"
                | "playwright.domSnapshot"
                | "playwright.locator"
                | "playwright.evaluate"
                | "playwright.elementInfo"
                | "tab.screenshot"
        ) {
            return Err(denied("mcp_app_operation_unsupported"));
        }
        let id = input["tabId"]
            .as_str()
            .ok_or_else(|| denied("mcp_app_tab_required"))?;
        self.require_browser(state, id, authority.scope())?;
        Ok(())
    }

    pub(crate) async fn operation_for_run(
        &self,
        state: &LocalRuntimeState,
        run_id: &str,
        input: &Value,
    ) -> CoreResult<Value> {
        let identity = call_identity::active()?;
        let authority = self
            .registered(run_id, identity.engine_session_id())
            .ok_or_else(|| denied("mcp_app_execution_unavailable"))?;
        authority.current()?;
        let operation = input["operation"]
            .as_str()
            .ok_or_else(|| denied("mcp_app_operation_required"))?;
        if operation == "tabs.list" {
            return Ok(json!({"tabs": self.list(state, authority.scope())}));
        }
        if operation == "capabilities.list" && input.get("tabId").is_none() {
            return Ok(json!([]));
        }
        let id = input["tabId"]
            .as_str()
            .ok_or_else(|| denied("mcp_app_tab_required"))?;
        self.browser_operation(
            state,
            &authority,
            id,
            operation,
            input.get("args").cloned().unwrap_or_else(|| json!([])),
        )
        .await
    }

    /// This entry point is reachable only through the Electron private control channel.
    async fn renderer_operation(
        &self,
        state: &Arc<LocalRuntimeState>,
        input: Value,
    ) -> CoreResult<Value> {
        let id = input["tabId"]
            .as_str()
            .ok_or_else(|| denied("mcp_app_tab_required"))?;
        let operation = input["operation"]
            .as_str()
            .ok_or_else(|| denied("mcp_app_operation_required"))?;
        let nonce = input["mountNonce"]
            .as_str()
            .filter(|value| !value.is_empty() && value.len() <= 128)
            .ok_or_else(|| denied("mcp_app_mount_nonce_required"))?;
        if operation == "detach" || operation == "attach" {
            return if operation == "detach" {
                self.cancel_mount(id, nonce)
            } else {
                self.attach_mount(state, id, nonce)
            };
        }
        let (tab, authority) = self.require(state, id, None)?;
        if !tab.attached || tab.mount_nonce.as_deref() != Some(nonce) {
            return Err(denied("mcp_app_frame_unavailable"));
        }
        let scope = authority.mcp_scope();
        let args = &input["arguments"];
        let output = match operation {
            "tools/call" => Box::pin(self.call_tool(state, id, &tab, &authority, args)).await?,
            "resources/list" => {
                json!({"resources":state.mcp_supervisor.list_resources(&scope, Some(&tab.app.server_id)).await.map_err(|error|denied(error.reason_code()))?})
            }
            "resources/templates/list" => {
                json!({"resourceTemplates":state.mcp_supervisor.list_resource_templates(&scope, &tab.app.server_id).await.map_err(|error|denied(error.reason_code()))?})
            }
            "resources/read" => {
                json!({"contents":state.mcp_supervisor.read_resource(&scope, &tab.app.server_id, args["uri"].as_str().ok_or_else(||denied("mcp_app_uri_required"))?).await.map_err(|error|denied(error.reason_code()))?})
            }
            "prompts/list" => {
                json!({"prompts":state.mcp_supervisor.list_prompts(&scope, &tab.app.server_id).await.map_err(|error|denied(error.reason_code()))?})
            }
            "prompts/get" => state
                .mcp_supervisor
                .get_prompt(
                    &scope,
                    &tab.app.server_id,
                    args["name"]
                        .as_str()
                        .ok_or_else(|| denied("mcp_app_prompt_required"))?,
                    args.get("arguments").cloned().unwrap_or_else(|| json!({})),
                )
                .await
                .map_err(|error| denied(error.reason_code()))?,
            _ => return Err(denied("mcp_app_operation_unsupported")),
        };
        let (current, _) = self.require(state, id, None).map_err(|_| {
            denied("mcp_app_authority_revoked_after_dispatch: outcome may already exist")
        })?;
        if !current.attached || current.registration != tab.registration {
            return Err(denied(
                "mcp_app_frame_changed_after_dispatch: outcome may already exist",
            ));
        }
        Ok(output)
    }
}

impl LocalRuntimeService {
    pub(crate) async fn mcp_app_operation(&self, input: Value) -> Result<Value, String> {
        self.state
            .mcp_app_automation
            .renderer_operation(&self.state, input)
            .await
            .map_err(|error| error.to_string())
    }
}
