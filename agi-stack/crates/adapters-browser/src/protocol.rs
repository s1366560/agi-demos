//! Wire types for the browser-extension bridge contract.
//!
//! All messages are JSON-RPC 2.0. Requests flow sidecar → extension
//! (`hello` / `ping` / `attach` / `detach` / `executeCdp` / `getTabs` /
//! `createTab` / `ensureTabGroup` / `assignTab` / `ungroupTab` / `closeTab` /
//! `focusTab` / `moveMouse` / `turnEnded`); notifications flow extension →
//! sidecar (`onCDPEvent` / `onCDPDetach`). Field names on the wire are
//! camelCase and fixed by the contract — the serde renames here are
//! load-bearing.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// The bridge protocol revision this client implements.
pub const PROTOCOL_VERSION: u32 = 1;

/// Request method names (sidecar → extension).
pub const METHOD_HELLO: &str = "hello";
pub const METHOD_PING: &str = "ping";
pub const METHOD_ATTACH: &str = "attach";
pub const METHOD_DETACH: &str = "detach";
pub const METHOD_EXECUTE_CDP: &str = "executeCdp";
pub const METHOD_GET_TABS: &str = "getTabs";
pub const METHOD_CREATE_TAB: &str = "createTab";
// M2 tab-group / cursor / turn-lifecycle methods (implemented by the
// extension workstream against this same contract).
pub const METHOD_ENSURE_TAB_GROUP: &str = "ensureTabGroup";
pub const METHOD_ASSIGN_TAB: &str = "assignTab";
pub const METHOD_UNGROUP_TAB: &str = "ungroupTab";
pub const METHOD_CLOSE_TAB: &str = "closeTab";
pub const METHOD_FOCUS_TAB: &str = "focusTab";
pub const METHOD_MOVE_MOUSE: &str = "moveMouse";
pub const METHOD_TURN_ENDED: &str = "turnEnded";

/// Notification method names (extension → sidecar).
pub const NOTIFY_ON_CDP_EVENT: &str = "onCDPEvent";
pub const NOTIFY_ON_CDP_DETACH: &str = "onCDPDetach";

/// Bridge-level error: the handler ran but failed (e.g. tab gone).
pub const ERR_HANDLER: i64 = 1;
/// JSON-RPC standard: method not found.
pub const ERR_METHOD_NOT_FOUND: i64 = -32601;
/// JSON-RPC standard: invalid params.
pub const ERR_INVALID_PARAMS: i64 = -32602;

/// Optional trace fields carried on every envelope. Unused in M1 but part of
/// the wire shape, so they serialize only when present.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TraceContext {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub turn_id: Option<String>,
}

/// JSON-RPC 2.0 request envelope (sidecar → extension).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RequestEnvelope {
    pub jsonrpc: String,
    pub id: u64,
    pub method: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub params: Option<Value>,
    #[serde(flatten)]
    pub trace: TraceContext,
}

/// JSON-RPC 2.0 notification envelope (either direction).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NotificationEnvelope {
    pub jsonrpc: String,
    pub method: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub params: Option<Value>,
    #[serde(flatten)]
    pub trace: TraceContext,
}

/// The JSON-RPC `error` object.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RpcErrorObject {
    pub code: i64,
    pub message: String,
}

/// JSON-RPC 2.0 response envelope (extension → sidecar). Exactly one of
/// `result` / `error` is present; this is validated by the codec, not serde.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResponseEnvelope {
    pub jsonrpc: String,
    pub id: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<RpcErrorObject>,
    #[serde(flatten)]
    pub trace: TraceContext,
}

/// A notification delivered to consumers of the bridge (CDP events, detach).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BridgeNotification {
    pub method: String,
    pub params: Value,
}

/// `hello` result: protocol handshake payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HelloResult {
    pub protocol_version: u32,
    pub extension_id: String,
    pub capabilities: Vec<String>,
}

/// `attach` / `detach` params.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TabParams {
    pub tab_id: u64,
}

/// `executeCdp` params: run one Chrome DevTools Protocol command on a tab.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExecuteCdpParams {
    pub tab_id: u64,
    pub method: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub params: Option<Value>,
}

/// `executeCdp` result: the raw CDP response body.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExecuteCdpResult {
    pub result: Value,
}

/// One tab as reported by `getTabs`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TabInfo {
    pub tab_id: u64,
    pub window_id: u64,
    pub title: String,
    pub url: String,
    pub active: bool,
}

/// `getTabs` result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GetTabsResult {
    pub tabs: Vec<TabInfo>,
}

/// `createTab` params.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CreateTabParams {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
}

/// `createTab` result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateTabResult {
    pub tab_id: u64,
}

/// Who created a tab lease: the agent (`createTab`/`browser_new_tab`) or the
/// user (`browser_claim_tab`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LeaseOrigin {
    Agent,
    User,
}

/// End-of-turn disposition marker on a lease.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TabMark {
    Handoff,
    Deliverable,
}

/// `ensureTabGroup` params: idempotent per `key` (one tab group per run).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EnsureTabGroupParams {
    pub key: String,
    pub title: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub color: Option<String>,
}

/// `ensureTabGroup` result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EnsureTabGroupResult {
    pub group_id: u64,
}

/// `assignTab` params: move a tab into a group.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AssignTabParams {
    pub tab_id: u64,
    pub group_id: u64,
}

// `ungroupTab` / `closeTab` / `focusTab` all take `{tabId}` — reuse
// [`TabParams`].

/// `moveMouse` params (virtual cursor). The bridge handler always succeeds;
/// errors are swallowed client-side so the cursor can never block actions.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MoveMouseParams {
    pub tab_id: u64,
    pub x: f64,
    pub y: f64,
    pub wait_for_arrival: bool,
}

/// One lease in a `turnEnded` payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TurnEndedLease {
    pub tab_id: u64,
    pub origin: LeaseOrigin,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mark: Option<TabMark>,
}

/// `turnEnded` params: the leases of the run whose turn just ended.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TurnEndedParams {
    pub leases: Vec<TurnEndedLease>,
}

/// `turnEnded` result: cleanup counts reported by the extension.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TurnEndedResult {
    pub closed: u64,
    pub ungrouped: u64,
}

/// `onCDPEvent` params: a CDP event from an attached tab.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OnCdpEventParams {
    pub tab_id: u64,
    pub method: String,
    #[serde(default)]
    pub params: Value,
    /// Backend that emitted the event (`"iab"`); absent means the default
    /// chrome-extension backend.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub backend: Option<String>,
}

/// `onCDPDetach` params: the debugger detached from a tab.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OnCdpDetachParams {
    pub tab_id: u64,
    pub reason: String,
    /// Backend that emitted the notification (`"iab"`); absent means chrome.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub backend: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn hello_result_uses_camel_case_wire_names() {
        let hello: HelloResult = serde_json::from_value(json!({
            "protocolVersion": 1,
            "extensionId": "ext-abc",
            "capabilities": ["cdp"]
        }))
        .unwrap();
        assert_eq!(hello.protocol_version, PROTOCOL_VERSION);
        assert_eq!(hello.extension_id, "ext-abc");
    }

    #[test]
    fn trace_fields_are_omitted_when_absent() {
        let env = RequestEnvelope {
            jsonrpc: "2.0".into(),
            id: 1,
            method: METHOD_PING.into(),
            params: None,
            trace: TraceContext::default(),
        };
        let wire = serde_json::to_value(&env).unwrap();
        assert_eq!(wire, json!({"jsonrpc": "2.0", "id": 1, "method": "ping"}));
    }

    #[test]
    fn trace_fields_serialize_when_present() {
        let env = NotificationEnvelope {
            jsonrpc: "2.0".into(),
            method: NOTIFY_ON_CDP_DETACH.into(),
            params: Some(json!({"tabId": 7, "reason": "target_closed"})),
            trace: TraceContext {
                session_id: Some("s-1".into()),
                turn_id: Some("t-9".into()),
            },
        };
        let wire = serde_json::to_value(&env).unwrap();
        assert_eq!(wire["session_id"], "s-1");
        assert_eq!(wire["turn_id"], "t-9");
    }

    #[test]
    fn cdp_event_params_round_trip() {
        let params: OnCdpEventParams = serde_json::from_value(json!({
            "tabId": 42,
            "method": "Log.entryAdded",
            "params": {"entry": {"level": "info", "text": "hi", "timestamp": 1.5}}
        }))
        .unwrap();
        assert_eq!(params.tab_id, 42);
        assert_eq!(params.method, "Log.entryAdded");
    }

    #[test]
    fn m2_method_constants_match_the_contract() {
        assert_eq!(METHOD_ENSURE_TAB_GROUP, "ensureTabGroup");
        assert_eq!(METHOD_ASSIGN_TAB, "assignTab");
        assert_eq!(METHOD_UNGROUP_TAB, "ungroupTab");
        assert_eq!(METHOD_CLOSE_TAB, "closeTab");
        assert_eq!(METHOD_FOCUS_TAB, "focusTab");
        assert_eq!(METHOD_MOVE_MOUSE, "moveMouse");
        assert_eq!(METHOD_TURN_ENDED, "turnEnded");
    }

    #[test]
    fn ensure_tab_group_wire_names_are_camel_case() {
        let params = EnsureTabGroupParams {
            key: "run-1".into(),
            title: "MemStack Agent".into(),
            color: None,
        };
        let wire = serde_json::to_value(&params).unwrap();
        assert_eq!(wire, json!({"key": "run-1", "title": "MemStack Agent"}));
        let result: EnsureTabGroupResult = serde_json::from_value(json!({"groupId": 9})).unwrap();
        assert_eq!(result.group_id, 9);
    }

    #[test]
    fn move_mouse_serializes_wait_for_arrival_camel_case() {
        let params = MoveMouseParams {
            tab_id: 7,
            x: 10.5,
            y: 20.0,
            wait_for_arrival: true,
        };
        let wire = serde_json::to_value(&params).unwrap();
        assert_eq!(
            wire,
            json!({"tabId": 7, "x": 10.5, "y": 20.0, "waitForArrival": true})
        );
    }

    #[test]
    fn turn_ended_lease_omits_mark_when_absent() {
        let params = TurnEndedParams {
            leases: vec![
                TurnEndedLease {
                    tab_id: 7,
                    origin: LeaseOrigin::Agent,
                    mark: Some(TabMark::Deliverable),
                },
                TurnEndedLease {
                    tab_id: 8,
                    origin: LeaseOrigin::User,
                    mark: None,
                },
            ],
        };
        let wire = serde_json::to_value(&params).unwrap();
        assert_eq!(
            wire,
            json!({"leases": [
                {"tabId": 7, "origin": "agent", "mark": "deliverable"},
                {"tabId": 8, "origin": "user"},
            ]})
        );
        let result: TurnEndedResult =
            serde_json::from_value(json!({"closed": 1, "ungrouped": 1})).unwrap();
        assert_eq!((result.closed, result.ungrouped), (1, 1));
    }
}
