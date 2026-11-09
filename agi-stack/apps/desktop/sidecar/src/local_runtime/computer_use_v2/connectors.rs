//! Connector routing uses declared serverInfo capabilities and exact tool IDs only.
use super::Owner;
use crate::local_runtime::{
    mcp_supervisor::{McpScope, McpServerDefinition, McpToolCallOutcome},
    LocalRuntimeState,
};
use agistack_adapters_cua::{ConnectorOperationEffect, CONNECTOR_OPERATION_EFFECTS};
use agistack_core::ports::{CoreError, CoreResult, ToolResult};
use serde::Serialize;
use serde_json::{json, Value};

#[derive(Clone, Serialize)]
pub(super) struct Connector {
    pub account_id: String,
    pub server_id: String,
    pub provider: String,
    pub capability: String,
    pub tools: Vec<String>,
    pub available: bool,
    pub operations: Vec<ConnectorOperationEffect>,
    #[serde(skip)]
    pub identity: String,
}
fn declared(server: &McpServerDefinition) -> Vec<Connector> {
    let Some(descriptor) = server
        .server_info
        .as_ref()
        .and_then(|info| info.get("computer_use_connector"))
    else {
        return vec![];
    };
    let Some(provider) = descriptor
        .get("provider")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
    else {
        return vec![];
    };
    let account = descriptor
        .get("account_id")
        .and_then(Value::as_str)
        .unwrap_or(&server.id);
    let Some(capabilities) = descriptor.get("capabilities").and_then(Value::as_object) else {
        return vec![];
    };
    if !matches!(provider, "google" | "microsoft365" | "configured_mcp") {
        return vec![];
    }
    let identity=super::super::tool_authority::canonical_json_digest(&json!({"server_id":server.id,"command":server.command,"provider":provider,"account":account,"capabilities":capabilities,"tools":server.discovered_tools})).unwrap_or_default();
    capabilities
        .iter()
        .filter(|(name, _)| matches!(name.as_str(), "calendar" | "contacts" | "messages"))
        .filter_map(|(capability, tools)| {
            let tools = tools
                .as_array()?
                .iter()
                .filter_map(Value::as_str)
                .filter(|name| {
                    server
                        .discovered_tools
                        .iter()
                        .any(|tool| tool["name"] == *name)
                })
                .map(str::to_owned)
                .collect::<Vec<_>>();
            (!tools.is_empty()).then(|| Connector {
                account_id: account.into(),
                server_id: server.id.clone(),
                provider: provider.into(),
                capability: capability.clone(),
                tools,
                operations: server
                    .discovered_tools
                    .iter()
                    .filter(|tool| {
                        tools_contains(capabilities.get(capability), tool["name"].as_str())
                    })
                    .filter_map(|tool| {
                        let name = tool["name"].as_str()?;
                        Some(ConnectorOperationEffect {
                            provider: provider.into(),
                            account_id: Some(account.into()),
                            server_id: Some(server.id.clone()),
                            server_name: Some(server.name.clone()),
                            managed_account: false,
                            connector: capability.clone(),
                            operation: name.into(),
                            effect: if tool["annotations"]["readOnlyHint"] == true
                                && tool["annotations"]["destructiveHint"] != true
                            {
                                "read"
                            } else {
                                "mutate"
                            }
                            .into(),
                        })
                    })
                    .collect(),
                available: server.enabled && server.runtime_status == "healthy",
                identity: identity.clone(),
            })
        })
        .collect()
}
fn tools_contains(tools: Option<&Value>, name: Option<&str>) -> bool {
    name.is_some_and(|name| {
        tools
            .and_then(Value::as_array)
            .is_some_and(|tools| tools.iter().any(|tool| tool.as_str() == Some(name)))
    })
}
pub(super) fn declares_tool(server: &McpServerDefinition, tool: &str) -> bool {
    declared(server)
        .iter()
        .any(|connector| connector.tools.iter().any(|name| name == tool))
}
pub(super) fn list(state: &LocalRuntimeState, owner: &Owner) -> Result<Vec<Connector>, String> {
    let scope = McpScope {
        tenant_id: owner.tenant_id.clone(),
        project_id: owner.project_id.clone(),
    };
    let managed = state
        .mcp_supervisor
        .computer_use_managed_servers(&scope)
        .map_err(|error| error.reason_code().to_owned())?;
    let owned = super::accounts::owned_ids(state, owner)?;
    state
        .mcp_supervisor
        .list_servers(&McpScope {
            tenant_id: owner.tenant_id.clone(),
            project_id: owner.project_id.clone(),
        })
        .map(|servers| {
            servers
                .iter()
                .filter(|server| !managed.contains(&server.id) || owned.contains(&server.id))
                .flat_map(|server| {
                    let mut connectors = declared(server);
                    for connector in &mut connectors {
                        for operation in &mut connector.operations {
                            operation.managed_account =
                                managed.contains(&server.id) && owned.contains(&server.id);
                        }
                    }
                    connectors
                })
                .collect()
        })
        .map_err(|error| error.reason_code().into())
}
pub(super) fn select(
    state: &LocalRuntimeState,
    owner: &Owner,
    input: &Value,
) -> CoreResult<Option<Connector>> {
    if input
        .get("provider")
        .and_then(Value::as_str)
        .unwrap_or("native")
        == "native"
    {
        return Ok(None);
    }
    let capability = input
        .get("connector")
        .and_then(Value::as_str)
        .ok_or_else(|| CoreError::Tool("cua_connector_invalid".into()))?;
    let operation = input
        .get("operation")
        .and_then(Value::as_str)
        .ok_or_else(|| CoreError::Tool("cua_connector_invalid".into()))?;
    let candidates = list(state, owner)
        .map_err(CoreError::Tool)?
        .into_iter()
        .filter(|connector| {
            connector.capability == capability
                && connector.tools.iter().any(|tool| tool == operation)
                && input
                    .get("account_id")
                    .and_then(Value::as_str)
                    .is_none_or(|account| connector.account_id == account)
                && input
                    .get("provider")
                    .and_then(Value::as_str)
                    .is_none_or(|provider| {
                        connector.provider == provider || provider == "configured_mcp"
                    })
        })
        .collect::<Vec<_>>();
    match candidates.len() {
        0 if input.get("provider").is_none() && input.get("account_id").is_none() => Ok(None),
        0 => Err(CoreError::Tool("cua_connector_unavailable".into())),
        1 => {
            let connector = candidates.into_iter().next().expect("one candidate");
            if !connector.available {
                return Err(CoreError::Tool("cua_connector_unavailable".into()));
            }
            Ok(Some(connector))
        }
        _ => Err(CoreError::Tool(
            json!({"error":"cua_connector_account_required","candidates":candidates}).to_string(),
        )),
    }
}
pub(super) fn scoped_list(
    state: &LocalRuntimeState,
    owner: &Owner,
    allowed: &[String],
) -> Result<Vec<Connector>, String> {
    let scope = McpScope {
        tenant_id: owner.tenant_id.clone(),
        project_id: owner.project_id.clone(),
    };
    let managed = state
        .mcp_supervisor
        .computer_use_managed_servers(&scope)
        .map_err(|error| error.reason_code().to_owned())?;
    Ok(list(state, owner)?
        .into_iter()
        .filter(|connector| {
            managed.contains(&connector.server_id)
                || allowed.iter().any(|server| {
                    server == "*"
                        || server == &connector.server_id
                        || connector
                            .operations
                            .iter()
                            .any(|operation| operation.server_name.as_deref() == Some(server))
                })
        })
        .collect())
}
pub(super) fn schema(
    state: &LocalRuntimeState,
    owner: &Owner,
    allowed: &[String],
    mut schema: Value,
) -> Value {
    let mut operations = agistack_adapters_cua::native_connector_operations();
    if let Ok(connectors) = scoped_list(state, owner, allowed) {
        operations.extend(
            connectors
                .into_iter()
                .filter(|connector| connector.available)
                .flat_map(|connector| connector.operations),
        );
    }
    schema[CONNECTOR_OPERATION_EFFECTS] = json!(operations);
    schema
}
pub(super) async fn call(
    state: &LocalRuntimeState,
    owner: &Owner,
    connector: &Connector,
    input: &Value,
    call_id: &str,
) -> CoreResult<ToolResult> {
    // Re-resolve just before dispatch so disabled or replaced accounts cannot use a pinned binding.
    let current=select(state,owner,&json!({"connector":connector.capability,"operation":input["operation"],"account_id":connector.account_id,"provider":connector.provider}))?
        .filter(|current|current.identity==connector.identity&&current.server_id==connector.server_id).ok_or_else(||CoreError::Tool("cua_connector_authorization_revoked".into()))?;
    let result = state
        .mcp_supervisor
        .call_tool(
            &McpScope {
                tenant_id: owner.tenant_id.clone(),
                project_id: owner.project_id.clone(),
            },
            &current.server_id,
            input["operation"]
                .as_str()
                .ok_or_else(|| CoreError::Tool("cua_connector_invalid".into()))?,
            input["arguments"].clone(),
            call_id,
        )
        .await
        .map_err(|error| CoreError::Tool(error.reason_code().into()))?;
    tool_result(result)
}

fn tool_result(result: McpToolCallOutcome) -> CoreResult<ToolResult> {
    let output = json!({
        "result": result.result,
        "content": result.content,
        "isError": result.is_error,
        "duplicate": result.duplicate,
    });
    if result.is_error {
        return Err(CoreError::Tool(output.to_string()));
    }
    Ok(ToolResult::text(output.to_string()))
}

#[cfg(test)]
#[path = "connector_result_tests.rs"]
mod result_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn structured_mcp_failure_uses_tool_error_even_with_successful_transport() {
        let output = json!({"isError":true,"content":[{"type":"text","text":"fixture rejected"}]});
        let result = tool_result(McpToolCallOutcome {
            result: output.clone(),
            content: output["content"].as_array().unwrap().clone(),
            is_error: true,
            duplicate: false,
        });
        let Err(CoreError::Tool(error)) = result else {
            panic!("MCP isError must enter the ordinary tool failure path");
        };
        let error: Value = serde_json::from_str(&error).unwrap();
        assert_eq!(error["isError"], true);
        assert_eq!(error["content"][0]["text"], "fixture rejected");
    }

    #[test]
    fn error_text_in_successful_mcp_content_does_not_change_status() {
        let result = tool_result(McpToolCallOutcome {
            result: json!({"isError":false}),
            content: vec![json!({"type":"text","text":"error count: 0"})],
            is_error: false,
            duplicate: true,
        })
        .unwrap();
        let output: Value = serde_json::from_str(&result.output_json).unwrap();
        assert_eq!(output["isError"], false);
        assert_eq!(output["duplicate"], true);
        assert_eq!(output["content"][0]["text"], "error count: 0");
        assert!(result.control_outcome.is_none());
    }

    fn server() -> McpServerDefinition {
        McpServerDefinition {
            id: "account".into(),
            tenant_id: "tenant".into(),
            project_id: "project".into(),
            name: "Calendar Name Is Not A Policy".into(),
            description: None,
            transport: crate::local_runtime::mcp_supervisor::McpTransport::Stdio,
            command: vec!["/bundled/server".into()],
            cwd: None,
            vault_env_refs: Default::default(),
            enabled: true,
            revision: 1,
            runtime_status: "healthy".into(),
            reason_code: None,
            discovered_tools: vec![json!({"name":"arbitrary_tool_id"})],
            server_info: None,
            created_at: String::new(),
            updated_at: String::new(),
        }
    }
    #[test]
    fn connector_names_do_not_classify_and_declared_exact_tools_do() {
        let mut server = server();
        assert!(declared(&server).is_empty());
        server.server_info = Some(
            json!({"computer_use_connector":{"provider":"configured_mcp","capabilities":{"calendar":["arbitrary_tool_id","not_advertised"],"messages":["not_advertised"]}}}),
        );
        let connectors = declared(&server);
        assert_eq!(connectors.len(), 1);
        assert_eq!(connectors[0].tools, ["arbitrary_tool_id"]);
        assert_eq!(connectors[0].operations[0].effect, "mutate");
        server.discovered_tools[0]["annotations"] = json!({"readOnlyHint":true});
        assert_eq!(declared(&server)[0].operations[0].effect, "read");
        server.discovered_tools[0]["annotations"]["destructiveHint"] = json!(true);
        assert_eq!(declared(&server)[0].operations[0].effect, "mutate");
    }
}
