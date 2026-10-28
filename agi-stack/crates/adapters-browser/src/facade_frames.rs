//! Resolve frame locators through CDP-owned frame identities, including OOPIFs.
use crate::host::{Backend, BridgeEndpoint, BrowserToolHost, tool_err};
use agistack_core::ports::CoreResult;
use serde_json::{Value, json};

pub struct FacadeFrameContext {
    pub session_id: Option<String>,
    pub context_id: u64,
    pub frame_id: String,
    pub loader_id: String,
    pub url: String,
    pub steps: Vec<Value>,
}

fn frame(tree: &Value, id: &str) -> Option<Value> {
    if tree["frame"]["id"] == id {
        return Some(tree["frame"].clone());
    }
    tree["childFrames"]
        .as_array()?
        .iter()
        .find_map(|child| frame(child, id))
}

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub(crate) async fn facade_locator_click(
        &self,
        backend: Backend,
        tab: u64,
        args: &[Value],
    ) -> CoreResult<Value> {
        self.with_input_visibility(backend, tab, self.facade_locator_click_prepared(backend, tab, args)).await
    }

    async fn facade_locator_click_prepared(
        &self, backend: Backend, tab: u64, args: &[Value],
    ) -> CoreResult<Value> {
        let steps = args
            .first()
            .and_then(Value::as_array)
            .ok_or_else(|| tool_err("locator steps required"))?;
        let scope = self
            .facade_frame_context(&backend.as_str(), tab, steps)
            .await?;
        let options = args
            .get(2)
            .and_then(|values| values.get(0))
            .cloned()
            .unwrap_or(json!({}));
        let expression = super::facade::dom_expression(
            "playwright.locator",
            &json!([scope.steps, "clickPoint", [options]]),
        )?;
        let result=self.execute_cdp_session(backend,tab,scope.session_id.as_deref(),"Runtime.evaluate",json!({"expression":expression,"contextId":scope.context_id,"returnByValue":true,"awaitPromise":true})).await?;
        if let Some(exception) = result.get("exceptionDetails") {
            return Err(tool_err(
                exception["exception"]["description"]
                    .as_str()
                    .unwrap_or("click target unavailable"),
            ));
        }
        self.facade_mouse_click(
            backend,
            tab,
            scope.session_id.as_deref(),
            &result["result"]["value"],
            &options,
            args.get(1).and_then(Value::as_str) == Some("dblclick"),
        )
        .await
    }

    pub async fn facade_frame_context(
        &self,
        backend_name: &str,
        tab: u64,
        steps: &[Value],
    ) -> CoreResult<FacadeFrameContext> {
        let backend = crate::host::backend_of(&json!({"backend":backend_name}))?;
        self.ensure_attached(backend, tab).await?;
        self.ensure_page_enabled(backend, tab).await?;
        let (mut frame_id, mut context_id) = self.world_context(backend, tab).await?;
        let mut session: Option<String> = None;
        let mut remaining = steps.to_vec();
        while let Some(index) = remaining
            .iter()
            .position(|step| step["kind"] == "frameLocator")
        {
            self.ensure_facade_targets(backend, tab).await?;
            let mut selector = remaining[..=index].to_vec();
            selector[index]["kind"] = json!("locator");
            let expression =
                super::facade::dom_expression("playwright.resolveElement", &json!([selector]))?;
            let result = self.execute_cdp_session(backend,tab,session.as_deref(),"Runtime.evaluate",json!({"expression":expression,"contextId":context_id,"returnByValue":false,"awaitPromise":true})).await?;
            if result.get("exceptionDetails").is_some() {
                return Err(tool_err("frame locator is missing or ambiguous"));
            }
            let object = result["result"]["objectId"]
                .as_str()
                .ok_or_else(|| tool_err("frame locator did not resolve an element"))?;
            let described = self
                .execute_cdp_session(
                    backend,
                    tab,
                    session.as_deref(),
                    "DOM.describeNode",
                    json!({"objectId":object}),
                )
                .await;
            let _ = self
                .execute_cdp_session(
                    backend,
                    tab,
                    session.as_deref(),
                    "Runtime.releaseObject",
                    json!({"objectId":object}),
                )
                .await;
            let described = described?;
            frame_id = described["node"]["frameId"]
                .as_str()
                .or_else(|| described["node"]["contentDocument"]["frameId"].as_str())
                .ok_or_else(|| tool_err("locator does not identify an attached frame"))?
                .to_string();
            let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(2);
            loop {
                let child = self
                    .state
                    .facade_events
                    .lock()
                    .map_err(|_| tool_err("event buffer unavailable"))?
                    .get(&(backend, tab))
                    .and_then(|buffer| {
                        buffer.targets.values().find(|target| {
                            target["targetId"] == frame_id && target["active"] == true
                        })
                    })
                    .and_then(|target| target["sessionId"].as_str())
                    .map(str::to_owned);
                let selected = child.or_else(|| session.clone());
                match self.execute_cdp_session(backend,tab,selected.as_deref(),"Page.createIsolatedWorld",json!({"frameId":frame_id,"worldName":"memstack-facade-frame-v1","grantUniveralAccess":false})).await {
                    Ok(world) => {
                        context_id = world["executionContextId"].as_u64().ok_or_else(||tool_err("frame world unavailable"))?;
                        session = selected;
                        if let Some(child) = &session {
                            self.execute_cdp_session(backend,tab,Some(child),"Target.setAutoAttach",json!({"autoAttach":true,"waitForDebuggerOnStart":false,"flatten":true})).await?;
                        }
                        break;
                    },
                    Err(error) if tokio::time::Instant::now()>=deadline => return Err(error),
                    Err(_) => tokio::time::sleep(std::time::Duration::from_millis(25)).await,
                }
            }
            remaining = remaining[index + 1..].to_vec();
        }
        let tree = self
            .execute_cdp_session(
                backend,
                tab,
                session.as_deref(),
                "Page.getFrameTree",
                json!({}),
            )
            .await?;
        let current = frame(&tree["frameTree"], &frame_id)
            .ok_or_else(|| tool_err("frame navigated during locator resolution"))?;
        Ok(FacadeFrameContext {
            session_id: session,
            context_id,
            frame_id,
            loader_id: current["loaderId"].as_str().unwrap_or_default().into(),
            url: current["url"].as_str().unwrap_or_default().into(),
            steps: remaining,
        })
    }

    pub(crate) async fn facade_frame_operation(
        &self,
        backend: Backend,
        tab: u64,
        operation: &str,
        args: &[Value],
    ) -> CoreResult<Value> {
        let steps = args
            .first()
            .and_then(Value::as_array)
            .ok_or_else(|| tool_err("locator steps are required"))?;
        let scope = self
            .facade_frame_context(&backend.as_str(), tab, steps)
            .await?;
        let mut args = args.to_vec();
        args[0] = json!(scope.steps);
        let expression = super::facade::dom_expression(operation, &json!(args))?;
        let user_gesture =
            super::facade::operation_effect(&json!({"operation":operation,"args":args}))?
                != super::facade::FacadeEffect::Read;
        let result = self.execute_cdp_session(backend,tab,scope.session_id.as_deref(),"Runtime.evaluate",json!({"expression":expression,"contextId":scope.context_id,"returnByValue":true,"awaitPromise":true,"userGesture":user_gesture})).await?;
        if let Some(exception) = result.get("exceptionDetails") {
            return Err(tool_err(
                exception["exception"]["description"]
                    .as_str()
                    .or_else(|| exception["text"].as_str())
                    .unwrap_or("frame operation failed"),
            ));
        }
        Ok(result["result"]["value"].clone())
    }
}
