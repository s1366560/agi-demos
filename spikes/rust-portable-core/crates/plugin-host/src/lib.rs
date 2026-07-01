//! `memstack-plugin-host`: the **hot-pluggable, multi-layer capability registry**
//! for the cross-platform spike's extensibility axis.
//!
//! This crate is the Rust distillation of patterns learned from OpenClaw's
//! (`openclaw/openclaw`) plugin system, mapped onto the agi-stack design:
//!
//!   - **Capability registration** (OpenClaw `api.registerProvider/registerTool/…`)
//!     -> [`registry::HotPlugRegistry`] typed registration methods.
//!   - **Plugin shapes** (OpenClaw plain/hybrid/hook-only/non-capability)
//!     -> [`tool::PluginShape`], classified from a manifest's *actual* contributions.
//!   - **Manifest / package contract** (OpenClaw `package.json` `openclaw` field)
//!     -> [`manifest::PluginManifest`].
//!   - **Enable / disable lifecycle** (OpenClaw `manage-plugins`)
//!     -> [`host::PluginHost`].
//!
//! On top of that hot-plug core sits the **control-flow / data-flow split**
//! (Istio + Kubernetes, see `08-control-data-plane-separation.md`):
//!   - [`control_plane::ControlPlane`] is the authoritative desired-state holder
//!     (K8s API-server-as-SSOT) that emits versioned, typed
//!     [`control_plane::ConfigSnapshot`]s (Istio/Envoy xDS `DiscoveryResponse`).
//!   - [`reconcile::DataPlaneReconciler`] is the level-triggered, declarative
//!     reconciler that converges this registry toward a pushed snapshot and
//!     ACK/NACKs it, keeping the last-good config on rejection.
//!
//! Hot-plug mechanism (ADR-0006): the registry is an `Arc<ArcSwap<ToolRegistry>>`.
//! Mutations are *clone -> modify -> atomic swap*; reads are lock-free. A call
//! that captured an older [`registry::ToolRegistry`] snapshot keeps using the old
//! tool version — changes only take effect for calls started after the swap, i.e.
//! at the next **round boundary** (ADR-0005). This is what makes hot-swap safe
//! without interrupting in-flight work.
//!
//! Portability invariant (sustains ADR-0001/0003): no tokio, no `std::time`, no
//! task spawning. `arc-swap` compiles to every target the core does, including
//! `wasm32`, so the same registry runs on server, desktop, mobile, and in-browser.

pub mod control_plane;
pub mod host;
pub mod manifest;
pub mod native;
pub mod reconcile;
pub mod registry;
pub mod tool;

pub use control_plane::{ConfigAck, ConfigSnapshot, ControlPlane, TOOL_REGISTRY_TYPE_URL};
pub use host::{PluginHost, ToolFactory};
pub use manifest::{CapabilityKind, PluginManifest, ToolDecl};
pub use reconcile::{DataPlaneReconciler, ReconcileOutcome};
pub use registry::{HotPlugRegistry, ToolRegistry};
pub use tool::{PluginShape, Tool, Trust};
