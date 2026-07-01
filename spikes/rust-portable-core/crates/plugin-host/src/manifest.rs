//! Declarative plugin manifest + plugin-shape classification.
//!
//! Mirrors OpenClaw's package contract: a package declares its OpenClaw
//! resources under a `package.json` `"openclaw"` field
//! (`docs/plugins/manifest.md`, `docs/agent-runtime-architecture.md` "Manifests":
//! `{ "openclaw": { "extensions": [...], "skills": [...], "prompts": [...] } }`).
//! Here we use a small JSON shape carrying the same idea so the loader can
//! discover what a plugin contributes *before* instantiating anything.

use serde::Deserialize;

use memstack_core::ports::{CoreError, CoreResult};

use crate::tool::PluginShape;

/// One declared tool capability. The manifest is pure *data* — actual
/// `Arc<dyn Tool>` instances are built by a [`crate::host::ToolFactory`], which
/// keeps this crate free of any WASM/runtime dependency.
#[derive(Debug, Clone, Deserialize)]
pub struct ToolDecl {
    pub name: String,
    #[serde(default = "default_version")]
    pub version: String,
    /// `"builtin"` (native, trusted) or `"wasm"` (sandboxed). Free-form here;
    /// the factory decides how to honour it.
    #[serde(default)]
    pub trust: String,
    /// Optional inline WAT for wasm tools (spike convenience — a real package
    /// would ship a `.wasm` artifact reference instead).
    #[serde(default)]
    pub wat: Option<String>,
}

fn default_version() -> String {
    "0.0.0".to_string()
}

/// The capability kinds a manifest can contribute. Used to classify the plugin
/// [`PluginShape`] the same way OpenClaw counts distinct capability *types*.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CapabilityKind {
    Tool,
    Skill,
    Provider,
    Channel,
}

/// A plugin package manifest. The presence/absence of each contribution list is
/// what drives [`shape`](Self::shape) — exactly OpenClaw's "classify by actual
/// registration behaviour" rule.
#[derive(Debug, Clone, Deserialize)]
pub struct PluginManifest {
    pub name: String,
    #[serde(default = "default_version")]
    pub version: String,
    #[serde(default)]
    pub tools: Vec<ToolDecl>,
    #[serde(default)]
    pub skills: Vec<String>,
    #[serde(default)]
    pub providers: Vec<String>,
    #[serde(default)]
    pub channels: Vec<String>,
    /// Hook names only (no capabilities) -> classifies as `hook-only` (legacy).
    #[serde(default)]
    pub hooks: Vec<String>,
}

impl PluginManifest {
    /// Parse a manifest from JSON.
    pub fn from_json(s: &str) -> CoreResult<Self> {
        serde_json::from_str(s).map_err(|e| CoreError::Tool(format!("bad manifest: {e}")))
    }

    /// Distinct capability *kinds* this manifest contributes (capabilities, not
    /// hooks). Mirrors how OpenClaw counts capability types for shape detection.
    pub fn capability_kinds(&self) -> Vec<CapabilityKind> {
        let mut kinds = Vec::new();
        if !self.tools.is_empty() {
            kinds.push(CapabilityKind::Tool);
        }
        if !self.skills.is_empty() {
            kinds.push(CapabilityKind::Skill);
        }
        if !self.providers.is_empty() {
            kinds.push(CapabilityKind::Provider);
        }
        if !self.channels.is_empty() {
            kinds.push(CapabilityKind::Channel);
        }
        kinds
    }

    /// Classify the plugin shape from actual contributions
    /// (`docs/plugins/architecture.md` "Plugin shapes"):
    /// - 0 capability kinds + only hooks -> `HookOnly`
    /// - 0 capability kinds + no hooks    -> `NonCapability`
    /// - exactly 1 capability kind        -> `PlainCapability`
    /// - 2+ capability kinds              -> `HybridCapability`
    pub fn shape(&self) -> PluginShape {
        match self.capability_kinds().len() {
            0 if !self.hooks.is_empty() => PluginShape::HookOnly,
            0 => PluginShape::NonCapability,
            1 => PluginShape::PlainCapability,
            _ => PluginShape::HybridCapability,
        }
    }
}
