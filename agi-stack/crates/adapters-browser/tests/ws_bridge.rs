//! End-to-end test of `BridgeWsClient` against a real WebSocket server that
//! speaks the fixed bridge contract: scripted `hello` / `ping` responses, one
//! `onCDPEvent` notification, then a connection drop — after which the client
//! must reconnect (the server accepts a second connection) and keep serving
//! requests.

use std::sync::Arc;
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::net::TcpListener;
use tokio_tungstenite::tungstenite::handshake::server::{Request, Response};
use tokio_tungstenite::tungstenite::http::{header, StatusCode};
use tokio_tungstenite::tungstenite::Message;

use agistack_adapters_browser::ws_client::{bridge_ws_url, BridgeWsClient};

const TOKEN: &str = "test-token";

/// Handshake callback enforcing the bearer token, like the real broker.
fn check_auth(
    req: &Request,
    response: Response,
) -> Result<Response, tokio_tungstenite::tungstenite::handshake::server::ErrorResponse> {
    let expected = format!("Bearer {TOKEN}");
    match req
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
    {
        Some(value) if value == expected => Ok(response),
        _ => Err(Response::builder()
            .status(StatusCode::UNAUTHORIZED)
            .body(Some("unauthorized".to_string()))
            .unwrap()),
    }
}

/// Read one JSON-RPC request frame and return its `(id, method)`.
async fn read_request<S>(stream: &mut S) -> (u64, String)
where
    S: StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin,
{
    loop {
        match stream.next().await {
            Some(Ok(Message::Text(text))) => {
                let value: Value = serde_json::from_str(&text).unwrap();
                let id = value.get("id").and_then(Value::as_u64).unwrap();
                let method = value
                    .get("method")
                    .and_then(Value::as_str)
                    .unwrap()
                    .to_string();
                return (id, method);
            }
            Some(Ok(_)) => continue, // Ping/Pong/etc.
            other => panic!("server expected a request frame, got {other:?}"),
        }
    }
}

/// Serve one connection per accepted socket.
/// Connection 1: hello → notification → ping → drop. Connection 2: ping,
/// then idle until the client goes away.
async fn serve(listener: TcpListener) {
    for connection in 0..2u32 {
        let (socket, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_hdr_async(socket, check_auth)
            .await
            .unwrap();

        // hello handshake + one notification (first connection only).
        if connection == 0 {
            let (id, method) = read_request(&mut ws).await;
            assert_eq!(method, "hello");
            let reply = json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "protocolVersion": 1,
                    "extensionId": "ext-test",
                    "capabilities": ["cdp"]
                }
            });
            ws.send(Message::Text(reply.to_string().into()))
                .await
                .unwrap();
            let notification = json!({
                "jsonrpc": "2.0",
                "method": "onCDPEvent",
                "params": {
                    "tabId": 7,
                    "method": "Log.entryAdded",
                    "params": {"entry": {"level": "info", "text": "hello from page", "timestamp": 1.0}}
                }
            });
            ws.send(Message::Text(notification.to_string().into()))
                .await
                .unwrap();
        }

        // One ping, then drop the first connection to force a reconnect.
        let (id, method) = read_request(&mut ws).await;
        assert_eq!(method, "ping");
        let reply = json!({"jsonrpc": "2.0", "id": id, "result": {}});
        ws.send(Message::Text(reply.to_string().into()))
            .await
            .unwrap();
        if connection == 0 {
            drop(ws); // hard drop: client must detect and reconnect
            continue;
        }

        // Second connection: serve pings until the client disconnects.
        while let Some(frame) = ws.next().await {
            match frame {
                Ok(Message::Text(text)) => {
                    let value: Value = serde_json::from_str(&text).unwrap();
                    if let Some(id) = value.get("id").and_then(Value::as_u64) {
                        let reply = json!({"jsonrpc": "2.0", "id": id, "result": {}});
                        ws.send(Message::Text(reply.to_string().into()))
                            .await
                            .unwrap();
                    }
                }
                Ok(Message::Close(_)) | Err(_) => break,
                _ => {}
            }
        }
    }
}

#[tokio::test]
async fn correlates_requests_delivers_notifications_and_reconnects() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = Arc::new(tokio::spawn(serve(listener)));

    let client = BridgeWsClient::connect(&bridge_ws_url(port), TOKEN)
        .await
        .unwrap();
    let mut notifications = client.subscribe_notifications();

    // 1. Request/response correlation.
    let hello = client.request("hello", json!({})).await.unwrap();
    assert_eq!(hello["protocolVersion"], 1);
    assert_eq!(hello["extensionId"], "ext-test");

    // 2. Notification delivery.
    let notification = tokio::time::timeout(Duration::from_secs(5), notifications.recv())
        .await
        .expect("notification timed out")
        .unwrap();
    assert_eq!(notification.method, "onCDPEvent");
    assert_eq!(notification.params["tabId"], 7);
    assert_eq!(notification.params["method"], "Log.entryAdded");

    // 3. First ping succeeds on connection 1; the server then drops it.
    client.request("ping", json!({})).await.unwrap();

    // 4. After the drop the client reconnects (backoff starts at 250ms) and
    //    later pings succeed on connection 2.
    let mut reconnected = false;
    for _ in 0..50 {
        tokio::time::sleep(Duration::from_millis(100)).await;
        if client.request("ping", json!({})).await.is_ok() {
            reconnected = true;
            break;
        }
    }
    assert!(reconnected, "client did not reconnect and serve requests");

    client.shutdown().await;
    drop(server);
}

#[tokio::test]
async fn connect_fails_fast_on_auth_rejection() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    tokio::spawn(async move {
        let (socket, _) = listener.accept().await.unwrap();
        let _ = tokio_tungstenite::accept_hdr_async(socket, check_auth).await;
    });

    let result = BridgeWsClient::connect(&bridge_ws_url(port), "wrong-token").await;
    assert!(result.is_err(), "bad token must fail the initial connect");
}
