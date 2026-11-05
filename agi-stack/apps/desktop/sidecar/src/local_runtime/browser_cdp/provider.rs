//! Adapt browser-level CDP targets into the established integer-tab bridge contract.
use super::transport::Connection;
use agistack_adapters_browser::protocol::BridgeNotification;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};
use tokio::sync::broadcast;

#[derive(Default)]
struct Targets {
    next_tab: u64,
    tabs: HashMap<u64, Value>,
    ids: HashMap<String, u64>,
    sessions: HashMap<String, u64>,
    roots: HashMap<u64, String>,
    initialized_sessions: HashSet<String>,
    groups: HashMap<String, u64>,
    active: Option<u64>,
}

impl Targets {
    fn admit(&mut self, info: &Value) -> Option<u64> {
        if info["type"] != "page" {
            return None;
        }
        let target = info["targetId"].as_str()?;
        let tab = if let Some(tab) = self.ids.get(target) {
            *tab
        } else {
            self.next_tab = self.next_tab.checked_add(1)?;
            self.ids.insert(target.to_string(), self.next_tab);
            self.next_tab
        };
        self.tabs.insert(tab, info.clone());
        Some(tab)
    }
    fn remove(&mut self, target: &str) -> Option<u64> {
        let tab = self.ids.remove(target)?;
        self.tabs.remove(&tab);
        if let Some(root) = self.roots.remove(&tab) {
            self.initialized_sessions.remove(&root);
        }
        self.sessions.retain(|_, owner| *owner != tab);
        let sessions = &self.sessions;
        self.initialized_sessions
            .retain(|session| sessions.contains_key(session));
        if self.active == Some(tab) {
            self.active = None;
        }
        Some(tab)
    }
}

pub(super) struct Provider {
    pub(super) identity: String,
    pub(super) connection: Arc<Connection>,
    targets: Mutex<Targets>,
    attachment: tokio::sync::Mutex<()>,
    notifications: broadcast::Sender<BridgeNotification>,
}

impl Provider {
    pub(super) fn new(
        identity: String,
        connection: Arc<Connection>,
        notifications: broadcast::Sender<BridgeNotification>,
    ) -> Arc<Self> {
        Arc::new(Self {
            identity,
            connection,
            targets: Mutex::new(Targets::default()),
            attachment: tokio::sync::Mutex::new(()),
            notifications,
        })
    }
    pub(super) async fn initialize(&self) -> Result<(), String> {
        self.connection
            .request("Target.setDiscoverTargets", json!({"discover":true}), None)
            .await?;
        self.refresh().await
    }
    async fn refresh(&self) -> Result<(), String> {
        let result = self
            .connection
            .request("Target.getTargets", json!({}), None)
            .await?;
        let infos = result["targetInfos"]
            .as_array()
            .ok_or("cdp_target_inventory_invalid")?;
        let mut state = self.targets.lock().expect("cdp targets");
        let live: HashSet<_> = infos
            .iter()
            .filter(|info| info["type"] == "page")
            .filter_map(|info| info["targetId"].as_str())
            .collect();
        let removed: Vec<_> = state
            .ids
            .keys()
            .filter(|target| !live.contains(target.as_str()))
            .cloned()
            .collect();
        for target in removed {
            if let Some(tab) = state.remove(&target) {
                self.detached(tab, "target_closed");
            }
        }
        for info in infos {
            state.admit(info);
        }
        Ok(())
    }
    fn detached(&self, tab: u64, reason: &str) {
        let _ = self.notifications.send(BridgeNotification {
            method: "onCDPDetach".into(),
            params: json!({"backend":self.identity,"tabId":tab,"reason":reason}),
        });
    }
    fn target(&self, tab: u64) -> Result<String, String> {
        self.targets
            .lock()
            .expect("cdp targets")
            .tabs
            .get(&tab)
            .and_then(|info| info["targetId"].as_str())
            .map(str::to_owned)
            .ok_or_else(|| "cdp_tab_expired".into())
    }
    async fn attach(&self, tab: u64) -> Result<String, String> {
        let _lock = self.attachment.lock().await;
        let existing = {
            let state = self.targets.lock().expect("cdp targets");
            let session = state.roots.get(&tab).cloned();
            if session
                .as_ref()
                .is_some_and(|id| state.initialized_sessions.contains(id))
            {
                return Ok(session.expect("checked root"));
            }
            session
        };
        let session = if let Some(session) = existing {
            session
        } else {
            let target = self.target(tab)?;
            let result = self
                .connection
                .request(
                    "Target.attachToTarget",
                    json!({"targetId":target,"flatten":true}),
                    None,
                )
                .await?;
            result["sessionId"]
                .as_str()
                .ok_or("cdp_attach_failed")?
                .to_string()
        };
        {
            let mut state = self.targets.lock().expect("cdp targets");
            if !state.tabs.contains_key(&tab) {
                return Err("cdp_tab_expired".into());
            }
            state.sessions.insert(session.clone(), tab);
            state.roots.insert(tab, session.clone());
        }
        self.initialize_session(&session).await?;
        Ok(session)
    }
    async fn initialize_session(&self, session: &str) -> Result<(), String> {
        if self
            .targets
            .lock()
            .expect("cdp targets")
            .initialized_sessions
            .contains(session)
        {
            return Ok(());
        }
        self.connection
            .request(
                "Target.setAutoAttach",
                json!({"autoAttach":true,"waitForDebuggerOnStart":false,"flatten":true}),
                Some(session),
            )
            .await?;
        let mut state = self.targets.lock().expect("cdp targets");
        if !state.sessions.contains_key(session) {
            return Err("cdp_session_expired".into());
        }
        state.initialized_sessions.insert(session.to_string());
        Ok(())
    }
    pub(super) async fn run(&self, mut events: broadcast::Receiver<Value>) {
        loop {
            tokio::select! {
                _ = self.connection.closed() => break,
                event = events.recv() => match event {
                    Ok(event) => {
                        let child = (event["method"] == "Target.attachedToTarget" && event["sessionId"].is_string()
                            && matches!(event["params"]["targetInfo"]["type"].as_str(),Some("iframe"|"page")))
                            .then(|| event["params"]["sessionId"].as_str().map(str::to_string)).flatten();
                        self.on_event(event);
                        if let Some(child) = child {
                            let owned = self.targets.lock().expect("cdp targets").sessions.contains_key(&child);
                            if owned && self.initialize_session(&child).await.is_err() { self.connection.close(); break; }
                        }
                    },
                    // Losing a session identity makes future frame dispatch uncertain.
                    Err(_) => { self.connection.close(); break; },
                }
            }
        }
    }
    fn on_event(&self, event: Value) {
        let Some(method) = event["method"].as_str() else {
            return;
        };
        let params = &event["params"];
        let mut state = self.targets.lock().expect("cdp targets");
        match method {
            "Target.targetCreated" | "Target.targetInfoChanged" => {
                state.admit(&params["targetInfo"]);
            }
            "Target.targetDestroyed" => {
                if let Some(target) = params["targetId"].as_str() {
                    if let Some(tab) = state.remove(target) {
                        self.detached(tab, "target_closed");
                    }
                }
            }
            _ => {}
        }
        let outer = event["sessionId"].as_str();
        let mut owner = outer.and_then(|id| state.sessions.get(id).copied());
        if method == "Target.attachedToTarget" {
            if owner.is_none() {
                owner = params["targetInfo"]["targetId"]
                    .as_str()
                    .and_then(|id| state.ids.get(id).copied());
            }
            if let (Some(tab), Some(child)) = (owner, params["sessionId"].as_str()) {
                state.sessions.insert(child.to_string(), tab);
                if outer.is_none() {
                    state.roots.entry(tab).or_insert_with(|| child.to_string());
                }
            }
        }
        if method == "Target.detachedFromTarget" {
            if let Some(session) = params["sessionId"].as_str() {
                let detached_owner = state.sessions.remove(session);
                state.initialized_sessions.remove(session);
                owner = owner.or(detached_owner);
                if let Some(tab) = detached_owner {
                    if state.roots.get(&tab).is_some_and(|root| root == session) {
                        state.roots.remove(&tab);
                        state.sessions.retain(|_, owner| *owner != tab);
                        let remaining: HashSet<_> = state.sessions.keys().cloned().collect();
                        state
                            .initialized_sessions
                            .retain(|id| remaining.contains(id));
                        self.detached(tab, "debugger_detached");
                    }
                }
            }
        }
        let Some(tab) = owner else {
            return;
        };
        // Browser-level root attachments are transport details. Only actual
        // descendants belong in the tab's public target-event stream.
        if outer.is_none() {
            return;
        }
        let child = outer.filter(|id| state.roots.get(&tab).is_none_or(|root| root != *id));
        let mut wire = json!({"backend":self.identity,"tabId":tab,"method":method,"params":params});
        if let Some(child) = child {
            wire["sessionId"] = json!(child);
        }
        let _ = self.notifications.send(BridgeNotification {
            method: "onCDPEvent".into(),
            params: wire,
        });
    }

    pub(super) async fn request(&self, method: &str, params: Value) -> Result<Value, String> {
        if self.connection.is_closed() {
            return Err("cdp_connection_closed".into());
        }
        match method {
            "ping" => Ok(json!({})),
            "getTabs" => {
                self.refresh().await?;
                let state = self.targets.lock().expect("cdp targets");
                let mut tabs = state.tabs.iter().map(|(id, info)| json!({"tabId":id,"windowId":0,"title":info["title"],"url":info["url"],"active":state.active==Some(*id)})).collect::<Vec<_>>();
                tabs.sort_by_key(|tab| tab["tabId"].as_u64());
                Ok(json!({"tabs":tabs}))
            }
            "attach" => {
                self.attach(tab_id(&params)?).await?;
                Ok(json!({}))
            }
            "detach" => {
                let tab = tab_id(&params)?;
                let session = self
                    .targets
                    .lock()
                    .expect("cdp targets")
                    .roots
                    .get(&tab)
                    .cloned();
                if let Some(session) = session {
                    self.connection
                        .request(
                            "Target.detachFromTarget",
                            json!({"sessionId":session}),
                            None,
                        )
                        .await?;
                }
                Ok(json!({}))
            }
            "executeCdp" => {
                let tab = tab_id(&params)?;
                self.target(tab)?;
                let session = if let Some(session) = params["sessionId"].as_str() {
                    if self
                        .targets
                        .lock()
                        .expect("cdp targets")
                        .sessions
                        .get(session)
                        != Some(&tab)
                    {
                        return Err("cdp_session_not_owned_by_tab".into());
                    }
                    session.to_string()
                } else {
                    self.attach(tab).await?
                };
                let method = params["method"].as_str().ok_or("cdp_method_invalid")?;
                let result = self
                    .connection
                    .request(
                        method,
                        params.get("params").cloned().unwrap_or(json!({})),
                        Some(&session),
                    )
                    .await?;
                Ok(json!({"result":result}))
            }
            "createTab" => {
                let url = params["url"].as_str().unwrap_or("about:blank");
                let created = self
                    .connection
                    .request(
                        "Target.createTarget",
                        json!({"url":url,"background":params["active"]!=true}),
                        None,
                    )
                    .await?;
                let target = created["targetId"]
                    .as_str()
                    .ok_or("cdp_create_target_failed")?;
                self.refresh().await?;
                let tab = *self
                    .targets
                    .lock()
                    .expect("cdp targets")
                    .ids
                    .get(target)
                    .ok_or("cdp_create_target_failed")?;
                if params["active"] == true {
                    self.targets.lock().expect("cdp targets").active = Some(tab);
                }
                Ok(json!({"tabId":tab}))
            }
            "closeTab" => {
                self.close_tab(tab_id(&params)?).await?;
                Ok(json!({}))
            }
            "focusTab" => {
                let tab = tab_id(&params)?;
                self.connection
                    .request(
                        "Target.activateTarget",
                        json!({"targetId":self.target(tab)?}),
                        None,
                    )
                    .await?;
                self.targets.lock().expect("cdp targets").active = Some(tab);
                Ok(json!({}))
            }
            "facadeCapabilities" => Ok(json!({"browser":[],"tab":["cdp","pageAssets","webmcp"]})),
            // These are host lease/session bookkeeping, not browser tab-group APIs.
            "ensureTabGroup" => {
                let key = params["key"].as_str().ok_or("cdp_session_key_invalid")?;
                let mut state = self.targets.lock().expect("cdp targets");
                let next = u64::try_from(state.groups.len())
                    .map_err(|_| "cdp_session_limit")?
                    .checked_add(1)
                    .ok_or("cdp_session_limit")?;
                let group = *state.groups.entry(key.to_string()).or_insert(next);
                Ok(json!({"groupId":group}))
            }
            "assignTab" | "ungroupTab" => {
                self.target(tab_id(&params)?)?;
                Ok(json!({}))
            }
            "nameSession" => Ok(json!({})),
            "moveMouse" => {
                let session = self.attach(tab_id(&params)?).await?;
                let x = params["x"]
                    .as_f64()
                    .filter(|value| value.is_finite())
                    .ok_or("cdp_pointer_invalid")?;
                let y = params["y"]
                    .as_f64()
                    .filter(|value| value.is_finite())
                    .ok_or("cdp_pointer_invalid")?;
                self.connection
                    .request(
                        "Input.dispatchMouseEvent",
                        json!({"type":"mouseMoved","x":x,"y":y,"button":"none"}),
                        Some(&session),
                    )
                    .await?;
                Ok(json!({}))
            }
            "turnEnded" => {
                let mut closed = 0;
                for lease in params["leases"].as_array().ok_or("cdp_leases_invalid")? {
                    if lease["origin"] == "agent" && lease.get("mark").is_none_or(Value::is_null) {
                        self.close_tab(tab_id(lease)?).await?;
                        closed += 1;
                    }
                }
                Ok(json!({"closed":closed,"ungrouped":0}))
            }
            _ => Err("cdp_provider_operation_unavailable".into()),
        }
    }
    async fn close_tab(&self, tab: u64) -> Result<(), String> {
        let target = self.target(tab)?;
        let result = self
            .connection
            .request("Target.closeTarget", json!({"targetId":target}), None)
            .await?;
        if result["success"] != true {
            return Err("cdp_close_target_failed".into());
        }
        self.targets.lock().expect("cdp targets").remove(&target);
        self.detached(tab, "target_closed");
        Ok(())
    }
}

fn tab_id(params: &Value) -> Result<u64, String> {
    params["tabId"]
        .as_u64()
        .filter(|id| *id > 0)
        .ok_or_else(|| "cdp_tab_id_invalid".into())
}
