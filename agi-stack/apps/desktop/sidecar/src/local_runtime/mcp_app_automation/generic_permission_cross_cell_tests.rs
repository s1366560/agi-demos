//! Public tab objects persist across completed Node cells and ordinary HTTP approval.
use super::*;
use crate::local_runtime::browser_bridge::{self, BrowserBridgeConfig, BrowserBridgeRuntime};
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::{client::IntoClientRequest, Message};

/// Real authenticated bridge transport; only the iframe's DOM snapshot is scripted.
pub(super) async fn attach_dom_bridge(fixture: &FormalFixture) -> JoinHandle<()> {
    let path = fixture.root.join("bridge-registry.json");
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
    let state = fixture.state.clone();
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
                    let expected = state.mcp_app_automation.tabs.lock().unwrap()[&renderer_id]
                        .mount_nonce
                        .clone()
                        .unwrap();
                    assert_eq!(request["params"]["mountNonce"], expected);
                    assert_eq!(request["params"]["operation"], "playwright.domSnapshot");
                    json!("<main>callback fixture</main>")
                }
                method => panic!("unexpected bridge operation: {method}"),
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
    broker
}

#[tokio::test]
async fn formal_generic_approval_preserves_the_same_public_tab_variable_across_cells() {
    preserves_public_tab_across_cells(false).await;
}

#[tokio::test]
async fn formal_clarification_preserves_the_same_public_tab_and_dom_across_cells() {
    preserves_public_tab_across_cells(true).await;
}

async fn preserves_public_tab_across_cells(is_clarification: bool) {
    let fixture = FormalFixture::new().await;
    let broker = attach_dom_bridge(&fixture).await;
    let code = format!(
        "var genericTab = await cua.getTab({}, {{browser:'mcpapps'}}); genericTab.id",
        json!(fixture.handle)
    );
    let initial = agent_access::scope(
        Some(fixture.authorization.clone()),
        call_identity::scope(
            &ToolPolicyContext {
                session_id: &fixture.conversation.id,
                round: 2,
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
    let pending: Value = serde_json::from_str(&initial.output_json).unwrap();
    assert_eq!(
        pending["error"], "repl_tool_permission_required",
        "{pending}"
    );
    // Binding a tab is a write. Setup grants only the actual pending claim's
    // host-issued step/input key; the later generic approval inherits no grant.
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
    let initial = agent_access::scope(
        Some(fixture.authorization.clone()),
        call_identity::scope(
            &ToolPolicyContext {
                session_id: &fixture.conversation.id,
                round: 3,
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
    let initial: Value = serde_json::from_str(&initial.output_json).unwrap();
    assert_eq!(initial["ok"], true, "{initial}");
    assert_eq!(initial["value"], fixture.handle);
    assert!(fixture
        .state
        .run_once_tool_permissions
        .lock()
        .unwrap()
        .is_empty());
    let response = if is_clarification {
        let request = super::super::clarification_tests::clarification(&fixture).await;
        super::super::clarification_tests::answer(&request, json!("The original App is mounted."))
    } else {
        command(&generic_permission(&fixture).await, true)
    };
    let llm = fixture.llm(Some(
        "[genericTab.id, await genericTab.title(), await genericTab.playwright.domSnapshot()]"
            .into(),
    ));
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        response,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    tokio::time::timeout(Duration::from_secs(15), llm.ready.notified())
        .await
        .unwrap();
    let transcript = llm.observed.lock().unwrap().clone();
    let output = transcript
        .iter()
        .filter_map(|content| serde_json::from_str::<Value>(content).ok())
        .find(|value| value.get("cell_id").is_some())
        .unwrap();
    let expected = json!([
        fixture.handle,
        "render_main",
        "<main>callback fixture</main>"
    ]);
    let counts = fixture.counts().await;
    fixture
        .state
        .browser_bridge
        .lock()
        .unwrap()
        .take()
        .unwrap()
        .stop();
    broker.abort();
    fixture.finish(Some(&llm)).await;
    assert_eq!(output["ok"], true, "{output}");
    assert_eq!(output["value"], expected, "{output}");
    assert_ne!(output["cell_id"], initial["cell_id"]);
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}
