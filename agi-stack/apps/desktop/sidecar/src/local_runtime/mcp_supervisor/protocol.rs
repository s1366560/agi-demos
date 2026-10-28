//! Complete, bounded MCP collections and exact structured tool identities.
use std::collections::BTreeSet;

use serde_json::{json, Value};

use super::{
    validate_identifier, value_hash, McpResult, McpScope, McpServerDefinition, McpSupervisor,
    McpSupervisorError,
};

const MAX_PAGES: usize = 128;
const MAX_ITEMS: usize = 10_000;
const MAX_CURSOR_BYTES: usize = 4096;

/// A discovered tool bound to the server configuration and current catalog.
#[derive(Clone)]
pub(in crate::local_runtime) struct McpToolBinding {
    pub server_id: String,
    pub tool_name: String,
    pub server_revision: u64,
    pub catalog_digest: String,
    pub definition: Value,
}

fn malformed() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_malformed_response",
        "MCP collection response is malformed",
    )
}

impl McpSupervisor {
    pub(in crate::local_runtime) async fn list_tools(
        &self,
        scope: &McpScope,
        server_id: &str,
    ) -> McpResult<Vec<Value>> {
        let _generation = self.acquire_active_call(scope, server_id)?;
        self.collect_and_record_tools(scope, server_id).await
    }

    pub(in crate::local_runtime) async fn list_tools_for_marketplace_verification(
        &self,
        scope: &McpScope,
        server_id: &str,
    ) -> McpResult<Vec<Value>> {
        let _verification = self.acquire_marketplace_verification(scope, server_id)?;
        self.collect_and_record_tools(scope, server_id).await
    }

    async fn collect_and_record_tools(
        &self,
        scope: &McpScope,
        server_id: &str,
    ) -> McpResult<Vec<Value>> {
        let server = self.required_server(scope, server_id)?;
        let tools = self
            .collect_pages(scope, &server, "tools/list", "tools")
            .await?;
        self.store
            .record_tools_and_apps(&server, &tools)
            .map_err(|_| super::storage_error())?;
        Ok(tools)
    }

    pub(in crate::local_runtime) fn resolve_tool(
        &self,
        scope: &McpScope,
        server_id: &str,
        tool_name: &str,
    ) -> McpResult<McpToolBinding> {
        validate_identifier(tool_name, "local_mcp_tool_name_invalid")?;
        let server = self.required_server(scope, server_id)?;
        let definition = server
            .discovered_tools
            .iter()
            .find(|tool| tool["name"].as_str() == Some(tool_name))
            .cloned()
            .ok_or_else(|| {
                McpSupervisorError::new(
                    "local_mcp_tool_not_discovered",
                    "MCP tool is absent from the discovered catalog",
                )
            })?;
        Ok(McpToolBinding {
            server_id: server.id.clone(),
            tool_name: tool_name.into(),
            server_revision: server.revision,
            catalog_digest: value_hash(&json!({
                "id": server.id, "revision": server.revision, "transport": server.transport,
                "command": server.command, "tools": server.discovered_tools,
            })),
            definition,
        })
    }

    pub(super) async fn list_collection(
        &self,
        scope: &McpScope,
        server: &McpServerDefinition,
        method: &str,
        field: &str,
    ) -> McpResult<Vec<Value>> {
        let _generation = self.acquire_active_call(scope, &server.id)?;
        self.collect_pages(scope, server, method, field).await
    }

    async fn collect_pages(
        &self,
        scope: &McpScope,
        server: &McpServerDefinition,
        method: &str,
        field: &str,
    ) -> McpResult<Vec<Value>> {
        let mut items = Vec::new();
        let mut cursors = BTreeSet::new();
        let mut cursor = None;
        let mut bytes = 0usize;
        for _ in 0..MAX_PAGES {
            // A continuation cannot silently switch server configuration or account.
            if self.required_server(scope, &server.id)?.revision != server.revision {
                return Err(McpSupervisorError::new(
                    "local_mcp_catalog_changed",
                    "MCP server changed during pagination",
                ));
            }
            let params = cursor
                .as_ref()
                .map_or_else(|| json!({}), |value| json!({"cursor":value}));
            let result = self.request(server, method, params).await?;
            if self.required_server(scope, &server.id)?.revision != server.revision {
                return Err(McpSupervisorError::new(
                    "local_mcp_catalog_changed",
                    "MCP server changed during pagination",
                ));
            }
            bytes = bytes
                .checked_add(result.to_string().len())
                .ok_or_else(malformed)?;
            if bytes > self.limits.max_aggregate_bytes {
                return Err(McpSupervisorError::new(
                    "local_mcp_collection_too_large",
                    "MCP collection exceeds the response limit",
                ));
            }
            let page = result
                .get(field)
                .and_then(Value::as_array)
                .ok_or_else(malformed)?;
            if page.iter().any(|item| !item.is_object())
                || items.len().saturating_add(page.len()) > MAX_ITEMS
            {
                return Err(malformed());
            }
            items.extend(page.iter().cloned());
            match result.get("nextCursor") {
                None => return Ok(items),
                Some(Value::String(next)) if !next.is_empty() && next.len() <= MAX_CURSOR_BYTES => {
                    if !cursors.insert(next.clone()) {
                        return Err(McpSupervisorError::new(
                            "local_mcp_cursor_repeated",
                            "MCP server repeated a pagination cursor",
                        ));
                    }
                    cursor = Some(next.clone());
                }
                _ => return Err(malformed()),
            }
        }
        Err(McpSupervisorError::new(
            "local_mcp_page_limit",
            "MCP collection exceeds the page limit",
        ))
    }

    pub(in crate::local_runtime) async fn list_resource_templates(
        &self,
        scope: &McpScope,
        server_id: &str,
    ) -> McpResult<Vec<Value>> {
        let server = self.required_server(scope, server_id)?;
        let values = self
            .list_collection(
                scope,
                &server,
                "resources/templates/list",
                "resourceTemplates",
            )
            .await?;
        if values.iter().any(|item| {
            item["uriTemplate"].as_str().is_none_or(str::is_empty)
                || item["name"].as_str().is_none_or(str::is_empty)
        }) {
            return Err(malformed());
        }
        Ok(values)
    }

    pub(in crate::local_runtime) async fn list_prompts(
        &self,
        scope: &McpScope,
        server_id: &str,
    ) -> McpResult<Vec<Value>> {
        let server = self.required_server(scope, server_id)?;
        let values = self
            .list_collection(scope, &server, "prompts/list", "prompts")
            .await?;
        if values
            .iter()
            .any(|item| item["name"].as_str().is_none_or(str::is_empty))
        {
            return Err(malformed());
        }
        Ok(values)
    }

    pub(in crate::local_runtime) async fn get_prompt(
        &self,
        scope: &McpScope,
        server_id: &str,
        name: &str,
        arguments: Value,
    ) -> McpResult<Value> {
        validate_identifier(name, "local_mcp_prompt_name_invalid")?;
        if !arguments
            .as_object()
            .is_some_and(|values| values.values().all(Value::is_string))
        {
            return Err(McpSupervisorError::new(
                "local_mcp_prompt_arguments_invalid",
                "MCP prompt arguments must be strings",
            ));
        }
        let _generation = self.acquire_active_call(scope, server_id)?;
        let server = self.required_server(scope, server_id)?;
        let result = self
            .request(
                &server,
                "prompts/get",
                json!({"name":name,"arguments":arguments}),
            )
            .await?;
        if self.required_server(scope, server_id)?.revision != server.revision {
            return Err(McpSupervisorError::new(
                "local_mcp_catalog_changed",
                "MCP server changed during prompt retrieval",
            ));
        }
        let messages = result["messages"].as_array().ok_or_else(malformed)?;
        for message in messages {
            if !matches!(message["role"].as_str(), Some("user" | "assistant"))
                || !message["content"].is_object()
                || !matches!(
                    message["content"]["type"].as_str(),
                    Some("text" | "image" | "audio" | "resource" | "resource_link")
                )
            {
                return Err(malformed());
            }
        }
        Ok(result)
    }
}
