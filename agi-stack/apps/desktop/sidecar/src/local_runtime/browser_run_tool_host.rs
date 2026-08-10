//! Run-scoped origin-consent gate for the browser tool surface (M2, see
//! `docs/design/browser-extension-bridge.md` §4.3).
//!
//! [`BrowserRunToolHost`] wraps the concrete
//! [`BrowserToolHost`] before the fan-out so every `browser_*` call carries
//! the run's `_run_id` (lease bookkeeping) and every mutating call is checked
//! against the persisted origin grants plus the run-scoped once-consent
//! cache. Consent denials are returned as tool RESULTS (Ok JSON), never as
//! errors, so the agent loop keeps running and the model can raise a
//! permission HITL request. Origin membership checks are deterministic
//! (set-membership per AGENTS.md); the consent verdict itself always comes
//! from the human via HITL.

use std::{
    collections::BTreeSet,
    sync::{Arc, Mutex},
};

use agistack_adapters_browser::{
    actions::{
        TOOL_CLAIM_TAB, TOOL_CLICK, TOOL_MARK_TAB, TOOL_NAVIGATE, TOOL_NEW_TAB, TOOL_SCROLL,
        TOOL_TYPE,
    },
    host::{BridgeEndpoint, BrowserToolHost},
};
use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use async_trait::async_trait;
use serde_json::{json, Value};
use url::Url;

use super::{
    authority_store::{BrowserOriginDecision, DesktopRun},
    session_store::DesktopSessionStore,
};

/// Mutating browser tools gated by origin consent. Read tools pass through.
const GATED_BROWSER_TOOLS: &[&str] = &[
    TOOL_NAVIGATE,
    TOOL_CLICK,
    TOOL_TYPE,
    TOOL_SCROLL,
    TOOL_NEW_TAB,
    TOOL_CLAIM_TAB,
    TOOL_MARK_TAB,
];

const DECLINE_HINT: &str = "The user declined this origin. Do not retry or work around.";
const CONSENT_HINT: &str =
    "Ask the user for permission to interact with this origin via a permission request \
     (HitlKind::Permission, target kind browser_origin, scopes: once/site/all/decline).";

/// Shared run-scoped once-consent cache
/// (`(run_id, host)`), written by the HITL respond path on scope `once` and
/// cleared when the run reaches a terminal status.
pub(super) type BrowserOnceConsents = Arc<Mutex<BTreeSet<(String, String)>>>;

pub(super) fn new_browser_once_consents() -> BrowserOnceConsents {
    Arc::new(Mutex::new(BTreeSet::new()))
}

/// Extract the consent origin (lowercase host) of an http(s) URL.
/// `about:blank` and non-http(s) schemes carry no consent origin.
fn origin_host(url: &str) -> Option<String> {
    let parsed = Url::parse(url).ok()?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return None;
    }
    parsed.host_str().map(|host| host.to_lowercase())
}

#[derive(Clone)]
pub(super) struct BrowserRunToolHost<E: BridgeEndpoint> {
    inner: Arc<BrowserToolHost<E>>,
    session_store: DesktopSessionStore,
    run: Option<DesktopRun>,
    once_consents: BrowserOnceConsents,
}

impl<E: BridgeEndpoint> BrowserRunToolHost<E> {
    pub(super) fn new(
        inner: Arc<BrowserToolHost<E>>,
        session_store: DesktopSessionStore,
        run: Option<DesktopRun>,
        once_consents: BrowserOnceConsents,
    ) -> Self {
        Self {
            inner,
            session_store,
            run,
            once_consents,
        }
    }

    /// Resolve the consent origin for a mutating call: `browser_navigate`
    /// (and `browser_new_tab` with a `url`) gate on the argument URL, the
    /// tab-bound tools gate on the tab's current URL. `None` means the call
    /// carries no consent origin (about:blank, non-http(s), no url arg).
    async fn resolve_origin(&self, tool: &str, input: &Value) -> CoreResult<Option<String>> {
        match tool {
            TOOL_NAVIGATE | TOOL_NEW_TAB => {
                let Some(url) = input.get("url").and_then(Value::as_str) else {
                    return Ok(None);
                };
                Ok(origin_host(url))
            }
            _ => {
                let tab_id = input.get("tabId").and_then(Value::as_i64).ok_or_else(|| {
                    CoreError::Tool(format!(
                        "tool '{tool}' requires a numeric 'tabId' for origin consent"
                    ))
                })?;
                let url = self.inner.current_url(tab_id).await?;
                Ok(origin_host(&url))
            }
        }
    }

    /// The consent verdict for `host`: persisted decline beats everything,
    /// then global `all`, then host `site`, then the run-scoped once cache.
    /// Returns `None` when the origin is undecided.
    fn persisted_verdict(&self, host: &str) -> CoreResult<Option<bool>> {
        let decisions = self
            .session_store
            .active_browser_origin_decisions(host)
            .map_err(CoreError::Tool)?;
        if decisions
            .iter()
            .any(|grant| grant.decision == BrowserOriginDecision::Decline)
        {
            return Ok(Some(false));
        }
        if decisions
            .iter()
            .any(|grant| grant.host == "*" && grant.decision == BrowserOriginDecision::All)
        {
            return Ok(Some(true));
        }
        if decisions
            .iter()
            .any(|grant| grant.host == host && grant.decision == BrowserOriginDecision::Site)
        {
            return Ok(Some(true));
        }
        Ok(None)
    }

    fn once_consent_active(&self, host: &str) -> bool {
        let Some(run) = self.run.as_ref() else {
            return false;
        };
        self.once_consents
            .lock()
            .expect("browser once consents")
            .contains(&(run.id.clone(), host.to_string()))
    }

    /// Gate one mutating call. `Ok(None)` allows; `Ok(Some(result))` is the
    /// tool RESULT the model receives (decline or consent-required).
    fn gate(&self, tool: &str, origin: Option<String>) -> CoreResult<Option<String>> {
        let Some(host) = origin else {
            return Ok(None);
        };
        match self.persisted_verdict(&host)? {
            Some(false) => {
                return Ok(Some(
                    json!({
                        "error": "origin_declined",
                        "origin": host,
                        "hint": DECLINE_HINT,
                    })
                    .to_string(),
                ));
            }
            Some(true) => return Ok(None),
            None => {}
        }
        if self.once_consent_active(&host) {
            return Ok(None);
        }
        Ok(Some(
            json!({
                "error": "origin_consent_required",
                "origin": host,
                "tool": tool,
                "hint": CONSENT_HINT,
            })
            .to_string(),
        ))
    }
}

#[async_trait]
impl<E: BridgeEndpoint> ToolHost for BrowserRunToolHost<E> {
    fn list_tools(&self) -> Vec<String> {
        self.inner.list_tools()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        let mut input: Value = if input_json.trim().is_empty() {
            json!({})
        } else {
            match serde_json::from_str(input_json) {
                Ok(input) => input,
                // Let the inner host produce its own invalid-input error.
                Err(_) => return self.inner.call(tool, input_json).await,
            }
        };
        if let (Some(run), Value::Object(map)) = (self.run.as_ref(), &mut input) {
            map.insert("_run_id".to_string(), json!(run.id));
        }
        if GATED_BROWSER_TOOLS.contains(&tool) {
            let origin = self.resolve_origin(tool, &input).await?;
            if let Some(result) = self.gate(tool, origin)? {
                return Ok(result);
            }
        }
        self.inner
            .call(
                tool,
                &serde_json::to_string(&input).map_err(|error| {
                    CoreError::Tool(format!("failed to encode tool input: {error}"))
                })?,
            )
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::{HashMap, VecDeque};

    use agistack_adapters_browser::protocol::{BridgeNotification, METHOD_GET_TABS};
    use tokio::sync::broadcast;

    use super::super::{
        authority_store::{
            BrowserOriginDecision, BrowserOriginGrant, DesktopExecutionEnvironmentKind,
            DesktopPermissionProfile, DesktopRunStatus,
        },
        authorized_tool_host::AuthorizedRunToolHost,
        now_iso,
        session_store::ApprovePlanStartInput,
        ConversationCapabilityMode, ConversationRunMode, LocalConversation,
    };

    /// Scripted bridge endpoint: responses are queued per bridge method and
    /// every request is recorded behind a shared handle.
    struct MockEndpoint {
        responses: Mutex<HashMap<String, VecDeque<CoreResult<Value>>>>,
        requests: Arc<Mutex<Vec<(String, Value)>>>,
        notifications: broadcast::Sender<BridgeNotification>,
    }

    #[derive(Clone)]
    struct MockRequests(Arc<Mutex<Vec<(String, Value)>>>);

    impl MockRequests {
        fn count(&self, method: &str) -> usize {
            self.0
                .lock()
                .unwrap()
                .iter()
                .filter(|(m, _)| m == method)
                .count()
        }

        fn params_of(&self, method: &str) -> Vec<Value> {
            self.0
                .lock()
                .unwrap()
                .iter()
                .filter(|(m, _)| m == method)
                .map(|(_, params)| params.clone())
                .collect()
        }
    }

    impl MockEndpoint {
        fn new() -> Self {
            Self {
                responses: Mutex::new(HashMap::new()),
                requests: Arc::new(Mutex::new(Vec::new())),
                notifications: broadcast::channel(16).0,
            }
        }

        fn script(self, method: &str, results: Vec<CoreResult<Value>>) -> Self {
            self.responses
                .lock()
                .unwrap()
                .insert(method.to_string(), results.into_iter().collect());
            self
        }

        fn requests(&self) -> MockRequests {
            MockRequests(Arc::clone(&self.requests))
        }
    }

    #[async_trait]
    impl BridgeEndpoint for MockEndpoint {
        async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
            self.requests
                .lock()
                .unwrap()
                .push((method.to_string(), params));
            let mut responses = self.responses.lock().unwrap();
            let queue = responses
                .get_mut(method)
                .unwrap_or_else(|| panic!("no scripted responses for {method}"));
            queue
                .pop_front()
                .unwrap_or_else(|| panic!("scripted responses for {method} exhausted"))
        }

        fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification> {
            self.notifications.subscribe()
        }
    }

    fn ok(value: Value) -> CoreResult<Value> {
        Ok(value)
    }

    fn tabs_with(tab_id: u64, url: &str) -> Value {
        json!({"tabs": [{
            "tabId": tab_id, "windowId": 1, "title": "T", "url": url, "active": true,
        }]})
    }

    fn test_run() -> DesktopRun {
        let now = now_iso();
        DesktopRun {
            id: "run-1".to_string(),
            conversation_id: "conversation-1".to_string(),
            project_id: "local-project".to_string(),
            plan_version_id: "plan-1".to_string(),
            idempotency_key: "idem-1".to_string(),
            message_id: "message-1".to_string(),
            request_message: "Browse".to_string(),
            status: DesktopRunStatus::Running,
            revision: 1,
            created_at: now.clone(),
            updated_at: now,
            started_at: None,
            completed_at: None,
            last_heartbeat_at: None,
            error: None,
            environment: None,
            permission_profile: DesktopPermissionProfile::FullAccess,
            authorization_snapshot: json!({}),
        }
    }

    fn grant(host: &str, decision: BrowserOriginDecision) -> BrowserOriginGrant {
        BrowserOriginGrant {
            id: format!("grant-{}", uuid::Uuid::new_v4()),
            host: host.to_string(),
            decision,
            source_hitl_request_id: "hitl-1".to_string(),
            created_at: now_iso(),
            revoked_at: None,
        }
    }

    struct Fixture {
        store: DesktopSessionStore,
        once: BrowserOnceConsents,
        host: BrowserRunToolHost<MockEndpoint>,
    }

    fn build_fixture(endpoint: MockEndpoint) -> Fixture {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let once = new_browser_once_consents();
        let host = BrowserRunToolHost::new(
            Arc::new(BrowserToolHost::new(endpoint)),
            store.clone(),
            Some(test_run()),
            Arc::clone(&once),
        );
        Fixture { store, once, host }
    }

    fn claim_tab_endpoint(tab_url: &str) -> MockEndpoint {
        MockEndpoint::new().script(METHOD_GET_TABS, vec![ok(tabs_with(7, tab_url))])
    }

    #[tokio::test]
    async fn read_tools_pass_through_ungated() {
        let fixture = build_fixture(
            MockEndpoint::new().script(METHOD_GET_TABS, vec![ok(tabs_with(7, "https://x.test"))]),
        );
        // No grants at all; a global decline must not gate reads either.
        fixture
            .store
            .insert_browser_origin_grant(&grant("*", BrowserOriginDecision::Decline))
            .expect("insert decline");
        let output = fixture
            .host
            .call("browser_list_tabs", "{}")
            .await
            .expect("read tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["tabs"][0]["tabId"], 7);
    }

    #[tokio::test]
    async fn persisted_decline_blocks_navigate_with_tool_result_and_no_bridge_call() {
        let endpoint = MockEndpoint::new();
        let fixture = build_fixture(endpoint);
        fixture
            .store
            .insert_browser_origin_grant(&grant("example.com", BrowserOriginDecision::Decline))
            .expect("insert decline");
        let output = fixture
            .host
            .call(
                TOOL_NAVIGATE,
                r#"{"tabId": 7, "url": "https://example.com/page"}"#,
            )
            .await
            .expect("decline is a tool result, not an error");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "origin_declined");
        assert_eq!(output["origin"], "example.com");
        assert!(
            output["hint"]
                .as_str()
                .unwrap()
                .contains("Do not retry or work around"),
            "decline hint must forbid retry: {output}"
        );
    }

    #[tokio::test]
    async fn global_decline_blocks_tab_bound_tool_via_current_url() {
        let endpoint = claim_tab_endpoint("https://foo.test");
        let requests = endpoint.requests();
        let fixture = build_fixture(endpoint);
        fixture
            .store
            .insert_browser_origin_grant(&grant("*", BrowserOriginDecision::Decline))
            .expect("insert global decline");
        let output = fixture
            .host
            .call(TOOL_CLICK, r#"{"tabId": 7, "ref": "e1"}"#)
            .await
            .expect("decline is a tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "origin_declined");
        assert_eq!(output["origin"], "foo.test");
        // The click path resolved the origin from the tab's current URL.
        assert_eq!(requests.count(METHOD_GET_TABS), 1);
    }

    #[tokio::test]
    async fn decline_beats_global_all_and_site() {
        // Host decline beats '*' all.
        let endpoint = MockEndpoint::new();
        let fixture = build_fixture(endpoint);
        fixture
            .store
            .insert_browser_origin_grant(&grant("*", BrowserOriginDecision::All))
            .expect("insert global all");
        fixture
            .store
            .insert_browser_origin_grant(&grant("example.com", BrowserOriginDecision::Decline))
            .expect("insert host decline");
        let output = fixture
            .host
            .call(
                TOOL_NAVIGATE,
                r#"{"tabId": 7, "url": "https://example.com"}"#,
            )
            .await
            .expect("decline is a tool result");
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap()["error"],
            "origin_declined"
        );

        // Global decline beats host site.
        let endpoint = claim_tab_endpoint("https://foo.test");
        let fixture = build_fixture(endpoint);
        fixture
            .store
            .insert_browser_origin_grant(&grant("foo.test", BrowserOriginDecision::Site))
            .expect("insert site");
        fixture
            .store
            .insert_browser_origin_grant(&grant("*", BrowserOriginDecision::Decline))
            .expect("insert global decline");
        let output = fixture
            .host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("decline is a tool result");
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap()["error"],
            "origin_declined"
        );
    }

    #[tokio::test]
    async fn global_all_allows_tab_bound_tool() {
        let endpoint = claim_tab_endpoint("https://foo.test");
        let fixture = build_fixture(endpoint);
        fixture
            .store
            .insert_browser_origin_grant(&grant("*", BrowserOriginDecision::All))
            .expect("insert global all");
        let output = fixture
            .host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("allowed tool result");
        assert_eq!(serde_json::from_str::<Value>(&output).unwrap()["tabId"], 7);
    }

    #[tokio::test]
    async fn site_grant_allows_matching_host_only() {
        let endpoint = claim_tab_endpoint("https://foo.test");
        let fixture = build_fixture(endpoint);
        fixture
            .store
            .insert_browser_origin_grant(&grant("foo.test", BrowserOriginDecision::Site))
            .expect("insert site");
        let output = fixture
            .host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("allowed tool result");
        assert_eq!(serde_json::from_str::<Value>(&output).unwrap()["tabId"], 7);

        // A site grant for another host does not cover this origin.
        let endpoint = claim_tab_endpoint("https://foo.test");
        let fixture = build_fixture(endpoint);
        fixture
            .store
            .insert_browser_origin_grant(&grant("other.test", BrowserOriginDecision::Site))
            .expect("insert other site");
        let output = fixture
            .host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("consent required is a tool result");
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap()["error"],
            "origin_consent_required"
        );
    }

    #[tokio::test]
    async fn once_consent_is_run_scoped() {
        let endpoint = claim_tab_endpoint("https://foo.test");
        let fixture = build_fixture(endpoint);
        fixture
            .once
            .lock()
            .unwrap()
            .insert(("run-1".to_string(), "foo.test".to_string()));
        let output = fixture
            .host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("allowed tool result");
        assert_eq!(serde_json::from_str::<Value>(&output).unwrap()["tabId"], 7);

        // A once consent for another run does not apply.
        let endpoint = claim_tab_endpoint("https://foo.test");
        let fixture = build_fixture(endpoint);
        fixture
            .once
            .lock()
            .unwrap()
            .insert(("run-other".to_string(), "foo.test".to_string()));
        let output = fixture
            .host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("consent required is a tool result");
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap()["error"],
            "origin_consent_required"
        );
    }

    #[tokio::test]
    async fn undecided_navigate_returns_consent_required_without_bridge_calls() {
        let endpoint = MockEndpoint::new();
        let requests = endpoint.requests();
        let fixture = build_fixture(endpoint);
        let output = fixture
            .host
            .call(
                TOOL_NAVIGATE,
                r#"{"tabId": 7, "url": "https://foo.test/landing"}"#,
            )
            .await
            .expect("consent required is a tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "origin_consent_required");
        assert_eq!(output["origin"], "foo.test");
        assert_eq!(output["tool"], TOOL_NAVIGATE);
        let hint = output["hint"].as_str().unwrap();
        assert!(hint.contains("HitlKind::Permission"), "hint: {hint}");
        assert!(hint.contains("browser_origin"), "hint: {hint}");
        assert!(hint.contains("once/site/all/decline"), "hint: {hint}");
        // Navigate resolves the origin from the url argument: no getTabs call.
        assert_eq!(requests.count(METHOD_GET_TABS), 0);
    }

    #[tokio::test]
    async fn about_blank_and_missing_url_carry_no_consent_origin() {
        let endpoint = MockEndpoint::new()
            .script(
                "createTab",
                vec![ok(json!({"tabId": 9})), ok(json!({"tabId": 10}))],
            )
            .script(
                "ensureTabGroup",
                vec![ok(json!({"groupId": 3})), ok(json!({"groupId": 3}))],
            )
            .script("assignTab", vec![ok(json!({})), ok(json!({}))]);
        let fixture = build_fixture(endpoint);
        let output = fixture
            .host
            .call(TOOL_NEW_TAB, r#"{"url": "about:blank"}"#)
            .await
            .expect("about:blank is ungated");
        assert_eq!(serde_json::from_str::<Value>(&output).unwrap()["tabId"], 9);
        let output = fixture
            .host
            .call(TOOL_NEW_TAB, "{}")
            .await
            .expect("missing url is ungated");
        assert_eq!(serde_json::from_str::<Value>(&output).unwrap()["tabId"], 10);
    }

    #[tokio::test]
    async fn new_tab_with_url_is_gated_on_the_url_origin() {
        let endpoint = MockEndpoint::new();
        let fixture = build_fixture(endpoint);
        let output = fixture
            .host
            .call(TOOL_NEW_TAB, r#"{"url": "https://bar.test"}"#)
            .await
            .expect("consent required is a tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "origin_consent_required");
        assert_eq!(output["origin"], "bar.test");
    }

    #[tokio::test]
    async fn run_id_is_injected_for_lease_bookkeeping() {
        let endpoint = MockEndpoint::new()
            .script(METHOD_GET_TABS, vec![ok(tabs_with(7, "https://foo.test"))])
            .script("turnEnded", vec![ok(json!({}))]);
        let requests = endpoint.requests();
        let store = DesktopSessionStore::in_memory().expect("session store");
        store
            .insert_browser_origin_grant(&grant("foo.test", BrowserOriginDecision::Site))
            .expect("insert site");
        let once = new_browser_once_consents();
        let inner = Arc::new(BrowserToolHost::new(endpoint));
        let host = BrowserRunToolHost::new(Arc::clone(&inner), store, Some(test_run()), once);
        host.call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("claim tab");
        // The lease must be recorded under the injected run id: turn_ended
        // with the run's id ships exactly that lease to the extension.
        inner.turn_ended("run-1").await;
        let turn_ended = requests.params_of("turnEnded");
        assert_eq!(turn_ended.len(), 1);
        assert_eq!(turn_ended[0]["leases"][0]["tabId"], 7);
    }

    #[tokio::test]
    async fn consent_retry_after_grant_is_not_trapped_by_ledger_dedup() {
        // Full build-mode stack: AuthorizedRunToolHost(BrowserRunToolHost(
        // BrowserToolHost)). The consent short-circuit is an Ok tool result,
        // so the authorized host must not ledger it as a Completed
        // invocation; otherwise a byte-identical retry after the user grants
        // consent would hit the "already completed" replay.
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: format!("conversation-{}", uuid::Uuid::new_v4()),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Browser consent retry".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("conversation");
        store
            .replace_agent_plan_tasks(
                &conversation.id,
                &[json!({
                    "id": "browser-dedup-task",
                    "conversation_id": conversation.id,
                    "content": "Exercise the consent retry",
                    "status": "pending",
                    "priority": "high",
                    "order_index": 0,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })],
            )
            .expect("plan");
        let plan = store
            .latest_draft_plan(&conversation.id)
            .expect("load plan")
            .expect("plan");
        let outcome = store
            .approve_plan_and_start_in_environment(ApprovePlanStartInput {
                conversation_id: &conversation.id,
                project_id: "local-project",
                plan_version_id: &plan.id,
                expected_plan_version: plan.version,
                idempotency_key: "browser-dedup-run",
                message_id: "browser-dedup-message",
                request_message: "Browse with consent",
                environment: None,
                requested_environment_kind: DesktopExecutionEnvironmentKind::Local,
                permission_profile: DesktopPermissionProfile::FullAccess,
                now: &now_iso(),
            })
            .expect("approve and start");
        let run = store
            .prepare_run_for_execution(&outcome.run.id, &now_iso())
            .expect("prepare run")
            .expect("run started");

        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![
                ok(tabs_with(7, "https://foo.test")),
                ok(tabs_with(7, "https://foo.test")),
            ],
        );
        let requests = endpoint.requests();
        let gated = BrowserRunToolHost::new(
            Arc::new(BrowserToolHost::new(endpoint)),
            store.clone(),
            Some(run.clone()),
            new_browser_once_consents(),
        );
        let host = AuthorizedRunToolHost::new(Arc::new(gated), store.clone(), run);

        let first = host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("consent required is a tool result");
        assert_eq!(
            serde_json::from_str::<Value>(&first).unwrap()["error"],
            "origin_consent_required"
        );
        assert!(
            store
                .list_tool_invocations(&conversation.id)
                .expect("invocations")
                .is_empty(),
            "browser tools bypass the invocation ledger"
        );

        // The user grants the origin; the identical retry must execute.
        store
            .insert_browser_origin_grant(&grant("foo.test", BrowserOriginDecision::Site))
            .expect("insert site grant");
        let second = host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("retry executes");
        let second: Value = serde_json::from_str(&second).unwrap();
        assert_eq!(second["tabId"], 7, "retry must not replay: {second}");
        // Both calls resolved the origin (the second via the URL cache).
        assert_eq!(requests.count(METHOD_GET_TABS), 1);
    }

    #[test]
    fn origin_host_extraction() {
        assert_eq!(
            origin_host("https://Example.COM/path"),
            Some("example.com".to_string())
        );
        assert_eq!(
            origin_host("http://foo.test:8080/x"),
            Some("foo.test".to_string())
        );
        assert_eq!(origin_host("about:blank"), None);
        assert_eq!(origin_host("chrome://extensions"), None);
        assert_eq!(origin_host("not a url"), None);
    }
}
