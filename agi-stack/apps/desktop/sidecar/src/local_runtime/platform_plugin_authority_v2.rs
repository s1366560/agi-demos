use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
    sync::{Arc, Mutex, RwLock},
};

use agistack_plugin_host::protocol_v2::ProfileSnapshotV2;
use agistack_plugin_host::{
    project_snapshot_entries_v2, ControlPlaneDistributionV2, DataPlaneTargetV2,
    DesktopSidecarHttpRouteContributionV2, GenerationLeaseV2, GenerationManagerV2,
    GenerationRetirementV2, ScopeKindV2, ScopeV2, TargetHostDescriptorV2,
    DESKTOP_SIDECAR_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2, DESKTOP_SIDECAR_HOST_SERVICE_V2,
    DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2, DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_VERSION_V2,
    DESKTOP_SIDECAR_HTTP_ROUTE_STRATEGY_V2,
};
use serde::Serialize;
use serde_json::Value;
use tokio::sync::oneshot;

use crate::trusted_session::TrustedSessionBroker;

const DESKTOP_SIDECAR_TARGET_V2: &str = "desktop-sidecar";
const DESKTOP_SIDECAR_HOST_SERVICE_VERSION_V2: &str = "1.0.0";
const DESKTOP_SIDECAR_HOST_STRATEGY_V2: &str = "native-local-capability";

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(super) struct ActivePlatformPluginGenerationDescriptorV2 {
    pub(super) publication_version: Option<u64>,
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
    GenerationMismatch,
    MissingFromGeneration,
    VersionNotActive,
    InactiveForDesktopSidecar,
    ScopeNotVisible,
}

impl PlatformPluginAvailabilityV2Error {
    pub(super) const fn code(self) -> &'static str {
        match self {
            Self::GenerationUnavailable => "plugin_generation_v2_unavailable",
            Self::GenerationMismatch => "plugin_generation_v2_mismatch",
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
            Self::GenerationMismatch => {
                "The active desktop-sidecar projection does not match its runtime generation"
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
    #[cfg(test)]
    pub(super) fn from_distribution(distribution: &ControlPlaneDistributionV2) -> Self {
        Self::from_snapshot(&distribution.snapshot, Some(distribution.envelope.version))
    }

    fn from_snapshot(snapshot: &ProfileSnapshotV2, publication_version: Option<u64>) -> Self {
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
                publication_version,
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
                    && requested_version.map_or(true, |version| entry.version == version)
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

struct PublishedPlatformPluginGenerationV2 {
    projection: Arc<ActivePlatformPluginGenerationV2>,
    renderer_distribution: PlatformPluginRendererDistributionV2,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "source", rename_all = "snake_case")]
pub(crate) enum PlatformPluginRendererDistributionV2 {
    Local {
        snapshot: Value,
    },
    Cloud {
        distribution: ControlPlaneDistributionV2,
    },
}

#[derive(Debug)]
pub(super) struct PlatformPluginGenerationAcquireV2Error {
    reason: PlatformPluginAvailabilityV2Error,
    descriptor: Option<ActivePlatformPluginGenerationDescriptorV2>,
}

impl PlatformPluginGenerationAcquireV2Error {
    pub(super) const fn reason(&self) -> PlatformPluginAvailabilityV2Error {
        self.reason
    }

    pub(super) const fn descriptor(&self) -> Option<&ActivePlatformPluginGenerationDescriptorV2> {
        self.descriptor.as_ref()
    }
}

pub(super) struct ActivePlatformPluginGenerationLeaseV2 {
    projection: Arc<ActivePlatformPluginGenerationV2>,
    http_routes: Arc<DesktopSidecarHttpRouteContributionV2>,
    runtime_generation: Arc<agistack_plugin_host::RuntimeGenerationV2>,
    _release_guard: GenerationReleaseGuardV2,
}

impl fmt::Debug for ActivePlatformPluginGenerationLeaseV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ActivePlatformPluginGenerationLeaseV2")
            .field("descriptor", self.descriptor())
            .finish()
    }
}

impl ActivePlatformPluginGenerationLeaseV2 {
    pub(super) fn knowledge_authority(
        &self,
        scope: &ScopeV2,
    ) -> Result<
        Arc<super::knowledge_authority_v2::KnowledgeAuthorityV2>,
        agistack_plugin_host::RuntimeV2Error,
    > {
        self.runtime_generation.resolve_versioned(
            super::knowledge_authority_v2::SERVICE,
            super::knowledge_authority_v2::VERSION,
            scope,
            None,
        )
    }

    pub(super) fn descriptor(&self) -> &ActivePlatformPluginGenerationDescriptorV2 {
        self.projection.descriptor()
    }

    pub(super) fn http_routes(&self) -> &DesktopSidecarHttpRouteContributionV2 {
        &self.http_routes
    }

    pub(super) fn plugin_availability(
        &self,
        resource_id: &str,
        tenant_id: &str,
        project_id: &str,
    ) -> Result<(), PlatformPluginAvailabilityV2Error> {
        self.projection
            .plugin_availability(resource_id, tenant_id, project_id)
    }
}

struct GenerationReleaseGuardV2 {
    release_tx: Option<oneshot::Sender<()>>,
}

impl Drop for GenerationReleaseGuardV2 {
    fn drop(&mut self) {
        if let Some(release_tx) = self.release_tx.take() {
            let _ = release_tx.send(());
        }
    }
}

pub(super) struct PlatformPluginAuthorityV2 {
    active_generation: RwLock<Option<Arc<PublishedPlatformPluginGenerationV2>>>,
    manager: Arc<GenerationManagerV2>,
    trusted_sessions: Mutex<Option<TrustedSessionBroker>>,
}

impl Default for PlatformPluginAuthorityV2 {
    fn default() -> Self {
        Self {
            active_generation: RwLock::new(None),
            manager: Arc::new(GenerationManagerV2::new()),
            trusted_sessions: Mutex::new(None),
        }
    }
}

impl PlatformPluginAuthorityV2 {
    pub(super) fn install_trusted_sessions(&self, trusted_sessions: TrustedSessionBroker) {
        *lock(&self.trusted_sessions) = Some(trusted_sessions);
    }

    pub(super) fn trusted_sessions(&self) -> Option<TrustedSessionBroker> {
        lock(&self.trusted_sessions).clone()
    }

    pub(super) fn manager(&self) -> Arc<GenerationManagerV2> {
        Arc::clone(&self.manager)
    }

    pub(super) async fn publish(
        &self,
        distribution: &ControlPlaneDistributionV2,
        generation: Arc<agistack_plugin_host::RuntimeGenerationV2>,
    ) {
        self.replace_distribution(distribution, generation)
            .dispose()
            .await;
    }

    pub(super) async fn publish_local_baseline(
        &self,
        snapshot: &ProfileSnapshotV2,
        snapshot_wire: &Value,
        generation: Arc<agistack_plugin_host::RuntimeGenerationV2>,
    ) {
        self.replace_local_baseline(snapshot, snapshot_wire, generation)
            .dispose()
            .await;
    }

    pub(super) fn replace_distribution(
        &self,
        distribution: &ControlPlaneDistributionV2,
        generation: Arc<agistack_plugin_host::RuntimeGenerationV2>,
    ) -> GenerationRetirementV2 {
        self.replace_snapshot(
            &distribution.snapshot,
            Some(distribution.envelope.version),
            PlatformPluginRendererDistributionV2::Cloud {
                distribution: distribution.clone(),
            },
            generation,
        )
    }

    pub(super) fn replace_local_baseline(
        &self,
        snapshot: &ProfileSnapshotV2,
        snapshot_wire: &Value,
        generation: Arc<agistack_plugin_host::RuntimeGenerationV2>,
    ) -> GenerationRetirementV2 {
        self.replace_snapshot(
            snapshot,
            None,
            PlatformPluginRendererDistributionV2::Local {
                snapshot: snapshot_wire.clone(),
            },
            generation,
        )
    }

    fn replace_snapshot(
        &self,
        snapshot: &ProfileSnapshotV2,
        publication_version: Option<u64>,
        renderer_distribution: PlatformPluginRendererDistributionV2,
        generation: Arc<agistack_plugin_host::RuntimeGenerationV2>,
    ) -> GenerationRetirementV2 {
        let mut active_generation = write_lock(&self.active_generation);
        let retirement = self.manager.replace_current(generation);
        *active_generation = Some(Arc::new(PublishedPlatformPluginGenerationV2 {
            projection: Arc::new(ActivePlatformPluginGenerationV2::from_snapshot(
                snapshot,
                publication_version,
            )),
            renderer_distribution,
        }));
        retirement
    }

    pub(super) async fn renderer_distribution_current(
        &self,
    ) -> Option<PlatformPluginRendererDistributionV2> {
        let (lease, renderer_distribution, matches_projection) = {
            let active_generation = read_lock(&self.active_generation);
            let published = active_generation.as_ref()?.clone();
            let lease = self.manager.acquire().ok()?;
            let matches_projection =
                runtime_generation_matches_projection(&lease, published.projection.descriptor())
                    .is_some();
            (
                lease,
                published.renderer_distribution.clone(),
                matches_projection,
            )
        };
        if let Err(error) = lease.release().await {
            tracing::error!(
                error_code = error.code(),
                "desktop-sidecar renderer distribution generation lease release failed"
            );
            return None;
        }
        matches_projection.then_some(renderer_distribution)
    }

    pub(super) fn retire_current(&self) -> GenerationRetirementV2 {
        let mut active_generation = write_lock(&self.active_generation);
        let retirement = self.manager.clear_current();
        active_generation.take();
        retirement
    }

    pub(super) async fn deactivate(&self) {
        self.retire_current().dispose().await;
    }

    pub(super) fn acquire_generation(
        &self,
    ) -> Result<ActivePlatformPluginGenerationLeaseV2, PlatformPluginGenerationAcquireV2Error> {
        let active_generation = read_lock(&self.active_generation);
        let published =
            active_generation
                .as_ref()
                .cloned()
                .ok_or(PlatformPluginGenerationAcquireV2Error {
                    reason: PlatformPluginAvailabilityV2Error::GenerationUnavailable,
                    descriptor: None,
                })?;
        let descriptor = Some(published.projection.descriptor().clone());
        let lease = self
            .manager
            .acquire()
            .map_err(|_| PlatformPluginGenerationAcquireV2Error {
                reason: PlatformPluginAvailabilityV2Error::GenerationUnavailable,
                descriptor: descriptor.clone(),
            })?;
        drop(active_generation);
        let http_routes =
            runtime_generation_matches_projection(&lease, published.projection.descriptor());
        let runtime_generation = lease.generation().ok().cloned();
        let release_guard = spawn_release_owner(lease);
        let (Some(http_routes), Some(runtime_generation)) = (http_routes, runtime_generation)
        else {
            drop(release_guard);
            return Err(PlatformPluginGenerationAcquireV2Error {
                reason: PlatformPluginAvailabilityV2Error::GenerationMismatch,
                descriptor,
            });
        };
        Ok(ActivePlatformPluginGenerationLeaseV2 {
            projection: Arc::clone(&published.projection),
            http_routes,
            runtime_generation,
            _release_guard: release_guard,
        })
    }
}

fn runtime_generation_matches_projection(
    lease: &GenerationLeaseV2,
    descriptor: &ActivePlatformPluginGenerationDescriptorV2,
) -> Option<Arc<DesktopSidecarHttpRouteContributionV2>> {
    let Ok(generation) = lease.generation() else {
        return None;
    };
    if generation.snapshot.profile_id != descriptor.profile_id
        || generation.snapshot.generation != descriptor.generation
        || generation.snapshot.digest != descriptor.digest
    {
        return None;
    }
    let root_scope = ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    };
    let host_matches = generation
        .resolve_versioned::<TargetHostDescriptorV2>(
            DESKTOP_SIDECAR_HOST_SERVICE_V2,
            DESKTOP_SIDECAR_HOST_SERVICE_VERSION_V2,
            &root_scope,
            None,
        )
        .is_ok_and(|host| {
            host.target == DESKTOP_SIDECAR_TARGET_V2
                && host.strategy == DESKTOP_SIDECAR_HOST_STRATEGY_V2
        });
    if !host_matches {
        return None;
    }
    generation
        .resolve_versioned::<DesktopSidecarHttpRouteContributionV2>(
            DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2,
            DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_VERSION_V2,
            &root_scope,
            None,
        )
        .ok()
        .filter(|routes| {
            routes.contribution_id == DESKTOP_SIDECAR_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2
                && routes.strategy == DESKTOP_SIDECAR_HTTP_ROUTE_STRATEGY_V2
        })
}

fn spawn_release_owner(lease: GenerationLeaseV2) -> GenerationReleaseGuardV2 {
    let (release_tx, release_rx) = oneshot::channel();
    tokio::spawn(async move {
        let _ = release_rx.await;
        if let Err(error) = lease.release().await {
            tracing::error!(
                error_code = error.code(),
                "desktop-sidecar protocol-v2 generation lease release failed"
            );
        }
    });
    GenerationReleaseGuardV2 {
        release_tx: Some(release_tx),
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

fn read_lock<T>(lock: &RwLock<T>) -> std::sync::RwLockReadGuard<'_, T> {
    lock.read()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn write_lock<T>(lock: &RwLock<T>) -> std::sync::RwLockWriteGuard<'_, T> {
    lock.write()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

#[cfg(test)]
mod tests {
    use agistack_plugin_host::{
        desktop_sidecar_host_definition_v2, desktop_sidecar_http_routes_definition_v2,
        parse_control_plane_distribution_v2, ControlPlaneDistributionV2, LoaderV2,
        PluginSnapshotReconcilerV2,
    };
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

    #[tokio::test]
    async fn authority_acquires_the_reconciler_generation_and_pins_it_after_clear() {
        let distribution = bootstrap_distribution();
        let authority = PlatformPluginAuthorityV2::default();
        let reconciler = PluginSnapshotReconcilerV2::new_with_manager(
            LoaderV2::for_target(
                DataPlaneTargetV2::DesktopSidecar,
                [
                    desktop_sidecar_http_routes_definition_v2(),
                    desktop_sidecar_host_definition_v2(),
                ],
            ),
            authority.manager(),
        );
        let generation = reconciler
            .stage_snapshot(distribution.snapshot.clone())
            .await
            .expect("generation must stage");
        authority.publish(&distribution, generation).await;

        assert_eq!(
            serde_json::to_value(
                authority
                    .renderer_distribution_current()
                    .await
                    .expect("cloud renderer distribution must be published")
            )
            .expect("cloud renderer distribution must serialize"),
            json!({
                "source": "cloud",
                "distribution": distribution,
            })
        );

        let lease = authority
            .acquire_generation()
            .expect("runtime generation must be available");
        assert_eq!(lease.descriptor().digest, distribution.snapshot.digest);
        assert_eq!(
            lease.http_routes().contribution_id,
            DESKTOP_SIDECAR_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2
        );
        assert_eq!(
            lease.http_routes().strategy,
            DESKTOP_SIDECAR_HTTP_ROUTE_STRATEGY_V2
        );
        assert_eq!(
            lease.plugin_availability(
                "memstack-native-target-hosts@2.0.0",
                "local",
                "local-project",
            ),
            Ok(())
        );

        authority.deactivate().await;
        assert_eq!(authority.renderer_distribution_current().await, None);
        assert_eq!(
            lease.http_routes().contribution_id,
            DESKTOP_SIDECAR_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2
        );
        assert_eq!(
            lease.plugin_availability(
                "memstack-native-target-hosts@2.0.0",
                "local",
                "local-project",
            ),
            Ok(())
        );
        drop(lease);
        reconciler.close().await;
    }

    #[tokio::test]
    async fn authority_rejects_a_projection_from_another_runtime_generation() {
        let distribution = bootstrap_distribution();
        let authority = PlatformPluginAuthorityV2::default();
        let reconciler = PluginSnapshotReconcilerV2::new_with_manager(
            LoaderV2::for_target(
                DataPlaneTargetV2::DesktopSidecar,
                [
                    desktop_sidecar_http_routes_definition_v2(),
                    desktop_sidecar_host_definition_v2(),
                ],
            ),
            authority.manager(),
        );
        let generation = reconciler
            .stage_snapshot(distribution.snapshot.clone())
            .await
            .expect("generation must stage");
        let mut mismatched_projection = distribution.clone();
        mismatched_projection.snapshot.generation += 1;
        mismatched_projection.snapshot.digest = "sha256:mismatched-projection".to_owned();
        authority.publish(&mismatched_projection, generation).await;

        let error = authority
            .acquire_generation()
            .expect_err("projection/runtime mismatch must fail closed");

        assert_eq!(authority.renderer_distribution_current().await, None);

        assert_eq!(
            error.reason(),
            PlatformPluginAvailabilityV2Error::GenerationMismatch
        );
        assert_eq!(
            error.descriptor().map(|descriptor| descriptor.generation),
            Some(distribution.snapshot.generation + 1)
        );
        reconciler.close().await;
    }

    #[tokio::test]
    async fn local_baseline_exports_only_its_validated_snapshot() {
        let distribution = bootstrap_distribution();
        let snapshot_wire: Value =
            serde_json::from_str(BOOTSTRAP).expect("bootstrap wire must parse");
        let authority = PlatformPluginAuthorityV2::default();
        let reconciler = PluginSnapshotReconcilerV2::new_with_manager(
            LoaderV2::for_target(
                DataPlaneTargetV2::DesktopSidecar,
                [
                    desktop_sidecar_http_routes_definition_v2(),
                    desktop_sidecar_host_definition_v2(),
                ],
            ),
            authority.manager(),
        );
        let generation = reconciler
            .stage_snapshot(distribution.snapshot.clone())
            .await
            .expect("generation must stage");
        authority
            .publish_local_baseline(&distribution.snapshot, &snapshot_wire, generation)
            .await;

        assert_eq!(
            serde_json::to_value(
                authority
                    .renderer_distribution_current()
                    .await
                    .expect("local renderer snapshot must be published")
            )
            .expect("local renderer snapshot must serialize"),
            json!({
                "source": "local",
                "snapshot": snapshot_wire,
            })
        );

        authority.deactivate().await;
        reconciler.close().await;
    }
}
