//! The headline property: a sandboxed WASM tool can be **hot-swapped at runtime**
//! (v1 bytes -> v2 bytes) through the atomic `HotPlugRegistry`, and a caller that
//! snapshotted before the swap still observes v1 (round-boundary apply,
//! ADR-0005/0006).

use std::sync::Arc;

use futures::executor::block_on;
use memstack_adapters_wasmi::WasmTool;
use memstack_plugin_host::registry::HotPlugRegistry;
use memstack_plugin_host::tool::{Tool, Trust};

// v1: run(n) = n*3 + 7
const SCORE_V1: &str = r#"
(module
  (func (export "run") (param i32) (result i32)
    local.get 0
    i32.const 3
    i32.mul
    i32.const 7
    i32.add))
"#;

// v2: run(n) = n*10  (different behavior proves the swap took effect)
const SCORE_V2: &str = r#"
(module
  (func (export "run") (param i32) (result i32)
    local.get 0
    i32.const 10
    i32.mul))
"#;

#[test]
fn wasm_tool_hot_swap_with_inflight_isolation() {
    let reg = HotPlugRegistry::new();

    // Load v1 from bytes at runtime and register it.
    let v1 = WasmTool::from_wat("score", "1.0.0", SCORE_V1).unwrap();
    assert_eq!(v1.trust(), Trust::SandboxedWasm);
    reg.register_tool(Arc::new(v1));

    // Invoke v1: 5*3 + 7 = 22, computed inside the sandbox.
    let out = block_on(reg.invoke("score", r#"{"n":5}"#)).unwrap();
    assert!(out.contains("\"out\":22"), "v1 out: {out}");
    assert!(out.contains("\"version\":\"1.0.0\""), "v1 out: {out}");

    // A round already in flight pins the v1 snapshot.
    let inflight = reg.snapshot();

    // Hot-load v2 bytes and atomically replace the registry entry.
    let v2 = WasmTool::from_wat("score", "2.0.0", SCORE_V2).unwrap();
    reg.replace_tool(Arc::new(v2));

    // New calls see v2: 5*10 = 50.
    let out2 = block_on(reg.invoke("score", r#"{"n":5}"#)).unwrap();
    assert!(out2.contains("\"out\":50"), "v2 out: {out2}");
    assert!(out2.contains("\"version\":\"2.0.0\""), "v2 out: {out2}");

    // The in-flight snapshot still resolves v1 -> 22 (no mid-round disruption).
    let pinned = inflight.get("score").unwrap();
    let out1_again = block_on(pinned.invoke(r#"{"n":5}"#)).unwrap();
    assert!(out1_again.contains("\"out\":22"), "pinned out: {out1_again}");
    assert!(out1_again.contains("\"version\":\"1.0.0\""), "pinned: {out1_again}");
}
