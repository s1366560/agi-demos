//! Bridge: expose the hot-pluggable [`HotPlugRegistry`] as the core's
//! [`agistack_core::ToolHost`] port.
//!
//! This is the seam where the **extensibility axis** (this crate's registry) and
//! the **agent core** (the ReAct loop in `agistack-core`) meet. The engine only
//! depends on the `ToolHost` trait; wiring a `HotPlugRegistry` behind it means
//! every tool the agent calls is resolved against the *current* atomic snapshot —
//! so a hot-swap / CP→DP reconcile that lands between rounds is picked up at the
//! next round boundary without the engine knowing anything changed (ADR-0005/6).
//!
//! Orphan rule: `HotPlugRegistry` is local to this crate and `ToolHost` comes
//! from a dependency, so this impl is allowed here (not in `agistack-core`).

use async_trait::async_trait;
use agistack_core::ports::{CoreResult, ToolHost};

use crate::registry::HotPlugRegistry;

#[async_trait]
impl ToolHost for HotPlugRegistry {
    fn list_tools(&self) -> Vec<String> {
        self.names()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        self.invoke(tool, input_json).await
    }
}
