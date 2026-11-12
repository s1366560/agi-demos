//! Real downloads and native file chooser delivery, including an out-of-process frame.
use agistack_adapters_browser::{facade, BridgeWsClient, BrowserToolHost};
use agistack_core::ports::ToolHost;
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{json, Value};
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::{path::Path, process::Stdio, sync::Arc, time::Duration};
use tokio::io::{AsyncBufReadExt, BufReader};

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
async fn call(
    host: &BrowserToolHost<BridgeWsClient>,
    root: &Path,
    operation: &str,
    args: Value,
) -> Value {
    let input = json!({"browserId":"chrome","tabId":"1","operation":operation,"args":args,
        "_run_id":"artifacts-test","_artifact_root":root,"_authorized_file_roots":[root],"_blocked_file_roots":[]});
    let output = tokio::time::timeout(
        Duration::from_secs(15),
        host.call(
            facade::operation_effect(&input).unwrap().tool(),
            &input.to_string(),
        ),
    )
    .await
    .unwrap()
    .unwrap();
    serde_json::from_str(&output).unwrap()
}
#[tokio::test]
#[ignore = "requires Node and the desktop Playwright Chromium installation"]
async fn real_download_and_cross_origin_file_chooser_use_scoped_files() {
    let script = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../packages/cua-repl/tests/chromium-bridge.mjs");
    let mut command = tokio::process::Command::new("node");
    command
        .arg(script)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    #[cfg(unix)]
    command.as_std_mut().process_group(0);
    let mut child = command.spawn().unwrap();
    let _guard = FixtureGuard(child.id().unwrap());
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    let ready: Value = serde_json::from_str(
        &tokio::time::timeout(Duration::from_secs(15), lines.next_line())
            .await
            .unwrap()
            .unwrap()
            .unwrap(),
    )
    .unwrap();
    let endpoint = BridgeWsClient::connect(ready["endpoint"].as_str().unwrap(), "test-only")
        .await
        .unwrap();
    let host = Arc::new(BrowserToolHost::new(endpoint));
    struct Files(std::path::PathBuf);
    impl Drop for Files {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    let files = Files(std::env::temp_dir().join(format!(
            "memstack-artifacts-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        )));
    std::fs::create_dir(&files.0).unwrap();
    let root = files.0.canonicalize().unwrap();
    let upload = root.join("upload-fixture.txt");
    std::fs::write(&upload, "upload fixture").unwrap();
    call(&host, &root, "tab.claim", json!([])).await;
    let origin = ready["url"].as_str().unwrap().trim_end_matches('/');
    call(
        &host,
        &root,
        "tab.goto",
        json!([format!("{origin}/files-frame")]),
    )
    .await;
    let field = json!([{"kind":"frameLocator","args":["#foreign"]},{"kind":"getByLabel","args":["Upload",{"exact":true}]}]);
    // Resolve the iframe first so its live CDP session is included in interception.
    call(&host,&root,"playwright.locator",json!([[{"kind":"frameLocator","args":["#foreign"]},{"kind":"locator","args":["input"]}],"count",[]])).await;
    let (chooser, _) = tokio::join!(
        call(
            &host,
            &root,
            "playwright.waitForEvent",
            json!(["filechooser", {"timeoutMs":10000}])
        ),
        call(
            &host,
            &root,
            "playwright.locator",
            json!([field, "click", []])
        ),
    );
    call(
        &host,
        &root,
        "filechooser.setFiles",
        json!([chooser["id"], [upload]]),
    )
    .await;
    assert_eq!(call(&host,&root,"playwright.locator",json!([[{"kind":"frameLocator","args":["#foreign"]},{"kind":"locator","args":["output"]}],"innerText",[]])).await,"upload-fixture.txt");
    let (download, _) = tokio::join!(
        call(
            &host,
            &root,
            "playwright.waitForEvent",
            json!(["download", {"timeoutMs":10000}])
        ),
        call(
            &host,
            &root,
            "playwright.locator",
            json!([[{"kind":"getByRole","args":["link",{"name":"Download","exact":true}]}],"click",[]])
        ),
    );
    let path = call(&host, &root, "download.path", json!([download["id"]])).await;
    let path = Path::new(path.as_str().unwrap());
    assert!(path.starts_with(&root));
    assert_eq!(std::fs::read_to_string(path).unwrap(), "download fixture\n");
    call(&host, &root, "tab.goto", json!([format!("{origin}/media")])).await;
    let media = call(&host,&root,"playwright.locator",json!([[{"kind":"getByRole","args":["link",{"name":"Media file","exact":true}]}],"downloadMedia",[]])).await;
    assert_eq!(
        std::fs::read_to_string(media.as_str().unwrap()).unwrap(),
        "media fixture\n"
    );
    let inline = call(&host,&root,"playwright.locator",json!([[{"kind":"getByRole","args":["img",{"name":"Inline media","exact":true}]}],"downloadMedia",[]])).await;
    assert!(std::fs::read(inline.as_str().unwrap())
        .unwrap()
        .starts_with(b"\x89PNG"));
    call(&host, &root, "playwright.domSnapshot", json!([])).await;
    assert_eq!(
        call(
            &host,
            &root,
            "dom_cua.downloadMedia",
            json!([{"node_id":"0"}])
        )
        .await,
        Value::Null
    );
    let point = call(&host,&root,"playwright.locator",json!([[{"kind":"getByRole","args":["link",{"name":"Media file","exact":true}]}],"evaluate",[{"function":"element => { const r = element.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }"}]])).await;
    assert_eq!(
        call(&host, &root, "cua.downloadMedia", json!([point])).await,
        Value::Null
    );
    let screenshot = call(&host, &root, "playwright.elementScreenshot", json!([point])).await;
    assert_eq!(screenshot["mimeType"], "image/png");
    let pixels = image::load_from_memory(
        &STANDARD
            .decode(screenshot["dataBase64"].as_str().unwrap())
            .unwrap(),
    )
    .unwrap()
    .into_rgba8();
    assert!(pixels.pixels().any(|pixel| pixel.0 == [255, 40, 40, 255]));
    assert!(pixels.pixels().any(|pixel| pixel.0 == [0, 110, 255, 255]));
    let _ = tokio::process::Command::new("kill")
        .arg("-TERM")
        .arg(child.id().unwrap().to_string())
        .status()
        .await;
    let _ = tokio::time::timeout(Duration::from_secs(5), child.wait()).await;
}
