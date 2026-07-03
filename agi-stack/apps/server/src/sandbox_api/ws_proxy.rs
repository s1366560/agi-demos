use std::sync::Arc;
use std::time::Duration;

use axum::extract::ws::{CloseFrame as AxumCloseFrame, Message as AxumWsMessage, WebSocket};
use axum::http::HeaderValue;
use futures_util::{SinkExt, StreamExt};
use rustls::{
    client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier},
    pki_types::{CertificateDer, ServerName, UnixTime},
    DigitallySignedStruct, Error as RustlsError, SignatureScheme,
};
use serde::Deserialize;
use serde_json::json;
use tokio_tungstenite::{
    connect_async, connect_async_tls_with_config,
    tungstenite::{
        client::IntoClientRequest,
        protocol::{
            frame::{
                coding::CloseCode as TungsteniteCloseCode, CloseFrame as TungsteniteCloseFrame,
            },
            Message as TungsteniteMessage,
        },
    },
    Connector,
};

use super::*;

#[derive(Debug)]
struct NoDesktopCertificateVerification;

impl ServerCertVerifier for NoDesktopCertificateVerification {
    fn verify_server_cert(
        &self,
        _end_entity: &CertificateDer<'_>,
        _intermediates: &[CertificateDer<'_>],
        _server_name: &ServerName<'_>,
        _ocsp_response: &[u8],
        _now: UnixTime,
    ) -> Result<ServerCertVerified, RustlsError> {
        Ok(ServerCertVerified::assertion())
    }

    fn verify_tls12_signature(
        &self,
        _message: &[u8],
        _cert: &CertificateDer<'_>,
        _dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, RustlsError> {
        Ok(HandshakeSignatureValid::assertion())
    }

    fn verify_tls13_signature(
        &self,
        _message: &[u8],
        _cert: &CertificateDer<'_>,
        _dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, RustlsError> {
        Ok(HandshakeSignatureValid::assertion())
    }

    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        vec![
            SignatureScheme::RSA_PKCS1_SHA256,
            SignatureScheme::RSA_PKCS1_SHA384,
            SignatureScheme::RSA_PKCS1_SHA512,
            SignatureScheme::RSA_PSS_SHA256,
            SignatureScheme::RSA_PSS_SHA384,
            SignatureScheme::RSA_PSS_SHA512,
            SignatureScheme::ECDSA_NISTP256_SHA256,
            SignatureScheme::ECDSA_NISTP384_SHA384,
            SignatureScheme::ED25519,
        ]
    }
}

fn desktop_ws_tls_connector() -> Connector {
    let config = rustls::ClientConfig::builder_with_provider(
        rustls::crypto::aws_lc_rs::default_provider().into(),
    )
    .with_safe_default_protocol_versions()
    .expect("rustls default protocol versions are valid")
    .dangerous()
    .with_custom_certificate_verifier(Arc::new(NoDesktopCertificateVerification))
    .with_no_client_auth();
    Connector::Rustls(Arc::new(config))
}

pub(super) async fn proxy_mcp_ws_session(socket: WebSocket, ws_target: String) {
    let request = match ws_target.into_client_request() {
        Ok(request) => request,
        Err(_) => {
            close_mcp_ws_with_internal_error(socket).await;
            return;
        }
    };

    let upstream = match tokio::time::timeout(Duration::from_secs(10), connect_async(request)).await
    {
        Ok(Ok((stream, _response))) => stream,
        _ => {
            close_mcp_ws_with_internal_error(socket).await;
            return;
        }
    };

    let (mut client_tx, mut client_rx) = socket.split();
    let (mut upstream_tx, mut upstream_rx) = upstream.split();

    loop {
        tokio::select! {
            incoming = client_rx.next() => {
                let Some(Ok(message)) = incoming else {
                    let _ = upstream_tx.close().await;
                    break;
                };
                let should_close = matches!(message, AxumWsMessage::Close(_));
                if upstream_tx.send(axum_ws_to_tungstenite(message)).await.is_err() {
                    break;
                }
                if should_close {
                    break;
                }
            }
            incoming = upstream_rx.next() => {
                let Some(message) = incoming else {
                    let _ = client_tx
                        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                            code: 1001,
                            reason: "Upstream disconnected".into(),
                        })))
                        .await;
                    break;
                };
                match message {
                    Ok(TungsteniteMessage::Text(text)) => {
                        let normalized = normalize_mcp_resource_mime_type(&text);
                        if client_tx
                            .send(AxumWsMessage::Text(normalized))
                            .await
                            .is_err()
                        {
                            break;
                        }
                    }
                    Ok(message) => {
                        let should_close = matches!(message, TungsteniteMessage::Close(_));
                        if let Some(message) = tungstenite_ws_to_axum(message) {
                            if client_tx.send(message).await.is_err() {
                                break;
                            }
                        }
                        if should_close {
                            break;
                        }
                    }
                    Err(_) => {
                        let _ = client_tx
                            .send(AxumWsMessage::Text(
                                json!({ "error": "MCP WebSocket proxy failed" }).to_string(),
                            ))
                            .await;
                        let _ = client_tx
                            .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                                code: 1011,
                                reason: "MCP WebSocket proxy failure".into(),
                            })))
                            .await;
                        break;
                    }
                }
            }
        }
    }
}

pub(super) async fn proxy_http_service_ws_session(
    socket: WebSocket,
    ws_target: String,
    origin: String,
) {
    let mut request = match ws_target.into_client_request() {
        Ok(request) => request,
        Err(_) => {
            close_http_service_ws_with_internal_error(socket).await;
            return;
        }
    };
    let origin = match HeaderValue::from_str(&origin) {
        Ok(origin) => origin,
        Err(_) => {
            close_http_service_ws_with_internal_error(socket).await;
            return;
        }
    };
    request.headers_mut().insert("origin", origin);

    let upstream = match tokio::time::timeout(Duration::from_secs(10), connect_async(request)).await
    {
        Ok(Ok((stream, _response))) => stream,
        _ => {
            close_http_service_ws_with_internal_error(socket).await;
            return;
        }
    };
    pump_http_service_websockets(socket, upstream).await;
}

#[derive(Debug, Deserialize)]
struct TerminalClientWsMessage {
    #[serde(rename = "type")]
    kind: String,
    data: Option<String>,
    cols: Option<u16>,
    rows: Option<u16>,
}

pub(super) fn new_terminal_session_id() -> String {
    agistack_adapters_secrets::generate_uuid_v4()
        .replace('-', "")
        .chars()
        .take(12)
        .collect()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct TerminalSize {
    pub(super) cols: u16,
    pub(super) rows: u16,
}

impl Default for TerminalSize {
    fn default() -> Self {
        Self {
            cols: TERMINAL_DEFAULT_COLS,
            rows: TERMINAL_DEFAULT_ROWS,
        }
    }
}

impl TerminalSize {
    fn update(self, cols: Option<u16>, rows: Option<u16>) -> Self {
        Self {
            cols: cols.unwrap_or(self.cols).max(1),
            rows: rows.unwrap_or(self.rows).max(1),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TerminalSessionRecord {
    pub(super) project_id: String,
    pub(super) session_id: String,
    pub(super) cols: u16,
    pub(super) rows: u16,
    pub(super) connected: bool,
    pub(super) last_seen_at_ms: i64,
    pub(super) expires_at_ms: i64,
}

impl TerminalSessionRecord {
    pub(super) fn new(
        project_id: String,
        session_id: String,
        size: TerminalSize,
        connected: bool,
        now_ms: i64,
        ttl_seconds: i64,
    ) -> Self {
        Self {
            project_id,
            session_id,
            cols: size.cols,
            rows: size.rows,
            connected,
            last_seen_at_ms: now_ms,
            expires_at_ms: now_ms + ttl_seconds.max(1) * 1000,
        }
    }

    pub(super) fn size(&self) -> TerminalSize {
        TerminalSize {
            cols: self.cols.max(1),
            rows: self.rows.max(1),
        }
    }
}

fn terminal_connected_message(session_id: &str, size: TerminalSize) -> String {
    json!({
        "type": "connected",
        "session_id": session_id,
        "cols": size.cols,
        "rows": size.rows,
    })
    .to_string()
}

fn terminal_output_message(data: &str) -> String {
    json!({
        "type": "output",
        "data": data,
    })
    .to_string()
}

pub(super) fn terminal_error_message() -> String {
    json!({
        "type": "error",
        "message": "Terminal WebSocket proxy failed",
    })
    .to_string()
}

fn ttyd_initial_terminal_message(size: TerminalSize) -> TungsteniteMessage {
    TungsteniteMessage::Binary(
        json!({
            "AuthToken": "",
            "columns": size.cols,
            "rows": size.rows,
        })
        .to_string()
        .into_bytes(),
    )
}

fn ttyd_input_message(data: &[u8]) -> TungsteniteMessage {
    let mut payload = Vec::with_capacity(data.len() + 1);
    payload.push(TTYD_INPUT_COMMAND);
    payload.extend_from_slice(data);
    TungsteniteMessage::Binary(payload)
}

fn ttyd_resize_message(size: TerminalSize) -> TungsteniteMessage {
    let mut payload = Vec::with_capacity(32);
    payload.push(TTYD_RESIZE_COMMAND);
    payload.extend_from_slice(
        json!({
            "columns": size.cols,
            "rows": size.rows,
        })
        .to_string()
        .as_bytes(),
    );
    TungsteniteMessage::Binary(payload)
}

fn ttyd_output_payload(data: &[u8]) -> Option<String> {
    let (&command, payload) = data.split_first()?;
    match command {
        TTYD_INPUT_COMMAND => Some(String::from_utf8_lossy(payload).to_string()),
        TTYD_RESIZE_COMMAND | TTYD_PREFERENCES_COMMAND => None,
        _ => Some(String::from_utf8_lossy(data).to_string()),
    }
}

#[derive(Clone)]
pub(super) struct TerminalSessionRecorder {
    registry: SharedHttpServiceRegistry,
    project_id: String,
    session_id: String,
    ttl_seconds: i64,
}

impl TerminalSessionRecorder {
    pub(super) fn new(
        registry: SharedHttpServiceRegistry,
        project_id: String,
        session_id: String,
        ttl_seconds: i64,
    ) -> Self {
        Self {
            registry,
            project_id,
            session_id,
            ttl_seconds,
        }
    }

    pub(super) async fn store(&self, size: TerminalSize, connected: bool) -> SandboxApiResult<()> {
        let now = now_ms();
        let record = TerminalSessionRecord::new(
            self.project_id.clone(),
            self.session_id.clone(),
            size,
            connected,
            now,
            self.ttl_seconds,
        );
        self.registry
            .upsert_terminal_session(record, self.ttl_seconds)
            .await
    }
}

pub(super) async fn proxy_terminal_ws_session(
    socket: WebSocket,
    ws_target: String,
    origin: String,
    session_id: String,
    initial_size: TerminalSize,
    recorder: TerminalSessionRecorder,
) {
    let mut request = match ws_target.into_client_request() {
        Ok(request) => request,
        Err(_) => {
            close_terminal_ws_with_internal_error(socket).await;
            return;
        }
    };
    let origin = match HeaderValue::from_str(&origin) {
        Ok(origin) => origin,
        Err(_) => {
            close_terminal_ws_with_internal_error(socket).await;
            return;
        }
    };
    request.headers_mut().insert("origin", origin);

    let upstream = match tokio::time::timeout(Duration::from_secs(10), connect_async(request)).await
    {
        Ok(Ok((stream, _response))) => stream,
        _ => {
            close_terminal_ws_with_internal_error(socket).await;
            return;
        }
    };

    let (mut client_tx, mut client_rx) = socket.split();
    let (mut upstream_tx, mut upstream_rx) = upstream.split();
    let mut terminal_size = initial_size;
    if recorder.store(terminal_size, true).await.is_err() {
        let _ = client_tx
            .send(AxumWsMessage::Text(terminal_error_message()))
            .await;
        let _ = client_tx
            .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                code: 1011,
                reason: "Terminal WebSocket proxy failure".into(),
            })))
            .await;
        let _ = upstream_tx.close().await;
        return;
    }
    if upstream_tx
        .send(ttyd_initial_terminal_message(terminal_size))
        .await
        .is_err()
    {
        let _ = client_tx
            .send(AxumWsMessage::Text(terminal_error_message()))
            .await;
        let _ = client_tx
            .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                code: 1011,
                reason: "Terminal WebSocket proxy failure".into(),
            })))
            .await;
        return;
    }
    if client_tx
        .send(AxumWsMessage::Text(terminal_connected_message(
            &session_id,
            terminal_size,
        )))
        .await
        .is_err()
    {
        let _ = upstream_tx.close().await;
        return;
    }

    loop {
        tokio::select! {
            incoming = client_rx.next() => {
                let Some(Ok(message)) = incoming else {
                    let _ = upstream_tx.close().await;
                    break;
                };
                match message {
                    AxumWsMessage::Text(text) => {
                        let parsed = serde_json::from_str::<TerminalClientWsMessage>(&text);
                        let Ok(message) = parsed else {
                            let _ = client_tx
                                .send(AxumWsMessage::Text(terminal_error_message()))
                                .await;
                            let _ = client_tx
                                .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                                    code: 1011,
                                    reason: "Terminal WebSocket proxy failure".into(),
                                })))
                                .await;
                            let _ = upstream_tx.close().await;
                            break;
                        };
                        match message.kind.as_str() {
                            "input" => {
                                let data = message.data.unwrap_or_default();
                                if upstream_tx
                                    .send(ttyd_input_message(data.as_bytes()))
                                    .await
                                    .is_err()
                                {
                                    break;
                                }
                            }
                            "resize" => {
                                terminal_size = terminal_size.update(message.cols, message.rows);
                                if upstream_tx
                                    .send(ttyd_resize_message(terminal_size))
                                    .await
                                    .is_err()
                                {
                                    break;
                                }
                                if recorder.store(terminal_size, true).await.is_err() {
                                    let _ = client_tx
                                        .send(AxumWsMessage::Text(terminal_error_message()))
                                        .await;
                                    let _ = client_tx
                                        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                                            code: 1011,
                                            reason: "Terminal WebSocket proxy failure".into(),
                                        })))
                                        .await;
                                    let _ = upstream_tx.close().await;
                                    break;
                                }
                            }
                            "ping"
                                if client_tx
                                    .send(AxumWsMessage::Text(
                                        json!({ "type": "pong" }).to_string(),
                                    ))
                                    .await
                                    .is_err() =>
                            {
                                break;
                            }
                            "ping" => {}
                            _ => {}
                        }
                    }
                    AxumWsMessage::Binary(binary) => {
                        if upstream_tx
                            .send(ttyd_input_message(binary.as_ref()))
                            .await
                            .is_err()
                        {
                            break;
                        }
                    }
                    AxumWsMessage::Ping(payload) => {
                        let _ = upstream_tx.send(TungsteniteMessage::Ping(payload)).await;
                    }
                    AxumWsMessage::Pong(payload) => {
                        let _ = upstream_tx.send(TungsteniteMessage::Pong(payload)).await;
                    }
                    AxumWsMessage::Close(close) => {
                        let _ = upstream_tx
                            .send(axum_ws_to_tungstenite(AxumWsMessage::Close(close)))
                            .await;
                        break;
                    }
                }
            }
            upstream = upstream_rx.next() => {
                let Some(message) = upstream else {
                    let _ = client_tx
                        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                            code: 1000,
                            reason: "Terminal upstream closed".into(),
                        })))
                        .await;
                    break;
                };
                match message {
                    Ok(TungsteniteMessage::Text(text)) => {
                        if let Some(output) = ttyd_output_payload(text.as_bytes()) {
                            if client_tx
                                .send(AxumWsMessage::Text(terminal_output_message(&output)))
                                .await
                                .is_err()
                            {
                                break;
                            }
                        }
                    }
                    Ok(TungsteniteMessage::Binary(binary)) => {
                        if let Some(output) = ttyd_output_payload(binary.as_ref()) {
                            if client_tx
                                .send(AxumWsMessage::Text(terminal_output_message(&output)))
                                .await
                                .is_err()
                            {
                                break;
                            }
                        }
                    }
                    Ok(TungsteniteMessage::Ping(payload)) => {
                        let _ = upstream_tx.send(TungsteniteMessage::Pong(payload)).await;
                    }
                    Ok(TungsteniteMessage::Pong(_)) => {}
                    Ok(TungsteniteMessage::Close(close)) => {
                        if let Some(close) =
                            tungstenite_ws_to_axum(TungsteniteMessage::Close(close))
                        {
                            let _ = client_tx.send(close).await;
                        }
                        break;
                    }
                    Ok(TungsteniteMessage::Frame(_)) => {}
                    Err(_) => {
                        let _ = client_tx
                            .send(AxumWsMessage::Text(terminal_error_message()))
                            .await;
                        let _ = client_tx
                            .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                                code: 1011,
                                reason: "Terminal WebSocket proxy failure".into(),
                            })))
                            .await;
                        break;
                    }
                }
            }
        }
    }
    let _ = recorder.store(terminal_size, false).await;
}

pub(super) async fn proxy_desktop_ws_session(socket: WebSocket, ws_target: String, origin: String) {
    let is_tls_target = match url::Url::parse(&ws_target) {
        Ok(url) => url.scheme() == "wss",
        Err(_) => {
            close_desktop_ws_with_internal_error(socket).await;
            return;
        }
    };
    let mut request = match ws_target.into_client_request() {
        Ok(request) => request,
        Err(_) => {
            close_desktop_ws_with_internal_error(socket).await;
            return;
        }
    };
    let origin = match HeaderValue::from_str(&origin) {
        Ok(origin) => origin,
        Err(_) => {
            close_desktop_ws_with_internal_error(socket).await;
            return;
        }
    };
    request.headers_mut().insert("origin", origin);
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static(DESKTOP_WEBSOCKET_SUBPROTOCOL),
    );

    let connect = async {
        if is_tls_target {
            connect_async_tls_with_config(request, None, false, Some(desktop_ws_tls_connector()))
                .await
        } else {
            connect_async(request).await
        }
    };
    let upstream = match tokio::time::timeout(Duration::from_secs(10), connect).await {
        Ok(Ok((stream, _response))) => stream,
        _ => {
            close_desktop_ws_with_internal_error(socket).await;
            return;
        }
    };
    pump_http_service_websockets(socket, upstream).await;
}

async fn pump_http_service_websockets(
    mut client: WebSocket,
    mut upstream: tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
) {
    loop {
        tokio::select! {
            incoming = client.recv() => {
                let Some(Ok(message)) = incoming else {
                    let _ = upstream.close(None).await;
                    break;
                };
                let should_close = matches!(message, AxumWsMessage::Close(_));
                if upstream.send(axum_ws_to_tungstenite(message)).await.is_err() {
                    break;
                }
                if should_close {
                    break;
                }
            }
            incoming = upstream.next() => {
                let Some(Ok(message)) = incoming else {
                    let _ = client.send(AxumWsMessage::Close(None)).await;
                    break;
                };
                let should_close = matches!(message, TungsteniteMessage::Close(_));
                if let Some(message) = tungstenite_ws_to_axum(message) {
                    if client.send(message).await.is_err() {
                        break;
                    }
                }
                if should_close {
                    break;
                }
            }
        }
    }
}

fn axum_ws_to_tungstenite(message: AxumWsMessage) -> TungsteniteMessage {
    match message {
        AxumWsMessage::Text(text) => TungsteniteMessage::Text(text),
        AxumWsMessage::Binary(binary) => TungsteniteMessage::Binary(binary),
        AxumWsMessage::Ping(ping) => TungsteniteMessage::Ping(ping),
        AxumWsMessage::Pong(pong) => TungsteniteMessage::Pong(pong),
        AxumWsMessage::Close(Some(close)) => {
            TungsteniteMessage::Close(Some(TungsteniteCloseFrame {
                code: TungsteniteCloseCode::from(close.code),
                reason: close.reason,
            }))
        }
        AxumWsMessage::Close(None) => TungsteniteMessage::Close(None),
    }
}

fn tungstenite_ws_to_axum(message: TungsteniteMessage) -> Option<AxumWsMessage> {
    match message {
        TungsteniteMessage::Text(text) => Some(AxumWsMessage::Text(text)),
        TungsteniteMessage::Binary(binary) => Some(AxumWsMessage::Binary(binary)),
        TungsteniteMessage::Ping(ping) => Some(AxumWsMessage::Ping(ping)),
        TungsteniteMessage::Pong(pong) => Some(AxumWsMessage::Pong(pong)),
        TungsteniteMessage::Close(Some(close)) => {
            Some(AxumWsMessage::Close(Some(AxumCloseFrame {
                code: close.code.into(),
                reason: close.reason,
            })))
        }
        TungsteniteMessage::Close(None) => Some(AxumWsMessage::Close(None)),
        TungsteniteMessage::Frame(_) => None,
    }
}
