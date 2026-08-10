//! [`ToolHost`] implementation exposing browser tools over the extension bridge.
//!
//! [`BrowserToolHost`] wraps any [`BridgeEndpoint`] (the real
//! [`BridgeWsClient`](crate::ws_client::BridgeWsClient), or a mock in tests)
//! and exposes read-only tools plus M2 mutation tools to the agent engine:
//!
//! | tool | bridge/CDP calls | output |
//! |---|---|---|
//! | `browser_list_tabs` | `getTabs` | `{tabs: [...]}` |
//! | `browser_snapshot` | `attach` → snapshot CDP sequence (cached isolated world) | `{snapshot, truncated}` |
//! | `browser_screenshot` | `attach` → `Page.captureScreenshot` | `{mimeType, dataBase64, width, height}` |
//! | `browser_console_logs` | `attach` → `Runtime/Log.enable` → ring buffer | `{entries: [...]}` |
//! | `browser_navigate` / `browser_click` / `browser_type` / `browser_scroll` | see [`crate::actions`] | compact JSON |
//! | `browser_new_tab` / `browser_claim_tab` / `browser_mark_tab` | tab-group bridge methods + leases | compact JSON |
//! | `browser_cdp_raw` | `attach` → full-access policy check → `executeCdp` | `{result}` (capped at 4000 chars) |
//!
//! Console events are collected continuously from `onCDPEvent` notifications
//! into a per-tab ring buffer (capacity 500) by a background feeder task. The
//! same feeder invalidates the isolated-world cache on navigation/context
//! teardown (see [`crate::actions`]).
//!
//! Every tool accepts an optional `backend` input (`"chrome"` | `"iab"`,
//! default chrome): chrome calls go through [`BridgeEndpoint::request`], iab
//! calls through [`BridgeEndpoint::request_on`], and all per-tab host state
//! (attach memos, world cache, console buffers, URL cache, leases) is keyed
//! by `(backend, tabId)`.

use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use serde::Serialize;
use serde_json::{json, Value};
use tokio::sync::broadcast;

use agistack_core::ports::{CoreError, CoreResult, ToolHost};

use crate::actions::{
    TOOL_CLAIM_TAB, TOOL_CLICK, TOOL_MARK_TAB, TOOL_NAVIGATE, TOOL_NEW_TAB, TOOL_SCROLL, TOOL_TYPE,
};
use crate::cdp_policy::{check_cdp_allowed_with_mode, CdpPolicyMode};
use crate::protocol::{
    BridgeNotification, LeaseOrigin, OnCdpDetachParams, OnCdpEventParams, TabMark, METHOD_ATTACH,
    METHOD_EXECUTE_CDP, METHOD_GET_TABS, METHOD_MOVE_MOUSE, METHOD_TURN_ENDED,
    NOTIFY_ON_CDP_DETACH, NOTIFY_ON_CDP_EVENT,
};
use crate::snapshot::{self, PLACEHOLDER_CONTEXT_ID, PLACEHOLDER_FRAME_ID, SNAPSHOT_WORLD_NAME};

/// Registered tool names (exact — the agent engine matches on these strings).
pub const TOOL_LIST_TABS: &str = "browser_list_tabs";
pub const TOOL_SNAPSHOT: &str = "browser_snapshot";
pub const TOOL_SCREENSHOT: &str = "browser_screenshot";
pub const TOOL_CONSOLE_LOGS: &str = "browser_console_logs";
pub const TOOL_CDP_RAW: &str = "browser_cdp_raw";

const DEFAULT_MAX_CHARS: usize = 20_000;
const DEFAULT_CONSOLE_LIMIT: usize = 100;
const CONSOLE_RING_CAPACITY: usize = 500;
/// Serialized-output cap for `browser_cdp_raw`; oversized results are
/// truncated with a marker.
const CDP_RAW_MAX_OUTPUT_CHARS: usize = 4000;

pub(crate) fn tool_err(message: impl Into<String>) -> CoreError {
    CoreError::Tool(message.into())
}

/// The bridge surface the host needs: request/response plus a notification
/// stream. Implemented by
/// [`BridgeWsClient`](crate::ws_client::BridgeWsClient) in production.
#[async_trait]
pub trait BridgeEndpoint: Send + Sync {
    /// Issue one bridge request, returning the JSON-RPC `result` payload.
    async fn request(&self, method: &str, params: Value) -> CoreResult<Value>;
    /// Issue one bridge request against a named non-default backend (e.g.
    /// `"iab"`). The default implementation ignores the backend and
    /// delegates to [`BridgeEndpoint::request`]; multi-backend endpoints
    /// (the sidecar) override it.
    async fn request_on(&self, backend: &str, method: &str, params: Value) -> CoreResult<Value> {
        let _ = backend;
        self.request(method, params).await
    }
    /// Subscribe to extension notifications (`onCDPEvent` / `onCDPDetach`).
    fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification>;
}

/// Browser backend selector carried by the optional `backend` tool input
/// (`"chrome"` | `"iab"`, default chrome). All per-tab host state is keyed
/// by `(Backend, tabId)`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) enum Backend {
    /// The Chrome extension bridge (default).
    Chrome,
    /// The in-app browser backend.
    Iab,
}

impl Backend {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Backend::Chrome => "chrome",
            Backend::Iab => "iab",
        }
    }

    /// Backend named on a bridge notification; absent or unknown means the
    /// default chrome-extension backend.
    pub(crate) fn from_wire(name: Option<&str>) -> Self {
        match name {
            Some("iab") => Backend::Iab,
            _ => Backend::Chrome,
        }
    }
}

/// Extract the optional `backend` tool input (`"chrome"` | `"iab"`, default
/// chrome); any other value is a tool error.
pub(crate) fn backend_of(input: &Value) -> CoreResult<Backend> {
    match input.get("backend") {
        None | Some(Value::Null) => Ok(Backend::Chrome),
        Some(Value::String(s)) => match s.as_str() {
            "chrome" => Ok(Backend::Chrome),
            "iab" => Ok(Backend::Iab),
            other => Err(tool_err(format!(
                "invalid 'backend': {other:?} (expected \"chrome\" or \"iab\")"
            ))),
        },
        Some(_) => Err(tool_err(
            "invalid 'backend' (expected \"chrome\" or \"iab\")",
        )),
    }
}

#[async_trait]
impl BridgeEndpoint for crate::ws_client::BridgeWsClient {
    async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        self.request(method, params).await
    }

    fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification> {
        self.subscribe_notifications()
    }
}

/// One captured console entry.
#[derive(Debug, Clone, Serialize)]
pub(crate) struct ConsoleEntry {
    level: String,
    text: String,
    timestamp: f64,
}

/// One tab lease: a tab bound to a run until [`BrowserToolHost::turn_ended`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TabLease {
    pub backend: Backend,
    pub tab_id: u64,
    pub origin: LeaseOrigin,
    pub mark: Option<TabMark>,
}

/// Mutable host state shared with the notification feeder task. Every
/// per-tab dimension is keyed by `(backend, tabId)`: the same tab id on two
/// backends refers to different tabs.
pub(crate) struct HostState {
    /// Tabs we have already sent `attach` for (attach is idempotent, but the
    /// memo avoids a round trip per tool call).
    pub(crate) attached: Mutex<HashSet<(Backend, u64)>>,
    /// Tabs for which `Runtime.enable` + `Log.enable` were already sent.
    pub(crate) console_enabled: Mutex<HashSet<(Backend, u64)>>,
    /// Per-tab console ring buffers.
    pub(crate) console_buffers: Mutex<HashMap<(Backend, u64), VecDeque<ConsoleEntry>>>,
    /// Isolated-world cache: `(backend, tabId, frameId)` →
    /// `executionContextId`. The world is created once and reused for
    /// snapshots and ref resolution (same-name `Page.createIsolatedWorld`
    /// calls do NOT reuse a world, so without this cache the
    /// `window.__memstackSnapshotRefs` stash is lost).
    pub(crate) worlds: Mutex<HashMap<(Backend, u64, String), u64>>,
    /// Tabs for which `Page.enable` was already sent (load/navigation events).
    pub(crate) page_enabled: Mutex<HashSet<(Backend, u64)>>,
    /// Last known URL per tab (set by `browser_navigate` and main-frame
    /// `Page.frameNavigated` events); backs [`BrowserToolHost::current_url`].
    pub(crate) tab_urls: Mutex<HashMap<(Backend, u64), String>>,
    /// Tab leases per run id, cleaned up by [`BrowserToolHost::turn_ended`].
    pub(crate) leases: Mutex<HashMap<String, Vec<TabLease>>>,
}

impl HostState {
    fn handle_notification(&self, notification: &BridgeNotification) {
        match notification.method.as_str() {
            NOTIFY_ON_CDP_EVENT => {
                let Ok(event) =
                    serde_json::from_value::<OnCdpEventParams>(notification.params.clone())
                else {
                    return;
                };
                let backend = Backend::from_wire(event.backend.as_deref());
                if let Some(entry) = console_entry(&event) {
                    let mut buffers = self.console_buffers.lock().unwrap();
                    let buffer = buffers.entry((backend, event.tab_id)).or_default();
                    if buffer.len() >= CONSOLE_RING_CAPACITY {
                        buffer.pop_front();
                    }
                    buffer.push_back(entry);
                }
                self.handle_world_lifecycle(backend, &event);
            }
            NOTIFY_ON_CDP_DETACH => {
                let Ok(detach) =
                    serde_json::from_value::<OnCdpDetachParams>(notification.params.clone())
                else {
                    return;
                };
                let backend = Backend::from_wire(detach.backend.as_deref());
                let key = (backend, detach.tab_id);
                self.attached.lock().unwrap().remove(&key);
                self.console_enabled.lock().unwrap().remove(&key);
                self.page_enabled.lock().unwrap().remove(&key);
                self.tab_urls.lock().unwrap().remove(&key);
                self.worlds
                    .lock()
                    .unwrap()
                    .retain(|(b, tab, _), _| !(*b == backend && *tab == detach.tab_id));
            }
            _ => {}
        }
    }

    /// Isolated-world cache invalidation driven by CDP lifecycle events.
    fn handle_world_lifecycle(&self, backend: Backend, event: &OnCdpEventParams) {
        match event.method.as_str() {
            // All contexts of the tab are gone (navigation, crash, ...).
            "Runtime.executionContextsCleared" => {
                self.worlds
                    .lock()
                    .unwrap()
                    .retain(|(b, tab, _), _| !(*b == backend && *tab == event.tab_id));
            }
            // A single context died; drop any cache entry of this backend
            // pointing at it.
            "Runtime.executionContextDestroyed" => {
                if let Some(id) = event
                    .params
                    .get("executionContextId")
                    .and_then(Value::as_u64)
                {
                    self.worlds
                        .lock()
                        .unwrap()
                        .retain(|(b, _, _), ctx| !(*b == backend && *ctx == id));
                }
            }
            // Main-frame navigation destroys every isolated world of the tab
            // and is also our cheapest URL tracking signal.
            "Page.frameNavigated" => {
                let Some(frame) = event.params.get("frame") else {
                    return;
                };
                if frame.get("parentId").is_some() {
                    return; // sub-frame navigation: main world survives
                }
                self.worlds
                    .lock()
                    .unwrap()
                    .retain(|(b, tab, _), _| !(*b == backend && *tab == event.tab_id));
                if let Some(url) = frame.get("url").and_then(Value::as_str) {
                    self.tab_urls
                        .lock()
                        .unwrap()
                        .insert((backend, event.tab_id), url.to_string());
                }
            }
            _ => {}
        }
    }
}

/// Translate one CDP event into a console entry, if it is a console event.
fn console_entry(event: &OnCdpEventParams) -> Option<ConsoleEntry> {
    match event.method.as_str() {
        "Runtime.consoleAPICalled" => {
            let level = event
                .params
                .get("type")
                .and_then(Value::as_str)
                .unwrap_or("log")
                .to_string();
            let text = event
                .params
                .get("args")
                .and_then(Value::as_array)
                .map(|args| {
                    args.iter()
                        .map(remote_object_text)
                        .collect::<Vec<_>>()
                        .join(" ")
                })
                .unwrap_or_default();
            let timestamp = event
                .params
                .get("timestamp")
                .and_then(Value::as_f64)
                .unwrap_or(0.0);
            Some(ConsoleEntry {
                level,
                text,
                timestamp,
            })
        }
        "Log.entryAdded" => {
            let entry = event.params.get("entry")?;
            Some(ConsoleEntry {
                level: entry
                    .get("level")
                    .and_then(Value::as_str)
                    .unwrap_or("info")
                    .to_string(),
                text: entry
                    .get("text")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                timestamp: entry
                    .get("timestamp")
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0),
            })
        }
        _ => None,
    }
}

/// Best-effort text form of a CDP `Runtime.RemoteObject`.
fn remote_object_text(object: &Value) -> String {
    if let Some(value) = object.get("value") {
        return match value {
            Value::String(s) => s.clone(),
            other => other.to_string(),
        };
    }
    object
        .get("description")
        .or_else(|| object.get("unserializableValue"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

/// A [`ToolHost`] exposing the browser tools over a bridge endpoint.
pub struct BrowserToolHost<E: BridgeEndpoint> {
    pub(crate) endpoint: Arc<E>,
    pub(crate) state: Arc<HostState>,
}

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    /// Create the host and spawn the console-notification feeder task.
    pub fn new(endpoint: E) -> Self {
        let endpoint = Arc::new(endpoint);
        let state = Arc::new(HostState {
            attached: Mutex::new(HashSet::new()),
            console_enabled: Mutex::new(HashSet::new()),
            console_buffers: Mutex::new(HashMap::new()),
            worlds: Mutex::new(HashMap::new()),
            page_enabled: Mutex::new(HashSet::new()),
            tab_urls: Mutex::new(HashMap::new()),
            leases: Mutex::new(HashMap::new()),
        });
        let mut notifications = endpoint.subscribe_notifications();
        let feeder_state = Arc::clone(&state);
        tokio::spawn(async move {
            loop {
                match notifications.recv().await {
                    Ok(notification) => feeder_state.handle_notification(&notification),
                    Err(broadcast::error::RecvError::Lagged(skipped)) => {
                        tracing::warn!("browser console feeder lagged, dropped {skipped} events");
                    }
                    Err(broadcast::error::RecvError::Closed) => return,
                }
            }
        });
        Self { endpoint, state }
    }

    /// Route one bridge request to a backend: chrome goes through the
    /// default `request`, every other backend through `request_on`.
    pub(crate) async fn backend_request(
        &self,
        backend: Backend,
        method: &str,
        params: Value,
    ) -> CoreResult<Value> {
        match backend {
            Backend::Chrome => self.endpoint.request(method, params).await,
            Backend::Iab => {
                self.endpoint
                    .request_on(backend.as_str(), method, params)
                    .await
            }
        }
    }

    /// Send `attach` for `tab_id` unless already attached.
    pub(crate) async fn ensure_attached(&self, backend: Backend, tab_id: u64) -> CoreResult<()> {
        if self
            .state
            .attached
            .lock()
            .unwrap()
            .contains(&(backend, tab_id))
        {
            return Ok(());
        }
        self.backend_request(backend, METHOD_ATTACH, json!({ "tabId": tab_id }))
            .await?;
        self.state
            .attached
            .lock()
            .unwrap()
            .insert((backend, tab_id));
        Ok(())
    }

    /// Run one CDP command on an attached tab, returning the CDP response
    /// body (the `result` field of the `executeCdp` result).
    pub(crate) async fn execute_cdp(
        &self,
        backend: Backend,
        tab_id: u64,
        method: &str,
        params: Value,
    ) -> CoreResult<Value> {
        let response = self
            .backend_request(
                backend,
                METHOD_EXECUTE_CDP,
                json!({ "tabId": tab_id, "method": method, "params": params }),
            )
            .await?;
        Ok(response.get("result").cloned().unwrap_or(Value::Null))
    }

    /// Get or create the cached isolated world for the tab's main frame,
    /// returning `(frameId, executionContextId)`. The world persists across
    /// calls so the snapshot's `window.__memstackSnapshotRefs` stash stays
    /// resolvable by the action tools; the notification feeder invalidates
    /// the cache on context/navigation teardown.
    pub(crate) async fn world_context(
        &self,
        backend: Backend,
        tab_id: u64,
    ) -> CoreResult<(String, u64)> {
        self.ensure_attached(backend, tab_id).await?;
        let tree = self
            .execute_cdp(backend, tab_id, "Page.getFrameTree", json!({}))
            .await?;
        let frame_id = tree
            .pointer("/frameTree/frame/id")
            .and_then(Value::as_str)
            .ok_or_else(|| tool_err("Page.getFrameTree returned no main frame id"))?
            .to_string();

        let key = (backend, tab_id, frame_id.clone());
        if let Some(&context_id) = self.state.worlds.lock().unwrap().get(&key) {
            return Ok((frame_id, context_id));
        }
        let world = self
            .execute_cdp(
                backend,
                tab_id,
                "Page.createIsolatedWorld",
                json!({
                    "frameId": frame_id,
                    "worldName": SNAPSHOT_WORLD_NAME,
                    "grantUniveralAccess": true,
                }),
            )
            .await?;
        let context_id = world
            .get("executionContextId")
            .and_then(Value::as_u64)
            .ok_or_else(|| tool_err("Page.createIsolatedWorld returned no executionContextId"))?;
        self.state.worlds.lock().unwrap().insert(key, context_id);
        Ok((frame_id, context_id))
    }

    /// Record (or refresh) a tab lease for `run_id`.
    pub(crate) fn record_lease(
        &self,
        run_id: &str,
        backend: Backend,
        tab_id: u64,
        origin: LeaseOrigin,
    ) {
        let mut leases = self.state.leases.lock().unwrap();
        let run = leases.entry(run_id.to_string()).or_default();
        if let Some(existing) = run
            .iter_mut()
            .find(|l| l.backend == backend && l.tab_id == tab_id)
        {
            existing.origin = origin;
            return;
        }
        run.push(TabLease {
            backend,
            tab_id,
            origin,
            mark: None,
        });
    }

    /// Set the end-of-turn mark on the lease for `tab_id` (scoped to
    /// `run_id` when given). Returns false when no lease covers the tab.
    pub(crate) fn mark_lease(
        &self,
        run_id: Option<&str>,
        backend: Backend,
        tab_id: u64,
        mark: TabMark,
    ) -> bool {
        let mut leases = self.state.leases.lock().unwrap();
        let found = match run_id {
            Some(run_id) => leases.get_mut(run_id).and_then(|run| {
                run.iter_mut()
                    .find(|l| l.backend == backend && l.tab_id == tab_id)
            }),
            None => leases
                .values_mut()
                .flat_map(|run| run.iter_mut())
                .find(|l| l.backend == backend && l.tab_id == tab_id),
        };
        match found {
            Some(lease) => {
                lease.mark = Some(mark);
                true
            }
            None => false,
        }
    }

    /// Remember the current URL of a tab (also fed by navigation events).
    pub(crate) fn set_tab_url(&self, backend: Backend, tab_id: u64, url: &str) {
        self.state
            .tab_urls
            .lock()
            .unwrap()
            .insert((backend, tab_id), url.to_string());
    }

    /// Move the virtual cursor over a chrome-backend tab. Kept for the
    /// sidecar consent wrapper; tool code calls
    /// [`BrowserToolHost::move_mouse_on`].
    pub async fn move_mouse(&self, tab_id: u64, x: f64, y: f64, wait_for_arrival: bool) {
        self.move_mouse_on(Backend::Chrome, tab_id, x, y, wait_for_arrival)
            .await;
    }

    /// Move the virtual cursor over a tab. The bridge handler always
    /// succeeds; any error (cursor invisible, overlay missing, bridge down)
    /// is swallowed so the cursor can never block a real action.
    pub(crate) async fn move_mouse_on(
        &self,
        backend: Backend,
        tab_id: u64,
        x: f64,
        y: f64,
        wait_for_arrival: bool,
    ) {
        let result = self
            .backend_request(
                backend,
                METHOD_MOVE_MOUSE,
                json!({
                    "tabId": tab_id,
                    "x": x,
                    "y": y,
                    "waitForArrival": wait_for_arrival,
                }),
            )
            .await;
        if let Err(e) = result {
            tracing::debug!(
                "moveMouse failed and was swallowed (backend {}, tab {tab_id}): {e}",
                backend.as_str()
            );
        }
    }

    /// End-of-turn cleanup for a run: ship the run's leases to the extension
    /// (`turnEnded` decides close/ungroup/keep per mark and origin), then
    /// drop the local lease state. Leases are grouped per backend — one
    /// `turnEnded` bridge call each. Bridge errors are tolerated — local
    /// state is cleaned up regardless. (Stage B's consent wrapper also drops
    /// any per-run cached consent here; M2 holds none.)
    pub async fn turn_ended(&self, run_id: &str) {
        let leases = self
            .state
            .leases
            .lock()
            .unwrap()
            .remove(run_id)
            .unwrap_or_default();
        if leases.is_empty() {
            return;
        }
        // Group by backend, preserving first-seen order.
        let mut by_backend: Vec<(Backend, Vec<Value>)> = Vec::new();
        for lease in &leases {
            let mut entry = json!({ "tabId": lease.tab_id, "origin": lease.origin });
            if let Some(mark) = lease.mark {
                entry["mark"] = json!(mark);
            }
            match by_backend
                .iter_mut()
                .find(|(backend, _)| *backend == lease.backend)
            {
                Some((_, payloads)) => payloads.push(entry),
                None => by_backend.push((lease.backend, vec![entry])),
            }
        }
        for (backend, payloads) in by_backend {
            if let Err(e) = self
                .backend_request(backend, METHOD_TURN_ENDED, json!({ "leases": payloads }))
                .await
            {
                tracing::warn!(
                    "turnEnded bridge request failed (run {run_id}, backend {}); \
                     local state already cleaned: {e}",
                    backend.as_str()
                );
            }
        }
    }

    /// Current URL of a chrome-backend tab for the origin-consent wrapper
    /// (Stage B). Delegates to [`BrowserToolHost::current_url_on`].
    pub async fn current_url(&self, tab_id: i64) -> CoreResult<String> {
        self.current_url_on(Backend::Chrome, tab_id).await
    }

    /// Current URL of a tab on one backend. Uses the cheapest available
    /// source: the navigate/event-tracked URL cache, falling back to a
    /// bridge `getTabs` lookup.
    pub(crate) async fn current_url_on(&self, backend: Backend, tab_id: i64) -> CoreResult<String> {
        if tab_id < 0 {
            return Err(tool_err(format!("invalid tab id: {tab_id}")));
        }
        let tab_id = tab_id as u64;
        if let Some(url) = self.state.tab_urls.lock().unwrap().get(&(backend, tab_id)) {
            return Ok(url.clone());
        }
        let tabs = self
            .backend_request(backend, METHOD_GET_TABS, json!({}))
            .await?;
        let url = tabs
            .get("tabs")
            .and_then(Value::as_array)
            .and_then(|tabs| {
                tabs.iter()
                    .find(|t| t.get("tabId").and_then(Value::as_u64) == Some(tab_id))
            })
            .and_then(|t| t.get("url"))
            .and_then(Value::as_str)
            .ok_or_else(|| tool_err(format!("tab {tab_id} not found")))?;
        self.set_tab_url(backend, tab_id, url);
        Ok(url.to_string())
    }

    /// `browser_list_tabs`: with an explicit `backend`, that backend's tabs;
    /// without one, chrome + iab aggregated. Every entry is annotated with
    /// its `"backend"`. Aggregation tolerates an offline iab backend (the
    /// sidecar fails closed with `... is not connected` when no iab bridge
    /// is registered): it contributes an empty list. Chrome-branch errors
    /// and any other iab error still propagate.
    async fn list_tabs(&self, input: &Value) -> CoreResult<Value> {
        let backend = backend_of(input)?;
        let aggregate = matches!(input.get("backend"), None | Some(Value::Null));
        let backends = if aggregate {
            vec![Backend::Chrome, Backend::Iab]
        } else {
            vec![backend]
        };
        let mut tabs = Vec::new();
        for backend in backends {
            let result = match self
                .backend_request(backend, METHOD_GET_TABS, json!({}))
                .await
            {
                Ok(result) => result,
                Err(e)
                    if aggregate
                        && backend == Backend::Iab
                        && e.to_string().contains("is not connected") =>
                {
                    tracing::debug!("iab backend not connected; aggregating chrome tabs only");
                    continue;
                }
                Err(e) => return Err(e),
            };
            if let Some(list) = result.get("tabs").and_then(Value::as_array) {
                for tab in list {
                    let mut tab = tab.clone();
                    if let Some(obj) = tab.as_object_mut() {
                        obj.insert("backend".to_string(), json!(backend.as_str()));
                    }
                    tabs.push(tab);
                }
            }
        }
        Ok(json!({ "tabs": tabs }))
    }

    async fn snapshot(&self, input: &Value) -> CoreResult<Value> {
        let backend = backend_of(input)?;
        let tab_id = required_tab_id(input)?;
        let max_chars = input
            .get("maxChars")
            .and_then(Value::as_u64)
            .unwrap_or(DEFAULT_MAX_CHARS as u64) as usize;

        // The snapshot plan's evaluate step runs inside the *cached* isolated
        // world so the `window.__memstackSnapshotRefs` stash it leaves behind
        // stays resolvable by later action-tool calls.
        let plan = snapshot::build_snapshot_request(max_chars as u32);
        let (frame_id, context_id) = self.world_context(backend, tab_id).await?;
        let (_, evaluate_params) = plan
            .into_iter()
            .find(|(method, _)| method == "Runtime.evaluate")
            .expect("snapshot plan always ends with Runtime.evaluate");
        let params = substitute_placeholders(&evaluate_params, &frame_id, context_id);
        let cdp = self
            .execute_cdp(backend, tab_id, "Runtime.evaluate", params)
            .await?;
        if let Some(exception) = cdp.get("exceptionDetails") {
            let detail = exception
                .pointer("/exception/description")
                .or_else(|| exception.pointer("/text"))
                .and_then(Value::as_str)
                .unwrap_or("snapshot script raised");
            return Err(tool_err(format!("snapshot evaluation failed: {detail}")));
        }
        let snapshot_text = cdp
            .pointer("/result/value")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();

        let (snapshot, truncated) = snapshot::truncate_snapshot(&snapshot_text, max_chars);
        Ok(json!({ "snapshot": snapshot, "truncated": truncated }))
    }

    async fn screenshot(&self, input: &Value) -> CoreResult<Value> {
        let backend = backend_of(input)?;
        let tab_id = required_tab_id(input)?;
        let full_page = input
            .get("fullPage")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        self.ensure_attached(backend, tab_id).await?;

        let metrics = self
            .execute_cdp(backend, tab_id, "Page.getLayoutMetrics", json!({}))
            .await?;
        let (width, height) = if full_page {
            let size = metrics.get("cssContentSize").unwrap_or(&Value::Null);
            (
                size.get("width").and_then(Value::as_f64).unwrap_or(0.0),
                size.get("height").and_then(Value::as_f64).unwrap_or(0.0),
            )
        } else {
            let viewport = metrics.get("cssLayoutViewport").unwrap_or(&Value::Null);
            (
                viewport
                    .get("clientWidth")
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0),
                viewport
                    .get("clientHeight")
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0),
            )
        };

        let mut params = json!({ "format": "jpeg", "quality": 80 });
        if full_page {
            params["clip"] = json!({
                "x": 0, "y": 0, "width": width, "height": height, "scale": 1,
            });
            params["captureBeyondViewport"] = json!(true);
        }
        let capture = self
            .execute_cdp(backend, tab_id, "Page.captureScreenshot", params)
            .await?;
        let data = capture
            .get("data")
            .and_then(Value::as_str)
            .ok_or_else(|| tool_err("Page.captureScreenshot returned no image data"))?;

        Ok(json!({
            "mimeType": "image/jpeg",
            "dataBase64": data,
            "width": width.round() as u64,
            "height": height.round() as u64,
        }))
    }

    async fn console_logs(&self, input: &Value) -> CoreResult<Value> {
        let backend = backend_of(input)?;
        let tab_id = required_tab_id(input)?;
        let limit = input
            .get("limit")
            .and_then(Value::as_u64)
            .unwrap_or(DEFAULT_CONSOLE_LIMIT as u64) as usize;
        self.ensure_attached(backend, tab_id).await?;

        let key = (backend, tab_id);
        if !self.state.console_enabled.lock().unwrap().contains(&key) {
            self.execute_cdp(backend, tab_id, "Runtime.enable", json!({}))
                .await?;
            self.execute_cdp(backend, tab_id, "Log.enable", json!({}))
                .await?;
            self.state.console_enabled.lock().unwrap().insert(key);
        }

        let entries: Vec<ConsoleEntry> = self
            .state
            .console_buffers
            .lock()
            .unwrap()
            .get(&key)
            .map(|buffer| {
                let skip = buffer.len().saturating_sub(limit);
                buffer.iter().skip(skip).cloned().collect()
            })
            .unwrap_or_default();
        Ok(json!({ "entries": entries }))
    }

    /// M3 raw-CDP escape hatch: run one CDP method under FullAccess policy.
    /// Consent gating (desktop full-CDP enablement, per-origin approval) lives
    /// in the sidecar wrapper; this crate only enforces the policy deny-list.
    async fn cdp_raw(&self, input: &Value) -> CoreResult<Value> {
        let backend = backend_of(input)?;
        let tab_id = required_tab_id(input)?;
        if tab_id == 0 {
            return Err(tool_err("invalid 'tabId' (expected a positive integer)"));
        }
        let method = input
            .get("method")
            .and_then(Value::as_str)
            .ok_or_else(|| tool_err("missing or invalid 'method' (expected a string)"))?;
        if !is_valid_cdp_method_name(method) {
            return Err(tool_err(format!(
                "invalid 'method' (expected '<Domain>.<method>', e.g. \"Runtime.evaluate\"): {method}"
            )));
        }
        let params = input.get("params").cloned().unwrap_or(Value::Null);

        self.ensure_attached(backend, tab_id).await?;
        check_cdp_allowed_with_mode(CdpPolicyMode::FullAccess, method, &params)
            .map_err(|e| tool_err(e.to_string()))?;
        let result = self.execute_cdp(backend, tab_id, method, params).await?;

        let serialized = result.to_string();
        if let Some(truncated) = truncate_cdp_raw_output(&serialized) {
            Ok(json!({ "result": truncated, "truncated": true }))
        } else {
            Ok(json!({ "result": result }))
        }
    }
}

/// `browser_cdp_raw` accepts only `<Domain>.<method>` CDP names matching
/// `^[A-Z][A-Za-z]+\.[A-Za-z]+$`.
fn is_valid_cdp_method_name(method: &str) -> bool {
    let Some((domain, name)) = method.split_once('.') else {
        return false;
    };
    let mut chars = domain.chars();
    let valid_domain = matches!(chars.next(), Some(c) if c.is_ascii_uppercase())
        && matches!(chars.next(), Some(c) if c.is_ascii_alphabetic())
        && chars.all(|c| c.is_ascii_alphabetic());
    let valid_name = !name.is_empty() && name.chars().all(|c| c.is_ascii_alphabetic());
    valid_domain && valid_name
}

/// Cap a serialized `browser_cdp_raw` result at [`CDP_RAW_MAX_OUTPUT_CHARS`],
/// returning the truncated string (with marker) or `None` when it fits.
fn truncate_cdp_raw_output(serialized: &str) -> Option<String> {
    if serialized.len() <= CDP_RAW_MAX_OUTPUT_CHARS {
        return None;
    }
    let mut end = CDP_RAW_MAX_OUTPUT_CHARS;
    while !serialized.is_char_boundary(end) {
        end -= 1;
    }
    Some(format!(
        "{}\n… [truncated at {CDP_RAW_MAX_OUTPUT_CHARS} chars]",
        &serialized[..end]
    ))
}

pub(crate) fn required_tab_id(input: &Value) -> CoreResult<u64> {
    input
        .get("tabId")
        .and_then(Value::as_u64)
        .ok_or_else(|| tool_err("missing or invalid 'tabId' (expected a number)"))
}

/// Replace snapshot-plan placeholders with the values learned from earlier
/// steps.
fn substitute_placeholders(params: &Value, frame_id: &str, context_id: u64) -> Value {
    match params {
        Value::String(s) if s == PLACEHOLDER_FRAME_ID => Value::String(frame_id.to_string()),
        Value::String(s) if s == PLACEHOLDER_CONTEXT_ID => json!(context_id),
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|v| substitute_placeholders(v, frame_id, context_id))
                .collect(),
        ),
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(k, v)| (k.clone(), substitute_placeholders(v, frame_id, context_id)))
                .collect(),
        ),
        other => other.clone(),
    }
}

#[async_trait]
impl<E: BridgeEndpoint> ToolHost for BrowserToolHost<E> {
    fn list_tools(&self) -> Vec<String> {
        vec![
            TOOL_LIST_TABS.to_string(),
            TOOL_SNAPSHOT.to_string(),
            TOOL_SCREENSHOT.to_string(),
            TOOL_CONSOLE_LOGS.to_string(),
            TOOL_NAVIGATE.to_string(),
            TOOL_CLICK.to_string(),
            TOOL_TYPE.to_string(),
            TOOL_SCROLL.to_string(),
            TOOL_NEW_TAB.to_string(),
            TOOL_CLAIM_TAB.to_string(),
            TOOL_MARK_TAB.to_string(),
            TOOL_CDP_RAW.to_string(),
        ]
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        let input: Value = if input_json.trim().is_empty() {
            json!({})
        } else {
            serde_json::from_str(input_json)
                .map_err(|e| tool_err(format!("invalid tool input json: {e}")))?
        };
        let output = match tool {
            TOOL_LIST_TABS => self.list_tabs(&input).await?,
            TOOL_SNAPSHOT => self.snapshot(&input).await?,
            TOOL_SCREENSHOT => self.screenshot(&input).await?,
            TOOL_CONSOLE_LOGS => self.console_logs(&input).await?,
            TOOL_NAVIGATE => self.navigate(&input).await?,
            TOOL_CLICK => self.click(&input).await?,
            TOOL_TYPE => self.type_text(&input).await?,
            TOOL_SCROLL => self.scroll(&input).await?,
            TOOL_NEW_TAB => self.new_tab(&input).await?,
            TOOL_CLAIM_TAB => self.claim_tab(&input).await?,
            TOOL_MARK_TAB => self.mark_tab(&input).await?,
            TOOL_CDP_RAW => self.cdp_raw(&input).await?,
            other => return Err(tool_err(format!("unknown browser tool: {other}"))),
        };
        Ok(output.to_string())
    }
}

/// MCP-shaped metadata (`{name, description, inputSchema}`) for the browser
/// tools, for surfaces that advertise tool schemas. `_run_id` (injected into
/// the input JSON by the run wrapper for lease bookkeeping) is deliberately
/// never advertised, and the mutation-tool schemas tolerate extra properties
/// so the injection does not trip schema validation.
pub fn list_tool_metadata() -> Vec<Value> {
    // Optional on every tool: which browser backend to drive.
    let backend_prop = || {
        json!({
            "type": "string",
            "enum": ["chrome", "iab"],
            "default": "chrome",
            "description": "Browser backend to drive: \"chrome\" (the Chrome extension \
                bridge) or \"iab\" (the in-app browser). Default \"chrome\".",
        })
    };
    let mut tools = vec![
        json!({
            "name": TOOL_LIST_TABS,
            "description": "List open browser tabs (read-only). With no backend, \
                aggregates the chrome and iab backends; each entry is annotated with \
                its \"backend\". Returns {tabs: [{tabId, windowId, title, url, active, backend}]}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "backend": backend_prop(),
                },
                "additionalProperties": false,
            },
        }),
        json!({
            "name": TOOL_SNAPSHOT,
            "description": "Capture a text accessibility snapshot of a tab \
                (read-only; no navigation or interaction). Returns \
                {snapshot, truncated}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Target tab id from browser_list_tabs" },
                    "backend": backend_prop(),
                    "maxChars": {
                        "type": "integer",
                        "description": "Snapshot character budget",
                        "default": DEFAULT_MAX_CHARS,
                    },
                },
                "required": ["tabId"],
                "additionalProperties": false,
            },
        }),
        json!({
            "name": TOOL_SCREENSHOT,
            "description": "Capture a JPEG screenshot of a tab (read-only). \
                Returns {mimeType: \"image/jpeg\", dataBase64, width, height}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Target tab id from browser_list_tabs" },
                    "backend": backend_prop(),
                    "fullPage": {
                        "type": "boolean",
                        "description": "Capture the full scrollable page instead of the viewport",
                        "default": false,
                    },
                },
                "required": ["tabId"],
                "additionalProperties": false,
            },
        }),
        json!({
            "name": TOOL_CONSOLE_LOGS,
            "description": "Read recent console messages of a tab (read-only; \
                collected from Runtime.consoleAPICalled and Log.entryAdded \
                events). Returns {entries: [{level, text, timestamp}]}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Target tab id from browser_list_tabs" },
                    "backend": backend_prop(),
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of recent entries to return",
                        "default": DEFAULT_CONSOLE_LIMIT,
                    },
                },
                "required": ["tabId"],
                "additionalProperties": false,
            },
        }),
    ];
    // M2 mutation tools. Schemas omit `additionalProperties: false` on
    // purpose: the run wrapper injects `_run_id` into the input JSON.
    tools.extend([
        json!({
            "name": TOOL_NAVIGATE,
            "description": "Navigate a tab to a URL (mutating; http/https/about:blank \
                only, origin consent enforced by the run wrapper). Waits for the load \
                event (15s cap). Returns {url, title}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Target tab id from browser_list_tabs" },
                    "backend": backend_prop(),
                    "url": { "type": "string", "description": "http(s):// URL or about:blank" },
                },
                "required": ["tabId", "url"],
            },
        }),
        json!({
            "name": TOOL_CLICK,
            "description": "Click an element from a browser_snapshot ref (mutating). \
                Scrolls it into view, moves the virtual cursor, then dispatches a real \
                click. Returns {clicked, x, y}, or {error: \"stale_ref\"} when the ref \
                no longer resolves (call browser_snapshot again).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Target tab id from browser_list_tabs" },
                    "backend": backend_prop(),
                    "ref": { "type": "string", "description": "Element ref from browser_snapshot (e.g. \"e12\")" },
                },
                "required": ["tabId", "ref"],
            },
        }),
        json!({
            "name": TOOL_TYPE,
            "description": "Type text into an element from a browser_snapshot ref \
                (mutating). Focuses the element, optionally clears it first, inserts \
                the text, optionally presses Enter. mode \"insert\" (default) uses \
                Input.insertText — fast, full Unicode; mode \"keys\" dispatches \
                per-key rawKeyDown/keyUp events (US-layout ASCII only) — prefer it \
                for apps listening to keydown/keyup, keyboard shortcuts, or fields \
                that ignore synthetic text insertion. Returns {typed: <chars>}, or \
                {error: \"stale_ref\"} when the ref no longer resolves.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Target tab id from browser_list_tabs" },
                    "backend": backend_prop(),
                    "ref": { "type": "string", "description": "Element ref from browser_snapshot (e.g. \"e12\")" },
                    "text": { "type": "string", "description": "Text to insert" },
                    "mode": {
                        "type": "string",
                        "enum": ["insert", "keys"],
                        "default": "insert",
                        "description": "\"insert\" inserts the whole string (any Unicode); \
                            \"keys\" dispatches per-character key events (printable ASCII, \
                            Enter, Tab, Escape, Backspace, Delete) for apps that listen to \
                            keydown/keyup or shortcuts",
                    },
                    "clear": { "type": "boolean", "description": "Clear the field before typing", "default": false },
                    "pressEnter": { "type": "boolean", "description": "Send Enter after typing", "default": false },
                },
                "required": ["tabId", "ref", "text"],
            },
        }),
        json!({
            "name": TOOL_SCROLL,
            "description": "Scroll vertically (mutating) at an element ref's center, \
                or at the viewport center when no ref is given. Returns \
                {scrolled: deltaY}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Target tab id from browser_list_tabs" },
                    "backend": backend_prop(),
                    "ref": { "type": "string", "description": "Optional element ref from browser_snapshot" },
                    "deltaY": { "type": "number", "description": "Vertical scroll delta in CSS px (positive = down)" },
                },
                "required": ["tabId", "deltaY"],
            },
        }),
        json!({
            "name": TOOL_NEW_TAB,
            "description": "Open a new background tab in the run's \"MemStack Agent\" \
                tab group (mutating) and record an agent lease on it. Returns \
                {tabId, groupId}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "backend": backend_prop(),
                    "url": { "type": "string", "description": "Optional http(s):// URL or about:blank" },
                    "activate": { "type": "boolean", "description": "Focus the new tab", "default": false },
                },
            },
        }),
        json!({
            "name": TOOL_CLAIM_TAB,
            "description": "Adopt an existing user tab into the run as a user-origin \
                lease (mutating lease, tab is NOT grouped). Browser-internal tabs \
                (chrome:// etc.) are refused. Returns {tabId}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Tab id from browser_list_tabs" },
                    "backend": backend_prop(),
                },
                "required": ["tabId"],
            },
        }),
        json!({
            "name": TOOL_MARK_TAB,
            "description": "Mark a leased tab for end-of-turn handling (mutating \
                lease): \"handoff\" keeps it across turns, \"deliverable\" keeps it \
                ungrouped. Returns {tabId, mark}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Leased tab id" },
                    "backend": backend_prop(),
                    "mark": { "type": "string", "enum": ["handoff", "deliverable"] },
                },
                "required": ["tabId", "mark"],
            },
        }),
        json!({
            "name": TOOL_CDP_RAW,
            "description": "Execute a raw Chrome DevTools Protocol method on a tab \
                (mutating escape hatch for advanced use). Requires the desktop's \
                full-CDP enablement and per-origin approval (enforced by the \
                sidecar); even in full-access mode a hard policy denylist still \
                applies (e.g. the Storage / CacheStorage / Database / Target / \
                WebAuthn / Browser domains, Page.setBypassCSP, \
                Network.clearBrowserCookies). Returns {result}; serialized output \
                is capped at 4000 chars and oversized results are truncated with a \
                marker — truncating base64 payloads is acceptable because \
                browser_screenshot is the supported path for screenshots.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": { "type": "integer", "description": "Target tab id from browser_list_tabs" },
                    "backend": backend_prop(),
                    "method": { "type": "string", "description": "CDP method, e.g. \"Runtime.evaluate\"" },
                    "params": { "type": "object", "description": "Optional CDP params object" },
                },
                "required": ["tabId", "method"],
            },
        }),
    ]);
    tools
}

/// Scripted bridge endpoint shared by the host and action-tool tests:
/// responses are queued per bridge method, with `executeCdp` further keyed by
/// the CDP method inside the params (`"cdp:<Method>"`).
#[cfg(test)]
pub(crate) mod test_support {
    use super::*;
    use std::collections::VecDeque;

    pub(crate) struct MockEndpoint {
        pub(crate) responses: Mutex<HashMap<String, VecDeque<CoreResult<Value>>>>,
        pub(crate) requests: Mutex<Vec<(String, Value)>>,
        /// `(backend, method, params)` of every `request_on` call, in order
        /// (those calls are also recorded in `requests` via the delegate).
        pub(crate) backend_requests: Mutex<Vec<(String, String, Value)>>,
        pub(crate) notifications: broadcast::Sender<BridgeNotification>,
    }

    impl MockEndpoint {
        pub(crate) fn new() -> Self {
            Self {
                responses: Mutex::new(HashMap::new()),
                requests: Mutex::new(Vec::new()),
                backend_requests: Mutex::new(Vec::new()),
                notifications: broadcast::channel(16).0,
            }
        }

        pub(crate) fn script(self, method: &str, results: Vec<CoreResult<Value>>) -> Self {
            self.responses
                .lock()
                .unwrap()
                .insert(method.to_string(), results.into_iter().collect());
            self
        }

        pub(crate) fn count(&self, method: &str) -> usize {
            self.requests
                .lock()
                .unwrap()
                .iter()
                .filter(|(m, _)| m == method)
                .count()
        }

        /// Recorded params of every call to a bridge method, in order.
        pub(crate) fn params_of(&self, method: &str) -> Vec<Value> {
            self.requests
                .lock()
                .unwrap()
                .iter()
                .filter(|(m, _)| m == method)
                .map(|(_, p)| p.clone())
                .collect()
        }

        /// Recorded params of every `request_on(backend, method)` call, in
        /// order.
        pub(crate) fn backend_params_of(&self, backend: &str, method: &str) -> Vec<Value> {
            self.backend_requests
                .lock()
                .unwrap()
                .iter()
                .filter(|(b, m, _)| b == backend && m == method)
                .map(|(_, _, p)| p.clone())
                .collect()
        }
    }

    #[async_trait]
    impl BridgeEndpoint for MockEndpoint {
        async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
            self.requests
                .lock()
                .unwrap()
                .push((method.to_string(), params.clone()));
            let key = if method == METHOD_EXECUTE_CDP {
                format!(
                    "cdp:{}",
                    params.get("method").and_then(Value::as_str).unwrap_or("")
                )
            } else {
                method.to_string()
            };
            let mut responses = self.responses.lock().unwrap();
            let queue = responses
                .get_mut(&key)
                .unwrap_or_else(|| panic!("no scripted responses for {key}"));
            queue
                .pop_front()
                .unwrap_or_else(|| panic!("scripted responses for {key} exhausted"))
        }

        /// Records the backend, then shares the `request` scripting queues.
        async fn request_on(
            &self,
            backend: &str,
            method: &str,
            params: Value,
        ) -> CoreResult<Value> {
            self.backend_requests.lock().unwrap().push((
                backend.to_string(),
                method.to_string(),
                params.clone(),
            ));
            self.request(method, params).await
        }

        fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification> {
            self.notifications.subscribe()
        }
    }

    pub(crate) fn ok(value: Value) -> CoreResult<Value> {
        Ok(value)
    }
}

#[cfg(test)]
mod tests {
    use super::test_support::{ok, MockEndpoint};
    use super::*;

    #[tokio::test]
    async fn list_tabs_returns_bridge_payload() {
        // No backend → aggregate: one getTabs per backend (the mock's
        // request_on shares the same scripted queues).
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![
                ok(json!({"tabs": [{"tabId": 7, "windowId": 1, "title": "T", "url": "https://x", "active": true}]})),
                ok(json!({"tabs": []})),
            ],
        );
        let host = BrowserToolHost::new(endpoint);
        let out = host.call(TOOL_LIST_TABS, "{}").await.unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["tabs"][0]["tabId"], 7);
        assert_eq!(out["tabs"][0]["backend"], "chrome");
        assert_eq!(host.list_tools().len(), 12);
    }

    #[tokio::test]
    async fn snapshot_runs_cdp_sequence_and_truncates() {
        let long = "a".repeat(30);
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script(
                "cdp:Page.getFrameTree",
                vec![ok(
                    json!({"result": {"frameTree": {"frame": {"id": "F1"}}}}),
                )],
            )
            .script(
                "cdp:Page.createIsolatedWorld",
                vec![ok(json!({"result": {"executionContextId": 11}}))],
            )
            .script(
                "cdp:Runtime.evaluate",
                vec![ok(
                    json!({"result": {"result": {"type": "string", "value": long}}}),
                )],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_SNAPSHOT, r#"{"tabId": 7, "maxChars": 10}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(
            out["snapshot"],
            format!("{}\n… [truncated at 10 chars]", "a".repeat(10))
        );
        assert_eq!(out["truncated"], true);

        // The evaluate call must have run inside the isolated world.
        let requests = host.endpoint.requests.lock().unwrap();
        let evaluate = requests
            .iter()
            .find(|(_, p)| p.get("method") == Some(&json!("Runtime.evaluate")))
            .unwrap();
        assert_eq!(evaluate.1["params"]["contextId"], 11);
        let create_world = requests
            .iter()
            .find(|(_, p)| p.get("method") == Some(&json!("Page.createIsolatedWorld")))
            .unwrap();
        assert_eq!(create_world.1["params"]["frameId"], "F1");
    }

    #[tokio::test]
    async fn attach_is_memoized_per_tab() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.getLayoutMetrics", vec![
                ok(json!({"result": {"cssLayoutViewport": {"clientWidth": 800, "clientHeight": 600}}})),
                ok(json!({"result": {"cssLayoutViewport": {"clientWidth": 800, "clientHeight": 600}}})),
            ])
            .script("cdp:Page.captureScreenshot", vec![
                ok(json!({"result": {"data": "QUJD"}})),
                ok(json!({"result": {"data": "QUJD"}})),
            ]);
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_SCREENSHOT, r#"{"tabId": 7}"#).await.unwrap();
        host.call(TOOL_SCREENSHOT, r#"{"tabId": 7}"#).await.unwrap();
        assert_eq!(
            host.endpoint.count(METHOD_ATTACH),
            1,
            "attach must be idempotent on the host"
        );
    }

    #[tokio::test]
    async fn screenshot_full_page_uses_clip_and_beyond_viewport() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script(
                "cdp:Page.getLayoutMetrics",
                vec![ok(json!({
                    "result": {"cssContentSize": {"width": 1200.0, "height": 5000.0}}
                }))],
            )
            .script(
                "cdp:Page.captureScreenshot",
                vec![ok(json!({"result": {"data": "QUJD"}}))],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_SCREENSHOT, r#"{"tabId": 7, "fullPage": true}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["mimeType"], "image/jpeg");
        assert_eq!(out["dataBase64"], "QUJD");
        assert_eq!(out["width"], 1200);
        assert_eq!(out["height"], 5000);
        let requests = host.endpoint.requests.lock().unwrap();
        let capture = requests
            .iter()
            .find(|(_, p)| p.get("method") == Some(&json!("Page.captureScreenshot")))
            .unwrap();
        assert_eq!(capture.1["params"]["captureBeyondViewport"], true);
        assert_eq!(capture.1["params"]["clip"]["height"], 5000.0);
        assert_eq!(capture.1["params"]["format"], "jpeg");
        assert_eq!(capture.1["params"]["quality"], 80);
    }

    #[tokio::test]
    async fn console_logs_are_collected_from_notifications() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Runtime.enable", vec![ok(json!({"result": {}}))])
            .script("cdp:Log.enable", vec![ok(json!({"result": {}}))]);
        let host = BrowserToolHost::new(endpoint);

        // Inject one consoleAPICalled and one entryAdded event for tab 7.
        let tx = &host.endpoint.notifications;
        tx.send(BridgeNotification {
            method: NOTIFY_ON_CDP_EVENT.into(),
            params: json!({
                "tabId": 7,
                "method": "Runtime.consoleAPICalled",
                "params": {"type": "warn", "args": [{"value": "careful"}, {"value": 42}], "timestamp": 10.0}
            }),
        })
        .unwrap();
        tx.send(BridgeNotification {
            method: NOTIFY_ON_CDP_EVENT.into(),
            params: json!({
                "tabId": 7,
                "method": "Log.entryAdded",
                "params": {"entry": {"level": "error", "text": "boom", "timestamp": 11.0}}
            }),
        })
        .unwrap();

        // The feeder task is async; poll the tool until both entries land.
        let mut entries = Vec::new();
        for _ in 0..50 {
            let out = host
                .call(TOOL_CONSOLE_LOGS, r#"{"tabId": 7}"#)
                .await
                .unwrap();
            let out: Value = serde_json::from_str(&out).unwrap();
            entries = out["entries"].as_array().unwrap().clone();
            if entries.len() == 2 {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0]["level"], "warn");
        assert_eq!(entries[0]["text"], "careful 42");
        assert_eq!(entries[1]["level"], "error");
        assert_eq!(entries[1]["text"], "boom");
    }

    #[tokio::test]
    async fn detach_notification_clears_attach_memo() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({})), ok(json!({}))])
            .script("cdp:Page.getLayoutMetrics", vec![
                ok(json!({"result": {"cssLayoutViewport": {"clientWidth": 1, "clientHeight": 1}}})),
                ok(json!({"result": {"cssLayoutViewport": {"clientWidth": 1, "clientHeight": 1}}})),
            ])
            .script("cdp:Page.captureScreenshot", vec![
                ok(json!({"result": {"data": "QUJD"}})),
                ok(json!({"result": {"data": "QUJD"}})),
            ]);
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_SCREENSHOT, r#"{"tabId": 7}"#).await.unwrap();
        host.endpoint
            .notifications
            .send(BridgeNotification {
                method: NOTIFY_ON_CDP_DETACH.into(),
                params: json!({"tabId": 7, "reason": "target_closed"}),
            })
            .unwrap();
        // Let the feeder process the detach, then the next call re-attaches.
        for _ in 0..50 {
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            if !host
                .state
                .attached
                .lock()
                .unwrap()
                .contains(&(Backend::Chrome, 7))
            {
                break;
            }
        }
        host.call(TOOL_SCREENSHOT, r#"{"tabId": 7}"#).await.unwrap();
        assert_eq!(host.endpoint.count(METHOD_ATTACH), 2);
    }

    #[tokio::test]
    async fn unknown_tool_is_a_tool_error() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        let err = host.call("browser_eval", "{}").await.unwrap_err();
        assert!(matches!(err, CoreError::Tool(_)));
        assert!(err.to_string().contains("unknown browser tool"));
    }

    #[tokio::test]
    async fn endpoint_errors_propagate_as_tool_errors() {
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![Err(CoreError::Tool("bridge exploded".into()))],
        );
        let host = BrowserToolHost::new(endpoint);
        let err = host.call(TOOL_LIST_TABS, "{}").await.unwrap_err();
        assert_eq!(err.to_string(), "tool error: bridge exploded");
    }

    #[tokio::test]
    async fn missing_tab_id_is_rejected() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        let err = host.call(TOOL_SNAPSHOT, "{}").await.unwrap_err();
        assert!(err.to_string().contains("tabId"));
    }

    #[test]
    fn metadata_covers_all_tools_and_never_exposes_run_id() {
        let metadata = list_tool_metadata();
        assert_eq!(metadata.len(), 12);
        let names: Vec<&str> = metadata
            .iter()
            .map(|m| m["name"].as_str().unwrap())
            .collect();
        assert_eq!(
            names,
            [
                TOOL_LIST_TABS,
                TOOL_SNAPSHOT,
                TOOL_SCREENSHOT,
                TOOL_CONSOLE_LOGS,
                crate::actions::TOOL_NAVIGATE,
                crate::actions::TOOL_CLICK,
                crate::actions::TOOL_TYPE,
                crate::actions::TOOL_SCROLL,
                crate::actions::TOOL_NEW_TAB,
                crate::actions::TOOL_CLAIM_TAB,
                crate::actions::TOOL_MARK_TAB,
                TOOL_CDP_RAW,
            ]
        );
        for m in &metadata {
            assert_eq!(m["inputSchema"]["type"], "object");
            let serialized = m.to_string();
            assert!(
                !serialized.contains("_run_id"),
                "_run_id must never appear in advertised schemas: {serialized}"
            );
        }
        for m in &metadata[..4] {
            assert!(m["description"].as_str().unwrap().contains("read-only"));
        }
    }

    #[tokio::test]
    async fn cdp_raw_round_trips_an_allowed_method() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script(
                "cdp:Runtime.evaluate",
                vec![ok(
                    json!({"result": {"result": {"type": "number", "value": 2}}}),
                )],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Runtime.evaluate", "params": {"expression": "1+1"}}"#,
            )
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["result"]["result"]["value"], 2);
        assert!(out.get("truncated").is_none());

        // Params are forwarded to the bridge untouched.
        let params = host.endpoint.params_of(METHOD_EXECUTE_CDP);
        assert_eq!(params.len(), 1);
        assert_eq!(params[0]["tabId"], 7);
        assert_eq!(params[0]["method"], "Runtime.evaluate");
        assert_eq!(params[0]["params"]["expression"], "1+1");
    }

    #[tokio::test]
    async fn cdp_raw_rejects_hard_denied_methods() {
        let endpoint = MockEndpoint::new().script(METHOD_ATTACH, vec![ok(json!({}))]);
        let host = BrowserToolHost::new(endpoint);
        let err = host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Storage.getCookies"}"#,
            )
            .await
            .unwrap_err();
        assert!(err.to_string().contains("blocked by policy"));
        assert!(err.to_string().contains("Storage.getCookies"));
        assert_eq!(
            host.endpoint.count(METHOD_EXECUTE_CDP),
            0,
            "denied calls must never reach the bridge"
        );
    }

    #[tokio::test]
    async fn cdp_raw_allows_conservative_only_methods_in_full_access() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script(
                "cdp:Page.setDownloadBehavior",
                vec![ok(json!({"result": {}}))],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Page.setDownloadBehavior", "params": {"behavior": "allow"}}"#,
            )
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["result"], json!({}));
    }

    #[tokio::test]
    async fn cdp_raw_truncates_oversized_output() {
        let big = "x".repeat(5000);
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script(
                "cdp:Runtime.evaluate",
                vec![ok(json!({"result": {"data": big}}))],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Runtime.evaluate"}"#,
            )
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["truncated"], true);
        let result = out["result"].as_str().unwrap();
        assert!(
            result.contains("… [truncated at 4000 chars]"),
            "truncated output must carry the marker: {result}"
        );
        assert!(result.len() <= 4100);
    }

    #[tokio::test]
    async fn cdp_raw_validates_method_and_tab_id() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        for bad in [
            "",
            "runtime.evaluate",
            "RuntimeEvaluate",
            "Runtime.eval.u8",
            "Runtime.",
            "A.b",
        ] {
            let input = json!({"tabId": 7, "method": bad}).to_string();
            let err = host.call(TOOL_CDP_RAW, &input).await.unwrap_err();
            assert!(err.to_string().contains("invalid 'method'"), "{bad}: {err}");
        }
        for bad_tab in [
            json!({}),
            json!({"tabId": 0}),
            json!({"tabId": -3}),
            json!({"tabId": "7"}),
        ] {
            let mut input = bad_tab;
            input["method"] = json!("Runtime.evaluate");
            let err = host
                .call(TOOL_CDP_RAW, &input.to_string())
                .await
                .unwrap_err();
            assert!(err.to_string().contains("tabId"), "{input}: {err}");
        }
        // Validation failures must never reach the bridge.
        assert_eq!(host.endpoint.count(METHOD_EXECUTE_CDP), 0);
        assert_eq!(host.endpoint.count(METHOD_ATTACH), 0);
    }

    // ------------------------------------------------------------- backend

    #[tokio::test]
    async fn invalid_backend_is_rejected_before_any_bridge_call() {
        let host = BrowserToolHost::new(MockEndpoint::new());
        let cases: [(&str, Value); 13] = [
            (TOOL_LIST_TABS, json!({"backend": "firefox"})),
            (TOOL_LIST_TABS, json!({"backend": 5})),
            (TOOL_SNAPSHOT, json!({"tabId": 7, "backend": "firefox"})),
            (TOOL_SCREENSHOT, json!({"tabId": 7, "backend": "firefox"})),
            (TOOL_CONSOLE_LOGS, json!({"tabId": 7, "backend": "firefox"})),
            (
                TOOL_NAVIGATE,
                json!({"tabId": 7, "url": "https://x", "backend": "firefox"}),
            ),
            (
                TOOL_CLICK,
                json!({"tabId": 7, "ref": "e1", "backend": "firefox"}),
            ),
            (
                TOOL_TYPE,
                json!({"tabId": 7, "ref": "e1", "text": "hi", "backend": "firefox"}),
            ),
            (
                TOOL_SCROLL,
                json!({"tabId": 7, "deltaY": 100, "backend": "firefox"}),
            ),
            (TOOL_NEW_TAB, json!({"backend": "firefox"})),
            (TOOL_CLAIM_TAB, json!({"tabId": 7, "backend": "firefox"})),
            (
                TOOL_MARK_TAB,
                json!({"tabId": 7, "mark": "handoff", "backend": "firefox"}),
            ),
            (
                TOOL_CDP_RAW,
                json!({"tabId": 7, "method": "Runtime.evaluate", "backend": "firefox"}),
            ),
        ];
        for (tool, input) in cases {
            let err = host.call(tool, &input.to_string()).await.unwrap_err();
            assert!(err.to_string().contains("backend"), "{tool}: {err}");
        }
        assert!(host.endpoint.requests.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn iab_backend_routes_bridge_calls_through_request_on() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script("cdp:Page.getLayoutMetrics", vec![
                ok(json!({"result": {"cssLayoutViewport": {"clientWidth": 800, "clientHeight": 600}}})),
            ])
            .script(
                "cdp:Page.captureScreenshot",
                vec![ok(json!({"result": {"data": "QUJD"}}))],
            );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_SCREENSHOT, r#"{"tabId": 7, "backend": "iab"}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["dataBase64"], "QUJD");

        // Every bridge call went through request_on("iab", …).
        let routed = host.endpoint.backend_requests.lock().unwrap();
        assert_eq!(routed.len(), 3);
        assert!(routed.iter().all(|(backend, _, _)| backend == "iab"));
        assert_eq!(routed[0].1, METHOD_ATTACH);
    }

    #[tokio::test]
    async fn host_state_is_isolated_per_backend() {
        let frame_tree = || json!({"result": {"frameTree": {"frame": {"id": "F1"}}}});
        let snapshot_value = || json!({"result": {"result": {"type": "string", "value": "SNAP"}}});
        let endpoint = MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({})), ok(json!({}))])
            .script(
                "cdp:Page.getFrameTree",
                vec![ok(frame_tree()), ok(frame_tree())],
            )
            .script(
                "cdp:Page.createIsolatedWorld",
                vec![
                    ok(json!({"result": {"executionContextId": 11}})),
                    ok(json!({"result": {"executionContextId": 22}})),
                ],
            )
            .script(
                "cdp:Runtime.evaluate",
                vec![ok(snapshot_value()), ok(snapshot_value())],
            );
        let host = BrowserToolHost::new(endpoint);
        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7}"#).await.unwrap();
        host.call(TOOL_SNAPSHOT, r#"{"tabId": 7, "backend": "iab"}"#)
            .await
            .unwrap();

        // Same tabId on two backends: separate attach memos and world cache
        // entries.
        assert_eq!(host.endpoint.count(METHOD_ATTACH), 2);
        {
            let worlds = host.state.worlds.lock().unwrap();
            assert_eq!(worlds.len(), 2);
            assert_eq!(worlds[&(Backend::Chrome, 7, "F1".to_string())], 11);
            assert_eq!(worlds[&(Backend::Iab, 7, "F1".to_string())], 22);
        }
        // The iab snapshot ran entirely through request_on with its own
        // world (contextId 22).
        let iab_cdp = host.endpoint.backend_params_of("iab", METHOD_EXECUTE_CDP);
        assert_eq!(iab_cdp.len(), 3);
        let evaluate = iab_cdp
            .iter()
            .find(|p| p["method"] == "Runtime.evaluate")
            .unwrap();
        assert_eq!(evaluate["params"]["contextId"], 22);
    }

    #[tokio::test]
    async fn list_tabs_without_backend_aggregates_and_annotates() {
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![
                ok(json!({"tabs": [{"tabId": 7, "windowId": 1, "title": "C", "url": "https://c", "active": true}]})),
                ok(json!({"tabs": [{"tabId": 3, "windowId": 0, "title": "I", "url": "https://i", "active": true}]})),
            ],
        );
        let host = BrowserToolHost::new(endpoint);
        let out = host.call(TOOL_LIST_TABS, "{}").await.unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        let tabs = out["tabs"].as_array().unwrap();
        assert_eq!(tabs.len(), 2);
        assert_eq!(tabs[0]["tabId"], 7);
        assert_eq!(tabs[0]["backend"], "chrome");
        assert_eq!(tabs[1]["tabId"], 3);
        assert_eq!(tabs[1]["backend"], "iab");
        // Chrome went through `request`, iab through `request_on`.
        assert_eq!(host.endpoint.count(METHOD_GET_TABS), 2);
        assert_eq!(
            host.endpoint
                .backend_params_of("iab", METHOD_GET_TABS)
                .len(),
            1
        );
    }

    #[tokio::test]
    async fn list_tabs_with_explicit_backend_queries_only_that_backend() {
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![ok(json!({"tabs": [{"tabId": 3, "windowId": 0, "title": "I", "url": "https://i", "active": true}]}))],
        );
        let host = BrowserToolHost::new(endpoint);
        let out = host
            .call(TOOL_LIST_TABS, r#"{"backend": "iab"}"#)
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        let tabs = out["tabs"].as_array().unwrap();
        assert_eq!(tabs.len(), 1);
        assert_eq!(tabs[0]["backend"], "iab");
        // A single getTabs, via request_on — no chrome call.
        assert_eq!(host.endpoint.count(METHOD_GET_TABS), 1);
        assert_eq!(
            host.endpoint
                .backend_params_of("iab", METHOD_GET_TABS)
                .len(),
            1
        );
    }

    #[tokio::test]
    async fn list_tabs_tolerates_offline_iab_backend_when_aggregating() {
        // The sidecar registry fails closed for unregistered backends.
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![
                ok(json!({"tabs": [{"tabId": 7, "windowId": 1, "title": "C", "url": "https://c", "active": true}]})),
                Err(CoreError::Tool(
                    "browser bridge backend 'iab' is not connected".into(),
                )),
            ],
        );
        let host = BrowserToolHost::new(endpoint);
        let out = host.call(TOOL_LIST_TABS, "{}").await.unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        let tabs = out["tabs"].as_array().unwrap();
        assert_eq!(tabs.len(), 1);
        assert_eq!(tabs[0]["tabId"], 7);
        assert_eq!(tabs[0]["backend"], "chrome");
    }

    #[tokio::test]
    async fn list_tabs_propagates_other_iab_errors() {
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![
                ok(json!({"tabs": []})),
                Err(CoreError::Tool("iab bridge exploded".into())),
            ],
        );
        let host = BrowserToolHost::new(endpoint);
        let err = host.call(TOOL_LIST_TABS, "{}").await.unwrap_err();
        assert!(err.to_string().contains("iab bridge exploded"), "{err}");

        // An explicit iab query never swallows the offline error either.
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![Err(CoreError::Tool(
                "browser bridge backend 'iab' is not connected".into(),
            ))],
        );
        let host = BrowserToolHost::new(endpoint);
        let err = host
            .call(TOOL_LIST_TABS, r#"{"backend": "iab"}"#)
            .await
            .unwrap_err();
        assert!(err.to_string().contains("is not connected"), "{err}");
    }
}
