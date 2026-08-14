use std::{
    io,
    path::{Path, PathBuf},
    process::Stdio,
    time::Instant,
};

use serde_json::{json, Value};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
    time::timeout,
};

use crate::application_vault::ApplicationCredentialVault;

use super::{
    remote_common::{
        credential_reference, credential_reference_is_scoped, elicitation_unavailable,
        server_request_rejection, unsupported_client_request, InitializedServer,
    },
    McpCredentialKind, McpResult, McpScope, McpServerDefinition, McpSupervisorError,
    SupervisorLimits, MCP_PROTOCOL_VERSION,
};

struct StdioChild {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

pub(super) struct StdioRuntime {
    child: Option<StdioChild>,
    initialized_revision: Option<u64>,
    next_request_id: u64,
    consecutive_failures: u32,
    retry_after: Option<Instant>,
}

impl StdioRuntime {
    pub(super) fn new() -> Self {
        Self {
            child: None,
            initialized_revision: None,
            next_request_id: 1,
            consecutive_failures: 0,
            retry_after: None,
        }
    }

    pub(super) async fn ensure_initialized(
        &mut self,
        server: &McpServerDefinition,
        workspace_root: &Path,
        credential_vault: Option<&ApplicationCredentialVault>,
        limits: SupervisorLimits,
    ) -> McpResult<InitializedServer> {
        if self.initialized_revision == Some(server.revision) {
            match self.child_is_running() {
                Ok(true) => {
                    return Ok(InitializedServer {
                        server_info: server.server_info.clone().unwrap_or_else(|| json!({})),
                    });
                }
                Ok(false) => {}
                Err(error) => {
                    self.fail(limits).await;
                    return Err(error);
                }
            }
        }
        self.stop().await;
        self.enforce_backoff()?;
        let child = match spawn_child(server, workspace_root, credential_vault) {
            Ok(child) => child,
            Err(error) => {
                self.fail(limits).await;
                return Err(error);
            }
        };
        self.child = Some(child);

        let initialize = self
            .request_inner(
                "initialize",
                json!({
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "agistack-desktop",
                        "version": env!("CARGO_PKG_VERSION"),
                    },
                }),
                limits.initialize_timeout,
                limits,
            )
            .await;
        let initialize = match initialize {
            Ok(result) => result,
            Err(error) => {
                self.fail(limits).await;
                return Err(error);
            }
        };
        let protocol_version = initialize
            .get("protocolVersion")
            .and_then(Value::as_str)
            .ok_or_else(malformed_response)?;
        if protocol_version.is_empty() {
            self.fail(limits).await;
            return Err(malformed_response());
        }
        let server_info = initialize
            .get("serverInfo")
            .filter(|value| value.is_object())
            .cloned()
            .ok_or_else(malformed_response)?;
        if let Err(error) = self
            .send_notification("notifications/initialized", json!({}), limits)
            .await
        {
            self.fail(limits).await;
            return Err(error);
        }
        self.initialized_revision = Some(server.revision);
        self.consecutive_failures = 0;
        self.retry_after = None;
        Ok(InitializedServer { server_info })
    }

    pub(super) async fn request(
        &mut self,
        server: &McpServerDefinition,
        workspace_root: &Path,
        credential_vault: Option<&ApplicationCredentialVault>,
        method: &str,
        params: Value,
        limits: SupervisorLimits,
    ) -> McpResult<Value> {
        self.ensure_initialized(server, workspace_root, credential_vault, limits)
            .await?;
        match self
            .request_inner(method, params, limits.request_timeout, limits)
            .await
        {
            Ok(result) => Ok(result),
            Err(error) => {
                self.fail(limits).await;
                Err(error)
            }
        }
    }

    fn child_is_running(&mut self) -> McpResult<bool> {
        let Some(child) = self.child.as_mut() else {
            return Ok(false);
        };
        match child.child.try_wait() {
            Ok(None) => Ok(true),
            Ok(Some(_)) => {
                self.child = None;
                self.initialized_revision = None;
                Err(process_exited())
            }
            Err(_) => Err(process_exited()),
        }
    }

    async fn request_inner(
        &mut self,
        method: &str,
        params: Value,
        request_timeout: std::time::Duration,
        limits: SupervisorLimits,
    ) -> McpResult<Value> {
        let request_id = self.next_request_id;
        self.next_request_id = self.next_request_id.saturating_add(1);
        let request = json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        });
        self.write_message(&request, limits).await?;
        timeout(
            request_timeout,
            read_response(
                self.required_child()?,
                request_id,
                limits.max_response_bytes,
            ),
        )
        .await
        .map_err(|_| {
            McpSupervisorError::new("local_mcp_request_timeout", "MCP request timed out")
        })?
    }

    async fn send_notification(
        &mut self,
        method: &str,
        params: Value,
        limits: SupervisorLimits,
    ) -> McpResult<()> {
        self.write_message(
            &json!({
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }),
            limits,
        )
        .await
    }

    async fn write_message(&mut self, message: &Value, limits: SupervisorLimits) -> McpResult<()> {
        let mut encoded = serde_json::to_vec(message).map_err(|_| malformed_request())?;
        if encoded.len() > limits.max_request_bytes {
            return Err(McpSupervisorError::new(
                "local_mcp_request_too_large",
                "MCP request exceeds the local payload limit",
            ));
        }
        encoded.push(b'\n');
        let child = self.required_child()?;
        child
            .stdin
            .write_all(&encoded)
            .await
            .map_err(|_| process_exited())?;
        child.stdin.flush().await.map_err(|_| process_exited())
    }

    fn required_child(&mut self) -> McpResult<&mut StdioChild> {
        self.child.as_mut().ok_or_else(process_exited)
    }

    fn enforce_backoff(&self) -> McpResult<()> {
        if self
            .retry_after
            .is_some_and(|retry_after| Instant::now() < retry_after)
        {
            return Err(McpSupervisorError::new(
                "local_mcp_restart_backoff",
                "MCP server restart is waiting for bounded backoff",
            ));
        }
        Ok(())
    }

    async fn fail(&mut self, limits: SupervisorLimits) {
        self.stop().await;
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);
        let shift = self.consecutive_failures.saturating_sub(1).min(10);
        let multiplier = 1_u32.checked_shl(shift).unwrap_or(u32::MAX);
        let delay = limits
            .retry_base
            .saturating_mul(multiplier)
            .min(limits.retry_max);
        self.retry_after = Some(Instant::now() + delay);
    }

    async fn stop(&mut self) {
        self.initialized_revision = None;
        if let Some(mut child) = self.child.take() {
            let _ = child.child.kill().await;
            let _ = child.child.wait().await;
        }
    }
}

fn spawn_child(
    server: &McpServerDefinition,
    workspace_root: &Path,
    credential_vault: Option<&ApplicationCredentialVault>,
) -> McpResult<StdioChild> {
    let executable = PathBuf::from(
        server
            .command
            .first()
            .ok_or_else(|| {
                McpSupervisorError::new("local_mcp_command_invalid", "MCP stdio command is empty")
            })?
            .as_str(),
    );
    if !executable.is_absolute() || !executable.is_file() {
        return Err(McpSupervisorError::new(
            "local_mcp_executable_invalid",
            "MCP executable must be an existing absolute file",
        ));
    }
    let cwd = resolve_cwd(workspace_root, server.cwd.as_deref())?;
    let mut command = Command::new(executable);
    command
        .args(server.command.iter().skip(1))
        .current_dir(cwd)
        .env_clear()
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    for (name, reference) in &server.vault_env_refs {
        let expected = credential_reference(
            &McpScope {
                tenant_id: server.tenant_id.clone(),
                project_id: server.project_id.clone(),
            },
            &server.name,
            server.transport,
            &server.command,
            server.cwd.as_deref(),
            McpCredentialKind::Env,
            name,
        )?;
        if !credential_reference_is_scoped(&expected, reference) {
            return Err(McpSupervisorError::new(
                "local_mcp_remote_credential_scope_invalid",
                "MCP credential reference is outside its tenant, project, server, or target scope",
            ));
        }
        let value = credential_vault
            .ok_or_else(vault_unavailable)?
            .get(reference)
            .map_err(|_| vault_unavailable())?
            .ok_or_else(vault_unavailable)?;
        command.env(name, value);
    }
    let mut child = command.spawn().map_err(|_| {
        McpSupervisorError::new(
            "local_mcp_process_start_failed",
            "MCP stdio process could not be started",
        )
    })?;
    let stdin = child.stdin.take().ok_or_else(process_exited)?;
    let stdout = child.stdout.take().ok_or_else(process_exited)?;
    Ok(StdioChild {
        child,
        stdin,
        stdout: BufReader::new(stdout),
    })
}

fn resolve_cwd(workspace_root: &Path, requested: Option<&str>) -> McpResult<PathBuf> {
    let candidate = workspace_root.join(requested.unwrap_or("."));
    let resolved = candidate.canonicalize().map_err(|_| {
        McpSupervisorError::new(
            "local_mcp_cwd_invalid",
            "MCP working directory does not exist",
        )
    })?;
    if !resolved.starts_with(workspace_root) || !resolved.is_dir() {
        return Err(McpSupervisorError::new(
            "local_mcp_cwd_invalid",
            "MCP working directory escapes the native workspace",
        ));
    }
    Ok(resolved)
}

async fn read_response(
    child: &mut StdioChild,
    request_id: u64,
    max_response_bytes: usize,
) -> McpResult<Value> {
    for _ in 0..64 {
        let line = read_bounded_line(&mut child.stdout, max_response_bytes)
            .await
            .map_err(|error| {
                if error.kind() == io::ErrorKind::UnexpectedEof {
                    process_exited()
                } else if error.kind() == io::ErrorKind::InvalidData {
                    McpSupervisorError::new(
                        "local_mcp_response_too_large",
                        "MCP response exceeds the local payload limit",
                    )
                } else {
                    process_exited()
                }
            })?;
        let response: Value = serde_json::from_slice(&line).map_err(|_| malformed_response())?;
        if response.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
            return Err(malformed_response());
        }
        if let Some((rejection, elicitation)) = server_request_rejection(&response)? {
            let mut encoded = serde_json::to_vec(&rejection).map_err(|_| malformed_response())?;
            encoded.push(b'\n');
            child
                .stdin
                .write_all(&encoded)
                .await
                .map_err(|_| process_exited())?;
            child.stdin.flush().await.map_err(|_| process_exited())?;
            return Err(if elicitation {
                elicitation_unavailable()
            } else {
                unsupported_client_request()
            });
        }
        let Some(response_id) = response.get("id").and_then(Value::as_u64) else {
            continue;
        };
        if response_id != request_id {
            continue;
        }
        if response.get("error").is_some_and(|value| !value.is_null()) {
            return Err(McpSupervisorError::new(
                "local_mcp_json_rpc_error",
                "MCP server returned a JSON-RPC error",
            ));
        }
        return response
            .get("result")
            .cloned()
            .ok_or_else(malformed_response);
    }
    Err(McpSupervisorError::new(
        "local_mcp_response_correlation_failed",
        "MCP response did not match the request",
    ))
}

async fn read_bounded_line(
    reader: &mut BufReader<ChildStdout>,
    max_response_bytes: usize,
) -> io::Result<Vec<u8>> {
    let mut line = Vec::new();
    loop {
        let available = reader.fill_buf().await?;
        if available.is_empty() {
            return Err(io::Error::from(io::ErrorKind::UnexpectedEof));
        }
        let newline = available.iter().position(|value| *value == b'\n');
        let take = newline.map_or(available.len(), |index| index + 1);
        if line.len().saturating_add(take) > max_response_bytes {
            return Err(io::Error::from(io::ErrorKind::InvalidData));
        }
        line.extend_from_slice(&available[..take]);
        reader.consume(take);
        if newline.is_some() {
            while matches!(line.last(), Some(b'\n' | b'\r')) {
                line.pop();
            }
            return Ok(line);
        }
    }
}

fn malformed_request() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_request_invalid",
        "MCP request could not be encoded",
    )
}

fn malformed_response() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_malformed_response",
        "MCP server returned a malformed response",
    )
}

fn process_exited() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_process_exited",
        "MCP stdio process exited unexpectedly",
    )
}

fn vault_unavailable() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_vault_reference_unavailable",
        "MCP environment vault reference is unavailable",
    )
}
