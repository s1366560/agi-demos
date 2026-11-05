//! Run-scoped origin-consent gate for the browser tool surface (M2, see
//! `docs/design/browser-extension-bridge.md` §4.3) plus the M3 additions:
//! the full-CDP capability gate (`browser_cdp_raw`), the brokered credential
//! fill (`browser_fill_credentials`, values never leave the sidecar), the
//! browser action audit sink, and screenshot artifact delivery.
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
//!
//! Every call (read and write) is also recorded in the browser action audit
//! with a sanitized target summary — input values (especially credentials)
//! never reach the audit row, and an audit write failure never fails the
//! tool call.

use std::{
    collections::BTreeSet,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::Instant,
};

use agistack_adapters_browser::{
    actions::{
        TOOL_CLAIM_TAB, TOOL_CLICK, TOOL_MARK_TAB, TOOL_NAVIGATE, TOOL_NEW_TAB, TOOL_SCROLL,
        TOOL_TYPE,
    },
    facade::{self, TOOL_CDP as TOOL_FACADE_CDP, TOOL_WRITE as TOOL_FACADE_WRITE},
    host::{BridgeEndpoint, BrowserToolHost, TOOL_CDP_RAW, TOOL_SCREENSHOT},
};
use agistack_core::ports::{
    CoreError, CoreResult, PermissionKind, PermissionRequired, ToolHost, ToolResult,
};
use async_trait::async_trait;
use base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine as _};
use serde_json::{json, Value};
use url::Url;

use super::{
    authority_store::{
        credential_fill_once_key, full_cdp_once_key, BrowserCapabilityDecision,
        BrowserOriginDecision, DesktopRun, FULL_CDP_CAPABILITY,
    },
    provider_credentials::SiteCredentialBroker,
    session_store::DesktopSessionStore,
};

#[path = "browser_auth_host.rs"]
mod auth;
#[path = "cloud_browser_tool_host.rs"]
mod cloud;
pub(super) use cloud::{BrowserStepAuthority, CloudBrowserToolHost};

/// The wrapper-composed credential fill tool (M3). Implemented here (not in
/// the browser crate) because the vault, the consent matrix, and the
/// audit sink are all sidecar concerns; the inner host only executes the
/// composed `Runtime.evaluate` fill script.
pub(super) const TOOL_FILL_CREDENTIALS: &str = "browser_fill_credentials";

/// Mutating browser tools gated by origin consent. Read tools pass through.
const GATED_BROWSER_TOOLS: &[&str] = &[
    TOOL_NAVIGATE,
    TOOL_CLICK,
    TOOL_TYPE,
    TOOL_SCROLL,
    TOOL_NEW_TAB,
    TOOL_CLAIM_TAB,
    TOOL_MARK_TAB,
    TOOL_CDP_RAW,
    TOOL_FACADE_WRITE,
    TOOL_FACADE_CDP,
];

const DECLINE_HINT: &str = "The user declined this origin. Do not retry or work around.";
const CONSENT_HINT: &str =
    "Ask the user for permission to interact with this origin via a permission request \
     (HitlKind::Permission, target kind browser_origin, scopes: once/site/all/decline).";
const FULL_CDP_DISABLED_HINT: &str =
    "Enable full CDP access in Settings → Browser integration (elevated risk).";
const FULL_CDP_CONSENT_HINT: &str =
    "Ask the user via a permission request (target kind browser_full_cdp, scopes: once/site). \
     Note: no all-sites scope exists for full CDP.";
const CREDENTIAL_FILL_CONSENT_HINT: &str =
    "Ask the user via a permission request (HitlKind::Permission, target kind \
     browser_credential_fill, scope: once). Credential-fill consent is never persisted.";

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
    owner: Option<super::auth_context::AuthenticatedContext>,
    once_consents: BrowserOnceConsents,
    full_cdp_enabled: bool,
    site_credentials: SiteCredentialBroker,
    screenshot_dir: Option<PathBuf>,
    file_roots: Vec<PathBuf>,
    blocked_file_roots: Vec<PathBuf>,
    artifact_root: Option<PathBuf>,
    browser_auth: Option<super::browser_auth::BrowserAuthBroker>,
}

impl<E: BridgeEndpoint> BrowserRunToolHost<E> {
    pub(super) fn new(
        inner: Arc<BrowserToolHost<E>>,
        session_store: DesktopSessionStore,
        run: Option<DesktopRun>,
        once_consents: BrowserOnceConsents,
        full_cdp_enabled: bool,
        site_credentials: SiteCredentialBroker,
        screenshot_dir: Option<PathBuf>,
    ) -> Self {
        let file_roots = run
            .as_ref()
            .and_then(|run| run.environment.as_ref())
            .map(|environment| vec![PathBuf::from(&environment.workspace_path)])
            .unwrap_or_default();
        let artifact_root = screenshot_dir
            .as_ref()
            .and_then(|path| path.parent())
            .map(|parent| parent.join("browser-downloads"));
        Self {
            inner,
            session_store,
            owner: run
                .as_ref()
                .and_then(|_| super::knowledge_authority_v2::agent_access::current_auth()),
            run,
            once_consents,
            full_cdp_enabled,
            site_credentials,
            screenshot_dir,
            file_roots,
            blocked_file_roots: Vec::new(),
            artifact_root,
            browser_auth: None,
        }
    }

    pub(super) fn with_file_roots(mut self, roots: Vec<PathBuf>) -> Self {
        self.file_roots = roots;
        self
    }
    pub(super) fn with_blocked_file_roots(mut self, roots: Vec<PathBuf>) -> Self {
        self.blocked_file_roots = roots;
        self
    }
    pub(super) fn with_artifact_root(mut self, root: PathBuf) -> Self {
        self.artifact_root = Some(root);
        self
    }
    pub(super) fn with_browser_auth(
        mut self,
        broker: super::browser_auth::BrowserAuthBroker,
    ) -> Self {
        self.browser_auth = Some(broker);
        self
    }

    fn validate_owner(&self) -> CoreResult<()> {
        if self.owner.as_ref().is_some_and(|owner| {
            !self
                .session_store
                .session_context_is_current(owner, chrono::Utc::now().timestamp_millis())
                .unwrap_or(false)
        }) {
            return Err(CoreError::Tool(
                "browser owner session is no longer current".into(),
            ));
        }
        Ok(())
    }

    fn inject_file_authority(&self, input: &mut Value, run_id: &str) -> CoreResult<()> {
        let object = input
            .as_object_mut()
            .ok_or_else(|| CoreError::Tool("browser input must be an object".into()))?;
        for key in [
            "_authorized_file_roots",
            "_blocked_file_roots",
            "_artifact_root",
        ] {
            object.remove(key);
        }
        let configured = super::execution_authority::current_file_roots()
            .unwrap_or_else(|| self.file_roots.clone());
        let roots: Vec<_> = configured
            .iter()
            .filter_map(|root| root.canonicalize().ok())
            .collect();
        let blocked: Vec<_> = self
            .blocked_file_roots
            .iter()
            .filter_map(|root| root.canonicalize().ok())
            .collect();
        object.insert("_authorized_file_roots".into(), json!(roots));
        object.insert("_blocked_file_roots".into(), json!(blocked));
        let root = super::execution_authority::current_download_root()
            .or_else(|| self.artifact_root.clone());
        if let Some(root) = root {
            // UUID v5 makes the trusted run id an opaque path component.
            let directory = root.join(
                uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_OID, run_id.as_bytes()).to_string(),
            );
            std::fs::create_dir_all(&directory)
                .map_err(|_| CoreError::Tool("browser artifact directory is unavailable".into()))?;
            let directory = directory
                .canonicalize()
                .map_err(|_| CoreError::Tool("browser artifact directory is unavailable".into()))?;
            object.insert("_artifact_root".into(), json!(directory));
        }
        Ok(())
    }

    /// Resolve the consent origin for a mutating call: `browser_navigate`
    /// (and `browser_new_tab` with a `url`) gate on the argument URL, the
    /// tab-bound tools gate on the tab's current URL. `None` means the call
    /// carries no consent origin (about:blank, non-http(s), no url arg).
    async fn resolve_origin(&self, tool: &str, input: &Value) -> CoreResult<Option<String>> {
        if matches!(tool, TOOL_FACADE_WRITE | TOOL_FACADE_CDP)
            && input.get("tabId").is_none()
            && input
                .get("operation")
                .and_then(Value::as_str)
                .is_some_and(|operation| {
                    operation == "nameSession"
                        || operation.starts_with("capability.management.")
                        || operation.starts_with("capability.visibility.")
                        || operation.starts_with("capability.viewport.")
                })
        {
            return Ok(None);
        }
        if matches!(tool, TOOL_FACADE_WRITE | TOOL_FACADE_CDP)
            && matches!(
                input.get("operation").and_then(Value::as_str),
                Some("tabs.new" | "tab.goto")
            )
        {
            let url = input
                .pointer("/args/0")
                .and_then(Value::as_str)
                .ok_or_else(|| CoreError::Tool("navigation requires a URL".into()))?;
            return Ok(origin_host(url));
        }
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
                let url = self.inner.current_url_for_input(input, tab_id).await?;
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
    fn gate(
        &self,
        tool: &str,
        origin: Option<String>,
        original_input: &str,
    ) -> CoreResult<Option<ToolResult>> {
        let Some(host) = origin else {
            return Ok(None);
        };
        match self.persisted_verdict(&host)? {
            Some(false) => {
                return Ok(Some(ToolResult::text(
                    json!({
                        "error": "origin_declined",
                        "origin": host,
                        "hint": DECLINE_HINT,
                    })
                    .to_string(),
                )));
            }
            Some(true) => return Ok(None),
            None => {}
        }
        if self.once_consent_active(&host) {
            return Ok(None);
        }
        Ok(Some(
            PermissionRequired::new(
                PermissionKind::BrowserOrigin,
                super::execution_authority::permission_binding(tool, original_input)?,
                json!({
                    "error": "origin_consent_required",
                    "origin": host,
                    "tool": tool,
                    "hint": CONSENT_HINT,
                }),
            )
            .into_result(),
        ))
    }

    /// The full-CDP capability gate for `browser_cdp_raw` (M3): desktop
    /// enablement first, then the persisted per-origin capability decision
    /// (decline blocks, site allows), then the run-scoped once cache. There
    /// is no all-sites scope for full CDP.
    fn full_cdp_gate(
        &self,
        tool: &str,
        origin: Option<String>,
        original_input: &str,
    ) -> CoreResult<Option<ToolResult>> {
        if !self.full_cdp_enabled {
            return Ok(Some(ToolResult::text(
                json!({
                    "error": "full_cdp_disabled",
                    "hint": FULL_CDP_DISABLED_HINT,
                })
                .to_string(),
            )));
        }
        let Some(host) = origin else {
            return Ok(Some(
                PermissionRequired::new(
                    PermissionKind::BrowserFullCdp,
                    super::execution_authority::permission_binding(tool, original_input)?,
                    json!({
                        "error": "full_cdp_consent_required",
                        "origin": Value::Null,
                        "hint": FULL_CDP_CONSENT_HINT,
                    }),
                )
                .into_result(),
            ));
        };
        let decisions = self
            .session_store
            .active_browser_capability_decisions(&host, FULL_CDP_CAPABILITY)
            .map_err(CoreError::Tool)?;
        if decisions
            .iter()
            .any(|grant| grant.decision == BrowserCapabilityDecision::Decline)
        {
            return Ok(Some(ToolResult::text(
                json!({
                    "error": "full_cdp_declined",
                    "origin": host,
                    "hint": DECLINE_HINT,
                })
                .to_string(),
            )));
        }
        if decisions
            .iter()
            .any(|grant| grant.decision == BrowserCapabilityDecision::Site)
        {
            return Ok(None);
        }
        if self.once_consent_active(&full_cdp_once_key(&host)) {
            return Ok(None);
        }
        Ok(Some(
            PermissionRequired::new(
                PermissionKind::BrowserFullCdp,
                super::execution_authority::permission_binding(tool, original_input)?,
                json!({
                    "error": "full_cdp_consent_required",
                    "origin": host,
                    "hint": FULL_CDP_CONSENT_HINT,
                }),
            )
            .into_result(),
        ))
    }

    /// `browser_fill_credentials` (M3): brokered credential fill. The origin
    /// consent matrix runs first (M2 rules), then the run-scoped
    /// credential-fill once consent (never persisted), then the vault record
    /// is loaded and a fill script is composed and executed through the inner
    /// host. The password never appears in the tool result — only the list of
    /// filled field kinds is returned.
    async fn fill_credentials(
        &self,
        input: &Value,
        original_input: &str,
    ) -> CoreResult<ToolResult> {
        let _tab_id = input.get("tabId").and_then(Value::as_i64).ok_or_else(|| {
            CoreError::Tool(format!(
                "tool '{TOOL_FILL_CREDENTIALS}' requires a numeric 'tabId'"
            ))
        })?;
        let origin = input
            .get("origin")
            .and_then(Value::as_str)
            .map(|origin| origin.trim().to_lowercase())
            .filter(|origin| !origin.is_empty())
            .ok_or_else(|| {
                CoreError::Tool(format!(
                    "tool '{TOOL_FILL_CREDENTIALS}' requires a bare-host 'origin'"
                ))
            })?;
        if let Some(result) =
            self.gate(TOOL_FILL_CREDENTIALS, Some(origin.clone()), original_input)?
        {
            return Ok(result);
        }
        if !self.once_consent_active(&credential_fill_once_key(&origin)) {
            return Ok(PermissionRequired::new(
                PermissionKind::BrowserCredentialFill,
                super::execution_authority::permission_binding(
                    TOOL_FILL_CREDENTIALS,
                    original_input,
                )?,
                json!({
                    "error": "credential_fill_consent_required",
                    "origin": origin,
                    "hint": CREDENTIAL_FILL_CONSENT_HINT,
                }),
            )
            .into_result());
        }
        self.fill_credentials_after_consent(input)
            .await
            .map(ToolResult::text)
    }

    /// Called only after the local or authenticated cloud authority has admitted
    /// this exact credential-fill step. The vault and page checks stay local.
    async fn fill_credentials_after_consent(&self, input: &Value) -> CoreResult<String> {
        let tab_id = input
            .get("tabId")
            .and_then(Value::as_i64)
            .ok_or_else(|| CoreError::Tool("credential fill requires a numeric tabId".into()))?;
        let origin = input
            .get("origin")
            .and_then(Value::as_str)
            .map(|origin| origin.trim().to_lowercase())
            .filter(|origin| !origin.is_empty())
            .ok_or_else(|| CoreError::Tool("credential fill requires a bare-host origin".into()))?;
        let username = input.get("username").and_then(Value::as_str);
        let current_url = self.inner.current_url_for_input(input, tab_id).await?;
        self.validate_owner()?;
        if origin_host(&current_url).as_deref() != Some(origin.as_str()) {
            return Ok(json!({"error":"credential_origin_mismatch"}).to_string());
        }
        let metadata = self
            .session_store
            .active_browser_site_credential(&origin, username)
            .map_err(CoreError::Tool)?;
        let Some(metadata) = metadata else {
            return Ok(json!({
                "error": "credential_not_found",
                "origin": origin,
            })
            .to_string());
        };
        let secret = self
            .site_credentials
            .load(&metadata.credential_ref, &origin, Some(&metadata.username))
            .map_err(|_| CoreError::Tool("browser site credential is unavailable".to_string()))?;
        let Some(secret) = secret else {
            return Ok(json!({
                "error": "credential_not_found",
                "origin": origin,
            })
            .to_string());
        };
        let script = format!("(() => {{ if (location.hostname.toLowerCase() !== {}) throw new Error('credential origin changed'); return {}; }})()", serde_json::to_string(&origin).map_err(|error| CoreError::Tool(error.to_string()))?, credential_fill_script(&secret.username, &secret.password));
        let raw = self
            .inner
            .call(
                TOOL_CDP_RAW,
                &json!({
                    "tabId": tab_id,
                    "backend": input.get("backend").cloned().unwrap_or(json!("chrome")),
                    "method": "Runtime.evaluate",
                    "params": { "expression": script, "returnByValue": true },
                })
                .to_string(),
            )
            .await?;
        let parsed: Value = serde_json::from_str(&raw).map_err(|error| {
            CoreError::Tool(format!("credential fill result is invalid: {error}"))
        })?;
        if parsed.pointer("/result/exceptionDetails").is_some() {
            return Ok(json!({
                "error": "credential_fill_failed",
                "origin": origin,
            })
            .to_string());
        }
        let filled: Vec<&str> = parsed
            .pointer("/result/result/value/filled")
            .and_then(Value::as_array)
            .map(|items| items.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default();
        Ok(json!({ "filled": filled }).to_string())
    }

    /// Screenshot delivery (M3): decode the base64 JPEG, write it under the
    /// data directory's `browser-screenshots/`, and replace the tool result
    /// with a compact reference. With a run binding the screenshot is
    /// registered through the artifact machinery (`desktop_artifact_versions`);
    /// without one (or if that registration fails) the result falls back to
    /// the file path.
    fn deliver_screenshot(&self, input: &Value, output: &str) -> String {
        let fallback = || output.to_string();
        let Ok(parsed) = serde_json::from_str::<Value>(output) else {
            return fallback();
        };
        let Some(data) = parsed.get("dataBase64").and_then(Value::as_str) else {
            return fallback();
        };
        let width = parsed.get("width").and_then(Value::as_u64).unwrap_or(0);
        let height = parsed.get("height").and_then(Value::as_u64).unwrap_or(0);
        let Some(directory) = self.screenshot_dir.clone() else {
            return fallback();
        };
        let bytes = match BASE64_STANDARD.decode(data) {
            Ok(bytes) => bytes,
            Err(_) => return fallback(),
        };
        let tab_id = input.get("tabId").and_then(Value::as_i64).unwrap_or(0);
        let timestamp = chrono::Utc::now().timestamp_millis();
        let filename = format!("browser-screenshot-{tab_id}-{timestamp}.jpg");
        let path = directory.join(&filename);
        if let Err(error) =
            std::fs::create_dir_all(&directory).and_then(|_| std::fs::write(&path, &bytes))
        {
            eprintln!("failed to write browser screenshot: {error}");
            return fallback();
        }
        let path = path.to_string_lossy().into_owned();
        if let Some(run) = self.run.as_ref() {
            let artifact_output = json!({
                "artifact_id": format!("browser-screenshot-{tab_id}"),
                "artifact_version_id": format!("browser-screenshot-version-{}", uuid::Uuid::new_v4()),
                "filename": filename,
                "path": path,
                "relative_path": format!("browser-screenshots/{filename}"),
                "mime_type": "image/jpeg",
                "bytes": bytes.len() as u64,
            });
            match self.session_store.record_artifact_version(
                &run.conversation_id,
                Some(&run.id),
                &artifact_output,
                &super::now_iso(),
            ) {
                Ok(version) => {
                    return json!({
                        "artifact_id": version.artifact_id,
                        "artifact_version_id": version.id,
                        "width": width,
                        "height": height,
                    })
                    .to_string();
                }
                Err(error) => {
                    eprintln!("failed to persist browser screenshot artifact: {error}");
                }
            }
        }
        json!({
            "path": path,
            "width": width,
            "height": height,
        })
        .to_string()
    }

    /// Record one audit row for a browser tool call. Best-effort: the origin
    /// lookup and the write itself never fail the tool call. The target
    /// summary is a compact sanitized handle (CDP method, snapshot ref, host)
    /// — never an input value.
    fn record_audit(
        &self,
        tool: &str,
        input: Option<&Value>,
        origin: Option<String>,
        result: &CoreResult<ToolResult>,
        started: Instant,
    ) {
        let target_summary = audit_target_summary(tool, input, origin.as_deref());
        let outcome = audit_outcome(result);
        let run_id = self.run.as_ref().map(|run| run.id.clone());
        if let Err(error) = self.session_store.insert_browser_action_audit(
            run_id.as_deref(),
            tool,
            origin.as_deref(),
            &target_summary,
            outcome,
            started.elapsed().as_millis() as i64,
            chrono::Utc::now().timestamp_millis(),
        ) {
            eprintln!("failed to record browser action audit for {tool}: {error}");
        }
    }

    /// Best-effort audit origin: the argument URL for navigation tools, the
    /// declared origin for credential fills, the tab's current URL for
    /// tab-bound read tools. Mutating calls reuse their authorization origin.
    /// Only an already-bound backend can be inspected here. Never
    /// fails; an unresolvable origin audits as NULL.
    async fn audit_origin(&self, tool: &str, input: Option<&Value>) -> Option<String> {
        self.validate_owner().ok()?;
        let input = input?;
        match tool {
            TOOL_NAVIGATE | TOOL_NEW_TAB => input
                .get("url")
                .and_then(Value::as_str)
                .and_then(origin_host),
            TOOL_FILL_CREDENTIALS => input
                .get("origin")
                .and_then(Value::as_str)
                .map(|origin| origin.trim().to_lowercase())
                .filter(|origin| !origin.is_empty()),
            _ => {
                let tab_id = input.get("tabId").and_then(Value::as_i64)?;
                let url = self.inner.current_url_for_input(input, tab_id).await.ok()?;
                origin_host(&url)
            }
        }
    }
}

/// Compact, sanitized audit target handle per tool: the CDP method for
/// `browser_cdp_raw`, the snapshot ref for click/type, the origin host for
/// navigation and credential fills, the tab id for the remaining tab-bound
/// tools. Input *values* (typed text, CDP params, credentials) are never
/// part of the summary.
fn audit_target_summary(tool: &str, input: Option<&Value>, origin: Option<&str>) -> String {
    let Some(input) = input else {
        return String::new();
    };
    let summary = match tool {
        TOOL_CDP_RAW => input
            .get("method")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        TOOL_CLICK | TOOL_TYPE => input
            .get("ref")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        TOOL_NAVIGATE | TOOL_NEW_TAB | TOOL_FILL_CREDENTIALS => {
            origin.unwrap_or_default().to_string()
        }
        _ => input
            .get("tabId")
            .and_then(Value::as_i64)
            .map(|tab_id| format!("tab:{tab_id}"))
            .unwrap_or_default(),
    };
    summary.chars().take(200).collect()
}

/// Only trusted gate metadata identifies pending permission. Application error
/// payloads stay ordinary outcomes; transport/execution failures audit as error.
fn audit_outcome(result: &CoreResult<ToolResult>) -> &'static str {
    let Ok(output) = result else {
        return "error";
    };
    if output.permission_required.is_some() {
        return "consent_required";
    }
    let Ok(parsed) = serde_json::from_str::<Value>(&output.output_json) else {
        return "ok";
    };
    let Some(error) = parsed.get("error").and_then(Value::as_str) else {
        return "ok";
    };
    if matches!(error, "origin_declined" | "full_cdp_declined") {
        "declined"
    } else {
        "error"
    }
}

/// The credential fill script executed in the page. Values are JSON-encoded
/// string literals (safe embedding); the script returns only the list of
/// filled field kinds — never the values themselves.
fn credential_fill_script(username: &str, password: &str) -> String {
    let username = serde_json::to_string(username).unwrap_or_else(|_| "\"\"".to_string());
    let password = serde_json::to_string(password).unwrap_or_else(|_| "\"\"".to_string());
    format!(
        r#"(() => {{
  const username = {username};
  const password = {password};
  const set = (el, value) => {{
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  const passwordField = document.querySelector('input[type="password"]');
  if (!passwordField) return {{ filled: [] }};
  let userField = document.querySelector('input[autocomplete="username"]');
  if (!userField) {{
    const candidates = Array.from(
      document.querySelectorAll('input[type="text"], input[type="email"], input:not([type])')
    );
    const before = candidates.filter((el) =>
      !!(el.compareDocumentPosition(passwordField) & Node.DOCUMENT_POSITION_FOLLOWING)
    );
    userField = before[before.length - 1] || null;
  }}
  const filled = [];
  if (userField) {{ set(userField, username); filled.push('username'); }}
  set(passwordField, password);
  filled.push('password');
  return {{ filled }};
}})()"#
    )
}

/// MCP-shaped metadata for `browser_fill_credentials`, merged into the local
/// tool listing next to the browser crate's metadata. The schema tolerates
/// extra properties so the run wrapper's `_run_id` injection does not trip
/// validation.
pub(super) fn fill_credentials_tool_metadata() -> Value {
    json!({
        "name": TOOL_FILL_CREDENTIALS,
        "description": "Fill the stored site credential for an origin into the tab's login \
            form (mutating; requires origin consent plus a per-run credential-fill approval). \
            Credential values are brokered by the sidecar and never appear in tool arguments, \
            results, or logs. Returns {filled: [\"username\", \"password\"]} or an error \
            payload such as {error: \"credential_not_found\"}.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tabId": {
                    "type": "integer",
                    "description": "Target tab id from browser_list_tabs",
                },
                "origin": {
                    "type": "string",
                    "description": "Bare host the credential is stored for (e.g. example.com)",
                },
                "username": {
                    "type": "string",
                    "description": "Optional selector when several credentials exist for the origin",
                },
            },
            "required": ["tabId", "origin"],
            "additionalProperties": true,
        },
    })
}

#[async_trait]
impl<E: BridgeEndpoint> ToolHost for BrowserRunToolHost<E> {
    fn tool_definition(&self, name: &str) -> Option<agistack_core::ports::ToolDefinition> {
        if !self.list_tools().iter().any(|tool| tool == name) {
            return None;
        }
        let metadata = if name == TOOL_FILL_CREDENTIALS {
            fill_credentials_tool_metadata()
        } else {
            agistack_adapters_browser::host::list_tool_metadata()
                .into_iter()
                .find(|metadata| metadata["name"].as_str() == Some(name))?
        };
        Some(agistack_core::ports::ToolDefinition {
            name: name.to_string(),
            description: metadata["description"].as_str().map(str::to_string),
            input_schema: metadata.get("inputSchema").cloned(),
        })
    }

    fn list_tools(&self) -> Vec<String> {
        let mut tools = self.inner.list_tools();
        tools.push(TOOL_FILL_CREDENTIALS.to_string());
        tools
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        self.call_with_content(tool, input_json)
            .await
            .map(|result| result.output_json)
    }

    async fn call_with_content(&self, tool: &str, input_json: &str) -> CoreResult<ToolResult> {
        let started = Instant::now();
        let audit_input: Option<Value> = if input_json.trim().is_empty() {
            Some(json!({}))
        } else {
            serde_json::from_str(input_json).ok()
        };
        let mut bound_input = None;
        let mut resolved_origin = None;
        let dispatch = self.dispatch(tool, input_json, &mut bound_input, &mut resolved_origin);
        let result = if let Some(run) = &self.run {
            let caller = super::browser_caller::for_run(run)?;
            agistack_adapters_browser::caller::scope(caller, dispatch).await
        } else {
            dispatch.await
        };
        let origin = match resolved_origin {
            Some(origin) => origin,
            None => self.audit_origin(tool, bound_input.as_ref()).await,
        };
        self.record_audit(
            tool,
            bound_input.as_ref().or(audit_input.as_ref()),
            origin,
            &result,
            started,
        );
        result
    }
}

impl<E: BridgeEndpoint> BrowserRunToolHost<E> {
    async fn dispatch(
        &self,
        tool: &str,
        input_json: &str,
        bound_input: &mut Option<Value>,
        resolved_origin: &mut Option<Option<String>>,
    ) -> CoreResult<ToolResult> {
        self.validate_owner()?;
        let mut input: Value = if input_json.trim().is_empty() {
            json!({})
        } else {
            match serde_json::from_str(input_json) {
                Ok(input) => input,
                // Let the inner host produce its own invalid-input error.
                Err(_) if tool != TOOL_FILL_CREDENTIALS => {
                    return self.inner.call_with_content(tool, input_json).await;
                }
                Err(error) => {
                    return Err(CoreError::Tool(format!("invalid tool input json: {error}")));
                }
            }
        };
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
        input = self.inner.bind_input(tool, &input).await?;
        *bound_input = Some(input.clone());
        self.validate_owner()?;
        if let (Some(run), Value::Object(map)) = (self.run.as_ref(), &mut input) {
            map.insert("_run_id".to_string(), json!(run.id));
        }
        self.inject_file_authority(
            &mut input,
            self.run
                .as_ref()
                .map(|run| run.id.as_str())
                .unwrap_or("unbound"),
        )?;
        if tool == TOOL_FILL_CREDENTIALS {
            return self.fill_credentials(&input, input_json).await;
        }
        if GATED_BROWSER_TOOLS.contains(&tool) {
            // A failed authorization lookup must not be retried for audit: a
            // second lookup could observe a different page after the denial.
            *resolved_origin = Some(None);
            let origin = self.resolve_origin(tool, &input).await?;
            *resolved_origin = Some(origin.clone());
            self.validate_owner()?;
            if let Some(result) = self.gate(tool, origin.clone(), input_json)? {
                return Ok(result);
            }
            if matches!(tool, TOOL_CDP_RAW | TOOL_FACADE_CDP) {
                if let Some(result) = self.full_cdp_gate(tool, origin, input_json)? {
                    return Ok(result);
                }
            }
        }
        if input["operation"] == "capability.browserAuth.request" {
            return self
                .request_browser_auth(&input)
                .await
                .map(ToolResult::text);
        }
        self.validate_owner()?;
        let mut output = self
            .inner
            .call_with_content(
                tool,
                &serde_json::to_string(&input).map_err(|error| {
                    CoreError::Tool(format!("failed to encode tool input: {error}"))
                })?,
            )
            .await?;
        self.validate_owner()?;
        if tool == TOOL_SCREENSHOT {
            output.output_json = self.deliver_screenshot(&input, &output.output_json);
            return Ok(output);
        }
        if input["operation"] == "capabilities.list"
            && input.get("tabId").is_some()
            && self.browser_auth.is_some()
            && self.run.is_some()
        {
            let mut capabilities: Value = serde_json::from_str(&output.output_json)
                .map_err(|_| CoreError::Tool("invalid browser capabilities".into()))?;
            if let Some(capabilities) = capabilities.as_array_mut() {
                capabilities.push(json!("browserAuth"));
            }
            output.output_json = capabilities.to_string();
        }
        Ok(output)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::{HashMap, VecDeque};

    use agistack_adapters_browser::protocol::{
        BridgeNotification, METHOD_ATTACH, METHOD_EXECUTE_CDP, METHOD_GET_TABS,
    };
    use tokio::sync::broadcast;

    use super::super::{
        authority_store::{
            BrowserCapabilityDecision, BrowserCapabilityGrant, BrowserOriginDecision,
            BrowserOriginGrant, DesktopExecutionEnvironmentKind, DesktopPermissionProfile,
            DesktopRunStatus,
        },
        authorized_tool_host::AuthorizedRunToolHost,
        now_iso,
        provider_credentials::ProviderCredentialBroker,
        session_store::ApprovePlanStartInput,
        ConversationCapabilityMode, ConversationRunMode, LocalConversation,
    };

    fn test_site_credentials(store: &DesktopSessionStore) -> SiteCredentialBroker {
        ProviderCredentialBroker::in_memory(store.installation_id())
            .expect("provider credential broker")
            .site_credential_broker()
    }

    #[tokio::test]
    async fn browser_model_contracts_preserve_native_and_credential_fill_schemas() {
        let fixture = build_fixture(MockEndpoint::new());
        let contracts = fixture.host.tool_definitions().expect("model contracts");
        for metadata in agistack_adapters_browser::host::list_tool_metadata()
            .into_iter()
            .chain([fill_credentials_tool_metadata()])
        {
            let name = metadata["name"].as_str().expect("tool name");
            let contract = contracts
                .iter()
                .find(|item| item.name == name)
                .expect("advertised browser tool");
            assert_eq!(
                contract.input_schema.as_ref(),
                Some(&metadata["inputSchema"])
            );
            assert_eq!(
                contract.description.as_deref(),
                metadata["description"].as_str()
            );
            assert!(contract.input_schema.as_ref().unwrap()["properties"]
                .get("_run_id")
                .is_none());
        }
        assert!(fixture.host.tool_definition("unavailable").is_none());
    }

    /// Scripted bridge endpoint: responses are queued per bridge method and
    /// every request is recorded behind a shared handle.
    struct MockEndpoint {
        responses: Mutex<HashMap<String, VecDeque<CoreResult<Value>>>>,
        requests: Arc<Mutex<Vec<(String, String, Value)>>>,
        notifications: broadcast::Sender<BridgeNotification>,
    }

    #[derive(Clone)]
    struct MockRequests(Arc<Mutex<Vec<(String, String, Value)>>>);

    impl MockRequests {
        fn count(&self, method: &str) -> usize {
            self.0
                .lock()
                .unwrap()
                .iter()
                .filter(|(_, m, _)| m == method)
                .count()
        }

        fn params_of(&self, method: &str) -> Vec<Value> {
            self.0
                .lock()
                .unwrap()
                .iter()
                .filter(|(_, m, _)| m == method)
                .map(|(_, _, params)| params.clone())
                .collect()
        }

        fn backends_of(&self, method: &str) -> Vec<String> {
            self.0
                .lock()
                .unwrap()
                .iter()
                .filter(|(_, m, _)| m == method)
                .map(|(backend, _, _)| backend.clone())
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

        fn scripted_request(
            &self,
            backend: &str,
            method: &str,
            params: Value,
        ) -> CoreResult<Value> {
            self.requests
                .lock()
                .unwrap()
                .push((backend.to_string(), method.to_string(), params));
            let mut responses = self.responses.lock().unwrap();
            let queue = responses
                .get_mut(method)
                .unwrap_or_else(|| panic!("no scripted responses for {method}"));
            queue
                .pop_front()
                .unwrap_or_else(|| panic!("scripted responses for {method} exhausted"))
        }
    }

    #[async_trait]
    impl BridgeEndpoint for MockEndpoint {
        async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
            self.scripted_request("chrome", method, params)
        }

        async fn request_on(
            &self,
            backend: &str,
            method: &str,
            params: Value,
        ) -> CoreResult<Value> {
            self.scripted_request(backend, method, params)
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
        site_credentials: SiteCredentialBroker,
        host: BrowserRunToolHost<MockEndpoint>,
    }

    fn build_fixture(endpoint: MockEndpoint) -> Fixture {
        build_fixture_with(endpoint, true, None)
    }

    fn build_fixture_with(
        endpoint: MockEndpoint,
        full_cdp_enabled: bool,
        screenshot_dir: Option<PathBuf>,
    ) -> Fixture {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let once = new_browser_once_consents();
        let site_credentials = test_site_credentials(&store);
        let host = BrowserRunToolHost::new(
            Arc::new(BrowserToolHost::new(endpoint)),
            store.clone(),
            Some(test_run()),
            Arc::clone(&once),
            full_cdp_enabled,
            site_credentials.clone(),
            screenshot_dir,
        );
        Fixture {
            store,
            once,
            site_credentials,
            host,
        }
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
            .call("browser_list_tabs", r#"{"backend": "chrome"}"#)
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
        let site_credentials = test_site_credentials(&store);
        let host = BrowserRunToolHost::new(
            Arc::clone(&inner),
            store,
            Some(test_run()),
            once,
            true,
            site_credentials,
            None,
        );
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
                permission_profile: DesktopPermissionProfile::ReadOnly,
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
            true,
            test_site_credentials(&store),
            None,
        );
        let tool_once = Arc::new(Mutex::new(BTreeSet::from([(
            run.id.clone(),
            TOOL_CLAIM_TAB.to_string(),
        )])));
        let host = AuthorizedRunToolHost::new(Arc::new(gated), store.clone(), run)
            .with_once_permissions(Arc::clone(&tool_once));

        let first = host
            .call(TOOL_CLAIM_TAB, r#"{"tabId": 7}"#)
            .await
            .expect("consent required is a tool result");
        assert_eq!(
            serde_json::from_str::<Value>(&first).unwrap()["error"],
            "origin_consent_required"
        );
        assert_eq!(
            tool_once.lock().unwrap().len(),
            1,
            "pending consent must not spend the action grant"
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
        assert!(
            tool_once.lock().unwrap().is_empty(),
            "successful action spends its exact once grant"
        );
        assert!(
            host.call(TOOL_CLAIM_TAB, r#"{"tabId":7}"#).await.is_err(),
            "the tool grant cannot execute a second action"
        );
        // Each action checks the live URL; consent retries cannot trust a cache.
        assert_eq!(requests.count(METHOD_GET_TABS), 2);
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

    fn capability_grant(host: &str, decision: BrowserCapabilityDecision) -> BrowserCapabilityGrant {
        BrowserCapabilityGrant {
            id: format!("capability-{}", uuid::Uuid::new_v4()),
            host: host.to_string(),
            capability: FULL_CDP_CAPABILITY.to_string(),
            decision,
            source_hitl_request_id: "hitl-1".to_string(),
            created_at: now_iso(),
            revoked_at: None,
        }
    }

    fn cdp_evaluate_endpoint(tab_url: &str) -> MockEndpoint {
        MockEndpoint::new()
            .script(METHOD_GET_TABS, vec![ok(tabs_with(7, tab_url))])
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script(
                METHOD_EXECUTE_CDP,
                vec![ok(
                    json!({"result": {"result": {"type": "number", "value": 2}}}),
                )],
            )
    }

    fn grant_origin(fixture: &Fixture, host: &str) {
        fixture
            .store
            .insert_browser_origin_grant(&grant(host, BrowserOriginDecision::Site))
            .expect("insert origin site grant");
    }

    #[tokio::test]
    async fn cdp_raw_is_blocked_when_full_cdp_access_is_disabled() {
        let endpoint = cdp_evaluate_endpoint("https://foo.test");
        let requests = endpoint.requests();
        let fixture = build_fixture_with(endpoint, false, None);
        grant_origin(&fixture, "foo.test");
        let output = fixture
            .host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Runtime.evaluate"}"#,
            )
            .await
            .expect("disabled full CDP is a tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "full_cdp_disabled");
        assert!(
            output["hint"].as_str().unwrap().contains("Settings"),
            "hint: {output}"
        );
        assert_eq!(requests.count(METHOD_EXECUTE_CDP), 0);
    }

    #[tokio::test]
    async fn cdp_raw_requires_a_full_cdp_capability_grant() {
        let endpoint = cdp_evaluate_endpoint("https://foo.test");
        let requests = endpoint.requests();
        let fixture = build_fixture(endpoint);
        grant_origin(&fixture, "foo.test");
        let output = fixture
            .host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Runtime.evaluate"}"#,
            )
            .await
            .expect("consent required is a tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "full_cdp_consent_required");
        assert_eq!(output["origin"], "foo.test");
        let hint = output["hint"].as_str().unwrap();
        assert!(hint.contains("browser_full_cdp"), "hint: {hint}");
        assert!(hint.contains("no all-sites scope"), "hint: {hint}");
        assert_eq!(requests.count(METHOD_EXECUTE_CDP), 0);
    }

    #[tokio::test]
    async fn cdp_raw_decline_rows_block_like_origin_declines() {
        let endpoint = cdp_evaluate_endpoint("https://foo.test");
        let requests = endpoint.requests();
        let fixture = build_fixture(endpoint);
        grant_origin(&fixture, "foo.test");
        fixture
            .store
            .insert_browser_capability_grant(&capability_grant(
                "foo.test",
                BrowserCapabilityDecision::Decline,
            ))
            .expect("insert capability decline");
        let output = fixture
            .host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Runtime.evaluate"}"#,
            )
            .await
            .expect("decline is a tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "full_cdp_declined");
        assert_eq!(output["origin"], "foo.test");
        assert_eq!(requests.count(METHOD_EXECUTE_CDP), 0);
    }

    #[tokio::test]
    async fn cdp_raw_delegates_with_a_site_capability_grant() {
        let endpoint = cdp_evaluate_endpoint("https://foo.test");
        let requests = endpoint.requests();
        let fixture = build_fixture(endpoint);
        grant_origin(&fixture, "foo.test");
        fixture
            .store
            .insert_browser_capability_grant(&capability_grant(
                "foo.test",
                BrowserCapabilityDecision::Site,
            ))
            .expect("insert capability site grant");
        let output = fixture
            .host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Runtime.evaluate", "params": {"expression": "1+1"}}"#,
            )
            .await
            .expect("granted call delegates");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["result"]["result"]["value"], 2);
        assert_eq!(requests.count(METHOD_EXECUTE_CDP), 1);
    }

    #[tokio::test]
    async fn cdp_raw_once_scope_is_run_scoped() {
        let endpoint = cdp_evaluate_endpoint("https://foo.test");
        let fixture = build_fixture(endpoint);
        grant_origin(&fixture, "foo.test");
        fixture
            .once
            .lock()
            .unwrap()
            .insert(("run-1".to_string(), full_cdp_once_key("foo.test")));
        let output = fixture
            .host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Runtime.evaluate"}"#,
            )
            .await
            .expect("once consent delegates");
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap()["result"]["result"]["value"],
            2
        );

        // A once consent recorded under another run does not apply.
        let endpoint = cdp_evaluate_endpoint("https://foo.test");
        let fixture = build_fixture(endpoint);
        grant_origin(&fixture, "foo.test");
        fixture
            .once
            .lock()
            .unwrap()
            .insert(("run-other".to_string(), full_cdp_once_key("foo.test")));
        let output = fixture
            .host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Runtime.evaluate"}"#,
            )
            .await
            .expect("consent required is a tool result");
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap()["error"],
            "full_cdp_consent_required"
        );
    }

    #[tokio::test]
    async fn cdp_raw_still_requires_origin_consent_first() {
        let endpoint = cdp_evaluate_endpoint("https://foo.test");
        let requests = endpoint.requests();
        let fixture = build_fixture(endpoint);
        fixture
            .store
            .insert_browser_capability_grant(&capability_grant(
                "foo.test",
                BrowserCapabilityDecision::Site,
            ))
            .expect("insert capability site grant");
        let output = fixture
            .host
            .call(
                TOOL_CDP_RAW,
                r#"{"tabId": 7, "method": "Runtime.evaluate"}"#,
            )
            .await
            .expect("origin consent required is a tool result");
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap()["error"],
            "origin_consent_required"
        );
        assert_eq!(requests.count(METHOD_EXECUTE_CDP), 0);
    }

    fn fill_endpoint(filled: Value) -> MockEndpoint {
        MockEndpoint::new()
            .script(METHOD_GET_TABS, vec![ok(tabs_with(7, "https://foo.test"))])
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script(
                METHOD_EXECUTE_CDP,
                vec![ok(json!({
                    "result": {"result": {"type": "object", "value": {"filled": filled}}},
                }))],
            )
    }

    fn consent_credential_fill(fixture: &Fixture, origin: &str) {
        fixture
            .once
            .lock()
            .unwrap()
            .insert(("run-1".to_string(), credential_fill_once_key(origin)));
    }

    fn store_credential(fixture: &Fixture, origin: &str, username: &str, password: &str) {
        let credential_ref = fixture
            .site_credentials
            .save(origin, username, password, &now_iso())
            .expect("save site credential");
        fixture
            .store
            .upsert_browser_site_credential(&super::super::authority_store::BrowserSiteCredential {
                id: format!("credential-{}", uuid::Uuid::new_v4()),
                origin: origin.to_string(),
                username: username.to_string(),
                credential_ref,
                created_at: now_iso(),
                revoked_at: None,
            })
            .expect("insert credential metadata");
    }

    #[tokio::test]
    async fn fill_credentials_applies_the_origin_consent_matrix_first() {
        let endpoint = MockEndpoint::new();
        let fixture = build_fixture(endpoint);
        let output = fixture
            .host
            .call(
                TOOL_FILL_CREDENTIALS,
                r#"{"tabId": 7, "origin": "foo.test"}"#,
            )
            .await
            .expect("origin consent required is a tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "origin_consent_required");
        assert_eq!(output["origin"], "foo.test");
    }

    #[tokio::test]
    async fn fill_credentials_requires_a_run_scoped_once_consent() {
        let endpoint = MockEndpoint::new();
        let fixture = build_fixture(endpoint);
        grant_origin(&fixture, "foo.test");
        store_credential(&fixture, "foo.test", "alice", "s3cret");
        let output = fixture
            .host
            .call(
                TOOL_FILL_CREDENTIALS,
                r#"{"tabId": 7, "origin": "foo.test"}"#,
            )
            .await
            .expect("credential fill consent required is a tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "credential_fill_consent_required");
        assert!(output["hint"]
            .as_str()
            .unwrap()
            .contains("browser_credential_fill"));
    }

    #[tokio::test]
    async fn fill_credentials_executes_the_fill_script_without_leaking_secrets() {
        let endpoint = fill_endpoint(json!(["username", "password"]));
        let requests = endpoint.requests();
        let fixture = build_fixture(endpoint);
        grant_origin(&fixture, "foo.test");
        consent_credential_fill(&fixture, "foo.test");
        store_credential(&fixture, "foo.test", "alice", "s3cret-value");
        let output = fixture
            .host
            .call(
                TOOL_FILL_CREDENTIALS,
                r#"{"tabId": 7, "origin": "foo.test"}"#,
            )
            .await
            .expect("fill result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["filled"], json!(["username", "password"]));
        assert!(
            !output.to_string().contains("s3cret-value"),
            "the password must never appear in the tool result: {output}"
        );
        // The fill script reached the bridge as Runtime.evaluate with the
        // credential values embedded in the page-side expression only.
        let executions = requests.params_of(METHOD_EXECUTE_CDP);
        assert_eq!(executions.len(), 1);
        assert_eq!(executions[0]["method"], "Runtime.evaluate");
        let expression = executions[0]["params"]["expression"].as_str().unwrap();
        assert!(expression.contains("s3cret-value"));
        assert!(expression.contains("alice"));
    }

    #[tokio::test]
    async fn fill_credentials_without_a_stored_credential_returns_not_found() {
        let endpoint = claim_tab_endpoint("https://foo.test");
        let fixture = build_fixture(endpoint);
        grant_origin(&fixture, "foo.test");
        consent_credential_fill(&fixture, "foo.test");
        let output = fixture
            .host
            .call(
                TOOL_FILL_CREDENTIALS,
                r#"{"tabId": 7, "origin": "foo.test"}"#,
            )
            .await
            .expect("not found is a tool result");
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["error"], "credential_not_found");
        assert_eq!(output["origin"], "foo.test");
    }

    #[tokio::test]
    async fn fill_credentials_tool_is_advertised() {
        let fixture = build_fixture(MockEndpoint::new());
        let tools = fixture.host.list_tools();
        assert!(tools.iter().any(|tool| tool == TOOL_FILL_CREDENTIALS));
        assert!(tools.iter().any(|tool| tool == TOOL_CDP_RAW));
    }

    #[tokio::test]
    async fn audit_records_ok_consent_required_and_error_outcomes() {
        let endpoint = MockEndpoint::new().script(
            METHOD_GET_TABS,
            vec![
                ok(tabs_with(7, "https://foo.test")),
                Err(CoreError::Tool("bridge offline".to_string())),
            ],
        );
        let fixture = build_fixture(endpoint);
        // ok
        fixture
            .host
            .call("browser_list_tabs", r#"{"backend": "chrome"}"#)
            .await
            .expect("list tabs");
        // consent_required
        let blocked = fixture
            .host
            .call(
                TOOL_NAVIGATE,
                r#"{"tabId": 7, "url": "https://foo.test/landing"}"#,
            )
            .await
            .expect("consent required is a tool result");
        assert!(blocked.contains("origin_consent_required"));
        // error (the origin resolution fails when the bridge errors)
        let failed = fixture
            .host
            .call(TOOL_CLICK, r#"{"tabId": 7, "ref": "e1"}"#)
            .await;
        assert!(failed.is_err());

        let entries = fixture
            .store
            .list_browser_action_audit(500, None)
            .expect("audit entries");
        assert_eq!(entries.len(), 3);
        let by_tool = |tool: &str| {
            entries
                .iter()
                .find(|entry| entry.tool_name == tool)
                .unwrap()
        };
        let list_tabs = by_tool("browser_list_tabs");
        assert_eq!(list_tabs.outcome, "ok");
        assert_eq!(list_tabs.origin, None);
        assert_eq!(list_tabs.run_id.as_deref(), Some("run-1"));
        let navigate = by_tool(TOOL_NAVIGATE);
        assert_eq!(navigate.outcome, "consent_required");
        assert_eq!(navigate.origin.as_deref(), Some("foo.test"));
        assert_eq!(navigate.target_summary, "foo.test");
        let click = by_tool(TOOL_CLICK);
        assert_eq!(click.outcome, "error");
        assert!(entries.iter().all(|entry| entry.latency_ms >= 0));
    }

    #[tokio::test]
    async fn audit_write_failure_never_fails_the_tool_call() {
        let endpoint =
            MockEndpoint::new().script(METHOD_GET_TABS, vec![ok(tabs_with(7, "https://x.test"))]);
        let fixture = build_fixture(endpoint);
        fixture
            .store
            .with_local_mcp_connection(|connection| {
                connection
                    .execute_batch("DROP TABLE desktop_browser_action_audit;")
                    .map_err(|error| error.to_string())
            })
            .expect("drop audit table");
        let output = fixture
            .host
            .call("browser_list_tabs", r#"{"backend": "chrome"}"#)
            .await
            .expect("audit failure must not fail the tool call");
        assert_eq!(
            serde_json::from_str::<Value>(&output).unwrap()["tabs"][0]["tabId"],
            7
        );
    }

    #[test]
    fn audit_target_summaries_never_carry_input_values() {
        let click = json!({"tabId": 7, "ref": "e12", "text": "super-secret-value"});
        assert_eq!(
            audit_target_summary(TOOL_CLICK, Some(&click), Some("foo.test")),
            "e12"
        );
        let cdp = json!({"tabId": 7, "method": "Runtime.evaluate", "params": {"expression": "x"}});
        assert_eq!(
            audit_target_summary(TOOL_CDP_RAW, Some(&cdp), Some("foo.test")),
            "Runtime.evaluate"
        );
        let navigate = json!({"tabId": 7, "url": "https://foo.test/secret-path?token=abc"});
        assert_eq!(
            audit_target_summary(TOOL_NAVIGATE, Some(&navigate), Some("foo.test")),
            "foo.test"
        );
        let fill = json!({"tabId": 7, "origin": "foo.test", "username": "alice"});
        assert_eq!(
            audit_target_summary(TOOL_FILL_CREDENTIALS, Some(&fill), Some("foo.test")),
            "foo.test"
        );
        for summary in [
            audit_target_summary(TOOL_CLICK, Some(&click), Some("foo.test")),
            audit_target_summary(TOOL_CDP_RAW, Some(&cdp), Some("foo.test")),
            audit_target_summary(TOOL_NAVIGATE, Some(&navigate), Some("foo.test")),
        ] {
            assert!(!summary.contains("super-secret-value"));
            assert!(!summary.contains("secret-path"));
            assert!(!summary.contains("token=abc"));
            assert!(!summary.contains("1+1"));
        }
    }

    fn screenshot_endpoint(tab_url: &str, data_base64: String) -> MockEndpoint {
        MockEndpoint::new()
            .script(METHOD_ATTACH, vec![ok(json!({}))])
            .script(
                METHOD_EXECUTE_CDP,
                vec![
                    ok(json!({
                        "result": {
                            "cssLayoutViewport": {"clientWidth": 800, "clientHeight": 600},
                        },
                    })),
                    ok(json!({ "result": { "data": data_base64 } })),
                ],
            )
            .script(METHOD_GET_TABS, vec![ok(tabs_with(7, tab_url))])
    }

    #[tokio::test]
    async fn screenshot_result_is_rewritten_to_an_artifact_reference() {
        let directory =
            std::env::temp_dir().join(format!("agistack-screenshots-{}", uuid::Uuid::new_v4()));
        let data = BASE64_STANDARD.encode(b"\xff\xd8jpeg-bytes");
        let endpoint = screenshot_endpoint("https://foo.test", data.clone());
        let fixture = build_fixture_with(endpoint, true, Some(directory.clone()));
        // The artifact machinery needs the run's conversation to exist.
        fixture
            .store
            .insert_conversation(&LocalConversation {
                id: "conversation-1".to_string(),
                project_id: "local-project".to_string(),
                tenant_id: "local".to_string(),
                title: "Screenshots".to_string(),
                workspace_id: Some("local-workspace".to_string()),
                capability_mode: ConversationCapabilityMode::Code,
                current_mode: ConversationRunMode::Build,
                created_at: now_iso(),
                updated_at: now_iso(),
            })
            .expect("insert conversation");
        let output = fixture
            .host
            .call(TOOL_SCREENSHOT, r#"{"tabId": 7}"#)
            .await
            .expect("screenshot result");
        assert!(
            !output.contains(&data),
            "base64 payload must not survive in the result: {output}"
        );
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["artifact_id"], "conversation-1:browser-screenshot-7");
        assert!(output["artifact_version_id"].is_string());
        assert_eq!(output["width"], 800);
        assert_eq!(output["height"], 600);
        assert!(
            output.as_object().map_or(0, serde_json::Map::len) <= 4,
            "compact result: {output}"
        );

        let version = fixture
            .store
            .artifact_version(output["artifact_version_id"].as_str().unwrap())
            .expect("artifact version lookup")
            .expect("artifact version recorded");
        assert_eq!(version.mime_type, "image/jpeg");
        assert_eq!(version.run_id.as_deref(), Some("run-1"));
        let written = std::fs::read(&version.path).expect("screenshot file");
        assert_eq!(written, b"\xff\xd8jpeg-bytes");
        assert!(version.filename.starts_with("browser-screenshot-7-"));
        let _ = std::fs::remove_dir_all(directory);
    }

    #[tokio::test]
    async fn screenshot_falls_back_to_a_path_result_without_a_run_binding() {
        let directory =
            std::env::temp_dir().join(format!("agistack-screenshots-{}", uuid::Uuid::new_v4()));
        let data = BASE64_STANDARD.encode(b"\xff\xd8jpeg-bytes");
        let endpoint = screenshot_endpoint("https://foo.test", data.clone());
        // test_run's conversation is not in the store, so artifact recording
        // fails and the result degrades to the file path.
        let fixture = build_fixture_with(endpoint, true, Some(directory.clone()));
        let output = fixture
            .host
            .call(TOOL_SCREENSHOT, r#"{"tabId": 7}"#)
            .await
            .expect("screenshot result");
        assert!(!output.contains(&data));
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["width"], 800);
        assert_eq!(output["height"], 600);
        let path = output["path"].as_str().expect("path fallback");
        assert!(
            path.contains("browser-screenshots")
                || path.starts_with(directory.to_string_lossy().as_ref())
        );
        assert_eq!(
            std::fs::read(path).expect("screenshot file"),
            b"\xff\xd8jpeg-bytes"
        );
        let _ = std::fs::remove_dir_all(directory);
    }

    include!("browser_run_audit_tests.rs");
    include!("browser_permission_provenance_tests.rs");
}
