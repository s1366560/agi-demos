//! Host-only credential handoff. These entry points are never exposed as generic browser tools.
use crate::host::{Backend, BridgeEndpoint, BrowserToolHost, HostState, backend_of, tool_err};
use agistack_core::ports::CoreResult;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;

#[derive(Clone)]
pub(crate) struct Protection {
    request_id: String,
    loader_id: String,
    input_started: bool,
}

#[derive(Clone)]
struct Target {
    id: String,
    role: &'static str,
    spec: Value,
    session: Option<String>,
    object: String,
}
pub struct PreparedAuth {
    backend: Backend,
    tab: u64,
    request_id: String,
    origin: String,
    request: Value,
    targets: Vec<Target>,
    endpoint: Arc<dyn BridgeEndpoint>,
    state: Arc<HostState>,
}

impl Drop for PreparedAuth {
    fn drop(&mut self) {
        if let Ok(mut protected) = self.state.browser_auth.lock() {
            if protected
                .get(&(self.backend, self.tab))
                .is_some_and(|value| value.request_id == self.request_id && !value.input_started)
            {
                protected.remove(&(self.backend, self.tab));
            }
        }
        let endpoint = self.endpoint.clone();
        let targets = self.targets.clone();
        let backend = self.backend;
        let tab = self.tab;
        if let Ok(runtime) = tokio::runtime::Handle::try_current() {
            runtime.spawn(async move {
                for target in targets {
                    let mut params=json!({"tabId":tab,"method":"Runtime.releaseObject","params":{"objectId":target.object}});
                    if let Some(session)=target.session {params["sessionId"]=json!(session);}
                    let request=async {if backend==Backend::Chrome {endpoint.request("executeCdp",params).await}
                        else {endpoint.request_on(&backend.wire_name(),"executeCdp",params).await}};
                    let _=tokio::time::timeout(std::time::Duration::from_secs(2),request).await;
                }
            });
        }
    }
}

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub fn has_protected_auth(&self) -> bool {
        self.state
            .browser_auth
            .lock()
            .map_or(true, |protected| !protected.is_empty())
    }
    pub async fn prepare_browser_auth(
        &self,
        backend_name: &str,
        tab: u64,
        request_id: &str,
        request: &Value,
    ) -> CoreResult<PreparedAuth> {
        let backend = backend_of(&json!({"backend":backend_name}))?;
        self.ensure_attached(backend, tab).await?;
        let tree = self
            .execute_cdp(backend, tab, "Page.getFrameTree", json!({}))
            .await?;
        let loader = tree["frameTree"]["frame"]["loaderId"]
            .as_str()
            .filter(|value| !value.is_empty())
            .ok_or_else(|| tool_err("page_changed"))?;
        {
            let mut protected = self
                .state
                .browser_auth
                .lock()
                .map_err(|_| tool_err("unavailable"))?;
            if protected.contains_key(&(backend, tab)) {
                return Err(tool_err("browser_auth_already_pending_or_protected"));
            }
            protected.insert(
                (backend, tab),
                Protection {
                    request_id: request_id.into(),
                    loader_id: loader.into(),
                    input_started: false,
                },
            );
        }
        let mut prepared = PreparedAuth {
            backend,
            tab,
            request_id: request_id.into(),
            origin: request["origin"]
                .as_str()
                .ok_or_else(|| tool_err("origin_changed"))?
                .into(),
            request: request.clone(),
            targets: Vec::new(),
            endpoint: self.endpoint.clone(),
            state: self.state.clone(),
        };
        let result = self.prepare_auth_targets(&mut prepared).await;
        if let Err(error) = result {
            self.finish_browser_auth(&prepared, false).await;
            return Err(error);
        }
        Ok(prepared)
    }

    async fn prepare_auth_targets(&self, prepared: &mut PreparedAuth) -> CoreResult<()> {
        let mut targets = Vec::new();
        for field in prepared.request["fields"].as_array().into_iter().flatten() {
            targets.push((
                "field",
                field["id"].as_str().unwrap_or_default().to_owned(),
                field.clone(),
            ));
        }
        for option in prepared.request["options"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|option| !option["selector"].is_null())
        {
            targets.push((
                "option",
                option["id"].as_str().unwrap_or_default().to_owned(),
                option.clone(),
            ));
        }
        if let Some(submit) = prepared
            .request
            .get("submit")
            .filter(|value| !value.is_null())
        {
            targets.push(("submit", "submit".into(), submit.clone()));
        }
        for (role, id, spec) in targets {
            let steps = spec["selector"]["steps"]
                .as_array()
                .ok_or_else(|| tool_err("locator_invalid"))?;
            let context = self
                .facade_frame_context(&prepared.backend.as_str(), prepared.tab, steps)
                .await
                .map_err(|_| tool_err("locator_invalid"))?;
            let expression = crate::facade::dom_expression(
                "playwright.resolveElement",
                &json!([context.steps]),
            )?;
            let result = self.execute_cdp_session(prepared.backend,prepared.tab,context.session_id.as_deref(),"Runtime.evaluate",json!({"expression":expression,"contextId":context.context_id,"returnByValue":false,"awaitPromise":true})).await.map_err(|_| tool_err("locator_invalid"))?;
            let object = result["result"]["objectId"]
                .as_str()
                .ok_or_else(|| tool_err("locator_invalid"))?
                .to_owned();
            prepared.targets.push(Target {
                id,
                role,
                spec,
                session: context.session_id,
                object,
            });
            let target = prepared
                .targets
                .last()
                .ok_or_else(|| tool_err("locator_invalid"))?;
            self.auth_element(prepared, target, "validate", None)
                .await?;
        }
        Ok(())
    }

    async fn auth_element(
        &self,
        prepared: &PreparedAuth,
        target: &Target,
        action: &str,
        value: Option<&str>,
    ) -> CoreResult<()> {
        let current = self
            .state
            .browser_auth
            .lock()
            .map_err(|_| tool_err("unavailable"))?
            .get(&(prepared.backend, prepared.tab))
            .is_some_and(|value| value.request_id == prepared.request_id);
        if !current {
            return Err(tool_err("page_changed"));
        }
        let params = json!({"objectId":target.object,"functionDeclaration":include_str!("../assets/browser-auth-element.js"),"arguments":[{"value":{"action":action,"role":target.role,"spec":target.spec,"origin":prepared.origin,"value":value}}],"returnByValue":true,"awaitPromise":true,"userGesture":action != "validate"});
        let result = self
            .execute_cdp_session(
                prepared.backend,
                prepared.tab,
                target.session.as_deref(),
                "Runtime.callFunctionOn",
                params,
            )
            .await
            .map_err(|_| tool_err("page_changed"))?;
        match result["result"]["value"]["status"].as_str() {
            Some("ready" | "filled" | "focused" | "submitted") => Ok(()),
            Some("origin_changed") => Err(tool_err("origin_changed")),
            Some("locator_invalid") => Err(tool_err("locator_invalid")),
            _ => Err(tool_err("page_changed")),
        }
    }

    async fn validate_auth_document(&self, prepared: &PreparedAuth) -> CoreResult<()> {
        let loader = self
            .state
            .browser_auth
            .lock()
            .map_err(|_| tool_err("unavailable"))?
            .get(&(prepared.backend, prepared.tab))
            .filter(|value| value.request_id == prepared.request_id)
            .map(|value| value.loader_id.clone())
            .ok_or_else(|| tool_err("page_changed"))?;
        let tree = self
            .execute_cdp(
                prepared.backend,
                prepared.tab,
                "Page.getFrameTree",
                json!({}),
            )
            .await?;
        if tree["frameTree"]["frame"]["loaderId"] != loader {
            return Err(tool_err("page_changed"));
        }
        let origin = tree["frameTree"]["frame"]["url"]
            .as_str()
            .and_then(|url| url::Url::parse(url).ok())
            .map(|url| url.origin().ascii_serialization());
        if origin.as_deref() != Some(&prepared.origin) {
            return Err(tool_err("origin_changed"));
        }
        Ok(())
    }

    /// Captures the current authentication screen solely for the trusted native UI.
    pub async fn browser_auth_qr_image(&self, prepared: &PreparedAuth) -> CoreResult<String> {
        if prepared.request["qr_code"] != true {
            return Err(tool_err("unavailable"));
        }
        self.validate_auth_document(prepared).await?;
        let result = self
            .execute_cdp(
                prepared.backend,
                prepared.tab,
                "Page.captureScreenshot",
                json!({"format":"png","captureBeyondViewport":false}),
            )
            .await?;
        let data = result["data"]
            .as_str()
            .filter(|data| !data.is_empty() && data.len() <= 8 * 1024 * 1024)
            .ok_or_else(|| tool_err("unavailable"))?;
        self.validate_auth_document(prepared).await?;
        Ok(format!("data:image/png;base64,{data}"))
    }

    pub async fn submit_browser_auth(
        &self,
        prepared: &PreparedAuth,
        selected: Option<&str>,
        values: &BTreeMap<String, String>,
    ) -> CoreResult<Value> {
        self.validate_auth_document(prepared).await?;
        if prepared.request["qr_code"] == true {
            if selected.is_some() || !values.is_empty() {
                return Err(tool_err("unavailable"));
            }
            return Ok(json!({"status":"submitted"}));
        }
        // Revalidate all pinned elements before the first input operation.
        for target in &prepared.targets {
            self.auth_element(prepared, target, "validate", None)
                .await?;
        }
        let option = prepared.request["options"].as_array().and_then(|options| {
            options
                .iter()
                .find(|option| option["id"].as_str() == selected)
        });
        if let Some(option) = option.filter(|option| !option["selector"].is_null()) {
            let target = prepared
                .targets
                .iter()
                .find(|target| {
                    target.role == "option"
                        && target.id == option["id"].as_str().unwrap_or_default()
                })
                .ok_or_else(|| tool_err("locator_invalid"))?;
            self.auth_element(prepared, target, "click", None).await?;
            return Ok(json!({"status":"submitted","selected_option":selected}));
        }
        {
            let mut protected = self
                .state
                .browser_auth
                .lock()
                .map_err(|_| tool_err("unavailable"))?;
            let current = protected
                .get_mut(&(prepared.backend, prepared.tab))
                .filter(|value| value.request_id == prepared.request_id)
                .ok_or_else(|| tool_err("page_changed"))?;
            current.input_started = true;
        }
        for target in prepared
            .targets
            .iter()
            .filter(|target| target.role == "field")
        {
            if let Some(value) = values.get(&target.id) {
                self.auth_element(prepared, target, "fill", Some(value))
                    .await?;
            }
        }
        if let Some(target) = prepared
            .targets
            .iter()
            .find(|target| target.role == "submit")
        {
            let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
            let action = if target.spec["action"] == "press_enter" {
                "focus"
            } else {
                "click"
            };
            loop {
                match self.auth_element(prepared, target, action, None).await {
                    Ok(()) => break,
                    Err(error)
                        if error.to_string().contains("locator_invalid")
                            && tokio::time::Instant::now() < deadline =>
                    {
                        tokio::time::sleep(std::time::Duration::from_millis(50)).await
                    }
                    Err(error) => return Err(error),
                }
            }
            if action == "focus" {
                for kind in ["keyDown", "keyUp"] {
                    self.execute_cdp_session(prepared.backend,prepared.tab,target.session.as_deref(),"Input.dispatchKeyEvent",json!({"type":kind,"key":"Enter","code":"Enter","windowsVirtualKeyCode":13,"nativeVirtualKeyCode":13})).await.map_err(|_| tool_err("submission_failed"))?;
                }
            }
        }
        Ok(json!({"status":"submitted","selected_option":selected}))
    }

    pub async fn finish_browser_auth(&self, prepared: &PreparedAuth, preserve: bool) {
        for target in &prepared.targets {
            let _ = self
                .execute_cdp_session(
                    prepared.backend,
                    prepared.tab,
                    target.session.as_deref(),
                    "Runtime.releaseObject",
                    json!({"objectId":target.object}),
                )
                .await;
        }
        if let Ok(mut protected) = self.state.browser_auth.lock() {
            if protected
                .get(&(prepared.backend, prepared.tab))
                .is_some_and(|value| {
                    value.request_id == prepared.request_id && !preserve && !value.input_started
                })
            {
                protected.remove(&(prepared.backend, prepared.tab));
            }
        }
    }

    pub(crate) fn auth_guard(
        &self,
        tool: &str,
        input: &Value,
    ) -> CoreResult<Option<(Backend, u64, String)>> {
        let protected = self
            .state
            .browser_auth
            .lock()
            .map_err(|_| tool_err("browser_auth_unavailable"))?;
        if protected.is_empty() {
            return Ok(None);
        }
        let operation = input["operation"].as_str();
        let tab = input["tabId"]
            .as_u64()
            .or_else(|| input["tabId"].as_str().and_then(|value| value.parse().ok()));
        let normalized = crate::facade::normalize_input(input)?;
        let backend = backend_of(&normalized)?;
        let Some(tab) = tab else {
            if input.get("backend").is_none() && input.get("browserId").is_none()
                || protected.keys().any(|(browser, _)| *browser == backend)
            {
                return Err(tool_err(
                    "browser_auth_protected: explicit navigation is required before further observation",
                ));
            }
            return Ok(None);
        };
        let Some(protection) = protected.get(&(backend, tab)) else {
            return Ok(None);
        };
        if tool == crate::actions::TOOL_NAVIGATE
            || (tool == crate::facade::TOOL_WRITE && operation == Some("tab.goto"))
        {
            return Ok(Some((backend, tab, protection.loader_id.clone())));
        }
        Err(tool_err(
            "browser_auth_protected: explicit navigation is required before further observation",
        ))
    }

    pub(crate) async fn auth_after_navigation(
        &self,
        backend: Backend,
        tab: u64,
        previous: &str,
    ) -> CoreResult<()> {
        let tree = self
            .execute_cdp(backend, tab, "Page.getFrameTree", json!({}))
            .await?;
        let current = tree["frameTree"]["frame"]["loaderId"]
            .as_str()
            .filter(|value| !value.is_empty())
            .ok_or_else(|| tool_err("browser_auth_protected"))?;
        if current == previous {
            return Err(tool_err(
                "browser_auth_protected: navigation did not replace the credential document",
            ));
        }
        self.state
            .browser_auth
            .lock()
            .map_err(|_| tool_err("browser_auth_unavailable"))?
            .remove(&(backend, tab));
        self.state
            .console_buffers
            .lock()
            .map_err(|_| tool_err("browser_auth_unavailable"))?
            .remove(&(backend, tab));
        self.state
            .facade_events
            .lock()
            .map_err(|_| tool_err("browser_auth_unavailable"))?
            .remove(&(backend, tab));
        Ok(())
    }
}
