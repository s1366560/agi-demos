//! Control-plane / data-plane reconcile protocol: declarative convergence,
//! ACK/NACK with last-good, idempotent re-push, and stale-version rejection.
//!
//! These exercise the agi-stack distillation of Kubernetes' level-triggered
//! reconcile and Istio/Envoy xDS ACK-NACK (see
//! `agi-stack/docs/architecture/08-control-data-plane-separation.md`).

use std::sync::Arc;

use agistack_core::ports::{CoreError, CoreResult};
use agistack_plugin_host::control_plane::ConfigSnapshot;
use agistack_plugin_host::native::EchoTool;
use agistack_plugin_host::{
    ControlPlane, DataPlaneReconciler, HotPlugRegistry, Tool, ToolDecl, ToolFactory,
    TOOL_REGISTRY_TYPE_URL,
};

/// A factory that builds trusted native echo tools, but **refuses** anything with
/// `trust == "bad"` — lets us drive a build failure deterministically to test the
/// NACK / last-good path.
struct TestFactory;

impl ToolFactory for TestFactory {
    fn build(&self, decl: &ToolDecl) -> CoreResult<Arc<dyn Tool>> {
        if decl.trust == "bad" {
            return Err(CoreError::Tool(format!("refusing to build {}", decl.name)));
        }
        Ok(Arc::new(EchoTool::new(decl.name.clone(), decl.version.clone())))
    }
}

fn decl(name: &str, version: &str, trust: &str) -> ToolDecl {
    ToolDecl {
        name: name.to_string(),
        version: version.to_string(),
        trust: trust.to_string(),
        wat: None,
    }
}

/// The control plane sends only desired *state*; the data plane computes the
/// add/remove diff itself (declarative, not imperative).
#[test]
fn declarative_reconcile_converges_via_diff() {
    let registry = HotPlugRegistry::new();
    let mut dp = DataPlaneReconciler::new(registry.clone());
    let mut cp = ControlPlane::new();
    let f = TestFactory;

    // Desired {a, b}; the data plane had nothing -> both added.
    let snap1 = cp.publish(vec![decl("a", "1", "builtin"), decl("b", "1", "builtin")]);
    let (ack1, out1) = dp.reconcile(&snap1, &f);
    assert!(ack1.is_ack());
    assert_eq!(ack1.version(), 1);
    assert_eq!(out1.added, vec!["a".to_string(), "b".to_string()]);
    assert!(out1.removed.is_empty() && out1.updated.is_empty());
    assert_eq!(registry.names(), vec!["a".to_string(), "b".to_string()]);

    // Desired {a, c}: the CP never says "remove b" — it just states the new
    // desired set, and the DP derives that b must go and c must come.
    let snap2 = cp.publish(vec![decl("a", "1", "builtin"), decl("c", "1", "builtin")]);
    let (ack2, out2) = dp.reconcile(&snap2, &f);
    assert!(ack2.is_ack());
    assert_eq!(out2.added, vec!["c".to_string()]);
    assert_eq!(out2.removed, vec!["b".to_string()]);
    assert!(out2.updated.is_empty());
    assert_eq!(registry.names(), vec!["a".to_string(), "c".to_string()]);
    assert_eq!(dp.applied_version(), 2);
}

/// A same-named tool whose declared version changed is hot-swapped (update),
/// not double-counted as add+remove.
#[test]
fn same_name_changed_version_is_hot_swapped() {
    let registry = HotPlugRegistry::new();
    let mut dp = DataPlaneReconciler::new(registry.clone());
    let mut cp = ControlPlane::new();
    let f = TestFactory;

    let s1 = cp.publish(vec![decl("a", "1.0.0", "builtin")]);
    dp.reconcile(&s1, &f);
    assert_eq!(registry.get("a").unwrap().version(), "1.0.0");

    let s2 = cp.publish(vec![decl("a", "2.0.0", "builtin")]);
    let (ack, out) = dp.reconcile(&s2, &f);
    assert!(ack.is_ack());
    assert_eq!(out.updated, vec!["a".to_string()]);
    assert!(out.added.is_empty() && out.removed.is_empty());
    assert_eq!(registry.get("a").unwrap().version(), "2.0.0");
}

/// A snapshot that fails to build is NACKed and the data plane keeps its
/// last-good config — a bad push cannot brick it (Envoy xDS semantics).
#[test]
fn nack_keeps_last_good_config() {
    let registry = HotPlugRegistry::new();
    let mut dp = DataPlaneReconciler::new(registry.clone());
    let mut cp = ControlPlane::new();
    let f = TestFactory;

    let s1 = cp.publish(vec![decl("a", "1", "builtin"), decl("b", "1", "builtin")]);
    dp.reconcile(&s1, &f);
    assert_eq!(registry.names(), vec!["a".to_string(), "b".to_string()]);

    // v2 contains a tool the factory refuses to build, and would also drop `b`.
    let s2 = cp.publish(vec![decl("a", "1", "builtin"), decl("boom", "1", "bad")]);
    let (ack, out) = dp.reconcile(&s2, &f);
    assert!(ack.is_nack());
    assert_eq!(ack.version(), 2);
    assert!(ack.error().unwrap().contains("boom"));
    assert!(out.is_noop());

    // Registry untouched: still last-good {a, b}. `boom` never appeared, and `b`
    // was NOT removed despite being absent from the rejected desired set —
    // accept/reject is atomic.
    assert_eq!(registry.names(), vec!["a".to_string(), "b".to_string()]);
    assert_eq!(dp.applied_version(), 1);
    let lg: Vec<String> = dp.last_good().iter().map(|d| d.name.clone()).collect();
    assert_eq!(lg, vec!["a".to_string(), "b".to_string()]);
}

/// Re-applying the same snapshot (e.g. a reconnect full-resend) is an idempotent
/// no-op: no diff, and existing tool instances are not churned.
#[test]
fn reapplying_same_snapshot_is_idempotent_noop() {
    let registry = HotPlugRegistry::new();
    let mut dp = DataPlaneReconciler::new(registry.clone());
    let mut cp = ControlPlane::new();
    let f = TestFactory;

    let snap = cp.publish(vec![decl("a", "1", "builtin"), decl("b", "1", "builtin")]);
    let (ack1, out1) = dp.reconcile(&snap, &f);
    assert!(ack1.is_ack());
    assert!(!out1.is_noop());
    let a_before = registry.get("a").unwrap();

    let (ack2, out2) = dp.reconcile(&snap, &f);
    assert!(ack2.is_ack());
    assert!(out2.is_noop(), "re-applying the same desired state must be a no-op");

    // Same Arc instance -> the tool was not rebuilt/replaced (no churn of
    // in-flight handles).
    let a_after = registry.get("a").unwrap();
    assert!(Arc::ptr_eq(&a_before, &a_after));
    assert_eq!(registry.names(), vec!["a".to_string(), "b".to_string()]);
}

/// The data plane can jump straight to the latest version (level-triggered: it
/// need not see every intermediate version), and a late, older push is rejected
/// as stale while the converged state is preserved.
#[test]
fn stale_push_is_nacked_and_latest_wins() {
    let registry = HotPlugRegistry::new();
    let mut dp = DataPlaneReconciler::new(registry.clone());
    let mut cp = ControlPlane::new();
    let f = TestFactory;

    let snap1 = cp.publish(vec![decl("a", "1", "builtin")]); // version 1
    let snap2 = cp.publish(vec![decl("a", "1", "builtin"), decl("b", "1", "builtin")]); // version 2

    // Apply the latest (v2) directly, skipping v1.
    let (ack2, _) = dp.reconcile(&snap2, &f);
    assert!(ack2.is_ack());
    assert_eq!(registry.names(), vec!["a".to_string(), "b".to_string()]);
    assert_eq!(dp.applied_version(), 2);

    // A late v1 arrives out of order -> stale NACK; converged v2 state preserved.
    let (ack1, out1) = dp.reconcile(&snap1, &f);
    assert!(ack1.is_nack());
    assert!(ack1.error().unwrap().contains("stale"));
    assert!(out1.is_noop());
    assert_eq!(registry.names(), vec!["a".to_string(), "b".to_string()]);
    assert_eq!(dp.applied_version(), 2);
}

/// A snapshot whose `type_url` does not match is rejected before any mutation
/// (the xDS type-check).
#[test]
fn wrong_type_url_is_nacked() {
    let registry = HotPlugRegistry::new();
    let mut dp = DataPlaneReconciler::new(registry.clone());
    let f = TestFactory;

    let bad = ConfigSnapshot {
        type_url: "some/other/type".to_string(),
        version: 1,
        nonce: "n1".to_string(),
        resources: vec![decl("a", "1", "builtin")],
    };
    let (ack, out) = dp.reconcile(&bad, &f);
    assert!(ack.is_nack());
    assert!(ack.error().unwrap().contains("type_url"));
    assert!(out.is_noop());
    assert!(registry.names().is_empty());

    // Sanity: the canonical type_url is what the control plane stamps.
    assert_eq!(TOOL_REGISTRY_TYPE_URL, "agi-stack/tool-registry/v1");
}
