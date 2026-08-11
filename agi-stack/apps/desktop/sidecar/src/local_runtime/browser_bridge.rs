//! Browser-extension bridge: registry file, authenticated WebSocket server
//! for the native-messaging broker, and the in-process endpoint behind
//! [`BrowserToolHost`].
//!
//! Topology (see `docs/design/browser-extension-bridge.md` §4): the Chrome
//! extension talks native messaging to the broker (`--native-host` mode of
//! this binary); the broker connects back to this module's WebSocket endpoint
//! (`GET /api/v1/browser-bridge/ws`, `Authorization: Bearer <token>`), and the
//! sidecar drives the browser by issuing bridge JSON-RPC requests over that
//! accepted socket. The connection credentials live in a registry file the
//! sidecar rewrites on every bridge start (`~/.memstack/browser-bridge/
//! registry.json`, directory 0700, file 0600).
//!
//! Multi-backend (M4): after auth the sidecar sends `hello {}` and the
//! broker's response names its backend (`"chrome-extension"`, `"iab"`;
//! absent/unknown defaults to `"chrome-extension"`). One live session per
//! backend — a same-backend reconnect replaces the incumbent, other backends
//! are untouched, and heartbeat/offline accounting is per session. Brokers
//! may also call back into the sidecar: `getSidePanelSession {}` mints a
//! side-panel credential, gated to the chrome-extension backend on the
//! peer-UID-checked unix socket; anything else gets JSON-RPC `-32601`.

use std::{
    collections::HashMap,
    path::{Path as FsPath, PathBuf},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};

use agistack_adapters_browser::{
    bridge_ws_url,
    host::{BridgeEndpoint, BrowserToolHost},
    jsonrpc::{self, JsonRpcMessage},
    protocol::{
        protocol_ranges_overlap, BridgeNotification, PROTOCOL_MAX, PROTOCOL_MIN, PROTOCOL_VERSION,
    },
};
use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use async_trait::async_trait;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Extension, State,
    },
    http::{header::AUTHORIZATION, HeaderMap, StatusCode},
    response::Response,
    routing::get,
    Router,
};
use chrono::Utc;
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::{
    net::TcpListener,
    sync::{broadcast, mpsc, oneshot, Notify},
    task::JoinHandle,
};
use url::Url;
use uuid::Uuid;

use super::session_store::DesktopSessionStore;
use crate::private_file_permissions::{
    set_private_directory_permissions, set_private_file_permissions,
};

/// Default loopback port for the bridge WebSocket server.
pub const DEFAULT_BROWSER_BRIDGE_PORT: u16 = 9765;
/// Extension ID pinned by the browser extension's manifest `key`.
pub const DEFAULT_EXTENSION_ID: &str = "enbljdpbhdllbbkcjhccmbgpkfmcdkkl";
/// On a port conflict the server retries the next this many ports.
const PORT_FALLBACK_ATTEMPTS: u16 = 10;
/// Registry document schema version written and accepted by this build.
pub const REGISTRY_SCHEMA_VERSION: u32 = 1;

const OUTBOUND_BUFFER: usize = 32;
const NOTIFICATION_BUFFER: usize = 256;
/// Filename of the unix-domain bridge socket inside the bridge directory.
const BRIDGE_SOCKET_FILE_NAME: &str = "bridge.sock";
/// Server-side liveness probe for a broker socket (§6 M2 心跳熔断): a WS
/// ping every interval; the session is declared offline after this many
/// consecutive intervals without any inbound frame. Heartbeat accounting is
/// per backend session (M4): one backend going silent never takes the
/// others offline.
const BROKER_HEARTBEAT_INTERVAL: Duration = Duration::from_secs(30);
const BROKER_HEARTBEAT_MISS_LIMIT: u8 = 2;
/// Upper bound on the post-auth `hello` exchange that identifies the
/// connecting backend. A broker that never answers is dropped.
const HELLO_TIMEOUT: Duration = Duration::from_secs(10);

/// Backend id of the Chrome extension broker.
pub(crate) const BACKEND_CHROME_EXTENSION: &str = "chrome-extension";
/// Backend id of the in-app browser connecting from the Electron main
/// process.
pub(crate) const BACKEND_IAB: &str = "iab";
/// Broker-initiated method minting a side-panel session (M4).
const BROKER_METHOD_GET_SIDE_PANEL_SESSION: &str = "getSidePanelSession";

fn default_bridge_port() -> u16 {
    DEFAULT_BROWSER_BRIDGE_PORT
}

fn default_extension_ids() -> Vec<String> {
    vec![DEFAULT_EXTENSION_ID.to_string()]
}

/// `browser_bridge` section of [`LocalRuntimeConfig`](super::LocalRuntimeConfig).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserBridgeConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_bridge_port")]
    pub port: u16,
    #[serde(default = "default_extension_ids")]
    pub extension_ids: Vec<String>,
    /// Gate for the full-CDP-access workstream; this milestone only carries
    /// the flag, it does not consume it.
    #[serde(default)]
    pub full_cdp_access_enabled: bool,
}

impl Default for BrowserBridgeConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            port: DEFAULT_BROWSER_BRIDGE_PORT,
            extension_ids: default_extension_ids(),
            full_cdp_access_enabled: false,
        }
    }
}

/// `browser_bridge` projection of [`LocalRuntimeStatus`](super::LocalRuntimeStatus).
#[derive(Clone, Debug, Serialize)]
pub struct BrowserBridgeStatus {
    pub enabled: bool,
    pub port: u16,
    pub broker_connected: bool,
    /// Backend ids with a live broker session (sorted; empty when offline).
    pub connected_backends: Vec<String>,
    pub extension_ids: Vec<String>,
    pub extension_id: Option<String>,
    pub extension_version: Option<String>,
}

/// Registry file written by the sidecar and consumed by the broker. Serialized
/// with camelCase keys (`schemaVersion`, `wsUrl`, ...) — that casing is part
/// of the frozen wire contract.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BridgeRegistry {
    pub schema_version: u32,
    pub ws_url: String,
    pub token: String,
    pub extension_ids: Vec<String>,
    pub sidecar_path: PathBuf,
    pub updated_at: String,
    /// Unix-domain socket the broker prefers over TCP. Written by unix
    /// sidecars only (`None` on Windows, where TCP remains the transport).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub socket_path: Option<String>,
}

/// The user's home directory (`$HOME` on unix, `%USERPROFILE%` on Windows).
pub(crate) fn home_dir() -> Result<PathBuf, String> {
    #[cfg(windows)]
    let value = std::env::var_os("USERPROFILE");
    #[cfg(not(windows))]
    let value = std::env::var_os("HOME");
    value
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| "cannot locate the user home directory".to_string())
}

/// `~/.memstack/browser-bridge/registry.json`.
pub(crate) fn registry_path() -> Result<PathBuf, String> {
    Ok(home_dir()?
        .join(".memstack")
        .join("browser-bridge")
        .join("registry.json"))
}

/// The unix bridge socket always sits next to the registry file as
/// `bridge.sock` (in production `~/.memstack/browser-bridge/bridge.sock`).
#[cfg(unix)]
pub(crate) fn bridge_socket_path(registry_path: &FsPath) -> Result<PathBuf, String> {
    let directory = registry_path
        .parent()
        .ok_or_else(|| "browser bridge registry path has no parent directory".to_string())?;
    Ok(directory.join(BRIDGE_SOCKET_FILE_NAME))
}

/// Write the registry file, enforcing 0700 on its directory and 0600 on the
/// file itself (the token inside is a bearer credential).
pub(crate) fn write_registry(path: &FsPath, registry: &BridgeRegistry) -> Result<(), String> {
    let directory = path
        .parent()
        .ok_or_else(|| "browser bridge registry path has no parent directory".to_string())?;
    std::fs::create_dir_all(directory).map_err(|error| error.to_string())?;
    set_private_directory_permissions(directory).map_err(|error| error.to_string())?;
    let serialized = serde_json::to_string_pretty(registry).map_err(|error| error.to_string())?;
    std::fs::write(path, serialized).map_err(|error| error.to_string())?;
    set_private_file_permissions(path).map_err(|error| error.to_string())?;
    Ok(())
}

pub(crate) fn read_registry(path: &FsPath) -> Result<BridgeRegistry, String> {
    validate_registry_file_permissions(path)?;
    let serialized = std::fs::read_to_string(path)
        .map_err(|error| format!("browser bridge registry is unreadable: {error}"))?;
    serde_json::from_str(&serialized)
        .map_err(|error| format!("browser bridge registry is invalid: {error}"))
}

/// Reject registry paths whose filesystem shape or Unix mode could expose the
/// bearer token. Windows ACL validation remains a release-platform blocker;
/// regular-file and symlink validation is enforced on every platform.
pub(crate) fn validate_registry_file_permissions(path: &FsPath) -> Result<(), String> {
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|error| format!("browser bridge registry metadata is unreadable: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.file_type().is_file() {
        return Err("browser bridge registry must be a regular file".to_string());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = metadata.permissions().mode() & 0o777;
        if mode & 0o077 != 0 {
            return Err(format!(
                "browser bridge registry permissions {mode:o} are broader than 0600"
            ));
        }
    }
    Ok(())
}

/// Validate the registry fields the broker depends on. Anything off-contract
/// fails closed — the broker must not connect with ambiguous credentials.
pub(crate) fn validate_registry(registry: &BridgeRegistry) -> Result<(), String> {
    if registry.schema_version != REGISTRY_SCHEMA_VERSION {
        return Err(format!(
            "browser bridge registry schema version {} is unsupported",
            registry.schema_version
        ));
    }
    let url = Url::parse(&registry.ws_url)
        .map_err(|error| format!("browser bridge registry wsUrl is invalid: {error}"))?;
    if !matches!(url.host_str(), Some("127.0.0.1") | Some("localhost")) {
        return Err("browser bridge registry wsUrl must target 127.0.0.1".to_string());
    }
    if registry.token.len() != 64 || !registry.token.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("browser bridge registry token is invalid".to_string());
    }
    if let Some(socket_path) = &registry.socket_path {
        validate_socket_path(socket_path)?;
    }
    Ok(())
}

/// Validate the advertised `socketPath`. The socket must be an absolute path
/// named `bridge.sock` directly inside the `.memstack/browser-bridge`
/// directory — the shape the sidecar itself writes. This is a shape check,
/// not a `$HOME` equality check, so it stays valid for relocated homes and
/// test fixtures; a rogue registry writer gains nothing from it either way
/// (the same 0600 file already hands them the bearer token).
fn validate_socket_path(socket_path: &str) -> Result<(), String> {
    let path = FsPath::new(socket_path);
    if !path.is_absolute() {
        return Err("browser bridge registry socketPath must be absolute".to_string());
    }
    if path.file_name() != Some(std::ffi::OsStr::new(BRIDGE_SOCKET_FILE_NAME)) {
        return Err(format!(
            "browser bridge registry socketPath must be named {BRIDGE_SOCKET_FILE_NAME}"
        ));
    }
    let parent = path.parent();
    let grandparent = parent.and_then(FsPath::parent);
    let in_bridge_dir = matches!(
        (
            grandparent.and_then(FsPath::file_name),
            parent.and_then(FsPath::file_name),
        ),
        (Some(base), Some(dir)) if base == ".memstack" && dir == "browser-bridge"
    );
    if !in_bridge_dir {
        return Err(
            "browser bridge registry socketPath must live in .memstack/browser-bridge".to_string(),
        );
    }
    Ok(())
}

/// Log the permission failure before [`read_registry`] returns the same
/// failure to the broker. The registry is never consumed after this warning.
pub(crate) fn warn_if_registry_permissions_open(path: &FsPath) {
    if let Err(error) = validate_registry_file_permissions(path) {
        tracing::warn!(path = %path.display(), %error, "browser bridge registry rejected");
    }
}

/// Constant-time bearer-token comparison.
pub(crate) fn token_matches(expected: &str, presented: &str) -> bool {
    if expected.len() != presented.len() {
        return false;
    }
    let mut difference = 0u8;
    for (left, right) in expected.bytes().zip(presented.bytes()) {
        difference |= left ^ right;
    }
    difference == 0
}

/// The transport one broker connection arrived on. Recorded per session
/// because broker-initiated privilege gates (`getSidePanelSession`) depend on
/// it: the unix socket is peer-UID checked, TCP is not.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum BridgeTransport {
    Tcp,
    #[cfg_attr(not(unix), allow(dead_code))] // only constructible on unix
    Unix,
}

impl BridgeTransport {
    fn label(self) -> &'static str {
        match self {
            Self::Tcp => "tcp",
            Self::Unix => "unix",
        }
    }
}

/// Everything the bridge needs to answer a broker's `getSidePanelSession`
/// request: the runtime's bound address, the launch capability, and the
/// session store that mints and audits local session credentials. Created by
/// the local runtime when the bridge (re)starts.
#[derive(Clone)]
pub(crate) struct SidePanelSessionMinter {
    api_base_url: String,
    launch_capability: String,
    session_store: DesktopSessionStore,
}

impl SidePanelSessionMinter {
    pub(super) fn new(
        api_base_url: String,
        launch_capability: String,
        session_store: DesktopSessionStore,
    ) -> Self {
        Self {
            api_base_url,
            launch_capability,
            session_store,
        }
    }

    /// Mint a fresh, non-trusted local session credential for the side panel.
    fn mint_credential(&self) -> Result<String, String> {
        let credential = format!(
            "local-session-{}.{}",
            Uuid::new_v4(),
            super::generate_capability_token()
        );
        let outcome = self
            .session_store
            .create_local_session(credential, false, Utc::now().timestamp_millis())
            .map_err(|error| error.to_string())?;
        Ok(outcome.access_token)
    }

    /// Fire-and-forget audit row for one `getSidePanelSession` call; a write
    /// failure is logged, never propagated.
    fn audit(&self, outcome: &str, target_summary: &str, latency_ms: i64) {
        if let Err(error) = self.session_store.insert_browser_action_audit(
            None,
            BROKER_METHOD_GET_SIDE_PANEL_SESSION,
            None,
            target_summary,
            outcome,
            latency_ms,
            Utc::now().timestamp_millis(),
        ) {
            tracing::warn!(%error, "failed to record browser action audit for getSidePanelSession");
        }
    }
}

/// One live broker connection. The server holds at most one of these per
/// backend id; a new authenticated connection for the same backend replaces
/// the previous one.
struct BrokerSession {
    backend: String,
    hello: BrokerHelloIdentity,
    transport: BridgeTransport,
    outbound: mpsc::Sender<String>,
    waiters: Mutex<HashMap<u64, oneshot::Sender<Result<Value, String>>>>,
    closed: AtomicBool,
    notify_closed: Notify,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct BrokerHelloIdentity {
    backend: String,
    extension_id: Option<String>,
    extension_version: Option<String>,
    protocol_version: u32,
    protocol_min: u32,
    protocol_max: u32,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct BrokerHelloWire {
    #[serde(default = "default_protocol_version")]
    protocol_version: u32,
    #[serde(default)]
    protocol_min: Option<u32>,
    #[serde(default)]
    protocol_max: Option<u32>,
    #[serde(default)]
    backend: Option<String>,
    #[serde(default)]
    extension_id: Option<String>,
    #[serde(default)]
    extension_version: Option<String>,
}

fn default_protocol_version() -> u32 {
    PROTOCOL_VERSION
}

impl BrokerSession {
    fn fail_waiters(&self, reason: &str) {
        let waiters: Vec<_> = self
            .waiters
            .lock()
            .expect("browser bridge waiters")
            .drain()
            .map(|(_, waiter)| waiter)
            .collect();
        for waiter in waiters {
            let _ = waiter.send(Err(reason.to_string()));
        }
    }
}

/// Error payload for a broker-initiated request. `audit_outcome` is the
/// `desktop_browser_action_audit.outcome` value the call records.
struct BrokerRequestError {
    code: i64,
    message: String,
    audit_outcome: &'static str,
}

impl BrokerRequestError {
    fn denied(message: impl Into<String>) -> Self {
        Self {
            code: 1,
            message: message.into(),
            audit_outcome: "denied",
        }
    }

    fn failed(message: impl Into<String>) -> Self {
        Self {
            code: 1,
            message: message.into(),
            audit_outcome: "error",
        }
    }
}

/// Shared state behind the bridge WebSocket route and the agent-facing
/// endpoint. One instance per bridge start; the token is fixed for its
/// lifetime (a start regenerates token *and* server).
pub(crate) struct BrowserBridgeServer {
    token: String,
    port: u16,
    backends: Mutex<HashMap<String, Arc<BrokerSession>>>,
    notifications: broadcast::Sender<BridgeNotification>,
    next_id: AtomicU64,
    minter: Option<SidePanelSessionMinter>,
    heartbeat_interval: Duration,
}

impl BrowserBridgeServer {
    fn with_heartbeat_interval(
        token: String,
        port: u16,
        minter: Option<SidePanelSessionMinter>,
        heartbeat_interval: Duration,
    ) -> Self {
        let (notifications, _) = broadcast::channel(NOTIFICATION_BUFFER);
        Self {
            token,
            port,
            backends: Mutex::new(HashMap::new()),
            notifications,
            next_id: AtomicU64::new(1),
            minter,
            heartbeat_interval,
        }
    }

    pub(crate) fn port(&self) -> u16 {
        self.port
    }

    /// The agent-facing surface key on the Chrome extension: true while a
    /// `chrome-extension` backend session is live.
    pub(crate) fn broker_connected(&self) -> bool {
        self.backends
            .lock()
            .expect("browser bridge backends")
            .contains_key(BACKEND_CHROME_EXTENSION)
    }

    /// Backend ids with a live session, sorted for a stable status payload.
    pub(crate) fn connected_backends(&self) -> Vec<String> {
        let mut backends: Vec<String> = self
            .backends
            .lock()
            .expect("browser bridge backends")
            .keys()
            .cloned()
            .collect();
        backends.sort();
        backends
    }

    fn chrome_extension_identity(&self) -> Option<BrokerHelloIdentity> {
        self.backends
            .lock()
            .expect("browser bridge backends")
            .get(BACKEND_CHROME_EXTENSION)
            .map(|session| session.hello.clone())
    }

    /// Issue one bridge request to the connected Chrome-extension broker,
    /// awaiting the correlated response. Fails immediately when that backend
    /// is not connected.
    pub(crate) async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        self.request_on(BACKEND_CHROME_EXTENSION, method, params)
            .await
    }

    /// Issue one bridge request to the session of one specific backend.
    pub(crate) async fn request_on(
        &self,
        backend: &str,
        method: &str,
        params: Value,
    ) -> CoreResult<Value> {
        let session = self
            .backends
            .lock()
            .expect("browser bridge backends")
            .get(backend)
            .cloned()
            .ok_or_else(|| {
                CoreError::Tool(format!(
                    "browser bridge backend '{backend}' is not connected"
                ))
            })?;
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = oneshot::channel();
        session
            .waiters
            .lock()
            .expect("browser bridge waiters")
            .insert(id, tx);
        let frame = jsonrpc::encode_request(id, method, params);
        if session.outbound.send(frame).await.is_err() {
            session
                .waiters
                .lock()
                .expect("browser bridge waiters")
                .remove(&id);
            return Err(CoreError::Tool(
                "browser bridge broker connection is closed".to_string(),
            ));
        }
        match rx.await {
            Ok(Ok(result)) => Ok(result),
            Ok(Err(message)) => Err(CoreError::Tool(format!("browser bridge error: {message}"))),
            Err(_) => Err(CoreError::Tool(
                "browser bridge broker dropped the response".to_string(),
            )),
        }
    }

    async fn dispatch_inbound(&self, session: &Arc<BrokerSession>, payload: &str) {
        match jsonrpc::decode(payload) {
            Ok(JsonRpcMessage::Response { id, result }) => {
                let waiter = session
                    .waiters
                    .lock()
                    .expect("browser bridge waiters")
                    .remove(&id);
                if let Some(waiter) = waiter {
                    let _ =
                        waiter.send(result.map_err(|e| format!("code {}: {}", e.code, e.message)));
                }
            }
            Ok(JsonRpcMessage::Notification { method, params }) => {
                let _ = self
                    .notifications
                    .send(BridgeNotification { method, params });
            }
            Ok(JsonRpcMessage::Request { id, method, .. }) => {
                self.dispatch_broker_request(session, id, &method).await;
            }
            Err(error) => {
                tracing::warn!(%error, "dropping malformed broker frame");
            }
        }
    }

    /// Answer a broker-originated request and route the reply frame to that
    /// session's outbound queue. Unknown methods get a JSON-RPC `-32601`.
    async fn dispatch_broker_request(&self, session: &Arc<BrokerSession>, id: u64, method: &str) {
        let frame = match method {
            BROKER_METHOD_GET_SIDE_PANEL_SESSION => {
                let started = Instant::now();
                let result = self.side_panel_session(session);
                if let Some(minter) = &self.minter {
                    let outcome = match &result {
                        Ok(_) => "ok",
                        Err(error) => error.audit_outcome,
                    };
                    let summary = format!(
                        "backend:{} transport:{}",
                        session.backend,
                        session.transport.label()
                    );
                    minter.audit(outcome, &summary, started.elapsed().as_millis() as i64);
                }
                match result {
                    Ok(result) => json!({ "jsonrpc": "2.0", "id": id, "result": result }),
                    Err(error) => json!({
                        "jsonrpc": "2.0",
                        "id": id,
                        "error": { "code": error.code, "message": error.message },
                    }),
                }
            }
            _ => json!({
                "jsonrpc": "2.0",
                "id": id,
                "error": {
                    "code": -32601,
                    "message": format!("unknown broker method: {method}"),
                },
            }),
        };
        if session.outbound.send(frame.to_string()).await.is_err() {
            tracing::debug!(
                method,
                "broker session closed before the bridge reply could be sent"
            );
        }
    }

    /// `getSidePanelSession {}` → `{apiBaseUrl, launchCapability, credential}`.
    /// Gated twice: the session must have arrived over the peer-UID-checked
    /// unix socket, and only the Chrome-extension backend may mint.
    fn side_panel_session(&self, session: &BrokerSession) -> Result<Value, BrokerRequestError> {
        if session.transport != BridgeTransport::Unix {
            return Err(BrokerRequestError::denied(
                "side panel session requires the unix socket transport",
            ));
        }
        if session.backend != BACKEND_CHROME_EXTENSION {
            return Err(BrokerRequestError::denied(
                "side panel session requires the chrome-extension backend",
            ));
        }
        let minter = self
            .minter
            .as_ref()
            .ok_or_else(|| BrokerRequestError::failed("side panel sessions are unavailable"))?;
        let credential = minter
            .mint_credential()
            .map_err(BrokerRequestError::failed)?;
        Ok(json!({
            "apiBaseUrl": minter.api_base_url,
            "launchCapability": minter.launch_capability,
            "credential": credential,
        }))
    }
}

async fn browser_bridge_ws(
    State(server): State<Arc<BrowserBridgeServer>>,
    transport: Option<Extension<BridgeTransport>>,
    headers: HeaderMap,
    upgrade: WebSocketUpgrade,
) -> Result<Response, StatusCode> {
    let presented = headers
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));
    let Some(presented) = presented else {
        return Err(StatusCode::UNAUTHORIZED);
    };
    if !token_matches(&server.token, presented) {
        return Err(StatusCode::UNAUTHORIZED);
    }
    // The unix listener serves the same router with this extension layered
    // on; its absence means the connection arrived over TCP.
    let transport = transport.map_or(BridgeTransport::Tcp, |Extension(transport)| transport);
    Ok(upgrade.on_upgrade(move |socket| serve_broker(server, socket, transport)))
}

/// Post-auth handshake: the sidecar sends `hello {}` and the broker's
/// response carries the backend id (`"backend": "chrome-extension" | "iab"`).
/// An absent or unknown value defaults to `chrome-extension` so broker builds
/// predating the field keep working. Returns `None` (drop the connection)
/// when the broker closes, errors, or never answers.
async fn broker_hello(
    server: &BrowserBridgeServer,
    sink: &mut futures_util::stream::SplitSink<WebSocket, Message>,
    stream: &mut futures_util::stream::SplitStream<WebSocket>,
) -> Option<BrokerHelloIdentity> {
    let hello_id = server.next_id.fetch_add(1, Ordering::SeqCst);
    sink.send(Message::Text(jsonrpc::encode_request(
        hello_id,
        "hello",
        json!({}),
    )))
    .await
    .ok()?;
    let timeout = tokio::time::sleep(HELLO_TIMEOUT);
    tokio::pin!(timeout);
    loop {
        tokio::select! {
            _ = &mut timeout => {
                tracing::warn!("browser bridge broker hello timed out; dropping connection");
                return None;
            }
            message = stream.next() => {
                match message {
                    Some(Ok(Message::Text(text))) => {
                        if let Some(identity) = hello_identity(&text, hello_id) {
                            return Some(identity);
                        }
                    }
                    Some(Ok(Message::Binary(bytes))) => {
                        if let Some(identity) = hello_identity(&String::from_utf8_lossy(&bytes), hello_id) {
                            return Some(identity);
                        }
                    }
                    Some(Ok(Message::Close(_))) | None => return None,
                    Some(Ok(_)) => {} // Ping/Pong carry no payload.
                    Some(Err(error)) => {
                        tracing::warn!(%error, "browser bridge broker hello failed");
                        return None;
                    }
                }
            }
        }
    }
}

/// The backend id out of the hello response correlated to `hello_id`;
/// `None` for any other frame.
fn hello_identity(payload: &str, hello_id: u64) -> Option<BrokerHelloIdentity> {
    let Ok(JsonRpcMessage::Response { id, result }) = jsonrpc::decode(payload) else {
        return None;
    };
    if id != hello_id {
        return None;
    }
    let wire: BrokerHelloWire = serde_json::from_value(result.ok()?).ok()?;
    let protocol_min = wire.protocol_min.unwrap_or(wire.protocol_version);
    let protocol_max = wire.protocol_max.unwrap_or(wire.protocol_version);
    if wire.protocol_version < protocol_min
        || wire.protocol_version > protocol_max
        || !protocol_ranges_overlap(PROTOCOL_MIN, PROTOCOL_MAX, protocol_min, protocol_max)
    {
        return None;
    }
    let backend = match wire.backend.as_deref() {
        Some(BACKEND_IAB) => BACKEND_IAB.to_string(),
        // Absent/unknown → the current extension build's implicit identity.
        _ => BACKEND_CHROME_EXTENSION.to_string(),
    };
    Some(BrokerHelloIdentity {
        backend,
        extension_id: wire.extension_id,
        extension_version: wire.extension_version,
        protocol_version: wire.protocol_version,
        protocol_min,
        protocol_max,
    })
}

async fn serve_broker(
    server: Arc<BrowserBridgeServer>,
    socket: WebSocket,
    transport: BridgeTransport,
) {
    let (mut sink, mut stream) = socket.split();
    let Some(hello) = broker_hello(&server, &mut sink, &mut stream).await else {
        let _ = sink.close().await;
        return;
    };
    let backend = hello.backend.clone();
    let (outbound, mut outbound_rx) = mpsc::channel::<String>(OUTBOUND_BUFFER);
    let mut heartbeat = tokio::time::interval(server.heartbeat_interval);
    heartbeat.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    // Discard the immediate first tick so the first probe fires after one
    // full interval.
    heartbeat.tick().await;
    let mut unanswered_heartbeats: u8 = 0;
    let session = Arc::new(BrokerSession {
        backend: backend.clone(),
        hello,
        transport,
        outbound,
        waiters: Mutex::new(HashMap::new()),
        closed: AtomicBool::new(false),
        notify_closed: Notify::new(),
    });

    // One active session per backend: an authenticated newcomer for the same
    // backend replaces the incumbent; other backends are untouched.
    let previous = server
        .backends
        .lock()
        .expect("browser bridge backends")
        .insert(backend.clone(), Arc::clone(&session));
    if let Some(previous) = previous {
        previous.closed.store(true, Ordering::SeqCst);
        previous.notify_closed.notify_waiters();
        previous.fail_waiters("browser bridge broker connection was replaced");
    }

    loop {
        if session.closed.load(Ordering::SeqCst) {
            break;
        }
        tokio::select! {
            frame = outbound_rx.recv() => {
                match frame {
                    Some(frame) => {
                        if let Err(error) = sink.send(Message::Text(frame)).await {
                            tracing::warn!(%error, "browser bridge broker send failed");
                            break;
                        }
                    }
                    None => break,
                }
            }
            message = stream.next() => {
                match message {
                    Some(Ok(Message::Text(text))) => {
                        server.dispatch_inbound(&session, &text).await;
                    }
                    Some(Ok(Message::Binary(bytes))) => {
                        let payload = String::from_utf8_lossy(&bytes);
                        server.dispatch_inbound(&session, &payload).await;
                    }
                    Some(Ok(Message::Close(_))) | None => break,
                    Some(Ok(_)) => {} // Ping/Pong carry no payload.
                    Some(Err(error)) => {
                        tracing::warn!(%error, "browser bridge broker receive failed");
                        break;
                    }
                }
                // Any inbound frame (including pongs) proves liveness.
                unanswered_heartbeats = 0;
            }
            _ = heartbeat.tick() => {
                if unanswered_heartbeats >= BROKER_HEARTBEAT_MISS_LIMIT {
                    tracing::warn!(
                        backend,
                        "browser bridge backend missed {BROKER_HEARTBEAT_MISS_LIMIT} heartbeats; marking offline"
                    );
                    break;
                }
                if sink.send(Message::Ping(Vec::new())).await.is_err() {
                    tracing::warn!(backend, "browser bridge broker heartbeat send failed");
                    break;
                }
                unanswered_heartbeats += 1;
            }
            _ = session.notify_closed.notified() => break,
        }
    }
    let _ = sink.close().await;

    // Clear the backend slot only if it still points at this session.
    let mut backends = server.backends.lock().expect("browser bridge backends");
    if backends
        .get(&backend)
        .is_some_and(|current| Arc::ptr_eq(current, &session))
    {
        backends.remove(&backend);
    }
    drop(backends);
    session.fail_waiters("browser bridge broker disconnected");
}

/// Clone-cheap endpoint handed to [`BrowserToolHost`]; delegates to the
/// server's per-backend broker sessions.
#[derive(Clone)]
pub(crate) struct BrowserBridgeEndpoint {
    server: Arc<BrowserBridgeServer>,
}

#[async_trait]
impl BridgeEndpoint for BrowserBridgeEndpoint {
    async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        self.server.request(method, params).await
    }

    /// Multi-backend override of the trait's single-backend default.
    async fn request_on(&self, backend: &str, method: &str, params: Value) -> CoreResult<Value> {
        self.server.request_on(backend, method, params).await
    }

    fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification> {
        self.server.notifications.subscribe()
    }
}

/// A running bridge: bound listener, registry file, and the tool host the
/// agent engine fans out to. Dropped/aborted on stop.
pub(crate) struct BrowserBridgeRuntime {
    server: Arc<BrowserBridgeServer>,
    tool_host: Arc<BrowserToolHost<BrowserBridgeEndpoint>>,
    config: BrowserBridgeConfig,
    registry_path: PathBuf,
    server_task: JoinHandle<()>,
    #[cfg(unix)]
    unix_listener: Option<UnixBridgeListener>,
}

/// Unix half of the bridge: the accept task plus the socket path so stop can
/// unlink it.
#[cfg(unix)]
struct UnixBridgeListener {
    socket_path: PathBuf,
    task: JoinHandle<()>,
}

impl BrowserBridgeRuntime {
    /// Bind the listener (falling back across `port + 1 ..= port + 10` on
    /// conflicts), generate a fresh token, write the registry, and spawn the
    /// WebSocket server. `registry_path` is a parameter so tests stay out of
    /// the real home directory.
    ///
    /// On unix a peer-UID-checked unix socket next to the registry is served
    /// alongside the TCP listener and advertised as `socketPath`; when the
    /// unix bind fails the bridge stays TCP-only (the broker then never sees
    /// a `socketPath` and keeps using `wsUrl`).
    ///
    /// `minter` answers the broker-initiated `getSidePanelSession` request;
    /// `None` (dev/test bridges) makes that method fail closed.
    pub(crate) fn start_with_registry_path(
        config: &BrowserBridgeConfig,
        registry_path: PathBuf,
        minter: Option<SidePanelSessionMinter>,
    ) -> Result<Self, String> {
        Self::start_with_heartbeat(config, registry_path, minter, BROKER_HEARTBEAT_INTERVAL)
    }

    fn start_with_heartbeat(
        config: &BrowserBridgeConfig,
        registry_path: PathBuf,
        minter: Option<SidePanelSessionMinter>,
        heartbeat_interval: Duration,
    ) -> Result<Self, String> {
        let (listener, port) = bind_bridge_listener(config.port)?;
        let token = super::generate_capability_token();

        #[cfg(unix)]
        let unix_socket = match bridge_socket_path(&registry_path)
            .and_then(|path| bind_unix_bridge_listener(&path).map(|listener| (listener, path)))
        {
            Ok(bound) => Some(bound),
            Err(error) => {
                tracing::warn!(%error, "browser bridge unix socket unavailable; serving TCP only");
                None
            }
        };
        #[cfg(unix)]
        let socket_path = unix_socket
            .as_ref()
            .map(|(_, path)| path.to_string_lossy().into_owned());
        #[cfg(not(unix))]
        let socket_path = None;

        let registry = BridgeRegistry {
            schema_version: REGISTRY_SCHEMA_VERSION,
            ws_url: bridge_ws_url(port),
            token: token.clone(),
            extension_ids: config.extension_ids.clone(),
            sidecar_path: std::env::current_exe().map_err(|error| error.to_string())?,
            updated_at: super::now_iso(),
            socket_path,
        };
        write_registry(&registry_path, &registry)?;

        let server = Arc::new(BrowserBridgeServer::with_heartbeat_interval(
            token,
            port,
            minter,
            heartbeat_interval,
        ));
        let tool_host = Arc::new(BrowserToolHost::new(BrowserBridgeEndpoint {
            server: Arc::clone(&server),
        }));
        let app = Router::new()
            .route("/api/v1/browser-bridge/ws", get(browser_bridge_ws))
            .with_state(Arc::clone(&server));
        let server_task = tokio::spawn({
            let app = app.clone();
            async move {
                if let Err(error) = axum::serve(listener, app).await {
                    tracing::warn!(%error, "browser bridge server stopped");
                }
            }
        });
        #[cfg(unix)]
        let unix_listener = unix_socket.map(|(unix_listener, socket_path)| UnixBridgeListener {
            task: tokio::spawn(serve_unix_bridge(
                unix_listener,
                app.layer(Extension(BridgeTransport::Unix)),
            )),
            socket_path,
        });
        Ok(Self {
            server,
            tool_host,
            config: config.clone(),
            registry_path,
            server_task,
            #[cfg(unix)]
            unix_listener,
        })
    }

    pub(crate) fn start(
        config: &BrowserBridgeConfig,
        minter: Option<SidePanelSessionMinter>,
    ) -> Result<Self, String> {
        Self::start_with_registry_path(config, registry_path()?, minter)
    }

    pub(crate) fn matches(&self, config: &BrowserBridgeConfig) -> bool {
        &self.config == config
    }

    pub(crate) fn port(&self) -> u16 {
        self.server.port()
    }

    pub(crate) fn broker_connected(&self) -> bool {
        self.server.broker_connected()
    }

    pub(crate) fn connected_backends(&self) -> Vec<String> {
        self.server.connected_backends()
    }

    pub(crate) fn extension_identity(&self) -> Option<(String, Option<String>)> {
        self.server
            .chrome_extension_identity()
            .and_then(|identity| {
                identity
                    .extension_id
                    .map(|extension_id| (extension_id, identity.extension_version))
            })
    }

    #[cfg_attr(not(test), allow(dead_code))] // exercised by bridge tests
    pub(crate) fn tool_host(&self) -> Arc<dyn ToolHost> {
        Arc::clone(&self.tool_host) as Arc<dyn ToolHost>
    }

    /// The concrete browser host: the run wrapper gates consent on it and the
    /// runtime drives inherent helpers (`current_url`, `turn_ended`) that the
    /// `ToolHost` trait does not expose.
    pub(crate) fn browser_tool_host(&self) -> Arc<BrowserToolHost<BrowserBridgeEndpoint>> {
        Arc::clone(&self.tool_host)
    }

    /// Dev/diagnostic hook: forward a raw JSON-RPC request to the connected
    /// broker (used by the bridge smoke test; not part of the agent surface).
    pub(crate) fn server(&self) -> Arc<BrowserBridgeServer> {
        Arc::clone(&self.server)
    }

    pub(crate) fn stop(self) {
        self.server_task.abort();
        #[cfg(unix)]
        if let Some(unix_listener) = &self.unix_listener {
            unix_listener.task.abort();
            if let Err(error) = std::fs::remove_file(&unix_listener.socket_path) {
                if error.kind() != std::io::ErrorKind::NotFound {
                    tracing::warn!(%error, "failed to remove browser bridge unix socket");
                }
            }
        }
        if let Err(error) = std::fs::remove_file(&self.registry_path) {
            if error.kind() != std::io::ErrorKind::NotFound {
                tracing::warn!(%error, "failed to remove browser bridge registry");
            }
        }
    }
}

/// Bind `127.0.0.1:port`, falling back across the next
/// [`PORT_FALLBACK_ATTEMPTS`] ports on conflict. `port == 0` requests an
/// OS-assigned ephemeral port (tests).
fn bind_bridge_listener(port: u16) -> Result<(TcpListener, u16), String> {
    if port == 0 {
        return std_listener(0).and_then(|listener| into_tokio(listener));
    }
    let mut last_error = None;
    for candidate in port..=port.saturating_add(PORT_FALLBACK_ATTEMPTS) {
        match std_listener(candidate) {
            Ok(listener) => return into_tokio(listener),
            Err(error) => last_error = Some(error),
        }
    }
    Err(format!(
        "no browser bridge port available in {port}..={}: {}",
        port.saturating_add(PORT_FALLBACK_ATTEMPTS),
        last_error.map_or_else(|| "unknown error".to_string(), |error| error.to_string())
    ))
}

fn std_listener(port: u16) -> Result<std::net::TcpListener, String> {
    std::net::TcpListener::bind(("127.0.0.1", port)).map_err(|error| error.to_string())
}

fn into_tokio(listener: std::net::TcpListener) -> Result<(TcpListener, u16), String> {
    listener
        .set_nonblocking(true)
        .map_err(|error| error.to_string())?;
    let port = listener
        .local_addr()
        .map_err(|error| error.to_string())?
        .port();
    let listener = TcpListener::from_std(listener).map_err(|error| error.to_string())?;
    Ok((listener, port))
}

/// Bind the unix bridge socket. A stale socket file left behind by a crashed
/// sidecar is unlinked first; the fresh socket is forced to 0600 inside its
/// 0700 bridge directory.
#[cfg(unix)]
fn bind_unix_bridge_listener(socket_path: &FsPath) -> Result<tokio::net::UnixListener, String> {
    match std::fs::remove_file(socket_path) {
        Ok(()) => {
            tracing::info!(
                path = %socket_path.display(),
                "removed stale browser bridge unix socket"
            );
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.to_string()),
    }
    let listener =
        tokio::net::UnixListener::bind(socket_path).map_err(|error| error.to_string())?;
    set_private_file_permissions(socket_path).map_err(|error| error.to_string())?;
    Ok(listener)
}

/// Accept loop for the unix listener: every accepted connection must belong
/// to this same user, then is served by the same axum router as the TCP
/// listener. axum 0.7's `serve` is TCP-only, so the connection is handed to
/// hyper's HTTP/1 driver (with WS upgrades) via `hyper-util` adapters.
#[cfg(unix)]
async fn serve_unix_bridge(listener: tokio::net::UnixListener, app: Router) {
    loop {
        let (stream, _) = match listener.accept().await {
            Ok(accepted) => accepted,
            Err(error) => {
                tracing::warn!(%error, "browser bridge unix accept failed");
                continue;
            }
        };
        match unix_peer_uid(&stream) {
            Ok(peer_uid) if peer_uid_matches_self(peer_uid, self_uid()) => {}
            Ok(peer_uid) => {
                tracing::warn!(
                    peer_uid,
                    "browser bridge unix peer rejected: belongs to a different user"
                );
                continue;
            }
            Err(error) => {
                tracing::warn!(%error, "browser bridge unix peer identity check failed");
                continue;
            }
        }
        let service = hyper_util::service::TowerToHyperService::new(app.clone());
        tokio::spawn(async move {
            let connection = hyper::server::conn::http1::Builder::new()
                .serve_connection(hyper_util::rt::TokioIo::new(stream), service)
                .with_upgrades();
            if let Err(error) = connection.await {
                tracing::debug!(%error, "browser bridge unix connection ended");
            }
        });
    }
}

/// Pure decision behind the unix peer check, extracted for testing: the
/// accepted peer must be the same user as this process.
#[cfg(unix)]
fn peer_uid_matches_self(peer_uid: u32, self_uid: u32) -> bool {
    peer_uid == self_uid
}

#[cfg(unix)]
fn self_uid() -> u32 {
    // SAFETY: getuid cannot fail.
    unsafe { libc::getuid() }
}

/// Effective uid of the process on the other end of an accepted unix socket.
#[cfg(all(unix, not(target_os = "linux")))]
fn unix_peer_uid(stream: &tokio::net::UnixStream) -> std::io::Result<u32> {
    use std::os::unix::io::AsRawFd;
    let mut uid: libc::uid_t = 0;
    let mut gid: libc::gid_t = 0;
    // SAFETY: the fd belongs to the live accepted socket and uid/gid are
    // valid out-pointers for the duration of the call.
    if unsafe { libc::getpeereid(stream.as_raw_fd(), &mut uid, &mut gid) } != 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(uid)
}

/// glibc exposes no `getpeereid` through the libc crate; the equivalent
/// kernel check is `SO_PEERCRED`, which tokio wraps.
#[cfg(target_os = "linux")]
fn unix_peer_uid(stream: &tokio::net::UnixStream) -> std::io::Result<u32> {
    stream.peer_cred().map(|credential| credential.uid())
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_adapters_browser::protocol::{METHOD_GET_TABS, NOTIFY_ON_CDP_EVENT};
    use futures_util::{SinkExt, StreamExt};
    use serde_json::json;
    use tokio_tungstenite::tungstenite::client::IntoClientRequest;
    use tokio_tungstenite::tungstenite::Message as ClientMessage;

    struct TestDirectory {
        path: PathBuf,
    }

    impl TestDirectory {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir().join(format!(
                "agistack-browser-registry-{label}-{}",
                uuid::Uuid::new_v4()
            ));
            std::fs::create_dir_all(&path).expect("create registry test directory");
            Self { path }
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.path);
        }
    }

    fn sample_registry() -> BridgeRegistry {
        BridgeRegistry {
            schema_version: REGISTRY_SCHEMA_VERSION,
            ws_url: bridge_ws_url(DEFAULT_BROWSER_BRIDGE_PORT),
            token: "a".repeat(64),
            extension_ids: default_extension_ids(),
            sidecar_path: PathBuf::from("/usr/local/bin/agistack-desktop-sidecar"),
            updated_at: "2026-08-07T00:00:00Z".to_string(),
            socket_path: None,
        }
    }

    #[test]
    fn hello_protocol_contract_accepts_legacy_current_and_next_only() {
        let legacy = hello_identity(
            r#"{"jsonrpc":"2.0","id":7,"result":{"protocolVersion":1}}"#,
            7,
        )
        .expect("legacy N hello remains compatible");
        assert_eq!((legacy.protocol_min, legacy.protocol_max), (1, 1));

        let current = hello_identity(
            r#"{"jsonrpc":"2.0","id":7,"result":{"protocolVersion":1,"protocolMin":1,"protocolMax":2,"extensionId":"extension","extensionVersion":"0.1.0"}}"#,
            7,
        )
        .expect("current N hello is compatible");
        assert_eq!((current.protocol_min, current.protocol_max), (1, 2));

        let next = hello_identity(
            r#"{"jsonrpc":"2.0","id":7,"result":{"protocolVersion":2,"protocolMin":1,"protocolMax":2}}"#,
            7,
        )
        .expect("N+1 hello is compatible during the rollout window");
        assert_eq!(next.protocol_version, 2);

        assert!(hello_identity(
            r#"{"jsonrpc":"2.0","id":7,"result":{"protocolVersion":3,"protocolMin":3,"protocolMax":3}}"#,
            7,
        )
        .is_none());
    }

    #[test]
    fn registry_serializes_with_camel_case_keys() {
        let value = serde_json::to_value(sample_registry()).expect("serialize registry");
        for key in [
            "schemaVersion",
            "wsUrl",
            "token",
            "extensionIds",
            "sidecarPath",
            "updatedAt",
        ] {
            assert!(value.get(key).is_some(), "missing camelCase key {key}");
        }
        assert!(value.get("schema_version").is_none());
        let round_trip: BridgeRegistry =
            serde_json::from_value(value).expect("deserialize registry");
        assert_eq!(round_trip, sample_registry());
    }

    #[test]
    fn registry_rejects_unknown_fields() {
        let mut value = serde_json::to_value(sample_registry()).expect("serialize registry");
        value
            .as_object_mut()
            .expect("registry object")
            .insert("unexpected".to_string(), json!(true));
        assert!(serde_json::from_value::<BridgeRegistry>(value).is_err());
    }

    #[test]
    fn registry_socket_path_round_trips_and_is_omitted_when_absent() {
        let mut registry = sample_registry();
        registry.socket_path = Some("/home/dev/.memstack/browser-bridge/bridge.sock".to_string());
        let value = serde_json::to_value(&registry).expect("serialize registry");
        assert_eq!(
            value.get("socketPath").expect("camelCase socketPath key"),
            "/home/dev/.memstack/browser-bridge/bridge.sock"
        );
        assert!(value.get("socket_path").is_none());
        let round_trip: BridgeRegistry =
            serde_json::from_value(value).expect("deserialize registry");
        assert_eq!(round_trip, registry);

        // Windows shape: the key is absent entirely, not null.
        let value = serde_json::to_value(sample_registry()).expect("serialize registry");
        assert!(value.get("socketPath").is_none());
        let round_trip: BridgeRegistry =
            serde_json::from_value(value).expect("absent socketPath parses");
        assert_eq!(round_trip, sample_registry());
    }

    #[test]
    fn registry_validation_checks_the_socket_path_shape() {
        let mut registry = sample_registry();
        registry.socket_path = Some("/home/dev/.memstack/browser-bridge/bridge.sock".to_string());
        validate_registry(&registry).expect("well-formed socketPath validates");

        // Relative path.
        registry.socket_path = Some(".memstack/browser-bridge/bridge.sock".to_string());
        assert!(validate_registry(&registry).is_err());

        // Wrong parent directory.
        registry.socket_path = Some("/home/dev/.memstack/other/bridge.sock".to_string());
        assert!(validate_registry(&registry).is_err());
        registry.socket_path = Some("/home/dev/browser-bridge/bridge.sock".to_string());
        assert!(validate_registry(&registry).is_err());

        // Wrong filename.
        registry.socket_path = Some("/home/dev/.memstack/browser-bridge/other.sock".to_string());
        assert!(validate_registry(&registry).is_err());
        registry.socket_path = Some("/home/dev/.memstack/browser-bridge".to_string());
        assert!(validate_registry(&registry).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn peer_uid_matches_self_only_for_the_same_uid() {
        assert!(peer_uid_matches_self(501, 501));
        assert!(!peer_uid_matches_self(0, 501));
        assert!(!peer_uid_matches_self(501, 0));
    }

    #[test]
    fn registry_validation_accepts_the_sample() {
        validate_registry(&sample_registry()).expect("sample registry must validate");
    }

    #[test]
    fn registry_validation_rejects_bad_schema_host_and_token() {
        let mut registry = sample_registry();
        registry.schema_version = 2;
        assert!(validate_registry(&registry).is_err());

        let mut registry = sample_registry();
        registry.ws_url = "ws://192.168.1.10:9765/api/v1/browser-bridge/ws".to_string();
        assert!(validate_registry(&registry).is_err());

        let mut registry = sample_registry();
        registry.ws_url = "ws://localhost:9765/api/v1/browser-bridge/ws".to_string();
        validate_registry(&registry).expect("localhost is an accepted loopback host");

        let mut registry = sample_registry();
        registry.token = "z".repeat(64);
        assert!(validate_registry(&registry).is_err());
        registry.token = "a".repeat(63);
        assert!(validate_registry(&registry).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn registry_write_enforces_private_permissions() {
        use std::os::unix::fs::PermissionsExt;
        let root = TestDirectory::new("private");
        let path = root.path.join("registry.json");
        write_registry(&path, &sample_registry()).expect("write registry");
        let file_mode = std::fs::metadata(&path).unwrap().permissions().mode() & 0o777;
        let dir_mode = std::fs::metadata(&root.path).unwrap().permissions().mode() & 0o777;
        assert_eq!(file_mode, 0o600);
        assert_eq!(dir_mode, 0o700);
        let loaded = read_registry(&path).expect("read registry back");
        assert_eq!(loaded, sample_registry());
    }

    #[cfg(unix)]
    #[test]
    fn registry_read_rejects_group_or_world_permissions_without_leaking_the_token() {
        use std::os::unix::fs::PermissionsExt;
        let root = TestDirectory::new("open-mode");
        let path = root.path.join("registry.json");
        let token = sample_registry().token;
        std::fs::write(
            &path,
            serde_json::to_vec(&sample_registry()).expect("serialize registry"),
        )
        .expect("write registry fixture");
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644))
            .expect("set broad permissions");

        let error = read_registry(&path).expect_err("0644 registry must fail closed");
        assert!(error.contains("permissions"));
        assert!(!error.contains(&token));
    }

    #[cfg(unix)]
    #[test]
    fn registry_read_rejects_a_symlink() {
        use std::os::unix::fs::{symlink, PermissionsExt};
        let root = TestDirectory::new("symlink");
        let target = root.path.join("target.json");
        std::fs::write(
            &target,
            serde_json::to_vec(&sample_registry()).expect("serialize registry"),
        )
        .expect("write registry target");
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o600))
            .expect("set target permissions");
        let path = root.path.join("registry.json");
        symlink(&target, &path).expect("create registry symlink");

        let error = read_registry(&path).expect_err("symlink registry must fail closed");
        assert!(error.contains("regular file"));
    }

    #[test]
    fn config_defaults_match_the_contract() {
        let config: BrowserBridgeConfig = serde_json::from_str("{}").expect("empty config parses");
        assert!(!config.enabled);
        assert_eq!(config.port, DEFAULT_BROWSER_BRIDGE_PORT);
        assert_eq!(config.extension_ids, vec![DEFAULT_EXTENSION_ID.to_string()]);
        assert!(!config.full_cdp_access_enabled);
        assert_eq!(BrowserBridgeConfig::default(), config);

        let config: BrowserBridgeConfig =
            serde_json::from_str(r#"{"enabled": true}"#).expect("partial config parses");
        assert!(config.enabled);
        assert_eq!(config.port, DEFAULT_BROWSER_BRIDGE_PORT);
        assert!(!config.full_cdp_access_enabled);

        let config: BrowserBridgeConfig =
            serde_json::from_str(r#"{"full_cdp_access_enabled": true}"#)
                .expect("full cdp flag parses");
        assert!(config.full_cdp_access_enabled);
        assert!(!config.enabled);

        assert!(serde_json::from_str::<BrowserBridgeConfig>(r#"{"bogus": 1}"#).is_err());
    }

    #[test]
    fn token_compare_is_exact() {
        let token = "b".repeat(64);
        assert!(token_matches(&token, &token));
        assert!(!token_matches(&token, &"c".repeat(64)));
        assert!(!token_matches(&token, &"b".repeat(63)));
        assert!(!token_matches(&token, ""));
    }

    #[test]
    fn local_runtime_config_parses_with_and_without_the_bridge_section() {
        use crate::local_runtime::LocalRuntimeConfig;

        let config: LocalRuntimeConfig = serde_json::from_str("{}").expect("empty config parses");
        assert!(!config.browser_bridge.enabled);
        assert_eq!(config.browser_bridge.port, DEFAULT_BROWSER_BRIDGE_PORT);
        assert_eq!(
            config.browser_bridge.extension_ids,
            vec![DEFAULT_EXTENSION_ID.to_string()]
        );
        assert!(!config.browser_bridge.full_cdp_access_enabled);

        let config: LocalRuntimeConfig = serde_json::from_str(
            r#"{"workspace_root": "/tmp/ws", "browser_bridge": {"enabled": true, "port": 9900}}"#,
        )
        .expect("bridge section parses");
        assert!(config.browser_bridge.enabled);
        assert_eq!(config.browser_bridge.port, 9900);
        assert_eq!(
            config.browser_bridge.extension_ids,
            vec![DEFAULT_EXTENSION_ID.to_string()]
        );

        // deny_unknown_fields still applies, top-level and nested.
        assert!(serde_json::from_str::<LocalRuntimeConfig>(r#"{"unknown": 1}"#).is_err());
        assert!(serde_json::from_str::<LocalRuntimeConfig>(
            r#"{"browser_bridge": {"unknown": 1}}"#
        )
        .is_err());
    }

    /// Test runtime on an ephemeral port with the registry in a temp dir. The
    /// registry lives under `<root>/.memstack/browser-bridge/` so the written
    /// `socketPath` satisfies registry validation on unix.
    struct TestBridge {
        runtime: BrowserBridgeRuntime,
        registry: BridgeRegistry,
        root: PathBuf,
    }

    impl TestBridge {
        fn bridge_dir(&self) -> PathBuf {
            self.root.join(".memstack").join("browser-bridge")
        }

        fn socket_path(&self) -> PathBuf {
            self.bridge_dir().join(BRIDGE_SOCKET_FILE_NAME)
        }
    }

    /// Short temp root for bridge fixtures: unix socket paths cap at ~104
    /// bytes, and the macOS per-user temp dir alone nearly fills that.
    fn short_temp_root(tag: &str) -> PathBuf {
        #[cfg(unix)]
        let base = PathBuf::from("/tmp");
        #[cfg(not(unix))]
        let base = std::env::temp_dir();
        let id = uuid::Uuid::new_v4().simple().to_string();
        base.join(format!("ag-bb-{tag}-{}", &id[..8]))
    }

    async fn start_test_bridge() -> TestBridge {
        start_test_bridge_full(None, BROKER_HEARTBEAT_INTERVAL).await
    }

    async fn start_test_bridge_full(
        minter: Option<SidePanelSessionMinter>,
        heartbeat_interval: Duration,
    ) -> TestBridge {
        let root = short_temp_root("srv");
        let bridge_dir = root.join(".memstack").join("browser-bridge");
        std::fs::create_dir_all(&bridge_dir).unwrap();
        let config = BrowserBridgeConfig {
            enabled: true,
            port: 0,
            extension_ids: default_extension_ids(),
            full_cdp_access_enabled: false,
        };
        let runtime = BrowserBridgeRuntime::start_with_heartbeat(
            &config,
            bridge_dir.join("registry.json"),
            minter,
            heartbeat_interval,
        )
        .expect("bridge starts on an ephemeral port");
        let registry =
            read_registry(&bridge_dir.join("registry.json")).expect("registry written on start");
        validate_registry(&registry).expect("written registry validates");
        assert_eq!(registry.ws_url, bridge_ws_url(runtime.server.port()));
        TestBridge {
            runtime,
            registry,
            root,
        }
    }

    async fn connect_broker(
        url: &str,
        token: Option<&str>,
    ) -> Result<
        tokio_tungstenite::WebSocketStream<
            tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
        >,
        String,
    > {
        let mut request = url
            .into_client_request()
            .map_err(|error| error.to_string())?;
        if let Some(token) = token {
            request.headers_mut().insert(
                tokio_tungstenite::tungstenite::http::header::AUTHORIZATION,
                format!("Bearer {token}").parse().unwrap(),
            );
        }
        let (ws, _) = tokio_tungstenite::connect_async(request)
            .await
            .map_err(|error| error.to_string())?;
        Ok(ws)
    }

    /// Connect over the unix socket. HTTP-layer failures (401) surface the
    /// status so auth tests can assert on it.
    #[cfg(unix)]
    async fn connect_broker_unix(
        socket_path: &FsPath,
        url: &str,
        token: Option<&str>,
    ) -> Result<tokio_tungstenite::WebSocketStream<tokio::net::UnixStream>, String> {
        let mut request = url
            .into_client_request()
            .map_err(|error| error.to_string())?;
        if let Some(token) = token {
            request.headers_mut().insert(
                tokio_tungstenite::tungstenite::http::header::AUTHORIZATION,
                format!("Bearer {token}").parse().unwrap(),
            );
        }
        let stream = tokio::net::UnixStream::connect(socket_path)
            .await
            .map_err(|error| error.to_string())?;
        match tokio_tungstenite::client_async(request, stream).await {
            Ok((ws, _)) => Ok(ws),
            Err(tokio_tungstenite::tungstenite::Error::Http(response)) => {
                Err(format!("http status {}", response.status()))
            }
            Err(error) => Err(error.to_string()),
        }
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn unix_socket_serves_the_authenticated_ws_endpoint() {
        use std::os::unix::fs::PermissionsExt;
        let bridge = start_test_bridge().await;

        // The registry advertises the socket and the file is owner-only.
        let socket_path = bridge.socket_path();
        assert_eq!(bridge.registry.socket_path.as_deref(), socket_path.to_str());
        let mode = std::fs::metadata(&socket_path)
            .unwrap()
            .permissions()
            .mode()
            & 0o777;
        assert_eq!(mode, 0o600);

        // A same-UID peer with the bearer token completes the WS handshake
        // (the foreign-UID reject branch is covered by the pure
        // peer_uid_matches_self test: only the local user can exist here).
        let mut ws = connect_broker_unix(
            &socket_path,
            &bridge.registry.ws_url,
            Some(&bridge.registry.token),
        )
        .await
        .expect("unix ws handshake with the valid token");
        broker_answer_hello(&mut ws, Some(BACKEND_CHROME_EXTENSION)).await;
        for _ in 0..50 {
            if bridge.runtime.broker_connected() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        assert!(
            bridge.runtime.broker_connected(),
            "unix broker session must register"
        );

        // Missing and wrong tokens are rejected exactly like the TCP path.
        let missing = connect_broker_unix(&socket_path, &bridge.registry.ws_url, None)
            .await
            .expect_err("missing token is rejected");
        assert!(missing.contains("401"), "unexpected error: {missing}");
        let wrong =
            connect_broker_unix(&socket_path, &bridge.registry.ws_url, Some(&"f".repeat(64)))
                .await
                .expect_err("wrong token is rejected");
        assert!(wrong.contains("401"), "unexpected error: {wrong}");

        bridge.runtime.stop();
        assert!(!socket_path.exists(), "stop removes the socket file");
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn unix_listener_replaces_a_stale_socket_file() {
        let root = short_temp_root("stale");
        let bridge_dir = root.join(".memstack").join("browser-bridge");
        std::fs::create_dir_all(&bridge_dir).unwrap();
        let socket_path = bridge_dir.join(BRIDGE_SOCKET_FILE_NAME);
        std::fs::write(&socket_path, b"stale socket from a crashed sidecar").unwrap();

        let config = BrowserBridgeConfig {
            enabled: true,
            port: 0,
            extension_ids: default_extension_ids(),
            full_cdp_access_enabled: false,
        };
        let runtime = BrowserBridgeRuntime::start_with_registry_path(
            &config,
            bridge_dir.join("registry.json"),
            None,
        )
        .expect("bridge starts despite the stale socket file");
        let registry = read_registry(&bridge_dir.join("registry.json")).unwrap();
        assert_eq!(registry.socket_path.as_deref(), socket_path.to_str());
        connect_broker_unix(&socket_path, &registry.ws_url, Some(&registry.token))
            .await
            .expect("fresh unix socket serves the ws endpoint");
        runtime.stop();
        std::fs::remove_dir_all(&root).unwrap();
    }

    /// Read one text frame from the broker side and decode it.
    async fn broker_next_request<S>(
        ws: &mut tokio_tungstenite::WebSocketStream<S>,
    ) -> (u64, String, Value)
    where
        S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
    {
        let message = tokio::time::timeout(std::time::Duration::from_secs(5), ws.next())
            .await
            .expect("broker receive timed out")
            .expect("broker stream ended")
            .expect("broker frame");
        let ClientMessage::Text(text) = message else {
            panic!("expected a text frame, got {message:?}");
        };
        match jsonrpc::decode(&text).expect("valid bridge request") {
            JsonRpcMessage::Request { id, method, params } => (id, method, params),
            other => panic!("expected a request frame, got {other:?}"),
        }
    }

    async fn broker_respond<S>(
        ws: &mut tokio_tungstenite::WebSocketStream<S>,
        id: u64,
        result: Value,
    ) where
        S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
    {
        ws.send(ClientMessage::Text(
            json!({ "jsonrpc": "2.0", "id": id, "result": result })
                .to_string()
                .into(),
        ))
        .await
        .expect("broker respond");
    }

    /// Read one response frame addressed to a broker-initiated request.
    async fn broker_next_response<S>(
        ws: &mut tokio_tungstenite::WebSocketStream<S>,
    ) -> (u64, Result<Value, (i64, String)>)
    where
        S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
    {
        let message = tokio::time::timeout(std::time::Duration::from_secs(5), ws.next())
            .await
            .expect("broker receive timed out")
            .expect("broker stream ended")
            .expect("broker frame");
        let ClientMessage::Text(text) = message else {
            panic!("expected a text frame, got {message:?}");
        };
        match jsonrpc::decode(&text).expect("valid bridge response") {
            JsonRpcMessage::Response { id, result } => {
                (id, result.map_err(|error| (error.code, error.message)))
            }
            other => panic!("expected a response frame, got {other:?}"),
        }
    }

    /// Send one broker-initiated request frame.
    async fn broker_send_request<S>(
        ws: &mut tokio_tungstenite::WebSocketStream<S>,
        id: u64,
        method: &str,
    ) where
        S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
    {
        ws.send(ClientMessage::Text(
            json!({ "jsonrpc": "2.0", "id": id, "method": method, "params": {} })
                .to_string()
                .into(),
        ))
        .await
        .expect("broker request");
    }

    /// Answer the server's post-auth `hello`. `Some(backend)` tags the
    /// session with that backend id; `None` answers without a `backend`
    /// field (the pre-M4 extension shape, defaulting to chrome-extension).
    async fn broker_answer_hello<S>(
        ws: &mut tokio_tungstenite::WebSocketStream<S>,
        backend: Option<&str>,
    ) where
        S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
    {
        let (id, method, _) = broker_next_request(ws).await;
        assert_eq!(method, "hello");
        let result = match backend {
            Some(backend) => json!({"ready": true, "backend": backend}),
            None => json!({"ready": true}),
        };
        broker_respond(ws, id, result).await;
    }

    /// Poll until the server reports exactly these connected backends.
    async fn wait_for_backends(runtime: &BrowserBridgeRuntime, expected: &[&str]) {
        for _ in 0..250 {
            if runtime.connected_backends() == expected {
                return;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        panic!(
            "backends never settled to {expected:?}; saw {:?}",
            runtime.connected_backends()
        );
    }

    #[tokio::test]
    async fn rejects_missing_and_wrong_tokens() {
        let bridge = start_test_bridge().await;
        assert!(connect_broker(&bridge.registry.ws_url, None).await.is_err());
        assert!(
            connect_broker(&bridge.registry.ws_url, Some(&"f".repeat(64)))
                .await
                .is_err()
        );
        assert!(
            connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
                .await
                .is_ok()
        );
        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[tokio::test]
    async fn a_new_broker_replaces_the_incumbent() {
        let bridge = start_test_bridge().await;
        let mut first = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("first broker connects");
        // No `backend` field: the pre-M4 extension shape defaults to
        // chrome-extension.
        broker_answer_hello(&mut first, None).await;
        // Wait until the server registered the first session.
        for _ in 0..50 {
            if bridge.runtime.broker_connected() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        assert!(bridge.runtime.broker_connected());

        let mut second = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("replacement broker connects");
        broker_answer_hello(&mut second, Some(BACKEND_CHROME_EXTENSION)).await;

        // The incumbent's socket must close promptly.
        let closed = tokio::time::timeout(std::time::Duration::from_secs(5), async {
            loop {
                match first.next().await {
                    Some(Ok(ClientMessage::Close(_))) | None => break true,
                    Some(Ok(_)) => {}
                    Some(Err(_)) => break true,
                }
            }
        })
        .await
        .expect("incumbent socket did not close");
        assert!(closed);
        assert!(bridge.runtime.broker_connected());
        assert_eq!(
            bridge.runtime.connected_backends(),
            vec![BACKEND_CHROME_EXTENSION.to_string()]
        );
        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[tokio::test]
    async fn list_tabs_round_trips_through_the_endpoint_and_events_flow() {
        let bridge = start_test_bridge().await;
        let broker = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("broker connects");

        // Scripted broker: answer the server-driven hello + getTabs, then
        // hand the socket back.
        let script = tokio::spawn(async move {
            let mut broker = broker;
            broker_answer_hello(&mut broker, Some(BACKEND_CHROME_EXTENSION)).await;

            let (id, method, _) = broker_next_request(&mut broker).await;
            assert_eq!(method, METHOD_GET_TABS);
            broker_respond(
                &mut broker,
                id,
                json!({"tabs": [{"tabId": 7, "windowId": 1, "title": "T", "url": "https://x", "active": true}]}),
            )
            .await;
            broker
        });

        // Wait until the server registered the broker session.
        for _ in 0..50 {
            if bridge.runtime.broker_connected() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        // The in-process endpoint is what BrowserToolHost drives. Without an
        // explicit `backend` input the host fans list_tabs out to every
        // backend (only chrome-extension is connected here), so pin chrome.
        let tool_host = bridge.runtime.tool_host();
        assert!(tool_host
            .list_tools()
            .contains(&agistack_adapters_browser::host::TOOL_LIST_TABS.to_string()));
        let output = tool_host
            .call("browser_list_tabs", r#"{"backend": "chrome"}"#)
            .await
            .expect("browser_list_tabs round trip");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["tabs"][0]["tabId"], 7);

        let mut broker = script.await.expect("broker script completed");

        // One extension notification must reach the server's broadcast.
        let mut notifications = bridge.runtime.server.notifications.subscribe();
        broker
            .send(ClientMessage::Text(
                json!({
                    "jsonrpc": "2.0",
                    "method": NOTIFY_ON_CDP_EVENT,
                    "params": {"tabId": 7, "method": "Runtime.consoleAPICalled", "params": {"type": "log", "args": [{"value": "hi"}], "timestamp": 1.0}}
                })
                .to_string()
                .into(),
            ))
            .await
            .expect("send notification");
        let notification =
            tokio::time::timeout(std::time::Duration::from_secs(5), notifications.recv())
                .await
                .expect("notification timed out")
                .expect("notification channel");
        assert_eq!(notification.method, NOTIFY_ON_CDP_EVENT);
        assert_eq!(notification.params["tabId"], 7);

        // executeCdp echo through the in-process endpoint.
        let echo = tokio::spawn(async move {
            let (id, method, params) = broker_next_request(&mut broker).await;
            assert_eq!(method, "executeCdp");
            let echoed = params.clone();
            broker_respond(&mut broker, id, json!({"result": {"echoed": echoed}})).await;
        });
        let response = bridge
            .runtime
            .server
            .request(
                "executeCdp",
                json!({"tabId": 7, "method": "Runtime.evaluate", "params": {}}),
            )
            .await
            .expect("executeCdp echo");
        assert_eq!(response["result"]["echoed"]["method"], "Runtime.evaluate");
        echo.await.unwrap();

        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[tokio::test]
    async fn requests_fail_closed_without_a_broker() {
        let bridge = start_test_bridge().await;
        let error = bridge
            .runtime
            .server
            .request(METHOD_GET_TABS, json!({}))
            .await
            .expect_err("no broker connected");
        assert!(error.to_string().contains("not connected"));
        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[tokio::test]
    async fn broker_disconnect_marks_the_bridge_offline() {
        let bridge = start_test_bridge().await;
        let mut broker = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("broker connects");
        broker_answer_hello(&mut broker, Some(BACKEND_CHROME_EXTENSION)).await;
        for _ in 0..50 {
            if bridge.runtime.broker_connected() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        assert!(bridge.runtime.broker_connected());

        // Dropping the socket closes the WS; the server must promptly clear
        // the backend slot so `connected_browser_tool_host()` returns None
        // and the browser tools vanish from the engine surface.
        drop(broker);
        let mut offline = false;
        for _ in 0..100 {
            if !bridge.runtime.broker_connected() {
                offline = true;
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        assert!(offline, "broker disconnect must mark the bridge offline");
        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[tokio::test]
    async fn two_backends_coexist_and_request_on_routes_to_the_right_session() {
        let bridge = start_test_bridge().await;

        let mut chrome = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("chrome broker connects");
        broker_answer_hello(&mut chrome, Some(BACKEND_CHROME_EXTENSION)).await;
        let mut iab = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("iab broker connects");
        broker_answer_hello(&mut iab, Some(BACKEND_IAB)).await;

        wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION, BACKEND_IAB]).await;
        assert!(bridge.runtime.broker_connected());

        // request_on("iab") reaches the iab session only.
        let iab_script = tokio::spawn(async move {
            let (id, method, _) = broker_next_request(&mut iab).await;
            assert_eq!(method, "iabMethod");
            broker_respond(&mut iab, id, json!({"via": "iab"})).await;
        });
        let result = bridge
            .runtime
            .server
            .request_on(BACKEND_IAB, "iabMethod", json!({}))
            .await
            .expect("iab round trip");
        assert_eq!(result["via"], "iab");
        iab_script.await.expect("iab script");

        // request() keeps addressing the chrome-extension backend.
        let chrome_script = tokio::spawn(async move {
            let (id, method, _) = broker_next_request(&mut chrome).await;
            assert_eq!(method, "chromeMethod");
            broker_respond(&mut chrome, id, json!({"via": "chrome"})).await;
        });
        let result = bridge
            .runtime
            .server
            .request("chromeMethod", json!({}))
            .await
            .expect("chrome round trip");
        assert_eq!(result["via"], "chrome");
        chrome_script.await.expect("chrome script");

        // Unknown backends fail closed.
        let error = bridge
            .runtime
            .server
            .request_on("unknown", "noop", json!({}))
            .await
            .expect_err("unknown backend must fail");
        assert!(error.to_string().contains("not connected"));

        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[tokio::test]
    async fn same_backend_replacement_leaves_other_backends_connected() {
        let bridge = start_test_bridge().await;
        let mut chrome = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("chrome broker connects");
        broker_answer_hello(&mut chrome, Some(BACKEND_CHROME_EXTENSION)).await;
        let mut iab = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("iab broker connects");
        broker_answer_hello(&mut iab, Some(BACKEND_IAB)).await;
        wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION, BACKEND_IAB]).await;

        let mut replacement = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("replacement chrome broker connects");
        broker_answer_hello(&mut replacement, Some(BACKEND_CHROME_EXTENSION)).await;

        // The replaced chrome session closes; the iab session is untouched.
        let closed = tokio::time::timeout(std::time::Duration::from_secs(5), async {
            loop {
                match chrome.next().await {
                    Some(Ok(ClientMessage::Close(_))) | None => break true,
                    Some(Ok(_)) => {}
                    Some(Err(_)) => break true,
                }
            }
        })
        .await
        .expect("incumbent chrome socket did not close");
        assert!(closed);
        wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION, BACKEND_IAB]).await;

        let iab_script = tokio::spawn(async move {
            let (id, method, _) = broker_next_request(&mut iab).await;
            assert_eq!(method, "ping");
            broker_respond(&mut iab, id, json!({"still": "here"})).await;
        });
        let result = bridge
            .runtime
            .server
            .request_on(BACKEND_IAB, "ping", json!({}))
            .await
            .expect("iab still routable after chrome replacement");
        assert_eq!(result["still"], "here");
        iab_script.await.expect("iab script");

        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[tokio::test]
    async fn heartbeat_offline_detection_is_per_backend() {
        let bridge = start_test_bridge_full(None, std::time::Duration::from_millis(50)).await;
        let mut chrome = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("chrome broker connects");
        broker_answer_hello(&mut chrome, Some(BACKEND_CHROME_EXTENSION)).await;
        let mut iab = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("iab broker connects");
        broker_answer_hello(&mut iab, Some(BACKEND_IAB)).await;
        wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION, BACKEND_IAB]).await;

        // Keep chrome alive by polling (tungstenite auto-answers the server
        // pings); starve iab by holding the socket without ever polling it,
        // so no pong ever leaves the client.
        let keepalive = tokio::spawn(async move { while chrome.next().await.is_some() {} });
        let _starved = iab;

        // iab misses the probes and drops out; chrome stays online.
        wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION]).await;
        assert!(bridge.runtime.broker_connected());

        keepalive.abort();
        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[tokio::test]
    async fn unknown_broker_methods_get_method_not_found() {
        let bridge = start_test_bridge().await;
        let mut broker = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("broker connects");
        broker_answer_hello(&mut broker, Some(BACKEND_CHROME_EXTENSION)).await;
        wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION]).await;

        broker_send_request(&mut broker, 9, "bogusMethod").await;
        let (id, result) = broker_next_response(&mut broker).await;
        assert_eq!(id, 9);
        let (code, message) = result.expect_err("unknown method must error");
        assert_eq!(code, -32601);
        assert!(message.contains("bogusMethod"));

        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    /// A local runtime state on an in-memory session store plus the minter
    /// the bridge would be started with. The returned root keeps the state's
    /// workspace directory alive.
    fn side_panel_fixture() -> (
        Arc<super::super::LocalRuntimeState>,
        SidePanelSessionMinter,
        PathBuf,
    ) {
        let root = short_temp_root("state");
        std::fs::create_dir_all(&root).unwrap();
        let tool_host =
            agistack_adapters_local_tools::LocalToolHost::new(&root).expect("tool host");
        let checkpoints: Arc<dyn agistack_core::ports::CheckpointStore> = Arc::new(
            agistack_adapters_device::SqliteCheckpointStore::in_memory().expect("checkpoints"),
        );
        let session_store = DesktopSessionStore::in_memory().expect("session store");
        let state = Arc::new(
            super::super::LocalRuntimeState::new(
                root.clone(),
                tool_host,
                checkpoints,
                super::super::generate_capability_token(),
                session_store,
            )
            .expect("local runtime state"),
        );
        let minter = SidePanelSessionMinter::new(
            "http://127.0.0.1:4789".to_string(),
            state.api_token.clone(),
            state.session_store.clone(),
        );
        (state, minter, root)
    }

    fn side_panel_audit_outcome(state: &super::super::LocalRuntimeState) -> String {
        state
            .session_store
            .list_browser_action_audit(10, None)
            .expect("audit rows")
            .into_iter()
            .find(|row| row.tool_name == BROKER_METHOD_GET_SIDE_PANEL_SESSION)
            .expect("getSidePanelSession audit row")
            .outcome
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn side_panel_session_over_unix_mints_a_working_credential() {
        use tower::ServiceExt;

        let (state, minter, state_root) = side_panel_fixture();
        let bridge = start_test_bridge_full(Some(minter), BROKER_HEARTBEAT_INTERVAL).await;
        let mut ws = connect_broker_unix(
            &bridge.socket_path(),
            &bridge.registry.ws_url,
            Some(&bridge.registry.token),
        )
        .await
        .expect("unix ws connects");
        broker_answer_hello(&mut ws, Some(BACKEND_CHROME_EXTENSION)).await;
        wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION]).await;

        broker_send_request(&mut ws, 42, BROKER_METHOD_GET_SIDE_PANEL_SESSION).await;
        let (id, result) = broker_next_response(&mut ws).await;
        assert_eq!(id, 42);
        let result = result.expect("side panel session minted");
        assert_eq!(result["apiBaseUrl"], "http://127.0.0.1:4789");
        assert_eq!(result["launchCapability"], json!(state.api_token));
        let credential = result["credential"]
            .as_str()
            .expect("credential string")
            .to_string();
        assert!(credential.starts_with("local-session-"));

        assert_eq!(side_panel_audit_outcome(&state), "ok");

        // The minted credential + launch capability authenticate against a
        // protected route exactly as the side panel will present them.
        let app = super::super::local_router(Arc::clone(&state));
        let response = app
            .oneshot(
                axum::http::Request::builder()
                    .uri("/api/v1/auth/me")
                    .header("x-agistack-launch", &state.api_token)
                    .header("authorization", format!("Bearer {credential}"))
                    .body(axum::body::Body::empty())
                    .expect("auth_me request"),
            )
            .await
            .expect("auth_me response");
        assert_eq!(response.status(), StatusCode::OK);

        drop(ws);
        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
        std::fs::remove_dir_all(&state_root).unwrap();
    }

    #[tokio::test]
    async fn side_panel_session_over_tcp_is_refused() {
        let (state, minter, state_root) = side_panel_fixture();
        let bridge = start_test_bridge_full(Some(minter), BROKER_HEARTBEAT_INTERVAL).await;
        let mut ws = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("tcp broker connects");
        broker_answer_hello(&mut ws, Some(BACKEND_CHROME_EXTENSION)).await;
        wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION]).await;

        broker_send_request(&mut ws, 7, BROKER_METHOD_GET_SIDE_PANEL_SESSION).await;
        let (id, result) = broker_next_response(&mut ws).await;
        assert_eq!(id, 7);
        let (code, message) = result.expect_err("tcp transport must be refused");
        assert_eq!(code, 1);
        assert_eq!(
            message,
            "side panel session requires the unix socket transport"
        );

        assert_eq!(side_panel_audit_outcome(&state), "denied");

        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
        std::fs::remove_dir_all(&state_root).unwrap();
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn side_panel_session_for_the_iab_backend_is_refused() {
        let (state, minter, state_root) = side_panel_fixture();
        let bridge = start_test_bridge_full(Some(minter), BROKER_HEARTBEAT_INTERVAL).await;
        let mut ws = connect_broker_unix(
            &bridge.socket_path(),
            &bridge.registry.ws_url,
            Some(&bridge.registry.token),
        )
        .await
        .expect("unix ws connects");
        broker_answer_hello(&mut ws, Some(BACKEND_IAB)).await;
        wait_for_backends(&bridge.runtime, &[BACKEND_IAB]).await;

        broker_send_request(&mut ws, 8, BROKER_METHOD_GET_SIDE_PANEL_SESSION).await;
        let (id, result) = broker_next_response(&mut ws).await;
        assert_eq!(id, 8);
        let (code, message) = result.expect_err("iab backend must be refused");
        assert_eq!(code, 1);
        assert!(message.contains(BACKEND_CHROME_EXTENSION));

        assert_eq!(side_panel_audit_outcome(&state), "denied");

        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
        std::fs::remove_dir_all(&state_root).unwrap();
    }
}
