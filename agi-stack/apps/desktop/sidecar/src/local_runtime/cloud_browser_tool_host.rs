//! Cloud admission is bound to the real backend and current page before dispatch.
use super::*;
use agistack_core::ports::{PermissionRequired, ToolResult};

#[async_trait]
pub(in crate::local_runtime) trait BrowserStepAuthority:
    Send + Sync
{
    fn current(&self) -> CoreResult<()>;
    /// Only the authenticated admission gate can return a pending permission.
    async fn authorize(
        &self,
        tool: &str,
        arguments: &Value,
        target: &Value,
    ) -> CoreResult<Option<PermissionRequired>>;
}

pub(in crate::local_runtime) struct CloudBrowserToolHost<E: BridgeEndpoint> {
    local: BrowserRunToolHost<E>,
    run_id: String,
    authority: Arc<dyn BrowserStepAuthority>,
    auth_owner: Option<(String, u64)>,
    browser_caller: Option<agistack_adapters_browser::caller::BrowserCaller>,
}

impl<E: BridgeEndpoint> CloudBrowserToolHost<E> {
    pub(in crate::local_runtime) fn new(
        inner: Arc<BrowserToolHost<E>>,
        session_store: DesktopSessionStore,
        run_id: String,
        full_cdp_enabled: bool,
        site_credentials: SiteCredentialBroker,
        authority: Arc<dyn BrowserStepAuthority>,
    ) -> Self {
        Self {
            local: BrowserRunToolHost::new(
                inner,
                session_store,
                None,
                new_browser_once_consents(),
                full_cdp_enabled,
                site_credentials,
                None,
            ),
            run_id,
            authority,
            auth_owner: None,
            browser_caller: None,
        }
    }

    pub(in crate::local_runtime) fn with_file_roots(mut self, roots: Vec<PathBuf>) -> Self {
        self.local.file_roots = roots;
        self
    }
    pub(in crate::local_runtime) fn with_blocked_file_roots(mut self, roots: Vec<PathBuf>) -> Self {
        self.local.blocked_file_roots = roots;
        self
    }
    pub(in crate::local_runtime) fn with_artifact_root(mut self, root: PathBuf) -> Self {
        self.local.artifact_root = Some(root);
        self
    }

    pub(in crate::local_runtime) fn with_browser_auth(
        mut self,
        broker: crate::local_runtime::browser_auth::BrowserAuthBroker,
        conversation_id: String,
        revision: u64,
    ) -> Self {
        self.local.browser_auth = Some(broker);
        self.auth_owner = Some((conversation_id, revision));
        self
    }

    pub(in crate::local_runtime) fn with_browser_caller(
        mut self,
        caller: agistack_adapters_browser::caller::BrowserCaller,
    ) -> Self {
        self.browser_caller = Some(caller);
        self
    }

    async fn target(&self, tool: &str, input: &Value) -> CoreResult<Value> {
        let backend = input
            .get("backend")
            .and_then(Value::as_str)
            .unwrap_or("chrome");
        agistack_adapters_browser::host::browser_family(backend)?;
        let tab = input.get("tabId").and_then(Value::as_i64);
        let current = match tab {
            Some(tab) if tab > 0 => Some(self.local.inner.current_url_for_input(input, tab).await?),
            Some(_) => return Err(CoreError::Tool("browser tabId must be positive".into())),
            None => None,
        };
        let destination = if matches!(tool, TOOL_NAVIGATE | TOOL_NEW_TAB) {
            input.get("url").and_then(Value::as_str)
        } else if matches!(
            input.get("operation").and_then(Value::as_str),
            Some("tab.goto" | "tabs.new")
        ) {
            input.pointer("/args/0").and_then(Value::as_str)
        } else {
            None
        };
        let url = destination.or(current.as_deref());
        let id = json!({"browser_id":backend,"tab_id":tab,"url":url,
            "origin":url.and_then(origin_host),"current_url":current})
        .to_string();
        Ok(json!({"kind":"browser","id":id}))
    }

    async fn dispatch(&self, tool: &str, input_json: &str) -> CoreResult<ToolResult> {
        if !self.list_tools().iter().any(|candidate| candidate == tool) {
            return Err(CoreError::Tool("browser tool is unavailable".into()));
        }
        let mut input: Value = serde_json::from_str(input_json)
            .map_err(|_| CoreError::Tool("invalid browser input JSON".into()))?;
        let requested = input.clone();
        let public = requested
            .as_object()
            .ok_or_else(|| CoreError::Tool("browser input must be an object".into()))?;
        for key in [
            "_run_id",
            "_browserCaller",
            "_browserSurface",
            "_authorized_file_roots",
            "_blocked_file_roots",
            "_artifact_root",
        ] {
            if public.contains_key(key) {
                return Err(CoreError::Tool(
                    "browser input contains private authority fields".into(),
                ));
            }
        }
        if matches!(
            tool,
            facade::TOOL_READ | TOOL_FACADE_WRITE | TOOL_FACADE_CDP
        ) {
            if facade::operation_effect(&input)?.tool() != tool {
                return Err(CoreError::Tool(
                    "browser operation authority does not match its effect".into(),
                ));
            }
            input = facade::normalize_input(&input)?;
        }
        input = self.local.inner.bind_input(tool, &input).await?;
        let object = input
            .as_object_mut()
            .ok_or_else(|| CoreError::Tool("browser input must be an object".into()))?;
        object.remove("_run_id");
        for key in [
            "_authorized_file_roots",
            "_blocked_file_roots",
            "_artifact_root",
        ] {
            object.remove(key);
        }
        if matches!(tool, TOOL_CDP_RAW | TOOL_FACADE_CDP) && !self.local.full_cdp_enabled {
            return Ok(ToolResult::text(
                json!({"error":"full_cdp_disabled","hint":FULL_CDP_DISABLED_HINT}).to_string(),
            ));
        }
        let target = self.target(tool, &input).await?;
        if let Some(pending) = self.authority.authorize(tool, &requested, &target).await? {
            return Ok(pending.into_result());
        }
        if self.target(tool, &input).await? != target {
            return Err(CoreError::Tool(
                "browser_target_changed: observe and authorize the current page again".into(),
            ));
        }
        input["_run_id"] = json!(self.run_id);
        self.local.inject_file_authority(&mut input, &self.run_id)?;
        if tool == TOOL_FILL_CREDENTIALS {
            return self
                .local
                .fill_credentials_after_consent(&input)
                .await
                .map(ToolResult::text);
        }
        if input["operation"] == "capability.browserAuth.request" {
            let (Some(broker), Some((conversation, revision))) =
                (&self.local.browser_auth, &self.auth_owner)
            else {
                return Ok(ToolResult::text(
                    json!({"status":"unavailable"}).to_string(),
                ));
            };
            let authority = self.authority.clone();
            return self
                .local
                .request_browser_auth_scoped(
                    &input,
                    broker,
                    conversation,
                    &self.run_id,
                    *revision,
                    Arc::new(move || authority.current().is_ok()),
                )
                .await
                .map(ToolResult::text);
        }
        // Keep screenshot bytes for the authenticated CUA media channel.
        let output = self.local.inner.call(tool, &input.to_string()).await?;
        if input["operation"] == "capabilities.list"
            && input.get("tabId").is_some()
            && self.local.browser_auth.is_some()
            && self.auth_owner.is_some()
        {
            let mut capabilities: Value = serde_json::from_str(&output)
                .map_err(|_| CoreError::Tool("browser capabilities result invalid".into()))?;
            if let Some(capabilities) = capabilities.as_array_mut() {
                capabilities.push(json!("browserAuth"));
            }
            return Ok(ToolResult::text(capabilities.to_string()));
        }
        Ok(ToolResult::text(output))
    }
}

#[async_trait]
impl<E: BridgeEndpoint> ToolHost for CloudBrowserToolHost<E> {
    fn list_tools(&self) -> Vec<String> {
        self.local.list_tools()
    }
    fn tool_definition(&self, name: &str) -> Option<agistack_core::ports::ToolDefinition> {
        self.local.tool_definition(name)
    }
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        self.call_with_content(tool, input_json)
            .await
            .map(|result| result.output_json)
    }
    async fn call_with_content(&self, tool: &str, input_json: &str) -> CoreResult<ToolResult> {
        let started = Instant::now();
        let input = serde_json::from_str::<Value>(input_json).ok();
        let dispatch = self.dispatch(tool, input_json);
        let result = if let Some(caller) = &self.browser_caller {
            agistack_adapters_browser::caller::scope(caller.clone(), dispatch).await
        } else {
            dispatch.await
        };
        let origin = self.local.audit_origin(tool, input.as_ref()).await;
        let _ = self.local.session_store.insert_browser_action_audit(
            Some(&self.run_id),
            tool,
            origin.as_deref(),
            &audit_target_summary(tool, input.as_ref(), origin.as_deref()),
            audit_outcome(&result),
            started.elapsed().as_millis() as i64,
            chrono::Utc::now().timestamp_millis(),
        );
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_adapters_browser::protocol::BridgeNotification;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tokio::sync::broadcast;

    struct Endpoint {
        url: Arc<Mutex<String>>,
        actions: Arc<AtomicUsize>,
        tx: broadcast::Sender<BridgeNotification>,
        seen_params: Option<Arc<Mutex<Vec<Value>>>>,
    }
    #[async_trait]
    impl BridgeEndpoint for Endpoint {
        async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
            if let Some(seen) = &self.seen_params {
                seen.lock().unwrap().push(params);
            }
            if method == "getTabs" {
                return Ok(json!({"tabs":[{"tabId":7,"url":self.url.lock().unwrap().clone()}]}));
            }
            self.actions.fetch_add(1, Ordering::SeqCst);
            Ok(json!({"result":{}}))
        }
        async fn request_on(&self, _: &str, method: &str, args: Value) -> CoreResult<Value> {
            self.request(method, args).await
        }
        fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification> {
            self.tx.subscribe()
        }
    }
    struct Authority {
        pending: bool,
        change: Option<Arc<Mutex<String>>>,
        seen: Arc<Mutex<Vec<Value>>>,
    }
    #[async_trait]
    impl BrowserStepAuthority for Authority {
        fn current(&self) -> CoreResult<()> {
            Ok(())
        }
        async fn authorize(
            &self,
            tool: &str,
            arguments: &Value,
            target: &Value,
        ) -> CoreResult<Option<PermissionRequired>> {
            assert!(arguments.get("_run_id").is_none());
            self.seen.lock().unwrap().push(target.clone());
            if let Some(url) = &self.change {
                *url.lock().unwrap() = "https://changed.example/".into();
            }
            Ok(self.pending.then(|| {
                PermissionRequired::new(
                    agistack_core::ports::PermissionKind::CloudExecutionStep,
                    agistack_core::ports::PermissionBinding {
                        tool_name: tool.into(),
                        input_digest: agistack_core::ports::permission_input_digest(
                            &arguments.to_string(),
                        )
                        .unwrap(),
                        engine_session_id: Some("session".into()),
                        cell_id: Some("cell".into()),
                        step_id: Some("step".into()),
                    },
                    json!({"error":"permission_required","request_id":"pending"}),
                )
            }))
        }
    }
    async fn run_input(
        pending: bool,
        change: bool,
        private: Option<&str>,
    ) -> (CoreResult<ToolResult>, usize, Vec<Value>) {
        let store = DesktopSessionStore::in_memory().unwrap();
        let credentials =
            super::super::super::provider_credentials::ProviderCredentialBroker::in_memory(
                store.installation_id(),
            )
            .unwrap()
            .site_credential_broker();
        let url = Arc::new(Mutex::new("https://original.example/path".into()));
        let actions = Arc::new(AtomicUsize::new(0));
        let seen = Arc::new(Mutex::new(Vec::new()));
        let host = CloudBrowserToolHost::new(
            Arc::new(BrowserToolHost::new(Endpoint {
                url: url.clone(),
                actions: actions.clone(),
                tx: broadcast::channel(8).0,
                seen_params: None,
            })),
            store,
            "cloud-run".into(),
            true,
            credentials,
            Arc::new(Authority {
                pending,
                change: change.then_some(url),
                seen: seen.clone(),
            }),
        );
        let mut input = json!({"browserId":"edge","tabId":"7","operation":"tab.reload","args":[]});
        if let Some(key) = private {
            input[key] = json!("forged");
        }
        let result = host
            .call_with_content(TOOL_FACADE_WRITE, &input.to_string())
            .await;
        let observations = seen.lock().unwrap().clone();
        (result, actions.load(Ordering::SeqCst), observations)
    }
    async fn run(pending: bool, change: bool) -> (CoreResult<ToolResult>, usize, Vec<Value>) {
        run_input(pending, change, None).await
    }
    #[tokio::test]
    async fn private_authority_fields_are_rejected_before_admission_or_dispatch() {
        for key in [
            "_run_id",
            "_browserCaller",
            "_browserSurface",
            "_authorized_file_roots",
            "_blocked_file_roots",
            "_artifact_root",
        ] {
            let (result, actions, seen) = run_input(true, false, Some(key)).await;
            assert!(result
                .unwrap_err()
                .to_string()
                .contains("private authority fields"));
            assert_eq!(actions, 0);
            assert!(seen.is_empty());
        }
    }
    #[tokio::test]
    async fn pending_step_never_dispatches_and_binds_backend_and_url() {
        let (result, actions, seen) = run(true, false).await;
        let result = result.unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&result.output_json).unwrap()["error"],
            "permission_required"
        );
        assert_eq!(actions, 0);
        let binding = result.permission_required.as_ref().unwrap().binding();
        assert_eq!(binding.input_digest, agistack_core::ports::permission_input_digest(
            r#"{"browserId":"edge","tabId":"7","operation":"tab.reload","args":[]}"#
        ).unwrap(), "permission binds the original public input, before backend and numeric tab normalization");
        let identity: Value = serde_json::from_str(seen[0]["id"].as_str().unwrap()).unwrap();
        assert_eq!(identity["browser_id"], "edge");
        assert_eq!(identity["origin"], "original.example");
    }
    #[tokio::test]
    async fn page_change_during_admission_prevents_dispatch() {
        let (result, actions, _) = run(false, true).await;
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("browser_target_changed"));
        assert_eq!(actions, 0);
    }
    #[tokio::test]
    async fn admitted_unchanged_page_dispatches() {
        let (result, actions, _) = run(false, false).await;
        assert!(result.is_ok());
        assert!(result.unwrap().permission_required.is_none());
        assert_eq!(actions, 2); // attach and reload
    }
    #[tokio::test]
    async fn verified_cloud_child_scope_reaches_bridge_and_forged_scope_is_rejected() {
        let store = DesktopSessionStore::in_memory().unwrap();
        let credentials =
            super::super::super::provider_credentials::ProviderCredentialBroker::in_memory(
                store.installation_id(),
            )
            .unwrap()
            .site_credential_broker();
        let seen = Arc::new(Mutex::new(Vec::new()));
        let host = CloudBrowserToolHost::new(
            Arc::new(BrowserToolHost::new(Endpoint {
                url: Arc::new(Mutex::new("https://example.test/".into())),
                actions: Arc::new(AtomicUsize::new(0)),
                tx: broadcast::channel(8).0,
                seen_params: Some(seen.clone()),
            })),
            store,
            "parent-run".into(),
            false,
            credentials,
            Arc::new(Authority {
                pending: false,
                change: None,
                seen: Default::default(),
            }),
        )
        .with_browser_caller(agistack_adapters_browser::caller::BrowserCaller {
            session_id: "child-execution".into(),
            main_session_id: "main-conversation".into(),
            caller_id: "child-execution".into(),
            turn_id: "parent-run".into(),
            allow_dot: true,
        });
        let input = json!({"browserId":"iab","operation":"tabs.list","args":[]});
        host.call_with_content(facade::TOOL_READ, &input.to_string())
            .await
            .unwrap();
        let calls = seen.lock().unwrap().clone();
        assert!(!calls.is_empty());
        assert!(calls.iter().all(
            |value| value["_browserCaller"]["callerId"] == "child-execution"
                && value["_browserCaller"]["mainSessionId"] == "main-conversation"
                && value["_browserCaller"]["turnId"] == "parent-run"
                && value["_browserCaller"]["allowDot"] == true
        ));
        let mut forged = input;
        forged["_browserCaller"] = json!({"callerId":"parent-run"});
        assert!(host
            .call_with_content(facade::TOOL_READ, &forged.to_string())
            .await
            .is_err());
        assert_eq!(seen.lock().unwrap().len(), calls.len());
        assert!(agistack_adapters_browser::caller::current().is_none());
    }
}
