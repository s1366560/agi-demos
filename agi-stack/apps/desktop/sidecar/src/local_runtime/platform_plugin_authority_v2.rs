use std::{
    collections::{BTreeMap, BTreeSet},
    sync::{Arc, Mutex},
};

use agistack_plugin_host::{
    project_snapshot_entries_v2, ControlPlaneDistributionV2, DataPlaneTargetV2, ScopeKindV2,
    ScopeV2,
};
use serde::Serialize;

use crate::trusted_session::TrustedSessionBroker;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(super) struct ActivePlatformPluginGenerationDescriptorV2 {
    pub(super) publication_version: u64,
    pub(super) profile_id: String,
    pub(super) generation: u64,
    pub(super) digest: String,
    pub(super) target: &'static str,
}

#[derive(Clone, Debug)]
struct ActivePlatformPluginEntryV2 {
    plugin_id: String,
    version: String,
    scope: ScopeV2,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum PlatformPluginAvailabilityV2Error {
    GenerationUnavailable,
    MissingFromGeneration,
    VersionNotActive,
    InactiveForDesktopSidecar,
    ScopeNotVisible,
}

impl PlatformPluginAvailabilityV2Error {
    pub(super) const fn code(self) -> &'static str {
        match self {
            Self::GenerationUnavailable => "plugin_generation_v2_unavailable",
            Self::MissingFromGeneration => "plugin_missing_from_generation_v2",
            Self::VersionNotActive => "plugin_version_not_active_v2",
            Self::InactiveForDesktopSidecar => "plugin_inactive_for_desktop_sidecar_v2",
            Self::ScopeNotVisible => "plugin_scope_not_visible_v2",
        }
    }

    pub(super) const fn message(self) -> &'static str {
        match self {
            Self::GenerationUnavailable => {
                "No active protocol-v2 desktop-sidecar generation is available"
            }
            Self::MissingFromGeneration => {
                "The plugin is absent from the active protocol-v2 generation"
            }
            Self::VersionNotActive => {
                "The requested plugin version is not active in this generation"
            }
            Self::InactiveForDesktopSidecar => {
                "The plugin has no active desktop-sidecar contribution in this generation"
            }
            Self::ScopeNotVisible => {
                "The active plugin contribution is outside the current workspace scope"
            }
        }
    }
}

pub(super) struct ActivePlatformPluginGenerationV2 {
    descriptor: ActivePlatformPluginGenerationDescriptorV2,
    manifest_versions: BTreeMap<String, BTreeSet<String>>,
    active_entries: Vec<ActivePlatformPluginEntryV2>,
}

impl ActivePlatformPluginGenerationV2 {
    pub(super) fn from_distribution(distribution: &ControlPlaneDistributionV2) -> Self {
        let snapshot = &distribution.snapshot;
        let mut manifest_versions: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for manifest in &snapshot.manifests {
            manifest_versions
                .entry(manifest.plugin_id.clone())
                .or_default()
                .insert(manifest.version.clone());
        }
        let active_entries =
            project_snapshot_entries_v2(snapshot, &DataPlaneTargetV2::DesktopSidecar)
                .into_iter()
                .filter(|entry| entry.enabled)
                .filter_map(|entry| {
                    snapshot
                        .manifests
                        .iter()
                        .find(|manifest| manifest.plugin_id == entry.plugin_ref)
                        .map(|manifest| ActivePlatformPluginEntryV2 {
                            plugin_id: manifest.plugin_id.clone(),
                            version: manifest.version.clone(),
                            scope: entry.scope.clone(),
                        })
                })
                .collect();
        Self {
            descriptor: ActivePlatformPluginGenerationDescriptorV2 {
                publication_version: distribution.envelope.version,
                profile_id: snapshot.profile_id.clone(),
                generation: snapshot.generation,
                digest: snapshot.digest.clone(),
                target: "desktop-sidecar",
            },
            manifest_versions,
            active_entries,
        }
    }

    pub(super) fn descriptor(&self) -> &ActivePlatformPluginGenerationDescriptorV2 {
        &self.descriptor
    }

    pub(super) fn plugin_availability(
        &self,
        resource_id: &str,
        tenant_id: &str,
        project_id: &str,
    ) -> Result<(), PlatformPluginAvailabilityV2Error> {
        let (plugin_id, requested_version) = plugin_coordinate(resource_id);
        let versions = self
            .manifest_versions
            .get(plugin_id)
            .ok_or(PlatformPluginAvailabilityV2Error::MissingFromGeneration)?;
        if requested_version.is_some_and(|version| !versions.contains(version)) {
            return Err(PlatformPluginAvailabilityV2Error::VersionNotActive);
        }
        let matching_entries: Vec<_> = self
            .active_entries
            .iter()
            .filter(|entry| {
                entry.plugin_id == plugin_id
                    && requested_version.is_none_or(|version| entry.version == version)
            })
            .collect();
        if matching_entries.is_empty() {
            return Err(PlatformPluginAvailabilityV2Error::InactiveForDesktopSidecar);
        }
        if matching_entries
            .iter()
            .any(|entry| scope_is_visible(&entry.scope, tenant_id, project_id))
        {
            return Ok(());
        }
        Err(PlatformPluginAvailabilityV2Error::ScopeNotVisible)
    }
}

#[derive(Default)]
pub(super) struct PlatformPluginAuthorityV2 {
    active_generation: Mutex<Option<Arc<ActivePlatformPluginGenerationV2>>>,
    trusted_sessions: Mutex<Option<TrustedSessionBroker>>,
}

impl PlatformPluginAuthorityV2 {
    pub(super) fn install_trusted_sessions(&self, trusted_sessions: TrustedSessionBroker) {
        *lock(&self.trusted_sessions) = Some(trusted_sessions);
    }

    pub(super) fn trusted_sessions(&self) -> Option<TrustedSessionBroker> {
        lock(&self.trusted_sessions).clone()
    }

    pub(super) fn publish(&self, distribution: &ControlPlaneDistributionV2) {
        *lock(&self.active_generation) = Some(Arc::new(
            ActivePlatformPluginGenerationV2::from_distribution(distribution),
        ));
    }

    pub(super) fn clear(&self) {
        lock(&self.active_generation).take();
    }

    pub(super) fn active_generation(&self) -> Option<Arc<ActivePlatformPluginGenerationV2>> {
        lock(&self.active_generation).clone()
    }
}

fn plugin_coordinate(resource_id: &str) -> (&str, Option<&str>) {
    resource_id
        .rsplit_once('@')
        .filter(|(plugin_id, version)| !plugin_id.is_empty() && !version.is_empty())
        .map_or((resource_id, None), |(plugin_id, version)| {
            (plugin_id, Some(version))
        })
}

fn scope_is_visible(scope: &ScopeV2, tenant_id: &str, project_id: &str) -> bool {
    match scope.kind {
        ScopeKindV2::Root => true,
        ScopeKindV2::Tenant => scope.tenant_id.as_deref() == Some(tenant_id),
        ScopeKindV2::Project => {
            scope.tenant_id.as_deref() == Some(tenant_id)
                && scope.project_id.as_deref() == Some(project_id)
        }
        ScopeKindV2::Session => false,
    }
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

#[cfg(test)]
mod tests {
    use agistack_plugin_host::{parse_control_plane_distribution_v2, ControlPlaneDistributionV2};
    use serde_json::{json, Value};

    use super::*;

    const BOOTSTRAP: &str =
        include_str!("../../../../../../shared/profiles/memstack-default-bootstrap.v2.json");

    fn bootstrap_distribution() -> ControlPlaneDistributionV2 {
        let snapshot: Value = serde_json::from_str(BOOTSTRAP).expect("bootstrap must parse");
        let digest = snapshot["digest"].as_str().expect("snapshot digest");
        let raw = json!({
            "schema_version": 2,
            "descriptor": {
                "profile_id": snapshot["profile_id"],
                "generation": snapshot["generation"],
                "digest": digest,
            },
            "snapshot": snapshot,
            "envelope": {
                "version": 31,
                "nonce": "nonce-31",
                "snapshot_digest": digest,
                "type_url": "types.memstack.ai/plugin.profile.v2",
            },
        });
        parse_control_plane_distribution_v2(&raw.to_string()).expect("distribution must parse")
    }

    #[test]
    fn active_desktop_generation_accepts_only_its_exact_plugin_version() {
        let generation =
            ActivePlatformPluginGenerationV2::from_distribution(&bootstrap_distribution());

        assert_eq!(
            generation.plugin_availability(
                "memstack-native-target-hosts@2.0.0",
                "local",
                "local-project",
            ),
            Ok(())
        );
        assert_eq!(
            generation.plugin_availability(
                "memstack-native-target-hosts@1.0.0",
                "local",
                "local-project",
            ),
            Err(PlatformPluginAvailabilityV2Error::VersionNotActive)
        );
    }

    #[test]
    fn missing_and_wrong_target_plugins_are_distinct_structured_failures() {
        let generation =
            ActivePlatformPluginGenerationV2::from_distribution(&bootstrap_distribution());

        assert_eq!(
            generation.plugin_availability("missing-plugin", "local", "local-project"),
            Err(PlatformPluginAvailabilityV2Error::MissingFromGeneration)
        );
        assert_eq!(
            generation.plugin_availability("memstack-runtime-kernel", "local", "local-project"),
            Err(PlatformPluginAvailabilityV2Error::InactiveForDesktopSidecar)
        );
    }
}
