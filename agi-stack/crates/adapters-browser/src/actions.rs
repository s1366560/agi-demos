//! M2 mutation tools: navigation, element actions, and tab leases.
//!
//! Seven tools are implemented here as methods on
//! [`BrowserToolHost`](crate::host::BrowserToolHost) (dispatch lives in
//! `host.rs`). They share three seams:
//!
//! - **Cached isolated world** — element refs (`e12` from `browser_snapshot`)
//!   resolve against the `window.__memstackSnapshotRefs` stash, which only
//!   survives because the host reuses one isolated world per tab frame
//!   ([`BrowserToolHost::world_context`]).
//! - **Virtual cursor** — `browser_click` awaits `moveMouse` before the real
//!   `Input.dispatchMouseEvent` sequence; all cursor errors are swallowed so
//!   the cursor can never block an action.
//! - **Tab leases** — `browser_new_tab` / `browser_claim_tab` /
//!   `browser_mark_tab` maintain a per-run lease registry; the run wrapper
//!   calls [`BrowserToolHost::turn_ended`] to ship the leases to the
//!   extension (`turnEnded`) and drop them locally.
//!
//! All tools are `ToolEffect::Mutate` (registration in the sidecar is a
//! separate workstream; the metadata in `host.rs` marks them "mutating").
//! Outputs are kept compact (fields clipped, no pretty-printing) and stay
//! well under the 2000-char budget.

use std::time::Duration;

use serde_json::{json, Value};
use tokio::sync::broadcast;

use agistack_core::ports::CoreResult;

use crate::host::{required_tab_id, tool_err, BridgeEndpoint, BrowserToolHost};
use crate::protocol::{
    BridgeNotification, LeaseOrigin, OnCdpEventParams, TabMark, METHOD_ASSIGN_TAB,
    METHOD_CREATE_TAB, METHOD_ENSURE_TAB_GROUP, NOTIFY_ON_CDP_EVENT,
};

/// Registered tool names (exact — the agent engine matches on these strings).
pub const TOOL_NAVIGATE: &str = "browser_navigate";
pub const TOOL_CLICK: &str = "browser_click";
pub const TOOL_TYPE: &str = "browser_type";
pub const TOOL_SCROLL: &str = "browser_scroll";
pub const TOOL_NEW_TAB: &str = "browser_new_tab";
pub const TOOL_CLAIM_TAB: &str = "browser_claim_tab";
pub const TOOL_MARK_TAB: &str = "browser_mark_tab";

/// Cap on waiting for `Page.loadEventFired` after `Page.navigate`.
const LOAD_EVENT_TIMEOUT: Duration = Duration::from_secs(15);
/// Clip for free-text output fields (url, title) so tool results stay far
/// below the 2000-char budget.
const MAX_FIELD_CHARS: usize = 500;
/// Tab-group title for agent-created tabs (one group per run).
const AGENT_GROUP_TITLE: &str = "MemStack Agent";
/// Group key used when the run wrapper did not inject `_run_id`.
const DEFAULT_GROUP_KEY: &str = "default";

/// Scroll the element into view and report its viewport rect (CSS px).
const SCROLL_INTO_VIEW_RECT_FN: &str = "function () {\
     this.scrollIntoView({ block: 'center' });\
     var r = this.getBoundingClientRect();\
     return { x: r.x, y: r.y, width: r.width, height: r.height };\
 }";
/// Focus the element.
const FOCUS_FN: &str = "function () { this.focus(); }";
/// Clear an input/textarea/contenteditable and notify the page.
const CLEAR_FN: &str = "function () {\
     if ('value' in this) { this.value = ''; }\
     else if (this.isContentEditable) { this.textContent = ''; }\
     this.dispatchEvent(new Event('input', { bubbles: true }));\
 }";

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    /// `browser_navigate {tabId, url} → {url, title}`.
    pub(crate) async fn navigate(&self, input: &Value) -> CoreResult<Value> {
        let tab_id = required_tab_id(input)?;
        let url = required_str(input, "url")?;
        validate_navigable_url(url)?;

        self.ensure_attached(tab_id).await?;
        self.ensure_page_enabled(tab_id).await?;
        // Subscribe *before* navigating so a fast load event cannot be missed.
        let mut load_events = self.endpoint.subscribe_notifications();
        self.execute_cdp(tab_id, "Page.navigate", json!({ "url": url }))
            .await?;
        self.wait_for_load_event(tab_id, &mut load_events).await;

        let (_frame_id, context_id) = self.world_context(tab_id).await?;
        let cdp = self
            .execute_cdp(
                tab_id,
                "Runtime.evaluate",
                json!({
                    "expression": "document.title",
                    "returnByValue": true,
                    "contextId": context_id,
                }),
            )
            .await?;
        let title = cdp
            .pointer("/result/value")
            .and_then(Value::as_str)
            .unwrap_or_default();
        self.set_tab_url(tab_id, url);
        Ok(json!({
            "url": clip(url, MAX_FIELD_CHARS),
            "title": clip(title, MAX_FIELD_CHARS),
        }))
    }

    /// `browser_click {tabId, ref} → {clicked, x, y}`.
    pub(crate) async fn click(&self, input: &Value) -> CoreResult<Value> {
        let tab_id = required_tab_id(input)?;
        let ref_ = required_ref(input)?;
        let Some(object_id) = self.resolve_ref_object(tab_id, ref_).await? else {
            return Ok(stale_ref_output(ref_));
        };
        let (x, y) = self.element_center(tab_id, &object_id).await?;

        // Cursor first (errors swallowed inside), then the real click.
        self.move_mouse(tab_id, x, y, true).await;
        let sequence = [
            json!({ "type": "mouseMoved", "x": x, "y": y }),
            json!({ "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1 }),
            json!({ "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1 }),
        ];
        for params in sequence {
            self.execute_cdp(tab_id, "Input.dispatchMouseEvent", params)
                .await?;
        }
        Ok(json!({ "clicked": true, "x": x, "y": y }))
    }

    /// `browser_type {tabId, ref, text, clear?, pressEnter?} → {typed}`.
    pub(crate) async fn type_text(&self, input: &Value) -> CoreResult<Value> {
        let tab_id = required_tab_id(input)?;
        let ref_ = required_ref(input)?;
        let text = input
            .get("text")
            .and_then(Value::as_str)
            .ok_or_else(|| tool_err("missing or invalid 'text' (expected a string)"))?;
        let clear = input.get("clear").and_then(Value::as_bool).unwrap_or(false);
        let press_enter = input
            .get("pressEnter")
            .and_then(Value::as_bool)
            .unwrap_or(false);

        let Some(object_id) = self.resolve_ref_object(tab_id, ref_).await? else {
            return Ok(stale_ref_output(ref_));
        };
        self.call_on_element(tab_id, &object_id, FOCUS_FN).await?;
        if clear {
            self.call_on_element(tab_id, &object_id, CLEAR_FN).await?;
        }
        self.execute_cdp(tab_id, "Input.insertText", json!({ "text": text }))
            .await?;
        if press_enter {
            for event_type in ["rawKeyDown", "keyUp"] {
                self.execute_cdp(
                    tab_id,
                    "Input.dispatchKeyEvent",
                    json!({
                        "type": event_type,
                        "windowsVirtualKeyCode": 13,
                        "key": "Enter",
                        "code": "Enter",
                    }),
                )
                .await?;
            }
        }
        Ok(json!({ "typed": text.chars().count() }))
    }

    /// `browser_scroll {tabId, ref?, deltaY} → {scrolled: deltaY}`.
    pub(crate) async fn scroll(&self, input: &Value) -> CoreResult<Value> {
        let tab_id = required_tab_id(input)?;
        let delta_y = input
            .get("deltaY")
            .and_then(Value::as_f64)
            .ok_or_else(|| tool_err("missing or invalid 'deltaY' (expected a number)"))?;

        let (x, y) = match input.get("ref").and_then(Value::as_str) {
            Some(ref_) => {
                if !valid_ref(ref_) {
                    return Err(bad_ref_err(ref_));
                }
                match self.resolve_ref_object(tab_id, ref_).await? {
                    Some(object_id) => self.element_center(tab_id, &object_id).await?,
                    None => return Ok(stale_ref_output(ref_)),
                }
            }
            None => self.viewport_center(tab_id).await?,
        };
        self.execute_cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            json!({ "type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": delta_y }),
        )
        .await?;
        Ok(json!({ "scrolled": delta_y }))
    }

    /// `browser_new_tab {url?, activate?=false} → {tabId, groupId}`.
    pub(crate) async fn new_tab(&self, input: &Value) -> CoreResult<Value> {
        let url = input.get("url").and_then(Value::as_str);
        if let Some(url) = url {
            validate_navigable_url(url)?;
        }
        let activate = input
            .get("activate")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let run_id = run_id_of(input).unwrap_or(DEFAULT_GROUP_KEY);

        let mut params = json!({ "active": activate });
        if let Some(url) = url {
            params["url"] = json!(url);
        }
        let created = self.endpoint.request(METHOD_CREATE_TAB, params).await?;
        let tab_id = created
            .get("tabId")
            .and_then(Value::as_u64)
            .ok_or_else(|| tool_err("createTab returned no tabId"))?;

        let group = self
            .endpoint
            .request(
                METHOD_ENSURE_TAB_GROUP,
                json!({ "key": run_id, "title": AGENT_GROUP_TITLE }),
            )
            .await?;
        let group_id = group
            .get("groupId")
            .and_then(Value::as_u64)
            .ok_or_else(|| tool_err("ensureTabGroup returned no groupId"))?;
        self.endpoint
            .request(
                METHOD_ASSIGN_TAB,
                json!({ "tabId": tab_id, "groupId": group_id }),
            )
            .await?;

        self.record_lease(run_id, tab_id, LeaseOrigin::Agent);
        if let Some(url) = url {
            self.set_tab_url(tab_id, url);
        }
        Ok(json!({ "tabId": tab_id, "groupId": group_id }))
    }

    /// `browser_claim_tab {tabId} → {tabId}` — user-origin lease, no grouping.
    pub(crate) async fn claim_tab(&self, input: &Value) -> CoreResult<Value> {
        let tab_id = required_tab_id(input)?;
        let url = self.current_url(tab_id as i64).await?;
        if is_browser_internal_url(&url) {
            return Err(tool_err(format!(
                "refusing to claim browser-internal tab {tab_id} ({url})"
            )));
        }
        let run_id = run_id_of(input).unwrap_or(DEFAULT_GROUP_KEY);
        self.record_lease(run_id, tab_id, LeaseOrigin::User);
        Ok(json!({ "tabId": tab_id }))
    }

    /// `browser_mark_tab {tabId, mark} → {tabId, mark}`.
    pub(crate) async fn mark_tab(&self, input: &Value) -> CoreResult<Value> {
        let tab_id = required_tab_id(input)?;
        let mark = match required_str(input, "mark")? {
            "handoff" => TabMark::Handoff,
            "deliverable" => TabMark::Deliverable,
            other => {
                return Err(tool_err(format!(
                    "invalid 'mark': {other:?} (expected \"handoff\" or \"deliverable\")"
                )))
            }
        };
        if !self.mark_lease(run_id_of(input), tab_id, mark) {
            return Err(tool_err(format!(
                "no lease for tab {tab_id}; call browser_new_tab or browser_claim_tab first"
            )));
        }
        Ok(json!({ "tabId": tab_id, "mark": mark }))
    }

    /// Send `Page.enable` once per tab (load/navigation events).
    async fn ensure_page_enabled(&self, tab_id: u64) -> CoreResult<()> {
        if self.state.page_enabled.lock().unwrap().contains(&tab_id) {
            return Ok(());
        }
        self.execute_cdp(tab_id, "Page.enable", json!({})).await?;
        self.state.page_enabled.lock().unwrap().insert(tab_id);
        Ok(())
    }

    /// Wait for the tab's `Page.loadEventFired`, capped at
    /// [`LOAD_EVENT_TIMEOUT`]; a timeout is logged and treated as success
    /// (some navigations never fire a load event).
    async fn wait_for_load_event(
        &self,
        tab_id: u64,
        events: &mut broadcast::Receiver<BridgeNotification>,
    ) {
        let wait = async {
            loop {
                match events.recv().await {
                    Ok(notification) => {
                        if notification.method != NOTIFY_ON_CDP_EVENT {
                            continue;
                        }
                        let Ok(event) =
                            serde_json::from_value::<OnCdpEventParams>(notification.params)
                        else {
                            continue;
                        };
                        if event.tab_id == tab_id && event.method == "Page.loadEventFired" {
                            return;
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(_)) => continue,
                    Err(broadcast::error::RecvError::Closed) => return,
                }
            }
        };
        if tokio::time::timeout(LOAD_EVENT_TIMEOUT, wait)
            .await
            .is_err()
        {
            tracing::debug!("load event wait timed out for tab {tab_id}; continuing anyway");
        }
    }

    /// Resolve a snapshot ref (`e12`) to a CDP `objectId` inside the cached
    /// isolated world. `Ok(None)` means the stash is gone or the WeakRef
    /// deref'd to null — the caller turns that into a `stale_ref` tool
    /// *result* (recoverable by re-snapshotting), not an exception.
    async fn resolve_ref_object(&self, tab_id: u64, ref_: &str) -> CoreResult<Option<String>> {
        let (_frame_id, context_id) = self.world_context(tab_id).await?;
        let ref_literal = serde_json::to_string(ref_).unwrap_or_else(|_| "\"\"".to_string());
        let expression = format!(
            "(function () {{\
                 var refs = window.__memstackSnapshotRefs;\
                 if (!refs) return null;\
                 var entry = refs.get({ref_literal});\
                 if (!entry) return null;\
                 var el = (typeof entry.deref === 'function') ? entry.deref() : entry;\
                 return el || null;\
             }})();"
        );
        let cdp = self
            .execute_cdp(
                tab_id,
                "Runtime.evaluate",
                json!({
                    "expression": expression,
                    "returnByValue": false,
                    "contextId": context_id,
                }),
            )
            .await?;
        if let Some(exception) = cdp.get("exceptionDetails") {
            let detail = exception
                .pointer("/exception/description")
                .or_else(|| exception.pointer("/text"))
                .and_then(Value::as_str)
                .unwrap_or("ref lookup raised");
            return Err(tool_err(format!("ref lookup failed for {ref_}: {detail}")));
        }
        Ok(cdp
            .pointer("/result/objectId")
            .and_then(Value::as_str)
            .map(str::to_string))
    }

    /// Run a `Runtime.callFunctionOn` against a resolved element object.
    async fn call_on_element(
        &self,
        tab_id: u64,
        object_id: &str,
        function_declaration: &str,
    ) -> CoreResult<Value> {
        let cdp = self
            .execute_cdp(
                tab_id,
                "Runtime.callFunctionOn",
                json!({
                    "objectId": object_id,
                    "functionDeclaration": function_declaration,
                    "returnByValue": true,
                }),
            )
            .await?;
        if let Some(exception) = cdp.get("exceptionDetails") {
            let detail = exception
                .pointer("/exception/description")
                .or_else(|| exception.pointer("/text"))
                .and_then(Value::as_str)
                .unwrap_or("element call raised");
            return Err(tool_err(format!("element call failed: {detail}")));
        }
        Ok(cdp)
    }

    /// Scroll the element into view and return its center point in viewport
    /// CSS px (the coordinate system of both `Input.*` and the cursor).
    async fn element_center(&self, tab_id: u64, object_id: &str) -> CoreResult<(f64, f64)> {
        let cdp = self
            .call_on_element(tab_id, object_id, SCROLL_INTO_VIEW_RECT_FN)
            .await?;
        let rect = cdp.pointer("/result/value").cloned().unwrap_or(Value::Null);
        let get = |key: &str| {
            rect.get(key).and_then(Value::as_f64).ok_or_else(|| {
                tool_err("element rect unavailable (callFunctionOn returned no rect)")
            })
        };
        Ok((
            get("x")? + get("width")? / 2.0,
            get("y")? + get("height")? / 2.0,
        ))
    }

    /// Center of the layout viewport in CSS px.
    async fn viewport_center(&self, tab_id: u64) -> CoreResult<(f64, f64)> {
        self.ensure_attached(tab_id).await?;
        let metrics = self
            .execute_cdp(tab_id, "Page.getLayoutMetrics", json!({}))
            .await?;
        let viewport = metrics
            .get("cssLayoutViewport")
            .cloned()
            .unwrap_or(Value::Null);
        let width = viewport
            .get("clientWidth")
            .and_then(Value::as_f64)
            .ok_or_else(|| tool_err("Page.getLayoutMetrics returned no viewport size"))?;
        let height = viewport
            .get("clientHeight")
            .and_then(Value::as_f64)
            .ok_or_else(|| tool_err("Page.getLayoutMetrics returned no viewport size"))?;
        Ok((width / 2.0, height / 2.0))
    }
}

/// The `_run_id` the run wrapper injects into tool input for lease
/// bookkeeping; absent input is tolerated (`None`).
fn run_id_of(input: &Value) -> Option<&str> {
    input
        .get("_run_id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
}

fn required_str<'a>(input: &'a Value, key: &str) -> CoreResult<&'a str> {
    input
        .get(key)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            tool_err(format!(
                "missing or invalid '{key}' (expected a non-empty string)"
            ))
        })
}

/// Snapshot refs look like `e12` (assigned by the snapshot script).
fn valid_ref(ref_: &str) -> bool {
    ref_.len() >= 2 && ref_.starts_with('e') && ref_[1..].chars().all(|c| c.is_ascii_digit())
}

fn bad_ref_err(ref_: &str) -> agistack_core::ports::CoreError {
    tool_err(format!(
        "invalid 'ref' format: {ref_:?} (expected a snapshot ref like \"e12\")"
    ))
}

fn required_ref(input: &Value) -> CoreResult<&str> {
    let ref_ = required_str(input, "ref")?;
    if !valid_ref(ref_) {
        return Err(bad_ref_err(ref_));
    }
    Ok(ref_)
}

/// Structured tool *result* for an unresolvable ref — the agent should
/// recover by taking a fresh snapshot, not by retrying the same ref.
fn stale_ref_output(ref_: &str) -> Value {
    json!({
        "error": "stale_ref",
        "ref": ref_,
        "hint": "call browser_snapshot again to refresh element refs",
    })
}

/// Only http/https/about:blank are navigable; everything else (chrome://,
/// file://, javascript:, data:, ...) is refused before any bridge call.
fn validate_navigable_url(url: &str) -> CoreResult<()> {
    if url == "about:blank" || url.starts_with("http://") || url.starts_with("https://") {
        return Ok(());
    }
    Err(tool_err(format!(
        "url scheme not allowed for navigation: {} (only http://, https:// and about:blank are allowed)",
        clip(url, 200)
    )))
}

/// Schemes a user tab may have that the agent must never claim.
fn is_browser_internal_url(url: &str) -> bool {
    const INTERNAL: &[&str] = &[
        "chrome://",
        "chrome-extension://",
        "devtools://",
        "edge://",
        "brave://",
        "opera://",
        "vivaldi://",
        "view-source:",
    ];
    INTERNAL.iter().any(|prefix| url.starts_with(prefix))
}

/// Clip to `max_chars` chars (outputs stay compact).
fn clip(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_string();
    }
    text.chars().take(max_chars).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::host::test_support::{ok, MockEndpoint};
    use crate::host::TOOL_SNAPSHOT;
    use crate::protocol::{
        METHOD_ASSIGN_TAB, METHOD_ATTACH, METHOD_CREATE_TAB, METHOD_ENSURE_TAB_GROUP,
        METHOD_EXECUTE_CDP, METHOD_GET_TABS, METHOD_MOVE_MOUSE, METHOD_TURN_ENDED,
        NOTIFY_ON_CDP_DETACH,
    };
    use agistack_core::ports::{CoreError, ToolHost};

    // ------------------------------------------------------------- helpers

    fn frame_tree() -> Value {
        json!({"result": {"frameTree": {"frame": {"id": "F1"}}}})
    }

    fn world(id: u64) -> Value {
        json!({"result": {"executionContextId": id}})
    }

    fn snapshot_value(text: &str) -> Value {
        json!({"result": {"result": {"type": "string", "value": text}}})
    }

    fn ref_hit() -> Value {
        json!({"result": {"result": {"type": "object", "objectId": "obj-1"}}})
    }

    fn ref_null() -> Value {
        json!({"result": {"result": {"type": "object", "subtype": "null", "value": null}}})
    }

    /// Rect (10,20,100x40) → center (60,40).
    fn rect_value() -> Value {
        json!({"result": {"result": {"type": "object", "value": {"x": 10.0, "y": 20.0, "width": 100.0, "height": 40.0}}}})
    }

    fn undefined_result() -> Value {
        json!({"result": {"result": {"type": "undefined"}}})
    }

    fn cdp_ok() -> Value {
        json!({"result": {}})
    }

    fn cdp_event(tab_id: u64, method: &str, params: Value) -> BridgeNotification {
        BridgeNotification {
            method: NOTIFY_ON_CDP_EVENT.into(),
            params: json!({"tabId": tab_id, "method": method, "params": params}),
        }
    }

    /// Params of every `executeCdp` call for one CDP method, in order.
    fn cdp_params_of(host: &BrowserToolHost<MockEndpoint>, cdp_method: &str) -> Vec<Value> {
        host.endpoint
            .requests
            .lock()
            .unwrap()
            .iter()
            .filter(|(m, p)| {
                m == METHOD_EXECUTE_CDP
                    && p.get("method").and_then(Value::as_str) == Some(cdp_method)
            })
            .map(|(_, p)| p["params"].clone())
            .collect()
    }

    fn cdp_count(host: &BrowserToolHost<MockEndpoint>, cdp_method: &str) -> usize {
        cdp_params_of(host, cdp_method).len()
    }

    async fn wait_until(cond: impl Fn() -> bool) {
        for _ in 0..200 {
            if cond() {
                return;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        panic!("condition not met within 2s");
    }

    /// Script the CDP calls a snapshot needs: `attaches` × attach, then per
    /// call getFrameTree + (createIsolatedWorld per entry in `worlds`) +
    /// evaluate.
    fn script_snapshot(
        endpoint: MockEndpoint,
        attaches: usize,
        worlds: Vec<u64>,
        evaluates: usize,
    ) -> MockEndpoint {
        endpoint
            .script(
                METHOD_ATTACH,
                (0..attaches).map(|_| ok(json!({}))).collect(),
            )
            .script(
                "cdp:Page.getFrameTree",
                (0..evaluates).map(|_| ok(frame_tree())).collect(),
            )
            .script(
                "cdp:Page.createIsolatedWorld",
                worlds.into_iter().map(|id| ok(world(id))).collect(),
            )
            .script(
                "cdp:Runtime.evaluate",
                (0..evaluates).map(|_| ok(snapshot_value("SNAP"))).collect(),
            )
    }

    // --------------------------------------------------------- world cache

    #[tokio::test]
    async fn world_cache_is_reused_across_calls() {
        let endpoint = script_snapshot(MockEndpoint::new(), 1, vec![11], 2);
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();
        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();

        assert_eq!(cdp_count(&host, "Page.createIsolatedWorld"), 1);
        let evaluates = cdp_params_of(&host, "Runtime.evaluate");
        assert_eq!(evaluates.len(), 2);
        assert!(evaluates.iter().all(|p| p["contextId"] == 11));
    }

    #[tokio::test]
    async fn world_cache_invalidated_on_execution_contexts_cleared() {
        let endpoint = script_snapshot(MockEndpoint::new(), 1, vec![11, 11], 2);
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();

        host.endpoint
            .notifications
            .send(cdp_event(7, "Runtime.executionContextsCleared", json!({})))
            .unwrap();
        wait_until(|| host.state.worlds.lock().unwrap().is_empty()).await;

        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();
        assert_eq!(cdp_count(&host, "Page.createIsolatedWorld"), 2);
    }

    #[tokio::test]
    async fn world_cache_invalidated_on_execution_context_destroyed() {
        let endpoint = script_snapshot(MockEndpoint::new(), 1, vec![11, 12], 2);
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();

        host.endpoint
            .notifications
            .send(cdp_event(
                7,
                "Runtime.executionContextDestroyed",
                json!({"executionContextId": 11}),
            ))
            .unwrap();
        wait_until(|| host.state.worlds.lock().unwrap().is_empty()).await;

        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();
        assert_eq!(cdp_count(&host, "Page.createIsolatedWorld"), 2);
        let evaluates = cdp_params_of(&host, "Runtime.evaluate");
        assert_eq!(evaluates[1]["contextId"], 12);
    }

    #[tokio::test]
    async fn world_cache_invalidated_on_main_frame_navigation() {
        let endpoint = script_snapshot(MockEndpoint::new(), 1, vec![11, 11], 2);
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();

        host.endpoint
            .notifications
            .send(cdp_event(
                7,
                "Page.frameNavigated",
                json!({"frame": {"id": "F1", "url": "https://example.com/new"}}),
            ))
            .unwrap();
        wait_until(|| host.state.worlds.lock().unwrap().is_empty()).await;

        // The same event is the cheapest URL tracking signal (no getTabs
        // scripted — a lookup would panic the mock).
        assert_eq!(
            host.current_url(7).await.unwrap(),
            "https://example.com/new"
        );

        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();
        assert_eq!(cdp_count(&host, "Page.createIsolatedWorld"), 2);
    }

    #[tokio::test]
    async fn world_cache_survives_subframe_navigation() {
        let endpoint = script_snapshot(MockEndpoint::new(), 1, vec![11], 2);
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();

        host.endpoint
            .notifications
            .send(cdp_event(
                7,
                "Page.frameNavigated",
                json!({"frame": {"id": "F2", "parentId": "F1", "url": "https://example.com/frame"}}),
            ))
            .unwrap();
        // Give the feeder a beat; the cache must survive.
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert!(!host.state.worlds.lock().unwrap().is_empty());

        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();
        assert_eq!(cdp_count(&host, "Page.createIsolatedWorld"), 1);
    }

    #[tokio::test]
    async fn detach_clears_world_cache() {
        let endpoint = script_snapshot(MockEndpoint::new(), 2, vec![11, 11], 2); // 2nd attach after detach
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();

        host.endpoint
            .notifications
            .send(BridgeNotification {
                method: NOTIFY_ON_CDP_DETACH.into(),
                params: json!({"tabId": 7, "reason": "target_closed"}),
            })
            .unwrap();
        wait_until(|| host.state.worlds.lock().unwrap().is_empty()).await;

        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();
        assert_eq!(cdp_count(&host, "Page.createIsolatedWorld"), 2);
    }

    // ----------------------------------------------------- ref resolution

    #[tokio::test]
    async fn click_happy_path_moves_cursor_then_clicks() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.getFrameTree", vec![ok(frame_tree())])
            .script("cdp:Page.createIsolatedWorld", vec![ok(world(11))])
            .script("cdp:Runtime.evaluate", vec![ok(ref_hit())])
            .script("cdp:Runtime.callFunctionOn", vec![ok(rect_value())])
            .script(METHOD_MOVE_MOUSE, vec![ok(json!({}))])
            .script(
                "cdp:Input.dispatchMouseEvent",
                vec![ok(cdp_ok()), ok(cdp_ok()), ok(cdp_ok())],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_CLICK, r#"{"tabId": 7, "ref": "e12"}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out, json!({"clicked": true, "x": 60.0, "y": 40.0}));

        // Ref lookup ran in the cached world with returnByValue off.
        let lookups = cdp_params_of(&host, "Runtime.evaluate");
        assert_eq!(lookups.len(), 1);
        assert_eq!(lookups[0]["contextId"], 11);
        assert_eq!(lookups[0]["returnByValue"], false);
        let expression = lookups[0]["expression"].as_str().unwrap();
        assert!(expression.contains("__memstackSnapshotRefs"));
        assert!(expression.contains("\"e12\""));

        // Cursor moved to the element center with arrival wait...
        let cursor = host.endpoint.params_of(METHOD_MOVE_MOUSE);
        assert_eq!(
            cursor,
            vec![json!({"tabId": 7, "x": 60.0, "y": 40.0, "waitForArrival": true})]
        );
        // ...strictly before the real click sequence.
        let requests = host.endpoint.requests.lock().unwrap();
        let cursor_pos = requests
            .iter()
            .position(|(m, _)| m == METHOD_MOVE_MOUSE)
            .unwrap();
        let input_pos = requests
            .iter()
            .position(|(m, p)| m == METHOD_EXECUTE_CDP && p["method"] == "Input.dispatchMouseEvent")
            .unwrap();
        assert!(cursor_pos < input_pos);
        drop(requests);

        let clicks = cdp_params_of(&host, "Input.dispatchMouseEvent");
        let types: Vec<&str> = clicks.iter().map(|p| p["type"].as_str().unwrap()).collect();
        assert_eq!(types, ["mouseMoved", "mousePressed", "mouseReleased"]);
        assert_eq!(clicks[1]["button"], "left");
        assert_eq!(clicks[1]["clickCount"], 1);
        assert_eq!(clicks[2]["button"], "left");
        assert!(clicks.iter().all(|p| p["x"] == 60.0 && p["y"] == 40.0));
    }

    #[tokio::test]
    async fn click_stale_ref_returns_structured_result() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.getFrameTree", vec![ok(frame_tree())])
            .script("cdp:Page.createIsolatedWorld", vec![ok(world(11))])
            .script("cdp:Runtime.evaluate", vec![ok(ref_null())]);
        let host = BrowserToolHost::new(endpoint);
        // A stale ref is a tool *result*, not an exception.
        let out = host
            .call(TOOL_CLICK, r#"{"tabId": 7, "ref": "e9"}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["error"], "stale_ref");
        assert_eq!(out["ref"], "e9");
        assert_eq!(
            out["hint"],
            "call browser_snapshot again to refresh element refs"
        );
        assert_eq!(cdp_count(&host, "Input.dispatchMouseEvent"), 0);
        assert_eq!(host.endpoint.count(METHOD_MOVE_MOUSE), 0);
    }

    #[tokio::test]
    async fn type_weakref_deref_null_returns_stale_ref() {
        // The page-side WeakRef deref'd to null (element GC'd / DOM changed);
        // the host sees the same null lookup as a missing stash.
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.getFrameTree", vec![ok(frame_tree())])
            .script("cdp:Page.createIsolatedWorld", vec![ok(world(11))])
            .script("cdp:Runtime.evaluate", vec![ok(ref_null())]);
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_TYPE, r#"{"tabId": 7, "ref": "e3", "text": "hi"}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["error"], "stale_ref");
        assert_eq!(cdp_count(&host, "Input.insertText"), 0);
    }

    #[tokio::test]
    async fn move_mouse_failure_still_clicks() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.getFrameTree", vec![ok(frame_tree())])
            .script("cdp:Page.createIsolatedWorld", vec![ok(world(11))])
            .script("cdp:Runtime.evaluate", vec![ok(ref_hit())])
            .script("cdp:Runtime.callFunctionOn", vec![ok(rect_value())])
            .script(
                METHOD_MOVE_MOUSE,
                vec![Err(CoreError::Tool("cursor exploded".into()))],
            )
            .script(
                "cdp:Input.dispatchMouseEvent",
                vec![ok(cdp_ok()), ok(cdp_ok()), ok(cdp_ok())],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_CLICK, r#"{"tabId": 7, "ref": "e12"}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["clicked"], true);
        assert_eq!(cdp_count(&host, "Input.dispatchMouseEvent"), 3);
    }

    // ------------------------------------------------------------ type/scroll

    #[tokio::test]
    async fn type_focuses_clears_inserts_and_presses_enter() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.getFrameTree", vec![ok(frame_tree())])
            .script("cdp:Page.createIsolatedWorld", vec![ok(world(11))])
            .script("cdp:Runtime.evaluate", vec![ok(ref_hit())])
            .script(
                "cdp:Runtime.callFunctionOn",
                vec![ok(undefined_result()), ok(undefined_result())],
            )
            .script("cdp:Input.insertText", vec![ok(cdp_ok())])
            .script(
                "cdp:Input.dispatchKeyEvent",
                vec![ok(cdp_ok()), ok(cdp_ok())],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(
                TOOL_TYPE,
                r#"{"tabId": 7, "ref": "e3", "text": "héllo", "clear": true, "pressEnter": true}"#,
            )
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out, json!({"typed": 5}));

        let calls = cdp_params_of(&host, "Runtime.callFunctionOn");
        assert_eq!(calls.len(), 2);
        assert!(calls[0]["functionDeclaration"]
            .as_str()
            .unwrap()
            .contains("this.focus()"));
        assert!(calls[1]["functionDeclaration"]
            .as_str()
            .unwrap()
            .contains("this.value = ''"));
        assert_eq!(cdp_params_of(&host, "Input.insertText")[0]["text"], "héllo");

        let keys = cdp_params_of(&host, "Input.dispatchKeyEvent");
        assert_eq!(keys.len(), 2);
        assert_eq!(keys[0]["type"], "rawKeyDown");
        assert_eq!(keys[1]["type"], "keyUp");
        for key in &keys {
            assert_eq!(key["windowsVirtualKeyCode"], 13);
            assert_eq!(key["key"], "Enter");
            assert_eq!(key["code"], "Enter");
        }
    }

    #[tokio::test]
    async fn scroll_without_ref_uses_viewport_center() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.getLayoutMetrics", vec![ok(
                json!({"result": {"cssLayoutViewport": {"clientWidth": 800, "clientHeight": 600}}}),
            )])
            .script("cdp:Input.dispatchMouseEvent", vec![ok(cdp_ok())]);
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_SCROLL, r#"{"tabId": 7, "deltaY": 240}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out, json!({"scrolled": 240.0}));
        let wheels = cdp_params_of(&host, "Input.dispatchMouseEvent");
        assert_eq!(
            wheels,
            vec![
                json!({"type": "mouseWheel", "x": 400.0, "y": 300.0, "deltaX": 0, "deltaY": 240.0})
            ]
        );
    }

    #[tokio::test]
    async fn scroll_with_ref_uses_element_center() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.getFrameTree", vec![ok(frame_tree())])
            .script("cdp:Page.createIsolatedWorld", vec![ok(world(11))])
            .script("cdp:Runtime.evaluate", vec![ok(ref_hit())])
            .script("cdp:Runtime.callFunctionOn", vec![ok(rect_value())])
            .script("cdp:Input.dispatchMouseEvent", vec![ok(cdp_ok())]);
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_SCROLL, r#"{"tabId": 7, "ref": "e5", "deltaY": -120}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out, json!({"scrolled": -120.0}));
        let wheels = cdp_params_of(&host, "Input.dispatchMouseEvent");
        assert_eq!(wheels[0]["type"], "mouseWheel");
        assert_eq!(wheels[0]["x"], 60.0);
        assert_eq!(wheels[0]["y"], 40.0);
    }

    // ------------------------------------------------------------- navigate

    /// Drive `host.call(TOOL_NAVIGATE, input)` while firing the load event as
    /// soon as `Page.navigate` has been sent.
    async fn navigate_firing_load(host: &BrowserToolHost<MockEndpoint>, input: &str) -> String {
        let driver = async {
            for _ in 0..200 {
                if cdp_count(host, "Page.navigate") == 1 {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            host.endpoint
                .notifications
                .send(cdp_event(7, "Page.loadEventFired", json!({})))
                .unwrap();
        };
        let (out, ()) = tokio::join!(host.call(TOOL_NAVIGATE, input), driver);
        out.unwrap()
    }

    fn script_navigate(endpoint: MockEndpoint, title: &str) -> MockEndpoint {
        endpoint
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.enable", vec![ok(cdp_ok())])
            .script(
                "cdp:Page.navigate",
                vec![ok(json!({"result": {"frameId": "F1"}}))],
            )
            .script("cdp:Page.getFrameTree", vec![ok(frame_tree())])
            .script("cdp:Page.createIsolatedWorld", vec![ok(world(11))])
            .script(
                "cdp:Runtime.evaluate",
                vec![ok(
                    json!({"result": {"result": {"type": "string", "value": title}}}),
                )],
            )
    }

    #[tokio::test]
    async fn navigate_waits_for_load_and_returns_title() {
        let endpoint = script_navigate(MockEndpoint::new(), "Example");
        let host = BrowserToolHost::new(endpoint);
        let out =
            navigate_firing_load(&host, r#"{"tabId": 7, "url": "https://example.com"}"#).await;
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(
            out,
            json!({"url": "https://example.com", "title": "Example"})
        );

        // The title was read inside the cached isolated world.
        let evaluates = cdp_params_of(&host, "Runtime.evaluate");
        assert_eq!(evaluates[0]["expression"], "document.title");
        assert_eq!(evaluates[0]["contextId"], 11);

        // navigate caches the URL for the consent wrapper (no getTabs scripted).
        assert_eq!(host.current_url(7).await.unwrap(), "https://example.com");
    }

    #[tokio::test]
    async fn navigate_output_stays_under_2000_chars() {
        let huge_title = "t".repeat(5000);
        let endpoint = script_navigate(MockEndpoint::new(), &huge_title);
        let host = BrowserToolHost::new(endpoint);
        let out =
            navigate_firing_load(&host, r#"{"tabId": 7, "url": "https://example.com"}"#).await;
        assert!(
            out.len() <= 2000,
            "tool output must stay within budget, got {} chars",
            out.len()
        );
    }

    // --------------------------------------------------------------- leases

    fn script_new_tab(endpoint: MockEndpoint) -> MockEndpoint {
        endpoint
            .script(METHOD_CREATE_TAB, vec![ok(json!({"tabId": 42}))])
            .script(METHOD_ENSURE_TAB_GROUP, vec![ok(json!({"groupId": 3}))])
            .script(METHOD_ASSIGN_TAB, vec![ok(json!({}))])
    }

    #[tokio::test]
    async fn new_tab_creates_groups_assigns_and_leases() {
        let endpoint = script_new_tab(MockEndpoint::new());
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(
                TOOL_NEW_TAB,
                r#"{"url": "https://example.com", "_run_id": "run-1"}"#,
            )
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out, json!({"tabId": 42, "groupId": 3}));

        assert_eq!(
            host.endpoint.params_of(METHOD_CREATE_TAB),
            vec![json!({"active": false, "url": "https://example.com"})]
        );
        assert_eq!(
            host.endpoint.params_of(METHOD_ENSURE_TAB_GROUP),
            vec![json!({"key": "run-1", "title": "MemStack Agent"})]
        );
        assert_eq!(
            host.endpoint.params_of(METHOD_ASSIGN_TAB),
            vec![json!({"tabId": 42, "groupId": 3})]
        );
        let leases = host.state.leases.lock().unwrap();
        let run = &leases["run-1"];
        assert_eq!(run.len(), 1);
        assert_eq!(run[0].tab_id, 42);
        assert_eq!(run[0].origin, LeaseOrigin::Agent);
    }

    #[tokio::test]
    async fn turn_ended_sends_leases_and_cleans_local_state() {
        let endpoint = script_new_tab(MockEndpoint::new()).script(
            METHOD_TURN_ENDED,
            vec![ok(json!({"closed": 1, "ungrouped": 1}))],
        );
        let host = BrowserToolHost::new(endpoint);
        host.call(
            TOOL_NEW_TAB,
            r#"{"url": "https://example.com", "_run_id": "run-1"}"#,
        )
        .await
        .unwrap();
        host.call(
            TOOL_MARK_TAB,
            r#"{"tabId": 42, "mark": "deliverable", "_run_id": "run-1"}"#,
        )
        .await
        .unwrap();

        host.turn_ended("run-1").await;
        assert_eq!(
            host.endpoint.params_of(METHOD_TURN_ENDED),
            vec![json!({"leases": [{"tabId": 42, "origin": "agent", "mark": "deliverable"}]})]
        );
        assert!(host.state.leases.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn claim_tab_records_user_origin_without_grouping() {
        let endpoint = MockEndpoint::new()
            .script(
                METHOD_GET_TABS,
                vec![ok(
                    json!({"tabs": [{"tabId": 7, "windowId": 1, "title": "t",
                    "url": "https://example.com", "active": true}]}),
                )],
            )
            .script(
                METHOD_TURN_ENDED,
                vec![ok(json!({"closed": 0, "ungrouped": 0}))],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7, "_run_id": "run-2"}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out, json!({"tabId": 7}));
        assert_eq!(host.endpoint.count(METHOD_ENSURE_TAB_GROUP), 0);

        host.turn_ended("run-2").await;
        assert_eq!(
            host.endpoint.params_of(METHOD_TURN_ENDED),
            vec![json!({"leases": [{"tabId": 7, "origin": "user"}]})]
        );
    }

    #[tokio::test]
    async fn turn_ended_tolerates_bridge_error_and_still_cleans_up() {
        let endpoint = script_new_tab(MockEndpoint::new()).script(
            METHOD_TURN_ENDED,
            vec![Err(CoreError::Tool("extension gone".into()))],
        );
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_NEW_TAB, r#"{"_run_id": "run-1"}"#)
            .await
            .unwrap();
        host.turn_ended("run-1").await; // must not panic or propagate
        assert!(host.state.leases.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn turn_ended_without_leases_is_a_noop() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        host.turn_ended("no-such-run").await; // no turnEnded scripted: a call would panic
        assert_eq!(host.endpoint.count(METHOD_TURN_ENDED), 0);
    }

    #[tokio::test]
    async fn current_url_falls_back_to_get_tabs_and_caches() {
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![ok(
                json!({"tabs": [{"tabId": 7, "windowId": 1, "title": "t",
                "url": "https://example.com/page", "active": false}]}),
            )],
        );
        let host = BrowserToolHost::new(endpoint);
        assert_eq!(
            host.current_url(7).await.unwrap(),
            "https://example.com/page"
        );
        // Second call hits the cache — only one getTabs was scripted.
        assert_eq!(
            host.current_url(7).await.unwrap(),
            "https://example.com/page"
        );
        assert_eq!(host.endpoint.count(METHOD_GET_TABS), 1);
    }

    #[tokio::test]
    async fn current_url_unknown_tab_errors() {
        let endpoint = MockEndpoint::new().script(METHOD_GET_TABS, vec![ok(json!({"tabs": []}))]);
        let host = BrowserToolHost::new(endpoint);
        let err = host.current_url(99).await.unwrap_err();
        assert!(err.to_string().contains("tab 99 not found"));
    }

    // ----------------------------------------------------------- validation

    #[tokio::test]
    async fn navigate_rejects_non_http_schemes() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        for url in [
            "chrome://newtab",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html,hi",
        ] {
            let input = json!({"tabId": 7, "url": url}).to_string();
            let err = host.call(TOOL_NAVIGATE, &input).await.unwrap_err();
            assert!(err.to_string().contains("scheme"), "{url}: {err}");
        }
        assert!(host.endpoint.requests.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn new_tab_rejects_bad_url_scheme() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        let err = host
            .call(TOOL_NEW_TAB, r#"{"url": "chrome://settings"}"#)
            .await
            .unwrap_err();
        assert!(err.to_string().contains("scheme"));
        assert!(host.endpoint.requests.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn click_and_type_reject_bad_ref_format() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        for bad in ["12", "x1", "", "e-3"] {
            let input = json!({"tabId": 7, "ref": bad}).to_string();
            let err = host.call(TOOL_CLICK, &input).await.unwrap_err();
            assert!(err.to_string().contains("ref"), "{bad}: {err}");
            let input = json!({"tabId": 7, "ref": bad, "text": "hi"}).to_string();
            let err = host.call(TOOL_TYPE, &input).await.unwrap_err();
            assert!(err.to_string().contains("ref"), "{bad}: {err}");
        }
        assert!(host.endpoint.requests.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn scroll_requires_delta_y() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        let err = host.call(TOOL_SCROLL, r#"{"tabId": 7}"#).await.unwrap_err();
        assert!(err.to_string().contains("deltaY"));
        assert!(host.endpoint.requests.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn mark_tab_rejects_bad_mark() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        let err = host
            .call(TOOL_MARK_TAB, r#"{"tabId": 7, "mark": "keep"}"#)
            .await
            .unwrap_err();
        assert!(err.to_string().contains("mark"));
        assert!(host.endpoint.requests.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn mark_tab_without_lease_errors() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        let err = host
            .call(TOOL_MARK_TAB, r#"{"tabId": 7, "mark": "handoff"}"#)
            .await
            .unwrap_err();
        assert!(err.to_string().contains("no lease"));
    }

    #[tokio::test]
    async fn claim_tab_refuses_browser_internal_url() {
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![ok(
                json!({"tabs": [{"tabId": 7, "windowId": 1, "title": "t",
                "url": "chrome://extensions/", "active": true}]}),
            )],
        );
        let host = BrowserToolHost::new(endpoint);
        let err = host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .unwrap_err();
        assert!(err.to_string().contains("browser-internal"));
        assert!(host.state.leases.lock().unwrap().is_empty());
    }
}
