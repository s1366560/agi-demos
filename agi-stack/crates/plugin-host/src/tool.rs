//! The atomic capability abstraction and its classification metadata.

use agistack_core::ports::CoreResult;
use async_trait::async_trait;

/// Trust tier of a capability provider — the **trust axis** (ADR-0002).
///
/// This is a *structural* fact declared by the loader, not a semantic judgment:
/// trusted built-ins are compiled in and run at native speed; untrusted
/// third-party / MCP tools MUST be sandboxed (WASM-only, never in-process).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Trust {
    /// Trusted built-in: native `dyn Trait`, in-process, full speed.
    Builtin,
    /// Untrusted third-party / MCP: only ever runs behind a WASM sandbox.
    SandboxedWasm,
}

/// OpenClaw-style classification of a plugin by its **actual** registration
/// behaviour (not static metadata). Mirrors `docs/plugins/architecture.md`
/// "Plugin shapes": `plain-capability` / `hybrid-capability` / `hook-only` /
/// `non-capability`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PluginShape {
    /// Registers exactly one capability kind (e.g. a tool-only plugin).
    PlainCapability,
    /// Registers multiple capability kinds (e.g. tool + provider).
    HybridCapability,
    /// Registers only hooks, no capabilities/tools (legacy-compatible path).
    HookOnly,
    /// Registers non-capability contributions only (skills/commands/services).
    NonCapability,
}

/// A single **atomic capability** — the L1 Tool layer.
///
/// Both trusted native built-ins and sandboxed WASM tools implement this trait,
/// so the registry can store them uniformly as `Arc<dyn Tool>` and hot-swap one
/// by atomically replacing its `Arc` (see [`crate::registry`]).
#[async_trait]
pub trait Tool: Send + Sync {
    /// Stable identity used for registry lookup and replacement.
    fn name(&self) -> &str;

    /// Semantic version; lets the registry/log distinguish hot-swapped builds.
    fn version(&self) -> &str;

    /// Trust tier (structural, declared at load time).
    fn trust(&self) -> Trust;

    /// Extensibility short-circuit — mirrors the gateway `skip()` predicate and
    /// OpenClaw capability applicability. Returns `false` to skip this tool for
    /// the given (opaque) context. Default: always applicable.
    ///
    /// Note (Agent First): a *structural* "is this tool wired for this surface"
    /// check is fine here; the *semantic* "is this the right tool for the user's
    /// intent" judgment belongs to an agent tool-call, not to this predicate.
    fn should_run(&self, _ctx: &str) -> bool {
        true
    }

    /// Invoke the capability with a JSON input, returning a JSON output.
    async fn invoke(&self, input_json: &str) -> CoreResult<String>;
}
