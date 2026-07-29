use std::{
    net::{IpAddr, SocketAddr},
    str::FromStr,
    time::Duration,
};

use futures_util::StreamExt;
use reqwest::{
    header::{self, HeaderMap, HeaderName, HeaderValue},
    redirect::Policy,
    Client, Response,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::net::lookup_host;
use url::{Host, Url};
use zeroize::Zeroize;

use crate::application_vault::ApplicationCredentialVault;

use super::{
    valid_env_name, McpCredentialKind, McpResult, McpScope, McpServerDefinition,
    McpServerDefinitionInput, McpSupervisorError, McpTransport, SupervisorLimits,
};

pub(super) const STREAMABLE_HTTP_PROTOCOL_VERSION: &str = "2025-03-26";
pub(super) const MAX_CORRELATION_MESSAGES: usize = 64;

const RESERVED_REMOTE_HEADERS: [&str; 8] = [
    "accept",
    "connection",
    "content-length",
    "content-type",
    "host",
    "mcp-protocol-version",
    "mcp-session-id",
    "transfer-encoding",
];
const MCP_REMOTE_CREDENTIAL_PREFIX: &str = "mcp-remote-credential.v1";
const MCP_STDIO_CREDENTIAL_PREFIX: &str = "mcp-stdio-credential.v1";

#[derive(Clone)]
pub(super) struct ResolvedEndpoint {
    pub(super) url: Url,
    pub(super) host: String,
    pub(super) addresses: Vec<SocketAddr>,
}

pub(super) struct InitializedServer {
    pub(super) server_info: Value,
}

#[derive(Debug)]
pub(super) struct SseEvent {
    pub(super) event: Option<String>,
    pub(super) data: Vec<u8>,
}

#[derive(Default)]
pub(super) struct SseDecoder {
    line: Vec<u8>,
    event: Option<String>,
    data: Vec<u8>,
    has_data: bool,
    swallow_lf: bool,
}

impl SseDecoder {
    pub(super) fn push(
        &mut self,
        chunk: &[u8],
        max_frame_bytes: usize,
        max_aggregate_bytes: usize,
    ) -> McpResult<Vec<SseEvent>> {
        let mut events = Vec::new();
        let mut emitted_bytes = 0_usize;
        for byte in chunk.iter().copied() {
            if self.swallow_lf {
                self.swallow_lf = false;
                if byte == b'\n' {
                    continue;
                }
            }
            let event = match byte {
                b'\r' => {
                    self.swallow_lf = true;
                    self.finish_line(max_frame_bytes, max_aggregate_bytes)?
                }
                b'\n' => self.finish_line(max_frame_bytes, max_aggregate_bytes)?,
                value => {
                    self.line.push(value);
                    if self.line.len() > max_frame_bytes
                        || self.current_allocation() > max_aggregate_bytes
                    {
                        return Err(response_too_large());
                    }
                    None
                }
            };
            let Some(event) = event else {
                continue;
            };
            emitted_bytes = emitted_bytes
                .saturating_add(event.data.len())
                .saturating_add(event.event.as_ref().map_or(0, String::len));
            if events.len() >= MAX_CORRELATION_MESSAGES || emitted_bytes > max_aggregate_bytes {
                return Err(response_too_large());
            }
            events.push(event);
        }
        if self.current_allocation() > max_aggregate_bytes {
            return Err(response_too_large());
        }
        Ok(events)
    }

    fn finish_line(
        &mut self,
        max_frame_bytes: usize,
        max_aggregate_bytes: usize,
    ) -> McpResult<Option<SseEvent>> {
        let line = std::mem::take(&mut self.line);
        if line.is_empty() {
            if !self.has_data {
                self.event = None;
                return Ok(None);
            }
            self.has_data = false;
            return Ok(Some(SseEvent {
                event: self.event.take(),
                data: std::mem::take(&mut self.data),
            }));
        }
        if line.first() == Some(&b':') {
            return Ok(None);
        }
        let separator = line.iter().position(|byte| *byte == b':');
        let (field, raw_value) = separator.map_or((&line[..], &[][..]), |index| {
            (&line[..index], &line[index.saturating_add(1)..])
        });
        let value = raw_value.strip_prefix(b" ").unwrap_or(raw_value);
        if field == b"event" {
            self.event = Some(
                std::str::from_utf8(value)
                    .map_err(|_| malformed_response())?
                    .to_string(),
            );
        } else if field == b"data" {
            if self.has_data {
                self.data.push(b'\n');
            }
            self.data.extend_from_slice(value);
            self.has_data = true;
        }
        if self.data.len() > max_frame_bytes || self.current_allocation() > max_aggregate_bytes {
            return Err(response_too_large());
        }
        Ok(None)
    }

    fn current_allocation(&self) -> usize {
        self.line
            .len()
            .saturating_add(self.data.len())
            .saturating_add(self.event.as_ref().map_or(0, String::len))
    }
}

pub(super) fn validate_remote_definition(server: &McpServerDefinition) -> McpResult<Url> {
    if server.command.len() != 1 {
        return Err(endpoint_invalid());
    }
    let endpoint = server.command.first().ok_or_else(endpoint_invalid)?;
    validate_remote_url(endpoint, server.transport, false)
}

pub(super) fn validate_remote_input(transport: McpTransport, command: &[String]) -> McpResult<()> {
    if command.len() != 1 {
        return Err(endpoint_invalid());
    }
    validate_remote_url(&command[0], transport, false)?;
    Ok(())
}

pub(super) fn validate_remote_header_names(
    references: &std::collections::BTreeMap<String, String>,
) -> McpResult<()> {
    for (name, reference) in references {
        let parsed = HeaderName::from_str(name).map_err(|_| remote_header_invalid())?;
        if RESERVED_REMOTE_HEADERS.contains(&parsed.as_str())
            || reference.is_empty()
            || reference.len() > 512
        {
            return Err(remote_header_invalid());
        }
    }
    Ok(())
}

pub(super) fn validate_remote_credential_bindings(
    scope: &McpScope,
    input: &McpServerDefinitionInput,
) -> McpResult<()> {
    let kind = if input.transport == McpTransport::Stdio {
        McpCredentialKind::Env
    } else {
        McpCredentialKind::Header
    };
    for (name, reference) in &input.vault_env_refs {
        let expected = credential_reference(
            scope,
            &input.name,
            input.transport,
            &input.command,
            input.cwd.as_deref(),
            kind,
            name,
        )?;
        if reference != &expected {
            return Err(remote_credential_scope_invalid());
        }
    }
    Ok(())
}

pub(in crate::local_runtime) fn remote_credential_reference(
    scope: &McpScope,
    server_name: &str,
    transport: McpTransport,
    endpoint: &str,
    header_name: &str,
) -> McpResult<String> {
    credential_reference(
        scope,
        server_name,
        transport,
        &[endpoint.to_string()],
        None,
        McpCredentialKind::Header,
        header_name,
    )
}

pub(in crate::local_runtime) fn credential_reference(
    scope: &McpScope,
    server_name: &str,
    transport: McpTransport,
    command: &[String],
    cwd: Option<&str>,
    kind: McpCredentialKind,
    name: &str,
) -> McpResult<String> {
    if server_name.is_empty()
        || server_name.len() > 200
        || server_name.chars().any(char::is_control)
    {
        return Err(remote_credential_scope_invalid());
    }
    let (prefix, domain, binding_target, canonical_name) = match (transport, kind) {
        (
            McpTransport::Http | McpTransport::Sse | McpTransport::Websocket,
            McpCredentialKind::Header,
        ) => {
            let endpoint = command.first().ok_or_else(endpoint_invalid)?;
            if command.len() != 1 || cwd.is_some() {
                return Err(endpoint_invalid());
            }
            let url = validate_remote_url(endpoint, transport, false)?;
            let header_name = HeaderName::from_str(name).map_err(|_| remote_header_invalid())?;
            if RESERVED_REMOTE_HEADERS.contains(&header_name.as_str()) {
                return Err(remote_header_invalid());
            }
            (
                MCP_REMOTE_CREDENTIAL_PREFIX,
                b"memstack-desktop-mcp-remote-credential-v1\0".as_slice(),
                url.origin().ascii_serialization(),
                header_name.as_str().to_string(),
            )
        }
        (McpTransport::Stdio, McpCredentialKind::Env) => {
            if command.is_empty() || !valid_env_name(name) {
                return Err(remote_credential_scope_invalid());
            }
            (
                MCP_STDIO_CREDENTIAL_PREFIX,
                b"memstack-desktop-mcp-stdio-credential-v1\0".as_slice(),
                serde_json::json!({"command": command, "cwd": cwd}).to_string(),
                name.to_string(),
            )
        }
        _ => return Err(remote_credential_scope_invalid()),
    };
    let mut digest = Sha256::new();
    digest.update(domain);
    digest.update(scope.tenant_id.as_bytes());
    digest.update(b"\0");
    digest.update(scope.project_id.as_bytes());
    digest.update(b"\0");
    digest.update(server_name.as_bytes());
    digest.update(b"\0");
    digest.update(binding_target.as_bytes());
    digest.update(b"\0");
    digest.update(canonical_name.as_bytes());
    Ok(format!("{prefix}.{:x}", digest.finalize()))
}

pub(super) async fn resolve_remote_endpoint(
    server: &McpServerDefinition,
    lookup_timeout: Duration,
) -> McpResult<ResolvedEndpoint> {
    let url = validate_remote_definition(server)?;
    let host = url.host_str().ok_or_else(endpoint_invalid)?.to_string();
    let port = url.port_or_known_default().ok_or_else(endpoint_invalid)?;
    let addresses = match url.host().ok_or_else(endpoint_invalid)? {
        Host::Ipv4(address) => vec![SocketAddr::new(IpAddr::V4(address), port)],
        Host::Ipv6(address) => vec![SocketAddr::new(IpAddr::V6(address), port)],
        Host::Domain(domain) => tokio::time::timeout(lookup_timeout, lookup_host((domain, port)))
            .await
            .map_err(|_| request_timeout())?
            .map_err(|_| endpoint_resolution_rejected())?
            .collect(),
    };
    if addresses.is_empty() {
        return Err(endpoint_resolution_rejected());
    }
    validate_resolved_addresses(&url, &addresses)?;
    Ok(ResolvedEndpoint {
        url,
        host,
        addresses,
    })
}

pub(super) fn remote_headers(
    server: &McpServerDefinition,
    credential_vault: Option<&ApplicationCredentialVault>,
) -> McpResult<HeaderMap> {
    let mut headers = HeaderMap::new();
    if server.vault_env_refs.is_empty() {
        return Ok(headers);
    }
    let broker = McpRemoteCredentialBroker {
        vault: credential_vault.ok_or_else(vault_unavailable)?,
    };
    for (name, reference) in &server.vault_env_refs {
        let header_name = HeaderName::from_str(name).map_err(|_| remote_header_invalid())?;
        if RESERVED_REMOTE_HEADERS.contains(&header_name.as_str()) {
            return Err(remote_header_invalid());
        }
        let mut value = broker.resolve(server, &header_name, reference)?;
        let header_value = match HeaderValue::from_str(&value) {
            Ok(header_value) => header_value,
            Err(_) => {
                value.zeroize();
                return Err(remote_header_invalid());
            }
        };
        value.zeroize();
        headers.insert(header_name, header_value);
    }
    Ok(headers)
}

struct McpRemoteCredentialBroker<'a> {
    vault: &'a ApplicationCredentialVault,
}

impl McpRemoteCredentialBroker<'_> {
    fn resolve(
        &self,
        server: &McpServerDefinition,
        header_name: &HeaderName,
        reference: &str,
    ) -> McpResult<String> {
        let scope = McpScope {
            tenant_id: server.tenant_id.clone(),
            project_id: server.project_id.clone(),
        };
        let endpoint = server.command.first().ok_or_else(endpoint_invalid)?;
        let expected = remote_credential_reference(
            &scope,
            &server.name,
            server.transport,
            endpoint,
            header_name.as_str(),
        )?;
        if reference != expected {
            return Err(remote_credential_scope_invalid());
        }
        self.vault
            .get(reference)
            .map_err(|_| vault_unavailable())?
            .ok_or_else(vault_unavailable)
    }
}

pub(super) fn build_client(endpoint: &ResolvedEndpoint) -> McpResult<Client> {
    Client::builder()
        .redirect(Policy::none())
        .no_proxy()
        .resolve_to_addrs(&endpoint.host, &endpoint.addresses)
        .build()
        .map_err(|_| {
            McpSupervisorError::new(
                "local_mcp_http_client_unavailable",
                "MCP HTTP client could not be initialized",
            )
        })
}

pub(super) fn is_content_type(headers: &HeaderMap, expected: &str) -> bool {
    headers
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.split(';').next())
        .is_some_and(|value| value.trim().eq_ignore_ascii_case(expected))
}

pub(super) fn retry_delay(failures: u32, limits: SupervisorLimits) -> Duration {
    let shift = failures.saturating_sub(1).min(10);
    let multiplier = 1_u32.checked_shl(shift).unwrap_or(u32::MAX);
    limits
        .retry_base
        .saturating_mul(multiplier)
        .min(limits.retry_max)
}

pub(super) async fn bounded_body(response: Response, max_bytes: usize) -> McpResult<Vec<u8>> {
    let mut body = Vec::new();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| connection_closed())?;
        if body.len().saturating_add(chunk.len()) > max_bytes {
            return Err(response_too_large());
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

pub(super) fn next_request_id(current: &mut u64) -> McpResult<u64> {
    let request_id = *current;
    *current = current.checked_add(1).ok_or_else(|| {
        McpSupervisorError::new(
            "local_mcp_request_id_exhausted",
            "MCP request identifier space is exhausted",
        )
    })?;
    Ok(request_id)
}

pub(super) fn encode_message(message: &Value, limits: SupervisorLimits) -> McpResult<Vec<u8>> {
    let encoded = serde_json::to_vec(message).map_err(|_| malformed_request())?;
    if encoded.len() > limits.max_request_bytes {
        return Err(McpSupervisorError::new(
            "local_mcp_request_too_large",
            "MCP request exceeds the local payload limit",
        ));
    }
    Ok(encoded)
}

pub(super) fn decode_json_rpc_messages(
    payload: &[u8],
    max_members: usize,
) -> McpResult<Vec<Value>> {
    let value: Value = serde_json::from_slice(payload).map_err(|_| malformed_response())?;
    let messages = match value {
        Value::Object(_) => vec![value],
        Value::Array(messages) => {
            if messages.is_empty() {
                return Err(malformed_response());
            }
            if messages.len() > max_members {
                return Err(response_too_large());
            }
            messages
        }
        _ => return Err(malformed_response()),
    };
    if messages.len() > max_members {
        return Err(response_too_large());
    }
    for message in &messages {
        validate_json_rpc_message(message)?;
    }
    Ok(messages)
}

fn validate_json_rpc_message(message: &Value) -> McpResult<()> {
    let object = message.as_object().ok_or_else(malformed_response)?;
    if object.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
        return Err(malformed_response());
    }
    if let Some(method) = object.get("method") {
        if !method.as_str().is_some_and(|value| !value.is_empty())
            || object.contains_key("result")
            || object.contains_key("error")
        {
            return Err(malformed_response());
        }
        if object
            .get("params")
            .is_some_and(|params| !params.is_object() && !params.is_array())
            || object.get("id").is_some_and(|id| !valid_json_rpc_id(id))
        {
            return Err(malformed_response());
        }
        return Ok(());
    }
    let Some(id) = object.get("id") else {
        return Err(malformed_response());
    };
    let has_result = object.contains_key("result");
    let has_error = object.contains_key("error");
    if !valid_json_rpc_id(id) || has_result == has_error {
        return Err(malformed_response());
    }
    if has_error {
        let error = object
            .get("error")
            .and_then(Value::as_object)
            .ok_or_else(malformed_response)?;
        if !error
            .get("code")
            .and_then(Value::as_number)
            .is_some_and(|code| code.is_i64() || code.is_u64())
            || error.get("message").and_then(Value::as_str).is_none()
        {
            return Err(malformed_response());
        }
    }
    Ok(())
}

fn valid_json_rpc_id(value: &Value) -> bool {
    value.is_string() || value.is_number() || value.is_null()
}

pub(super) fn correlated_result(message: &Value, request_id: u64) -> McpResult<Option<Value>> {
    if message.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
        return Err(malformed_response());
    }
    if message.get("method").is_some() {
        return Ok(None);
    }
    let Some(response_id) = message.get("id").and_then(Value::as_u64) else {
        return Ok(None);
    };
    if response_id != request_id {
        return Ok(None);
    }
    if message.get("error").is_some_and(|value| !value.is_null()) {
        return Err(McpSupervisorError::new(
            "local_mcp_json_rpc_error",
            "MCP server returned a JSON-RPC error",
        ));
    }
    message
        .get("result")
        .cloned()
        .map(Some)
        .ok_or_else(malformed_response)
}

pub(super) fn server_request_rejection(message: &Value) -> McpResult<Option<(Value, bool)>> {
    if message.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
        return Err(malformed_response());
    }
    let Some(method) = message.get("method").and_then(Value::as_str) else {
        return Ok(None);
    };
    let Some(id) = message.get("id").filter(|value| !value.is_null()).cloned() else {
        return Ok(None);
    };
    let is_elicitation = method == "elicitation/create";
    let error = if is_elicitation {
        json!({
            "jsonrpc": "2.0",
            "id": id,
            "error": {
                "code": -32601,
                "message": "elicitation is unavailable in the local desktop MCP host"
            }
        })
    } else {
        json!({
            "jsonrpc": "2.0",
            "id": id,
            "error": {
                "code": -32601,
                "message": "server-to-client request is not supported"
            }
        })
    };
    Ok(Some((error, is_elicitation)))
}

pub(super) fn elicitation_unavailable() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_elicitation_bridge_unavailable",
        "local MCP elicitation has no authoritative user-response bridge",
    )
}

pub(super) fn unsupported_client_request() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_client_request_unavailable",
        "MCP server requested an unsupported client capability",
    )
}

pub(super) fn malformed_request() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_request_invalid",
        "MCP request could not be encoded",
    )
}

pub(super) fn malformed_response() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_malformed_response",
        "MCP server returned a malformed response",
    )
}

pub(super) fn response_too_large() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_response_too_large",
        "MCP response exceeds the local payload limit",
    )
}

pub(super) fn request_timeout() -> McpSupervisorError {
    McpSupervisorError::new("local_mcp_request_timeout", "MCP request timed out")
}

pub(super) fn connection_closed() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_connection_closed",
        "MCP transport connection closed unexpectedly",
    )
}

pub(super) fn restart_backoff() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_restart_backoff",
        "MCP server restart is waiting for bounded backoff",
    )
}

pub(super) fn vault_unavailable() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_vault_reference_unavailable",
        "MCP vault reference is unavailable",
    )
}

pub(super) fn validate_remote_url(
    endpoint: &str,
    transport: McpTransport,
    allow_query: bool,
) -> McpResult<Url> {
    if endpoint.is_empty() || endpoint.len() > 4096 || endpoint.chars().any(char::is_control) {
        return Err(endpoint_invalid());
    }
    let url = Url::parse(endpoint).map_err(|_| endpoint_invalid())?;
    let allowed_scheme = match transport {
        McpTransport::Http | McpTransport::Sse => matches!(url.scheme(), "http" | "https"),
        McpTransport::Websocket => matches!(url.scheme(), "ws" | "wss"),
        McpTransport::Stdio => false,
    };
    if !allowed_scheme
        || url.host().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
        || (!allow_query && url.query().is_some())
    {
        return Err(endpoint_invalid());
    }
    if is_loopback_host(&url) && !has_canonical_loopback_authority(endpoint, &url) {
        return Err(endpoint_policy_rejected());
    }
    let is_cleartext = matches!(url.scheme(), "http" | "ws");
    if is_cleartext && !is_loopback_host(&url) {
        return Err(endpoint_policy_rejected());
    }
    if let Some(host) = url.host() {
        match host {
            Host::Ipv4(address)
                if !address.is_loopback() && !is_globally_routable(address.into()) =>
            {
                return Err(endpoint_policy_rejected());
            }
            Host::Ipv6(address)
                if !address.is_loopback() && !is_globally_routable(address.into()) =>
            {
                return Err(endpoint_policy_rejected());
            }
            Host::Domain(domain)
                if domain != "localhost"
                    && (!domain.contains('.') || domain.ends_with(".local")) =>
            {
                return Err(endpoint_policy_rejected());
            }
            _ => {}
        }
    }
    Ok(url)
}

pub(super) fn validate_legacy_message_endpoint(base: &Url, endpoint: &str) -> McpResult<Url> {
    let resolved = base.join(endpoint).map_err(|_| endpoint_invalid())?;
    if resolved.scheme() != base.scheme()
        || resolved.host_str() != base.host_str()
        || resolved.port_or_known_default() != base.port_or_known_default()
        || !resolved.username().is_empty()
        || resolved.password().is_some()
        || resolved.fragment().is_some()
    {
        return Err(McpSupervisorError::new(
            "local_mcp_sse_endpoint_rejected",
            "MCP SSE message endpoint escaped its declared origin",
        ));
    }
    Ok(resolved)
}

fn is_loopback_host(url: &Url) -> bool {
    match url.host() {
        Some(Host::Domain(domain)) => domain == "localhost",
        Some(Host::Ipv4(address)) => address.is_loopback(),
        Some(Host::Ipv6(address)) => address.is_loopback(),
        None => false,
    }
}

fn has_canonical_loopback_authority(endpoint: &str, url: &Url) -> bool {
    let Some(authority) = endpoint
        .split_once("://")
        .map(|(_, remainder)| remainder)
        .and_then(|remainder| remainder.split(['/', '?', '#']).next())
    else {
        return false;
    };
    let raw_host = if let Some(bracketed) = authority.strip_prefix('[') {
        bracketed.split_once(']').map(|(host, _)| host)
    } else {
        Some(
            authority
                .rsplit_once(':')
                .filter(|(_, port)| port.parse::<u16>().is_ok())
                .map_or(authority, |(host, _)| host),
        )
    };
    match (url.host(), raw_host) {
        (Some(Host::Domain("localhost")), Some(host)) => host.eq_ignore_ascii_case("localhost"),
        (Some(Host::Ipv4(address)), Some(host)) if address.is_loopback() => host == "127.0.0.1",
        (Some(Host::Ipv6(address)), Some(host)) if address.is_loopback() => {
            host.eq_ignore_ascii_case("::1")
        }
        _ => false,
    }
}

pub(super) fn validate_resolved_addresses(url: &Url, addresses: &[SocketAddr]) -> McpResult<()> {
    if addresses.is_empty() {
        return Err(endpoint_resolution_rejected());
    }
    if is_loopback_host(url) {
        if addresses.iter().all(|address| address.ip().is_loopback()) {
            return Ok(());
        }
    } else if addresses
        .iter()
        .all(|address| is_globally_routable(address.ip()))
    {
        return Ok(());
    }
    Err(endpoint_resolution_rejected())
}

pub(super) fn is_globally_routable(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(address) => is_globally_routable_v4(address.octets()),
        IpAddr::V6(address) => {
            let octets = address.octets();
            if octets[..10] == [0; 10] && octets[10..12] == [0xff, 0xff] {
                return is_globally_routable_v4([octets[12], octets[13], octets[14], octets[15]]);
            }
            let global_unicast = octets[0] & 0xe0 == 0x20;
            let documentation = octets[..4] == [0x20, 0x01, 0x0d, 0xb8]
                || (octets[0] == 0x3f && octets[1] & 0xf0 == 0xf0);
            let discard_only = octets[..8] == [0x01, 0x00, 0, 0, 0, 0, 0, 0];
            let benchmarking = octets[..6] == [0x20, 0x01, 0, 0x02, 0, 0];
            let orchid = octets[..3] == [0x20, 0x01, 0] && matches!(octets[3] & 0xf0, 0x10 | 0x20);
            let transition = octets[..4] == [0x20, 0x01, 0, 0]
                || octets[..2] == [0x20, 0x02]
                || octets[..12] == [0, 0x64, 0xff, 0x9b, 0, 0, 0, 0, 0, 0, 0, 0]
                || octets[..6] == [0, 0x64, 0xff, 0x9b, 0, 1];
            global_unicast
                && !documentation
                && !discard_only
                && !benchmarking
                && !orchid
                && !transition
        }
    }
}

fn is_globally_routable_v4(octets: [u8; 4]) -> bool {
    match octets {
        [0, ..]
        | [10, ..]
        | [127, ..]
        | [169, 254, ..]
        | [192, 0, 0, ..]
        | [192, 0, 2, ..]
        | [192, 88, 99, ..]
        | [192, 168, ..]
        | [198, 18 | 19, ..]
        | [198, 51, 100, ..]
        | [203, 0, 113, ..]
        | [224..=255, ..] => false,
        [100, second, ..] if second & 0xc0 == 0x40 => false,
        [172, second, ..] if second & 0xf0 == 0x10 => false,
        _ => true,
    }
}

fn endpoint_invalid() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_endpoint_invalid",
        "MCP remote endpoint is invalid",
    )
}

fn endpoint_policy_rejected() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_endpoint_policy_rejected",
        "MCP remote endpoint is rejected by local network policy",
    )
}

fn endpoint_resolution_rejected() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_endpoint_resolution_rejected",
        "MCP remote endpoint resolved outside the allowed network policy",
    )
}

fn remote_header_invalid() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_remote_header_invalid",
        "MCP remote header vault reference is invalid",
    )
}

fn remote_credential_scope_invalid() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_remote_credential_scope_invalid",
        "MCP remote credential reference is outside its tenant, project, server, or origin scope",
    )
}
