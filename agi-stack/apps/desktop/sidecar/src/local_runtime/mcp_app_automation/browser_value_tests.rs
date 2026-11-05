//! The public facade preserves typed values across authenticated bridge and Node RPC frames.
use super::*;
use crate::local_runtime::browser_bridge::{self, BrowserBridgeConfig, BrowserBridgeRuntime};
use futures_util::{SinkExt, StreamExt};
use std::collections::VecDeque;
use tokio_tungstenite::tungstenite::{client::IntoClientRequest, Message};

struct Reply {
    operation: &'static str,
    args: Value,
    result: Result<Value, &'static str>,
}

fn locator(selector: &str, method: &str, args: Value, result: Value) -> Reply {
    Reply {
        operation: "playwright.locator",
        args: json!([[{"kind":"locator","args":[selector]}],method,args]),
        result: Ok(result),
    }
}

async fn attach_value_bridge(
    fixture: &FormalFixture,
    replies: Vec<Reply>,
) -> (JoinHandle<()>, Arc<AtomicUsize>) {
    let path = fixture.root.join("value-bridge-registry.json");
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
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = calls.clone();
    let worker = tokio::spawn(async move {
        let mut replies = VecDeque::from(replies);
        while let Some(message) = socket.next().await {
            let Message::Text(text) = message.unwrap() else {
                continue;
            };
            let request: Value = serde_json::from_str(&text).unwrap();
            let result = match request["method"].as_str().unwrap() {
                "hello" => Ok(json!({"backend":"iab"})),
                "mcpAppsExecute" => {
                    let reply = replies
                        .pop_front()
                        .expect("one bridge request per public operation");
                    assert_eq!(request["params"]["tabId"], renderer_id);
                    assert_eq!(request["params"]["mountNonce"], "fixture-mount");
                    assert_eq!(request["params"]["operation"], reply.operation);
                    assert_eq!(
                        request["params"]["expression"],
                        agistack_adapters_browser::facade::dom_expression(
                            reply.operation,
                            &reply.args
                        )
                        .unwrap()
                    );
                    observed.fetch_add(1, Ordering::SeqCst);
                    reply.result
                }
                other => panic!("unexpected value bridge method: {other}"),
            };
            let mut frame = json!({"jsonrpc":"2.0","id":request["id"]});
            match result {
                Ok(value) => frame["result"] = value,
                Err(message) => frame["error"] = json!({"code":-32000,"message":message}),
            }
            socket.send(Message::Text(frame.to_string())).await.unwrap();
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
    (worker, calls)
}

async fn execute(fixture: &FormalFixture, code: &str, round: u64) -> Value {
    let output = agent_access::scope(
        Some(fixture.authorization.clone()),
        call_identity::scope(
            &ToolPolicyContext {
                session_id: &fixture.conversation.id,
                round,
                tool: "cua_repl_js",
            },
            fixture.host.call_with_content(
                "cua_repl_js",
                &json!({"code":code,"timeout_ms":15000}).to_string(),
            ),
        ),
    )
    .await
    .unwrap();
    serde_json::from_str(&output.output_json).unwrap()
}

#[tokio::test]
async fn real_public_locator_values_survive_authenticated_mcp_bridge_and_node_rpc() {
    let fixture = FormalFixture::new().await;
    let receipt = r#"{"count":7,"side":"main"}"#;
    let element_info = json!([{
        "tagName":"pre", "role":null, "ariaName":null,
        "visibleText":receipt, "preview":"<pre id=\"receipt\">...</pre>",
        "testId":null, "boundingBox":{"x":0,"y":0,"width":100,"height":20},
        "selector":{"primary":"#receipt","candidates":["#receipt"]}
    }]);
    let mut rejected = locator("#rejected", "innerText", json!([]), Value::Null);
    rejected.result = Err("fixture frame authority rejected");
    let replies = vec![
        Reply {
            operation: "playwright.domSnapshot",
            args: json!([{"disableDiffing":true}]),
            result: Ok(json!("<main>typed receipt fixture</main>")),
        },
        locator("#receipt", "innerText", json!([]), json!(receipt)),
        locator("#receipt", "textContent", json!([]), json!(receipt)),
        locator("#boolean-text", "innerText", json!([]), json!("true")),
        locator("#items", "count", json!([]), json!(7)),
        locator("#hidden", "isVisible", json!([]), json!(false)),
        locator("#button", "isEnabled", json!([]), json!(true)),
        locator("#button", "getAttribute", json!(["missing"]), Value::Null),
        locator(
            "#items",
            "allTextContents",
            json!([]),
            json!(["null", "1", "true"]),
        ),
        Reply {
            operation: "playwright.elementInfo",
            args: json!([{"x":1,"y":1,"includeNonInteractable":true}]),
            result: Ok(element_info.clone()),
        },
        rejected,
    ];
    let expected_calls = replies.len();
    let (bridge, calls) = attach_value_bridge(&fixture, replies).await;
    let bind = format!(
        "var typedTab = await cua.getTab({}, {{browser:'mcpapps'}}); typedTab.id",
        json!(fixture.handle)
    );
    let pending = execute(&fixture, &bind, 2).await;
    assert_eq!(
        pending["error"], "repl_tool_permission_required",
        "{pending}"
    );
    assert_eq!(pending["tool_name"], "browser_write_operation");
    let mut decision = crate::local_runtime::tests::test_decision_context();
    decision.action.name = pending["tool_name"].as_str().unwrap().into();
    decision.target.kind = "repl_step".into();
    decision.target.id = pending["step_id"].as_str().unwrap().into();
    let permission = cua_repl::permission_for_request(
        &fixture.state.cua_repl,
        &fixture.conversation.id,
        Some(&fixture.run.id),
        Some(&fixture.conversation.id),
        HitlKind::Permission,
        Some(&decision),
    )
    .unwrap()
    .unwrap();
    fixture
        .state
        .run_once_tool_permissions
        .lock()
        .unwrap()
        .insert(permission);
    let bound = execute(&fixture, &bind, 3).await;
    assert_eq!(bound["ok"], true, "{bound}");
    let output = execute(
        &fixture,
        r#"
        var parsedReceipt = JSON.parse(await typedTab.playwright.locator('#receipt').innerText());
        var values = [await typedTab.playwright.locator('#receipt').textContent(),
            await typedTab.playwright.locator('#boolean-text').innerText(),
            await typedTab.playwright.locator('#items').count(),
            await typedTab.playwright.locator('#hidden').isVisible(),
            await typedTab.playwright.locator('#button').isEnabled(),
            await typedTab.playwright.locator('#button').getAttribute('missing'),
            await typedTab.playwright.locator('#items').allTextContents(),
            await typedTab.playwright.elementInfo({x:1,y:1,includeNonInteractable:true})];
        var failure;
        try { await typedTab.playwright.locator('#rejected').innerText(); }
        catch (error) { failure = {code:error.code, message:error.message}; }
        ({parsedReceipt, values, failure});
    "#,
        4,
    )
    .await;
    let counts = fixture.counts().await;
    let remaining_grants = fixture
        .state
        .run_once_tool_permissions
        .lock()
        .unwrap()
        .len();
    fixture
        .state
        .browser_bridge
        .lock()
        .unwrap()
        .take()
        .unwrap()
        .stop();
    bridge.abort();
    fixture.finish(None).await;
    assert_eq!(output["ok"], true, "{output}");
    assert_eq!(
        output["value"]["parsedReceipt"],
        json!({"count":7,"side":"main"})
    );
    assert_eq!(
        output["value"]["values"],
        json!([
            receipt,
            "true",
            7,
            false,
            true,
            null,
            ["null", "1", "true"],
            element_info
        ])
    );
    assert_eq!(output["value"]["failure"]["code"], "repl_operation_failed");
    assert!(output["value"]["failure"]["message"]
        .as_str()
        .unwrap()
        .contains("fixture frame authority rejected"));
    assert_eq!(calls.load(Ordering::SeqCst), expected_calls);
    assert_eq!(remaining_grants, 0);
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}
