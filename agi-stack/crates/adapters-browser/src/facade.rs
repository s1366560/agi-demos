//! Structured browser facade operations. Effects are protocol metadata, never text inference.
use agistack_core::ports::CoreResult;
use serde_json::{Value, json};

use crate::host::{Backend, BridgeEndpoint, BrowserToolHost, backend_of, tool_err};

pub const TOOL_READ: &str = "browser_read_operation";
pub const TOOL_WRITE: &str = "browser_write_operation";
pub const TOOL_CDP: &str = "browser_cdp_operation";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FacadeEffect {
    Read,
    Mutate,
    FullCdp,
}

impl FacadeEffect {
    pub fn tool(self) -> &'static str {
        match self {
            Self::Read => TOOL_READ,
            Self::Mutate => TOOL_WRITE,
            Self::FullCdp => TOOL_CDP,
        }
    }
}

pub fn operation_effect(input: &Value) -> CoreResult<FacadeEffect> {
    let operation = input
        .get("operation")
        .and_then(Value::as_str)
        .ok_or_else(|| tool_err("missing browser operation"))?;
    match operation {
        "browsers.list"
        | "tabs.list"
        | "tabs.selected"
        | "history"
        | "tab.title"
        | "tab.url"
        | "tab.screenshot"
        | "tab.getJsDialog"
        | "capabilities.list"
        | "playwright.domSnapshot"
        | "playwright.elementInfo"
        | "playwright.elementScreenshot"
        | "playwright.waitForLoadState"
        | "playwright.waitForURL"
        | "playwright.waitForTimeout"
        | "playwright.armNavigation"
        | "playwright.waitNavigation"
        | "playwright.cancelNavigation"
        | "playwright.resolveElement"
        | "download.path"
        | "ax.get"
        | "dom_cua.get_visible_dom"
        | "cua.downloadMedia"
        | "dom_cua.downloadMedia"
        | "dev.logs"
        | "content.export"
        | "content.exportGsuite"
        | "content.exportYouTubeTranscript"
        | "capability.pageAssets.bundle"
        | "capability.cdp.readEvents"
        | "capability.pageAssets.list"
        | "capability.webmcp.listTools" => Ok(FacadeEffect::Read),
        "capability.management.getAuditTrail"
        | "capability.management.tabs.get"
        | "capability.management.tabs.query"
        | "capability.management.windows.get"
        | "capability.management.windows.getAll"
        | "capability.management.tabGroups.get"
        | "capability.management.tabGroups.query"
        | "capability.management.bookmarks.get"
        | "capability.management.bookmarks.getChildren"
        | "capability.management.bookmarks.getTree"
        | "capability.management.bookmarks.getSubTree"
        | "capability.management.bookmarks.search"
        | "capability.visibility.get" => Ok(FacadeEffect::Read),
        "capability.management.tabs.update"
        | "capability.management.tabs.move"
        | "capability.management.tabs.group"
        | "capability.management.tabs.ungroup"
        | "capability.management.tabs.remove"
        | "capability.management.windows.create"
        | "capability.management.windows.update"
        | "capability.management.tabGroups.update"
        | "capability.management.tabGroups.move"
        | "capability.management.bookmarks.create"
        | "capability.management.bookmarks.update"
        | "capability.management.bookmarks.move"
        | "capability.management.bookmarks.remove"
        | "capability.management.bookmarks.removeTree"
        | "capability.visibility.set"
        | "capability.viewport.set"
        | "capability.viewport.reset" => Ok(FacadeEffect::Mutate),
        "playwright.evaluate"
        | "capability.cdp.send"
        | "filechooser.setFiles"
        | "clipboard.read"
        | "clipboard.readText"
        | "clipboard.write"
        | "clipboard.writeText"
        | "capability.webmcp.callTool" => Ok(FacadeEffect::FullCdp),
        "playwright.waitForEvent" => match input.pointer("/args/0").and_then(Value::as_str) {
            Some("download" | "filechooser") => Ok(FacadeEffect::Mutate),
            _ => Err(tool_err("unsupported browser event")),
        },
        "playwright.locator" => match input.pointer("/args/1").and_then(Value::as_str) {
            Some(
                "count" | "allTextContents" | "getAttribute" | "innerText" | "textContent"
                | "isVisible" | "isEnabled" | "waitFor" | "downloadMedia" | "clickPoint",
            ) => Ok(FacadeEffect::Read),
            Some("evaluate" | "evaluateAll") => Ok(FacadeEffect::FullCdp),
            Some(
                "click" | "dblclick" | "fill" | "type" | "press" | "pressSequentially"
                | "selectOption" | "check" | "uncheck" | "setChecked",
            ) => Ok(FacadeEffect::Mutate),
            _ => Err(tool_err("unsupported locator operation")),
        },
        "capability.browserAuth.request"
        | "playwright.focusLocator"
        | "tabs.new"
        | "tab.claim"
        | "tab.close"
        | "tab.goto"
        | "tab.back"
        | "tab.forward"
        | "tab.reload"
        | "tab.markDeliverable"
        | "tab.markHandoff"
        | "tab.requestManualHandoff"
        | "tab.requestUserTakeover"
        | "ax.click"
        | "ax.drag"
        | "ax.paste"
        | "ax.performSecondaryAction"
        | "ax.pressKey"
        | "ax.scroll"
        | "ax.selectText"
        | "ax.setValue"
        | "ax.typeText"
        | "ax.write"
        | "cua.click"
        | "cua.double_click"
        | "cua.drag"
        | "cua.keypress"
        | "cua.move"
        | "cua.scroll"
        | "cua.type"
        | "dom_cua.click"
        | "dom_cua.double_click"
        | "dom_cua.keypress"
        | "dom_cua.scroll"
        | "dom_cua.type"
        | "dialog.accept"
        | "dialog.dismiss"
        | "nameSession" => Ok(FacadeEffect::Mutate),
        _ => Err(tool_err(format!(
            "unsupported browser operation: {operation}"
        ))),
    }
}

pub(crate) fn validate_session_name(name: &str) -> CoreResult<()> {
    if name.trim().is_empty() || name.chars().count() > 128 || name.chars().any(char::is_control) {
        return Err(tool_err(
            "session name must contain 1 to 128 printable characters",
        ));
    }
    Ok(())
}

/// Canonicalize only structural provider/tab fields before origin checks and execution.
pub fn normalize_input(input: &Value) -> CoreResult<Value> {
    let mut input = input.clone();
    let object = input
        .as_object_mut()
        .ok_or_else(|| tool_err("browser input must be an object"))?;
    if let Some(browser) = object
        .get("browserId")
        .and_then(Value::as_str)
        .map(str::to_owned)
    {
        object.insert("backend".into(), json!(browser));
    }
    if let Some(id) = object.get("tabId").and_then(Value::as_str) {
        let id = id
            .parse::<u64>()
            .map_err(|_| tool_err("tabId must identify a positive integer tab"))?;
        object.insert("tabId".into(), json!(id));
    }
    Ok(input)
}

/// A trusted, self-contained DOM implementation shared with frame-scoped MCP Apps.
pub fn dom_expression(operation: &str, args: &Value) -> CoreResult<String> {
    operation_effect(&json!({"operation":operation,"args":args}))?;
    let payload = json!({"operation":operation,"args":args});
    Ok(format!(
        "({})({payload})",
        include_str!("../assets/facade-dom.js")
    ))
}

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub(crate) async fn facade_operation(&self, tool: &str, raw: &Value) -> CoreResult<Value> {
        if operation_effect(raw)?.tool() != tool {
            return Err(tool_err(
                "browser operation effect does not match tool authority",
            ));
        }
        let input = normalize_input(raw)?;
        let operation = input["operation"]
            .as_str()
            .ok_or_else(|| tool_err("missing operation"))?;
        let args = input
            .get("args")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        if operation == "browsers.list" {
            return self.endpoint.browsers().await;
        }
        let backend = backend_of(&input)?;
        if operation == "history" {
            if backend.family() == "iab" {
                return Err(tool_err("history is unavailable for the in-app browser"));
            }
            return self
                .backend_request(
                    backend,
                    "browserHistory",
                    args.first().cloned().unwrap_or(json!({})),
                )
                .await;
        }
        if operation == "nameSession" {
            let name = args
                .first()
                .and_then(Value::as_str)
                .ok_or_else(|| tool_err("session name must be a string"))?;
            validate_session_name(name)?;
            let run = input["_run_id"]
                .as_str()
                .filter(|run| !run.is_empty())
                .ok_or_else(|| tool_err("session naming requires a run"))?;
            self.backend_request(backend, "nameSession", json!({"key":run,"title":name}))
                .await?;
            self.state
                .facade_sessions
                .lock()
                .map_err(|_| tool_err("session state poisoned"))?
                .insert((backend, run.to_string()), name.to_string());
            return Ok(Value::Null);
        }
        if operation == "capabilities.list" {
            let capabilities = self
                .backend_request(backend, "facadeCapabilities", json!({}))
                .await?;
            return Ok(capabilities[if input.get("tabId").is_some() {
                "tab"
            } else {
                "browser"
            }]
            .clone());
        }
        if let Some(method) = operation.strip_prefix("capability.management.") {
            let (namespace, method) = method.split_once('.').unwrap_or(("management", method));
            return self
                .backend_request(
                    backend,
                    "browserManagement",
                    json!({"namespace":namespace,"method":method,"args":args}),
                )
                .await;
        }
        if matches!(
            operation,
            "capability.visibility.get"
                | "capability.visibility.set"
                | "capability.viewport.set"
                | "capability.viewport.reset"
        ) {
            return self
                .backend_request(
                    backend,
                    "browserPresentation",
                    json!({"operation":operation,"args":args}),
                )
                .await;
        }
        if operation == "tabs.list" || operation == "tabs.selected" {
            let result = self.backend_request(backend, "getTabs", json!({})).await?;
            if operation == "tabs.selected" {
                return Ok(result["tabs"]
                    .as_array()
                    .and_then(|tabs| tabs.iter().find(|tab| tab["active"] == true))
                    .cloned()
                    .unwrap_or(Value::Null));
            }
            return Ok(result);
        }
        if operation == "tabs.new" {
            let mut params = input.clone();
            params["url"] = args.first().cloned().unwrap_or(json!("about:blank"));
            if let Some(name) = args.get(1).and_then(|o| o.get("sessionName")) {
                params["sessionName"] = name.clone();
            }
            let tab = self.new_tab(&params).await?;
            if backend.family() == "iab" {
                if let Some(visible) = args.get(1).and_then(|options| options.get("visible")) {
                    self.backend_request(
                        backend,
                        "browserPresentation",
                        json!({"operation":"capability.visibility.set","args":[visible]}),
                    )
                    .await?;
                }
            }
            return Ok(tab);
        }
        let tab_id = input
            .get("tabId")
            .and_then(Value::as_u64)
            .filter(|id| *id > 0)
            .ok_or_else(|| tool_err("operation requires a positive tabId"))?;
        if operation == "playwright.waitForEvent" {
            return self
                .facade_artifact_operation(backend, tab_id, operation, &args, &input)
                .await;
        }
        if operation_effect(&input)? != FacadeEffect::Read {
            self.wait_artifact_interception(backend, tab_id).await?;
        }
        self.ensure_attached(backend, tab_id).await?;
        if operation == "capability.cdp.readEvents" {
            self.ensure_facade_targets(backend, tab_id).await?;
            return self.facade_events(backend, tab_id, operation, &args).await;
        }
        match operation {
            "playwright.locator"
                if matches!(
                    args.get(1).and_then(Value::as_str),
                    Some("click" | "dblclick")
                ) =>
            {
                self.facade_locator_click(backend, tab_id, &args).await
            }
            "cua.downloadMedia" | "dom_cua.downloadMedia" => {
                self.download_media(backend, tab_id, operation, &args, &input)
                    .await
            }
            "playwright.locator"
                if args.get(1).and_then(Value::as_str) == Some("downloadMedia") =>
            {
                self.download_media(backend, tab_id, operation, &args, &input)
                    .await
            }
            "content.export"
            | "content.exportGsuite"
            | "content.exportYouTubeTranscript"
            | "capability.pageAssets.bundle" => {
                self.facade_content(backend, tab_id, operation, &args, &input)
                    .await
            }
            "playwright.waitForEvent" | "download.path" | "filechooser.setFiles" => {
                self.facade_artifact_operation(backend, tab_id, operation, &args, &input)
                    .await
            }
            "playwright.locator" if args.get(1).and_then(Value::as_str) == Some("press") => {
                self.with_input_visibility(backend, tab_id, async {
                    let steps = args
                        .first()
                        .cloned()
                        .ok_or_else(|| tool_err("locator steps missing"))?;
                    self.facade_frame_operation(backend, tab_id, "playwright.focusLocator", &[steps])
                        .await?;
                    let key = args
                        .get(2)
                        .and_then(|values| values.get(0))
                        .and_then(Value::as_str)
                        .ok_or_else(|| tool_err("press requires a key"))?;
                    self.facade_input(
                        backend,
                        tab_id,
                        "cua.keypress",
                        &[json!({"keys":key.split('+').collect::<Vec<_>>()})],
                    )
                    .await
                })
                .await
            }
            "playwright.locator"
                if matches!(
                    args.get(1).and_then(Value::as_str),
                    Some("type" | "pressSequentially")
                ) =>
            {
                self.with_input_visibility(backend, tab_id, async {
                    let steps = args
                        .first()
                        .cloned()
                        .ok_or_else(|| tool_err("locator steps missing"))?;
                    self.facade_frame_operation(backend, tab_id, "playwright.focusLocator", &[steps])
                        .await?;
                    let text = args
                        .get(2)
                        .and_then(|args| args.get(0))
                        .and_then(Value::as_str)
                        .ok_or_else(|| tool_err("type requires text"))?;
                    self.facade_type_characters(backend, tab_id, text).await
                })
                .await
            }
            "playwright.locator"
                if args.first().and_then(Value::as_array).is_some_and(|steps| {
                    steps.iter().any(|step| step["kind"] == "frameLocator")
                }) =>
            {
                self.facade_frame_operation(backend, tab_id, operation, &args)
                    .await
            }
            "playwright.armNavigation"
            | "playwright.waitNavigation"
            | "playwright.cancelNavigation"
            | "tab.getJsDialog"
            | "dialog.accept"
            | "dialog.dismiss" => self.facade_events(backend, tab_id, operation, &args).await,
            "ax.click" | "ax.drag" | "ax.scroll" | "ax.typeText" | "ax.paste" | "ax.pressKey"
            | "cua.click" | "cua.double_click" | "cua.drag" | "cua.keypress" | "cua.move"
            | "cua.scroll" | "cua.type" => {
                self.facade_input(backend, tab_id, operation, &args).await
            }
            "tab.claim" => self.claim_tab(&input).await,
            "tab.goto" => {
                let mut params = input.clone();
                params["url"] = args
                    .first()
                    .cloned()
                    .ok_or_else(|| tool_err("goto requires a URL"))?;
                self.navigate(&params).await
            }
            "tab.markDeliverable" | "tab.markHandoff" => {
                let mut params = input.clone();
                params["mark"] = json!(if operation == "tab.markDeliverable" {
                    "deliverable"
                } else {
                    "handoff"
                });
                self.mark_tab(&params).await
            }
            "tab.close" => {
                self.backend_request(backend, "closeTab", json!({"tabId":tab_id}))
                    .await
            }
            "tab.requestManualHandoff" | "tab.requestUserTakeover" => {
                self.backend_request(backend, "focusTab", json!({"tabId":tab_id}))
                    .await
            }
            "tab.screenshot" => self.screenshot(&input).await,
            "playwright.elementScreenshot" => {
                self.element_screenshot(backend, tab_id, &args, &input)
                    .await
            }
            "dev.logs" => self.console_logs(&input).await,
            "tab.url" => Ok(json!(
                self.current_url_for_input(&input, tab_id as i64).await?
            )),
            "tab.title" => {
                self.facade_evaluate(backend, tab_id, "document.title".into())
                    .await
            }
            "tab.reload" => {
                self.execute_cdp(backend, tab_id, "Page.reload", json!({}))
                    .await
            }
            "tab.back" | "tab.forward" => {
                let history = self
                    .execute_cdp(backend, tab_id, "Page.getNavigationHistory", json!({}))
                    .await?;
                let current = history["currentIndex"]
                    .as_i64()
                    .ok_or_else(|| tool_err("navigation history is unavailable"))?;
                let next = current + if operation == "tab.back" { -1 } else { 1 };
                let entry = usize::try_from(next)
                    .ok()
                    .and_then(|index| history["entries"].get(index))
                    .ok_or_else(|| tool_err("no history entry in that direction"))?;
                self.execute_cdp(
                    backend,
                    tab_id,
                    "Page.navigateToHistoryEntry",
                    json!({"entryId":entry["id"]}),
                )
                .await
            }
            "capability.cdp.send" => self.facade_cdp_send(backend, tab_id, &args).await,
            "playwright.waitForTimeout" => {
                let delay = args
                    .first()
                    .and_then(Value::as_u64)
                    .filter(|delay| *delay <= 30_000)
                    .ok_or_else(|| tool_err("wait must be between 0 and 30000 milliseconds"))?;
                tokio::time::sleep(std::time::Duration::from_millis(delay)).await;
                Ok(Value::Null)
            }
            "playwright.waitForURL" | "playwright.waitForLoadState" => {
                self.facade_wait(backend, tab_id, operation, &args).await
            }
            _ => {
                self.facade_evaluate_with_gesture(
                    backend,
                    tab_id,
                    dom_expression(operation, &json!(args))?,
                    operation_effect(&input)? != FacadeEffect::Read,
                )
                .await
            }
        }
    }

    pub(crate) async fn facade_evaluate(
        &self,
        backend: Backend,
        tab_id: u64,
        expression: String,
    ) -> CoreResult<Value> {
        self.facade_evaluate_with_gesture(backend, tab_id, expression, false)
            .await
    }

    async fn facade_evaluate_with_gesture(
        &self,
        backend: Backend,
        tab_id: u64,
        expression: String,
        user_gesture: bool,
    ) -> CoreResult<Value> {
        let (_, context_id) = self.world_context(backend, tab_id).await?;
        let result = self.execute_cdp(backend, tab_id, "Runtime.evaluate", json!({"expression":expression,"contextId":context_id,"awaitPromise":true,"returnByValue":true,"userGesture":user_gesture})).await?;
        if let Some(exception) = result.get("exceptionDetails") {
            return Err(tool_err(
                exception["exception"]["description"]
                    .as_str()
                    .or_else(|| exception["text"].as_str())
                    .unwrap_or("browser operation failed"),
            ));
        }
        Ok(result["result"]["value"].clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn effect_is_validated_from_protocol_metadata() {
        assert_eq!(
            operation_effect(&json!({"operation":"playwright.locator","args":[[],"count",[]]}))
                .unwrap(),
            FacadeEffect::Read
        );
        assert_eq!(
            operation_effect(&json!({"operation":"playwright.locator","args":[[],"fill",["x"]]}))
                .unwrap(),
            FacadeEffect::Mutate
        );
        assert_eq!(
            operation_effect(&json!({"operation":"playwright.locator","args":[[],"evaluate",[]]}))
                .unwrap(),
            FacadeEffect::FullCdp
        );
        assert!(operation_effect(&json!({"operation":"invented"})).is_err());
    }
    #[test]
    fn identity_and_dom_payload_are_structured() {
        let input = normalize_input(&json!({"browserId":"iab","tabId":"7"})).unwrap();
        assert_eq!(input["backend"], "iab");
        assert_eq!(input["tabId"], 7);
        assert!(normalize_input(&json!({"tabId":"wrong"})).is_err());
        let expression = dom_expression("playwright.domSnapshot", &json!(["</script>\n"])).unwrap();
        assert!(expression.contains("memstackDomOperation"));
        assert!(
            expression.ends_with(
                "\"args\":[\"</script>\\n\"],\"operation\":\"playwright.domSnapshot\"})"
            )
        );
    }
}
