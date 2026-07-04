//! End-to-end proof of the strangler gateway (plan.md Section 14.4 step 4):
//! two mock upstreams (a stand-in Rust server and a stand-in Python backend) +
//! the real gateway. We assert that strangled prefixes reach the Rust upstream,
//! everything else reaches the Python upstream, the `Authorization` bearer is
//! forwarded unchanged, method + body are preserved, and upstream redirects are
//! relayed (not followed). No full Python stack required.

use std::net::SocketAddr;

use axum::{
    body::Body,
    extract::{
        ws::{Message as AxumWsMessage, WebSocketUpgrade},
        State,
    },
    http::{header::CONTENT_TYPE, HeaderMap, HeaderValue, Request, Response, StatusCode, Uri},
    response::IntoResponse,
    routing::get,
    Router,
};
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{
    connect_async,
    tungstenite::{client::IntoClientRequest, Message as TungsteniteMessage},
};

use agistack_gateway::{app, GatewayState, Upstreams};

fn gateway_state(upstreams: Upstreams) -> GatewayState {
    GatewayState::try_new(upstreams).expect("test reqwest client should build")
}

/// A mock upstream that echoes which backend served the request plus the method,
/// path, forwarded `Authorization`, and body — so the test can assert routing
/// and header/body passthrough.
async fn echo(State(backend): State<&'static str>, req: Request<Body>) -> Response<Body> {
    let (parts, body) = req.into_parts();
    let auth = parts
        .headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let host = parts
        .headers
        .get("host")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let method = parts.method.as_str().to_string();
    let path = parts.uri.path().to_string();
    let body_bytes = axum::body::to_bytes(body, 1 << 20)
        .await
        .unwrap_or_default();
    let body_str = String::from_utf8_lossy(&body_bytes).replace('"', "'");
    let json = format!(
        "{{\"backend\":\"{backend}\",\"method\":\"{method}\",\"path\":\"{path}\",\"host\":\"{host}\",\"auth\":\"{auth}\",\"body\":\"{body_str}\"}}"
    );
    let mut resp = Response::new(Body::from(json));
    resp.headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    resp
}

async fn redirect() -> Response<Body> {
    let mut resp = Response::new(Body::empty());
    *resp.status_mut() = StatusCode::TEMPORARY_REDIRECT;
    resp.headers_mut().insert(
        axum::http::header::LOCATION,
        HeaderValue::from_static("/moved"),
    );
    resp
}

async fn ws_echo(
    State(backend): State<&'static str>,
    headers: HeaderMap,
    uri: Uri,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    let protocol = headers
        .get("sec-websocket-protocol")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let auth = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let host = headers
        .get("host")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let path = uri.path().to_string();
    ws.protocols(["memstack.auth", "binary"])
        .on_upgrade(move |mut socket| async move {
            let Some(Ok(AxumWsMessage::Text(text))) = socket.recv().await else {
                return;
            };
            let body = format!(
                "{{\"backend\":\"{backend}\",\"path\":\"{path}\",\"host\":\"{host}\",\"protocol\":\"{protocol}\",\"auth\":\"{auth}\",\"message\":{text}}}"
            );
            let _ = socket.send(AxumWsMessage::Text(body)).await;
        })
}

/// Bind an axum app on an ephemeral port and serve it in the background; return
/// its base URL (e.g. `http://127.0.0.1:54321`).
async fn spawn(router: Router) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    format!("http://{addr}")
}

fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .unwrap()
}

#[path = "proxy/agent_ws.rs"]
mod agent_ws;
#[path = "proxy/preview_http.rs"]
mod preview_http;
#[path = "proxy/preview_ws.rs"]
mod preview_ws;
#[path = "proxy/sandbox_ws.rs"]
mod sandbox_ws;
#[path = "proxy/strangler_http.rs"]
mod strangler_http;
