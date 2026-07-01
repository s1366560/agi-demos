//! Runnable narrative for the cross-layer hot-plug spike.
//!
//! Run with: `cargo run -p hotplug-demo`
//!
//! It demonstrates, end to end, the three properties the architecture docs claim:
//!   1. **Trusted built-ins** register natively (`dyn Trait`, full speed).
//!   2. **Manifest-driven enable/disable** adds/removes a plugin's capabilities
//!      atomically (OpenClaw `manage-plugins` lifecycle + shape classification).
//!   3. **Live WASM tool hot-swap**: a sandboxed `.wasm` tool is replaced at
//!      runtime (v1 -> v2) while a round already in flight keeps seeing v1
//!      (round-boundary apply, ADR-0005/0006).
//!
//! Everything runs on the runtime-agnostic core path: no tokio, no `std::time`.
//! Async tool calls are driven by `futures::executor::block_on`.

use std::sync::Arc;

use futures::executor::block_on;

use memstack_adapters_wasmi::WasmTool;
use memstack_core::ports::{CoreError, CoreResult};
use memstack_plugin_host::host::{PluginHost, ToolFactory};
use memstack_plugin_host::manifest::{PluginManifest, ToolDecl};
use memstack_plugin_host::native::{EchoTool, LenTool};
use memstack_plugin_host::registry::HotPlugRegistry;
use memstack_plugin_host::tool::Tool;

// Two builds of the same sandboxed scorer tool, exposing `run(i32) -> i32`.
const SCORE_V1_WAT: &str = r#"
(module (func (export "run") (param i32) (result i32)
  local.get 0 i32.const 3 i32.mul i32.const 7 i32.add))
"#;
const SCORE_V2_WAT: &str = r#"
(module (func (export "run") (param i32) (result i32)
  local.get 0 i32.const 10 i32.mul))
"#;

/// A factory that honours the manifest's **trust axis** (ADR-0002): `"wasm"`
/// tools are built behind the sandboxed [`WasmTool`]; anything else is treated
/// as a trusted built-in. This is the one place runtime knowledge lives — the
/// `plugin-host` crate itself stays free of any WASM dependency.
struct DemoFactory;

impl ToolFactory for DemoFactory {
    fn build(&self, decl: &ToolDecl) -> CoreResult<Arc<dyn Tool>> {
        match decl.trust.as_str() {
            "wasm" => {
                let wat = decl
                    .wat
                    .as_deref()
                    .ok_or_else(|| CoreError::Tool(format!("wasm tool {} has no wat", decl.name)))?;
                Ok(Arc::new(WasmTool::from_wat(
                    decl.name.clone(),
                    decl.version.clone(),
                    wat,
                )?))
            }
            _ => Ok(Arc::new(EchoTool::new(decl.name.clone(), decl.version.clone()))),
        }
    }
}

fn step(title: &str) {
    println!("\n=== {title} ===");
}

fn main() -> CoreResult<()> {
    let registry = HotPlugRegistry::new();
    let host = PluginHost::new(registry.clone());
    let factory = DemoFactory;

    // 1) Trusted built-in registered directly (the native dyn Trait path).
    step("1. Register a trusted built-in (LenTool)");
    registry.register_tool(Arc::new(LenTool));
    let out = block_on(registry.invoke("len", r#"{"text":"hello"}"#))?;
    println!("   len(\"hello\") -> {out}");
    println!("   tools now: {:?}", registry.names());

    // 2) Enable a sandboxed WASM plugin from a manifest (v1).
    step("2. Enable WASM plugin 'scorer' v1 from a manifest");
    let scorer_v1 = PluginManifest::from_json(
        r#"{
            "name": "scorer",
            "version": "1.0.0",
            "tools": [{ "name": "score", "version": "1.0.0", "trust": "wasm" }]
        }"#,
    )?;
    // Inject the v1 wasm body (a real package would reference a .wasm artifact).
    let scorer_v1 = with_wat(scorer_v1, SCORE_V1_WAT);
    println!("   shape: {:?}", scorer_v1.shape());
    let added = host.enable(&scorer_v1, &factory)?;
    println!("   enabled 'scorer' -> registered {added:?}");
    let out = block_on(registry.invoke("score", r#"{"n":5}"#))?;
    println!("   score(n=5) -> {out}");

    // 3) Pin an in-flight snapshot, then hot-swap the tool to v2.
    step("3. Hot-swap 'score' v1 -> v2 (in-flight snapshot stays on v1)");
    let inflight = registry.snapshot();
    let v2 = factory.build(&ToolDecl {
        name: "score".to_string(),
        version: "2.0.0".to_string(),
        trust: "wasm".to_string(),
        wat: Some(SCORE_V2_WAT.to_string()),
    })?;
    registry.replace_tool(v2);
    let out_new = block_on(registry.invoke("score", r#"{"n":5}"#))?;
    println!("   new call   score(n=5) -> {out_new}");
    let pinned = inflight.get("score").expect("pinned tool");
    let out_old = block_on(pinned.invoke(r#"{"n":5}"#))?;
    println!("   pinned call score(n=5) -> {out_old}");
    assert!(out_new.contains("\"out\":50") && out_old.contains("\"out\":22"));
    println!("   OK: new round sees v2 (50), in-flight round still sees v1 (22)");

    // 4) Enable/disable lifecycle with a native multi-tool plugin + shapes.
    step("4. Enable/disable a native 'notes' plugin (lifecycle + shape)");
    let notes = PluginManifest::from_json(
        r#"{
            "name": "notes",
            "version": "0.1.0",
            "tools": [
                { "name": "note_create", "version": "0.1.0" },
                { "name": "note_search", "version": "0.1.0" }
            ],
            "providers": ["local-fts"]
        }"#,
    )?;
    println!("   shape: {:?} (tools + providers => hybrid)", notes.shape());
    host.enable(&notes, &factory)?;
    println!("   tools after enable:  {:?}", registry.names());
    let removed = host.disable("notes");
    println!("   disabled 'notes' -> removed {removed:?}");
    println!("   tools after disable: {:?}", registry.names());

    step("Done");
    println!("   enabled plugins still loaded: {:?}", host.enabled_plugins());
    Ok(())
}

/// Spike helper: attach an inline WAT body to a manifest's single wasm tool.
fn with_wat(mut m: PluginManifest, wat: &str) -> PluginManifest {
    for t in &mut m.tools {
        if t.trust == "wasm" {
            t.wat = Some(wat.to_string());
        }
    }
    m
}
