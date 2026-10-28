use super::*;
use crate::local_runtime::browser_bridge::{
    self, BrowserBridgeConfig, BrowserBridgeRuntime, BACKEND_CHROME_EXTENSION, DEFAULT_EXTENSION_ID,
};
use crate::native_host::{framing, relay};
use agistack_adapters_browser::protocol::{PROTOCOL_MAX, PROTOCOL_MIN, PROTOCOL_VERSION};
use agistack_core::ports::ToolHost;
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use std::{
    os::unix::fs::{symlink, MetadataExt, PermissionsExt},
    path::PathBuf,
    time::Duration,
};
use tokio::{
    io::duplex,
    net::{UnixListener, UnixStream},
};
use tokio_tungstenite::{
    accept_hdr_async,
    tungstenite::{
        handshake::server::{Request, Response},
        Message,
    },
    WebSocketStream,
};

struct Fixture {
    root: PathBuf,
    directory: PathBuf,
    registry: PathBuf,
    socket: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "bc-{}",
            &uuid::Uuid::new_v4().simple().to_string()[..8]
        ));
        let directory = root.join(".memstack/browser-bridge");
        std::fs::create_dir_all(&directory).unwrap();
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
        Self {
            registry: directory.join("registry.json"),
            socket: directory.join("bridge.sock"),
            root,
            directory,
        }
    }
    fn document(&self, token: &str) -> BridgeRegistry {
        BridgeRegistry {
            schema_version: browser_bridge::REGISTRY_SCHEMA_VERSION,
            ws_url: "ws://127.0.0.1:9/api/v1/browser-bridge/ws".into(),
            token: token.repeat(64),
            extension_ids: vec![DEFAULT_EXTENSION_ID.into()],
            sidecar_path: PathBuf::from("/test/sidecar"),
            updated_at: "2026-10-22T04:43:10Z".into(),
            socket_path: Some(self.socket.to_string_lossy().into()),
        }
    }
    fn publish(&self, token: &str) {
        let staged = self.directory.join("registry.next");
        browser_bridge::write_registry(&staged, &self.document(token)).unwrap();
        std::fs::rename(staged, &self.registry).unwrap();
    }
    fn bind(&self) -> UnixListener {
        let listener = UnixListener::bind(&self.socket).unwrap();
        std::fs::set_permissions(&self.socket, std::fs::Permissions::from_mode(0o600)).unwrap();
        listener
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

#[test]
fn private_registry_refresh_rejects_permissions_symlinks_and_changed_inodes() {
    let fixture = Fixture::new();
    fixture.publish("a");
    let first = std::fs::metadata(&fixture.registry).unwrap();
    assert_eq!(
        load_registry(&fixture.registry).unwrap().token,
        "a".repeat(64)
    );
    fixture.publish("b");
    assert!(ensure_same_file(&first, &std::fs::metadata(&fixture.registry).unwrap()).is_err());
    assert_eq!(
        load_registry(&fixture.registry).unwrap().token,
        "b".repeat(64)
    );
    for (path, mode) in [(&fixture.registry, 0o644), (&fixture.directory, 0o755)] {
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode)).unwrap();
        let error = load_registry(&fixture.registry).unwrap_err();
        assert!(!error.contains(&"b".repeat(64)));
        std::fs::set_permissions(
            path,
            std::fs::Permissions::from_mode(if path == &fixture.registry {
                0o600
            } else {
                0o700
            }),
        )
        .unwrap();
    }
    let target = fixture.directory.join("real.json");
    std::fs::rename(&fixture.registry, &target).unwrap();
    symlink(target, &fixture.registry).unwrap();
    assert!(load_registry(&fixture.registry).is_err());
}

#[tokio::test]
async fn socket_selection_requires_a_private_real_socket_without_tcp_downgrade() {
    let fixture = Fixture::new();
    fixture.publish("a");
    let registry = load_registry(&fixture.registry).unwrap();
    assert!(transport(&fixture.registry, &registry).is_err());
    std::fs::write(&fixture.socket, "not a socket").unwrap();
    assert!(transport(&fixture.registry, &registry).is_err());
    std::fs::remove_file(&fixture.socket).unwrap();
    let _listener = fixture.bind();
    assert!(matches!(
        transport(&fixture.registry, &registry).unwrap(),
        BridgeTransport::Unix(_)
    ));
    std::fs::set_permissions(&fixture.socket, std::fs::Permissions::from_mode(0o666)).unwrap();
    assert!(transport(&fixture.registry, &registry).is_err());
    let mut tcp_only = registry;
    tcp_only.socket_path = None;
    assert!(matches!(
        transport(&fixture.registry, &tcp_only).unwrap(),
        BridgeTransport::Tcp(_)
    ));
}

#[tokio::test]
async fn connected_socket_rejects_foreign_peer_and_replaced_inode() {
    let fixture = Fixture::new();
    let _first_listener = fixture.bind();
    let identity = socket_identity(&fixture.socket).unwrap();
    assert!(
        verify_connected_socket(&fixture.socket, &identity, effective_uid().wrapping_add(1))
            .is_err()
    );
    std::fs::remove_file(&fixture.socket).unwrap();
    let _second_listener = fixture.bind();
    assert_ne!(
        identity.1.ino(),
        std::fs::metadata(&fixture.socket).unwrap().ino()
    );
    assert!(verify_connected_socket(&fixture.socket, &identity, effective_uid()).is_err());
}

async fn accept_authorized(listener: &UnixListener, token: &str) -> WebSocketStream<UnixStream> {
    let (stream, _) = tokio::time::timeout(Duration::from_secs(6), listener.accept())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(stream.peer_cred().unwrap().uid(), effective_uid());
    let expected = format!("Bearer {}", token.repeat(64));
    accept_hdr_async(stream, move |request: &Request, response: Response| {
        if request
            .headers()
            .get("authorization")
            .and_then(|value| value.to_str().ok())
            == Some(expected.as_str())
        {
            Ok(response)
        } else {
            Err(tokio_tungstenite::tungstenite::http::Response::builder()
                .status(401)
                .body(None)
                .unwrap())
        }
    })
    .await
    .expect("fresh registry token must authenticate")
}

async fn exchange(
    ws: &mut WebSocketStream<UnixStream>,
    native_input: &mut tokio::io::DuplexStream,
    native_output: &mut tokio::io::DuplexStream,
    round: u32,
) {
    let request = format!(r#"{{"jsonrpc":"2.0","id":{round},"method":"hello"}}"#);
    ws.send(Message::Text(request.clone())).await.unwrap();
    let payload = tokio::time::timeout(
        Duration::from_secs(3),
        framing::read_frame(native_output, framing::DEFAULT_MAX_INBOUND),
    )
    .await
    .unwrap()
    .unwrap()
    .unwrap();
    assert_eq!(payload, request.as_bytes());
    let answer = format!(r#"{{"jsonrpc":"2.0","id":{round},"result":{{"ok":true}}}}"#);
    framing::write_frame(
        native_input,
        answer.as_bytes(),
        framing::DEFAULT_MAX_OUTBOUND,
    )
    .await
    .unwrap();
    let message = tokio::time::timeout(Duration::from_secs(3), ws.next())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(message.into_text().unwrap(), answer);
}

#[tokio::test]
async fn live_broker_reloads_rotated_token_after_socket_restart_and_registry_gap() {
    let fixture = Fixture::new();
    fixture.publish("a");
    let first_listener = fixture.bind();
    let (broker_input, mut native_input) = duplex(65536);
    let (mut native_output, broker_output) = duplex(65536);
    let broker = tokio::spawn(relay(fixture.registry.clone(), broker_input, broker_output));
    let mut first = accept_authorized(&first_listener, "a").await;
    exchange(&mut first, &mut native_input, &mut native_output, 1).await;

    // Replace the actual socket while retaining the old established connection.
    // Removing the registry must not reuse the old token against the new socket.
    drop(first_listener);
    std::fs::remove_file(&fixture.socket).unwrap();
    let second_listener = fixture.bind();
    std::fs::remove_file(&fixture.registry).unwrap();
    first.close(None).await.unwrap();
    drop(first);
    assert!(
        tokio::time::timeout(Duration::from_millis(400), second_listener.accept())
            .await
            .is_err()
    );

    fixture.publish("b");
    let mut second = accept_authorized(&second_listener, "b").await;
    exchange(&mut second, &mut native_input, &mut native_output, 2).await;
    drop(native_input);
    tokio::time::timeout(Duration::from_secs(3), broker)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
}

async fn answer_runtime_hello(
    native_input: &mut tokio::io::DuplexStream,
    native_output: &mut tokio::io::DuplexStream,
) {
    let payload = tokio::time::timeout(
        Duration::from_secs(6),
        framing::read_frame(native_output, framing::DEFAULT_MAX_INBOUND),
    )
    .await
    .expect("the same native relay must receive the restarted bridge hello")
    .unwrap()
    .unwrap();
    let hello: Value = serde_json::from_slice(&payload).unwrap();
    assert_eq!(hello["method"], "hello");
    let answer = json!({
        "jsonrpc": "2.0",
        "id": hello["id"],
        "result": {
            "ready": true,
            "backend": BACKEND_CHROME_EXTENSION,
            "protocolVersion": PROTOCOL_VERSION,
            "protocolMin": PROTOCOL_MIN,
            "protocolMax": PROTOCOL_MAX,
            "profileId": "4b0d476b-dfb7-468e-bcf3-33589705a8fd",
            "extensionInstanceId": "d25f3848-c065-456e-9549-fcf5462b4321"
        }
    });
    framing::write_frame(
        native_input,
        answer.to_string().as_bytes(),
        framing::DEFAULT_MAX_OUTBOUND,
    )
    .await
    .unwrap();
}

async fn wait_for_runtime_broker(runtime: &BrowserBridgeRuntime) {
    tokio::time::timeout(Duration::from_secs(3), async {
        while runtime.connected_backends() != [BACKEND_CHROME_EXTENSION] {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("the production bridge must admit the relayed Chrome broker");
}

#[tokio::test]
async fn production_bridge_restart_reconnects_the_same_native_relay_and_expires_old_handles() {
    let fixture = Fixture::new();
    let config = BrowserBridgeConfig {
        enabled: true,
        port: 0,
        ..Default::default()
    };
    let first =
        BrowserBridgeRuntime::start_with_registry_path(&config, fixture.registry.clone(), None)
            .unwrap();
    let first_token = load_registry(&fixture.registry).unwrap().token;
    let (broker_input, mut native_input) = duplex(65536);
    let (mut native_output, broker_output) = duplex(65536);
    let broker = tokio::spawn(relay(fixture.registry.clone(), broker_input, broker_output));
    answer_runtime_hello(&mut native_input, &mut native_output).await;
    wait_for_runtime_broker(&first).await;
    let old_server = first.server();
    let old_host = first.browser_tool_host();
    let old_input = old_host
        .bind_input(
            "browser_snapshot",
            &json!({"backend": "chrome", "tabId": 7}),
        )
        .await
        .unwrap();

    // Only production stop closes the established connection: the relay and
    // both native pipe endpoints survive the listener and credential rotation.
    first.stop();
    assert!(!fixture.registry.exists());
    let second =
        BrowserBridgeRuntime::start_with_registry_path(&config, fixture.registry.clone(), None)
            .unwrap();
    assert!(
        first_token != load_registry(&fixture.registry).unwrap().token,
        "bridge restart must rotate credentials"
    );
    answer_runtime_hello(&mut native_input, &mut native_output).await;
    wait_for_runtime_broker(&second).await;
    assert!(!old_server.broker_connected());
    assert!(old_server.connected_backends().is_empty());
    let old_inventory = old_host
        .call(
            "browser_read_operation",
            r#"{"operation":"browsers.list","args":[]}"#,
        )
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&old_inventory).unwrap(),
        json!([])
    );
    assert!(old_host
        .bind_input("browser_snapshot", &old_input)
        .await
        .is_err());
    let new_host = second.browser_tool_host();
    let new_input = new_host
        .bind_input(
            "browser_snapshot",
            &json!({"backend": "chrome", "tabId": 7}),
        )
        .await
        .unwrap();
    assert_ne!(old_input["backend"], new_input["backend"]);
    assert!(new_host
        .bind_input("browser_snapshot", &old_input)
        .await
        .is_err());

    drop(native_input);
    tokio::time::timeout(Duration::from_secs(3), broker)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    second.stop();
}
