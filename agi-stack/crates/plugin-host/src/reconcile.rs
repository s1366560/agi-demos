//! The **data-plane** side of the control-flow / data-flow split: a declarative
//! reconciler that drives the local [`HotPlugRegistry`] toward the control
//! plane's desired state.
//!
//! This is the agi-stack distillation of two reconcilers:
//!   - **Kubernetes controllers** are **level-triggered**: they converge to the
//!     *current* desired state by computing a diff (add / remove / update) rather
//!     than replaying imperative events. A missed, duplicated, or reordered push
//!     self-heals on the next reconcile — the robustness property we want on
//!     flaky device links.
//!   - **Istio / Envoy xDS**: validate a pushed snapshot, then **ACK** on success
//!     or **NACK** while keeping the **last good** config on rejection
//!     (`envoyproxy/envoy:api/xds_protocol.rst`). A bad config cannot brick the
//!     data plane.
//!
//! Portability invariant (sustains ADR-0001/0003): [`reconcile`] is **pure and
//! synchronous** — set arithmetic plus the lock-free [`HotPlugRegistry`] swap. No
//! tokio, no `std::time`, no transport. The snapshot arrives by whatever platform
//! transport the host wired up; converging on it is runtime-agnostic, so the same
//! reconciler runs on server, desktop, mobile, and in-browser.
//!
//! The atomic registry swap happens at a **round boundary** (ADR-0005/0006): a
//! reconcile that adds/removes/replaces tools never disturbs an in-flight call
//! that already pinned an older snapshot.
//!
//! [`reconcile`]: DataPlaneReconciler::reconcile

use std::collections::{BTreeMap, BTreeSet};

use crate::control_plane::{ConfigAck, ConfigSnapshot, TOOL_REGISTRY_TYPE_URL};
use crate::host::ToolFactory;
use crate::manifest::ToolDecl;
use crate::registry::HotPlugRegistry;

/// What a single [`reconcile`](DataPlaneReconciler::reconcile) changed — returned
/// alongside the ACK for observability and tests. All three lists empty means the
/// data plane was already converged: an **idempotent no-op**, the steady-state
/// case for a re-push or a reconnect full-resend.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ReconcileOutcome {
    /// Tools present in desired but not observed — newly registered.
    pub added: Vec<String>,
    /// Tools present in observed but not desired — unregistered.
    pub removed: Vec<String>,
    /// Tools present in both whose declared `version` changed — hot-swapped.
    pub updated: Vec<String>,
}

impl ReconcileOutcome {
    /// Whether this reconcile changed nothing (already converged).
    pub fn is_noop(&self) -> bool {
        self.added.is_empty() && self.removed.is_empty() && self.updated.is_empty()
    }
}

/// Drives a [`HotPlugRegistry`] (the local data-plane state) toward the control
/// plane's desired config.
///
/// It tracks the **applied version** (for staleness + idempotency checks) and the
/// **last good** desired set (so a NACK can keep serving it). Building concrete
/// `Arc<dyn Tool>` instances is delegated to a [`ToolFactory`] — exactly like
/// [`crate::host::PluginHost`] — so this crate stays free of any runtime/WASM
/// dependency: the *config* (control plane) and the *tool runtime* (data plane)
/// are cleanly separated.
pub struct DataPlaneReconciler {
    registry: HotPlugRegistry,
    applied_version: u64,
    last_good: Vec<ToolDecl>,
}

impl DataPlaneReconciler {
    /// Create a reconciler over a (typically empty) registry. The registry is
    /// shared (`Arc` inside), so the same data-plane state can be handed to the
    /// runners that actually invoke tools.
    pub fn new(registry: HotPlugRegistry) -> Self {
        Self {
            registry,
            applied_version: 0,
            last_good: Vec::new(),
        }
    }

    /// The shared registry — hand `clone()`s to runners/workers.
    pub fn registry(&self) -> &HotPlugRegistry {
        &self.registry
    }

    /// The version currently applied to the registry (0 before the first ACK).
    pub fn applied_version(&self) -> u64 {
        self.applied_version
    }

    /// The last-good desired set still being served (after a NACK, this is the
    /// pre-rejection config).
    pub fn last_good(&self) -> &[ToolDecl] {
        &self.last_good
    }

    /// Reconcile the local registry toward `snapshot`'s desired state and return
    /// `(ack, outcome)`.
    ///
    /// **Declarative + level-triggered**: we compute the diff between desired and
    /// observed and apply only that, instead of executing imperative add/remove
    /// commands. The protocol rules — all deterministic, Agent First:
    ///
    /// 1. **Type check.** A wrong `type_url`, or a snapshot with duplicate tool
    ///    names, is rejected -> **NACK**, registry untouched (xDS type-check).
    /// 2. **Staleness.** `version < applied_version` is a late / reordered push ->
    ///    **NACK**, keep current (K8s monotonic `resourceVersion` / optimistic
    ///    concurrency). Non-contiguous *forward* jumps are fine: we converge to
    ///    the latest, we do not require every intermediate version.
    /// 3. **Validate-then-apply.** All added/updated tools are built *before* any
    ///    registry mutation; if any build fails -> **NACK**, last-good intact
    ///    (atomic accept/reject, Envoy semantics).
    /// 4. **Converge.** `desired - observed = added`, `observed - desired =
    ///    removed`, same-name-changed-version = `updated`. Apply via the atomic
    ///    registry (round-boundary), record the version, then **ACK**.
    pub fn reconcile(
        &mut self,
        snapshot: &ConfigSnapshot,
        factory: &dyn ToolFactory,
    ) -> (ConfigAck, ReconcileOutcome) {
        let nack = |error: String| {
            (
                ConfigAck::Nack {
                    version: snapshot.version,
                    nonce: snapshot.nonce.clone(),
                    error,
                },
                ReconcileOutcome::default(),
            )
        };

        // (1) Type check — reject a snapshot of the wrong resource type.
        if snapshot.type_url != TOOL_REGISTRY_TYPE_URL {
            return nack(format!("unknown type_url: {}", snapshot.type_url));
        }

        // (1b) Reject duplicate names — a desired *set* must be unambiguous.
        let mut seen = BTreeSet::new();
        for decl in &snapshot.resources {
            if !seen.insert(decl.name.as_str()) {
                return nack(format!("duplicate tool name: {}", decl.name));
            }
        }

        // (2) Staleness — a strictly older version is a stale/reordered push.
        if snapshot.version < self.applied_version {
            return nack(format!(
                "stale version {} < applied {}",
                snapshot.version, self.applied_version
            ));
        }

        // Observe current data-plane state: name -> version.
        let snap = self.registry.snapshot();
        let observed: BTreeMap<String, String> = snap
            .names()
            .into_iter()
            .filter_map(|n| snap.get(&n).map(|t| (n, t.version().to_string())))
            .collect();
        let desired: BTreeMap<&str, &ToolDecl> = snapshot
            .resources
            .iter()
            .map(|d| (d.name.as_str(), d))
            .collect();

        // (4a) Classify the diff (declarative, not imperative).
        let mut to_add: Vec<ToolDecl> = Vec::new();
        let mut to_update: Vec<ToolDecl> = Vec::new();
        for (name, decl) in &desired {
            match observed.get(*name) {
                None => to_add.push((*decl).clone()),
                Some(obs_ver) if obs_ver != &decl.version => to_update.push((*decl).clone()),
                Some(_) => {} // present and same version -> unchanged, leave pinned
            }
        }
        let to_remove: Vec<String> = observed
            .keys()
            .filter(|n| !desired.contains_key(n.as_str()))
            .cloned()
            .collect();

        // (3) Validate: build every add/update BEFORE mutating, so a bad snapshot
        // leaves last-good intact.
        let mut built = Vec::with_capacity(to_add.len() + to_update.len());
        for decl in to_add.iter().chain(to_update.iter()) {
            match factory.build(decl) {
                Ok(tool) => built.push(tool),
                Err(e) => return nack(format!("build failed for {}: {e}", decl.name)),
            }
        }

        // (4b) Apply the diff atomically (each op is an ArcSwap; an in-flight
        // snapshot pins the pre-swap versions until its round ends).
        for tool in built {
            self.registry.register_tool(tool);
        }
        for name in &to_remove {
            self.registry.unregister(name);
        }

        // Record acceptance: this version is now the data plane's good config.
        self.applied_version = snapshot.version;
        self.last_good = snapshot.resources.clone();

        let mut outcome = ReconcileOutcome {
            added: to_add.iter().map(|d| d.name.clone()).collect(),
            removed: to_remove,
            updated: to_update.iter().map(|d| d.name.clone()).collect(),
        };
        outcome.added.sort();
        outcome.removed.sort();
        outcome.updated.sort();

        (
            ConfigAck::Ack {
                version: snapshot.version,
                nonce: snapshot.nonce.clone(),
            },
            outcome,
        )
    }
}
