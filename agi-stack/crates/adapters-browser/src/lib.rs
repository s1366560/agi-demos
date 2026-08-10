//! Browser-extension bridge client for the MemStack desktop sidecar.
//!
//! The sidecar talks to a Chrome extension through a native-messaging broker
//! process: the broker owns the extension's stdio pipe and re-publishes it as
//! a JSON-RPC 2.0 WebSocket endpoint (`/api/v1/browser-bridge/ws`). This crate
//! is the Rust client for that endpoint and exposes the browser as a set of
//! **read-only** tools behind the existing [`ToolHost`] port, so the agent
//! engine sees the browser exactly like any other tool provider.
//!
//! ## Layout
//! - [`protocol`] — serde types for the fixed bridge contract (methods,
//!   params, results, notifications, error codes).
//! - [`jsonrpc`] — standalone JSON-RPC 2.0 codec (encode / validate /
//!   correlate), mirroring the sidecar's established validation semantics.
//! - [`framing`] — length-prefixed frame codec for the broker's stdio side.
//! - [`ws_client`] — [`BridgeWsClient`]: reconnecting WebSocket client with
//!   request/response correlation and a notification broadcast.
//! - [`cdp_policy`] — CDP method allow-policy (Conservative default; M3 added
//!   the FullAccess mode used by `browser_cdp_raw`).
//! - [`snapshot`] — the accessibility-snapshot CDP call sequence (the JS
//!   asset itself is embedded but opaque to this crate).
//! - [`host`] — [`BrowserToolHost`]: the [`ToolHost`] implementation exposing
//!   `browser_list_tabs` / `browser_snapshot` / `browser_screenshot` /
//!   `browser_console_logs` plus the M2 mutation tools.
//! - [`actions`] — M2 mutation tools: `browser_navigate` / `browser_click` /
//!   `browser_type` / `browser_scroll` / `browser_new_tab` /
//!   `browser_claim_tab` / `browser_mark_tab`, built on the cached isolated
//!   world, the virtual cursor, and per-run tab leases.

pub mod actions;
pub mod cdp_policy;
pub mod framing;
pub mod host;
pub mod jsonrpc;
pub mod protocol;
pub mod snapshot;
pub mod ws_client;

pub use host::{list_tool_metadata, BridgeEndpoint, BrowserToolHost};
pub use ws_client::{bridge_ws_url, BridgeWsClient};
