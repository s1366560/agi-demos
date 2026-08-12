//! Reconnecting WebSocket client for the browser bridge.
//!
//! [`BridgeWsClient`] owns one background connection task that speaks the
//! bridge contract to the broker's WebSocket endpoint
//! (`ws://127.0.0.1:<port>/api/v1/browser-bridge/ws`, authenticated with an
//! `Authorization: Bearer <token>` header). Callers use [`request`], which
//! correlates responses by JSON-RPC id over an outbound mpsc queue + oneshot
//! waiters (the same shape as `adapters-mcp`'s `WsMcpToolHost`); extension
//! notifications (`onCDPEvent` / `onCDPDetach`) are faned out over a
//! `broadcast` channel.
//!
//! On connection loss the task fails all in-flight waiters and reconnects
//! with capped exponential backoff (250ms → 1s → 4s → 10s). Requests queued
//! while disconnected are sent once the socket is back.
//!
//! [`request`]: BridgeWsClient::request

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tokio::net::TcpStream;
use tokio::sync::{broadcast, mpsc, oneshot, Notify};
use tokio::task::JoinHandle;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{connect_async, MaybeTlsStream, WebSocketStream};

use agistack_core::ports::{CoreError, CoreResult};

use crate::jsonrpc::{self, JsonRpcMessage};
use crate::protocol::BridgeNotification;

type Ws = WebSocketStream<MaybeTlsStream<TcpStream>>;

const OUTBOUND_BUFFER: usize = 32;
const NOTIFICATION_BUFFER: usize = 256;
/// Capped exponential backoff between reconnect attempts.
const BACKOFF_STEPS: [Duration; 4] = [
    Duration::from_millis(250),
    Duration::from_secs(1),
    Duration::from_secs(4),
    Duration::from_secs(10),
];

fn tool_err(message: impl Into<String>) -> CoreError {
    CoreError::Tool(message.into())
}

/// Build the bridge WebSocket URL for a broker listening on `port`.
pub fn bridge_ws_url(port: u16) -> String {
    format!("ws://127.0.0.1:{port}/api/v1/browser-bridge/ws")
}

/// Shared state between the client handle and the connection task.
struct Shared {
    waiters: Mutex<HashMap<u64, oneshot::Sender<Result<Value, String>>>>,
    notifications: broadcast::Sender<BridgeNotification>,
    shutdown: AtomicBool,
    notify_shutdown: Notify,
}

/// A client of the browser-bridge WebSocket endpoint.
///
/// Clone-cheap (all state is shared); dropping the last handle does **not**
/// stop the background task — call [`shutdown`](BridgeWsClient::shutdown).
pub struct BridgeWsClient {
    next_id: AtomicU64,
    outbound: mpsc::Sender<String>,
    shared: Arc<Shared>,
    task: Mutex<Option<JoinHandle<()>>>,
}

impl BridgeWsClient {
    /// Connect to the bridge at `url` (see [`bridge_ws_url`]) using a bearer
    /// `token`. The first connection attempt happens eagerly and its failure
    /// is returned; later drops reconnect in the background.
    pub async fn connect(url: &str, token: &str) -> CoreResult<Self> {
        let ws = establish(url, token).await?;
        let (outbound, outbound_rx) = mpsc::channel(OUTBOUND_BUFFER);
        let (notifications, _) = broadcast::channel(NOTIFICATION_BUFFER);
        let shared = Arc::new(Shared {
            waiters: Mutex::new(HashMap::new()),
            notifications,
            shutdown: AtomicBool::new(false),
            notify_shutdown: Notify::new(),
        });
        let task = tokio::spawn(run_connection(
            url.to_string(),
            token.to_string(),
            ws,
            outbound_rx,
            Arc::clone(&shared),
        ));
        Ok(Self {
            next_id: AtomicU64::new(1),
            outbound,
            shared,
            task: Mutex::new(Some(task)),
        })
    }

    /// Subscribe to extension notifications (CDP events, detach). Lagging
    /// receivers get `RecvError::Lagged` from the broadcast channel.
    pub fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification> {
        self.shared.notifications.subscribe()
    }

    /// Issue a bridge request and await the correlated response. A bridge
    /// `error` object maps to [`CoreError::Tool`].
    pub async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = oneshot::channel();
        self.shared.waiters.lock().unwrap().insert(id, tx);
        let frame = jsonrpc::encode_request(id, method, params);
        if self.outbound.send(frame).await.is_err() {
            self.shared.waiters.lock().unwrap().remove(&id);
            return Err(tool_err("browser bridge client is shut down"));
        }
        match rx.await {
            Ok(Ok(result)) => Ok(result),
            Ok(Err(message)) => Err(tool_err(format!("browser bridge error: {message}"))),
            Err(_) => Err(tool_err("browser bridge connection dropped the response")),
        }
    }

    /// Stop the background connection task. In-flight requests are failed.
    pub async fn shutdown(&self) {
        self.shared.shutdown.store(true, Ordering::SeqCst);
        self.shared.notify_shutdown.notify_waiters();
        let task = self.task.lock().unwrap().take();
        if let Some(task) = task {
            task.abort();
            let _ = task.await;
        }
        fail_waiters(&self.shared, "browser bridge client shut down");
    }
}

impl Drop for BridgeWsClient {
    fn drop(&mut self) {
        self.shared.shutdown.store(true, Ordering::SeqCst);
        if let Some(task) = self.task.get_mut().unwrap().take() {
            task.abort();
        }
    }
}

/// Open the WebSocket and present the bearer token during the handshake.
async fn establish(url: &str, token: &str) -> CoreResult<Ws> {
    let mut request = url
        .into_client_request()
        .map_err(|e| tool_err(format!("invalid bridge url {url}: {e}")))?;
    let auth = format!("Bearer {token}")
        .parse()
        .map_err(|_| tool_err("bridge token is not a valid header value"))?;
    request.headers_mut().insert(
        tokio_tungstenite::tungstenite::http::header::AUTHORIZATION,
        auth,
    );
    let (ws, _response) = connect_async(request)
        .await
        .map_err(|e| tool_err(format!("browser bridge connect failed: {e}")))?;
    Ok(ws)
}

/// Connection task body: serve the live socket; on loss, fail all waiters and
/// reconnect with capped exponential backoff until shutdown.
async fn run_connection(
    url: String,
    token: String,
    mut ws: Ws,
    mut outbound: mpsc::Receiver<String>,
    shared: Arc<Shared>,
) {
    let mut failures = 0usize;
    'outer: loop {
        serve_session(ws, &mut outbound, &shared).await;
        fail_waiters(&shared, "browser bridge connection lost");

        // Reconnect loop: capped exponential backoff, reset on success.
        loop {
            if shared.shutdown.load(Ordering::SeqCst) {
                return;
            }
            let delay = BACKOFF_STEPS[failures.min(BACKOFF_STEPS.len() - 1)];
            failures += 1;
            tokio::select! {
                _ = tokio::time::sleep(delay) => {}
                _ = shared.notify_shutdown.notified() => return,
            }
            match establish(&url, &token).await {
                Ok(reconnected) => {
                    failures = 0;
                    ws = reconnected;
                    continue 'outer;
                }
                Err(e) => {
                    tracing::warn!("browser bridge reconnect failed: {e}");
                }
            }
        }
    }
}

/// Serve one live socket until it errors, closes, or shutdown is requested.
async fn serve_session(ws: Ws, outbound: &mut mpsc::Receiver<String>, shared: &Arc<Shared>) {
    let (mut sink, mut stream) = ws.split();
    loop {
        tokio::select! {
            frame = outbound.recv() => {
                match frame {
                    Some(frame) => {
                        if let Err(e) = sink.send(Message::Text(frame)).await {
                            tracing::warn!("browser bridge send failed: {e}");
                            return;
                        }
                    }
                    // All senders dropped: nothing left to do on this socket.
                    None => return,
                }
            }
            message = stream.next() => {
                match message {
                    Some(Ok(Message::Text(text))) => dispatch(&text, shared),
                    Some(Ok(Message::Binary(bytes))) => {
                        dispatch(&String::from_utf8_lossy(&bytes), shared)
                    }
                    Some(Ok(Message::Close(_))) | None => return,
                    Some(Ok(_)) => {} // Ping/Pong carry no payload.
                    Some(Err(e)) => {
                        tracing::warn!("browser bridge receive failed: {e}");
                        return;
                    }
                }
            }
            _ = shared.notify_shutdown.notified() => return,
        }
    }
}

/// Route one inbound frame: responses complete waiters, notifications are
/// broadcast, extension-initiated requests are logged and ignored.
fn dispatch(payload: &str, shared: &Arc<Shared>) {
    match jsonrpc::decode(payload) {
        Ok(JsonRpcMessage::Response { id, result }) => {
            let waiter = shared.waiters.lock().unwrap().remove(&id);
            if let Some(waiter) = waiter {
                let _ = waiter.send(result.map_err(|e| format!("code {}: {}", e.code, e.message)));
            }
        }
        Ok(JsonRpcMessage::Notification { method, params }) => {
            let _ = shared
                .notifications
                .send(BridgeNotification { method, params });
        }
        Ok(JsonRpcMessage::Request { method, .. }) => {
            tracing::debug!("ignoring extension-initiated bridge request: {method}");
        }
        Err(e) => {
            tracing::warn!("dropping malformed bridge frame: {e}");
        }
    }
}

/// Fail every pending waiter (connection loss or shutdown).
fn fail_waiters(shared: &Arc<Shared>, reason: &str) {
    let waiters: Vec<_> = shared
        .waiters
        .lock()
        .unwrap()
        .drain()
        .map(|(_, w)| w)
        .collect();
    for waiter in waiters {
        let _ = waiter.send(Err(reason.to_string()));
    }
}
