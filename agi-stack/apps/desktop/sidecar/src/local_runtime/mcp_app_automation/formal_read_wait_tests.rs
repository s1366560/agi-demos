//! An in-flight App receipt read crosses the real HTTP approval revision change.
use super::*;
use crate::local_runtime::browser_bridge::{self, BrowserBridgeConfig, BrowserBridgeRuntime};
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::{client::IntoClientRequest, Message};

/// The production authenticated WebSocket and Node RPC paths are real. The
/// iframe wait resolves only after the real MCP server writes its effect marker.
struct ReceiptBridge {
    worker: JoinHandle<()>,
    requests: Arc<Mutex<Vec<Value>>>,
    expire: Arc<Notify>,
    expired: Arc<Notify>,
}

async fn attach_receipt_bridge(
    fixture: &FormalFixture,
    started: Arc<Notify>,
    expires_while_paused: bool,
) -> ReceiptBridge {
    let path = fixture.root.join("receipt-bridge-registry.json");
    let runtime = BrowserBridgeRuntime::start_with_registry_path(
        &BrowserBridgeConfig {
            enabled: true,
            port: 0,
            extension_ids: vec![],
            full_cdp_access_enabled: false,
            ..Default::default()
        },
        path.clone(),
        None,
    )
    .unwrap();
    let registry = browser_bridge::read_registry(&path).unwrap();
    let server = runtime.server();
    *fixture.state.browser_bridge.lock().unwrap() = Some(runtime);
    let mut request = registry.ws_url.into_client_request().unwrap();
    request.headers_mut().insert(
        "authorization",
        format!("Bearer {}", registry.token).parse().unwrap(),
    );
    let (mut socket, _) = tokio_tungstenite::connect_async(request).await.unwrap();
    let renderer_id = fixture.renderer_id.clone();
    let marker = fixture.root.join("callback-complete");
    let requests = Arc::new(Mutex::new(Vec::new()));
    let recorded = requests.clone();
    let expire = Arc::new(Notify::new());
    let expired = Arc::new(Notify::new());
    let expiry_tick = expire.clone();
    let expired_notice = expired.clone();
    let broker = tokio::spawn(async move {
        while let Some(message) = socket.next().await {
            let Message::Text(text) = message.unwrap() else {
                continue;
            };
            let request: Value = serde_json::from_str(&text).unwrap();
            let result = match request["method"].as_str().unwrap() {
                "hello" => json!({"backend":"iab"}),
                "mcpAppsExecute" => {
                    assert_eq!(request["params"]["tabId"], renderer_id);
                    assert_eq!(request["params"]["mountNonce"], "fixture-mount");
                    assert_eq!(request["params"]["operation"], "playwright.locator");
                    let expression = request["params"]["expression"].as_str().unwrap();
                    assert!(expression.contains("Actual main counter callback completed"));
                    let attempt = {
                        let mut requests = recorded.lock().unwrap();
                        requests.push(request["id"].clone());
                        requests.len()
                    };
                    started.notify_one();
                    if attempt == 1 && expires_while_paused {
                        // A controlled page-clock expiry occurs after the host has
                        // yielded approval. Neither Runtime.evaluate nor the DOM
                        // waiter needs a longer product timeout to survive it.
                        expiry_tick.notified().await;
                        socket.send(Message::Text(json!({"jsonrpc":"2.0","id":request["id"],"error":{"code":-32000,"message":"Runtime.evaluate timed out"}}).to_string())).await.unwrap();
                        expired_notice.notify_one();
                        continue;
                    }
                    tokio::time::timeout(Duration::from_secs(10), async {
                        while !marker.is_file() {
                            tokio::time::sleep(Duration::from_millis(5)).await;
                        }
                    })
                    .await
                    .unwrap();
                    json!(if attempt == 1 {
                        "stale poison"
                    } else {
                        "fresh receipt"
                    })
                }
                method => panic!("unexpected receipt bridge operation: {method}"),
            };
            socket
                .send(Message::Text(
                    json!({"jsonrpc":"2.0","id":request["id"],"result":result}).to_string(),
                ))
                .await
                .unwrap();
        }
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        while !server
            .connected_backends()
            .iter()
            .any(|backend| backend == "iab")
        {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    ReceiptBridge {
        worker: broker,
        requests,
        expire,
        expired,
    }
}

#[tokio::test]
async fn formal_http_approval_preserves_an_inflight_app_receipt_wait_in_the_same_cell() {
    receipt_wait(false).await;
}

#[tokio::test]
async fn formal_http_approval_ignores_expired_old_page_wait_and_readmits_current_receipt() {
    receipt_wait(true).await;
}

async fn receipt_wait(expires_while_paused: bool) {
    let fixture = FormalFixture::new().await;
    let started = Arc::new(Notify::new());
    let broker = attach_receipt_bridge(&fixture, started.clone(), expires_while_paused).await;
    let operation = json!({"browserId":"mcpapps","tabId":fixture.handle,"operation":"playwright.locator","args":[[{"kind":"getByRole","args":["status"]},{"kind":"filter","args":[{"hasText":"Actual main counter callback completed"}]}],"waitFor",[{"state":"attached","timeout":30000}]]});
    let code = format!("globalThis.receiptStarts=(globalThis.receiptStarts??0)+1; var receipt = await nodeRepl.rpc('browser.operation',{operation}); [globalThis.receiptStarts,receipt]");
    let (pending, callback) = fixture
        .pending_with(&code, move |state, input| {
            tokio::spawn(async move {
                // Ensure the read is actually in flight under the original authority
                // before the independent iframe callback enters permission admission.
                tokio::time::timeout(Duration::from_secs(5), started.notified())
                    .await
                    .unwrap();
                state
                    .mcp_app_automation
                    .renderer_operation(&state, input)
                    .await
            })
        })
        .await;
    let request = fixture.wait_for_approval(&pending).await;
    if expires_while_paused {
        broker.expire.notify_one();
        tokio::time::timeout(Duration::from_secs(2), broker.expired.notified())
            .await
            .unwrap();
    }
    let llm = fixture.llm(Some(code));
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    tokio::time::timeout(Duration::from_secs(15), llm.ready.notified())
        .await
        .unwrap();
    let callback_result = tokio::time::timeout(Duration::from_secs(2), callback)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    let transcript = llm.observed.lock().unwrap().clone();
    let observed = transcript
        .iter()
        .filter_map(|content| serde_json::from_str::<Value>(content).ok())
        .find(|value| value["cell_id"] == pending["repl_continuation"]["cell_id"]);
    let counts = fixture.counts().await;
    fixture
        .state
        .browser_bridge
        .lock()
        .unwrap()
        .take()
        .unwrap()
        .stop();
    let requests = broker.requests.lock().unwrap().clone();
    broker.worker.abort();
    fixture.finish(Some(&llm)).await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    assert_eq!(payload(&callback_result)["counts"]["main"], 1);
    assert_eq!(counts, json!({"main":1,"sibling":0,"hidden":0}));
    let observed =
        observed.unwrap_or_else(|| panic!("original receipt wait was lost: {transcript:?}"));
    assert_eq!(observed["ok"], true, "{observed}");
    assert_eq!(requests.len(), 2, "one original read and one current read");
    assert_ne!(
        requests[0], requests[1],
        "the stale bridge id must be retired"
    );
    assert_eq!(
        observed["value"],
        json!([1, "fresh receipt"]),
        "the retained Node cell must not restart"
    );
}
