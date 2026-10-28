//! The selected device executes cells; the server admits every exact inner operation.
use super::*;
use crate::local_runtime::{
    browser_run_tool_host::{BrowserStepAuthority, CloudBrowserToolHost},
    cua_repl,
    execution_authority::{
        current_step_id, current_step_origin, permission_binding, ExecutionAuthority, ExecutionScope,
        ScopedExecution,
    },
    mcp_agent_tool_host::McpAgentToolHost,
    mcp_supervisor::McpScope,
};
use async_trait::async_trait;
use agistack_core::ports::{PermissionKind, PermissionRequired};
use sha2::{Digest, Sha256};
use std::sync::Weak;
#[path = "cloud_continuation.rs"]
mod continuation;

#[derive(Clone)]
struct Admission {
    state: Weak<LocalRuntimeState>,
    claim: Arc<Claim>,
    lease: CloudLease,
}
impl Admission {
    fn current(&self) -> CoreResult<Arc<LocalRuntimeState>> {
        let state = self
            .state
            .upgrade()
            .ok_or_else(|| CoreError::Tool("cua_cloud_runtime_stopped".into()))?;
        if !self.lease.current(&state) {
            return Err(CoreError::Tool("cua_cloud_lease_expired".into()));
        }
        Ok(state)
    }
    async fn authorize(&self, tool: &str, input: &str, target: &Value) -> CoreResult<Permit> {
        self.current()?;
        let step = current_step_id()
            .ok_or_else(|| CoreError::Tool("cua_cloud_step_identity_required".into()))?;
        let origin = current_step_origin()
            .ok_or_else(|| CoreError::Tool("cua_cloud_cell_identity_required".into()))?;
        let body = json!({"device_id":self.claim.device_id,"cell_id":origin.cell_id,"tool_name":tool,"input_json":input,"target":target,
            "parent_request_id":origin.parent_request_id});
        let ready = self.send(&step, &body).await?;
        let expected_digest = format!("{:x}", Sha256::digest(input.as_bytes()));
        if ready["status"] == "pending" && ready["error"] == "cua_permission_required" {
            let request = &ready["request"];
            let code: Value = serde_json::from_str(&self.claim.input_json)
                .map_err(|_| CoreError::Tool("cua_cloud_step_parent_invalid".into()))?;
            let code = code["code"].as_str()
                .ok_or_else(|| CoreError::Tool("cua_cloud_step_parent_invalid".into()))?;
            if ready["scopes"] != json!(["once"])
                || request["capability"] != "execution_step"
                || request["engine_session_id"] != self.claim.session_id
                || request["session_id"] != origin.cell_id
                || request["tool_name"] != tool
                || request["input_digest"] != expected_digest
                || request["app"] != target["id"]
                || request["request_id"].as_str().is_none_or(str::is_empty)
                || request["identity_digest"].as_str().is_none_or(str::is_empty)
                || request["execution_step"]["key"].as_str().is_none_or(str::is_empty)
                || request["execution_step"]["cell_id"] != origin.cell_id
                || request["execution_step"]["step_id"] != step
                || request["execution_step"]["target"] != *target
                || request["execution_step"]["code_digest"] != format!("{:x}", Sha256::digest(code.as_bytes()))
            {
                return Err(CoreError::Tool("cua_cloud_pending_step_invalid".into()));
            }
            return Ok(Permit::Pending(PermissionRequired::new(
                PermissionKind::CloudExecutionStep,
                permission_binding(tool, input)?,
                ready,
            )));
        }
        let receipt = ready["receipt"]
            .as_str()
            .filter(|receipt| !receipt.is_empty())
            .ok_or_else(|| CoreError::Tool("cua_cloud_step_receipt_missing".into()))?;
        if ready["status"] != "ready"
            || ready["step_id"] != step
            || ready["cell_id"] != origin.cell_id
            || ready["input_digest"] != expected_digest
            || ready["authorization_revision"] != self.claim.authorization_revision
            || ready["catalog_digest"].as_str().is_none_or(str::is_empty)
        {
            return Err(CoreError::Tool("cua_cloud_step_receipt_invalid".into()));
        }
        let continuation = continuation::verify(self, &step, &origin, ready.get("continuation"))?;
        let mut consumed = body.clone();
        consumed["receipt"] = json!(receipt);
        let authorized = self.send(&step, &consumed).await?;
        if authorized["status"] != "authorized"
            || authorized["receipt"] != ready["receipt"]
            || authorized["cell_id"] != ready["cell_id"]
            || authorized["step_id"] != ready["step_id"]
            || authorized["input_digest"] != ready["input_digest"]
            || authorized["catalog_digest"] != ready["catalog_digest"]
            || authorized["authorization_revision"] != ready["authorization_revision"]
            || authorized.get("continuation") != ready.get("continuation")
        {
            return Err(CoreError::Tool("cua_cloud_step_consumption_invalid".into()));
        }
        self.current()?;
        Ok(Permit::Authorized {
            step,
            body: consumed,
            continuation,
        })
    }
    async fn send(&self, step: &str, body: &Value) -> CoreResult<Value> {
        self.current()?;
        let transport = transport(&self.lease.broker).map_err(CoreError::Tool)?;
        if transport.epoch != self.lease.epoch {
            return Err(CoreError::Tool("cua_cloud_epoch_changed".into()));
        }
        let mut url = url::Url::parse(&format!("{}/api/v1/agent/device/requests/", transport.base))
            .map_err(|_| CoreError::Tool("cua_cloud_authority_invalid".into()))?;
        url.path_segments_mut()
            .map_err(|_| CoreError::Tool("cua_cloud_authority_invalid".into()))?
            .pop_if_empty()
            .push(&self.claim.request_id)
            .push("steps")
            .push(step)
            .push("authorize");
        let response = transport
            .client
            .post(url)
            .bearer_auth(&transport.credential)
            .json(body)
            .send()
            .await
            .map_err(|_| CoreError::Tool("cua_cloud_step_authority_unavailable".into()))?
            .error_for_status()
            .map_err(|_| CoreError::Tool("cua_cloud_step_authority_rejected".into()))?;
        let result = response
            .json()
            .await
            .map_err(|_| CoreError::Tool("cua_cloud_step_authority_invalid".into()))?;
        self.current()?;
        Ok(result)
    }
    async fn release_not_sent(&self, permit: Permit) -> CoreResult<()> {
        let Permit::Authorized { step, mut body, .. } = permit else {
            return Ok(());
        };
        body["outcome"] = json!("not_sent");
        let result = self.send(&step, &body).await?;
        if result["status"] != "released" {
            return Err(CoreError::Tool("cua_cloud_step_release_rejected".into()));
        }
        Ok(())
    }

    fn native_not_sent(&self, result: &ToolResult, tool: &str, input: &str) -> CoreResult<bool> {
        let Some(permission) = result.permission_required.as_ref() else {
            return Ok(false);
        };
        if result.control_outcome.is_some() || result.control_generation.is_some() || !result.media.is_empty()
            || permission.kind() != PermissionKind::NativeConsent
            || permission.binding() != &permission_binding(tool, input)?
        {
            return Err(CoreError::Tool("cua_cloud_native_permission_binding_invalid".into()));
        }
        Ok(true)
    }
}
#[derive(Debug)]
enum Permit {
    Pending(PermissionRequired),
    Authorized { step: String, body: Value, continuation: Option<ExecutionScope> },
}

#[async_trait]
impl BrowserStepAuthority for Admission {
    fn current(&self) -> CoreResult<()> {
        Admission::current(self).map(|_| ())
    }
    async fn authorize(
        &self,
        tool: &str,
        arguments: &Value,
        target: &Value,
    ) -> CoreResult<Option<PermissionRequired>> {
        match self.authorize(tool, &arguments.to_string(), target).await? {
            Permit::Pending(permission) => Ok(Some(permission)),
            Permit::Authorized { .. } => Ok(None),
        }
    }
}

#[derive(Clone)]
struct CloudExecution {
    admission: Admission,
    scope: ExecutionScope,
    session: Arc<Session>,
    owner: Owner,
    mcp: Arc<McpAgentToolHost>,
    mcp_scope: McpScope,
    browser: Option<Arc<dyn ToolHost>>,
}
#[async_trait]
impl ScopedExecution for CloudExecution {
    fn scope(&self) -> &ExecutionScope {
        &self.scope
    }
    fn request_id(&self) -> Option<&str> {
        Some(&self.admission.claim.request_id)
    }
    fn allowed_mcp_servers(&self) -> Vec<String> {
        self.admission.lease.allowed_mcp_servers.clone()
    }
    fn mcp_scope(&self) -> McpScope {
        self.mcp_scope.clone()
    }
    fn current(&self) -> CoreResult<()> {
        let state = self.admission.current()?;
        if self.session.stopped.load(Ordering::SeqCst) {
            return Err(CoreError::Tool("cua_cloud_session_stopped".into()));
        }
        let instance = store::instance(
            &*state
                .session_store
                .connection()
                .map_err(CoreError::Storage)?,
            &self.owner,
        )
        .map_err(CoreError::Storage)?;
        if !instance.installed || !instance.enabled || instance.revision != self.session.revision {
            return Err(CoreError::Tool("cua_instance_disabled".into()));
        }
        Ok(())
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
        self.current()?;
        if current_step_origin().is_none() {
            let claim = &self.admission.claim;
            if claim.mcp_binding.is_none()
                || claim.tool_name != tool
                || claim.input_json != input
                || !self
                    .admission
                    .lease
                    .permits(tool, agistack_adapters_cua::CuaToolEffect::Mutate)
                || !self.mcp.can_dispatch(tool)
            {
                return Err(CoreError::Tool("cua_cloud_outer_mcp_claim_mismatch".into()));
            }
            let current_binding = self
                .mcp
                .device_tool_definitions()?
                .into_iter()
                .find(|definition| {
                    definition.name == tool
                        && definition
                            .input_schema
                            .as_ref()
                            .is_some_and(|schema| schema["x-cua-step-only"] != true)
                })
                .and_then(|definition| definition.input_schema)
                .and_then(|schema| schema.get("x-cua-mcp-binding").cloned());
            if current_binding != claim.mcp_binding {
                return Err(CoreError::Tool(
                    "cua_cloud_outer_mcp_binding_changed".into(),
                ));
            }
            let result = self.mcp.call_with_content(tool, input).await?;
            self.current()?;
            return Ok(result);
        }
        if [
            agistack_adapters_browser::facade::TOOL_READ,
            agistack_adapters_browser::facade::TOOL_WRITE,
            agistack_adapters_browser::facade::TOOL_CDP,
        ]
        .contains(&tool)
        {
            let arguments: Value = serde_json::from_str(input)
                .map_err(|_| CoreError::Tool("cua_cloud_step_input_invalid".into()))?;
            if agistack_adapters_browser::facade::operation_effect(&arguments)?.tool() != tool {
                return Err(CoreError::Tool("cua_cloud_browser_effect_mismatch".into()));
            }
            if arguments["browserId"] == "mcpapps" {
                let state = self.admission.current()?;
                let target = json!({"kind":"mcp_app","id":arguments.get("tabId").cloned().unwrap_or_else(||json!("mcpapps:inventory"))});
                let permit = self.admission.authorize(tool, input, &target).await?;
                if let Permit::Pending(permission) = permit {
                    return Ok(permission.into_result());
                }
                if let Permit::Authorized { continuation: Some(previous), .. } = &permit {
                    let handle = arguments["tabId"].as_str()
                        .ok_or_else(|| CoreError::Tool("cua_cloud_app_continuation_target_required".into()))?;
                    let authority = ExecutionAuthority::CloudClaim(Arc::new(self.clone()));
                    state.mcp_app_automation.resume_cloud_permission(previous, &authority, handle)?;
                }
                state.mcp_app_automation.validate_operation_for_run(&state, &self.scope.run_id, &arguments)?;
                let result = state
                    .mcp_app_automation
                    .operation_for_run(&state, &self.scope.run_id, &arguments)
                    .await?;
                return Ok(ToolResult::text(result.to_string()));
            }
            let mut result = match self.browser.as_ref() {
                Some(browser) => browser.call_with_content(tool, input).await?,
                None if arguments["operation"] == "browsers.list" => {
                    let target = json!({"kind":"browser","id":"inventory"});
                    if let Permit::Pending(permission) =
                        self.admission.authorize(tool, input, &target).await?
                    {
                        return Ok(permission.into_result());
                    }
                    self.current()?;
                    ToolResult::text("[]")
                }
                None => return Err(CoreError::Tool("cua_browser_unavailable".into())),
            };
            if arguments["operation"] == "browsers.list" {
                let state = self.admission.current()?;
                let mut value: Value = serde_json::from_str(&result.output_json)
                    .map_err(|_| CoreError::Tool("cua_browser_inventory_invalid".into()))?;
                if let Some(browsers) = value.as_array_mut() {
                    if state
                        .mcp_app_automation
                        .list(&state, &self.scope)
                        .as_array()
                        .is_some_and(|tabs| !tabs.is_empty())
                    {
                        browsers.push(json!({"id":"mcpapps","type":"mcpapps","backend":"mcpapps"}));
                    }
                    result.output_json = value.to_string();
                }
            }
            return Ok(result);
        }
        let arguments: Value = serde_json::from_str(input)
            .map_err(|_| CoreError::Tool("cua_cloud_step_input_invalid".into()))?;
        let native = agistack_adapters_cua::tool_effects().contains_key(tool);
        let target = if native {
            json!({"kind":"native","id":json!({"device_id":self.owner.device_id,"app":arguments.get("app")}).to_string()})
        } else if self.mcp.can_dispatch(tool) {
            let definition = self
                .mcp
                .device_tool_definitions()?
                .into_iter()
                .find(|definition| definition.name == tool)
                .ok_or_else(|| CoreError::Tool("cua_cloud_mcp_binding_missing".into()))?;
            json!({"kind":"mcp","id":definition.input_schema.and_then(|schema|schema.get("x-cua-mcp-binding").cloned()).ok_or_else(||CoreError::Tool("cua_cloud_mcp_binding_missing".into()))?.to_string()})
        } else {
            return Err(CoreError::Tool("cua_cloud_step_tool_not_allowed".into()));
        };
        let permit = self.admission.authorize(tool, input, &target).await?;
        if let Permit::Pending(permission) = permit {
            return Ok(permission.into_result());
        }
        let state = self.admission.current()?;
        if !native {
            let authority = ExecutionAuthority::CloudClaim(Arc::new(self.clone()));
            if let Some((captured, handle)) = state.mcp_app_automation.cloud_callback_target(&state, &authority, tool)? {
                if let Permit::Authorized { continuation: Some(previous), .. } = &permit {
                    if &captured != previous {
                        return Err(CoreError::Tool("cua_cloud_callback_continuation_changed".into()));
                    }
                    state.mcp_app_automation.resume_cloud_permission(previous, &authority, &handle)?;
                }
                state.mcp_app_automation.validate_cloud_callback(&state, &authority)?;
            }
        }
        let result = if native {
            let mut lease = self.admission.lease.clone();
            // This exact step has a consumed server receipt; no wildcard grant is introduced.
            lease.approved_tools.insert(tool.into());
            let client = state.computer_use.client().map_err(CoreError::Tool)?;
            let host = ScopedComputerUseHost {
                state: Arc::downgrade(&state),
                native: NativeIdentity::Cloud(lease),
                session: self.session.clone(),
                client: client.clone(),
                inner: Arc::new(
                    CuaToolHost::new(client).with_context(self.session.context.clone()),
                ),
            };
            let identity = call_identity::active()?;
            identity
                .for_tool(tool, host.call_with_content(tool, input))
                .await?
        } else {
            self.mcp.call_with_content(tool, input).await?
        };
        // The native consent protocol explicitly guarantees that this action was not sent.
        if native && self.admission.native_not_sent(&result, tool, input)? {
            self.admission.release_not_sent(permit).await?;
        }
        if result.control_outcome.is_none() {
            self.current()?;
        }
        Ok(result)
    }
}

pub(super) fn catalog(state: &Arc<LocalRuntimeState>, owner: &Owner, broker: &TrustedSessionBroker, epoch: u64) -> Result<Vec<Value>, String> {
    let mut tools = cua_repl::TOOLS
        .iter()
        .filter_map(|tool| cua_repl::definition(tool))
        .collect::<Vec<_>>();
    for mut metadata in agistack_adapters_browser::host::list_tool_metadata() {
        let name = metadata["name"].as_str().unwrap_or_default();
        if ![
            agistack_adapters_browser::facade::TOOL_READ,
            agistack_adapters_browser::facade::TOOL_WRITE,
            agistack_adapters_browser::facade::TOOL_CDP,
        ]
        .contains(&name)
        {
            continue;
        }
        let name = name.to_string();
        metadata["inputSchema"]["x-cua-step-only"] = json!(true);
        tools.push(agistack_core::ports::ToolDefinition {
            name,
            description: metadata["description"].as_str().map(str::to_string),
            input_schema: metadata.get("inputSchema").cloned(),
        });
    }
    let mcp = McpAgentToolHost::new(
        state.mcp_supervisor.clone(),
        crate::local_runtime::device_mcp::claim_scope(broker, epoch, &owner.user_id,
            &owner.tenant_id, &owner.project_id, &owner.device_id)?,
        "device-catalog".into(),
        None,
    )?;
    tools.extend(
        mcp.device_tool_definitions()
            .map_err(|error| error.to_string())?,
    );
    Ok(tools.into_iter().map(|tool|json!({"name":tool.name,"description":tool.description,"inputSchema":tool.input_schema})).collect())
}

pub(super) async fn execute(
    state: &Arc<LocalRuntimeState>,
    owner: &Owner,
    claim: Claim,
    lease: CloudLease,
    session: Arc<Session>,
) -> CoreResult<ToolResult> {
    let workspace = state
        .workspace_root
        .lock()
        .expect("device workspace")
        .clone();
    let profile = match claim.permission_profile.as_str() {
        "read_only" => crate::local_runtime::authority_store::DesktopPermissionProfile::ReadOnly,
        "workspace_write" => {
            crate::local_runtime::authority_store::DesktopPermissionProfile::WorkspaceWrite
        }
        "full_access" => {
            crate::local_runtime::authority_store::DesktopPermissionProfile::FullAccess
        }
        _ => return Err(CoreError::Tool("cua_cloud_profile_invalid".into())),
    };
    let scope = ExecutionScope {
        tenant_id: claim.tenant_id.clone(),
        project_id: claim.project_id.clone(),
        conversation_id: claim.conversation_id.clone(),
        run_id: claim.run_id.clone(),
        run_revision: claim.authorization_revision,
        engine_session_id: claim.session_id.clone(),
        device_id: Some(owner.device_id.clone()),
        connection_epoch: Some(lease.epoch),
        generation: lease.factory.descriptor().generation,
    };
    let claim = Arc::new(claim);
    let admission = Admission {
        state: Arc::downgrade(state),
        claim: claim.clone(),
        lease,
    };
    let mcp_scope = crate::local_runtime::device_mcp::claim_scope(
        &admission.lease.broker, admission.lease.epoch, &owner.user_id,
        &owner.tenant_id, &owner.project_id, &owner.device_id,
    ).map_err(CoreError::Tool)?;
    let mcp = Arc::new(
        McpAgentToolHost::new(
            state.mcp_supervisor.clone(),
            mcp_scope.clone(),
            claim.run_id.clone(),
            Some(&admission.lease.allowed_mcp_servers),
        )
        .map_err(CoreError::Tool)?
        .with_app_events(
            state.clone(),
            claim.conversation_id.clone(),
            claim.request_id.clone(),
        )
        .with_app_project(claim.project_id.clone()),
    );
    let browser = state.connected_browser_tool_host().map(|inner| {
        let full_cdp = state
            .config
            .lock()
            .expect("device config")
            .browser_bridge
            .full_cdp_access_enabled;
        let mut host = CloudBrowserToolHost::new(
            inner,
            state.session_store.clone(),
            claim.run_id.clone(),
            full_cdp,
            state.site_credentials.clone(),
            Arc::new(admission.clone()),
        )
        .with_file_roots(vec![workspace.clone()])
        .with_browser_auth(
            state.browser_auth.clone(),
            claim.conversation_id.clone(),
            claim.authorization_revision,
        );
        if let Some(root) = &state.app_data_dir {
            host = host
                .with_blocked_file_roots(vec![root.clone()])
                .with_artifact_root(root.join("browser-downloads"));
        }
        Arc::new(host) as Arc<dyn ToolHost>
    });
    let authority = Arc::new(ExecutionAuthority::CloudClaim(Arc::new(CloudExecution {
        admission,
        scope,
        session,
        owner: owner.clone(),
        mcp,
        mcp_scope,
        browser,
    })));
    state
        .mcp_app_automation
        .register_authority(authority.clone());
    let context = agistack_core::agent::tool_policy::ToolPolicyContext {
        session_id: &claim.session_id,
        round: claim.round,
        tool: &claim.tool_name,
    };
    if claim.mcp_binding.is_some() {
        return call_identity::scope(
            &context,
            authority.call(&claim.tool_name, &claim.input_json),
        )
        .await;
    }
    call_identity::scope(
        &context,
        cua_repl::execute_authorized(
            state,
            authority,
            &claim.tool_name,
            &claim.input_json,
            &workspace,
            profile,
        ),
    )
    .await
}

#[cfg(test)]
#[path = "cloud_repl_tests.rs"]
mod tests;
