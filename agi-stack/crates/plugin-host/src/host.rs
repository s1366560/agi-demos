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

fn plugin_host_lock_poisoned() -> CoreError {
    CoreError::Tool("poisoned plugin host lock".to_string())
}

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
    ///
    /// # Errors
    ///
    /// Returns an error if the plugin lifecycle state lock is poisoned.
    pub fn is_enabled(&self, name: &str) -> CoreResult<bool> {
        Ok(self
            .enabled
            .lock()
            .map_err(|_| plugin_host_lock_poisoned())?
            .contains_key(name))
    }

    /// Sorted names of currently enabled plugins.
    ///
    /// # Errors
    ///
    /// Returns an error if the plugin lifecycle state lock is poisoned.
    pub fn enabled_plugins(&self) -> CoreResult<Vec<String>> {
        let mut names: Vec<String> = self
            .enabled
            .lock()
            .map_err(|_| plugin_host_lock_poisoned())?
            .keys()
            .cloned()
            .collect();
        names.sort();
        Ok(names)
    }

    /// **Enable** a plugin: build each declared tool via `factory` and register
    /// it atomically. Returns the tool names that were registered.
    ///
    /// # Errors
    ///
    /// Returns an error when the plugin is already enabled, when tool
    /// construction fails, or when the plugin lifecycle state lock is poisoned.
    pub fn enable(
        &self,
        manifest: &PluginManifest,
        factory: &dyn ToolFactory,
    ) -> CoreResult<Vec<String>> {
        if self.is_enabled(&manifest.name)? {
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
            .map_err(|_| plugin_host_lock_poisoned())?
            .insert(manifest.name.clone(), registered.clone());
        Ok(registered)
    }

    /// **Disable** a plugin: unregister exactly the tools it contributed.
    /// Returns the tool names that were removed (empty if it was not enabled).
    ///
    /// # Errors
    ///
    /// Returns an error if the plugin lifecycle state lock is poisoned.
    pub fn disable(&self, plugin_name: &str) -> CoreResult<Vec<String>> {
        let removed = self
            .enabled
            .lock()
            .map_err(|_| plugin_host_lock_poisoned())?
            .remove(plugin_name)
            .unwrap_or_default();
        for name in &removed {
            self.registry.unregister(name);
        }
        Ok(removed)
    }
}

#[cfg(test)]
mod tests {
    use std::panic::{catch_unwind, set_hook, take_hook, AssertUnwindSafe};

    use super::*;

    static PANIC_HOOK_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn enabled_plugins_returns_error_when_lock_is_poisoned() {
        let _hook_guard = PANIC_HOOK_LOCK.lock().unwrap();
        let original_hook = take_hook();
        set_hook(Box::new(|_| {}));

        let host = PluginHost::new(HotPlugRegistry::new());
        let poison_result = catch_unwind(AssertUnwindSafe(|| {
            let _guard = host.enabled.lock().unwrap();
            panic!("poison plugin host lock");
        }));
        set_hook(original_hook);

        assert!(poison_result.is_err());
        let err = host.enabled_plugins().unwrap_err();
        assert!(matches!(
            err,
            CoreError::Tool(message) if message == "poisoned plugin host lock"
        ));
    }
}
