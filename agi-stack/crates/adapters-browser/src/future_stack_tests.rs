use crate::host::Backend;
use crate::{facade, BridgeEndpoint, BrowserToolHost};
use agistack_core::ports::{CoreResult, ToolHost};
use async_trait::async_trait;
use serde_json::{json, Value};
use tokio::sync::broadcast;

struct Endpoint;
#[async_trait]
impl BridgeEndpoint for Endpoint {
    async fn request(&self, _method: &str, _params: Value) -> CoreResult<Value> {
        Ok(json!({"tabs":[{"tabId":1,"windowId":1,"url":"https://fixture.test/","active":false}]}))
    }
    fn subscribe_notifications(&self) -> broadcast::Receiver<crate::protocol::BridgeNotification> {
        broadcast::channel(1).1
    }
}

#[test]
fn public_browser_reads_fit_default_stack_with_dispatch_headroom() {
    // The smaller budget leaves room for the production authorization, MCP,
    // profiling, and runtime wrappers outside this adapter.
    for stack_bytes in [2 * 1024 * 1024, 256 * 1024] {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(1)
            .thread_stack_size(stack_bytes)
            .enable_all()
            .build()
            .unwrap();
        runtime.block_on(async {
            tokio::spawn(async {
                let host = BrowserToolHost::new(Endpoint);
                for input in [
                    json!({"operation":"browsers.list","args":[]}),
                    json!({"browserId":"chrome","operation":"tabs.list","args":[]}),
                    json!({"browserId":"chrome","tabId":"1","operation":"tab.url","args":[]}),
                ] {
                    let result = host
                        .call(facade::TOOL_READ, &input.to_string())
                        .await
                        .unwrap();
                    let _: Value = serde_json::from_str(&result).unwrap();
                }
            })
            .await
            .unwrap();
        });
    }
}

#[tokio::test]
async fn browser_dispatch_future_sizes_fit_default_worker_stack() {
    let host = BrowserToolHost::new(Endpoint);
    let input = json!({"operation":"browsers.list","args":[]});
    let args = vec![json!({"x":1,"y":1})];
    let input_json = input.to_string();
    let call = host.call(facade::TOOL_READ, &input_json);
    let sizes = [
        (
            "ToolHost::call",
            std::mem::size_of_val(call.as_ref().get_ref()),
        ),
        (
            "facade_operation",
            std::mem::size_of_val(&host.facade_operation(facade::TOOL_READ, &input)),
        ),
        (
            "facade_input",
            std::mem::size_of_val(&host.facade_input(Backend::Chrome, 1, "cua.click", &args)),
        ),
        (
            "facade_locator_click",
            std::mem::size_of_val(&host.facade_locator_click(Backend::Chrome, 1, &args)),
        ),
        (
            "backend_request",
            std::mem::size_of_val(&host.backend_request(Backend::Chrome, "getTabs", json!({}))),
        ),
        (
            "with_input_visibility",
            std::mem::size_of_val(
                &host.with_input_visibility(Backend::Chrome, 1, async { Ok(Value::Null) }),
            ),
        ),
        (
            "facade_artifact_operation",
            std::mem::size_of_val(&host.facade_artifact_operation(
                Backend::Chrome,
                1,
                "filechooser.setFiles",
                &args,
                &input,
            )),
        ),
        (
            "download_media",
            std::mem::size_of_val(&host.download_media(
                Backend::Chrome,
                1,
                "cua.downloadMedia",
                &args,
                &input,
            )),
        ),
        (
            "facade_content",
            std::mem::size_of_val(&host.facade_content(
                Backend::Chrome,
                1,
                "content.export",
                &args,
                &input,
            )),
        ),
        (
            "facade_frame_operation",
            std::mem::size_of_val(&host.facade_frame_operation(
                Backend::Chrome,
                1,
                "playwright.locator",
                &args,
            )),
        ),
        (
            "facade_wait",
            std::mem::size_of_val(&host.facade_wait(
                Backend::Chrome,
                1,
                "playwright.waitForURL",
                &args,
            )),
        ),
        (
            "element_screenshot",
            std::mem::size_of_val(&host.element_screenshot(Backend::Chrome, 1, &args, &input)),
        ),
        ("snapshot", std::mem::size_of_val(&host.snapshot(&input))),
        (
            "screenshot",
            std::mem::size_of_val(&host.screenshot(&input)),
        ),
    ];
    for (name, bytes) in sizes {
        eprintln!("{name}: {bytes} bytes");
    }
    assert!(
        sizes[0].1 <= 8 * 1024,
        "public browser dispatcher embeds oversized branch futures"
    );
}
