use std::{
    collections::{BTreeMap, HashMap},
    fmt,
    path::{Component, Path, PathBuf},
    sync::{Arc, Mutex},
    time::Duration,
};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use tokio::sync::Mutex as AsyncMutex;

use crate::application_vault::ApplicationCredentialVault;

use super::DesktopSessionStore;

mod stdio;
mod store;

use stdio::StdioRuntime;
use store::McpStore;

const MCP_PROTOCOL_VERSION: &str = "2024-11-05";

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(super) struct McpScope {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub(super) enum McpTransport {
    Stdio,
    Http,
    Sse,
    Websocket,
}

impl McpTransport {
    fn as_str(self) -> &'static str {
        match self {
            Self::Stdio => "stdio",
            Self::Http => "http",
            Self::Sse => "sse",
            Self::Websocket => "websocket",
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub(super) struct McpServerDefinition {
    pub(super) id: String,
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) name: String,
    pub(super) description: Option<String>,
    pub(super) transport: McpTransport,
    pub(super) command: Vec<String>,
    pub(super) cwd: Option<String>,
    #[serde(skip_serializing)]
    pub(super) vault_env_refs: BTreeMap<String, String>,
    pub(super) enabled: bool,
    pub(super) revision: u64,
    pub(super) runtime_status: String,
    pub(super) reason_code: Option<String>,
    pub(super) discovered_tools: Vec<Value>,
    pub(super) server_info: Option<Value>,
    pub(super) created_at: String,
    pub(super) updated_at: String,
}

#[derive(Clone, Debug, PartialEq)]
pub(super) struct McpServerDefinitionInput {
    pub(super) name: String,
    pub(super) description: Option<String>,
    pub(super) transport: McpTransport,
    pub(super) command: Vec<String>,
    pub(super) cwd: Option<String>,
    pub(super) vault_env_refs: BTreeMap<String, String>,
    pub(super) enabled: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub(super) struct McpAppDefinition {
    pub(super) id: String,
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) server_id: String,
    pub(super) server_name: String,
    pub(super) tool_name: String,
    pub(super) resource_uri: Option<String>,
    pub(super) ui_metadata: Value,
    pub(super) status: String,
    pub(super) revision: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(super) struct McpServerHealth {
    pub(super) id: String,
    pub(super) name: String,
    pub(super) status: String,
    pub(super) enabled: bool,
    pub(super) tools_count: usize,
    pub(super) reason_code: Option<String>,
    pub(super) revision: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub(super) struct McpToolCallOutcome {
    pub(super) result: Value,
    pub(super) duplicate: bool,
}

#[derive(Clone, Copy)]
pub(super) struct SupervisorLimits {
    pub(super) request_timeout: Duration,
    pub(super) initialize_timeout: Duration,
    pub(super) retry_base: Duration,
    pub(super) retry_max: Duration,
    pub(super) max_request_bytes: usize,
    pub(super) max_response_bytes: usize,
}

impl Default for SupervisorLimits {
    fn default() -> Self {
        Self {
            request_timeout: Duration::from_secs(15),
            initialize_timeout: Duration::from_secs(10),
            retry_base: Duration::from_secs(1),
            retry_max: Duration::from_secs(30),
            max_request_bytes: 256 * 1024,
            max_response_bytes: 1024 * 1024,
        }
    }
}

#[derive(Debug)]
pub(super) struct McpSupervisorError {
    reason_code: &'static str,
    detail: &'static str,
}

impl McpSupervisorError {
    pub(super) const fn new(reason_code: &'static str, detail: &'static str) -> Self {
        Self {
            reason_code,
            detail,
        }
    }

    pub(super) const fn reason_code(&self) -> &'static str {
        self.reason_code
    }

    pub(super) const fn detail(&self) -> &'static str {
        self.detail
    }
}

impl fmt::Display for McpSupervisorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.detail)
    }
}

type McpResult<T> = Result<T, McpSupervisorError>;

pub(super) struct McpSupervisor {
    store: McpStore,
    workspace_root: PathBuf,
    credential_vault: Mutex<Option<ApplicationCredentialVault>>,
    limits: SupervisorLimits,
    runtimes: Mutex<HashMap<String, Arc<AsyncMutex<StdioRuntime>>>>,
}

impl McpSupervisor {
    pub(super) fn new(
        session_store: DesktopSessionStore,
        workspace_root: PathBuf,
        credential_vault: Option<ApplicationCredentialVault>,
        limits: SupervisorLimits,
    ) -> Result<Self, String> {
        let workspace_root = workspace_root
            .canonicalize()
            .or_else(|_| {
                std::fs::create_dir_all(&workspace_root)?;
                workspace_root.canonicalize()
            })
            .map_err(|error| error.to_string())?;
        Ok(Self {
            store: McpStore::new(session_store)?,
            workspace_root,
            credential_vault: Mutex::new(credential_vault),
            limits,
            runtimes: Mutex::new(HashMap::new()),
        })
    }

    pub(super) fn create_server(
        &self,
        scope: &McpScope,
        input: McpServerDefinitionInput,
        idempotency_key: &str,
    ) -> McpResult<McpServerDefinition> {
        validate_scope(scope)?;
        if input.transport != McpTransport::Stdio {
            return Err(unsupported_transport(input.transport));
        }
        validate_definition(&input)?;
        validate_idempotency_key(idempotency_key)?;
        let request_hash = definition_hash(scope, &input);
        self.store
            .create_server(scope, &input, idempotency_key, &request_hash)
    }

    pub(super) fn list_servers(&self, scope: &McpScope) -> McpResult<Vec<McpServerDefinition>> {
        validate_scope(scope)?;
        self.store.list_servers(scope)
    }

    pub(super) fn server(
        &self,
        scope: &McpScope,
        server_id: &str,
    ) -> McpResult<Option<McpServerDefinition>> {
        validate_scope(scope)?;
        validate_identifier(server_id, "local_mcp_server_id_invalid")?;
        self.store.server(scope, server_id)
    }

    pub(super) fn server_by_name(
        &self,
        scope: &McpScope,
        server_name: &str,
    ) -> McpResult<Option<McpServerDefinition>> {
        validate_scope(scope)?;
        validate_identifier(server_name, "local_mcp_server_name_invalid")?;
        self.store.server_by_name(scope, server_name)
    }

    pub(super) fn list_apps(&self, scope: &McpScope) -> McpResult<Vec<McpAppDefinition>> {
        validate_scope(scope)?;
        self.store.list_apps(scope)
    }

    pub(super) fn app(
        &self,
        scope: &McpScope,
        app_id: &str,
    ) -> McpResult<Option<McpAppDefinition>> {
        validate_scope(scope)?;
        validate_identifier(app_id, "local_mcp_app_id_invalid")?;
        self.store.app(scope, app_id)
    }

    pub(super) fn health(&self, scope: &McpScope, server_id: &str) -> McpResult<McpServerHealth> {
        let server = self
            .server(scope, server_id)?
            .ok_or_else(server_not_found)?;
        Ok(McpServerHealth {
            id: server.id,
            name: server.name,
            status: server.runtime_status,
            enabled: server.enabled,
            tools_count: server.discovered_tools.len(),
            reason_code: server.reason_code,
            revision: server.revision,
        })
    }

    pub(super) async fn recover_enabled(&self, scope: &McpScope) -> McpResult<()> {
        for server in self
            .list_servers(scope)?
            .into_iter()
            .filter(|item| item.enabled)
        {
            let _ = self.ensure_initialized(&server).await;
        }
        Ok(())
    }

    pub(super) async fn recover_all_enabled(&self) -> McpResult<()> {
        for server in self.store.enabled_servers()? {
            let _ = self.ensure_initialized(&server).await;
        }
        Ok(())
    }

    pub(super) fn install_credential_vault(
        &self,
        credential_vault: ApplicationCredentialVault,
    ) -> McpResult<()> {
        let mut current = self.credential_vault.lock().map_err(|_| storage_error())?;
        *current = Some(credential_vault);
        Ok(())
    }

    #[cfg(test)]
    pub(super) fn seed_route_contract_fixture(&self, scope: &McpScope) -> Result<(), String> {
        self.store.seed_route_contract_fixture(scope)
    }

    pub(super) async fn list_tools(
        &self,
        scope: &McpScope,
        server_id: &str,
    ) -> McpResult<Vec<Value>> {
        let server = self.required_server(scope, server_id)?;
        let result = self
            .request(&server, "tools/list", serde_json::json!({}))
            .await?;
        let tools = result
            .get("tools")
            .and_then(Value::as_array)
            .cloned()
            .ok_or_else(|| {
                McpSupervisorError::new(
                    "local_mcp_malformed_response",
                    "MCP tools/list response is malformed",
                )
            })?;
        self.store
            .record_tools_and_apps(&server, &tools)
            .map_err(|_| storage_error())?;
        Ok(tools)
    }

    pub(super) async fn call_tool(
        &self,
        scope: &McpScope,
        server_id: &str,
        tool_name: &str,
        arguments: Value,
        idempotency_key: Option<&str>,
    ) -> McpResult<McpToolCallOutcome> {
        validate_identifier(tool_name, "local_mcp_tool_name_invalid")?;
        if !arguments.is_object() {
            return Err(McpSupervisorError::new(
                "local_mcp_arguments_invalid",
                "MCP tool arguments must be an object",
            ));
        }
        let server = self.required_server(scope, server_id)?;
        let request_hash = value_hash(&serde_json::json!({
            "server_id": server_id,
            "tool_name": tool_name,
            "arguments": arguments,
        }));
        if let Some(key) = idempotency_key {
            validate_idempotency_key(key)?;
            if let Some(replay) = self.store.tool_call_receipt(scope, key, &request_hash)? {
                return Ok(McpToolCallOutcome {
                    result: replay,
                    duplicate: true,
                });
            }
        }
        let result = self
            .request(
                &server,
                "tools/call",
                serde_json::json!({ "name": tool_name, "arguments": arguments }),
            )
            .await?;
        if let Some(key) = idempotency_key {
            self.store
                .save_tool_call_receipt(scope, key, &request_hash, &server.id, &result)?;
        }
        Ok(McpToolCallOutcome {
            result,
            duplicate: false,
        })
    }

    pub(super) async fn list_resources(
        &self,
        scope: &McpScope,
        server_id: Option<&str>,
    ) -> McpResult<Vec<Value>> {
        let servers = if let Some(server_id) = server_id {
            vec![self.required_server(scope, server_id)?]
        } else {
            self.list_servers(scope)?
                .into_iter()
                .filter(|server| server.enabled)
                .collect()
        };
        let mut resources = Vec::new();
        for server in servers {
            let result = self
                .request(&server, "resources/list", serde_json::json!({}))
                .await?;
            let values = result
                .get("resources")
                .and_then(Value::as_array)
                .ok_or_else(|| {
                    McpSupervisorError::new(
                        "local_mcp_malformed_response",
                        "MCP resources/list response is malformed",
                    )
                })?;
            resources.extend(values.iter().cloned());
        }
        Ok(resources)
    }

    pub(super) async fn read_resource(
        &self,
        scope: &McpScope,
        server_id: &str,
        uri: &str,
    ) -> McpResult<Vec<Value>> {
        validate_resource_uri(uri)?;
        let server = self.required_server(scope, server_id)?;
        let result = self
            .request(&server, "resources/read", serde_json::json!({ "uri": uri }))
            .await?;
        result
            .get("contents")
            .and_then(Value::as_array)
            .cloned()
            .ok_or_else(|| {
                McpSupervisorError::new(
                    "local_mcp_malformed_response",
                    "MCP resources/read response is malformed",
                )
            })
    }

    fn required_server(&self, scope: &McpScope, server_id: &str) -> McpResult<McpServerDefinition> {
        let server = self
            .server(scope, server_id)?
            .ok_or_else(server_not_found)?;
        if !server.enabled {
            return Err(McpSupervisorError::new(
                "local_mcp_server_disabled",
                "MCP server is disabled",
            ));
        }
        if server.transport != McpTransport::Stdio {
            return Err(unsupported_transport(server.transport));
        }
        Ok(server)
    }

    async fn request(
        &self,
        server: &McpServerDefinition,
        method: &str,
        params: Value,
    ) -> McpResult<Value> {
        let runtime = self.runtime(&server.id)?;
        let credential_vault = self.credential_vault()?;
        let mut runtime = runtime.lock().await;
        runtime
            .request(
                server,
                &self.workspace_root,
                credential_vault.as_ref(),
                method,
                params,
                self.limits,
            )
            .await
            .inspect_err(|error| {
                let _ = self.store.record_runtime_error(server, error.reason_code());
            })
    }

    async fn ensure_initialized(&self, server: &McpServerDefinition) -> McpResult<()> {
        let runtime = self.runtime(&server.id)?;
        let credential_vault = self.credential_vault()?;
        let mut runtime = runtime.lock().await;
        let initialized = runtime
            .ensure_initialized(
                server,
                &self.workspace_root,
                credential_vault.as_ref(),
                self.limits,
            )
            .await
            .inspect_err(|error| {
                let _ = self.store.record_runtime_error(server, error.reason_code());
            })?;
        self.store
            .record_runtime_ready(server, &initialized.server_info)
            .map_err(|_| storage_error())
    }

    fn runtime(&self, server_id: &str) -> McpResult<Arc<AsyncMutex<StdioRuntime>>> {
        let mut runtimes = self.runtimes.lock().map_err(|_| storage_error())?;
        Ok(Arc::clone(
            runtimes
                .entry(server_id.to_string())
                .or_insert_with(|| Arc::new(AsyncMutex::new(StdioRuntime::new()))),
        ))
    }

    fn credential_vault(&self) -> McpResult<Option<ApplicationCredentialVault>> {
        self.credential_vault
            .lock()
            .map(|vault| vault.clone())
            .map_err(|_| storage_error())
    }
}

fn validate_scope(scope: &McpScope) -> McpResult<()> {
    validate_identifier(&scope.tenant_id, "local_mcp_tenant_id_invalid")?;
    validate_identifier(&scope.project_id, "local_mcp_project_id_invalid")
}

fn validate_definition(input: &McpServerDefinitionInput) -> McpResult<()> {
    validate_identifier(&input.name, "local_mcp_server_name_invalid")?;
    if input.command.is_empty() || input.command.len() > 64 {
        return Err(McpSupervisorError::new(
            "local_mcp_command_invalid",
            "MCP stdio command must contain direct argv entries",
        ));
    }
    for argument in &input.command {
        if argument.is_empty() || argument.len() > 4096 || argument.chars().any(char::is_control) {
            return Err(McpSupervisorError::new(
                "local_mcp_command_invalid",
                "MCP stdio command argv is invalid",
            ));
        }
    }
    for (name, reference) in &input.vault_env_refs {
        if !valid_env_name(name) || reference.is_empty() || reference.len() > 512 {
            return Err(McpSupervisorError::new(
                "local_mcp_environment_invalid",
                "MCP environment vault reference is invalid",
            ));
        }
    }
    if let Some(cwd) = input.cwd.as_deref() {
        validate_relative_path(cwd)?;
    }
    Ok(())
}

fn valid_env_name(name: &str) -> bool {
    let mut bytes = name.bytes();
    matches!(bytes.next(), Some(b'A'..=b'Z' | b'a'..=b'z' | b'_'))
        && bytes.all(|value| value.is_ascii_alphanumeric() || value == b'_')
}

fn validate_relative_path(value: &str) -> McpResult<()> {
    let path = Path::new(value);
    if value.is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|component| !matches!(component, Component::Normal(_) | Component::CurDir))
    {
        return Err(McpSupervisorError::new(
            "local_mcp_cwd_invalid",
            "MCP working directory must stay inside the native workspace",
        ));
    }
    Ok(())
}

fn validate_identifier(value: &str, reason_code: &'static str) -> McpResult<()> {
    if value.is_empty() || value.len() > 200 || value.chars().any(char::is_control) {
        return Err(McpSupervisorError::new(
            reason_code,
            "MCP identifier is invalid",
        ));
    }
    Ok(())
}

fn validate_idempotency_key(value: &str) -> McpResult<()> {
    if value.is_empty() || value.len() > 200 || value.chars().any(char::is_control) {
        return Err(McpSupervisorError::new(
            "local_mcp_idempotency_key_invalid",
            "MCP idempotency key is invalid",
        ));
    }
    Ok(())
}

fn validate_resource_uri(value: &str) -> McpResult<()> {
    if value.is_empty() || value.len() > 4096 || value.chars().any(char::is_control) {
        return Err(McpSupervisorError::new(
            "local_mcp_resource_uri_invalid",
            "MCP resource URI is invalid",
        ));
    }
    Ok(())
}

fn definition_hash(scope: &McpScope, input: &McpServerDefinitionInput) -> String {
    value_hash(&serde_json::json!({
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "name": input.name,
        "description": input.description,
        "transport": input.transport.as_str(),
        "command": input.command,
        "cwd": input.cwd,
        "vault_env_refs": input.vault_env_refs,
        "enabled": input.enabled,
    }))
}

fn value_hash(value: &Value) -> String {
    let mut hasher = Sha256::new();
    hasher.update(value.to_string());
    format!("{:x}", hasher.finalize())
}

fn unsupported_transport(transport: McpTransport) -> McpSupervisorError {
    match transport {
        McpTransport::Stdio => {
            McpSupervisorError::new("local_mcp_transport_invalid", "MCP transport is invalid")
        }
        McpTransport::Http | McpTransport::Sse => McpSupervisorError::new(
            "local_mcp_http_transport_unavailable",
            "local MCP HTTP and SSE transports are unavailable",
        ),
        McpTransport::Websocket => McpSupervisorError::new(
            "local_mcp_websocket_transport_unavailable",
            "local MCP WebSocket transport is unavailable",
        ),
    }
}

fn server_not_found() -> McpSupervisorError {
    McpSupervisorError::new("local_mcp_server_not_found", "MCP server was not found")
}

fn storage_error() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_storage_unavailable",
        "local MCP storage is unavailable",
    )
}
