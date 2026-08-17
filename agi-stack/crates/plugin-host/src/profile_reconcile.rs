//! Platform profile reconciliation with last-good semantics.
//!
//! Unlike [`crate::reconcile::DataPlaneReconciler`], which owns the concrete
//! tool registry, this reconciler applies the full Python-authored platform
//! profile at a process or session generation boundary. It validates and prepares
//! every activation before deactivating any old plugin, so a rejected snapshot
//! leaves the current generation untouched.

use std::collections::BTreeSet;

use crate::snapshot::{PlatformPluginSnapshot, SnapshotPlugin, PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL};

/// Versioned envelope emitted by the Python control plane.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlatformPluginEnvelope {
    pub version: u64,
    pub nonce: String,
    pub snapshot_digest: String,
    pub type_url: String,
}

impl PlatformPluginEnvelope {
    /// Validate that this envelope carries the platform profile resource type.
    pub fn validate_type(&self) -> Result<(), String> {
        if self.type_url == PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL {
            Ok(())
        } else {
            Err(format!(
                "unknown plugin profile type_url: {}",
                self.type_url
            ))
        }
    }
}

/// Final activation effect prepared by a host implementation.
pub struct PluginActivation {
    plugin_id: String,
    activate: Box<dyn FnOnce()>,
}

impl PluginActivation {
    /// Create an activation from a no-fail commit effect.
    pub fn new(plugin_id: impl Into<String>, activate: Box<dyn FnOnce()>) -> Self {
        Self {
            plugin_id: plugin_id.into(),
            activate,
        }
    }

    /// Plugin id prepared by the host.
    pub fn plugin_id(&self) -> &str {
        &self.plugin_id
    }

    fn commit(self) -> String {
        (self.activate)();
        self.plugin_id
    }
}

/// Host-owned factory that validates a snapshot row and prepares its commit.
pub trait PlatformPluginActivator {
    /// Prepare one activation without changing active runtime state.
    fn prepare(&self, plugin: &SnapshotPlugin) -> Result<PluginActivation, String>;

    /// Deactivate one plugin no longer present in the accepted desired set.
    fn deactivate(&self, _plugin_id: &str) {}
}

/// ACK/NACK outcome for one profile push.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PluginApplyStatus {
    Ack,
    Nack,
}

pub const PLUGIN_APPLY_STATUS_ACK: PluginApplyStatus = PluginApplyStatus::Ack;
pub const PLUGIN_APPLY_STATUS_NACK: PluginApplyStatus = PluginApplyStatus::Nack;

/// Immutable result returned to the transport/control plane.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PluginApplyReceipt {
    pub version: u64,
    pub nonce: String,
    pub digest: String,
    pub status: PluginApplyStatus,
    pub applied_version: u64,
    pub error: Option<String>,
    pub activated: Vec<String>,
}

/// Full-profile reconciler with last-good retention.
pub struct PlatformPluginSnapshotReconciler<A> {
    activator: A,
    applied_version: u64,
    applied_digest: Option<String>,
    last_good: Option<PlatformPluginSnapshot>,
    active_plugin_ids: BTreeSet<String>,
}

impl<A: PlatformPluginActivator> PlatformPluginSnapshotReconciler<A> {
    /// Create a reconciler with no accepted generation.
    pub fn new(activator: A) -> Self {
        Self {
            activator,
            applied_version: 0,
            applied_digest: None,
            last_good: None,
            active_plugin_ids: BTreeSet::new(),
        }
    }

    /// Currently accepted control-plane version.
    pub fn applied_version(&self) -> u64 {
        self.applied_version
    }

    /// Digest of the last accepted snapshot.
    pub fn applied_digest(&self) -> Option<&str> {
        self.applied_digest.as_deref()
    }

    /// Last-good snapshot retained for offline startup and diagnostics.
    pub fn last_good(&self) -> Option<&PlatformPluginSnapshot> {
        self.last_good.as_ref()
    }

    /// Validate, prepare, and atomically publish a platform profile generation.
    pub fn reconcile(
        &mut self,
        envelope: &PlatformPluginEnvelope,
        snapshot: &PlatformPluginSnapshot,
    ) -> PluginApplyReceipt {
        let nack = |error: String| PluginApplyReceipt {
            version: envelope.version,
            nonce: envelope.nonce.clone(),
            digest: envelope.snapshot_digest.clone(),
            status: PluginApplyStatus::Nack,
            applied_version: self.applied_version,
            error: Some(error),
            activated: Vec::new(),
        };

        if let Err(error) = envelope.validate_type() {
            return nack(error);
        }
        if envelope.snapshot_digest != snapshot.digest {
            return nack("envelope digest does not match snapshot".to_string());
        }
        if let Err(error) = snapshot.validate() {
            return nack(error.to_string());
        }
        if envelope.version < self.applied_version {
            return nack(format!(
                "stale plugin profile version {} < applied {}",
                envelope.version, self.applied_version
            ));
        }
        if envelope.version == self.applied_version {
            let unchanged = self
                .applied_digest
                .as_deref()
                .is_some_and(|digest| digest == snapshot.digest);
            if unchanged {
                return self.ack(envelope, Vec::new());
            }
            return nack("profile version reused with a different digest".to_string());
        }

        let mut seen = BTreeSet::new();
        for plugin in &snapshot.plugins {
            if !seen.insert(plugin.id.as_str()) {
                return nack(format!("duplicate plugin id: {}", plugin.id));
            }
        }

        // Build every activation before mutating the active generation.
        let mut prepared = Vec::with_capacity(snapshot.plugins.len());
        for plugin in &snapshot.plugins {
            match self.activator.prepare(plugin) {
                Ok(activation) => prepared.push(activation),
                Err(error) => {
                    return nack(format!("plugin {} failed preparation: {error}", plugin.id));
                }
            }
        }

        // A no-op snapshot does not restart plugin-local resources.
        let desired_ids: BTreeSet<&str> = snapshot.plugins.iter().map(|p| p.id.as_str()).collect();
        let changed = desired_ids
            != self
                .active_plugin_ids
                .iter()
                .map(String::as_str)
                .collect::<BTreeSet<_>>();
        if !changed && self.applied_digest.as_deref() == Some(snapshot.digest.as_str()) {
            return self.ack(envelope, Vec::new());
        }

        // Every new activation is prepared and valid before old resources are removed.
        let removed: Vec<String> = self
            .active_plugin_ids
            .iter()
            .filter(|plugin_id| !desired_ids.contains(plugin_id.as_str()))
            .cloned()
            .collect();
        for plugin_id in &removed {
            self.activator.deactivate(plugin_id);
        }

        let mut activated = Vec::with_capacity(prepared.len());
        for activation in prepared {
            activated.push(activation.commit());
        }
        self.active_plugin_ids = activated.clone().into_iter().collect();
        self.applied_version = envelope.version;
        self.applied_digest = Some(snapshot.digest.clone());
        self.last_good = Some(snapshot.clone());
        self.ack(envelope, activated)
    }

    fn ack(&self, envelope: &PlatformPluginEnvelope, activated: Vec<String>) -> PluginApplyReceipt {
        PluginApplyReceipt {
            version: envelope.version,
            nonce: envelope.nonce.clone(),
            digest: envelope.snapshot_digest.clone(),
            status: PluginApplyStatus::Ack,
            applied_version: self.applied_version,
            error: None,
            activated,
        }
    }
}
