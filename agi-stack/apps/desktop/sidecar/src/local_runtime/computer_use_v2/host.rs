//! Consent, execution identity and media preservation at the native boundary.
use super::*;
use crate::local_runtime::{local_plugin_tool_host_v2, tool_authority};
use async_trait::async_trait;

pub(super) struct ScopedComputerUseHost {
    pub(super) state: std::sync::Weak<LocalRuntimeState>,
    pub(super) native: NativeIdentity,
    pub(super) session: Arc<Session>,
    pub(super) client: Arc<CuaClient>,
    pub(super) inner: Arc<dyn ToolHost>,
}

impl ScopedComputerUseHost {
    fn control_result(&self, state: &LocalRuntimeState) -> CoreResult<Option<ToolResult>> {
        let result = self
            .session
            .user_control
            .outcome(self.session.paused.load(Ordering::SeqCst));
        if let Some(result) = result.as_ref() {
            let instance = store::instance(
                &*state
                    .session_store
                    .connection()
                    .map_err(CoreError::Storage)?,
                &self.session.owner,
            )
            .map_err(CoreError::Storage)?;
            if !self.native.current(state)
                || !instance.enabled
                || !instance.installed
                || instance.revision != self.session.revision
                || (self.session.stopped.load(Ordering::SeqCst)
                    && result.control_outcome
                        != Some(agistack_core::ports::ToolControlOutcome::UserStopped))
            {
                return Err(CoreError::Tool("cua_authorization_revoked".into()));
            }
        }
        Ok(result)
    }
}

#[async_trait]
impl ToolHost for ScopedComputerUseHost {
    fn list_tools(&self) -> Vec<String> {
        if self.session.stopped.load(Ordering::SeqCst) {
            vec![]
        } else {
            self.inner.list_tools()
        }
    }
    fn can_dispatch(&self, tool: &str) -> bool {
        // Catalog removal must not hide the terminal receipt from an already
        // planned call. Invocation still checks scoped Stop and current authority.
        self.inner.can_dispatch(tool)
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        let mut definition = self.inner.tool_definition(name)?;
        if name == "computer_connector_call" {
            let state = self.state.upgrade()?;
            definition.input_schema = Some(connectors::schema(
                &state,
                &self.session.owner,
                &self
                    .native
                    .allowed_mcp_servers(&state, &self.session.context.conversation_id),
                definition.input_schema?,
            ));
        }
        Some(definition)
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<String> {
        Ok(self.call_with_content(tool, input).await?.output_json)
    }
    async fn call_with_content(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
        let state = self
            .state
            .upgrade()
            .ok_or_else(|| CoreError::Tool("cua_runtime_stopped".into()))?;
        if state
            .connected_browser_tool_host()
            .is_some_and(|host| host.has_protected_auth())
            && !matches!(
                tool,
                "computer_audio_stop" | "computer_key_up" | "computer_clipboard_release"
            )
            && !(tool == "computer_drag_step"
                && serde_json::from_str::<Value>(input)
                    .ok()
                    .is_some_and(|value| value["phase"] == "end"))
            && !(tool == "computer_locked_use"
                && serde_json::from_str::<Value>(input)
                    .ok()
                    .is_some_and(|value| value["enabled"] == false))
        {
            return Err(CoreError::Tool("browser_auth_protected: finish authentication and explicitly navigate the browser before native observation or input".into()));
        }
        denials::ensure(
            &*state
                .session_store
                .connection()
                .map_err(CoreError::Storage)?,
            &self.session.owner,
            &self.session.context.run_id,
        )?;
        if user_control::stopped(&state, &self.session.owner, &self.session.context.run_id)? {
            return Ok(agistack_core::ports::ToolControlOutcome::UserStopped.result(None));
        }
        // Every invocation resolves the current managed factory; an older host
        // cannot keep executing through a disabled generic V2 generation.
        let _factory =
            cloud::factory_lease(&state, &self.session.owner).map_err(CoreError::Tool)?;
        if let Some(child) = local_plugin_tool_host_v2::identity::current_child() {
            let run = state
                .session_store
                .run(&child.run_id)
                .map_err(CoreError::Storage)?
                .ok_or_else(|| CoreError::Tool("cua_child_authority_revoked".into()))?;
            if child.run_id != self.session.context.run_id
                || run.revision != child.revision
                || !state.subagent_controls.plugin_execution_current(
                    &child.execution_id,
                    &self.session.context.conversation_id,
                    &run,
                    &child.subagent_id,
                    state.control_for_run(&run).as_ref(),
                )
            {
                return Err(CoreError::Tool("cua_child_authority_revoked".into()));
            }
            if self
                .session
                .child
                .as_ref()
                .is_none_or(|bound| bound.execution_id != child.execution_id)
            {
                if self.session.stopped.load(Ordering::SeqCst) {
                    return Err(CoreError::Tool("cua_authorization_revoked".into()));
                }
                let session = state.computer_use.child_session(&self.session, child)?;
                let host = ScopedComputerUseHost {
                    state: self.state.clone(),
                    native: self.native.clone(),
                    session: session.clone(),
                    client: self.client.clone(),
                    inner: Arc::new(
                        CuaToolHost::new(self.client.clone()).with_context(session.context.clone()),
                    ),
                };
                return host.call_with_content(tool, input).await;
            }
        } else if self.session.child.is_some() {
            return Err(CoreError::Tool("cua_child_authority_required".into()));
        }
        let _dispatch = self
            .session
            .dispatch
            .try_lock()
            .map_err(|_| CoreError::Tool("cua_device_busy".into()))?;
        if self.session.stopped.load(Ordering::SeqCst) || !self.native.current(&state) {
            return Err(CoreError::Tool("cua_authorization_revoked".into()));
        }
        if self.session.paused.load(Ordering::SeqCst) {
            let result = self
                .control_result(&state)?
                .ok_or_else(|| CoreError::Tool("cua_control_state_invalid".into()))?;
            local_control::retain(&state, &self.session, &self.native, tool, &result)?;
            return Ok(result);
        }
        let instance = {
            let db = state.session_store.connection().map_err(CoreError::Tool)?;
            store::instance(&db, &self.session.owner).map_err(CoreError::Tool)?
        };
        if !instance.enabled || !instance.installed || instance.revision != self.session.revision {
            return Err(CoreError::Tool("cua_instance_disabled".into()));
        }
        let original_input = input;
        let mut input: Value =
            serde_json::from_str(input).map_err(|error| CoreError::Tool(error.to_string()))?;
        if !input.is_object()
            || input.get("_cua_call_id").is_some()
            || input.get("_cua_expected_identity").is_some()
        {
            return Err(CoreError::Tool("cua_invalid_params".into()));
        }
        agistack_adapters_cua::validate_tool_input(tool, &input)?;
        let releases_locked_use = tool == "computer_locked_use" && input["enabled"] == false;
        if releases_locked_use {
            // Releasing a session-owned lease retains the configured runtime capability check.
            capability_for(tool, &input, &instance)?;
        }
        let effect = if tool == "computer_connector_call" {
            let definition = self
                .tool_definition(tool)
                .ok_or_else(|| CoreError::Tool("cua_connector_unavailable".into()))?;
            agistack_adapters_cua::connector_operation_effect(
                &definition.input_schema.unwrap_or(Value::Null),
                &input,
            )
        } else {
            *agistack_adapters_cua::tool_effects()
                .get(tool)
                .ok_or_else(|| CoreError::Tool("cua_tool_unknown".into()))?
        };
        if !self.native.permits(tool, effect) {
            return Err(CoreError::Tool("cua_cloud_run_permission_required".into()));
        }
        if ADMITTED_EFFECT
            .try_with(|admitted| {
                *admitted == agistack_adapters_cua::CuaToolEffect::Read && effect != *admitted
            })
            .unwrap_or(false)
        {
            return Err(CoreError::Tool("cua_connector_effect_changed".into()));
        }
        let identity = call_identity::current(tool)?;
        let engine_session_id = self
            .session
            .cloud
            .as_ref()
            .map(|cloud| cloud.engine_session_id.clone())
            .unwrap_or_else(|| identity.engine_session_id().to_owned());
        let input_digest =
            tool_authority::canonical_json_digest(&json!({"tool":tool,"input":input}))
                .map_err(|error| CoreError::Tool(error.to_string()))?;
        let call_id =
            call_identity::id(&self.session.owner, &self.session.context.run_id, &identity)?;
        {
            let db = state
                .session_store
                .connection()
                .map_err(CoreError::Storage)?;
            if let Some(result) = call_identity::existing(&db, &call_id, &input_digest)? {
                local_control::retain(&state, &self.session, &self.native, tool, &result)?;
                return Ok(result);
            }
        }
        if tool == "computer_audio_read" {
            return recordings_read::read(
                &state,
                &self.session.owner,
                &self.session.context,
                &engine_session_id,
                &input,
            )
            .map(|output| ToolResult::text(output.to_string()))
            .map_err(CoreError::Tool);
        }
        if tool == "computer_resolve_app" {
            let mut target = self
                .client
                .request_in_session(&self.session.context, "resolve_app", input)
                .await
                .map_err(|error| CoreError::Tool(error.to_string()))?;
            let pid = target["process_id"]
                .as_u64()
                .ok_or_else(|| CoreError::Tool("cua_target_process_invalid".into()))?;
            target["status"] = json!(if pid == 0 { "not_running" } else { "running" });
            let mut result = ToolResult::text(target.to_string());
            artifacts::persist(
                &state,
                &self.session.owner,
                &self.session.context,
                &mut result,
            )
            .await?;
            return Ok(result);
        }
        let connector = if tool == "computer_connector_call" {
            let connector = connectors::select(&state, &self.session.owner, &input)?;
            if let Some(connector) = &connector {
                if !connectors::scoped_list(
                    &state,
                    &self.session.owner,
                    &self
                        .native
                        .allowed_mcp_servers(&state, &self.session.context.conversation_id),
                )
                .map_err(CoreError::Tool)?
                .iter()
                .any(|allowed| {
                    allowed.server_id == connector.server_id
                        && allowed.identity == connector.identity
                        && allowed.capability == connector.capability
                }) {
                    return Err(CoreError::Tool("cua_connector_not_allowed_by_agent".into()));
                }
            }
            connector
        } else {
            None
        };
        if let Some(app) = input.get("app").and_then(Value::as_str) {
            let target = self
                .client
                .request_in_session(&self.session.context, "resolve_app", json!({"app":app}))
                .await
                .map_err(|error| CoreError::Tool(error.to_string()))?;
            let mut decoration = ToolResult {
                permission_required: None,
                control_outcome: None,
                control_generation: None,
                output_json: target.to_string(),
                media: vec![],
            };
            artifacts::persist(
                &state,
                &self.session.owner,
                &self.session.context,
                &mut decoration,
            )
            .await?;
            let target: Value = serde_json::from_str(&decoration.output_json)
                .map_err(|_| CoreError::Tool("cua_target_invalid".into()))?;
            presentation::resolved(&self.session, &target);
            let canonical = target
                .get("app")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
                .ok_or_else(|| CoreError::Tool("cua_target_invalid".into()))?;
            let identity = target
                .get("identity_digest")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
                .ok_or_else(|| CoreError::Tool("cua_target_identity_required".into()))?;
            let execution_target = frozen_target(tool, &target, canonical)?;
            let mut observed_input = input.clone();
            observed_input["app"] = execution_target.clone();
            // Invalid observations cannot spend a one-shot app capability.
            CuaToolHost::new(self.client.clone())
                .with_context(self.session.context.clone())
                .validate_observed_action(tool, &observed_input)
                .await?;
            input["app"] = json!(canonical);
            let mut canonical_input = input.clone();
            canonical_input["resolved_process_id"] = target["process_id"].clone();
            let input_digest = tool_authority::canonical_json_digest(&canonical_input)
                .map_err(|error| CoreError::Tool(error.to_string()))?;
            let capability = capability_for(tool, &input, &instance)?;
            let pending_id = format!("cua-consent-{}", Uuid::new_v4());
            // A retry may consume only its exact pending request's once grant.
            let pending = state
                .computer_use
                .pending_for(&self.session.owner)
                .into_iter()
                .find(|p| {
                    p.session_id == self.session.context.session_id
                        && p.app == canonical
                        && p.identity_digest == identity
                        && p.capability == capability
                        && p.tool_name == tool
                        && p.input_digest == input_digest
                });
            let request_id = pending
                .as_ref()
                .map(|p| p.request_id.as_str())
                .unwrap_or(&pending_id);
            let authorized = {
                let db = state.session_store.connection().map_err(CoreError::Tool)?;
                store::authorize(
                    &db,
                    &self.session.owner,
                    canonical,
                    identity,
                    capability,
                    &self.session.context.session_id,
                    request_id,
                )
                .map_err(CoreError::Tool)?
            };
            if !authorized {
                let pending = pending.unwrap_or(PendingConsent {
                    request_id: pending_id,
                    session_id: self.session.context.session_id.clone(),
                    engine_session_id: Some(engine_session_id.clone()),
                    app: canonical.into(),
                    identity_digest: identity.into(),
                    capability: capability.into(),
                    tool_name: tool.into(),
                    input_digest,
                    target: self
                        .session
                        .presentation
                        .lock()
                        .ok()
                        .and_then(|p| p.get("target").cloned()),
                    app_icon: target.get("app_icon").cloned(),
                    owner: self.session.owner.clone(),
                });
                state
                    .computer_use
                    .pending
                    .lock()
                    .expect("computer-use consent")
                    .insert(pending.request_id.clone(), pending.clone());
                {
                    let db = state.session_store.connection().map_err(CoreError::Tool)?;
                    store::save_pending(
                        &db,
                        &self.session.owner,
                        &pending.request_id,
                        &json!(pending),
                    )
                    .map_err(CoreError::Tool)?;
                }
                presentation::update(&self.session, "awaiting_permission", None);
                let _ = self
                    .client
                    .request_in_session(
                        &self.session.context,
                        "presentation_update",
                        json!({"phase":"awaiting_permission"}),
                    )
                    .await;
                return Ok(consent::permission_required(
                    pending,
                    crate::local_runtime::execution_authority::permission_binding(
                        tool,
                        original_input,
                    )?,
                ));
            }
            if let Some(pending) = pending {
                state
                    .computer_use
                    .pending
                    .lock()
                    .expect("computer-use consent")
                    .remove(&pending.request_id);
                let db = state.session_store.connection().map_err(CoreError::Tool)?;
                store::remove_pending(&db, &self.session.owner, &pending.request_id)
                    .map_err(CoreError::Tool)?;
            }
            input["app"] = execution_target;
            input["_cua_expected_identity"] = json!(identity);
        } else if !matches!(
            tool,
            "computer_list_apps"
                | "computer_capabilities"
                | "computer_audio_status"
                | "computer_audio_stop"
                | "computer_clipboard_release"
        ) && !releases_locked_use
        {
            let capability = if tool == "computer_connector_call"
                && effect != agistack_adapters_cua::CuaToolEffect::Read
            {
                "connector_action"
            } else {
                capability_for(tool, &input, &instance)?
            };
            let target = connector
                .as_ref()
                .map(|connector| {
                    format!("connector:{}:{}", connector.server_id, connector.capability)
                })
                .unwrap_or_else(|| {
                    if tool == "computer_connector_call" {
                        return format!(
                            "connector:native:{}",
                            input["connector"].as_str().unwrap_or("unknown")
                        );
                    }
                    match capability {
                        "microphone" | "system_audio" | "audio_mixed" => "device:audio",
                        "clipboard" => "device:clipboard",
                        _ => "device:control",
                    }
                    .into()
                });
            let identity = connector
                .as_ref()
                .map(|connector| connector.identity.clone())
                .unwrap_or_else(|| {
                    if tool == "computer_connector_call" {
                        format!(
                            "native:{}:{}",
                            self.session.owner.device_id,
                            input["connector"].as_str().unwrap_or("unknown")
                        )
                    } else {
                        self.session.owner.device_id.clone()
                    }
                });
            let input_digest = tool_authority::canonical_json_digest(&input)
                .map_err(|error| CoreError::Tool(error.to_string()))?;
            let prior = state
                .computer_use
                .pending_for(&self.session.owner)
                .into_iter()
                .find(|p| {
                    p.session_id == self.session.context.session_id
                        && p.app == target
                        && p.identity_digest == identity
                        && p.capability == capability
                        && p.tool_name == tool
                        && p.input_digest == input_digest
                });
            let request_id = prior
                .as_ref()
                .map(|p| p.request_id.clone())
                .unwrap_or_else(|| format!("cua-consent-{}", Uuid::new_v4()));
            let allowed = {
                let db = state.session_store.connection().map_err(CoreError::Tool)?;
                store::authorize(
                    &db,
                    &self.session.owner,
                    &target,
                    &identity,
                    capability,
                    &self.session.context.session_id,
                    &request_id,
                )
                .map_err(CoreError::Tool)?
            };
            if !allowed {
                let pending = PendingConsent {
                    request_id,
                    session_id: self.session.context.session_id.clone(),
                    engine_session_id: Some(engine_session_id.clone()),
                    app: target.into(),
                    identity_digest: identity,
                    capability: capability.into(),
                    tool_name: tool.into(),
                    input_digest,
                    target: None,
                    app_icon: None,
                    owner: self.session.owner.clone(),
                };
                state
                    .computer_use
                    .pending
                    .lock()
                    .expect("computer-use consent")
                    .insert(pending.request_id.clone(), pending.clone());
                {
                    let db = state.session_store.connection().map_err(CoreError::Tool)?;
                    store::save_pending(
                        &db,
                        &self.session.owner,
                        &pending.request_id,
                        &json!(pending),
                    )
                    .map_err(CoreError::Tool)?;
                }
                presentation::update(&self.session, "awaiting_permission", None);
                let _ = self
                    .client
                    .request_in_session(
                        &self.session.context,
                        "presentation_update",
                        json!({"phase":"awaiting_permission"}),
                    )
                    .await;
                return Ok(consent::permission_required(
                    pending,
                    crate::local_runtime::execution_authority::permission_binding(
                        tool,
                        original_input,
                    )?,
                ));
            }
            state
                .computer_use
                .pending
                .lock()
                .expect("computer-use consent")
                .remove(&request_id);
            {
                let db = state.session_store.connection().map_err(CoreError::Tool)?;
                store::remove_pending(&db, &self.session.owner, &request_id)
                    .map_err(CoreError::Tool)?;
            }
        }
        input["_cua_call_id"] = json!(call_id);
        if self.session.stopped.load(Ordering::SeqCst)
            || !self.native.current(&state)
            || !state
                .platform_plugin_authority_v2
                .acquire_generation()
                .is_ok_and(|current| current.descriptor() == _factory.descriptor())
        {
            return Err(CoreError::Tool("cua_authorization_revoked".into()));
        }
        CuaToolHost::new(self.client.clone())
            .with_context(self.session.context.clone())
            .validate_observed_action(tool, &input)
            .await?;
        let dispatch = call_identity::claim(
            &state.session_store,
            &self.session.owner,
            &self.session.context.run_id,
            &identity,
            &call_id,
            &input_digest,
        )?;
        // ReAct owns the durable round checkpoint; these fresh dispatches must not be digest-deduped.
        presentation::update(
            &self.session,
            if tool == "computer_get_app_state" {
                "observing"
            } else {
                "acting"
            },
            None,
        );
        let mut result = if tool == "computer_locked_use" {
            locked_use::call(
                &state,
                &self.session,
                &self.native,
                &_factory,
                &self.client,
                &input,
            )
            .await?
        } else if let Some(connector) = connector {
            connectors::call(&state, &self.session.owner, &connector, &input, &call_id).await?
        } else {
            let signal = agistack_adapters_cua::CuaDispatchSignal::new(call_id.clone());
            let result = agistack_adapters_cua::scope_dispatch_signal(
                signal.clone(),
                self.inner.call_with_content(tool, &input.to_string()),
            )
            .await;
            match result {
                Ok(result) => result,
                Err(error) => {
                    if matches!(error, CoreError::NativeControlInterrupted) {
                        if let Some(result) = self.control_result(&state)? {
                            dispatch.complete(&result)?;
                            local_control::retain(
                                &state,
                                &self.session,
                                &self.native,
                                tool,
                                &result,
                            )?;
                            return Ok(result);
                        }
                    }
                    presentation::update(
                        &self.session,
                        "error",
                        Some(&json!({"error_code":"cua_native_call_failed"})),
                    );
                    if !signal.was_sent() {
                        dispatch.not_sent()?;
                    }
                    return Err(error);
                }
            }
        };
        recordings::tool_result(&state, &self.session, &mut result).await?;
        if let Some(result) = self.control_result(&state)? {
            dispatch.complete(&result)?;
            local_control::retain(&state, &self.session, &self.native, tool, &result)?;
            return Ok(result);
        }
        if self.session.stopped.load(Ordering::SeqCst) {
            return Err(CoreError::Tool("cua_authorization_revoked".into()));
        }
        if tool == "computer_capabilities" {
            let mut output: Value = serde_json::from_str(&result.output_json)
                .map_err(|_| CoreError::Tool("cua_capabilities_invalid".into()))?;
            if let Some(status) = output.pointer_mut("/capabilities/locked_use") {
                *status = state.computer_use.locked_use.caller_status(
                    &self.session.context.session_id,
                    &self.session.context.run_id,
                    status,
                );
            }
            output["connectors"] = json!(connectors::scoped_list(
                &state,
                &self.session.owner,
                &self
                    .native
                    .allowed_mcp_servers(&state, &self.session.context.conversation_id)
            )
            .map_err(CoreError::Tool)?);
            output["native_connector_operations"] =
                json!(agistack_adapters_cua::native_connector_operations());
            result.output_json = output.to_string();
        }
        artifacts::persist(
            &state,
            &self.session.owner,
            &self.session.context,
            &mut result,
        )
        .await?;
        let output = serde_json::from_str(&result.output_json).unwrap_or(Value::Null);
        if tool == "computer_get_app_state" {
            presentation::observed(&self.session, &output);
            presentation::record(&state, &self.session);
        } else {
            presentation::update(&self.session, "idle", None);
        }
        dispatch.complete(&result)?;
        Ok(result)
    }
}

pub(super) fn frozen_target(tool: &str, target: &Value, canonical: &str) -> CoreResult<Value> {
    match target
        .get("process_id")
        .and_then(Value::as_i64)
        .filter(|pid| *pid > 0)
    {
        Some(pid) => Ok(json!(format!("pid:{pid}"))),
        None if tool == "computer_launch_app" => Ok(target
            .get("app_path")
            .and_then(Value::as_str)
            .filter(|path| !path.is_empty())
            .map(|path| json!(path))
            .unwrap_or_else(|| json!(canonical))),
        None => Err(CoreError::Tool("cua_target_not_running".into())),
    }
}

pub(super) fn capability_for<'a>(
    tool: &str,
    input: &Value,
    instance: &Instance,
) -> CoreResult<&'a str> {
    match tool {
        "computer_get_app_state" | "computer_list_windows" => Ok("observe"),
        "computer_clipboard_read" | "computer_clipboard_write" | "computer_clipboard_release" => {
            Ok("clipboard")
        }
        "computer_connector_call" => match input.get("connector").and_then(Value::as_str) {
            Some("calendar") => Ok("calendar"),
            Some("contacts") => Ok("contacts"),
            Some("messages") => Ok("messages"),
            _ => Err(CoreError::Tool("cua_connector_unavailable".into())),
        },
        "computer_audio_start" => match input.get("source").and_then(Value::as_str) {
            Some("microphone") if instance.microphone => Ok("microphone"),
            Some("system") if instance.system_audio => Ok("system_audio"),
            Some("mixed") if instance.system_audio && instance.microphone => Ok("audio_mixed"),
            _ => Err(CoreError::Tool("cua_audio_capability_disabled".into())),
        },
        "computer_locked_use" if instance.locked_use => Ok("locked_use"),
        "computer_locked_use" => Err(CoreError::Tool("cua_locked_use_disabled".into())),
        _ => Ok("control"),
    }
}
