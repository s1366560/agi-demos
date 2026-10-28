//! Callbacks queued by an old iframe must not acquire a replacement mount's authority.
use super::*;

#[tokio::test]
async fn queued_renderer_callbacks_reject_old_mount_before_any_stdio_dispatch() {
    let fixture = Fixture::new().await;
    let tab = fixture.render("render_main").await;
    fixture.attach(&tab).await;
    let old_nonce = fixture.state.mcp_app_automation.tabs.lock().unwrap()[&tab]
        .mount_nonce
        .clone()
        .unwrap();
    let args = json!({"operation_id":"queued-old-frame"});
    let operations = [
        (
            "tools/call",
            json!({"name":"increment_main","arguments":args}),
        ),
        ("resources/list", json!({})),
        ("resources/templates/list", json!({})),
        ("resources/read", json!({"uri":"ui://callback/main.html"})),
        ("prompts/list", json!({})),
        ("prompts/get", json!({"name":"describe"})),
    ];
    // Capture the wire requests before cleanup; dispatch them only after remount.
    let queued: Vec<Value> = operations
        .iter()
        .map(|(operation, arguments)| {
            json!({
                "tabId":tab,"mountNonce":old_nonce,"operation":operation,"arguments":arguments,
            })
        })
        .collect();
    fixture
        .state
        .mcp_app_automation
        .cancel_mount(&tab, &old_nonce)
        .unwrap();
    fixture.attach(&tab).await;
    let new_nonce = fixture.state.mcp_app_automation.tabs.lock().unwrap()[&tab]
        .mount_nonce
        .clone()
        .unwrap();
    assert_ne!(old_nonce, new_nonce);
    fixture.grant("increment_main", args);
    let before = payload(&fixture.model_call("inspect_counts").await)["dispatches"].clone();
    let mut results = vec![];
    for mut request in queued {
        // An App-supplied nested field cannot override the host's captured nonce.
        request["arguments"]["mountNonce"] = json!(new_nonce);
        let mut missing = request.clone();
        missing.as_object_mut().unwrap().remove("mountNonce");
        results.push(
            fixture
                .state
                .mcp_app_automation
                .renderer_operation(&fixture.state, missing)
                .await,
        );
        results.push(
            fixture
                .state
                .mcp_app_automation
                .renderer_operation(&fixture.state, request)
                .await,
        );
    }
    let after = payload(&fixture.model_call("inspect_counts").await)["dispatches"].clone();
    let counts = fixture.counts().await;
    drop(fixture);
    assert!(
        results.iter().all(Result::is_err),
        "old callback results: {results:?}"
    );
    assert_eq!(results.len(), 12);
    assert_eq!(
        before, after,
        "expired callbacks must not reach the real MCP server"
    );
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}
