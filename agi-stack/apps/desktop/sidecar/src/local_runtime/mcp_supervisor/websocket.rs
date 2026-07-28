use std::time::{Duration, Instant};

use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::net::TcpStream;
use tokio::time::timeout;
use tokio_tungstenite::{
    client_async_tls,
    tungstenite::{
        client::IntoClientRequest,
        protocol::{frame::coding::CloseCode, CloseFrame},
        Message,
    },
    MaybeTlsStream, WebSocketStream,
};

use crate::application_vault::ApplicationCredentialVault;

use super::{
    remote_common::{
        connection_closed, correlated_result, elicitation_unavailable, encode_message,
        malformed_response, next_request_id, remote_headers, request_timeout,
        resolve_remote_endpoint, response_too_large, restart_backoff, retry_delay,
        server_request_rejection, unsupported_client_request, InitializedServer,
        MAX_CORRELATION_MESSAGES, STREAMABLE_HTTP_PROTOCOL_VERSION,
    },
    McpResult, McpServerDefinition, McpSupervisorError, SupervisorLimits,
};

type WebSocket = WebSocketStream<MaybeTlsStream<TcpStream>>;

pub(super) struct WebSocketRuntime {
    socket: Option<WebSocket>,
    initialized_revision: Option<u64>,
    server_info: Option<Value>,
    next_request_id: u64,
    consecutive_failures: u32,
    retry_after: Option<Instant>,
}

impl WebSocketRuntime {
    pub(super) fn new() -> Self {
        Self {
            socket: None,
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
        if self.initialized_revision == Some(server.revision) && self.socket.is_some() {
            return Ok(InitializedServer {
                server_info: self.server_info.clone().unwrap_or_else(|| json!({})),
            });
        }
        self.stop().await;
        self.enforce_backoff()?;
        let connected: McpResult<WebSocket> = async {
            let endpoint = resolve_remote_endpoint(server).await?;
            let mut request = endpoint
                .url
                .as_str()
                .into_client_request()
                .map_err(|_| connection_closed())?;
            let headers = remote_headers(server, credential_vault)?;
            for (name, value) in &headers {
                request.headers_mut().insert(name, value.clone());
            }
            let address = endpoint
                .addresses
                .first()
                .copied()
                .ok_or_else(connection_closed)?;
            let stream = timeout(limits.initialize_timeout, TcpStream::connect(address))
                .await
                .map_err(|_| request_timeout())?
                .map_err(|_| connection_closed())?;
            let (socket, response) =
                timeout(limits.initialize_timeout, client_async_tls(request, stream))
                    .await
                    .map_err(|_| request_timeout())?
                    .map_err(|_| connection_closed())?;
            if response.status().as_u16() != 101 {
                return Err(McpSupervisorError::new(
                    "local_mcp_websocket_handshake_failed",
                    "MCP WebSocket handshake did not switch protocols",
                ));
            }
            Ok(socket)
        }
        .await;
        let socket = match connected {
            Ok(socket) => socket,
            Err(error) => {
                self.fail(limits).await;
                return Err(error);
            }
        };
        self.socket = Some(socket);
        let initialize = self
            .request_inner(
                "initialize",
                json!({
                    "protocolVersion": STREAMABLE_HTTP_PROTOCOL_VERSION,
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
        let protocol_version = initialize.get("protocolVersion").and_then(Value::as_str);
        if !protocol_version.is_some_and(|version| {
            matches!(
                version,
                STREAMABLE_HTTP_PROTOCOL_VERSION | super::MCP_PROTOCOL_VERSION
            )
        }) {
            self.fail(limits).await;
            return Err(McpSupervisorError::new(
                "local_mcp_protocol_version_unsupported",
                "MCP WebSocket protocol version is unsupported",
            ));
        }
        let server_info = initialize
            .get("serverInfo")
            .filter(|value| value.is_object())
            .cloned();
        let Some(server_info) = server_info else {
            self.fail(limits).await;
            return Err(malformed_response());
        };
        if let Err(error) = self
            .send_message(
                &json!({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }),
                limits,
            )
            .await
        {
            self.fail(limits).await;
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

    async fn request_inner(
        &mut self,
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
        self.send_message(&request, limits).await?;
        timeout(request_deadline, self.read_response(request_id, limits))
            .await
            .map_err(|_| request_timeout())?
    }

    async fn send_message(&mut self, message: &Value, limits: SupervisorLimits) -> McpResult<()> {
        let encoded = encode_message(message, limits)?;
        let text = String::from_utf8(encoded).map_err(|_| malformed_response())?;
        self.socket
            .as_mut()
            .ok_or_else(connection_closed)?
            .send(Message::Text(text))
            .await
            .map_err(|_| connection_closed())
    }

    async fn read_response(
        &mut self,
        request_id: u64,
        limits: SupervisorLimits,
    ) -> McpResult<Value> {
        let mut aggregate = 0_usize;
        for _ in 0..MAX_CORRELATION_MESSAGES {
            let frame = self
                .socket
                .as_mut()
                .ok_or_else(connection_closed)?
                .next()
                .await
                .ok_or_else(connection_closed)?
                .map_err(|_| connection_closed())?;
            let bytes = match frame {
                Message::Text(text) => text.into_bytes(),
                Message::Binary(bytes) => bytes,
                Message::Ping(payload) => {
                    self.socket
                        .as_mut()
                        .ok_or_else(connection_closed)?
                        .send(Message::Pong(payload))
                        .await
                        .map_err(|_| connection_closed())?;
                    continue;
                }
                Message::Pong(_) => continue,
                Message::Close(_) => return Err(connection_closed()),
                Message::Frame(_) => continue,
            };
            if bytes.len() > limits.max_frame_bytes {
                return Err(response_too_large());
            }
            aggregate = aggregate.saturating_add(bytes.len());
            if aggregate > limits.max_aggregate_bytes {
                return Err(response_too_large());
            }
            let message: Value =
                serde_json::from_slice(&bytes).map_err(|_| malformed_response())?;
            if let Some((rejection, elicitation)) = server_request_rejection(&message)? {
                self.send_message(&rejection, limits).await?;
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

    fn enforce_backoff(&self) -> McpResult<()> {
        if self
            .retry_after
            .is_some_and(|retry_after| Instant::now() < retry_after)
        {
            return Err(restart_backoff());
        }
        Ok(())
    }

    async fn fail(&mut self, limits: SupervisorLimits) {
        self.stop().await;
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);
        self.retry_after = Some(Instant::now() + retry_delay(self.consecutive_failures, limits));
    }

    async fn stop(&mut self) {
        self.initialized_revision = None;
        self.server_info = None;
        if let Some(mut socket) = self.socket.take() {
            let _ = socket
                .close(Some(CloseFrame {
                    code: CloseCode::Normal,
                    reason: "local supervisor reset".into(),
                }))
                .await;
        }
    }
}
