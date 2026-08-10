//! `--native-host` mode: the Chrome native-messaging broker, plus
//! install/uninstall/status of the native-messaging host manifests.
//!
//! Chrome launches this binary with `--native-host` over the extension's
//! stdio pipe. The broker reads the bridge registry written by the running
//! sidecar (`~/.memstack/browser-bridge/registry.json`), connects to the
//! sidecar's bridge WebSocket with the registry bearer token, and then relays
//! dumbly: length-prefixed stdin frames become WebSocket text frames and vice
//! versa. All logging goes to stderr so stdio stays protocol-clean.

use std::{
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};

use agistack_adapters_browser::framing;
use agistack_adapters_browser::jsonrpc::{self, JsonRpcMessage};
use futures_util::{SinkExt, StreamExt};
use serde::Serialize;
use serde_json::{json, Value};
#[cfg(unix)]
use tokio::net::UnixStream;
use tokio::{
    io::{AsyncRead, AsyncWrite},
    net::TcpStream,
    sync::{mpsc, Notify},
};
#[cfg(unix)]
use tokio_tungstenite::client_async;
use tokio_tungstenite::{
    connect_async,
    tungstenite::{client::IntoClientRequest, handshake::client::Request, Message},
    MaybeTlsStream, WebSocketStream,
};

use crate::local_runtime::browser_bridge::{
    self, read_registry, validate_registry, warn_if_registry_permissions_open, BridgeRegistry,
    DEFAULT_EXTENSION_ID,
};

/// Native messaging host name the extension asks Chrome to launch.
pub(crate) const HOST_NAME: &str = "com.memstack.browserbridge";
const MANIFEST_FILE_NAME: &str = "com.memstack.browserbridge.json";

/// Capped exponential backoff between WebSocket reconnect attempts.
const BACKOFF_STEPS: [Duration; 4] = [
    Duration::from_millis(250),
    Duration::from_secs(1),
    Duration::from_secs(4),
    Duration::from_secs(10),
];

const STDIO_BUFFER: usize = 32;

/// How the broker reaches the sidecar's bridge endpoint. The unix socket is
/// preferred whenever the registry advertises it and the file exists: it is
/// peer-UID-checked by the sidecar and never touches the loopback network.
/// TCP stays for Windows, dev, and stale-registry fallback.
#[derive(Clone, Debug, PartialEq, Eq)]
enum BridgeTransport {
    Unix(String),
    Tcp(String),
}

/// Pure transport decision, re-evaluated on every reconnect attempt.
fn pick_transport(registry: &BridgeRegistry, socket_exists: bool) -> BridgeTransport {
    match &registry.socket_path {
        Some(path) if socket_exists => BridgeTransport::Unix(path.clone()),
        _ => BridgeTransport::Tcp(registry.ws_url.clone()),
    }
}

/// Broker entry point (`--native-host`). Returns on stdin EOF; any registry
/// problem fails closed with a non-zero exit.
pub(crate) async fn run() -> Result<(), String> {
    let registry_path = browser_bridge::registry_path()?;
    warn_if_registry_permissions_open(&registry_path);
    let registry = read_registry(&registry_path)?;
    validate_registry(&registry)?;
    relay(registry).await
}

/// Relay loop: stdin frames ⇄ WebSocket text frames, reconnecting forever
/// until stdin closes.
async fn relay(registry: BridgeRegistry) -> Result<(), String> {
    let connected = Arc::new(AtomicBool::new(false));
    let done = Arc::new(AtomicBool::new(false));
    let notify_done = Arc::new(Notify::new());
    let (outbound_tx, mut outbound_rx) = mpsc::channel::<String>(STDIO_BUFFER);
    let (stdout_tx, mut stdout_rx) = mpsc::channel::<Vec<u8>>(STDIO_BUFFER);

    // Sole writer for stdout frames (protocol-clean: nothing else writes).
    let writer = tokio::spawn(async move {
        let mut stdout = tokio::io::stdout();
        while let Some(payload) = stdout_rx.recv().await {
            if let Err(error) =
                framing::write_frame(&mut stdout, &payload, framing::DEFAULT_MAX_OUTBOUND).await
            {
                tracing::warn!(%error, "browser bridge broker failed to write stdout");
                break;
            }
        }
    });

    // Sole reader for stdin frames. While the sidecar is unreachable nothing
    // is buffered: requests get an immediate JSON-RPC error instead.
    let reader = {
        let connected = Arc::clone(&connected);
        let done = Arc::clone(&done);
        let notify_done = Arc::clone(&notify_done);
        let outbound_tx = outbound_tx.clone();
        let stdout_tx = stdout_tx.clone();
        tokio::spawn(async move {
            let mut stdin = tokio::io::stdin();
            loop {
                match framing::read_frame(&mut stdin, framing::DEFAULT_MAX_INBOUND).await {
                    Ok(Some(payload)) => {
                        if connected.load(Ordering::SeqCst) {
                            match String::from_utf8(payload) {
                                Ok(text) => {
                                    if outbound_tx.send(text).await.is_err() {
                                        break;
                                    }
                                }
                                Err(_) => {
                                    tracing::warn!("dropping non-UTF-8 extension frame");
                                }
                            }
                        } else if let Some(response) = sidecar_unavailable_response(&payload) {
                            if stdout_tx.send(response.into_bytes()).await.is_err() {
                                break;
                            }
                        }
                    }
                    Ok(None) => break, // Clean stdin EOF: the extension hung up.
                    Err(error) => {
                        tracing::warn!(%error, "browser bridge broker stdin read failed");
                        break;
                    }
                }
            }
            done.store(true, Ordering::SeqCst);
            // notify_one (not notify_waiters): the permit is stored so a
            // connection manager that is not currently awaiting still sees it.
            notify_done.notify_one();
        })
    };

    let mut failures = 0usize;
    loop {
        if done.load(Ordering::SeqCst) {
            break;
        }
        // Re-evaluated every attempt: a restarted sidecar may add or remove
        // the unix socket while the broker is backing off.
        let socket_exists = registry
            .socket_path
            .as_deref()
            .is_some_and(|path| Path::new(path).is_file());
        let transport = pick_transport(&registry, socket_exists);
        match connect_and_serve(
            &transport,
            &registry,
            &connected,
            &mut outbound_rx,
            &stdout_tx,
            &notify_done,
        )
        .await
        {
            Ok(()) => failures = 0,
            Err(error) => {
                tracing::warn!(%error, "browser bridge broker connect failed");
                let delay = BACKOFF_STEPS[failures.min(BACKOFF_STEPS.len() - 1)];
                failures += 1;
                tokio::select! {
                    _ = tokio::time::sleep(delay) => {}
                    _ = notify_done.notified() => break,
                }
            }
        }
    }

    drop(outbound_tx);
    drop(stdout_tx);
    let _ = reader.await;
    let _ = writer.await;
    Ok(())
}

/// Serve one WebSocket session until it fails, the pipe closes, or stdin hits
/// EOF (`notify_done`).
async fn serve_connection<S>(
    ws: WebSocketStream<S>,
    outbound_rx: &mut mpsc::Receiver<String>,
    stdout_tx: &mpsc::Sender<Vec<u8>>,
    notify_done: &Arc<Notify>,
) where
    S: AsyncRead + AsyncWrite + Unpin,
{
    let (mut sink, mut stream) = ws.split();
    loop {
        tokio::select! {
            frame = outbound_rx.recv() => {
                match frame {
                    Some(frame) => {
                        if let Err(error) = sink.send(Message::Text(frame.into())).await {
                            tracing::warn!(%error, "browser bridge broker send failed");
                            return;
                        }
                    }
                    None => return,
                }
            }
            message = stream.next() => {
                match message {
                    Some(Ok(Message::Text(text))) => {
                        if stdout_tx.send(text.as_bytes().to_vec()).await.is_err() {
                            return;
                        }
                    }
                    Some(Ok(Message::Binary(bytes))) => {
                        if stdout_tx.send(bytes.to_vec()).await.is_err() {
                            return;
                        }
                    }
                    Some(Ok(Message::Close(_))) | None => return,
                    Some(Ok(_)) => {} // Ping/Pong carry no payload.
                    Some(Err(error)) => {
                        tracing::warn!(%error, "browser bridge broker receive failed");
                        return;
                    }
                }
            }
            _ = notify_done.notified() => return,
        }
    }
}

/// Connect over the chosen transport and serve the session. `Err` means the
/// connection never came up (the caller backs off and retries); a served
/// session that later dropped is `Ok`.
async fn connect_and_serve(
    transport: &BridgeTransport,
    registry: &BridgeRegistry,
    connected: &AtomicBool,
    outbound_rx: &mut mpsc::Receiver<String>,
    stdout_tx: &mpsc::Sender<Vec<u8>>,
    notify_done: &Arc<Notify>,
) -> Result<(), String> {
    match transport {
        BridgeTransport::Tcp(url) => {
            tracing::info!(transport = "tcp", url = %url, "browser bridge broker transport");
            let ws = establish_tcp(url, &registry.token).await?;
            run_session(ws, connected, outbound_rx, stdout_tx, notify_done).await;
            Ok(())
        }
        BridgeTransport::Unix(path) => {
            #[cfg(unix)]
            {
                tracing::info!(transport = "unix", path = %path, "browser bridge broker transport");
                let ws = establish_unix(path, &registry.ws_url, &registry.token).await?;
                run_session(ws, connected, outbound_rx, stdout_tx, notify_done).await;
                Ok(())
            }
            #[cfg(not(unix))]
            {
                Err(format!(
                    "browser bridge unix transport {path} is unsupported on this platform"
                ))
            }
        }
    }
}

/// Serve one established session, then fail any frames that were queued while
/// it died instead of buffering them into the next session.
async fn run_session<S>(
    ws: WebSocketStream<S>,
    connected: &AtomicBool,
    outbound_rx: &mut mpsc::Receiver<String>,
    stdout_tx: &mpsc::Sender<Vec<u8>>,
    notify_done: &Arc<Notify>,
) where
    S: AsyncRead + AsyncWrite + Unpin,
{
    connected.store(true, Ordering::SeqCst);
    serve_connection(ws, outbound_rx, stdout_tx, notify_done).await;
    connected.store(false, Ordering::SeqCst);
    while let Ok(stale) = outbound_rx.try_recv() {
        if let Some(response) = sidecar_unavailable_response(stale.as_bytes()) {
            if stdout_tx.send(response.into_bytes()).await.is_err() {
                break;
            }
        }
    }
}

/// Build the WS upgrade request shared by both transports: the registry
/// `wsUrl` supplies path and Host, the bearer token authenticates.
fn bridge_request(url: &str, token: &str) -> Result<Request, String> {
    let mut request = url
        .into_client_request()
        .map_err(|error| format!("invalid bridge url {url}: {error}"))?;
    let authorization = format!("Bearer {token}")
        .parse()
        .map_err(|_| "browser bridge registry token is not a valid header value".to_string())?;
    request.headers_mut().insert(
        tokio_tungstenite::tungstenite::http::header::AUTHORIZATION,
        authorization,
    );
    Ok(request)
}

/// Connect over loopback TCP presenting the registry token.
async fn establish_tcp(
    url: &str,
    token: &str,
) -> Result<WebSocketStream<MaybeTlsStream<TcpStream>>, String> {
    let (ws, _) = connect_async(bridge_request(url, token)?)
        .await
        .map_err(|error| format!("browser bridge connect failed: {error}"))?;
    Ok(ws)
}

/// Connect over the bridge unix socket presenting the registry token. The
/// HTTP request line still uses the registry `wsUrl` (only its path matters;
/// the Host header is never routed on).
#[cfg(unix)]
async fn establish_unix(
    socket_path: &str,
    url: &str,
    token: &str,
) -> Result<WebSocketStream<UnixStream>, String> {
    let stream = UnixStream::connect(socket_path)
        .await
        .map_err(|error| format!("browser bridge unix connect failed: {error}"))?;
    let (ws, _) = client_async(bridge_request(url, token)?, stream)
        .await
        .map_err(|error| format!("browser bridge unix handshake failed: {error}"))?;
    Ok(ws)
}

/// Build the `{"code": 1, "message": "sidecar unavailable"}` error response
/// for one inbound extension frame. `Some` only for requests — notifications
/// carry no id and get no answer.
fn sidecar_unavailable_response(payload: &[u8]) -> Option<String> {
    let value: Value = serde_json::from_slice(payload).ok()?;
    let id = match jsonrpc::decode_value(&value) {
        Ok(JsonRpcMessage::Request { id, .. }) => id,
        _ => return None,
    };
    Some(
        json!({
            "jsonrpc": "2.0",
            "id": id,
            "error": { "code": 1, "message": "sidecar unavailable" },
        })
        .to_string(),
    )
}

/// One browser's native-messaging host manifest location. `hosts_dir` is the
/// `NativeMessagingHosts` directory; installation only proceeds when its
/// parent (the browser's own profile directory) already exists.
#[derive(Clone, Debug)]
struct ManifestTarget {
    browser: &'static str,
    hosts_dir: PathBuf,
}

impl ManifestTarget {
    fn manifest_path(&self) -> PathBuf {
        self.hosts_dir.join(MANIFEST_FILE_NAME)
    }
}

#[cfg(target_os = "macos")]
fn manifest_targets() -> Vec<ManifestTarget> {
    let Ok(home) = browser_bridge::home_dir() else {
        return Vec::new();
    };
    let base = home.join("Library/Application Support");
    [
        ("Google Chrome", base.join("Google/Chrome")),
        ("Chromium", base.join("Chromium")),
        ("Microsoft Edge", base.join("Microsoft Edge")),
        ("Brave", base.join("BraveSoftware/Brave-Browser")),
    ]
    .into_iter()
    .map(|(browser, profile_dir)| ManifestTarget {
        browser,
        hosts_dir: profile_dir.join("NativeMessagingHosts"),
    })
    .collect()
}

#[cfg(target_os = "linux")]
fn manifest_targets() -> Vec<ManifestTarget> {
    let Ok(home) = browser_bridge::home_dir() else {
        return Vec::new();
    };
    let base = home.join(".config");
    [
        ("Google Chrome", base.join("google-chrome")),
        ("Chromium", base.join("chromium")),
        ("Microsoft Edge", base.join("microsoft-edge")),
        ("Brave", base.join("BraveSoftware/Brave-Browser")),
    ]
    .into_iter()
    .map(|(browser, profile_dir)| ManifestTarget {
        browser,
        hosts_dir: profile_dir.join("NativeMessagingHosts"),
    })
    .collect()
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn manifest_targets() -> Vec<ManifestTarget> {
    Vec::new()
}

// Chrome's manifest format itself is snake_case (`allowed_origins`); only the
// sidecar↔Electron result payloads are camelCase.
#[derive(Serialize)]
struct NativeMessagingManifest {
    name: &'static str,
    description: &'static str,
    path: PathBuf,
    #[serde(rename = "type")]
    manifest_type: &'static str,
    allowed_origins: Vec<String>,
}

fn manifest(host_path: &Path) -> NativeMessagingManifest {
    NativeMessagingManifest {
        name: HOST_NAME,
        description: "MemStack browser bridge native messaging host",
        path: host_path.to_path_buf(),
        manifest_type: "stdio",
        allowed_origins: vec![format!("chrome-extension://{DEFAULT_EXTENSION_ID}/")],
    }
}

/// One installed manifest, reported by `browser_bridge_install`.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct InstalledManifest {
    pub browser: String,
    pub manifest_path: PathBuf,
}

/// Result payload of `browser_bridge_install`.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct InstallResult {
    pub installed: Vec<InstalledManifest>,
    pub skipped: Vec<String>,
}

/// Result payload of `browser_bridge_uninstall`.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct UninstallResult {
    pub removed: Vec<String>,
}

/// One manifest probe entry, reported by `browser_bridge_status`.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ManifestStatus {
    pub browser: String,
    pub path: PathBuf,
    pub present: bool,
}

/// Write the native-messaging manifest into every detected browser. Windows
/// registration is registry-based and explicitly out of M1 scope.
pub(crate) fn install_manifests() -> Result<InstallResult, String> {
    if cfg!(windows) {
        return Err("windows native messaging registration is not supported in M1".to_string());
    }
    let host_path = std::env::current_exe().map_err(|error| error.to_string())?;
    let host_path = host_path.canonicalize().unwrap_or(host_path);
    let manifest = manifest(&host_path);
    let serialized = serde_json::to_vec_pretty(&manifest).map_err(|error| error.to_string())?;

    let mut installed = Vec::new();
    let mut skipped = Vec::new();
    for target in manifest_targets() {
        let Some(profile_dir) = target.hosts_dir.parent() else {
            continue;
        };
        if !profile_dir.is_dir() {
            skipped.push(target.browser.to_string());
            continue;
        }
        std::fs::create_dir_all(&target.hosts_dir).map_err(|error| error.to_string())?;
        let path = target.manifest_path();
        std::fs::write(&path, &serialized).map_err(|error| error.to_string())?;
        installed.push(InstalledManifest {
            browser: target.browser.to_string(),
            manifest_path: path,
        });
    }
    Ok(InstallResult { installed, skipped })
}

/// Remove the manifest from every browser location.
pub(crate) fn uninstall_manifests() -> Result<UninstallResult, String> {
    if cfg!(windows) {
        return Err("windows native messaging registration is not supported in M1".to_string());
    }
    let mut removed = Vec::new();
    for target in manifest_targets() {
        let path = target.manifest_path();
        match std::fs::remove_file(&path) {
            Ok(()) => removed.push(path.to_string_lossy().into_owned()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.to_string()),
        }
    }
    Ok(UninstallResult { removed })
}

/// Probe every known manifest location for `browser_bridge_status`.
pub(crate) fn manifest_statuses() -> Vec<ManifestStatus> {
    manifest_targets()
        .into_iter()
        .map(|target| {
            let path = target.manifest_path();
            ManifestStatus {
                browser: target.browser.to_string(),
                present: path.is_file(),
                path,
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn registry(socket_path: Option<&str>) -> BridgeRegistry {
        BridgeRegistry {
            schema_version: browser_bridge::REGISTRY_SCHEMA_VERSION,
            ws_url: "ws://127.0.0.1:9765/api/v1/browser-bridge/ws".to_string(),
            token: "a".repeat(64),
            extension_ids: vec![DEFAULT_EXTENSION_ID.to_string()],
            sidecar_path: PathBuf::from("/opt/memstack/sidecar"),
            updated_at: "2026-08-10T00:00:00Z".to_string(),
            socket_path: socket_path.map(str::to_string),
        }
    }

    #[test]
    fn pick_transport_prefers_the_unix_socket_when_present() {
        let registry = registry(Some("/home/dev/.memstack/browser-bridge/bridge.sock"));
        assert_eq!(
            pick_transport(&registry, true),
            BridgeTransport::Unix("/home/dev/.memstack/browser-bridge/bridge.sock".to_string())
        );
        // Socket advertised but missing on disk (stale registry): TCP.
        assert_eq!(
            pick_transport(&registry, false),
            BridgeTransport::Tcp(registry.ws_url.clone())
        );
    }

    #[test]
    fn pick_transport_falls_back_to_tcp_without_a_socket() {
        let registry = registry(None);
        assert_eq!(
            pick_transport(&registry, true),
            BridgeTransport::Tcp(registry.ws_url.clone())
        );
        assert_eq!(
            pick_transport(&registry, false),
            BridgeTransport::Tcp(registry.ws_url.clone())
        );
    }

    #[test]
    fn unavailable_response_echoes_the_request_id() {
        let response = sidecar_unavailable_response(
            br#"{"jsonrpc":"2.0","id":42,"method":"getTabs","params":{}}"#,
        )
        .expect("a request gets an error response");
        let value: Value = serde_json::from_str(&response).unwrap();
        assert_eq!(value["id"], 42);
        assert_eq!(value["error"]["code"], 1);
        assert_eq!(value["error"]["message"], "sidecar unavailable");
    }

    #[test]
    fn notifications_and_garbage_get_no_error_response() {
        assert!(sidecar_unavailable_response(
            br#"{"jsonrpc":"2.0","method":"onCDPEvent","params":{}}"#
        )
        .is_none());
        assert!(sidecar_unavailable_response(b"not json").is_none());
    }

    #[test]
    fn manifest_matches_the_frozen_contract() {
        let value = serde_json::to_value(manifest(Path::new("/opt/memstack/sidecar"))).unwrap();
        assert_eq!(value["name"], HOST_NAME);
        assert_eq!(
            value["description"],
            "MemStack browser bridge native messaging host"
        );
        assert_eq!(value["path"], "/opt/memstack/sidecar");
        assert_eq!(value["type"], "stdio");
        assert_eq!(
            value["allowed_origins"],
            json!([format!("chrome-extension://{DEFAULT_EXTENSION_ID}/")])
        );
    }
}
