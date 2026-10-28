use super::*;
use agistack_adapters_browser::facade::{TOOL_CDP, TOOL_READ, TOOL_WRITE};
use agistack_core::ports::{ToolDefinition, ToolHost, ToolResult};
use async_trait::async_trait;

const APP_FACADE_TOOLS: [&str; 3] = [TOOL_READ, TOOL_WRITE, TOOL_CDP];

/// Place inside Profiled/Authorized/plugin wrappers so each DOM operation uses their policy.
pub(crate) fn wrap_tools(
    inner: Arc<dyn ToolHost>,
    state: Weak<LocalRuntimeState>,
    run_id: String,
) -> Arc<dyn ToolHost> {
    Arc::new(McpAppFacadeToolHost {
        inner,
        state,
        run_id,
    })
}

struct McpAppFacadeToolHost {
    inner: Arc<dyn ToolHost>,
    state: Weak<LocalRuntimeState>,
    run_id: String,
}

#[async_trait]
impl ToolHost for McpAppFacadeToolHost {
    fn list_tools(&self) -> Vec<String> {
        let mut names = self.inner.list_tools();
        for name in APP_FACADE_TOOLS {
            if !names.iter().any(|existing| existing == name) {
                names.push(name.into());
            }
        }
        names
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        self.inner.tool_definition(name).or_else(|| {
            if !APP_FACADE_TOOLS.contains(&name) {
                return None;
            }
            let metadata = agistack_adapters_browser::host::list_tool_metadata()
                .into_iter()
                .find(|metadata| metadata["name"].as_str() == Some(name))?;
            Some(ToolDefinition {
                name: name.into(),
                description: metadata["description"].as_str().map(str::to_string),
                input_schema: metadata.get("inputSchema").cloned(),
            })
        })
    }
    fn can_dispatch(&self, tool: &str) -> bool {
        APP_FACADE_TOOLS.contains(&tool) || self.inner.can_dispatch(tool)
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<String> {
        self.call_with_content(tool, input)
            .await
            .map(|result| result.output_json)
    }
    async fn call_with_content(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
        use agistack_adapters_browser::facade::operation_effect;
        if !matches!(tool, TOOL_READ | TOOL_WRITE | TOOL_CDP) {
            return self.inner.call_with_content(tool, input).await;
        }
        let payload: Value =
            serde_json::from_str(input).map_err(|_| denied("mcp_app_arguments_invalid"))?;
        let is_app = payload["browserId"] == "mcpapps" || payload["backend"] == "mcpapps";
        let inventory = payload["operation"] == "browsers.list";
        if !is_app && !inventory {
            return self.inner.call_with_content(tool, input).await;
        }
        if operation_effect(&payload)?.tool() != tool {
            return Err(denied("mcp_app_effect_mismatch"));
        }
        let state = self
            .state
            .upgrade()
            .ok_or_else(|| denied("mcp_app_execution_unavailable"))?;
        let identity = call_identity::active()?;
        let authority = state
            .mcp_app_automation
            .registered(&self.run_id, identity.engine_session_id());
        if inventory {
            let mut result = if self.inner.can_dispatch(tool) {
                self.inner.call_with_content(tool, input).await?
            } else {
                ToolResult::text("[]")
            };
            if let Some(authority) = authority.filter(|item| item.current().is_ok()) {
                if state
                    .mcp_app_automation
                    .list(&state, authority.scope())
                    .as_array()
                    .is_some_and(|tabs| !tabs.is_empty())
                {
                    let mut value: Value = serde_json::from_str(&result.output_json)
                        .map_err(|_| denied("mcp_app_inventory_invalid"))?;
                    value
                        .as_array_mut()
                        .ok_or_else(|| denied("mcp_app_inventory_invalid"))?
                        .push(json!({"id":"mcpapps","type":"mcpapps","backend":"mcpapps"}));
                    result.output_json = value.to_string();
                }
            }
            return Ok(result);
        }
        let authority = authority.ok_or_else(|| denied("mcp_app_execution_unavailable"))?;
        authority.current()?;
        let operation = payload["operation"]
            .as_str()
            .ok_or_else(|| denied("mcp_app_operation_required"))?;
        let output = if operation == "tabs.list" {
            json!({"tabs":state.mcp_app_automation.list(&state, authority.scope())})
        } else if operation == "capabilities.list" && payload.get("tabId").is_none() {
            json!([])
        } else {
            let id = payload["tabId"]
                .as_str()
                .ok_or_else(|| denied("mcp_app_tab_required"))?;
            state
                .mcp_app_automation
                .browser_operation(
                    &state,
                    &authority,
                    id,
                    operation,
                    payload.get("args").cloned().unwrap_or_else(|| json!([])),
                )
                .await?
        };
        Ok(ToolResult::text(output.to_string()))
    }
}
