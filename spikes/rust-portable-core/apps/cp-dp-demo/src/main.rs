//! Runnable narrative for the **control-flow / data-flow separation** spike.
//!
//! Run with: `cargo run -p cp-dp-demo`
//!
//! It demonstrates, end to end, the protocol the architecture docs claim
//! (`agi-stack/docs/architecture/08-control-data-plane-separation.md`):
//!
//!   1. **Declarative push.** A cloud [`ControlPlane`] (the single source of
//!      truth, like a Kubernetes API server) publishes a *desired tool set* as a
//!      versioned [`ConfigSnapshot`] (an Istio/Envoy xDS `DiscoveryResponse`). It
//!      never issues imperative add/remove commands.
//!   2. **Level-triggered reconcile.** A [`DataPlaneReconciler`] (an edge/device
//!      data plane) computes the diff against its local registry and converges —
//!      adding, removing, and hot-swapping tools — then **ACKs** the version.
//!   3. **NACK + last-good.** A snapshot that fails to build is **NACKed** and the
//!      data plane keeps serving its previous good config: a bad push can't brick
//!      it.
//!   4. **Idempotent re-push.** Re-sending the current snapshot (a reconnect
//!      full-resend) is a no-op ACK — no churn of in-flight tools.
//!
//! Everything runs on the runtime-agnostic core path: no tokio, no `std::time`,
//! no transport. The control plane and reconciler exchange snapshots by direct
//! call here; a real deployment swaps in gRPC/WebSocket (server) or HTTP
//! long-poll (device) without touching this logic. Async tool calls are driven
//! by `futures::executor::block_on`.

use std::sync::Arc;

use futures::executor::block_on;

use memstack_adapters_wasmi::WasmTool;
use memstack_core::ports::{CoreError, CoreResult};
use memstack_plugin_host::control_plane::ConfigAck;
use memstack_plugin_host::native::EchoTool;
use memstack_plugin_host::{
    ControlPlane, DataPlaneReconciler, HotPlugRegistry, ReconcileOutcome, Tool, ToolDecl,
    ToolFactory,
};

// A sandboxed scorer tool exposing `run(i32) -> i32`: out = n * 10.
const SCORE_WAT: &str = r#"
(module (func (export "run") (param i32) (result i32)
  local.get 0 i32.const 10 i32.mul))
"#;

/// A factory honouring the manifest's **trust axis** (ADR-0002): `"wasm"` tools
/// are built behind the sandboxed [`WasmTool`]; `"bad"` is refused (to drive a
/// NACK); everything else is a trusted native built-in. This is the one place
/// runtime knowledge lives — the control plane / reconciler stay free of any WASM
/// dependency, exactly the config-vs-runtime separation the docs describe.
struct DemoFactory;

impl ToolFactory for DemoFactory {
    fn build(&self, decl: &ToolDecl) -> CoreResult<Arc<dyn Tool>> {
        match decl.trust.as_str() {
            "bad" => Err(CoreError::Tool(format!(
                "factory refuses to build broken tool '{}'",
                decl.name
            ))),
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

fn builtin(name: &str, version: &str) -> ToolDecl {
    ToolDecl {
        name: name.to_string(),
        version: version.to_string(),
        trust: "builtin".to_string(),
        wat: None,
    }
}

fn wasm(name: &str, version: &str, wat: &str) -> ToolDecl {
    ToolDecl {
        name: name.to_string(),
        version: version.to_string(),
        trust: "wasm".to_string(),
        wat: Some(wat.to_string()),
    }
}

fn show_ack(ack: &ConfigAck) -> String {
    match ack {
        ConfigAck::Ack { version, nonce } => format!("ACK   v{version}  [{nonce}]"),
        ConfigAck::Nack {
            version,
            nonce,
            error,
        } => format!("NACK  v{version}  [{nonce}]: {error}"),
    }
}

fn show_outcome(out: &ReconcileOutcome) -> String {
    if out.is_noop() {
        "no-op (already converged)".to_string()
    } else {
        format!(
            "added={:?} removed={:?} updated={:?}",
            out.added, out.removed, out.updated
        )
    }
}

fn step(title: &str) {
    println!("\n=== {title} ===");
}

fn main() -> CoreResult<()> {
    // Cloud control plane (SSOT) + edge data plane (reconciler over a registry).
    let mut cp = ControlPlane::new();
    let registry = HotPlugRegistry::new();
    let mut dp = DataPlaneReconciler::new(registry.clone());
    let factory = DemoFactory;

    // 1) CP publishes desired v1 = {echo, len}. DP had nothing -> both added.
    step("1. Control plane publishes desired v1 = {echo, len}");
    let snap1 = cp.publish(vec![builtin("echo", "1.0.0"), builtin("len", "1.0.0")]);
    println!(
        "   CP -> snapshot v{} ({} resources)",
        snap1.version,
        snap1.resources.len()
    );
    let (ack1, out1) = dp.reconcile(&snap1, &factory);
    println!("   DP <- {}", show_ack(&ack1));
    println!("   DP    reconcile: {}", show_outcome(&out1));
    println!("   DP    registry now: {:?}", registry.names());

    // 2) CP publishes desired v2 = {len@2.0.0, score(wasm)}. It only states the
    //    new desired set; the DP derives add(score) + remove(echo) + update(len).
    step("2. Control plane publishes desired v2 = {len@2.0.0, score(wasm)}  (drops echo)");
    let snap2 = cp.publish(vec![
        builtin("len", "2.0.0"),
        wasm("score", "1.0.0", SCORE_WAT),
    ]);
    println!(
        "   CP -> snapshot v{} ({} resources)",
        snap2.version,
        snap2.resources.len()
    );
    let (ack2, out2) = dp.reconcile(&snap2, &factory);
    println!("   DP <- {}", show_ack(&ack2));
    println!(
        "   DP    reconcile: {}  <- DP computed the diff, CP sent only desired state",
        show_outcome(&out2)
    );
    println!("   DP    registry now: {:?}", registry.names());
    // The sandboxed wasm tool flowed through the same CP/DP pipe and now runs.
    let scored = block_on(registry.invoke("score", r#"{"n":5}"#))?;
    println!("   DP    invoke score(n=5) -> {scored}");
    assert!(out2.added == ["score"] && out2.removed == ["echo"] && out2.updated == ["len"]);
    assert!(registry.names() == ["len".to_string(), "score".to_string()]);

    // 3) Reconnect: CP re-sends the *current* desired state at the SAME version
    //    (xDS full-resend / Kong DP reconnect). DP is already converged -> no-op.
    step("3. Data plane reconnects; CP re-sends current state v2  -> idempotent no-op ACK");
    let resend = cp.snapshot();
    println!(
        "   CP -> snapshot v{} (same version, fresh nonce {})",
        resend.version, resend.nonce
    );
    let score_before = registry.get("score").expect("score present");
    let (ack3, out3) = dp.reconcile(&resend, &factory);
    println!("   DP <- {}", show_ack(&ack3));
    println!("   DP    reconcile: {}", show_outcome(&out3));
    let score_after = registry.get("score").expect("score present");
    let churn_free = Arc::ptr_eq(&score_before, &score_after);
    println!("   DP    in-flight tool instance unchanged (no churn): {churn_free}");
    assert!(ack3.is_ack() && out3.is_noop() && churn_free);

    // 4) CP publishes desired v3 with a tool the data plane can't build -> NACK,
    //    keep last-good v2. CP's SSOT advances to v3, but the DP protects itself.
    step("4. Control plane publishes a broken desired v3  -> NACK, keep last-good v2");
    let snap4 = cp.publish(vec![
        builtin("len", "2.0.0"),
        wasm("score", "1.0.0", SCORE_WAT),
        ToolDecl {
            name: "rogue".to_string(),
            version: "1.0.0".to_string(),
            trust: "bad".to_string(),
            wat: None,
        },
    ]);
    println!(
        "   CP -> snapshot v{} ({} resources, one unbuildable)",
        snap4.version,
        snap4.resources.len()
    );
    let (ack4, out4) = dp.reconcile(&snap4, &factory);
    println!("   DP <- {}", show_ack(&ack4));
    println!("   DP    reconcile: {}", show_outcome(&out4));
    println!(
        "   DP    registry still: {:?}  (last-good preserved, applied v{})",
        registry.names(),
        dp.applied_version()
    );
    assert!(
        ack4.is_nack()
            && registry.names() == ["len".to_string(), "score".to_string()]
            && dp.applied_version() == 2
    );

    step("Done");
    println!(
        "   converged registry: {:?} @ applied v{}",
        registry.names(),
        dp.applied_version()
    );
    println!(
        "   control-plane SSOT desired version: v{}  (DP holds last-good v{} while v{} is unbuildable)",
        cp.version(),
        dp.applied_version(),
        cp.version()
    );
    Ok(())
}
