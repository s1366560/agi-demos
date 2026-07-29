use std::{
    collections::VecDeque,
    time::{Duration, Instant},
};

use futures_util::StreamExt;
use reqwest::{
    header::{self, HeaderMap, HeaderValue},
    Client, Response, StatusCode,
};
use serde_json::{json, Value};
use tokio::time::timeout;

use crate::application_vault::ApplicationCredentialVault;

use super::{
    remote_common::{
        bounded_body, build_client, connection_closed, correlated_result, decode_json_rpc_messages,
        elicitation_unavailable, encode_message, is_content_type, malformed_response,
        next_request_id, remote_headers, request_timeout, resolve_remote_endpoint,
        response_too_large, restart_backoff, retry_delay, server_request_rejection,
        unsupported_client_request, validate_legacy_message_endpoint, InitializedServer,
        ResolvedEndpoint, SseDecoder, SseEvent, MAX_CORRELATION_MESSAGES,
        STREAMABLE_HTTP_PROTOCOL_VERSION,
    },
    McpResult, McpServerDefinition, McpSupervisorError, SupervisorLimits, MCP_PROTOCOL_VERSION,
};

struct HttpResponseMessages {
    headers: HeaderMap,
    messages: Vec<Value>,
}

pub(super) struct HttpRuntime {
    pub(super) client: Option<Client>,
    pub(super) endpoint: Option<ResolvedEndpoint>,
    pub(super) session_id: Option<HeaderValue>,
    pub(super) protocol_version: Option<HeaderValue>,
    pub(super) initialized_revision: Option<u64>,
    pub(super) server_info: Option<Value>,
    pub(super) next_request_id: u64,
    pub(super) consecutive_failures: u32,
    pub(super) retry_after: Option<Instant>,
}

impl HttpRuntime {
    pub(super) fn new() -> Self {
        Self {
            client: None,
            endpoint: None,
            session_id: None,
            protocol_version: None,
            initialized_revision: None,
            server_info: None,
            next_request_id: 1,
            consecutive_failures: 0,
            retry_after: None,
        }
    }

    pub(super) async fn ensure_initialized(
        &mut self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        limits: SupervisorLimits,
    ) -> McpResult<InitializedServer> {
        if self.initialized_revision == Some(server.revision)
            && self.client.is_some()
            && self.endpoint.is_some()
        {
            return Ok(InitializedServer {
                server_info: self.server_info.clone().unwrap_or_else(|| json!({})),
            });
        }
        self.reset(server, credential_vault, limits).await;
        self.enforce_backoff()?;
        let endpoint = match resolve_remote_endpoint(server, limits.initialize_timeout).await {
            Ok(endpoint) => endpoint,
            Err(error) => {
                self.fail(server, credential_vault, limits).await;
                return Err(error);
            }
        };
        let client = match build_client(&endpoint) {
            Ok(client) => client,
            Err(error) => {
                self.fail(server, credential_vault, limits).await;
                return Err(error);
            }
        };
        self.endpoint = Some(endpoint);
        self.client = Some(client);

        let initialize = self
            .request_inner(
                server,
                credential_vault,
                "initialize",
                json!({
                    "protocolVersion": STREAMABLE_HTTP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "agistack-desktop",
                        "version": env!("CARGO_PKG_VERSION"),
                    },
                }),
                limits,
                true,
            )
            .await;
        let initialize = match initialize {
            Ok(result) => result,
            Err(error) => {
                self.fail(server, credential_vault, limits).await;
                return Err(error);
            }
        };
        let protocol_version = initialize
            .get("protocolVersion")
            .and_then(Value::as_str)
            .filter(|version| *version == STREAMABLE_HTTP_PROTOCOL_VERSION);
        if protocol_version.is_none() {
            self.fail(server, credential_vault, limits).await;
            return Err(McpSupervisorError::new(
                "local_mcp_protocol_version_unsupported",
                "MCP Streamable HTTP protocol version is unsupported",
            ));
        }
        self.protocol_version = Some(HeaderValue::from_static(STREAMABLE_HTTP_PROTOCOL_VERSION));
        let server_info = initialize
            .get("serverInfo")
            .filter(|value| value.is_object())
            .cloned();
        let Some(server_info) = server_info else {
            self.fail(server, credential_vault, limits).await;
            return Err(malformed_response());
        };
        if let Err(error) = self
            .send_without_response(
                server,
                credential_vault,
                json!({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }),
                limits,
            )
            .await
        {
            self.fail(server, credential_vault, limits).await;
            return Err(error);
        }
        self.initialized_revision = Some(server.revision);
        self.server_info = Some(server_info.clone());
        self.consecutive_failures = 0;
        self.retry_after = None;
        Ok(InitializedServer { server_info })
    }

    pub(super) async fn request(
        &mut self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        method: &str,
        params: Value,
        limits: SupervisorLimits,
    ) -> McpResult<Value> {
        self.ensure_initialized(server, credential_vault, limits)
            .await?;
        match self
            .request_inner(server, credential_vault, method, params, limits, false)
            .await
        {
            Ok(result) => Ok(result),
            Err(error) => {
                self.fail(server, credential_vault, limits).await;
                Err(error)
            }
        }
    }

    async fn request_inner(
        &mut self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        method: &str,
        params: Value,
        limits: SupervisorLimits,
        initialize: bool,
    ) -> McpResult<Value> {
        let request_deadline = if initialize {
            limits.initialize_timeout
        } else {
            limits.request_timeout
        };
        let request_id = next_request_id(&mut self.next_request_id)?;
        let request = json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        });
        let response = timeout(
            request_deadline,
            self.post_message(server, credential_vault, &request, limits, initialize),
        )
        .await
        .map_err(|_| request_timeout())??;
        if initialize {
            self.capture_session(&response.headers)?;
        }
        for message in response.messages.into_iter().take(MAX_CORRELATION_MESSAGES) {
            if let Some((rejection, elicitation)) = server_request_rejection(&message)? {
                self.send_without_response(server, credential_vault, rejection, limits)
                    .await?;
                return Err(if elicitation {
                    elicitation_unavailable()
                } else {
                    unsupported_client_request()
                });
            }
            if let Some(result) = correlated_result(&message, request_id)? {
                return Ok(result);
            }
        }
        Err(McpSupervisorError::new(
            "local_mcp_response_correlation_failed",
            "MCP response did not match the request",
        ))
    }

    async fn send_without_response(
        &self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        message: Value,
        limits: SupervisorLimits,
    ) -> McpResult<()> {
        timeout(
            limits.request_timeout,
            self.post_message(server, credential_vault, &message, limits, false),
        )
        .await
        .map_err(|_| request_timeout())??;
        Ok(())
    }

    async fn post_message(
        &self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        message: &Value,
        limits: SupervisorLimits,
        initialize: bool,
    ) -> McpResult<HttpResponseMessages> {
        let encoded = encode_message(message, limits)?;
        let client = self.client.as_ref().ok_or_else(connection_closed)?;
        let endpoint = self.endpoint.as_ref().ok_or_else(connection_closed)?;
        let mut headers = remote_headers(server, credential_vault)?;
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );
        headers.insert(
            header::ACCEPT,
            HeaderValue::from_static("application/json, text/event-stream"),
        );
        if !initialize {
            if let Some(session_id) = self.session_id.clone() {
                headers.insert("mcp-session-id", session_id);
            }
            if let Some(protocol_version) = self.protocol_version.clone() {
                headers.insert("mcp-protocol-version", protocol_version);
            }
        }
        let response = client
            .post(endpoint.url.clone())
            .headers(headers)
            .body(encoded)
            .send()
            .await
            .map_err(|_| connection_closed())?;
        let status = response.status();
        if status.is_redirection() {
            return Err(McpSupervisorError::new(
                "local_mcp_redirect_rejected",
                "MCP remote redirect was rejected",
            ));
        }
        if status == StatusCode::NOT_FOUND && self.session_id.is_some() {
            return Err(McpSupervisorError::new(
                "local_mcp_session_lost",
                "MCP Streamable HTTP session was lost",
            ));
        }
        if !status.is_success() {
            return Err(McpSupervisorError::new(
                "local_mcp_http_status_error",
                "MCP remote server returned an unsuccessful HTTP status",
            ));
        }
        let response_headers = response.headers().clone();
        if message.get("id").is_none() || message.get("method").is_none() {
            return Ok(HttpResponseMessages {
                headers: response_headers,
                messages: Vec::new(),
            });
        }
        let request_id = message
            .get("id")
            .and_then(Value::as_u64)
            .ok_or_else(malformed_response)?;
        let messages = response_messages(response, limits, request_id).await?;
        Ok(HttpResponseMessages {
            headers: response_headers,
            messages,
        })
    }

    fn capture_session(&mut self, headers: &HeaderMap) -> McpResult<()> {
        let Some(session_id) = headers.get("mcp-session-id") else {
            self.session_id = None;
            return Ok(());
        };
        let value = session_id.as_bytes();
        if value.is_empty()
            || value.len() > 1024
            || value.iter().any(|byte| !(0x21..=0x7e).contains(byte))
        {
            return Err(malformed_response());
        }
        self.session_id = Some(session_id.clone());
        Ok(())
    }

    fn enforce_backoff(&self) -> McpResult<()> {
        if self
            .retry_after
            .is_some_and(|retry_after| Instant::now() < retry_after)
        {
            return Err(restart_backoff());
        }
        Ok(())
    }
}

struct LegacyConnection {
    response: Response,
    decoder: SseDecoder,
    pending: VecDeque<LegacySseEvent>,
    raw_bytes_since_event: usize,
    message_endpoint: Option<url::Url>,
}

struct LegacySseEvent {
    event: SseEvent,
    raw_bytes: usize,
}

pub(super) struct SseRuntime {
    client: Option<Client>,
    endpoint: Option<ResolvedEndpoint>,
    connection: Option<LegacyConnection>,
    initialized_revision: Option<u64>,
    server_info: Option<Value>,
    next_request_id: u64,
    consecutive_failures: u32,
    retry_after: Option<Instant>,
}

impl SseRuntime {
    pub(super) fn new() -> Self {
        Self {
            client: None,
            endpoint: None,
            connection: None,
            initialized_revision: None,
            server_info: None,
            next_request_id: 1,
            consecutive_failures: 0,
            retry_after: None,
        }
    }

    pub(super) async fn ensure_initialized(
        &mut self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        limits: SupervisorLimits,
    ) -> McpResult<InitializedServer> {
        if self.initialized_revision == Some(server.revision) && self.connection.is_some() {
            return Ok(InitializedServer {
                server_info: self.server_info.clone().unwrap_or_else(|| json!({})),
            });
        }
        self.stop();
        self.enforce_backoff()?;
        let endpoint = match resolve_remote_endpoint(server, limits.initialize_timeout).await {
            Ok(endpoint) => endpoint,
            Err(error) => {
                self.fail(limits);
                return Err(error);
            }
        };
        let client = match build_client(&endpoint) {
            Ok(client) => client,
            Err(error) => {
                self.fail(limits);
                return Err(error);
            }
        };
        self.endpoint = Some(endpoint);
        self.client = Some(client);
        if let Err(error) = self
            .open_event_stream(server, credential_vault, limits)
            .await
        {
            self.fail(limits);
            return Err(error);
        }
        let initialize = self
            .request_inner(
                server,
                credential_vault,
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
                self.fail(limits);
                return Err(error);
            }
        };
        if initialize.get("protocolVersion").and_then(Value::as_str) != Some(MCP_PROTOCOL_VERSION) {
            self.fail(limits);
            return Err(McpSupervisorError::new(
                "local_mcp_protocol_version_unsupported",
                "MCP legacy SSE protocol version is unsupported",
            ));
        }
        let server_info = initialize
            .get("serverInfo")
            .filter(|value| value.is_object())
            .cloned();
        let Some(server_info) = server_info else {
            self.fail(limits);
            return Err(malformed_response());
        };
        if let Err(error) = self
            .post_without_response(
                server,
                credential_vault,
                &json!({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }),
                limits,
            )
            .await
        {
            self.fail(limits);
            return Err(error);
        }
        self.initialized_revision = Some(server.revision);
        self.server_info = Some(server_info.clone());
        self.consecutive_failures = 0;
        self.retry_after = None;
        Ok(InitializedServer { server_info })
    }

    pub(super) async fn request(
        &mut self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        method: &str,
        params: Value,
        limits: SupervisorLimits,
    ) -> McpResult<Value> {
        self.ensure_initialized(server, credential_vault, limits)
            .await?;
        match self
            .request_inner(
                server,
                credential_vault,
                method,
                params,
                limits.request_timeout,
                limits,
            )
            .await
        {
            Ok(result) => Ok(result),
            Err(error) => {
                self.fail(limits);
                Err(error)
            }
        }
    }

    async fn open_event_stream(
        &mut self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        limits: SupervisorLimits,
    ) -> McpResult<()> {
        let client = self.client.as_ref().ok_or_else(connection_closed)?;
        let endpoint = self.endpoint.as_ref().ok_or_else(connection_closed)?;
        let endpoint_url = endpoint.url.clone();
        let mut headers = remote_headers(server, credential_vault)?;
        headers.insert(
            header::ACCEPT,
            HeaderValue::from_static("text/event-stream"),
        );
        let response = timeout(
            limits.initialize_timeout,
            client.get(endpoint_url.clone()).headers(headers).send(),
        )
        .await
        .map_err(|_| request_timeout())?
        .map_err(|_| connection_closed())?;
        if response.status().is_redirection() {
            return Err(McpSupervisorError::new(
                "local_mcp_redirect_rejected",
                "MCP remote redirect was rejected",
            ));
        }
        if !response.status().is_success()
            || !is_content_type(response.headers(), "text/event-stream")
        {
            return Err(McpSupervisorError::new(
                "local_mcp_sse_handshake_failed",
                "MCP legacy SSE endpoint did not open an event stream",
            ));
        }
        self.connection = Some(LegacyConnection {
            response,
            decoder: SseDecoder::default(),
            pending: VecDeque::new(),
            raw_bytes_since_event: 0,
            message_endpoint: None,
        });
        let endpoint_event = timeout(
            limits.initialize_timeout,
            self.next_legacy_event(limits, limits.max_aggregate_bytes),
        )
        .await
        .map_err(|_| request_timeout())??;
        if endpoint_event.event.event.as_deref() != Some("endpoint") {
            return Err(McpSupervisorError::new(
                "local_mcp_sse_endpoint_missing",
                "MCP legacy SSE stream did not declare its message endpoint",
            ));
        }
        let endpoint_text =
            std::str::from_utf8(&endpoint_event.event.data).map_err(|_| malformed_response())?;
        let message_endpoint =
            validate_legacy_message_endpoint(&endpoint_url, endpoint_text.trim())?;
        if let Some(connection) = self.connection.as_mut() {
            connection.message_endpoint = Some(message_endpoint);
        }
        Ok(())
    }

    async fn request_inner(
        &mut self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        method: &str,
        params: Value,
        request_deadline: Duration,
        limits: SupervisorLimits,
    ) -> McpResult<Value> {
        let request_id = next_request_id(&mut self.next_request_id)?;
        let request = json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        });
        timeout(request_deadline, async {
            self.post_without_response(server, credential_vault, &request, limits)
                .await?;
            let mut aggregate_raw_bytes = 0_usize;
            let mut messages_seen = 0_usize;
            for _ in 0..MAX_CORRELATION_MESSAGES {
                let event = self
                    .next_legacy_event(
                        limits,
                        limits
                            .max_aggregate_bytes
                            .saturating_sub(aggregate_raw_bytes),
                    )
                    .await?;
                aggregate_raw_bytes = aggregate_raw_bytes.saturating_add(event.raw_bytes);
                if aggregate_raw_bytes > limits.max_aggregate_bytes {
                    return Err(response_too_large());
                }
                if event
                    .event
                    .event
                    .as_deref()
                    .is_some_and(|kind| kind != "message")
                {
                    continue;
                }
                let remaining = MAX_CORRELATION_MESSAGES.saturating_sub(messages_seen);
                for message in decode_json_rpc_messages(&event.event.data, remaining)? {
                    messages_seen = messages_seen.saturating_add(1);
                    if let Some((rejection, elicitation)) = server_request_rejection(&message)? {
                        self.post_without_response(server, credential_vault, &rejection, limits)
                            .await?;
                        return Err(if elicitation {
                            elicitation_unavailable()
                        } else {
                            unsupported_client_request()
                        });
                    }
                    if let Some(result) = correlated_result(&message, request_id)? {
                        return Ok(result);
                    }
                }
            }
            Err(McpSupervisorError::new(
                "local_mcp_response_correlation_failed",
                "MCP response did not match the request",
            ))
        })
        .await
        .map_err(|_| request_timeout())?
    }

    async fn post_without_response(
        &self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        message: &Value,
        limits: SupervisorLimits,
    ) -> McpResult<()> {
        let encoded = encode_message(message, limits)?;
        let client = self.client.as_ref().ok_or_else(connection_closed)?;
        let endpoint = self
            .connection
            .as_ref()
            .and_then(|connection| connection.message_endpoint.clone())
            .ok_or_else(connection_closed)?;
        let mut headers = remote_headers(server, credential_vault)?;
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );
        headers.insert(header::ACCEPT, HeaderValue::from_static("application/json"));
        let response = timeout(
            limits.request_timeout,
            client.post(endpoint).headers(headers).body(encoded).send(),
        )
        .await
        .map_err(|_| request_timeout())?
        .map_err(|_| connection_closed())?;
        if response.status().is_redirection() {
            return Err(McpSupervisorError::new(
                "local_mcp_redirect_rejected",
                "MCP remote redirect was rejected",
            ));
        }
        if !response.status().is_success() {
            return Err(McpSupervisorError::new(
                "local_mcp_http_status_error",
                "MCP remote server returned an unsuccessful HTTP status",
            ));
        }
        Ok(())
    }

    async fn next_legacy_event(
        &mut self,
        limits: SupervisorLimits,
        aggregate_remaining: usize,
    ) -> McpResult<LegacySseEvent> {
        let connection = self.connection.as_mut().ok_or_else(connection_closed)?;
        if let Some(event) = connection.pending.pop_front() {
            return Ok(event);
        }
        loop {
            let chunk = connection
                .response
                .chunk()
                .await
                .map_err(|_| connection_closed())?
                .ok_or_else(connection_closed)?;
            connection.raw_bytes_since_event =
                connection.raw_bytes_since_event.saturating_add(chunk.len());
            if connection.raw_bytes_since_event > aggregate_remaining {
                return Err(response_too_large());
            }
            let events = connection.decoder.push(
                &chunk,
                limits.max_frame_bytes,
                limits.max_aggregate_bytes,
            )?;
            if !events.is_empty() {
                let raw_bytes = std::mem::take(&mut connection.raw_bytes_since_event);
                connection
                    .pending
                    .extend(
                        events
                            .into_iter()
                            .enumerate()
                            .map(|(index, event)| LegacySseEvent {
                                event,
                                raw_bytes: if index == 0 { raw_bytes } else { 0 },
                            }),
                    );
            }
            if let Some(event) = connection.pending.pop_front() {
                return Ok(event);
            }
        }
    }

    fn enforce_backoff(&self) -> McpResult<()> {
        if self
            .retry_after
            .is_some_and(|retry_after| Instant::now() < retry_after)
        {
            return Err(restart_backoff());
        }
        Ok(())
    }

    fn fail(&mut self, limits: SupervisorLimits) {
        self.stop();
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);
        self.retry_after = Some(Instant::now() + retry_delay(self.consecutive_failures, limits));
    }

    fn stop(&mut self) {
        self.client = None;
        self.endpoint = None;
        self.connection = None;
        self.initialized_revision = None;
        self.server_info = None;
    }
}

async fn response_messages(
    response: Response,
    limits: SupervisorLimits,
    request_id: u64,
) -> McpResult<Vec<Value>> {
    let content_type = response
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .map(|value| {
            value
                .split(';')
                .next()
                .unwrap_or_default()
                .trim()
                .to_string()
        })
        .ok_or_else(malformed_response)?;
    if content_type == "application/json" || content_type.ends_with("+json") {
        let body = bounded_body(response, limits.max_aggregate_bytes).await?;
        if body.len() > limits.max_frame_bytes {
            return Err(response_too_large());
        }
        return decode_json_rpc_messages(&body, MAX_CORRELATION_MESSAGES);
    }
    if content_type == "text/event-stream" {
        let mut decoder = SseDecoder::default();
        let mut aggregate = 0_usize;
        let mut messages = Vec::new();
        let mut stream = response.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|_| connection_closed())?;
            aggregate = aggregate.saturating_add(chunk.len());
            if aggregate > limits.max_aggregate_bytes {
                return Err(response_too_large());
            }
            for event in decoder.push(&chunk, limits.max_frame_bytes, limits.max_aggregate_bytes)? {
                if event.event.as_deref().is_some_and(|kind| kind != "message") {
                    continue;
                }
                let remaining = MAX_CORRELATION_MESSAGES.saturating_sub(messages.len());
                for message in decode_json_rpc_messages(&event.data, remaining)? {
                    let is_server_request =
                        message.get("method").is_some() && message.get("id").is_some();
                    let is_expected_response = message.get("method").is_none()
                        && message.get("id").and_then(Value::as_u64) == Some(request_id);
                    messages.push(message);
                    if is_server_request
                        || is_expected_response
                        || messages.len() >= MAX_CORRELATION_MESSAGES
                    {
                        return Ok(messages);
                    }
                }
            }
        }
        return Ok(messages);
    }
    Err(McpSupervisorError::new(
        "local_mcp_content_type_rejected",
        "MCP remote response content type is unsupported",
    ))
}
