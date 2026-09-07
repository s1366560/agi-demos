use std::{
    collections::{BTreeMap, HashMap},
    fmt,
    path::{Component, Path, PathBuf},
    sync::{Arc, Mutex},
    time::Duration,
};

use futures_util::{stream, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use tokio::sync::Mutex as AsyncMutex;

use crate::application_vault::ApplicationCredentialVault;

use super::DesktopSessionStore;

#[cfg(test)]
mod hardening_tests;
mod http;
mod http_session;
mod remote_common;
mod stdio;
mod store;
mod tool_call_lease;
mod websocket;

use http::{HttpRuntime, SseRuntime};
pub(super) use remote_common::credential_reference;
#[cfg(test)]
pub(super) use remote_common::remote_credential_reference;
use remote_common::{
    request_timeout, validate_remote_credential_bindings, validate_remote_header_names,
    validate_remote_input, InitializedServer,
};
use stdio::StdioRuntime;
use store::{CredentialStageStatus, McpStore};
use websocket::WebSocketRuntime;

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

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub(super) enum McpCredentialKind {
    Env,
    Header,
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

#[derive(Clone, Debug, PartialEq)]
pub(super) struct McpCredentialProvisionInput {
    pub(super) server_name: String,
    pub(super) transport: McpTransport,
    pub(super) command: Vec<String>,
    pub(super) cwd: Option<String>,
    pub(super) kind: McpCredentialKind,
    pub(super) name: String,
    pub(super) mutation_idempotency_key: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct McpCredentialProvisionOutcome {
    pub(super) duplicate: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct McpServerDeletionOutcome {
    pub(super) id: String,
    pub(super) revision: u64,
    pub(super) duplicate: bool,
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
    pub(super) content: Vec<Value>,
    pub(super) is_error: bool,
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
    pub(super) max_frame_bytes: usize,
    pub(super) max_aggregate_bytes: usize,
    pub(super) tool_call_lease_duration: Duration,
    pub(super) tool_call_wait_timeout: Duration,
    pub(super) tool_call_poll_interval: Duration,
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
            max_frame_bytes: 1024 * 1024,
            max_aggregate_bytes: 4 * 1024 * 1024,
            tool_call_lease_duration: Duration::from_secs(45),
            tool_call_wait_timeout: Duration::from_secs(2),
            tool_call_poll_interval: Duration::from_millis(25),
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

#[derive(Clone)]
pub(super) struct McpSupervisor {
    store: McpStore,
    workspace_root: PathBuf,
    credential_vault: Arc<Mutex<Option<ApplicationCredentialVault>>>,
    limits: SupervisorLimits,
    runtimes: Arc<Mutex<HashMap<String, Arc<AsyncMutex<McpRuntime>>>>>,
}

enum McpRuntime {
    Stdio(Box<StdioRuntime>),
    Http(Box<HttpRuntime>),
    Sse(Box<SseRuntime>),
    Websocket(Box<WebSocketRuntime>),
}

impl McpRuntime {
    fn new(transport: McpTransport) -> Self {
        match transport {
            McpTransport::Stdio => Self::Stdio(Box::new(StdioRuntime::new())),
            McpTransport::Http => Self::Http(Box::new(HttpRuntime::new())),
            McpTransport::Sse => Self::Sse(Box::new(SseRuntime::new())),
            McpTransport::Websocket => Self::Websocket(Box::new(WebSocketRuntime::new())),
        }
    }

    async fn ensure_initialized(
        &mut self,
        server: &McpServerDefinition,
        workspace_root: &Path,
        credential_vault: Option<&ApplicationCredentialVault>,
        limits: SupervisorLimits,
    ) -> McpResult<InitializedServer> {
        match self {
            Self::Stdio(runtime) => {
                runtime
                    .ensure_initialized(server, workspace_root, credential_vault, limits)
                    .await
            }
            Self::Http(runtime) => {
                runtime
                    .ensure_initialized(server, credential_vault, limits)
                    .await
            }
            Self::Sse(runtime) => {
                runtime
                    .ensure_initialized(server, credential_vault, limits)
                    .await
            }
            Self::Websocket(runtime) => {
                runtime
                    .ensure_initialized(server, credential_vault, limits)
                    .await
            }
        }
    }

    async fn request(
        &mut self,
        server: &McpServerDefinition,
        workspace_root: &Path,
        credential_vault: Option<&ApplicationCredentialVault>,
        method: &str,
        params: Value,
        limits: SupervisorLimits,
    ) -> McpResult<Value> {
        match self {
            Self::Stdio(runtime) => {
                runtime
                    .request(
                        server,
                        workspace_root,
                        credential_vault,
                        method,
                        params,
                        limits,
                    )
                    .await
            }
            Self::Http(runtime) => {
                runtime
                    .request(server, credential_vault, method, params, limits)
                    .await
            }
            Self::Sse(runtime) => {
                runtime
                    .request(server, credential_vault, method, params, limits)
                    .await
            }
            Self::Websocket(runtime) => {
                runtime
                    .request(server, credential_vault, method, params, limits)
                    .await
            }
        }
    }
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
            credential_vault: Arc::new(Mutex::new(credential_vault)),
            limits,
            runtimes: Arc::new(Mutex::new(HashMap::new())),
        })
    }

    pub(super) fn create_server(
        &self,
        scope: &McpScope,
        input: McpServerDefinitionInput,
        idempotency_key: &str,
    ) -> McpResult<McpServerDefinition> {
        validate_scope(scope)?;
        validate_definition(&input)?;
        validate_remote_credential_bindings(scope, &input)?;
        validate_idempotency_key(idempotency_key)?;
        let request_hash = definition_hash(scope, &input);
        let _credential_guard = self.credential_vault.lock().map_err(|_| storage_error())?;
        self.store
            .create_server(scope, &input, idempotency_key, &request_hash)
    }

    pub(super) fn update_server(
        &self,
        scope: &McpScope,
        server_id: &str,
        input: McpServerDefinitionInput,
        expected_revision: u64,
        idempotency_key: &str,
    ) -> McpResult<McpServerDefinition> {
        validate_scope(scope)?;
        validate_identifier(server_id, "local_mcp_server_id_invalid")?;
        validate_definition(&input)?;
        validate_remote_credential_bindings(scope, &input)?;
        validate_expected_revision(expected_revision)?;
        validate_idempotency_key(idempotency_key)?;
        let vault_guard = self.credential_vault.lock().map_err(|_| storage_error())?;
        let request_hash = server_update_hash(scope, server_id, expected_revision, &input);
        let stored = self.store.update_server(
            scope,
            server_id,
            &input,
            expected_revision,
            idempotency_key,
            &request_hash,
        )?;
        self.evict_runtime(server_id)?;
        if let Err(error) = self.drain_pending_credential_cleanup_locked(vault_guard.as_ref()) {
            tracing::warn!(
                reason_code = error.reason_code(),
                "deferred MCP credential cleanup after server update"
            );
        }
        Ok(stored.server)
    }

    pub(super) fn delete_server(
        &self,
        scope: &McpScope,
        server_id: &str,
        expected_revision: u64,
        idempotency_key: &str,
    ) -> McpResult<McpServerDeletionOutcome> {
        validate_scope(scope)?;
        validate_identifier(server_id, "local_mcp_server_id_invalid")?;
        validate_expected_revision(expected_revision)?;
        validate_idempotency_key(idempotency_key)?;
        let request_hash = server_delete_hash(scope, server_id, expected_revision);
        let vault_guard = self.credential_vault.lock().map_err(|_| storage_error())?;
        let stored = self.store.delete_server(
            scope,
            server_id,
            expected_revision,
            idempotency_key,
            &request_hash,
        )?;
        self.evict_runtime(server_id)?;
        if let Err(error) = self.drain_pending_credential_cleanup_locked(vault_guard.as_ref()) {
            tracing::warn!(
                reason_code = error.reason_code(),
                "deferred MCP credential cleanup after server deletion"
            );
        }
        Ok(McpServerDeletionOutcome {
            id: stored.server.id,
            revision: stored.server.revision,
            duplicate: stored.duplicate,
        })
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
        let servers = self.store.enabled_servers()?;
        let supervisor = self.clone();
        let _task = tokio::spawn(async move {
            stream::iter(servers)
                .for_each_concurrent(4, move |server| {
                    let supervisor = supervisor.clone();
                    async move {
                        let _ = supervisor.ensure_initialized(&server).await;
                    }
                })
                .await;
        });
        Ok(())
    }

    pub(super) fn prepare_startup_recovery(&self) -> McpResult<()> {
        let vault_guard = self.credential_vault.lock().map_err(|_| storage_error())?;
        self.store.abandon_unbound_credential_stages()?;
        if let Err(error) = self.drain_pending_credential_cleanup_locked(vault_guard.as_ref()) {
            tracing::warn!(
                reason_code = error.reason_code(),
                "deferred MCP credential cleanup during startup recovery"
            );
        }
        drop(vault_guard);
        self.store.mark_enabled_recovery_pending()
    }

    pub(super) fn install_credential_vault(
        &self,
        credential_vault: ApplicationCredentialVault,
    ) -> McpResult<()> {
        let mut current = self.credential_vault.lock().map_err(|_| storage_error())?;
        *current = Some(credential_vault);
        Ok(())
    }

    pub(super) fn provision_credential(
        &self,
        scope: &McpScope,
        input: &McpCredentialProvisionInput,
        secret: &str,
        idempotency_key: &str,
    ) -> McpResult<McpCredentialProvisionOutcome> {
        validate_scope(scope)?;
        validate_identifier(&input.server_name, "local_mcp_server_name_invalid")?;
        validate_idempotency_key(idempotency_key)?;
        validate_credential_provision_input(input)?;
        if secret.is_empty() || secret.len() > 64 * 1024 || secret.contains('\0') {
            return Err(McpSupervisorError::new(
                "local_mcp_credential_secret_invalid",
                "MCP credential secret is invalid",
            ));
        }
        if input.kind == McpCredentialKind::Header
            && reqwest::header::HeaderValue::from_bytes(secret.as_bytes()).is_err()
        {
            return Err(McpSupervisorError::new(
                "local_mcp_credential_secret_invalid",
                "MCP credential secret is invalid",
            ));
        }
        let reference = credential_reference(
            scope,
            &input.server_name,
            input.transport,
            &input.command,
            input.cwd.as_deref(),
            input.kind,
            &input.name,
        )?;
        let request_hash = credential_provision_hash(scope, input, secret);
        let vault_guard = self.credential_vault.lock().map_err(|_| storage_error())?;
        let vault = vault_guard.as_ref().ok_or_else(|| {
            McpSupervisorError::new(
                "local_mcp_vault_reference_unavailable",
                "MCP vault reference is unavailable",
            )
        })?;
        if let Some(mutation_idempotency_key) = input.mutation_idempotency_key.as_deref() {
            validate_idempotency_key(mutation_idempotency_key)?;
            let staged_reference = staged_credential_reference(
                &reference,
                mutation_idempotency_key,
                idempotency_key,
                &request_hash,
            );
            let reservation = self.store.reserve_credential_stage(
                scope,
                idempotency_key,
                mutation_idempotency_key,
                &request_hash,
                &reference,
                &staged_reference,
            )?;
            if reservation.status.stores_secret() {
                vault
                    .put(&reservation.staged_reference, secret)
                    .map_err(|_| storage_error())?;
                if reservation.status != CredentialStageStatus::Active {
                    self.store.mark_credential_stage_ready(
                        scope,
                        idempotency_key,
                        &request_hash,
                    )?;
                }
            }
            return Ok(McpCredentialProvisionOutcome {
                duplicate: reservation.duplicate,
            });
        }
        if let Some((stored_hash, stored_reference, is_current_binding)) =
            self.store.credential_receipt(scope, idempotency_key)?
        {
            if stored_hash != request_hash || stored_reference != reference {
                return Err(McpSupervisorError::new(
                    "local_mcp_idempotency_conflict",
                    "MCP idempotency key is already bound to a different request",
                ));
            }
            if is_current_binding {
                vault.put(&reference, secret).map_err(|_| storage_error())?;
            }
            return Ok(McpCredentialProvisionOutcome { duplicate: true });
        }
        self.store
            .record_credential_receipt(scope, idempotency_key, &request_hash, &reference)?;
        vault.put(&reference, secret).map_err(|_| storage_error())?;
        Ok(McpCredentialProvisionOutcome { duplicate: false })
    }

    #[cfg(test)]
    pub(super) fn seed_route_contract_fixture(&self, scope: &McpScope) -> Result<(), String> {
        self.store.seed_route_contract_fixture(scope)
    }

    #[cfg(test)]
    pub(in crate::local_runtime) fn staged_credential_reference_for_test(
        &self,
        scope: &McpScope,
        provision_idempotency_key: &str,
    ) -> McpResult<Option<String>> {
        self.store
            .staged_credential_reference(scope, provision_idempotency_key)
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
        idempotency_key: &str,
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
        validate_idempotency_key(idempotency_key)?;
        tool_call_lease::execute_tool_call(
            self,
            scope,
            &server,
            tool_name,
            arguments,
            idempotency_key,
            &request_hash,
        )
        .await
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
        Ok(server)
    }

    async fn request(
        &self,
        server: &McpServerDefinition,
        method: &str,
        params: Value,
    ) -> McpResult<Value> {
        let runtime = self.runtime(server)?;
        let credential_vault = self.credential_vault()?;
        let operation_timeout = self
            .limits
            .initialize_timeout
            .saturating_add(self.limits.request_timeout);
        let result = tokio::time::timeout(operation_timeout, async {
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
        })
        .await
        .unwrap_or_else(|_| Err(request_timeout()));
        result.inspect_err(|error| {
            let _ = self.store.record_runtime_error(server, error.reason_code());
        })
    }

    async fn ensure_initialized(&self, server: &McpServerDefinition) -> McpResult<()> {
        let runtime = self.runtime(server)?;
        let credential_vault = self.credential_vault()?;
        let initialized = tokio::time::timeout(self.limits.initialize_timeout, async {
            let mut runtime = runtime.lock().await;
            runtime
                .ensure_initialized(
                    server,
                    &self.workspace_root,
                    credential_vault.as_ref(),
                    self.limits,
                )
                .await
        })
        .await
        .unwrap_or_else(|_| Err(request_timeout()))
        .inspect_err(|error| {
            let _ = self.store.record_runtime_error(server, error.reason_code());
        })?;
        self.store
            .record_runtime_ready(server, &initialized.server_info)
            .map_err(|_| storage_error())
    }

    fn runtime(&self, server: &McpServerDefinition) -> McpResult<Arc<AsyncMutex<McpRuntime>>> {
        let mut runtimes = self.runtimes.lock().map_err(|_| storage_error())?;
        Ok(Arc::clone(
            runtimes
                .entry(server.id.clone())
                .or_insert_with(|| Arc::new(AsyncMutex::new(McpRuntime::new(server.transport)))),
        ))
    }

    fn credential_vault(&self) -> McpResult<Option<ApplicationCredentialVault>> {
        self.credential_vault
            .lock()
            .map(|vault| vault.clone())
            .map_err(|_| storage_error())
    }

    fn drain_pending_credential_cleanup_locked(
        &self,
        credential_vault: Option<&ApplicationCredentialVault>,
    ) -> McpResult<()> {
        for cleanup in self.store.pending_credential_cleanups()? {
            if self.store.credential_cleanup_reference_is_live(&cleanup)? {
                self.store.complete_credential_cleanup(&cleanup)?;
                continue;
            }
            let Some(vault) = credential_vault else {
                self.store.record_credential_cleanup_failure(
                    &cleanup,
                    "local_mcp_vault_reference_unavailable",
                )?;
                continue;
            };
            if vault.clear(&cleanup.binding_reference).is_ok() {
                self.store.complete_credential_cleanup(&cleanup)?;
            } else {
                self.store
                    .record_credential_cleanup_failure(&cleanup, "local_mcp_storage_unavailable")?;
            }
        }
        Ok(())
    }

    fn evict_runtime(&self, server_id: &str) -> McpResult<()> {
        self.runtimes
            .lock()
            .map_err(|_| storage_error())?
            .remove(server_id);
        Ok(())
    }
}

fn validate_scope(scope: &McpScope) -> McpResult<()> {
    validate_identifier(&scope.tenant_id, "local_mcp_tenant_id_invalid")?;
    validate_identifier(&scope.project_id, "local_mcp_project_id_invalid")
}

fn validate_definition(input: &McpServerDefinitionInput) -> McpResult<()> {
    validate_identifier(&input.name, "local_mcp_server_name_invalid")?;
    match input.transport {
        McpTransport::Stdio => {
            if input.command.is_empty() || input.command.len() > 64 {
                return Err(McpSupervisorError::new(
                    "local_mcp_command_invalid",
                    "MCP stdio command must contain direct argv entries",
                ));
            }
            for argument in &input.command {
                if argument.is_empty()
                    || argument.len() > 4096
                    || argument.chars().any(char::is_control)
                {
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
        }
        McpTransport::Http | McpTransport::Sse | McpTransport::Websocket => {
            validate_remote_input(input.transport, &input.command)?;
            validate_remote_header_names(&input.vault_env_refs)?;
            if input.cwd.is_some() {
                return Err(McpSupervisorError::new(
                    "local_mcp_cwd_invalid",
                    "MCP remote transports do not accept a local working directory",
                ));
            }
        }
    }
    Ok(())
}

fn validate_credential_provision_input(input: &McpCredentialProvisionInput) -> McpResult<()> {
    let definition = McpServerDefinitionInput {
        name: input.server_name.clone(),
        description: None,
        transport: input.transport,
        command: input.command.clone(),
        cwd: input.cwd.clone(),
        vault_env_refs: BTreeMap::new(),
        enabled: true,
    };
    validate_definition(&definition)?;
    match (input.transport, input.kind) {
        (McpTransport::Stdio, McpCredentialKind::Env) => {
            if !valid_env_name(&input.name) {
                return Err(McpSupervisorError::new(
                    "local_mcp_environment_invalid",
                    "MCP environment credential name is invalid",
                ));
            }
        }
        (
            McpTransport::Http | McpTransport::Sse | McpTransport::Websocket,
            McpCredentialKind::Header,
        ) => {
            let references = BTreeMap::from([(input.name.clone(), "pending".to_string())]);
            validate_remote_header_names(&references)?;
        }
        _ => {
            return Err(McpSupervisorError::new(
                "local_mcp_credential_kind_invalid",
                "MCP credential kind does not match the selected transport",
            ));
        }
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

fn validate_expected_revision(value: u64) -> McpResult<()> {
    if value == 0 {
        return Err(McpSupervisorError::new(
            "local_mcp_revision_invalid",
            "MCP server revision must be a positive integer",
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

fn validate_tool_call_result(result: &Value) -> McpResult<(Vec<Value>, bool)> {
    let content = result
        .get("content")
        .and_then(Value::as_array)
        .cloned()
        .ok_or_else(|| {
            McpSupervisorError::new(
                "local_mcp_malformed_response",
                "MCP tools/call content is malformed",
            )
        })?;
    let is_error = match result.get("isError") {
        Some(value) => value.as_bool().ok_or_else(|| {
            McpSupervisorError::new(
                "local_mcp_malformed_response",
                "MCP tools/call error state is malformed",
            )
        })?,
        None => false,
    };
    Ok((content, is_error))
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

fn server_update_hash(
    scope: &McpScope,
    server_id: &str,
    expected_revision: u64,
    input: &McpServerDefinitionInput,
) -> String {
    value_hash(&serde_json::json!({
        "operation": "update_server",
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "server_id": server_id,
        "expected_revision": expected_revision,
        "name": input.name,
        "description": input.description,
        "transport": input.transport.as_str(),
        "command": input.command,
        "cwd": input.cwd,
        "vault_env_refs": input.vault_env_refs,
        "enabled": input.enabled,
    }))
}

fn server_delete_hash(scope: &McpScope, server_id: &str, expected_revision: u64) -> String {
    value_hash(&serde_json::json!({
        "operation": "delete_server",
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "server_id": server_id,
        "expected_revision": expected_revision,
    }))
}

fn value_hash(value: &Value) -> String {
    let mut hasher = Sha256::new();
    hasher.update(value.to_string());
    format!("{:x}", hasher.finalize())
}

fn credential_provision_hash(
    scope: &McpScope,
    input: &McpCredentialProvisionInput,
    secret: &str,
) -> String {
    let secret_hash = {
        let mut hasher = Sha256::new();
        hasher.update(secret.as_bytes());
        format!("{:x}", hasher.finalize())
    };
    value_hash(&serde_json::json!({
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "server_name": input.server_name,
        "transport": input.transport.as_str(),
        "command": input.command,
        "cwd": input.cwd,
        "credential_kind": input.kind,
        "credential_name": input.name,
        "secret_hash": secret_hash,
    }))
}

fn staged_credential_reference(
    logical_reference: &str,
    mutation_idempotency_key: &str,
    provision_idempotency_key: &str,
    request_hash: &str,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"memstack-desktop-mcp-credential-stage-v2\0");
    hasher.update(logical_reference.as_bytes());
    hasher.update(b"\0");
    hasher.update(mutation_idempotency_key.as_bytes());
    hasher.update(b"\0");
    hasher.update(provision_idempotency_key.as_bytes());
    hasher.update(b"\0");
    hasher.update(request_hash.as_bytes());
    format!("{logical_reference}.stage.v2.{:x}", hasher.finalize())
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
