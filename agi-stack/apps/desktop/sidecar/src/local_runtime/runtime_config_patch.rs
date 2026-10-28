//! The desktop shell sends workspace-only updates; absent settings are not resets.

use serde::{Deserialize, Deserializer};

use super::{browser_bridge::BrowserBridgeConfig, LocalRuntimeConfig};

#[derive(Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LocalRuntimeConfigPatch {
    #[serde(default, deserialize_with = "present")]
    workspace_root: Option<String>,
    #[serde(default, deserialize_with = "present")]
    browser_bridge: Option<BrowserBridgeConfig>,
}

// A missing field preserves its current value. An explicit null remains invalid,
// just as it was when the command accepted a complete LocalRuntimeConfig.
fn present<'de, T: Deserialize<'de>, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<T>, D::Error> {
    T::deserialize(deserializer).map(Some)
}

impl LocalRuntimeConfigPatch {
    pub(super) fn apply_to(self, current: LocalRuntimeConfig) -> LocalRuntimeConfig {
        LocalRuntimeConfig {
            workspace_root: self.workspace_root.unwrap_or(current.workspace_root),
            browser_bridge: self.browser_bridge.unwrap_or(current.browser_bridge),
        }
    }
}

impl From<LocalRuntimeConfig> for LocalRuntimeConfigPatch {
    fn from(config: LocalRuntimeConfig) -> Self {
        Self {
            workspace_root: Some(config.workspace_root),
            browser_bridge: Some(config.browser_bridge),
        }
    }
}

#[cfg(test)]
#[path = "runtime_config_patch_tests.rs"]
mod tests;
