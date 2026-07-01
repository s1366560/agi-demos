//! The lock-free, hot-pluggable registry — the heart of ADR-0006.

use std::sync::Arc;

use arc_swap::ArcSwap;
use memstack_core::ports::{CoreError, CoreResult};

use crate::tool::Tool;

/// An **immutable snapshot** of the registered tools.
///
/// Every mutation produces a fresh `ToolRegistry` (clone the `Arc` vec, apply
/// the change, sort by name for deterministic priority — mirroring ShenYu's
/// `sortPlugins`). Readers hold an `Arc<ToolRegistry>` and are never mutated
/// underneath them, which is exactly the in-flight isolation property we want.
#[derive(Default, Clone)]
pub struct ToolRegistry {
    tools: Vec<Arc<dyn Tool>>,
}

impl ToolRegistry {
    /// Look up a tool by name (the lock-free read path).
    pub fn get(&self, name: &str) -> Option<Arc<dyn Tool>> {
        self.tools.iter().find(|t| t.name() == name).cloned()
    }

    /// Sorted tool names — deterministic, for inspection/logging.
    pub fn names(&self) -> Vec<String> {
        let mut n: Vec<String> = self.tools.iter().map(|t| t.name().to_string()).collect();
        n.sort();
        n
    }

    pub fn len(&self) -> usize {
        self.tools.len()
    }

    pub fn is_empty(&self) -> bool {
        self.tools.is_empty()
    }

    /// Return a new registry with `tool` inserted, **replacing** any existing
    /// tool of the same name (this is also how hot-swap works). Result is sorted
    /// by name so ordering is stable across swaps.
    fn with_inserted(&self, tool: Arc<dyn Tool>) -> ToolRegistry {
        let mut tools: Vec<Arc<dyn Tool>> = self
            .tools
            .iter()
            .filter(|t| t.name() != tool.name())
            .cloned()
            .collect();
        tools.push(tool);
        tools.sort_by(|a, b| a.name().cmp(b.name()));
        ToolRegistry { tools }
    }

    /// Return a new registry with the named tool removed (no-op if absent).
    fn with_removed(&self, name: &str) -> ToolRegistry {
        ToolRegistry {
            tools: self
                .tools
                .iter()
                .filter(|t| t.name() != name)
                .cloned()
                .collect(),
        }
    }
}

/// The **hot-pluggable registry**: an `Arc<ArcSwap<ToolRegistry>>`.
///
/// - Mutations ([`register_tool`](Self::register_tool),
///   [`replace_tool`](Self::replace_tool), [`unregister`](Self::unregister))
///   are *clone -> modify -> atomic swap* via `rcu`, so concurrent registrations
///   are linearizable without a lock.
/// - Reads ([`snapshot`](Self::snapshot), [`get`](Self::get)) are lock-free.
/// - A caller that took a [`snapshot`](Self::snapshot) *before* a swap keeps
///   seeing the old tool set — changes apply only to calls started afterwards
///   (round-boundary apply, ADR-0005). That is what makes hot-swap safe.
///
/// `Clone` is cheap (shared `Arc`), so the same registry can be handed to every
/// runner/worker.
#[derive(Clone)]
pub struct HotPlugRegistry {
    inner: Arc<ArcSwap<ToolRegistry>>,
}

impl Default for HotPlugRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl HotPlugRegistry {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(ArcSwap::from_pointee(ToolRegistry::default())),
        }
    }

    /// Lock-free read of the current immutable snapshot. Hold this across a tool
    /// call to pin the version for the whole round (in-flight isolation).
    pub fn snapshot(&self) -> Arc<ToolRegistry> {
        self.inner.load_full()
    }

    /// Register (or hot-swap) a tool capability. Mirrors OpenClaw
    /// `api.registerTool(...)`. If a tool with the same name exists it is
    /// atomically replaced — this is the hot-swap primitive.
    pub fn register_tool(&self, tool: Arc<dyn Tool>) {
        self.inner
            .rcu(|cur| Arc::new(cur.with_inserted(Arc::clone(&tool))));
    }

    /// Alias for [`register_tool`](Self::register_tool) that documents intent at
    /// the call site when the tool is known to already exist.
    pub fn replace_tool(&self, tool: Arc<dyn Tool>) {
        self.register_tool(tool);
    }

    /// Remove a capability by name (no-op if absent). Mirrors disabling a
    /// plugin's contribution.
    pub fn unregister(&self, name: &str) {
        self.inner.rcu(|cur| Arc::new(cur.with_removed(name)));
    }

    /// Convenience lookup against the current snapshot.
    pub fn get(&self, name: &str) -> Option<Arc<dyn Tool>> {
        self.snapshot().get(name)
    }

    /// Sorted names in the current snapshot.
    pub fn names(&self) -> Vec<String> {
        self.snapshot().names()
    }

    /// Resolve and invoke a tool against the current snapshot. Equivalent to
    /// `snapshot().get(name)?.invoke(input)` — the snapshot pins the version for
    /// the duration of this single call.
    pub async fn invoke(&self, name: &str, input_json: &str) -> CoreResult<String> {
        let snapshot = self.snapshot();
        let tool = snapshot
            .get(name)
            .ok_or_else(|| CoreError::Tool(format!("unknown tool: {name}")))?;
        tool.invoke(input_json).await
    }
}
