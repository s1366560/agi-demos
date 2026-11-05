//! Real Chromium exercises the provider through the production browser host.
use super::*;
use crate::local_runtime::browser_bridge::{BrowserBridgeConfig, BrowserBridgeRuntime};
use agistack_core::ports::ToolHost;
use axum::{response::Html, routing::get, Router};
use serde_json::{json, Value};
use std::{
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Arc,
    time::Duration,
};

struct Chromium {
    child: Child,
    root: PathBuf,
}
impl Drop for Chromium {
    fn drop(&mut self) {
        #[cfg(unix)]
        // SAFETY: this child was started in its own process group; no shared process is selected.
        unsafe {
            libc::kill(-(self.child.id() as i32), libc::SIGKILL);
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

async fn browser() -> (Chromium, String) {
    let root = std::env::temp_dir().join(format!("memstack-cdp-chromium-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir(&root).unwrap();
    let executable = std::env::var("AGISTACK_NATIVE_CHROMIUM")
        .unwrap_or_else(|_| "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome".into());
    let mut command = Command::new(executable);
    command
        .args([
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            "--use-mock-keychain",
            "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
            "--site-per-process",
            "--no-proxy-server",
            "--host-resolver-rules=MAP *.test 127.0.0.1",
        ])
        .arg(format!("--user-data-dir={}", root.display()))
        .arg("about:blank")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let child = command
        .spawn()
        .expect("set AGISTACK_NATIVE_CHROMIUM to an installed Chromium executable");
    let owned = Chromium { child, root };
    let port = tokio::time::timeout(Duration::from_secs(15), async {
        loop {
            if let Ok(value) =
                tokio::fs::read_to_string(owned.root.join("DevToolsActivePort")).await
            {
                if let Some(port) = value
                    .lines()
                    .next()
                    .and_then(|line| line.parse::<u16>().ok())
                {
                    return port;
                }
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    })
    .await
    .expect("Chromium did not expose its owned debugging endpoint");
    (owned, format!("http://localhost:{port}"))
}

async fn call(
    host: &dyn ToolHost,
    operation: &str,
    browser: &str,
    tab: Option<u64>,
    args: Value,
) -> Value {
    let mut input = json!({"operation":operation,"browserId":browser,"args":args,"_run_id":"cdp-chromium-test"});
    if let Some(tab) = tab {
        input["tabId"] = json!(tab);
    }
    let tool = agistack_adapters_browser::facade::operation_effect(&input)
        .unwrap()
        .tool();
    serde_json::from_str(&host.call(tool, &input.to_string()).await.unwrap()).unwrap()
}

fn selector(kind: &str, args: Value) -> Value {
    json!({"kind":kind,"args":args})
}

#[tokio::test]
#[ignore = "requires an installed Chromium; run explicitly for CDP native acceptance"]
async fn real_chromium_cdp_dom_input_oopif_and_disconnect() {
    let (mut chromium, endpoint) = browser().await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let app = Router::new().route("/",get(move || async move { Html(format!("<label>Name<input></label><button onclick=\"document.querySelector('output').textContent=document.querySelector('input').value\">Save</button><output>empty</output><iframe id='foreign' src='http://a.test:{port}/frame'></iframe>")) }))
        .route("/frame",get(move || async move { Html(format!("<label>Frame name<input></label><button onclick=\"document.querySelector('output').textContent=document.querySelector('input').value\">Save frame</button><output>empty frame</output><iframe id='nested' src='http://b.test:{port}/nested'></iframe>")) }))
        .route("/nested",get(|| async { Html("<label>Nested name<input></label><button onclick=\"document.querySelector('output').textContent=document.querySelector('input').value\">Save nested</button><output>empty nested</output>") }));
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let provider_id = uuid::Uuid::new_v4().to_string();
    let runtime = BrowserBridgeRuntime::start_with_registry_path(
        &BrowserBridgeConfig {
            enabled: true,
            port: 0,
            cdp_endpoints: vec![CdpEndpointConfig {
                id: provider_id.clone(),
                name: "Owned Chromium".into(),
                endpoint,
                enabled: true,
            }],
            default_browser_id: format!("cdp:{provider_id}"),
            ..Default::default()
        },
        chromium.root.join("registry.json"),
        None,
    )
    .unwrap();
    let identity = tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if let Some(info) = runtime
                .browser_instances()
                .iter()
                .find(|info| info["family"] == "cdp")
            {
                return info["id"].as_str().unwrap().to_string();
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .unwrap();
    let host = runtime.browser_tool_host();
    let chosen: Value = serde_json::from_str(
        &host
            .call(
                "browser_read_operation",
                &json!({"operation":"browsers.resolve","args":[{}]}).to_string(),
            )
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(chosen["id"], identity);
    let tab = call(
        host.as_ref(),
        "tabs.new",
        &identity,
        None,
        json!([format!("http://root.test:{port}/")]),
    )
    .await["tabId"]
        .as_u64()
        .unwrap();
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            let snapshot = call(
                host.as_ref(),
                "playwright.domSnapshot",
                &identity,
                Some(tab),
                json!([]),
            )
            .await;
            if snapshot.to_string().contains("Name") {
                break;
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    })
    .await
    .unwrap();
    call(
        host.as_ref(),
        "playwright.locator",
        &identity,
        Some(tab),
        json!([
            [selector("getByLabel", json!(["Name",{"exact":true}]))],
            "fill",
            ["CDP value"]
        ]),
    )
    .await;
    call(
        host.as_ref(),
        "playwright.locator",
        &identity,
        Some(tab),
        json!([
            [selector(
                "getByRole",
                json!(["button",{"name":"Save","exact":true}])
            )],
            "click",
            []
        ]),
    )
    .await;
    let output = call(
        host.as_ref(),
        "playwright.locator",
        &identity,
        Some(tab),
        json!([[selector("locator", json!(["output"]))], "innerText", []]),
    )
    .await;
    assert_eq!(output, "CDP value");
    let frame = selector("frameLocator", json!(["#foreign"]));
    call(
        host.as_ref(),
        "playwright.locator",
        &identity,
        Some(tab),
        json!([
            [frame.clone(), selector("getByLabel", json!(["Frame name"]))],
            "fill",
            ["Frame CDP"]
        ]),
    )
    .await;
    call(
        host.as_ref(),
        "playwright.locator",
        &identity,
        Some(tab),
        json!([
            [
                frame.clone(),
                selector("getByRole", json!(["button",{"name":"Save frame"}]))
            ],
            "click",
            []
        ]),
    )
    .await;
    let frame_output = call(
        host.as_ref(),
        "playwright.locator",
        &identity,
        Some(tab),
        json!([
            [frame.clone(), selector("locator", json!(["output"]))],
            "innerText",
            []
        ]),
    )
    .await;
    assert_eq!(frame_output, "Frame CDP");
    let nested = selector("frameLocator", json!(["#nested"]));
    call(
        host.as_ref(),
        "playwright.locator",
        &identity,
        Some(tab),
        json!([
            [
                frame.clone(),
                nested.clone(),
                selector("getByLabel", json!(["Nested name"]))
            ],
            "fill",
            ["Nested CDP"]
        ]),
    )
    .await;
    call(
        host.as_ref(),
        "playwright.locator",
        &identity,
        Some(tab),
        json!([
            [
                frame.clone(),
                nested.clone(),
                selector("getByRole", json!(["button",{"name":"Save nested"}]))
            ],
            "click",
            []
        ]),
    )
    .await;
    let nested_output = call(
        host.as_ref(),
        "playwright.locator",
        &identity,
        Some(tab),
        json!([
            [frame, nested, selector("locator", json!(["output"]))],
            "innerText",
            []
        ]),
    )
    .await;
    assert_eq!(nested_output, "Nested CDP");
    let browser_caps = call(
        host.as_ref(),
        "capabilities.list",
        &identity,
        None,
        json!([]),
    )
    .await;
    assert!(!browser_caps
        .as_array()
        .unwrap()
        .iter()
        .any(|cap| cap == "management" || cap == "visibility"));
    let disposable = call(
        host.as_ref(),
        "tabs.new",
        &identity,
        None,
        json!(["about:blank"]),
    )
    .await["tabId"]
        .as_u64()
        .unwrap();
    call(
        host.as_ref(),
        "tab.close",
        &identity,
        Some(disposable),
        json!([]),
    )
    .await;
    let remaining = call(host.as_ref(), "tabs.list", &identity, None, json!([])).await;
    assert!(remaining["tabs"]
        .as_array()
        .unwrap()
        .iter()
        .all(|info| info["tabId"] != disposable));
    let pending = tokio::spawn({
        let host = Arc::clone(&host);
        let identity = identity.clone();
        async move {
            host.call("browser_cdp_operation",&json!({"operation":"playwright.evaluate","browserId":identity,"tabId":tab,"args":["() => new Promise(() => {})"]}).to_string()).await
        }
    });
    tokio::time::sleep(Duration::from_millis(100)).await;
    chromium.child.kill().unwrap();
    assert!(tokio::time::timeout(Duration::from_secs(3), pending)
        .await
        .unwrap()
        .unwrap()
        .is_err());
    tokio::time::timeout(Duration::from_secs(3), async {
        while !runtime.browser_instances().is_empty() {
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .unwrap();
    assert!(host
        .call(
            "browser_read_operation",
            &json!({"operation":"tabs.list","browserId":identity,"args":[]}).to_string()
        )
        .await
        .is_err());
    runtime.stop();
    server.abort();
}
