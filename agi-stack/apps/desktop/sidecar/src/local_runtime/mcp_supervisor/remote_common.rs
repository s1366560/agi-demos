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
use tokio::net::lookup_host;
use url::{Host, Url};
use zeroize::Zeroize;

use crate::application_vault::ApplicationCredentialVault;

use super::{McpResult, McpServerDefinition, McpSupervisorError, McpTransport, SupervisorLimits};

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
    buffer: Vec<u8>,
}

impl SseDecoder {
    pub(super) fn push(
        &mut self,
        chunk: &[u8],
        max_frame_bytes: usize,
    ) -> McpResult<Vec<SseEvent>> {
        self.buffer.extend_from_slice(chunk);
        let mut events = Vec::new();
        while let Some((end, delimiter_len)) = event_boundary(&self.buffer) {
            if end > max_frame_bytes {
                return Err(response_too_large());
            }
            let raw = self.buffer.drain(..end).collect::<Vec<_>>();
            self.buffer.drain(..delimiter_len);
            if let Some(event) = parse_event(&raw)? {
                events.push(event);
            }
        }
        if self.buffer.len() > max_frame_bytes {
            return Err(response_too_large());
        }
        Ok(events)
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

pub(super) async fn resolve_remote_endpoint(
    server: &McpServerDefinition,
) -> McpResult<ResolvedEndpoint> {
    let url = validate_remote_definition(server)?;
    let host = url.host_str().ok_or_else(endpoint_invalid)?.to_string();
    let port = url.port_or_known_default().ok_or_else(endpoint_invalid)?;
    let addresses = match url.host().ok_or_else(endpoint_invalid)? {
        Host::Ipv4(address) => vec![SocketAddr::new(IpAddr::V4(address), port)],
        Host::Ipv6(address) => vec![SocketAddr::new(IpAddr::V6(address), port)],
        Host::Domain(domain) => lookup_host((domain, port))
            .await
            .map_err(|_| endpoint_resolution_rejected())?
            .collect(),
    };
    if addresses.is_empty() {
        return Err(endpoint_resolution_rejected());
    }
    let loopback_definition = is_loopback_host(&url);
    if loopback_definition {
        if addresses.iter().any(|address| !address.ip().is_loopback()) {
            return Err(endpoint_resolution_rejected());
        }
    } else if addresses
        .iter()
        .any(|address| !is_public_address(address.ip()))
    {
        return Err(endpoint_resolution_rejected());
    }
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
    for (name, reference) in &server.vault_env_refs {
        let header_name = HeaderName::from_str(name).map_err(|_| remote_header_invalid())?;
        if RESERVED_REMOTE_HEADERS.contains(&header_name.as_str()) {
            return Err(remote_header_invalid());
        }
        let mut value = credential_vault
            .ok_or_else(vault_unavailable)?
            .get(reference)
            .map_err(|_| vault_unavailable())?
            .ok_or_else(vault_unavailable)?;
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
        .is_some_and(|value| value.trim() == expected)
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

fn validate_remote_url(
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
    let is_cleartext = matches!(url.scheme(), "http" | "ws");
    if is_cleartext && !is_loopback_host(&url) {
        return Err(endpoint_policy_rejected());
    }
    if let Some(host) = url.host() {
        match host {
            Host::Ipv4(address) if !address.is_loopback() && !is_public_address(address.into()) => {
                return Err(endpoint_policy_rejected());
            }
            Host::Ipv6(address) if !address.is_loopback() && !is_public_address(address.into()) => {
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

fn is_public_address(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(address) => {
            !address.is_private()
                && !address.is_loopback()
                && !address.is_link_local()
                && !address.is_broadcast()
                && !address.is_documentation()
                && !address.is_multicast()
                && !address.is_unspecified()
        }
        IpAddr::V6(address) => {
            let octets = address.octets();
            let is_unique_local = octets[0] & 0xfe == 0xfc;
            let is_unicast_link_local = octets[0] == 0xfe && octets[1] & 0xc0 == 0x80;
            !address.is_loopback()
                && !address.is_unspecified()
                && !address.is_multicast()
                && !is_unique_local
                && !is_unicast_link_local
        }
    }
}

fn event_boundary(buffer: &[u8]) -> Option<(usize, usize)> {
    buffer
        .windows(2)
        .position(|window| window == b"\n\n")
        .map(|index| (index, 2))
        .or_else(|| {
            buffer
                .windows(4)
                .position(|window| window == b"\r\n\r\n")
                .map(|index| (index, 4))
        })
}

fn parse_event(raw: &[u8]) -> McpResult<Option<SseEvent>> {
    let text = std::str::from_utf8(raw).map_err(|_| malformed_response())?;
    let mut event = None;
    let mut data = Vec::new();
    for line in text.lines() {
        let line = line.trim_end_matches('\r');
        if line.starts_with(':') {
            continue;
        }
        if let Some(value) = line.strip_prefix("event:") {
            event = Some(value.trim_start().to_string());
        } else if let Some(value) = line.strip_prefix("data:") {
            if !data.is_empty() {
                data.push(b'\n');
            }
            data.extend_from_slice(value.trim_start().as_bytes());
        }
    }
    if data.is_empty() {
        return Ok(None);
    }
    Ok(Some(SseEvent { event, data }))
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
