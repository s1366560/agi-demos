//! Wait for browser-observed load state using the current document identity.
use std::time::Duration;

use agistack_core::ports::CoreResult;
use serde_json::{Value, json};

use crate::host::{Backend, BridgeEndpoint, BrowserToolHost, tool_err};

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub(crate) async fn facade_wait(
        &self,
        backend: Backend,
        tab: u64,
        operation: &str,
        args: &[Value],
    ) -> CoreResult<Value> {
        let options = if operation == "playwright.waitForLoadState" {
            args.first()
        } else {
            args.get(1)
        };
        let state = options
            .and_then(|options| {
                options.get(if operation == "playwright.waitForLoadState" {
                    "state"
                } else {
                    "waitUntil"
                })
            })
            .and_then(Value::as_str)
            .unwrap_or("load");
        if !matches!(
            state,
            "load" | "domcontentloaded" | "networkidle" | "commit"
        ) {
            return Err(tool_err("unsupported page load state"));
        }
        let expected_url = if operation == "playwright.waitForURL" {
            Some(
                args.first()
                    .and_then(Value::as_str)
                    .ok_or_else(|| tool_err("waitForURL requires a URL"))?,
            )
        } else {
            None
        };
        let timeout = options
            .and_then(|options| options.get("timeoutMs"))
            .and_then(Value::as_u64)
            .unwrap_or(5000)
            .clamp(1, 30000);
        self.ensure_page_enabled(backend, tab).await?;
        if state == "networkidle" {
            self.execute_cdp(
                backend,
                tab,
                "Page.setLifecycleEventsEnabled",
                json!({"enabled":true}),
            )
            .await?;
        }
        let deadline = tokio::time::Instant::now() + Duration::from_millis(timeout);
        loop {
            let page = self
                .facade_evaluate(
                    backend,
                    tab,
                    "({url:location.href,state:document.readyState})".into(),
                )
                .await?;
            let url_matches = expected_url.is_none_or(|url| page["url"] == url);
            let loaded = match state {
                "commit" => true,
                "domcontentloaded" => page["state"] == "interactive" || page["state"] == "complete",
                "load" => page["state"] == "complete",
                _ => {
                    let tree = self
                        .execute_cdp(backend, tab, "Page.getFrameTree", json!({}))
                        .await?;
                    let frame = &tree["frameTree"]["frame"];
                    self.state
                        .facade_events
                        .lock()
                        .map_err(|_| tool_err("browser event buffer unavailable"))?
                        .get(&(backend, tab))
                        .is_some_and(|buffer| {
                            buffer.events.iter().any(|event| {
                                event["method"] == "Page.lifecycleEvent"
                                    && event["params"]["frameId"] == frame["id"]
                                    && event["params"]["loaderId"] == frame["loaderId"]
                                    && event["params"]["name"] == "networkIdle"
                            })
                        })
                }
            };
            if url_matches && loaded {
                return Ok(Value::Null);
            }
            if tokio::time::Instant::now() >= deadline {
                return Err(tool_err("browser wait timed out"));
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    }
}
