//! Native MCP credential and transport types shared by the local execution host.
#[path = "parity_routes/mcp_apps.rs"]
mod mcp_apps;
pub(super) use mcp_apps::native as device_mcp_contract;
