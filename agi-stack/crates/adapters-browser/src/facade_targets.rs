use crate::host::{Backend, BridgeEndpoint, BrowserToolHost, tool_err};
use agistack_core::ports::CoreResult;
use serde_json::{Value, json};

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub(crate) async fn ensure_facade_targets(&self, backend: Backend, tab: u64) -> CoreResult<()> {
        if self
            .state
            .facade_events
            .lock()
            .map_err(|_| tool_err("browser event buffer unavailable"))?
            .get(&(backend, tab))
            .is_some_and(|buffer| buffer.auto_attach_enabled)
        {
            return Ok(());
        }
        self.execute_cdp(
            backend,
            tab,
            "Target.setAutoAttach",
            json!({"autoAttach":true,"waitForDebuggerOnStart":false,"flatten":true}),
        )
        .await?;
        self.state
            .facade_events
            .lock()
            .map_err(|_| tool_err("browser event buffer unavailable"))?
            .entry((backend, tab))
            .or_default()
            .auto_attach_enabled = true;
        Ok(())
    }

    pub(crate) fn facade_target_session(
        &self,
        backend: Backend,
        tab: u64,
        target: &Value,
        active: bool,
    ) -> CoreResult<String> {
        let session = target.get("sessionId").and_then(Value::as_str);
        let id = target.get("targetId").and_then(Value::as_str);
        if session.is_some() == id.is_some()
            || target.as_object().is_none_or(|value| value.len() != 1)
        {
            return Err(tool_err(
                "target requires exactly one sessionId or targetId",
            ));
        }
        let buffers = self
            .state
            .facade_events
            .lock()
            .map_err(|_| tool_err("browser event buffer unavailable"))?;
        let buffer = buffers
            .get(&(backend, tab))
            .ok_or_else(|| tool_err("child target is unavailable"))?;
        let matches = buffer
            .targets
            .iter()
            .filter(|(key, value)| {
                (!active || value["active"] == true)
                    && (session.is_some_and(|session| session == *key)
                        || id.is_some_and(|id| value["targetId"] == id))
            })
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err(tool_err("child target is unavailable or ambiguous"));
        }
        Ok(matches[0].0.clone())
    }

    pub(crate) async fn execute_cdp_session(
        &self,
        backend: Backend,
        tab: u64,
        session: Option<&str>,
        method: &str,
        params: Value,
    ) -> CoreResult<Value> {
        let mut request = json!({"tabId":tab,"method":method,"params":params});
        if let Some(session) = session {
            request["sessionId"] = json!(session);
        }
        let result = self.backend_request(backend, "executeCdp", request).await?;
        Ok(result.get("result").cloned().unwrap_or(Value::Null))
    }

    pub(crate) async fn facade_cdp_send(
        &self,
        backend: Backend,
        tab: u64,
        args: &[Value],
    ) -> CoreResult<Value> {
        self.ensure_facade_targets(backend, tab).await?;
        let method = args
            .first()
            .and_then(Value::as_str)
            .ok_or_else(|| tool_err("CDP send requires a method"))?;
        let params = args.get(1).cloned().unwrap_or(json!({}));
        crate::cdp_policy::check_cdp_allowed_with_mode(
            crate::cdp_policy::CdpPolicyMode::FullAccess,
            method,
            &params,
        )
        .map_err(|error| tool_err(error.to_string()))?;
        let options = args.get(2).cloned().unwrap_or(json!({}));
        let session = options
            .get("target")
            .map(|target| self.facade_target_session(backend, tab, target, true))
            .transpose()?;
        let timeout = options
            .get("timeoutMs")
            .and_then(Value::as_u64)
            .unwrap_or(10_000)
            .clamp(1, 30_000);
        tokio::time::timeout(
            std::time::Duration::from_millis(timeout),
            self.execute_cdp_session(backend, tab, session.as_deref(), method, params),
        )
        .await
        .map_err(|_| tool_err("CDP command timed out"))?
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{facade_events::EventBuffer, protocol::OnCdpEventParams};
    #[test]
    fn child_event_source_and_detach_are_retained() {
        let mut buffer = EventBuffer::default();
        for value in [
            json!({"tabId":4,"method":"Target.attachedToTarget","params":{"sessionId":"child","targetInfo":{"targetId":"frame","url":"https://frame.test"}}}),
            json!({"tabId":4,"sessionId":"child","method":"Page.loadEventFired","params":{}}),
            json!({"tabId":4,"method":"Target.detachedFromTarget","params":{"sessionId":"child"}}),
        ] {
            buffer.push(&serde_json::from_value::<OnCdpEventParams>(value).unwrap());
        }
        assert_eq!(buffer.events[1]["source"]["sessionId"], "child");
        assert_eq!(buffer.events[1]["source"]["targetId"], "frame");
        assert_eq!(buffer.targets["child"]["active"], false);
    }
}
