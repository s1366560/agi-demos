//! Desktop computer-use adapter: JSON-RPC client for the `cua-helper` process
//! plus the agent-facing [`ToolHost`]. Contract documented in
//! `docs/cua/memstack-computer-use-replication-plan.md`.

mod ax_tree;
mod catalog;
pub mod client;
mod connector_contract;
mod coordinates;
mod dispatch;
pub mod error;
mod extra_tools;
pub mod framing;
pub mod host;
mod input;
mod status;
pub use input::{CuaInputMode, CuaInputTelemetry, CuaVirtualCursor};
pub use status::{CuaNativeStatus, CuaNativeTarget};

pub use ax_tree::{CuaAxBounds, CuaAxCoordinateSpace, CuaAxNode, CuaAxSource, CuaAxTree};
pub use catalog::*;
pub use client::{CuaCallContext, CuaClient, CuaClientBuilder};
pub use connector_contract::*;
pub use dispatch::{scope_dispatch_signal, CuaDispatchSignal};
pub use error::CuaError;
pub use host::{validate_tool_input, CuaToolEffect, CuaToolHost};

/// Wire protocol version negotiated during the `ping` handshake. Must match the
/// helper's `ipcProtocolVersion`; bump both on any contract change.
pub const IPC_PROTOCOL_VERSION: &str = "MemstackComputerUseIPC-3";
