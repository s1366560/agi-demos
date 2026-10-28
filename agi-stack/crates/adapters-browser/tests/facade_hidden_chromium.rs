//! Opt in with AGISTACK_NATIVE_CHROMIUM=/path/to/signed/browser executable.
//! Uses a raw launch and production extension; no Playwright page attachment.
use agistack_adapters_browser::protocol::BridgeNotification;
use agistack_adapters_browser::{BridgeEndpoint, BridgeWsClient, BrowserToolHost, facade};
use agistack_core::ports::{CoreResult, ToolHost};
use async_trait::async_trait;
use serde_json::{Value, json};
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::{process::Stdio, sync::Arc, time::Duration};
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    sync::broadcast,
};

struct FixtureGuard(u32);
impl Drop for FixtureGuard {
    fn drop(&mut self) {
        #[cfg(unix)]
        let _ = std::process::Command::new("/bin/kill")
            .args(["-TERM", "--", &format!("-{}", self.0)])
            .stderr(Stdio::null())
            .status();
    }
}
struct Endpoint(Arc<BridgeWsClient>);
#[async_trait]
impl BridgeEndpoint for Endpoint {
    async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        self.0.request(method, params).await
    }
    async fn request_on(&self, _backend: &str, method: &str, params: Value) -> CoreResult<Value> {
        self.0.request(method, params).await
    }
    fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification> {
        self.0.subscribe_notifications()
    }
}
async fn call(host: &BrowserToolHost<Endpoint>, operation: &str, args: Value) -> CoreResult<Value> {
    let family =
        std::env::var("AGISTACK_NATIVE_BROWSER_FAMILY").unwrap_or_else(|_| "chrome".into());
    let input = json!({"browserId":family,"tabId":"1","operation":operation,"args":args,"_run_id":"hidden-native-test"});
    let result = tokio::time::timeout(
        Duration::from_secs(15),
        host.call(facade::operation_effect(&input)?.tool(), &input.to_string()),
    )
    .await
    .expect("facade request timed out")?;
    Ok(serde_json::from_str(&result).unwrap())
}
async fn evaluate(host: &BrowserToolHost<Endpoint>, function: &str) -> Value {
    call(host, "playwright.evaluate", json!([{"function":function}]))
        .await
        .unwrap()
}
fn focus_trace(state: &Value) -> Vec<bool> {
    state["trace"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|call| call["method"] == "Emulation.setFocusEmulationEnabled")
        .map(|call| call["params"]["enabled"].as_bool().unwrap())
        .collect()
}
fn mouse_trace(state: &Value) -> Vec<String> {
    state["trace"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|call| call["method"] == "Input.dispatchMouseEvent")
        .map(|call| call["params"]["type"].as_str().unwrap().to_string())
        .collect()
}
fn assert_presentation_unchanged(before: &Value, after: &Value) {
    for field in ["active", "targetActive", "window", "foreground"] {
        assert_eq!(before[field], after[field], "presentation changed: {field}");
    }
}

#[tokio::test]
#[ignore = "requires AGISTACK_NATIVE_CHROMIUM and production browser-extension Node dependencies"]
async fn hidden_tab_click_restores_state_and_preserves_explicit_emulation() {
    assert!(std::env::var_os("AGISTACK_NATIVE_CHROMIUM").is_some());
    let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/hidden-chromium-bridge.mjs");
    let mut command = tokio::process::Command::new("node");
    command
        .arg(script)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .kill_on_drop(true);
    #[cfg(unix)]
    command.as_std_mut().process_group(0);
    let mut child = command.spawn().unwrap();
    let _guard = FixtureGuard(child.id().unwrap());
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    let ready = tokio::time::timeout(Duration::from_secs(20), lines.next_line())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    let ready: Value = serde_json::from_str(&ready).unwrap();
    eprintln!("native browser: {}", ready["version"]["product"]);
    let endpoint = Arc::new(
        BridgeWsClient::connect(ready["endpoint"].as_str().unwrap(), "test-only")
            .await
            .unwrap(),
    );
    let host = Arc::new(BrowserToolHost::new(Endpoint(endpoint.clone())));
    call(&host, "tab.claim", json!([])).await.unwrap();
    let before = endpoint.request("fixtureState", json!({})).await.unwrap();
    assert_eq!(before["window"]["state"], "minimized");
    assert_eq!(before["targetActive"], false);
    assert_eq!(
        evaluate(&host, "() => document.visibilityState").await,
        "hidden"
    );
    let input = json!([{"kind":"getByRole","args":["textbox",{"name":"Account","exact":true}]}]);
    let save = json!([{"kind":"getByRole","args":["button",{"name":"Save","exact":true}]}]);
    call(
        &host,
        "playwright.locator",
        json!([input, "fill", ["hidden-native-rust"]]),
    )
    .await
    .unwrap();
    call(&host, "playwright.locator", json!([save, "click", []]))
        .await
        .unwrap();
    assert_eq!(
        evaluate(&host, "() => document.querySelector('output').textContent").await,
        "hidden-native-rust"
    );
    assert_eq!(
        evaluate(&host, "() => JSON.parse(document.body.dataset.inputEvents)").await,
        json!([
            {"type":"pointerdown","trusted":true},{"type":"pointerup","trusted":true},{"type":"click","trusted":true}
        ])
    );
    assert_eq!(
        evaluate(&host, "() => document.visibilityState").await,
        "hidden"
    );
    let after = endpoint.request("fixtureState", json!({})).await.unwrap();
    assert_eq!(focus_trace(&after), [true, false]);
    assert_eq!(
        mouse_trace(&after),
        ["mouseMoved", "mousePressed", "mouseReleased"]
    );
    assert_presentation_unchanged(&before, &after);

    // Locator failure restores the renderer without issuing input packets.
    let missing = json!([{"kind":"getByRole","args":["button",{"name":"Missing","exact":true}]}]);
    assert!(
        call(&host, "playwright.locator", json!([missing, "click", []]))
            .await
            .is_err()
    );
    let failed = endpoint.request("fixtureState", json!({})).await.unwrap();
    assert_eq!(focus_trace(&failed), [true, false, true, false]);
    assert_eq!(mouse_trace(&failed), mouse_trace(&after));
    assert_eq!(
        evaluate(&host, "() => document.visibilityState").await,
        "hidden"
    );

    // A full-CDP caller's existing emulation remains enabled across our click.
    call(
        &host,
        "capability.cdp.send",
        json!(["Emulation.setFocusEmulationEnabled",{"enabled":true}]),
    )
    .await
    .unwrap();
    call(&host, "playwright.locator", json!([save, "click", []]))
        .await
        .unwrap();
    let preserved = endpoint.request("fixtureState", json!({})).await.unwrap();
    assert_eq!(focus_trace(&preserved), [true, false, true, false, true]);
    assert_eq!(
        evaluate(&host, "() => document.visibilityState").await,
        "visible"
    );
    assert_presentation_unchanged(&before, &preserved);
    call(
        &host,
        "capability.cdp.send",
        json!(["Emulation.setFocusEmulationEnabled",{"enabled":false}]),
    )
    .await
    .unwrap();

    // Cancel after the real down packet. Cleanup releases once before restoring.
    let task_host = host.clone();
    let task = tokio::spawn(async move {
        call(
            &task_host,
            "cua.click",
            json!([{"x":5,"y":5,"duration_ms":30000}]),
        )
        .await
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let state = endpoint.request("fixtureState", json!({})).await.unwrap();
            if mouse_trace(&state)
                .last()
                .is_some_and(|event| event == "mousePressed")
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .unwrap();
    task.abort();
    let _ = task.await;
    let cancelled = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let state = endpoint.request("fixtureState", json!({})).await.unwrap();
            if focus_trace(&state).last() == Some(&false) {
                break state;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .unwrap();
    let mouse = mouse_trace(&cancelled);
    assert_eq!(&mouse[mouse.len() - 2..], ["mousePressed", "mouseReleased"]);
    assert_eq!(
        mouse
            .iter()
            .filter(|event| *event == "mousePressed")
            .count(),
        3
    );
    assert_eq!(
        evaluate(&host, "() => document.visibilityState").await,
        "hidden"
    );
    assert_presentation_unchanged(&before, &cancelled);
    eprintln!(
        "native hidden click, failure, existing emulation, cancellation and presentation checks passed"
    );
    let _ = tokio::process::Command::new("kill")
        .args(["-TERM", &child.id().unwrap().to_string()])
        .status()
        .await;
    tokio::time::timeout(Duration::from_secs(10), child.wait())
        .await
        .unwrap()
        .unwrap();
}
