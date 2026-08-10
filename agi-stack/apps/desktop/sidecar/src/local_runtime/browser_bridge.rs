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

use std::{
    collections::HashMap,
    path::{Path as FsPath, PathBuf},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
};

use agistack_adapters_browser::{
    bridge_ws_url,
    host::{BridgeEndpoint, BrowserToolHost},
    jsonrpc::{self, JsonRpcMessage},
    protocol::BridgeNotification,
};
use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use async_trait::async_trait;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    http::{header::AUTHORIZATION, HeaderMap, StatusCode},
    response::Response,
    routing::get,
    Router,
};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::{
    net::TcpListener,
    sync::{broadcast, mpsc, oneshot, Notify},
    task::JoinHandle,
};
use url::Url;

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
/// Server-side liveness probe for the broker socket (§6 M2 心跳熔断): a WS
/// ping every interval; the broker is declared offline after this many
/// consecutive intervals without any inbound frame.
const BROKER_HEARTBEAT_INTERVAL: std::time::Duration = std::time::Duration::from_secs(30);
const BROKER_HEARTBEAT_MISS_LIMIT: u8 = 2;

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
}

impl Default for BrowserBridgeConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            port: DEFAULT_BROWSER_BRIDGE_PORT,
            extension_ids: default_extension_ids(),
        }
    }
}

/// `browser_bridge` projection of [`LocalRuntimeStatus`](super::LocalRuntimeStatus).
#[derive(Clone, Debug, Serialize)]
pub struct BrowserBridgeStatus {
    pub enabled: bool,
    pub port: u16,
    pub broker_connected: bool,
    pub extension_ids: Vec<String>,
}

/// Registry file written by the sidecar and consumed by the broker. Serialized
/// with camelCase keys (`schemaVersion`, `wsUrl`, ...) — that casing is part
/// of the frozen wire contract.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeRegistry {
    pub schema_version: u32,
    pub ws_url: String,
    pub token: String,
    pub extension_ids: Vec<String>,
    pub sidecar_path: PathBuf,
    pub updated_at: String,
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
    let serialized = std::fs::read_to_string(path)
        .map_err(|error| format!("browser bridge registry is unreadable: {error}"))?;
    serde_json::from_str(&serialized)
        .map_err(|error| format!("browser bridge registry is invalid: {error}"))
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
    Ok(())
}

/// Log a warning when the registry file is readable beyond the owner. The
/// broker continues — the file was placed by whatever installed the host —
/// but the exposure is surfaced.
pub(crate) fn warn_if_registry_permissions_open(path: &FsPath) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(metadata) = std::fs::metadata(path) {
            let mode = metadata.permissions().mode() & 0o777;
            if mode & 0o077 != 0 {
                tracing::warn!(
                    path = %path.display(),
                    mode = %format!("{mode:o}"),
                    "browser bridge registry permissions are broader than 0600"
                );
            }
        }
    }
    #[cfg(not(unix))]
    let _ = path;
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

/// One live broker connection. The server holds at most one of these; a new
/// authenticated connection replaces the previous one.
struct BrokerSession {
    outbound: mpsc::Sender<String>,
    waiters: Mutex<HashMap<u64, oneshot::Sender<Result<Value, String>>>>,
    closed: AtomicBool,
    notify_closed: Notify,
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

/// Shared state behind the bridge WebSocket route and the agent-facing
/// endpoint. One instance per bridge start; the token is fixed for its
/// lifetime (a start regenerates token *and* server).
pub(crate) struct BrowserBridgeServer {
    token: String,
    port: u16,
    active: Mutex<Option<Arc<BrokerSession>>>,
    notifications: broadcast::Sender<BridgeNotification>,
    next_id: AtomicU64,
}

impl BrowserBridgeServer {
    fn new(token: String, port: u16) -> Self {
        let (notifications, _) = broadcast::channel(NOTIFICATION_BUFFER);
        Self {
            token,
            port,
            active: Mutex::new(None),
            notifications,
            next_id: AtomicU64::new(1),
        }
    }

    pub(crate) fn port(&self) -> u16 {
        self.port
    }

    pub(crate) fn broker_connected(&self) -> bool {
        self.active.lock().expect("browser bridge broker").is_some()
    }

    /// Issue one bridge request to the connected broker, awaiting the
    /// correlated response. Fails immediately when no broker is connected.
    pub(crate) async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        let session = self
            .active
            .lock()
            .expect("browser bridge broker")
            .clone()
            .ok_or_else(|| CoreError::Tool("browser bridge broker is not connected".to_string()))?;
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

    fn dispatch_inbound(&self, session: &BrokerSession, payload: &str) {
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
            Ok(JsonRpcMessage::Request { method, .. }) => {
                tracing::debug!(method, "ignoring broker-initiated bridge request");
            }
            Err(error) => {
                tracing::warn!(%error, "dropping malformed broker frame");
            }
        }
    }
}

async fn browser_bridge_ws(
    State(server): State<Arc<BrowserBridgeServer>>,
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
    Ok(upgrade.on_upgrade(move |socket| serve_broker(server, socket)))
}

async fn serve_broker(server: Arc<BrowserBridgeServer>, socket: WebSocket) {
    let (mut sink, mut stream) = socket.split();
    let (outbound, mut outbound_rx) = mpsc::channel::<String>(OUTBOUND_BUFFER);
    let mut heartbeat = tokio::time::interval(BROKER_HEARTBEAT_INTERVAL);
    heartbeat.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    // Discard the immediate first tick so the first probe fires after one
    // full interval.
    heartbeat.tick().await;
    let mut unanswered_heartbeats: u8 = 0;
    let session = Arc::new(BrokerSession {
        outbound,
        waiters: Mutex::new(HashMap::new()),
        closed: AtomicBool::new(false),
        notify_closed: Notify::new(),
    });

    // Single active broker: an authenticated newcomer replaces the incumbent.
    let previous = server
        .active
        .lock()
        .expect("browser bridge broker")
        .replace(Arc::clone(&session));
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
                    Some(Ok(Message::Text(text))) => server.dispatch_inbound(&session, &text),
                    Some(Ok(Message::Binary(bytes))) => {
                        server.dispatch_inbound(&session, &String::from_utf8_lossy(&bytes));
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
                        "browser bridge broker missed {BROKER_HEARTBEAT_MISS_LIMIT} heartbeats; marking offline"
                    );
                    break;
                }
                if sink.send(Message::Ping(Vec::new())).await.is_err() {
                    tracing::warn!("browser bridge broker heartbeat send failed");
                    break;
                }
                unanswered_heartbeats += 1;
            }
            _ = session.notify_closed.notified() => break,
        }
    }
    let _ = sink.close().await;

    // Clear the active slot only if it still points at this session.
    let mut active = server.active.lock().expect("browser bridge broker");
    if active
        .as_ref()
        .is_some_and(|current| Arc::ptr_eq(current, &session))
    {
        active.take();
    }
    drop(active);
    session.fail_waiters("browser bridge broker disconnected");
}

/// Clone-cheap endpoint handed to [`BrowserToolHost`]; delegates to the
/// server's active broker session.
#[derive(Clone)]
pub(crate) struct BrowserBridgeEndpoint {
    server: Arc<BrowserBridgeServer>,
}

#[async_trait]
impl BridgeEndpoint for BrowserBridgeEndpoint {
    async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        self.server.request(method, params).await
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
}

impl BrowserBridgeRuntime {
    /// Bind the listener (falling back across `port + 1 ..= port + 10` on
    /// conflicts), generate a fresh token, write the registry, and spawn the
    /// WebSocket server. `registry_path` is a parameter so tests stay out of
    /// the real home directory.
    pub(crate) fn start_with_registry_path(
        config: &BrowserBridgeConfig,
        registry_path: PathBuf,
    ) -> Result<Self, String> {
        let (listener, port) = bind_bridge_listener(config.port)?;
        let token = super::generate_capability_token();
        let registry = BridgeRegistry {
            schema_version: REGISTRY_SCHEMA_VERSION,
            ws_url: bridge_ws_url(port),
            token: token.clone(),
            extension_ids: config.extension_ids.clone(),
            sidecar_path: std::env::current_exe().map_err(|error| error.to_string())?,
            updated_at: super::now_iso(),
        };
        write_registry(&registry_path, &registry)?;

        let server = Arc::new(BrowserBridgeServer::new(token, port));
        let tool_host = Arc::new(BrowserToolHost::new(BrowserBridgeEndpoint {
            server: Arc::clone(&server),
        }));
        let app = Router::new()
            .route("/api/v1/browser-bridge/ws", get(browser_bridge_ws))
            .with_state(Arc::clone(&server));
        let server_task = tokio::spawn(async move {
            if let Err(error) = axum::serve(listener, app).await {
                tracing::warn!(%error, "browser bridge server stopped");
            }
        });
        Ok(Self {
            server,
            tool_host,
            config: config.clone(),
            registry_path,
            server_task,
        })
    }

    pub(crate) fn start(config: &BrowserBridgeConfig) -> Result<Self, String> {
        Self::start_with_registry_path(config, registry_path()?)
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

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_adapters_browser::protocol::{METHOD_GET_TABS, NOTIFY_ON_CDP_EVENT};
    use futures_util::{SinkExt, StreamExt};
    use serde_json::json;
    use tokio_tungstenite::tungstenite::client::IntoClientRequest;
    use tokio_tungstenite::tungstenite::Message as ClientMessage;

    fn sample_registry() -> BridgeRegistry {
        BridgeRegistry {
            schema_version: REGISTRY_SCHEMA_VERSION,
            ws_url: bridge_ws_url(DEFAULT_BROWSER_BRIDGE_PORT),
            token: "a".repeat(64),
            extension_ids: default_extension_ids(),
            sidecar_path: PathBuf::from("/usr/local/bin/agistack-desktop-sidecar"),
            updated_at: "2026-08-07T00:00:00Z".to_string(),
        }
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
        let root = std::env::temp_dir().join(format!(
            "agistack-bridge-registry-test-{}",
            uuid::Uuid::new_v4()
        ));
        let path = root.join("registry.json");
        write_registry(&path, &sample_registry()).expect("write registry");
        let file_mode = std::fs::metadata(&path).unwrap().permissions().mode() & 0o777;
        let dir_mode = std::fs::metadata(&root).unwrap().permissions().mode() & 0o777;
        assert_eq!(file_mode, 0o600);
        assert_eq!(dir_mode, 0o700);
        let loaded = read_registry(&path).expect("read registry back");
        assert_eq!(loaded, sample_registry());
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn config_defaults_match_the_contract() {
        let config: BrowserBridgeConfig = serde_json::from_str("{}").expect("empty config parses");
        assert!(!config.enabled);
        assert_eq!(config.port, DEFAULT_BROWSER_BRIDGE_PORT);
        assert_eq!(config.extension_ids, vec![DEFAULT_EXTENSION_ID.to_string()]);
        assert_eq!(BrowserBridgeConfig::default(), config);

        let config: BrowserBridgeConfig =
            serde_json::from_str(r#"{"enabled": true}"#).expect("partial config parses");
        assert!(config.enabled);
        assert_eq!(config.port, DEFAULT_BROWSER_BRIDGE_PORT);

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

    /// Test runtime on an ephemeral port with the registry in a temp dir.
    struct TestBridge {
        runtime: BrowserBridgeRuntime,
        registry: BridgeRegistry,
        root: PathBuf,
    }

    async fn start_test_bridge() -> TestBridge {
        let root = std::env::temp_dir().join(format!(
            "agistack-bridge-server-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let config = BrowserBridgeConfig {
            enabled: true,
            port: 0,
            extension_ids: default_extension_ids(),
        };
        let runtime =
            BrowserBridgeRuntime::start_with_registry_path(&config, root.join("registry.json"))
                .expect("bridge starts on an ephemeral port");
        let registry =
            read_registry(&root.join("registry.json")).expect("registry written on start");
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

    /// Read one text frame from the broker side and decode it.
    async fn broker_next_request(
        ws: &mut tokio_tungstenite::WebSocketStream<
            tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
        >,
    ) -> (u64, String, Value) {
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

    async fn broker_respond(
        ws: &mut tokio_tungstenite::WebSocketStream<
            tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
        >,
        id: u64,
        result: Value,
    ) {
        ws.send(ClientMessage::Text(
            json!({ "jsonrpc": "2.0", "id": id, "result": result })
                .to_string()
                .into(),
        ))
        .await
        .expect("broker respond");
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
        // Wait until the server registered the first session.
        for _ in 0..50 {
            if bridge.runtime.broker_connected() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        assert!(bridge.runtime.broker_connected());

        let _second = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("replacement broker connects");

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
        bridge.runtime.stop();
        std::fs::remove_dir_all(&bridge.root).unwrap();
    }

    #[tokio::test]
    async fn list_tabs_round_trips_through_the_endpoint_and_events_flow() {
        let bridge = start_test_bridge().await;
        let broker = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("broker connects");

        // Scripted broker: answer hello + getTabs, then hand the socket back.
        let script = tokio::spawn(async move {
            let mut broker = broker;
            let (id, method, _) = broker_next_request(&mut broker).await;
            assert_eq!(method, "hello");
            broker_respond(&mut broker, id, json!({"ready": true})).await;

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
        assert!(bridge.runtime.broker_connected());

        // The in-process endpoint is what BrowserToolHost drives.
        let hello = bridge
            .runtime
            .server
            .request("hello", json!({}))
            .await
            .expect("hello round trip");
        assert_eq!(hello["ready"], true);

        let tool_host = bridge.runtime.tool_host();
        assert!(tool_host
            .list_tools()
            .contains(&agistack_adapters_browser::host::TOOL_LIST_TABS.to_string()));
        let output = tool_host
            .call("browser_list_tabs", "{}")
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
        let broker = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
            .await
            .expect("broker connects");
        for _ in 0..50 {
            if bridge.runtime.broker_connected() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        assert!(bridge.runtime.broker_connected());

        // Dropping the socket closes the WS; the server must promptly clear
        // the active slot so `connected_browser_tool_host()` returns None and
        // the browser tools vanish from the engine surface.
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
}
