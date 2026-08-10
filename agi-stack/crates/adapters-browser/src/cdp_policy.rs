//! CDP method allow-policy (M1-conservative; M2 loosened navigation).
//!
//! The bridge's `executeCdp` is raw Chrome DevTools Protocol access; this
//! pure-function filter is the single choke point deciding which CDP methods
//! the agent may invoke. M1 is deliberately conservative: anything that can
//! exfiltrate credentials, weaken page/browser security, persist across
//! sessions, or mutate browser-global state is denied, even where a careful
//! caller could use it safely. The list is expected to loosen deliberately,
//! case by case, in later milestones — M2 removed `Page.navigate` /
//! `Page.reload`, which are now gated by origin consent above the CDP layer.

use serde_json::Value;
use thiserror::Error;

/// Appended to every denial so the agent does not route around the policy.
pub const ANTI_BYPASS_GUIDANCE: &str = "do not attempt to achieve the same outcome via \
     workaround, indirect execution, or alternate CDP methods";

/// A CDP call rejected by policy.
#[derive(Debug, Error, PartialEq, Eq)]
#[error("CDP method '{method}' is blocked by policy: {reason}; {ANTI_BYPASS_GUIDANCE}")]
pub struct CdpPolicyError {
    /// The CDP method that was rejected.
    pub method: String,
    /// Why it was rejected (without the anti-bypass suffix).
    pub reason: String,
}

impl CdpPolicyError {
    fn new(method: &str, reason: impl Into<String>) -> Self {
        Self {
            method: method.to_string(),
            reason: reason.into(),
        }
    }
}

/// Whole CDP domains that are always denied. `Browser.*` is included: every
/// method there acts on the browser process, not a tab.
const DENIED_DOMAINS: &[&str] = &[
    "Storage",
    "CacheStorage",
    "Database",
    "Target",
    "WebAuthn",
    "Browser",
];

/// Individual high-risk methods denied on top of the domain rules.
/// M1-conservative: entries here are expected to be revisited, not extended
/// ad hoc.
const DENIED_METHODS: &[&str] = &[
    // Contract-specified.
    "Page.crash",
    "Page.setBypassCSP",
    "Page.addScriptToEvaluateOnNewDocument",
    "Page.removeScriptToEvaluateOnNewDocument",
    "Network.clearBrowserCookies",
    "Network.clearBrowserCache",
    "Emulation.setScriptExecutionDisabled",
    "Security.setIgnoreCertificateErrors",
    "Fetch.enable", // reserved: request interception is host-only
    // M1-conservative additions.
    "Page.setDocumentContent", // arbitrary DOM overwrite
    // NOTE: `Page.navigate` / `Page.reload` were removed in M2 — navigation is
    // gated by origin consent above the CDP layer (see host `browser_navigate`
    // and the authority store), not by this list.
    "Page.setDownloadBehavior",
    "Page.setInterceptFileChooserDialog",
    "DOM.setFileInputFiles", // pushes local files into the page (exfiltration)
    "Debugger.enable",       // debugger domain reserved
    "Debugger.setScriptSource", // rewrites running page scripts
    "HeapProfiler.takeHeapSnapshot", // raw page memory may hold secrets
    "HeapProfiler.startTrackingHeapObjects",
    "Network.loadNetworkResource", // credentialed arbitrary fetch
    "Emulation.setGeolocationOverride",
];

/// Cookie methods allowed only when explicitly scoped to a URL (or URLs), so
/// the agent cannot sweep the whole cookie jar.
const URL_SCOPED_COOKIE_METHODS: &[&str] = &[
    "Network.getCookies",
    "Network.setCookie",
    "Network.deleteCookies",
];

/// Check whether a CDP call is permitted. `params` is the (optional) CDP
/// params object; pass `Value::Null` when absent.
pub fn check_cdp_allowed(method: &str, params: &Value) -> Result<(), CdpPolicyError> {
    let (domain, _) = method
        .split_once('.')
        .filter(|(d, m)| !d.is_empty() && !m.is_empty())
        .ok_or_else(|| CdpPolicyError::new(method, "not a valid '<Domain>.<method>' CDP name"))?;

    if DENIED_DOMAINS.contains(&domain) {
        return Err(CdpPolicyError::new(
            method,
            format!("the entire '{domain}' domain is denied"),
        ));
    }
    if DENIED_METHODS.contains(&method) {
        return Err(CdpPolicyError::new(method, "method is on the M1 deny-list"));
    }
    if URL_SCOPED_COOKIE_METHODS.contains(&method) && !has_url_scope(params) {
        return Err(CdpPolicyError::new(
            method,
            "cookie access requires an explicit 'url' or 'urls' param",
        ));
    }
    Ok(())
}

fn has_url_scope(params: &Value) -> bool {
    let has_url = params
        .get("url")
        .and_then(Value::as_str)
        .is_some_and(|u| !u.is_empty());
    let has_urls = params
        .get("urls")
        .and_then(Value::as_array)
        .is_some_and(|us| !us.is_empty());
    has_url || has_urls
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn assert_denied(method: &str, params: Value) {
        let err = check_cdp_allowed(method, &params).expect_err(method);
        assert!(
            err.to_string().contains(ANTI_BYPASS_GUIDANCE),
            "denial for {method} must carry anti-bypass guidance"
        );
    }

    #[test]
    fn denied_domains_are_blocked_wholesale() {
        for method in [
            "Storage.getCookies",
            "CacheStorage.requestCacheNames",
            "Database.executeSql",
            "Target.createTarget",
            "WebAuthn.enable",
            "Browser.getVersion",
            "Browser.grantPermissions",
            "Browser.close",
        ] {
            assert_denied(method, json!({}));
        }
    }

    #[test]
    fn contract_denied_methods_are_blocked() {
        for method in [
            "Page.crash",
            "Page.setBypassCSP",
            "Page.addScriptToEvaluateOnNewDocument",
            "Page.removeScriptToEvaluateOnNewDocument",
            "Network.clearBrowserCookies",
            "Network.clearBrowserCache",
            "Emulation.setScriptExecutionDisabled",
            "Security.setIgnoreCertificateErrors",
            "Fetch.enable",
        ] {
            assert_denied(method, json!({}));
        }
    }

    #[test]
    fn m1_conservative_denied_methods_are_blocked() {
        for method in [
            "Page.setDocumentContent",
            "Page.setDownloadBehavior",
            "Page.setInterceptFileChooserDialog",
            "DOM.setFileInputFiles",
            "Debugger.enable",
            "Debugger.setScriptSource",
            "HeapProfiler.takeHeapSnapshot",
            "HeapProfiler.startTrackingHeapObjects",
            "Network.loadNetworkResource",
            "Emulation.setGeolocationOverride",
        ] {
            assert_denied(method, json!({}));
        }
    }

    #[test]
    fn navigation_methods_are_allowed_since_m2() {
        // Navigation is gated by origin consent above the CDP layer.
        assert!(check_cdp_allowed("Page.navigate", &json!({"url": "https://example.com"})).is_ok());
        assert!(check_cdp_allowed("Page.reload", &json!({})).is_ok());
    }

    #[test]
    fn cookie_methods_require_url_scope() {
        for method in [
            "Network.getCookies",
            "Network.setCookie",
            "Network.deleteCookies",
        ] {
            assert_denied(method, json!({}));
            assert_denied(method, json!({"name": "sid"}));
            assert_denied(method, json!({"url": ""}));
            assert_denied(method, json!({"urls": []}));
            assert!(check_cdp_allowed(method, &json!({"url": "https://example.com"})).is_ok());
            assert!(check_cdp_allowed(method, &json!({"urls": ["https://example.com"]})).is_ok());
        }
    }

    #[test]
    fn read_only_happy_paths_are_allowed() {
        for (method, params) in [
            (
                "Runtime.evaluate",
                json!({"expression": "1+1", "returnByValue": true}),
            ),
            ("Runtime.enable", json!({})),
            ("Log.enable", json!({})),
            (
                "Page.captureScreenshot",
                json!({"format": "jpeg", "quality": 80}),
            ),
            ("Page.getLayoutMetrics", json!({})),
            ("Page.getFrameTree", json!({})),
            (
                "Page.createIsolatedWorld",
                json!({"frameId": "F", "worldName": "w"}),
            ),
            (
                "Input.dispatchMouseEvent",
                json!({"type": "mousePressed", "x": 1, "y": 2}),
            ),
            ("Accessibility.getFullAXTree", json!({})),
        ] {
            assert!(check_cdp_allowed(method, &params).is_ok(), "{method}");
        }
    }

    #[test]
    fn malformed_method_names_are_rejected() {
        for bad in ["", "nodot", ".evaluate", "Runtime.", "a.b.c.d"] {
            // "a.b.c.d" still parses as domain "a" — only truly invalid shapes fail.
            let result = check_cdp_allowed(bad, &json!({}));
            if bad == "a.b.c.d" {
                assert!(result.is_ok());
            } else {
                assert!(result.is_err(), "{bad}");
            }
        }
    }
}
