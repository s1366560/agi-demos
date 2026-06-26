//! `agistack-plugin-host`: the **hot-pluggable, multi-layer capability registry**
//! for agi-stack's extensibility axis, plus the control-plane / data-plane config
//! distribution that drives it.
//!
//! It is the production realization of `02-extensibility.md`,
//! `07-plugin-runtime-architecture.md`, and `08-control-data-plane-separation.md`,
//! distilled from the spike in `spikes/rust-portable-core/crates/plugin-host`:
//!
//!   - **Capability registration** (OpenClaw `api.registerTool/…`)
//!     -> [`registry::HotPlugRegistry`] typed registration methods.
//!   - **Plugin shapes** (OpenClaw plain/hybrid/hook-only/non-capability)
//!     -> [`tool::PluginShape`], classified from a manifest's *actual* contributions.
//!   - **Manifest / package contract** -> [`manifest::PluginManifest`].
//!   - **Enable / disable lifecycle** -> [`host::PluginHost`].
//!   - **L2 Skill = data + Rhai** -> [`skill::SkillEngine`]: declarative tool
//!     compositions ([`skill::Skill`]) gated by a sandboxed Rhai trigger,
//!     composing tools already in the registry (`02-extensibility.md` §5b.6).
//!
//! On top of that hot-plug core sits the **control-flow / data-flow split**
//! (Istio + Kubernetes):
//!   - [`control_plane::ControlPlane`] is the authoritative desired-state holder
//!     (K8s API-server-as-SSOT) emitting versioned, typed
//!     [`control_plane::ConfigSnapshot`]s (Istio/Envoy xDS `DiscoveryResponse`).
//!   - [`reconcile::DataPlaneReconciler`] is the level-triggered, declarative
//!     reconciler that converges this registry toward a pushed snapshot and
//!     ACK/NACKs it, keeping the last-good config on rejection.
//!
//! And the seam to the agent core: [`registry::HotPlugRegistry`] implements
//! [`agistack_core::ToolHost`] (see `toolhost`), so the ReAct loop dispatches tool
//! calls through the *current* atomic registry snapshot.
//!
//! Hot-plug mechanism (ADR-0006): the registry is an `Arc<ArcSwap<ToolRegistry>>`.
//! Mutations are *clone -> modify -> atomic swap*; reads are lock-free. A call
//! that captured an older [`registry::ToolRegistry`] snapshot keeps using the old
//! tool version — changes only take effect for calls started after the swap, i.e.
//! at the next **round boundary** (ADR-0005). This is what makes hot-swap safe.
//!
//! Portability invariant (sustains ADR-0001/0003): no tokio, no `std::time`, no
//! task spawning. `arc-swap` and `rhai` (instruction-count sandbox, not
//! wall-clock) compile to every target the core does, including `wasm32`, so the
//! same registry + skill engine run on server, desktop, mobile, and in-browser.
//! (On `wasm32-unknown-unknown`, rhai's transitive `getrandom` uses the `wasm_js`
//! backend — see `.cargo/config.toml`; native targets use the OS RNG.)

pub mod control_plane;
pub mod host;
pub mod manifest;
pub mod native;
pub mod reconcile;
pub mod registry;
pub mod skill;
pub mod tool;
pub mod toolhost;

pub use control_plane::{ConfigAck, ConfigSnapshot, ControlPlane, TOOL_REGISTRY_TYPE_URL};
pub use host::{PluginHost, ToolFactory};
pub use manifest::{CapabilityKind, PluginManifest, ToolDecl};
pub use native::{EchoTool, LenTool, NativeToolFactory, UpperTool};
pub use reconcile::{DataPlaneReconciler, ReconcileOutcome};
pub use registry::{HotPlugRegistry, ToolRegistry};
pub use skill::{Skill, SkillContext, SkillEngine};
pub use tool::{PluginShape, Tool, Trust};
