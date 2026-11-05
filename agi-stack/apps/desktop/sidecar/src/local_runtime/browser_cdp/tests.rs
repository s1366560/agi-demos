use super::*;
use axum::{
    extract::ws::{Message, WebSocketUpgrade},
    response::IntoResponse,
    routing::get,
    Router,
};
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::time::Duration;
use tokio::sync::broadcast;

#[tokio::test]
async fn discovery_revalidates_redirect_and_discovered_websocket() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let app = Router::new()
        .route(
            "/redirect",
            get(|| async {
                axum::response::Redirect::temporary("http://169.254.169.254/json/version")
            }),
        )
        .route(
            "/external",
            get(|| async {
                axum::Json(json!({"webSocketDebuggerUrl":"ws://example.com/devtools/browser/a"}))
            }),
        )
        .route(
            "/local",
            get(move || async move {
                axum::Json(
                    json!({"webSocketDebuggerUrl":format!("ws://{address}/devtools/browser/a")}),
                )
            }),
        );
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    assert!(endpoint::discover(&format!("http://{address}/redirect"))
        .await
        .unwrap_err()
        .contains("loopback"));
    assert!(endpoint::discover(&format!("http://{address}/external"))
        .await
        .unwrap_err()
        .contains("loopback"));
    assert_eq!(
        endpoint::discover(&format!("http://{address}/local"))
            .await
            .unwrap()
            .scheme(),
        "ws"
    );
    server.abort();
}

async fn fake_cdp() -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let app = Router::new().route("/json/version", get(move || async move { axum::Json(json!({"webSocketDebuggerUrl":format!("ws://{address}/devtools/browser/a")})) }))
        .route("/devtools/browser/a", get(|upgrade: WebSocketUpgrade| async move {
            upgrade.on_upgrade(|mut socket| async move {
                while let Some(Ok(Message::Text(text))) = socket.next().await {
                    let request: Value = serde_json::from_str(&text).unwrap();
                    let result = match request["method"].as_str().unwrap() {
                        "Target.getTargets" => json!({"targetInfos":[{"targetId":"string-target","type":"page","title":"Fixture","url":"https://fixture.test/"}]}),
                        "Target.attachToTarget" => json!({"sessionId":"root-session"}),
                        "Target.closeTarget" => json!({"success":false}),
                        "Runtime.evaluate" => json!({"result":{"value":{"error":"ordinary application data"}}}),
                        "Test.never" => continue,
                        "Test.delayed" => { tokio::time::sleep(Duration::from_millis(100)).await; json!({"late":true}) },
                        "Test.disconnect" => break,
                        _ => json!({}),
                    };
                    if socket.send(Message::Text(json!({"id":request["id"],"result":result}).to_string())).await.is_err() { break; }
                }
            }).into_response()
        }));
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (format!("http://{address}"), server)
}

async fn wait_inventory(registry: &CdpRegistry) -> String {
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if let Some(id) = registry
                .inventory()
                .first()
                .and_then(|info| info["id"].as_str())
            {
                return id.to_string();
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap()
}

#[tokio::test]
async fn pending_commands_are_rejected_immediately_when_connection_closes() {
    let (endpoint, server) = fake_cdp().await;
    let connection = transport::Connection::connect(&endpoint).await.unwrap();
    let pending = tokio::spawn({
        let connection = connection.clone();
        async move { connection.request("Test.never", json!({}), None).await }
    });
    tokio::task::yield_now().await;
    connection.close();
    assert!(tokio::time::timeout(Duration::from_secs(1), pending)
        .await
        .unwrap()
        .unwrap()
        .is_err());
    assert!(connection
        .request("Target.getTargets", json!({}), None)
        .await
        .is_err());
    server.abort();
}

#[tokio::test]
async fn cancelled_command_late_reply_cannot_settle_a_later_request() {
    let (endpoint, server) = fake_cdp().await;
    let connection = transport::Connection::connect(&endpoint).await.unwrap();
    let pending = tokio::spawn({
        let connection = connection.clone();
        async move { connection.request("Test.delayed", json!({}), None).await }
    });
    tokio::time::sleep(Duration::from_millis(20)).await;
    pending.abort();
    assert!(pending.await.unwrap_err().is_cancelled());
    let next = connection
        .request("Target.getTargets", json!({}), None)
        .await
        .unwrap();
    assert!(next["targetInfos"].is_array());
    assert!(next.get("late").is_none());
    connection.close();
    server.abort();
}

#[tokio::test]
async fn independent_cdp_providers_have_distinct_handles_and_ambiguous_family() {
    let (endpoint, server) = fake_cdp().await;
    let configs: Vec<_> = ["First", "Second"]
        .into_iter()
        .map(|name| CdpEndpointConfig {
            id: uuid::Uuid::new_v4().to_string(),
            name: name.into(),
            endpoint: endpoint.clone(),
            enabled: true,
        })
        .collect();
    let (notifications, _) = broadcast::channel(256);
    let registry = CdpRegistry::start(&configs, notifications).unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        while registry.inventory().len() != 2 {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    assert!(registry.resolve("cdp").unwrap_err().contains("ambiguous"));
    let first = registry.resolve(&format!("cdp:{}", configs[0].id)).unwrap();
    let second = registry.resolve(&format!("cdp:{}", configs[1].id)).unwrap();
    assert_ne!(first, second);
    assert_eq!(
        registry
            .request(&first, "getTabs", json!({}))
            .await
            .unwrap()["tabs"][0]["tabId"],
        1
    );
    assert_eq!(
        registry
            .request(&second, "getTabs", json!({}))
            .await
            .unwrap()["tabs"][0]["tabId"],
        1
    );
    registry.stop();
    server.abort();
}

#[tokio::test]
async fn reconnect_rotates_identity_and_rejects_old_handles_and_foreign_sessions() {
    let (endpoint, server) = fake_cdp().await;
    let config = CdpEndpointConfig {
        id: uuid::Uuid::new_v4().to_string(),
        name: "Fixture".into(),
        endpoint,
        enabled: true,
    };
    let (notifications, _) = broadcast::channel(256);
    let registry = CdpRegistry::start(std::slice::from_ref(&config), notifications).unwrap();
    let old = wait_inventory(&registry).await;
    assert_eq!(
        registry.resolve(&format!("cdp:{}", config.id)).unwrap(),
        old
    );
    let tabs = registry.request(&old, "getTabs", json!({})).await.unwrap();
    let tab = tabs["tabs"][0]["tabId"].as_u64().unwrap();
    assert!(registry
        .request(
            &old,
            "executeCdp",
            json!({"tabId":tab,"sessionId":"foreign-session","method":"Runtime.evaluate"})
        )
        .await
        .is_err());
    let result = registry
        .request(
            &old,
            "executeCdp",
            json!({"tabId":tab,"method":"Runtime.evaluate"}),
        )
        .await
        .unwrap();
    assert_eq!(
        result["result"]["result"]["value"]["error"],
        "ordinary application data"
    );
    assert!(registry
        .request(
            &old,
            "executeCdp",
            json!({"tabId":tab,"method":"Test.disconnect"})
        )
        .await
        .is_err());
    let next = wait_inventory(&registry).await;
    assert_ne!(old, next);
    assert!(registry.resolve(&old).is_err());
    assert!(registry.request(&old, "getTabs", json!({})).await.is_err());
    registry.stop();
    assert!(registry.inventory().is_empty());
    assert!(registry.request(&next, "getTabs", json!({})).await.is_err());
    server.abort();
}

#[tokio::test]
async fn refused_target_close_preserves_live_tab_identity() {
    let (endpoint, server) = fake_cdp().await;
    let config = CdpEndpointConfig {
        id: uuid::Uuid::new_v4().to_string(),
        name: "Fixture".into(),
        endpoint,
        enabled: true,
    };
    let (notifications, _) = broadcast::channel(256);
    let registry = CdpRegistry::start(&[config], notifications).unwrap();
    let browser = wait_inventory(&registry).await;
    let before = registry
        .request(&browser, "getTabs", json!({}))
        .await
        .unwrap();
    let tab = before["tabs"][0]["tabId"].as_u64().unwrap();
    assert_eq!(
        registry
            .request(&browser, "closeTab", json!({"tabId":tab}))
            .await
            .unwrap_err(),
        "cdp_close_target_failed"
    );
    let after = registry
        .request(&browser, "getTabs", json!({}))
        .await
        .unwrap();
    assert_eq!(after["tabs"][0]["tabId"], tab);
    registry.stop();
    server.abort();
}

#[test]
fn cdp_endpoints_only_accept_explicit_loopback_and_no_credentials() {
    for value in [
        "http://127.0.0.1:9222",
        "ws://127.0.0.2:9222/devtools/browser/abc",
        "http://localhost:9222",
        "ws://[::1]:9222/devtools/browser/abc",
    ] {
        endpoint::validate(value).unwrap();
    }
    for value in [
        "https://example.com",
        "ws://192.168.1.2:9222",
        "http://169.254.169.254",
        "http://127.0.0.1.example.com",
        "ws://localhost.example.com",
        "file:///tmp/devtools",
        "ws://user:password@localhost:9222",
        "ws://localhost:9222/#secret",
        "ws://[::ffff:192.168.1.1]:9222",
        "http://0.0.0.0:9222",
    ] {
        assert!(endpoint::validate(value).is_err(), "accepted {value}");
    }
}

#[test]
fn cdp_configuration_rejects_duplicate_ids_and_invalid_disabled_endpoints() {
    let first = CdpEndpointConfig {
        id: uuid::Uuid::new_v4().to_string(),
        name: "Local Chromium".into(),
        endpoint: "http://127.0.0.1:9222".into(),
        enabled: true,
    };
    validate_configs(std::slice::from_ref(&first)).unwrap();
    assert!(validate_configs(&[first.clone(), first.clone()]).is_err());
    let mut invalid = first;
    invalid.enabled = false;
    invalid.endpoint = "http://example.com".into();
    assert!(validate_configs(&[invalid]).is_err());
}
