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

pub mod host;
pub mod manifest;
pub mod native;
pub mod registry;
pub mod tool;

pub use host::{PluginHost, ToolFactory};
pub use manifest::{CapabilityKind, PluginManifest, ToolDecl};
pub use registry::{HotPlugRegistry, ToolRegistry};
pub use tool::{PluginShape, Tool, Trust};
