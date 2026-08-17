//! Cross-runtime profile snapshot contract shared with the Python control plane.
//!
//! The Python profile engine owns composition and emits canonical JSON. This
//! module deliberately contains only serde data types and parsing: no filesystem,
//! clock, async runtime, or plugin loading. Keeping the contract pure allows the
//! same snapshot to be consumed by native, desktop, mobile, and browser targets.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use agistack_core::ports::{CoreError, CoreResult};

/// Type URL for MemStack platform profile snapshots.
pub const PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL: &str = "types.memstack.ai/plugin.profile.v1";

/// One capability advertised by an effective plugin row.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SnapshotCapability {
    pub kind: String,
    pub id: String,
    pub contract: String,
    #[serde(default)]
    pub config_schema: Map<String, Value>,
    #[serde(default)]
    pub permissions: Vec<String>,
}

/// One effective plugin row with whole-row configuration.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SnapshotPlugin {
    pub schema_version: u8,
    pub id: String,
    pub version: String,
    pub runtime: String,
    pub trust: String,
    #[serde(default)]
    pub requires: Vec<SnapshotRequirement>,
    pub provides: Vec<SnapshotCapability>,
    pub activation: SnapshotActivation,
    #[serde(default)]
    pub config: Map<String, Value>,
    #[serde(default)]
    pub layer_id: String,
}

/// A required capability contract.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SnapshotRequirement {
    pub capability: String,
    #[serde(default)]
    pub min_version: Option<String>,
}

/// Activation and generation policy.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SnapshotActivation {
    pub default_scope: String,
    pub restart_policy: String,
}

/// The full effective plugin profile emitted by the Python control plane.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlatformPluginSnapshot {
    pub schema_version: u8,
    pub profile_id: String,
    pub plugins: Vec<SnapshotPlugin>,
    pub digest: String,
}

impl PlatformPluginSnapshot {
    /// Parse a canonical Python profile snapshot.
    pub fn parse(raw: &str) -> CoreResult<Self> {
        let snapshot: Self = serde_json::from_str(raw)
            .map_err(|error| CoreError::Tool(format!("bad platform plugin snapshot: {error}")))?;
        snapshot.validate()?;
        Ok(snapshot)
    }

    /// Validate immutable structural and trust invariants.
    pub fn validate(&self) -> CoreResult<()> {
        if self.schema_version != 1 {
            return Err(CoreError::Tool(
                "platform plugin snapshot schema_version must be 1".to_string(),
            ));
        }
        if self.profile_id.trim().is_empty() {
            return Err(CoreError::Tool(
                "platform plugin snapshot profile_id must be non-empty".to_string(),
            ));
        }
        if self.digest.len() != 64 || !self.digest.chars().all(|ch| ch.is_ascii_hexdigit()) {
            return Err(CoreError::Tool(
                "platform plugin snapshot digest must be sha-256 hex".to_string(),
            ));
        }
        if self.plugins.iter().any(|plugin| plugin.schema_version != 1) {
            return Err(CoreError::Tool(
                "every platform plugin row must use schema_version 1".to_string(),
            ));
        }
        if self
            .plugins
            .iter()
            .any(|plugin| plugin.runtime == "python-trusted" && plugin.trust == "untrusted")
        {
            return Err(CoreError::Tool(
                "untrusted plugin cannot use python-trusted runtime".to_string(),
            ));
        }
        Ok(())
    }
}
