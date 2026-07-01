//! The enable / disable lifecycle on top of the hot-plug registry.
//!
//! Mirrors OpenClaw's plugin management surface (`docs/plugins/manage-plugins.md`):
//! enabling a plugin registers its declared capabilities; disabling unregisters
//! exactly what it contributed. State transitions go through the atomic
//! [`HotPlugRegistry`], so enable/disable are hot — no restart, and in-flight
//! calls that already took a snapshot are unaffected (ADR-0005/0006).

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use agistack_core::ports::{CoreError, CoreResult};

use crate::manifest::{PluginManifest, ToolDecl};
use crate::registry::HotPlugRegistry;
use crate::tool::Tool;

/// Builds concrete `Arc<dyn Tool>` instances from a manifest's tool
/// declarations. Implemented by the host application (e.g. a WASM-backed factory
/// in an adapter crate), which keeps `plugin-host` free of any runtime
/// dependency — the same separation OpenClaw draws between the plugin contract
/// and the harness that realises it.
pub trait ToolFactory {
    fn build(&self, decl: &ToolDecl) -> CoreResult<Arc<dyn Tool>>;
}

/// Tracks enabled plugins and the tools each one contributed, so [`disable`]
/// can remove precisely what [`enable`] added.
///
/// [`enable`]: PluginHost::enable
/// [`disable`]: PluginHost::disable
pub struct PluginHost {
    registry: HotPlugRegistry,
    /// plugin name -> the tool names it registered.
    enabled: Mutex<HashMap<String, Vec<String>>>,
}

impl PluginHost {
    pub fn new(registry: HotPlugRegistry) -> Self {
        Self {
            registry,
            enabled: Mutex::new(HashMap::new()),
        }
    }

    /// The shared registry. Hand `clone()`s of this to runners/workers.
    pub fn registry(&self) -> &HotPlugRegistry {
        &self.registry
    }

    /// Whether a plugin (by manifest name) is currently enabled.
    pub fn is_enabled(&self, name: &str) -> bool {
        self.enabled.lock().expect("poisoned").contains_key(name)
    }

    /// Sorted names of currently enabled plugins.
    pub fn enabled_plugins(&self) -> Vec<String> {
        let mut names: Vec<String> = self
            .enabled
            .lock()
            .expect("poisoned")
            .keys()
            .cloned()
            .collect();
        names.sort();
        names
    }

    /// **Enable** a plugin: build each declared tool via `factory` and register
    /// it atomically. Returns the tool names that were registered.
    pub fn enable(
        &self,
        manifest: &PluginManifest,
        factory: &dyn ToolFactory,
    ) -> CoreResult<Vec<String>> {
        if self.is_enabled(&manifest.name) {
            return Err(CoreError::Tool(format!(
                "plugin already enabled: {}",
                manifest.name
            )));
        }
        let mut registered = Vec::with_capacity(manifest.tools.len());
        for decl in &manifest.tools {
            let tool = factory.build(decl)?;
            self.registry.register_tool(tool);
            registered.push(decl.name.clone());
        }
        self.enabled
            .lock()
            .expect("poisoned")
            .insert(manifest.name.clone(), registered.clone());
        Ok(registered)
    }

    /// **Disable** a plugin: unregister exactly the tools it contributed.
    /// Returns the tool names that were removed (empty if it was not enabled).
    pub fn disable(&self, plugin_name: &str) -> Vec<String> {
        let removed = self
            .enabled
            .lock()
            .expect("poisoned")
            .remove(plugin_name)
            .unwrap_or_default();
        for name in &removed {
            self.registry.unregister(name);
        }
        removed
    }
}
