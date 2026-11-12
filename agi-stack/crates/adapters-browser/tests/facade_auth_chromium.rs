//! Secure browser handoff exercised through real Chromium, with non-secret fixture values.
use agistack_adapters_browser::{facade, BridgeWsClient, BrowserToolHost};
use agistack_core::ports::ToolHost;
use serde_json::{json, Value};
use std::collections::BTreeMap;
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, BufReader};

struct FixtureGuard(u32);
impl Drop for FixtureGuard {
    fn drop(&mut self) {
        #[cfg(unix)]
        let _ = std::process::Command::new("/bin/kill")
            .args(["-TERM", "--", &format!("-{}", self.0)])
            .status();
    }
}

async fn call(
    host: &BrowserToolHost<BridgeWsClient>,
    operation: &str,
    args: Value,
) -> Result<Value, String> {
    let input = json!({"browserId":"chrome","tabId":"1","operation":operation,"args":args,"_run_id":"auth-chromium-test"});
    let output = tokio::time::timeout(
        std::time::Duration::from_secs(15),
        host.call(
            facade::operation_effect(&input).unwrap().tool(),
            &input.to_string(),
        ),
    )
    .await
    .map_err(|_| "timed out".to_owned())?
    .map_err(|error| error.to_string())?;
    serde_json::from_str(&output).map_err(|error| error.to_string())
}

#[tokio::test]
#[ignore = "requires Node and the desktop Playwright Chromium installation"]
async fn credentials_are_pinned_filled_submitted_and_protected() {
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
    let origin = ready["url"].as_str().unwrap().trim_end_matches('/');
    call(&host, "tab.claim", json!([])).await.unwrap();
    call(&host, "tab.goto", json!([format!("{origin}/auth")]))
        .await
        .unwrap();
    let qr = host
        .prepare_browser_auth(
            "chrome",
            1,
            "qr-fixture",
            &json!({"origin":origin,"fields":[],"qr_code":true}),
        )
        .await
        .unwrap();
    let image = host.browser_auth_qr_image(&qr).await.unwrap();
    assert!(image.starts_with("data:image/png;base64,iVBOR"));
    assert!(call(&host, "tab.screenshot", json!([]))
        .await
        .unwrap_err()
        .contains("browser_auth_protected"));
    assert_eq!(
        host.submit_browser_auth(&qr, None, &BTreeMap::new())
            .await
            .unwrap(),
        json!({"status":"submitted"})
    );
    host.finish_browser_auth(&qr, false).await;
    drop(qr);
    let request = json!({"origin":origin,"fields":[{"id":"password","label":"Password","type":"password","autocomplete":"current-password","required":true,"selector":{"steps":[{"kind":"locator","args":["input[type=password]"]}]}}],"submit":{"action":"click","selector":{"steps":[{"kind":"locator","args":["button[type=submit]"]}]}}});
    let prepared = host
        .prepare_browser_auth("chrome", 1, "auth-fixture", &request)
        .await
        .unwrap();
    assert!(call(
        &host,
        "playwright.evaluate",
        json!(["document.querySelector('input').value"])
    )
    .await
    .unwrap_err()
    .contains("browser_auth_protected"));
    let result = host
        .submit_browser_auth(
            &prepared,
            None,
            &BTreeMap::from([("password".into(), "fixture-only-nonsecret".into())]),
        )
        .await
        .unwrap();
    assert_eq!(result["status"], "submitted");
    assert!(!result.to_string().contains("fixture-only-nonsecret"));
    host.finish_browser_auth(&prepared, false).await;
    drop(prepared);
    assert!(call(
        &host,
        "playwright.evaluate",
        json!(["document.body.innerText"])
    )
    .await
    .is_err());
    call(
        &host,
        "tab.goto",
        json!([format!("{origin}/auth-finished")]),
    )
    .await
    .unwrap();
    assert_eq!(call(&host,"playwright.locator",json!([[{"kind":"locator","args":["[data-auth-result]"]}],"getAttribute",["data-auth-result"]])).await.unwrap(),"complete");
    call(&host, "tab.goto", json!([format!("{origin}/auth")]))
        .await
        .unwrap();
    let abandoned = host
        .prepare_browser_auth("chrome", 1, "abandoned-fixture", &request)
        .await
        .unwrap();
    drop(abandoned);
    assert!(call(&host, "playwright.domSnapshot", json!([]))
        .await
        .is_ok());
    let _ = tokio::process::Command::new("kill")
        .arg("-TERM")
        .arg(child.id().unwrap().to_string())
        .status()
        .await;
    let _ = tokio::time::timeout(std::time::Duration::from_secs(5), child.wait()).await;
}
