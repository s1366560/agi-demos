//! `agistack-adapters-wasmtime`: the **native** sandboxed-tool host.
//!
//! This is the production realization of the *trust axis* (ADR-0002) on the
//! server/desktop: untrusted third-party / MCP tools never run in-process as
//! `dyn Trait`; they run as WASM guests behind [Wasmtime](https://wasmtime.dev),
//! which gives us Cranelift-compiled speed **and**, crucially, hard **resource
//! quotas** — *fuel* (deterministic per-instruction budget) and *epoch*
//! (wall-clock interruption). Quotas are the property that actually makes
//! untrusted code safe, and they are proven by the tests below.
//!
//! Relationship to the rest of the stack:
//! - It produces [`plugin_host::Tool`] instances, so a [`WasmtimeTool`] drops
//!   straight into the hot-pluggable [`plugin_host::HotPlugRegistry`] next to
//!   native built-ins and is dispatched through the core's
//!   [`agistack_core::ToolHost`] port like any other tool.
//! - [`WasmtimeToolFactory`] builds tools from a manifest [`ToolDecl`], so the
//!   enable/disable + CP/DP reconcile lifecycles drive **real** sandboxed wasm
//!   tools, not just the native `EchoTool` placeholder.
//! - The typed contract lives in [`wit/tool.wit`](../wit/tool.wit). The runnable
//!   sample realizes that `tool` world through the equivalent **core-module
//!   ABI** `score: func(param i32) -> i32` (a full Component Model guest needs
//!   `cargo-component`, deferred by the scorecard's Option A); the host enforces
//!   the same quotas either way.
//!
//! Portability: Wasmtime is JIT and **native-only**. iOS (no JIT) and the
//! browser keep the Wasmi interpreter fallback (03-platform-adapters §3). This
//! crate is therefore never part of the core's `wasm32` build — it is a
//! server/desktop adapter, exactly like `adapters-device`'s SQLite.

use async_trait::async_trait;
use wasmtime::{Config, Engine, Module, Store, Trap};

use agistack_core::ports::{CoreError, CoreResult};
use agistack_plugin_host::manifest::ToolDecl;
use agistack_plugin_host::tool::{Tool, Trust};
use agistack_plugin_host::ToolFactory;

/// Default per-call fuel budget. The sample scorers execute a handful of
/// instructions, so this is effectively unbounded for honest tools while still
/// trapping a runaway (e.g. an infinite loop) in well under a millisecond.
pub const DEFAULT_FUEL: u64 = 1_000_000;

/// A sandboxed tool backed by a Wasmtime-compiled module.
///
/// Holds a Cranelift-compiled [`Module`] and the shared [`Engine`]; each
/// invocation gets a **fresh [`Store`]** with its own fuel + epoch budget, so
/// calls cannot accumulate state or starve each other. Cheap to clone-share via
/// the registry's `Arc`.
pub struct WasmtimeTool {
    name: String,
    version: String,
    engine: Engine,
    module: Module,
    fuel: u64,
}

impl WasmtimeTool {
    /// Build the quota-enforcing engine config: both fuel and epoch
    /// interruption on. Fuel is the deterministic budget; epoch is the
    /// wall-clock budget the server runner drives via [`Engine::increment_epoch`]
    /// on a timer (the test below trips it deterministically without a timer).
    fn quota_config() -> Config {
        let mut config = Config::new();
        config.consume_fuel(true);
        config.epoch_interruption(true);
        config
    }

    /// Compile a tool from raw wasm **bytes loaded at runtime** (the property the
    /// spike's baked-in WAT lacked): in production these bytes come from a plugin
    /// registry / MCP package. The module must export `score(i32) -> i32`.
    pub fn from_bytes(
        name: impl Into<String>,
        version: impl Into<String>,
        wasm: &[u8],
        fuel: u64,
    ) -> CoreResult<Self> {
        let engine = Engine::new(&Self::quota_config())
            .map_err(|e| CoreError::Tool(format!("wasmtime engine: {e:#}")))?;
        let module = Module::new(&engine, wasm)
            .map_err(|e| CoreError::Tool(format!("wasm compile: {e:#}")))?;
        Ok(Self {
            name: name.into(),
            version: version.into(),
            engine,
            module,
            fuel,
        })
    }

    /// Convenience: compile from inline WAT text (Wasmtime's built-in `wat`
    /// support parses it). Real deployments ship `.wasm`; tests use WAT.
    pub fn from_wat(
        name: impl Into<String>,
        version: impl Into<String>,
        wat: &str,
        fuel: u64,
    ) -> CoreResult<Self> {
        // `Module::new` accepts WAT text directly, but going through bytes keeps
        // one code path and mirrors the runtime-bytes production flow.
        Self::from_bytes(name, version, wat.as_bytes(), fuel)
    }

    /// Run the guest `score(len)` inside a fresh, quota-bounded store.
    ///
    /// A new [`Store`] per call means fuel/epoch budgets are per-invocation and
    /// no wasm state leaks between calls. Errors (including quota traps) surface
    /// as [`CoreError::Tool`] — the host stays in control, the guest cannot
    /// escape its budget.
    fn run_score(&self, len: i32) -> CoreResult<i32> {
        let mut store = Store::new(&self.engine, ());
        // Deterministic per-instruction budget.
        store
            .set_fuel(self.fuel)
            .map_err(|e| CoreError::Tool(format!("set_fuel: {e:#}")))?;
        // Epoch is enabled in the config, so a deadline MUST be set or the store
        // traps immediately (wasmtime default deadline is 0). Push it far out:
        // the honest path never trips epoch; the server runner lowers/drives it
        // for a real wall-clock budget.
        store.set_epoch_deadline(u64::MAX);

        let instance = instantiate_module(&self.module, &mut store)?;
        let score = instance
            .get_typed_func::<i32, i32>(&mut store, "score")
            .map_err(|e| CoreError::Tool(format!("missing export score: {e:#}")))?;
        score.call(&mut store, len).map_err(map_trap)
    }
}

/// Instantiate a no-import module, mapping failures to [`CoreError`].
fn instantiate_module(module: &Module, store: &mut Store<()>) -> CoreResult<wasmtime::Instance> {
    wasmtime::Instance::new(store, module, &[])
        .map_err(|e| CoreError::Tool(format!("instantiate: {e:#}")))
}

/// Map a Wasmtime call error to [`CoreError::Tool`], surfacing quota traps with
/// a stable, greppable message. Fuel exhaustion Displays as "all fuel consumed
/// by WebAssembly"; an epoch deadline surfaces as `Trap::Interrupt` ("interrupt").
fn map_trap(e: wasmtime::Error) -> CoreError {
    if let Some(trap) = e.downcast_ref::<Trap>() {
        CoreError::Tool(format!("wasm trap: {trap}"))
    } else {
        CoreError::Tool(format!("wasm error: {e:#}"))
    }
}

#[async_trait]
impl Tool for WasmtimeTool {
    fn name(&self) -> &str {
        &self.name
    }
    fn version(&self) -> &str {
        &self.version
    }
    fn trust(&self) -> Trust {
        // Structural fact: wasm-hosted tools are the untrusted tier (ADR-0002).
        Trust::SandboxedWasm
    }
    async fn invoke(&self, input_json: &str) -> CoreResult<String> {
        let v: serde_json::Value =
            serde_json::from_str(input_json).map_err(|e| CoreError::Tool(e.to_string()))?;
        // Host lowers the JSON envelope to the guest's numeric input: prefer
        // `text` (length in chars), fall back to an explicit `len`.
        let len = match v.get("text").and_then(|t| t.as_str()) {
            Some(text) => text.chars().count() as i32,
            None => v.get("len").and_then(|x| x.as_i64()).unwrap_or(0) as i32,
        };
        let score = self.run_score(len)?;
        Ok(serde_json::json!({
            "tool": self.name,
            "version": self.version,
            "input_len": len,
            "score": score,
        })
        .to_string())
    }
}

/// A [`ToolFactory`] that builds **sandboxed** [`WasmtimeTool`]s from a manifest
/// declaration's inline WAT (`decl.wat`). This is the wasm counterpart to
/// `plugin_host::NativeToolFactory`: wiring it into [`plugin_host::PluginHost`]
/// means enable/disable and CP/DP reconcile drive real Wasmtime tools.
pub struct WasmtimeToolFactory {
    fuel: u64,
}

impl WasmtimeToolFactory {
    pub fn new() -> Self {
        Self { fuel: DEFAULT_FUEL }
    }
    /// Override the per-call fuel budget given to every tool this factory builds.
    pub fn with_fuel(fuel: u64) -> Self {
        Self { fuel }
    }
}

impl Default for WasmtimeToolFactory {
    fn default() -> Self {
        Self::new()
    }
}

impl ToolFactory for WasmtimeToolFactory {
    fn build(&self, decl: &ToolDecl) -> CoreResult<std::sync::Arc<dyn Tool>> {
        let wat = decl.wat.as_deref().ok_or_else(|| {
            CoreError::Tool(format!(
                "wasm tool '{}' has no `wat` in manifest",
                decl.name
            ))
        })?;
        let tool = WasmtimeTool::from_wat(decl.name.clone(), decl.version.clone(), wat, self.fuel)?;
        Ok(std::sync::Arc::new(tool))
    }
}

/// Sample scorer **v1**: `score(len) = len * 3 + 7` (matches the frozen wasmi
/// spike, so the cross-host contract is provably identical).
pub const SCORE_V1_WAT: &str = r#"
(module
  (func (export "score") (param i32) (result i32)
    local.get 0
    i32.const 3
    i32.mul
    i32.const 7
    i32.add))
"#;

/// Sample scorer **v2**: a *different* formula `score(len) = len * 5`, to prove
/// a hot-swap changes observable behaviour at the round boundary.
pub const SCORE_V2_WAT: &str = r#"
(module
  (func (export "score") (param i32) (result i32)
    local.get 0
    i32.const 5
    i32.mul))
"#;

/// A runaway tool: `score` never returns. Under fuel metering the call traps
/// once the budget is exhausted — proving the sandbox bounds untrusted compute.
pub const INFINITE_WAT: &str = r#"
(module
  (func (export "score") (param i32) (result i32)
    (loop $l (br $l))
    unreachable))
"#;

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_core::ports::ToolHost;
    use agistack_plugin_host::{HotPlugRegistry, PluginHost, PluginManifest};
    use futures::executor::block_on;
    use std::sync::Arc;

    #[test]
    fn loads_and_executes_v1() {
        let tool = WasmtimeTool::from_wat("score", "1.0.0", SCORE_V1_WAT, DEFAULT_FUEL).unwrap();
        // len("hello") = 5 -> 5*3+7 = 22
        let out = block_on(tool.invoke(r#"{"text":"hello"}"#)).unwrap();
        assert!(out.contains("\"score\":22"), "unexpected: {out}");
        assert!(out.contains("\"input_len\":5"), "unexpected: {out}");
    }

    #[test]
    fn hot_swap_changes_behaviour_at_round_boundary() {
        // Register v1 into the hot-plug registry, dispatch through the ToolHost
        // port, then atomically swap in v2 and dispatch again. A snapshot taken
        // before the swap must still see v1 (in-flight isolation, ADR-0005/0006).
        let registry = HotPlugRegistry::new();
        registry.register_tool(Arc::new(
            WasmtimeTool::from_wat("score", "1.0.0", SCORE_V1_WAT, DEFAULT_FUEL).unwrap(),
        ));

        let pinned = registry.snapshot(); // pin v1 like an in-flight round

        let v1 = block_on(ToolHost::call(&registry, "score", r#"{"len":10}"#)).unwrap();
        assert!(v1.contains("\"score\":37"), "v1: {v1}"); // 10*3+7

        registry.replace_tool(Arc::new(
            WasmtimeTool::from_wat("score", "2.0.0", SCORE_V2_WAT, DEFAULT_FUEL).unwrap(),
        ));

        let v2 = block_on(ToolHost::call(&registry, "score", r#"{"len":10}"#)).unwrap();
        assert!(v2.contains("\"score\":50"), "v2: {v2}"); // 10*5
        assert!(v2.contains("\"version\":\"2.0.0\""), "v2 version: {v2}");

        // The pinned pre-swap snapshot still resolves v1.
        let still_v1 = block_on(pinned.get("score").unwrap().invoke(r#"{"len":10}"#)).unwrap();
        assert!(
            still_v1.contains("\"score\":37"),
            "pinned still v1: {still_v1}"
        );
    }

    #[test]
    fn fuel_exhaustion_traps_runaway_tool() {
        // A small fuel budget so the infinite loop trips fast and deterministically.
        let tool = WasmtimeTool::from_wat("runaway", "1.0.0", INFINITE_WAT, 100_000).unwrap();
        let err = block_on(tool.invoke(r#"{"len":1}"#)).unwrap_err();
        let msg = format!("{err}");
        assert!(msg.contains("fuel"), "expected fuel trap, got: {msg}");
    }

    #[test]
    fn epoch_deadline_traps_deterministically() {
        // Drive epoch without a timer thread: set the deadline to 1 tick beyond
        // current, advance the engine epoch once, then call -> the store is past
        // its deadline on entry and traps. Generous fuel so fuel is not the cause.
        let tool = WasmtimeTool::from_wat("slow", "1.0.0", SCORE_V1_WAT, u64::MAX).unwrap();
        let mut store = Store::new(&tool.engine, ());
        store.set_fuel(u64::MAX).unwrap();
        store.set_epoch_deadline(1);
        tool.engine.increment_epoch(); // now current epoch == deadline
        let instance = wasmtime::Instance::new(&mut store, &tool.module, &[]).unwrap();
        let score = instance
            .get_typed_func::<i32, i32>(&mut store, "score")
            .unwrap();
        let err = score.call(&mut store, 3).map_err(map_trap).unwrap_err();
        let msg = format!("{err}");
        // The epoch-deadline trap surfaces as Trap::Interrupt in wasmtime 46.
        assert!(
            msg.contains("interrupt"),
            "expected epoch interrupt trap, got: {msg}"
        );
    }

    #[test]
    fn factory_builds_wasm_tool_from_manifest_and_enables() {
        // The wasm factory + PluginHost enable path: a manifest declaring an
        // inline-WAT tool gets compiled and registered as a sandboxed tool, then
        // is dispatchable through the ToolHost port.
        let registry = HotPlugRegistry::new();
        let host = PluginHost::new(registry.clone());
        let manifest = PluginManifest::from_json(
            &serde_json::json!({
                "name": "scorer-pkg",
                "version": "0.1.0",
                "tools": [{
                    "name": "score",
                    "version": "1.0.0",
                    "trust": "wasm",
                    "wat": SCORE_V1_WAT,
                }]
            })
            .to_string(),
        )
        .unwrap();

        let registered = host.enable(&manifest, &WasmtimeToolFactory::new()).unwrap();
        assert_eq!(registered, vec!["score".to_string()]);

        // Dispatch through the core port; confirm it is the sandboxed tier.
        let out = block_on(ToolHost::call(&registry, "score", r#"{"text":"abcd"}"#)).unwrap();
        assert!(out.contains("\"score\":19"), "4*3+7=19, got: {out}");
        assert_eq!(registry.get("score").unwrap().trust(), Trust::SandboxedWasm);

        // Disable removes exactly what it added.
        let removed = host.disable("scorer-pkg").unwrap();
        assert_eq!(removed, vec!["score".to_string()]);
        assert!(registry.get("score").is_none());
    }
}
