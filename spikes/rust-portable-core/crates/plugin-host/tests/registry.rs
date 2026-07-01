//! Registry mechanics: lock-free reads, atomic register/replace/unregister, and
//! the in-flight snapshot isolation that makes hot-swap safe (ADR-0005/0006).

use std::sync::Arc;

use futures::executor::block_on;
use memstack_plugin_host::native::{EchoTool, LenTool};
use memstack_plugin_host::registry::HotPlugRegistry;
use memstack_plugin_host::tool::Trust;

#[test]
fn register_lookup_and_invoke() {
    let reg = HotPlugRegistry::new();
    assert!(reg.names().is_empty());

    reg.register_tool(Arc::new(LenTool));
    assert_eq!(reg.names(), vec!["len".to_string()]);

    let out = block_on(reg.invoke("len", r#"{"text":"hello"}"#)).unwrap();
    assert!(out.contains("\"len\":5"), "unexpected: {out}");

    let tool = reg.get("len").unwrap();
    assert_eq!(tool.trust(), Trust::Builtin);
}

#[test]
fn unknown_tool_is_an_error() {
    let reg = HotPlugRegistry::new();
    let err = block_on(reg.invoke("nope", "{}"));
    assert!(err.is_err());
}

#[test]
fn names_are_sorted_deterministically() {
    let reg = HotPlugRegistry::new();
    reg.register_tool(Arc::new(EchoTool::new("zeta", "1.0.0")));
    reg.register_tool(Arc::new(EchoTool::new("alpha", "1.0.0")));
    reg.register_tool(Arc::new(LenTool));
    assert_eq!(
        reg.names(),
        vec!["alpha".to_string(), "len".to_string(), "zeta".to_string()]
    );
}

#[test]
fn replace_is_a_hot_swap_and_snapshot_pins_the_old_version() {
    let reg = HotPlugRegistry::new();
    reg.register_tool(Arc::new(EchoTool::new("greet", "1.0.0")));
    assert_eq!(reg.get("greet").unwrap().version(), "1.0.0");

    // A caller that snapshots BEFORE the swap pins v1 for its whole round.
    let inflight = reg.snapshot();

    // Hot-swap to v2 atomically.
    reg.replace_tool(Arc::new(EchoTool::new("greet", "2.0.0")));

    // New lookups see v2 immediately...
    assert_eq!(reg.get("greet").unwrap().version(), "2.0.0");
    // ...but the in-flight snapshot still resolves v1 (round-boundary apply).
    assert_eq!(inflight.get("greet").unwrap().version(), "1.0.0");
}

#[test]
fn unregister_removes_only_the_named_tool() {
    let reg = HotPlugRegistry::new();
    reg.register_tool(Arc::new(LenTool));
    reg.register_tool(Arc::new(EchoTool::new("keep", "1.0.0")));

    reg.unregister("len");
    assert_eq!(reg.names(), vec!["keep".to_string()]);
    reg.unregister("does-not-exist"); // no-op
    assert_eq!(reg.names(), vec!["keep".to_string()]);
}
