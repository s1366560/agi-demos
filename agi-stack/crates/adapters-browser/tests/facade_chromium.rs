//! Opt-in test executes the production Rust facade against real Chromium CDP.
use agistack_adapters_browser::{facade, BridgeWsClient, BrowserToolHost};
use agistack_core::ports::ToolHost;
use serde_json::{json, Value};
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, BufReader};

struct FixtureGuard(u32);
impl Drop for FixtureGuard {
    fn drop(&mut self) {
        // The fixture and Chromium share a dedicated process group.
        #[cfg(unix)]
        let _ = std::process::Command::new("/bin/kill")
            .args(["-TERM", "--", &format!("-{}", self.0)])
            .stderr(Stdio::null())
            .status();
    }
}

#[tokio::test]
#[ignore = "requires Node and the desktop Playwright Chromium installation"]
async fn facade_drives_real_dom_and_cross_origin_frame() {
    let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../packages/cua-repl/tests/chromium-bridge.mjs");
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
    let ready = tokio::time::timeout(std::time::Duration::from_secs(15), lines.next_line())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    let ready: Value = serde_json::from_str(&ready).unwrap();
    let endpoint = BridgeWsClient::connect(ready["endpoint"].as_str().unwrap(), "test-only")
        .await
        .unwrap();
    let host = BrowserToolHost::new(endpoint);
    async fn call(host: &BrowserToolHost<BridgeWsClient>, operation: &str, args: Value) -> Value {
        let input = json!({"browserId":"chrome","tabId":"1","operation":operation,"args":args,"_run_id":"chromium-test"});
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(15),
            host.call(
                facade::operation_effect(&input).unwrap().tool(),
                &input.to_string(),
            ),
        )
        .await
        .unwrap()
        .unwrap();
        serde_json::from_str(&result).unwrap()
    }
    call(&host, "tab.claim", json!([])).await;
    let input = json!([{"kind":"getByRole","args":["textbox",{"name":"Account","exact":true}]}]);
    call(
        &host,
        "playwright.locator",
        json!([input, "fill", ["native-rust"]]),
    )
    .await;
    call(&host,"playwright.evaluate",json!([{"function":"() => { const b=document.querySelector('button'); b.addEventListener('pointerdown', e => document.body.dataset.pointerTrusted=String(e.isTrusted)); b.addEventListener('contextmenu', e => { e.preventDefault(); document.body.dataset.contextShift=String(e.shiftKey); }); b.addEventListener('dblclick', e => document.body.dataset.doubleTrusted=String(e.isTrusted)); }"}])).await;
    let save = json!([{"kind":"getByRole","args":["button",{"name":"Save","exact":true}]}]);
    call(&host, "playwright.locator", json!([save, "click", []])).await;
    assert_eq!(
        call(
            &host,
            "playwright.evaluate",
            json!([{"function":"() => document.body.dataset.pointerTrusted"}])
        )
        .await,
        "true"
    );
    call(
        &host,
        "playwright.locator",
        json!([save,"click",[{"button":"right","modifiers":["Shift"]}]]),
    )
    .await;
    assert_eq!(
        call(
            &host,
            "playwright.evaluate",
            json!([{"function":"() => document.body.dataset.contextShift"}])
        )
        .await,
        "true"
    );
    call(&host, "playwright.locator", json!([save, "dblclick", []])).await;
    assert_eq!(
        call(
            &host,
            "playwright.evaluate",
            json!([{"function":"() => document.body.dataset.doubleTrusted"}])
        )
        .await,
        "true"
    );
    assert_eq!(
        call(
            &host,
            "playwright.locator",
            json!([[{"kind":"locator","args":["output"]}],"innerText",[]])
        )
        .await,
        "native-rust"
    );
    call(&host,"playwright.evaluate",json!([{"function":"() => { document.querySelector('input').addEventListener('keydown', () => { document.body.dataset.keys = String(Number(document.body.dataset.keys ?? 0) + 1); }); }"}])).await;
    call(
        &host,
        "playwright.locator",
        json!([input, "pressSequentially", ["+中"]]),
    )
    .await;
    assert_eq!(call(&host,"playwright.evaluate",json!([{"function":"() => ({value:document.querySelector('input').value,keys:document.body.dataset.keys})"}])).await,json!({"value":"native-rust+中","keys":"2"}));
    call(
        &host,
        "playwright.waitForLoadState",
        json!([{"state":"domcontentloaded","timeoutMs":2000}]),
    )
    .await;
    call(
        &host,
        "playwright.waitForLoadState",
        json!([{"state":"networkidle","timeoutMs":5000}]),
    )
    .await;
    call(
        &host,
        "playwright.waitForURL",
        json!([ready["url"],{"waitUntil":"load","timeoutMs":2000}]),
    )
    .await;
    let field = json!([{"kind":"frameLocator","args":["#foreign"]},{"kind":"getByRole","args":["textbox",{"name":"Frame value","exact":true}]}]);
    call(
        &host,
        "playwright.locator",
        json!([field, "fill", ["cross-origin-rust"]]),
    )
    .await;
    let button = json!([{"kind":"frameLocator","args":["#foreign"]},{"kind":"getByRole","args":["button",{"name":"Save frame","exact":true}]}]);
    call(&host, "playwright.locator", json!([button, "click", []])).await;
    let output =
        json!([{"kind":"frameLocator","args":["#foreign"]},{"kind":"locator","args":["output"]}]);
    assert_eq!(
        call(
            &host,
            "playwright.locator",
            json!([output, "innerText", []])
        )
        .await,
        "cross-origin-rust"
    );
    let _ = tokio::process::Command::new("kill")
        .arg("-TERM")
        .arg(child.id().unwrap().to_string())
        .status()
        .await;
    let _ = tokio::time::timeout(std::time::Duration::from_secs(5), child.wait()).await;
}
