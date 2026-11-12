use crate::host::{tool_err, Backend, BridgeEndpoint, BrowserToolHost};
use crate::protocol::OnCdpEventParams;
use agistack_core::ports::CoreResult;
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};
use std::time::Duration;

#[derive(Default)]
pub(crate) struct EventBuffer {
    pub cursor: u64,
    pub events: VecDeque<Value>,
    pub auto_attach_enabled: bool,
    pub targets: HashMap<String, Value>,
}
impl EventBuffer {
    pub(crate) fn push(&mut self, event: &OnCdpEventParams) {
        self.cursor = self.cursor.saturating_add(1);
        if event.method == "Target.attachedToTarget" {
            if let Some(session) = event.params["sessionId"].as_str() {
                self.targets.insert(session.into(),json!({"sessionId":session,"targetId":event.params["targetInfo"]["targetId"],"url":event.params["targetInfo"]["url"],"type":event.params["targetInfo"]["type"],"active":true}));
            }
        } else if event.method == "Target.detachedFromTarget" {
            if let Some(target) = event.params["sessionId"]
                .as_str()
                .and_then(|id| self.targets.get_mut(id))
            {
                target["active"] = json!(false);
            }
        }
        let mut source = json!({"tabId":event.tab_id});
        if let Some(session) = &event.session_id {
            source["sessionId"] = json!(session);
            if let Some(target) = self.targets.get(session) {
                source["targetId"] = target["targetId"].clone();
            }
        }
        self.events.push_back(json!({"method":event.method,"params":event.params,"sequence":self.cursor,"source":source}));
        if self.events.len() > 1000 {
            self.events.pop_front();
        }
    }
}

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub(crate) async fn facade_events(
        &self,
        backend: Backend,
        tab: u64,
        operation: &str,
        args: &[Value],
    ) -> CoreResult<Value> {
        self.ensure_page_enabled(backend, tab).await?;
        if operation == "playwright.armNavigation" {
            let buffers = self
                .state
                .facade_events
                .lock()
                .map_err(|_| tool_err("event buffer unavailable"))?;
            return Ok(
                json!({"id":buffers.get(&(backend,tab)).map_or(0, |buffer|buffer.cursor).to_string()}),
            );
        }
        if operation == "playwright.cancelNavigation" {
            return Ok(Value::Null);
        }
        if operation == "tab.getJsDialog" || matches!(operation, "dialog.accept" | "dialog.dismiss")
        {
            let dialog = {
                let buffers = self
                    .state
                    .facade_events
                    .lock()
                    .map_err(|_| tool_err("event buffer unavailable"))?;
                buffers
                    .get(&(backend, tab))
                    .and_then(|buffer| {
                        buffer.events.iter().rev().find(|event| {
                            matches!(
                                event["method"].as_str(),
                                Some(
                                    "Page.javascriptDialogOpening" | "Page.javascriptDialogClosed"
                                )
                            )
                        })
                    })
                    .filter(|event| event["method"] == "Page.javascriptDialogOpening")
                    .cloned()
            };
            if operation == "tab.getJsDialog" {
                return Ok(dialog.map(|event| json!({"id":event["sequence"].to_string(),"type":event["params"]["type"],"message":event["params"]["message"]})).unwrap_or(Value::Null));
            }
            let dialog = dialog.ok_or_else(|| tool_err("dialog is no longer open"))?;
            if args.first().and_then(Value::as_str) != Some(dialog["sequence"].to_string().as_str())
            {
                return Err(tool_err("dialog identity expired"));
            }
            return self.execute_cdp(backend,tab,"Page.handleJavaScriptDialog",json!({"accept":operation=="dialog.accept","promptText":args.get(1).and_then(Value::as_str).unwrap_or("")})).await;
        }
        let navigation = operation == "playwright.waitNavigation";
        let options = if navigation {
            args.get(1).cloned().unwrap_or(json!({}))
        } else {
            args.first().cloned().unwrap_or(json!({}))
        };
        let session = options
            .get("target")
            .map(|target| self.facade_target_session(backend, tab, target, false))
            .transpose()?;
        let after = if navigation {
            args.first()
                .and_then(Value::as_str)
                .and_then(|value| value.parse::<u64>().ok())
        } else {
            options.get("afterSequence").and_then(Value::as_u64)
        };
        let limit = options
            .get("limit")
            .and_then(Value::as_u64)
            .unwrap_or(100)
            .clamp(1, 1000) as usize;
        let timeout = options
            .get("timeoutMs")
            .and_then(Value::as_u64)
            .unwrap_or(if navigation { 5000 } else { 0 })
            .min(30000);
        let deadline = tokio::time::Instant::now() + Duration::from_millis(timeout);
        let mut after = after;
        loop {
            let result = {
                let buffers = self
                    .state
                    .facade_events
                    .lock()
                    .map_err(|_| tool_err("event buffer unavailable"))?;
                let empty = EventBuffer::default();
                let buffer = buffers.get(&(backend, tab)).unwrap_or(&empty);
                let after = *after.get_or_insert(buffer.cursor);
                let methods = options.get("methods").and_then(Value::as_array);
                let mut matches = buffer.events.iter().filter(|event| {
                    event["sequence"].as_u64().unwrap_or(0) > after
                        && session
                            .as_ref()
                            .is_none_or(|session| event["source"]["sessionId"] == *session)
                        && if navigation {
                            event["method"] == "Page.frameNavigated"
                                && event["params"]["frame"].get("parentId").is_none()
                        } else {
                            methods.is_none_or(|methods| methods.contains(&event["method"]))
                        }
                });
                let events = matches.by_ref().take(limit).cloned().collect::<Vec<_>>();
                let has_more = matches.next().is_some();
                let cursor = if has_more {
                    events
                        .last()
                        .and_then(|event| event["sequence"].as_u64())
                        .unwrap_or(after)
                } else {
                    buffer.cursor
                };
                json!({"events":events,"cursor":cursor,"hasMore":has_more,"truncated":buffer.events.front().and_then(|event|event["sequence"].as_u64()).is_some_and(|first|first>after.saturating_add(1))})
            };
            if result["events"]
                .as_array()
                .is_some_and(|events| !events.is_empty())
            {
                if navigation {
                    let remaining = deadline
                        .saturating_duration_since(tokio::time::Instant::now())
                        .as_millis()
                        .max(1);
                    let state = options
                        .get("waitUntil")
                        .and_then(Value::as_str)
                        .unwrap_or("load");
                    if let Some(url) = options.get("url") {
                        self.facade_wait(
                            backend,
                            tab,
                            "playwright.waitForURL",
                            &[
                                url.clone(),
                                json!({"waitUntil":state,"timeoutMs":remaining}),
                            ],
                        )
                        .await?;
                    } else {
                        self.facade_wait(
                            backend,
                            tab,
                            "playwright.waitForLoadState",
                            &[json!({"state":state,"timeoutMs":remaining})],
                        )
                        .await?;
                    }
                    return Ok(Value::Null);
                }
                return Ok(result);
            }
            if tokio::time::Instant::now() >= deadline {
                return if navigation {
                    Err(tool_err("navigation timed out"))
                } else {
                    Ok(result)
                };
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    }
}
