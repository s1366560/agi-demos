//! Project-scoped MCP tools exposed to the local ReAct engine.
//!
//! Tool identity and authorization are structural. The model decides whether a
//! tool is semantically appropriate; this host only exposes enabled, healthy,
//! already-discovered tools in the active tenant/project scope and dispatches
//! exact structured calls through [`McpSupervisor`].

use std::{collections::BTreeMap, sync::Arc};

use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use async_trait::async_trait;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use serde_json::{json, Value};

use super::{
    mcp_supervisor::{McpScope, McpSupervisor},
    tool_authority::{canonical_json_digest, ToolEffect, ToolMetadata},
};

const TOOL_PREFIX: &str = "mcp__";

#[derive(Clone)]
struct McpAgentTool {
    server_id: String,
    server_name: String,
    tool_name: String,
    metadata: ToolMetadata,
}

/// Snapshot of the active project-scoped MCP tool catalog for one agent run.
pub(super) struct McpAgentToolHost {
    supervisor: Arc<McpSupervisor>,
    scope: McpScope,
    run_id: String,
    tools: BTreeMap<String, McpAgentTool>,
}

impl McpAgentToolHost {
    pub(super) fn new(
        supervisor: Arc<McpSupervisor>,
        scope: McpScope,
        run_id: String,
        allowed_servers: Option<&[String]>,
    ) -> Result<Self, String> {
        let mut tools = BTreeMap::new();
        for server in supervisor
            .list_servers(&scope)
            .map_err(|error| error.to_string())?
            .into_iter()
            .filter(|server| {
                server.enabled
                    && server.runtime_status == "healthy"
                    && server_allowed(allowed_servers, &server.id, &server.name)
            })
        {
            for definition in &server.discovered_tools {
                let Some(tool_name) = definition.get("name").and_then(Value::as_str) else {
                    continue;
                };
                if tool_name.is_empty() || tool_name.chars().any(char::is_control) {
                    continue;
                }
                let exposed_name = exposed_tool_name(&server.id, tool_name);
                let effect = if definition
                    .pointer("/annotations/readOnlyHint")
                    .and_then(Value::as_bool)
                    == Some(true)
                {
                    ToolEffect::Read
                } else {
                    ToolEffect::Mutate
                };
                tools.insert(
                    exposed_name.clone(),
                    McpAgentTool {
                        server_id: server.id.clone(),
                        server_name: server.name.clone(),
                        tool_name: tool_name.to_string(),
                        metadata: ToolMetadata {
                            name: exposed_name,
                            effect,
                            sensitive_input_fields: Default::default(),
                        },
                    },
                );
            }
        }
        Ok(Self {
            supervisor,
            scope,
            run_id,
            tools,
        })
    }

    pub(super) fn authority_metadata_by_name(&self) -> BTreeMap<String, ToolMetadata> {
        self.tools
            .iter()
            .map(|(name, item)| (name.clone(), item.metadata.clone()))
            .collect()
    }
}

#[async_trait]
impl ToolHost for McpAgentToolHost {
    fn list_tools(&self) -> Vec<String> {
        self.tools.keys().cloned().collect()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        let definition = self
            .tools
            .get(tool)
            .ok_or_else(|| CoreError::Tool(format!("unknown MCP agent tool: {tool}")))?;
        let arguments: Value = serde_json::from_str(input_json)
            .map_err(|error| CoreError::Tool(format!("invalid MCP tool input: {error}")))?;
        if !arguments.is_object() {
            return Err(CoreError::Tool(
                "MCP tool input must be a JSON object".to_string(),
            ));
        }
        let call_digest = canonical_json_digest(&json!({
            "run_id": self.run_id,
            "tool": tool,
            "arguments": arguments,
        }))
        .map_err(|error| CoreError::Tool(error.to_string()))?;
        let outcome = self
            .supervisor
            .call_tool(
                &self.scope,
                &definition.server_id,
                &definition.tool_name,
                arguments,
                &format!("agent-{call_digest}"),
            )
            .await
            .map_err(|error| {
                CoreError::Tool(format!("{}: {}", error.reason_code(), error.detail()))
            })?;
        serde_json::to_string(&json!({
            "server_name": definition.server_name,
            "tool_name": definition.tool_name,
            "content": outcome.content,
            "is_error": outcome.is_error,
            "duplicate": outcome.duplicate,
        }))
        .map_err(|error| CoreError::Tool(error.to_string()))
    }
}

fn server_allowed(allowed: Option<&[String]>, server_id: &str, server_name: &str) -> bool {
    allowed.map_or(true, |values| {
        values
            .iter()
            .any(|value| value == "*" || value == server_id || value == server_name)
    })
}

fn exposed_tool_name(server_id: &str, tool_name: &str) -> String {
    format!(
        "{TOOL_PREFIX}{}__{}",
        URL_SAFE_NO_PAD.encode(server_id.as_bytes()),
        URL_SAFE_NO_PAD.encode(tool_name.as_bytes())
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exposed_names_are_collision_free_for_punctuation_variants() {
        assert_ne!(
            exposed_tool_name("server-a", "repo/query"),
            exposed_tool_name("server_a", "repo-query")
        );
    }

    #[test]
    fn allow_list_matches_only_declared_identity_or_wildcard() {
        assert!(server_allowed(Some(&["*".to_string()]), "id", "name"));
        assert!(server_allowed(Some(&["id".to_string()]), "id", "name"));
        assert!(!server_allowed(
            Some(&["another".to_string()]),
            "id",
            "name"
        ));
    }
}
