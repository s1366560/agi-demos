//! The **strangler-fig gateway** (plan.md Section 14.1) — the single front door
//! that lets the Rust rewrite replace the Python backend one capability at a
//! time, with zero frontend changes and instant rollback.
//!
//! ```text
//!  client ──▶ gateway ──▶ /api/v1/memories|episodes|recall  ──▶ agistack-server (Rust)
//!                     └──▶ everything else                    ──▶ Python backend (legacy)
//! ```
//!
//! A capability is "strangled" by moving its path prefix into
//! [`STRANGLED_PREFIXES`]. Because both backends speak the same `/api/v1`
//! contract, same `ms_sk_` bearer auth, and same JSON shapes (guaranteed by the
//! P1 parity work), the client cannot tell which backend served a request — the
//! essence of the strangler pattern. Rollback = move the prefix back.
//!
//! The gateway is a dumb, deterministic reverse proxy: **routing is pure path
//! prefix matching** (no semantics), and it forwards method/headers/body
//! verbatim — including `Authorization`, so bearer auth passes through unchanged.
//! WebSocket paths are also proxied without interpreting application messages.

use std::sync::Arc;

use axum::{
    body::Body,
    extract::{
        ws::{CloseFrame as AxumCloseFrame, Message as AxumWsMessage, WebSocket, WebSocketUpgrade},
        State,
    },
    http::{HeaderMap, HeaderName, Request, Response, StatusCode, Uri},
    response::IntoResponse,
};
use futures_util::{SinkExt, StreamExt};
use tokio::net::TcpStream;
use tokio_tungstenite::{
    connect_async,
    tungstenite::{
        client::IntoClientRequest,
        handshake::client::Request as WsClientRequest,
        protocol::{
            frame::{
                coding::CloseCode as TungsteniteCloseCode, CloseFrame as TungsteniteCloseFrame,
            },
            Message as TungsteniteMessage,
        },
    },
    MaybeTlsStream, WebSocketStream,
};

mod routing;

pub use routing::{
    is_preview_host, is_strangled, is_strangled_request, strangled_rule_summary, upstream_for,
    upstream_for_request, upstream_for_request_with_headers, MethodMatchKind, MethodRule,
    Upstreams, STRANGLED_METHOD_RULES, STRANGLED_PREFIXES,
};
use routing::{is_preview_host_headers, upstream_for_request_with_preview};

/// Max proxied *request* body size — 25 MiB, generous for JSON payloads while
/// bounding memory (the 413 contract requires measuring the body before
/// forwarding). Response bodies are streamed, not buffered, so they need no
/// cap.
const MAX_BODY_BYTES: usize = 25 * 1024 * 1024;
/// Shared gateway state: a reusable HTTP client + the upstream addresses.
#[derive(Clone)]
pub struct GatewayState {
    pub client: reqwest::Client,
    pub upstreams: Arc<Upstreams>,
}

impl GatewayState {
    /// Builds shared gateway state with redirects disabled for backend parity.
    ///
    /// # Errors
    ///
    /// Returns the underlying reqwest error if the HTTP client cannot be built.
    pub fn try_new(upstreams: Upstreams) -> Result<Self, reqwest::Error> {
        let client = reqwest::Client::builder()
            // Do not follow redirects: a 307 from a backend must reach the client
            // unchanged (mirrors FastAPI trailing-slash semantics end to end).
            .redirect(reqwest::redirect::Policy::none())
            .build()?;
        Ok(Self {
            client,
            upstreams: Arc::new(upstreams),
        })
    }
}

/// Hop-by-hop headers (RFC 7230 §6.1) plus framing headers we must not copy
/// verbatim, since the proxied body is re-framed by the client/server.
fn is_hop_by_hop(name: &HeaderName) -> bool {
    matches!(
        name.as_str(),
        "connection"
            | "keep-alive"
            | "proxy-authenticate"
            | "proxy-authorization"
            | "te"
            | "trailer"
            | "transfer-encoding"
            | "upgrade"
            | "content-length"
            | "host"
    )
}

/// Copy end-to-end headers from `src` into `dst`, dropping hop-by-hop/framing
/// headers. `Authorization` is end-to-end, so bearer tokens pass through.
fn copy_end_to_end_headers(src: &HeaderMap, dst: &mut HeaderMap) {
    for (name, value) in src.iter() {
        if !is_hop_by_hop(name) {
            dst.append(name.clone(), value.clone());
        }
    }
}

fn websocket_url(upstream: &str, path_and_query: &str) -> String {
    let base = upstream.trim_end_matches('/');
    let ws_base = if let Some(rest) = base.strip_prefix("http://") {
        format!("ws://{rest}")
    } else if let Some(rest) = base.strip_prefix("https://") {
        format!("wss://{rest}")
    } else {
        base.to_string()
    };
    format!("{ws_base}{path_and_query}")
}

fn copy_websocket_forward_headers(src: &HeaderMap, dst: &mut HeaderMap) {
    for name in [
        HeaderName::from_static("authorization"),
        HeaderName::from_static("cookie"),
        HeaderName::from_static("sec-websocket-protocol"),
        HeaderName::from_static("x-request-id"),
        HeaderName::from_static("x-correlation-id"),
        HeaderName::from_static("x-forwarded-for"),
        HeaderName::from_static("x-real-ip"),
    ] {
        if let Some(value) = src.get(&name) {
            dst.insert(name, value.clone());
        }
    }
}

fn preserve_host_header(src: &HeaderMap, dst: &mut HeaderMap) {
    if let Some(value) = src.get(HeaderName::from_static("host")) {
        dst.insert(HeaderName::from_static("host"), value.clone());
    }
}

fn build_upstream_ws_request(
    url: &str,
    headers: &HeaderMap,
    preserve_host: bool,
) -> Result<WsClientRequest, String> {
    let mut request = url
        .into_client_request()
        .map_err(|err| format!("invalid upstream websocket request: {err}"))?;
    copy_websocket_forward_headers(headers, request.headers_mut());
    if preserve_host {
        preserve_host_header(headers, request.headers_mut());
    }
    Ok(request)
}

type UpstreamWs = WebSocketStream<MaybeTlsStream<TcpStream>>;
const WEBSOCKET_SUBPROTOCOLS: [&str; 2] = ["memstack.auth", "binary"];

/// Proxy the single strangled WebSocket endpoint. The gateway connects to the
/// Rust upstream before accepting the client upgrade, so upstream failures can
/// still surface as a normal FastAPI-shaped 502 response.
pub async fn websocket_proxy(
    State(state): State<GatewayState>,
    headers: HeaderMap,
    uri: Uri,
    ws: WebSocketUpgrade,
) -> Response<Body> {
    websocket_proxy_to_upstream(&state.upstreams.rust, headers, uri, ws, false).await
}

async fn websocket_proxy_to_upstream(
    upstream: &str,
    headers: HeaderMap,
    uri: Uri,
    ws: WebSocketUpgrade,
    preserve_host: bool,
) -> Response<Body> {
    let path_and_query = uri.path_and_query().map(|pq| pq.as_str()).unwrap_or("/");
    let upstream_url = websocket_url(upstream, path_and_query);
    let request = match build_upstream_ws_request(&upstream_url, &headers, preserve_host) {
        Ok(request) => request,
        Err(err) => return error_response(StatusCode::BAD_GATEWAY, &err),
    };
    let upstream = match connect_async(request).await {
        Ok((stream, _response)) => stream,
        Err(err) => {
            return error_response(
                StatusCode::BAD_GATEWAY,
                &format!("upstream websocket failed: {err}"),
            )
        }
    };

    ws.protocols(WEBSOCKET_SUBPROTOCOLS)
        .on_upgrade(move |socket| pump_websockets(socket, upstream))
        .into_response()
}

async fn pump_websockets(mut client: WebSocket, mut upstream: UpstreamWs) {
    loop {
        tokio::select! {
            incoming = client.recv() => {
                let Some(Ok(message)) = incoming else {
                    let _ = upstream.close(None).await;
                    break;
                };
                let should_close = matches!(message, AxumWsMessage::Close(_));
                if upstream.send(axum_to_tungstenite(message)).await.is_err() {
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
                if let Some(message) = tungstenite_to_axum(message) {
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

fn axum_to_tungstenite(message: AxumWsMessage) -> TungsteniteMessage {
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

fn tungstenite_to_axum(message: TungsteniteMessage) -> Option<AxumWsMessage> {
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

/// The catch-all proxy handler: forward any request to the upstream chosen by
/// its path, preserving method, end-to-end headers (incl. `Authorization`), and
/// body, then relay the upstream's status/headers/body back to the client.
pub async fn proxy(State(state): State<GatewayState>, req: Request<Body>) -> Response<Body> {
    let (parts, body) = req.into_parts();
    let path = parts.uri.path().to_string();
    let path_and_query = parts
        .uri
        .path_and_query()
        .map(|pq| pq.as_str())
        .unwrap_or("/");

    // Compute the preview-host verdict once per request and pass it down.
    let preview_host = is_preview_host_headers(&parts.headers);
    let upstream =
        upstream_for_request_with_preview(&parts.method, &path, preview_host, &state.upstreams);
    let url = format!("{upstream}{path_and_query}");

    let body_bytes = match axum::body::to_bytes(body, MAX_BODY_BYTES).await {
        Ok(bytes) => bytes,
        Err(_) => return error_response(StatusCode::PAYLOAD_TOO_LARGE, "request body too large"),
    };

    // Build the upstream request: same method + end-to-end headers + body.
    let mut forward_headers = HeaderMap::new();
    copy_end_to_end_headers(&parts.headers, &mut forward_headers);
    if preview_host {
        preserve_host_header(&parts.headers, &mut forward_headers);
    }

    let upstream_response = state
        .client
        .request(parts.method.clone(), &url)
        .headers(forward_headers)
        .body(body_bytes)
        .send()
        .await;

    let resp = match upstream_response {
        Ok(resp) => resp,
        Err(err) => {
            // Upstream unreachable / transport error -> 502, like a real gateway.
            return error_response(
                StatusCode::BAD_GATEWAY,
                &format!("upstream request failed: {err}"),
            );
        }
    };

    let status = resp.status();
    let mut response_headers = HeaderMap::new();
    copy_end_to_end_headers(resp.headers(), &mut response_headers);

    // Stream the upstream response body instead of materializing it: large
    // payloads (event replays, file downloads) no longer sit fully buffered in
    // gateway memory, and the first byte reaches the client immediately.
    // Trade-off: a mid-stream upstream failure now truncates the body instead
    // of producing a clean 502 — the standard behaviour of streaming gateways.
    let mut out = Response::new(Body::from_stream(resp.bytes_stream()));
    *out.status_mut() = status;
    *out.headers_mut() = response_headers;
    out
}

pub async fn fallback_proxy(
    State(state): State<GatewayState>,
    headers: HeaderMap,
    uri: Uri,
    ws: Option<WebSocketUpgrade>,
    req: Request<Body>,
) -> Response<Body> {
    if let Some(ws) = ws {
        if is_preview_host_headers(&headers) {
            return websocket_proxy_to_upstream(&state.upstreams.rust, headers, uri, ws, true)
                .await;
        }
    }
    proxy(State(state), req).await
}

/// A minimal JSON error envelope matching the `{"detail": ...}` shape the rest
/// of the stack uses.
fn error_response(status: StatusCode, detail: &str) -> Response<Body> {
    let body = format!("{{\"detail\":\"{}\"}}", detail.replace('"', "'"));
    let mut resp = Response::new(Body::from(body));
    *resp.status_mut() = status;
    resp.headers_mut().insert(
        axum::http::header::CONTENT_TYPE,
        axum::http::HeaderValue::from_static("application/json"),
    );
    resp
}

/// Build the gateway router: a single catch-all that proxies every method and
/// path. Callers `serve` this or drive it in tests.
pub fn app(state: GatewayState) -> axum::Router {
    use axum::routing::{any, get};
    axum::Router::new()
        .route("/api/v1/agent/ws", get(websocket_proxy))
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop/proxy/websockify",
            get(websocket_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal/proxy/ws",
            get(websocket_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/mcp/proxy",
            get(websocket_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws",
            get(websocket_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws/*path",
            get(websocket_proxy),
        )
        .fallback(any(fallback_proxy))
        .with_state(state)
}

#[cfg(test)]
mod unit {
    use super::*;

    #[test]
    fn authorization_is_end_to_end() {
        // The bearer token must survive proxying -> not hop-by-hop.
        assert!(!is_hop_by_hop(&HeaderName::from_static("authorization")));
        // Framing/hop-by-hop headers are dropped.
        assert!(is_hop_by_hop(&HeaderName::from_static("content-length")));
        assert!(is_hop_by_hop(&HeaderName::from_static("connection")));
        assert!(is_hop_by_hop(&HeaderName::from_static("transfer-encoding")));
    }

    #[test]
    fn websocket_url_converts_http_base_to_ws() {
        assert_eq!(
            websocket_url("http://rust:8088", "/api/v1/agent/ws?token=ms_sk_x"),
            "ws://rust:8088/api/v1/agent/ws?token=ms_sk_x"
        );
        assert_eq!(
            websocket_url("https://rust.example", "/api/v1/agent/ws"),
            "wss://rust.example/api/v1/agent/ws"
        );
    }
}
