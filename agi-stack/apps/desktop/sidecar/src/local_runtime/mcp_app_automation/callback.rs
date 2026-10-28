use super::{callback_origin::CallbackOrigin, *};

impl McpAppAutomationRegistry {
    /// Only a queued host callback may reach the server receipt check under a new revision.
    /// This inspects the old attachment; it does not update it or dispatch a tool.
    fn cloud_callback_candidate(
        &self,
        state: &LocalRuntimeState,
        id: &str,
        captured: &ExecutionScope,
        authority: &ExecutionAuthority,
    ) -> CoreResult<AppTab> {
        use crate::local_runtime::execution_authority::{
            current_cell_lifetime, current_step_origin,
        };
        authority.current()?;
        let origin =
            current_step_origin().ok_or_else(|| denied("mcp_app_pending_cell_required"))?;
        let previous = origin
            .continuation_scope
            .as_ref()
            .ok_or_else(|| denied("mcp_app_pending_cell_required"))?;
        let mut captured_previous = captured.clone();
        captured_previous.run_revision = previous.run_revision;
        let mut expected = previous.clone();
        expected.run_revision = authority.scope().run_revision;
        if !matches!(authority, ExecutionAuthority::CloudClaim(_))
            || expected != *authority.scope()
            || captured_previous != *previous
            || previous.connection_epoch.is_none()
            || authority.scope().run_revision < previous.run_revision
            || current_cell_lifetime()
                .is_none_or(|live| !live.load(std::sync::atomic::Ordering::SeqCst))
        {
            return Err(denied("mcp_app_pending_cell_changed"));
        }
        let tab = self
            .tabs
            .lock()
            .expect("MCP app tabs")
            .get(id)
            .cloned()
            .ok_or_else(|| denied("mcp_app_frame_expired"))?;
        if !tab.attached
            || tab.registration.is_none()
            || tab.scope != *previous
            || (captured.run_revision != previous.run_revision
                && !tab.continuation_revisions.contains(&captured.run_revision))
            || tab.child.is_some()
        {
            return Err(denied("mcp_app_frame_or_scope_changed"));
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
            .any(|name| name == "*" || name == &server.id || name == &server.name)
        {
            return Err(denied("mcp_app_server_forbidden"));
        }
        Ok(tab)
    }

    /// The target comes from the captured iframe callback, never from JavaScript arguments.
    pub(crate) fn cloud_callback_target(
        &self,
        state: &LocalRuntimeState,
        authority: &ExecutionAuthority,
        tool: &str,
    ) -> CoreResult<Option<(ExecutionScope, String)>> {
        let Some(origin) = CallbackOrigin::current() else {
            return Ok(None);
        };
        if crate::local_runtime::mcp_agent_tool_host::legacy_exposed_tool_name(
            &origin.server_id,
            &origin.tool_name,
        ) != tool
            || call_identity::active()?.engine_session_id() != origin.engine_session_id
        {
            return Err(denied("mcp_app_callback_binding_changed"));
        }
        let tab = match (
            authority,
            self.require_callback_continuation(state, &origin.renderer_id, &origin.scope),
        ) {
            (_, Ok((tab, _))) if &tab.scope == authority.scope() => tab,
            (ExecutionAuthority::LocalRun(_), Err(error)) => return Err(error),
            (ExecutionAuthority::LocalRun(_), Ok(_)) => {
                return Err(denied("mcp_app_scope_mismatch"));
            }
            (ExecutionAuthority::CloudClaim(_), _) => self.cloud_callback_candidate(
                state,
                &origin.renderer_id,
                &origin.scope,
                authority,
            )?,
        };
        if !tab.attached || tab.registration.as_deref() != Some(&origin.registration) {
            return Err(denied("mcp_app_frame_or_scope_changed"));
        }
        Ok(Some((tab.scope, origin.registration)))
    }

    pub(crate) fn validate_cloud_callback(
        &self,
        state: &LocalRuntimeState,
        authority: &ExecutionAuthority,
    ) -> CoreResult<()> {
        let origin =
            CallbackOrigin::current().ok_or_else(|| denied("mcp_app_callback_source_required"))?;
        let (tab, _) =
            self.require_callback_continuation(state, &origin.renderer_id, &origin.scope)?;
        if !tab.attached
            || tab.registration.as_deref() != Some(&origin.registration)
            || &tab.scope != authority.scope()
        {
            return Err(denied("mcp_app_frame_or_scope_changed"));
        }
        Ok(())
    }

    pub(super) async fn call_tool(
        &self,
        state: &Arc<LocalRuntimeState>,
        id: &str,
        tab: &AppTab,
        authority: &ExecutionAuthority,
        args: &Value,
    ) -> CoreResult<Value> {
        let scope = authority.mcp_scope();
        let name = args["name"]
            .as_str()
            .ok_or_else(|| denied("mcp_app_tool_required"))?;
        let arguments = args.get("arguments").cloned().unwrap_or_else(|| json!({}));
        if !arguments.is_object() {
            return Err(denied("mcp_app_arguments_invalid"));
        }
        let binding = state
            .mcp_supervisor
            .resolve_tool(&scope, &tab.app.server_id, name)
            .map_err(|error| denied(error.reason_code()))?;
        if binding.catalog_digest != tab.binding.catalog_digest {
            return Err(denied("mcp_app_catalog_changed"));
        }
        let metadata = &binding.definition["_meta"];
        let ui = &metadata["ui"];
        let visibility = ui
            .get("visibility")
            .or_else(|| metadata.get("visibility"))
            .or_else(|| metadata.get("mcp/visibility"));
        let uri = ui["resourceUri"]
            .as_str()
            .or_else(|| metadata["ui/resourceUri"].as_str())
            .or_else(|| metadata["mcp/ui/resourceUri"].as_str());
        let visible = visibility.map_or(uri.is_some(), |value| {
            value.as_str() == Some("app")
                || value
                    .as_array()
                    .is_some_and(|items| items.iter().any(|item| item == "app"))
        });
        if !visible || (uri != tab.app.resource_uri.as_deref() && name != tab.app.tool_name) {
            return Err(denied("mcp_app_tool_not_visible"));
        }
        let origin = CallbackOrigin::capture(id, tab, &binding)?;
        let tool = crate::local_runtime::mcp_agent_tool_host::legacy_exposed_tool_name(
            &binding.server_id,
            &binding.tool_name,
        );
        let input_json = arguments.to_string();
        let context = state
            .cua_repl
            .active_context_for(&tab.scope.run_id, tab.identity.engine_session_id());
        if let Some(context) = context {
            let weak_state = Arc::downgrade(state);
            let id = id.to_string();
            let scope = tab.scope.clone();
            let identity = tab.identity.clone();
            let child = tab.child.clone();
            let registration = tab.registration.clone();
            let dispatch: crate::local_runtime::cua_repl::ExternalDispatch =
                Arc::new(move |authority| {
                    let state = weak_state.clone();
                    let id = id.clone();
                    let scope = scope.clone();
                    let identity = identity.clone();
                    let child = child.clone();
                    let tool = tool.clone();
                    let input_json = input_json.clone();
                    let registration = registration.clone();
                    let origin = origin.clone();
                    Box::pin(async move {
                        let state = state
                            .upgrade()
                            .ok_or_else(|| denied("mcp_app_execution_unavailable"))?;
                        let current = match (
                            authority.as_ref(),
                            state
                                .mcp_app_automation
                                .require_callback_continuation(&state, &id, &scope),
                        ) {
                            (_, Ok((current, _))) if authority.scope() == &current.scope => current,
                            (ExecutionAuthority::LocalRun(_), Err(error)) => return Err(error),
                            (ExecutionAuthority::LocalRun(_), Ok(_)) => {
                                return Err(denied("mcp_app_scope_mismatch"));
                            }
                            (ExecutionAuthority::CloudClaim(_), _) => state
                                .mcp_app_automation
                                .cloud_callback_candidate(&state, &id, &scope, &authority)?,
                        };
                        if !current.attached || current.registration != registration {
                            return Err(denied("mcp_app_frame_or_scope_changed"));
                        }
                        let active_identity = call_identity::active()?;
                        if active_identity.engine_session_id() != identity.engine_session_id() {
                            return Err(denied("mcp_app_engine_scope_changed"));
                        }
                        let call = active_identity
                            .for_tool(&tool, origin.scope(authority.call(&tool, &input_json)));
                        if let Some(child) = child {
                            crate::local_runtime::local_plugin_tool_host_v2::identity::child_scope(
                                child, call,
                            )
                            .await
                        } else {
                            call.await
                        }
                    })
                });
            return context.submit(dispatch).await;
        }
        if authority.request_id().is_some() {
            return Err(denied("mcp_app_requires_active_cell"));
        }
        let step_id = uuid::Uuid::new_v4().to_string();
        let dispatch = tab.identity.for_tool(
            &tool,
            crate::local_runtime::execution_authority::with_step_id(
                step_id,
                origin.scope(authority.call(&tool, &input_json)),
            ),
        );
        let output = if let Some(child) = tab.child.clone() {
            crate::local_runtime::local_plugin_tool_host_v2::identity::child_scope(child, dispatch)
                .await?
        } else {
            dispatch.await?
        };
        serde_json::from_str(&output.output_json).map_err(|_| denied("mcp_app_result_invalid"))
    }
}
