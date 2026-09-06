use std::{collections::BTreeMap, sync::Arc};

use agistack_plugin_host::protocol_v2::ProfileSnapshotV2;
use agistack_plugin_host::{
    desktop_sidecar_host_definition_v2, desktop_sidecar_http_routes_definition_v2,
    parse_profile_snapshot_v2, rust_server_host_definition_v2,
    rust_server_http_routes_definition_v2, ContextV2, DataPlaneTargetV2,
    DesktopSidecarHttpRouteContributionV2, LoaderV2, PluginDefinitionV2, PluginModuleRuntimeV2,
    RuntimeV2Error, ScopeKindV2, ScopeV2, TargetHostDescriptorV2,
    DESKTOP_SIDECAR_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2, DESKTOP_SIDECAR_HOST_SERVICE_V2,
    DESKTOP_SIDECAR_HTTP_ROUTES_MODULE_REF_V2, DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2,
    DESKTOP_SIDECAR_HTTP_ROUTE_STRATEGY_V2,
};
use async_trait::async_trait;
use futures::executor::block_on;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const BOOTSTRAP: &str =
    include_str!("../../../../shared/profiles/memstack-default-bootstrap.v2.json");

fn root_scope() -> ScopeV2 {
    ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    }
}

fn sha256_digest(value: &Value) -> String {
    let canonical = serde_jcs::to_vec(value).expect("value must canonicalize");
    format!("sha256:{:x}", Sha256::digest(canonical))
}

fn refresh_snapshot_digest(snapshot: &mut Value) {
    let mut digest_payload = snapshot.clone();
    digest_payload
        .as_object_mut()
        .expect("snapshot object")
        .remove("digest");
    snapshot["digest"] = Value::String(
        sha256_digest(&digest_payload)
            .strip_prefix("sha256:")
            .expect("digest prefix")
            .to_owned(),
    );
}

fn mutated_bootstrap_snapshot(mutate: impl FnOnce(&mut Value)) -> ProfileSnapshotV2 {
    let mut snapshot: Value =
        serde_json::from_str(BOOTSTRAP).expect("bootstrap profile must parse");
    mutate(&mut snapshot);
    refresh_snapshot_digest(&mut snapshot);
    parse_profile_snapshot_v2(&snapshot.to_string()).expect("mutated profile must parse")
}

fn desktop_host_entry_mut(snapshot: &mut Value) -> &mut Value {
    snapshot["entries"]
        .as_array_mut()
        .expect("profile entries")
        .iter_mut()
        .find(|entry| entry["entry_id"] == "builtin-desktop-sidecar-local-capability")
        .expect("desktop sidecar host entry")
}

fn desktop_routes_contract_digest(snapshot: &ProfileSnapshotV2) -> String {
    snapshot
        .manifests
        .iter()
        .flat_map(|manifest| &manifest.modules)
        .find(|module| module.module_ref == DESKTOP_SIDECAR_HTTP_ROUTES_MODULE_REF_V2)
        .expect("desktop route contract must exist")
        .contract_digest
        .clone()
}

fn desktop_loader_with(route_definition: PluginDefinitionV2) -> LoaderV2 {
    LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [route_definition, desktop_sidecar_host_definition_v2()],
    )
}

async fn stage_error(loader: LoaderV2, snapshot: ProfileSnapshotV2) -> RuntimeV2Error {
    match loader.stage(snapshot).await {
        Ok(_) => panic!("desktop candidate must be rejected"),
        Err(error) => error,
    }
}

fn desktop_routes_definition(
    snapshot: &ProfileSnapshotV2,
    module: Arc<dyn PluginModuleRuntimeV2>,
) -> PluginDefinitionV2 {
    PluginDefinitionV2 {
        module_ref: DESKTOP_SIDECAR_HTTP_ROUTES_MODULE_REF_V2.to_owned(),
        contract_digest: desktop_routes_contract_digest(snapshot),
        module,
    }
}

struct WrongTypeDesktopHttpRoutes;

#[async_trait]
impl PluginModuleRuntimeV2 for WrongTypeDesktopHttpRoutes {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        context.provide(
            DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2,
            "wrong concrete service type".to_owned(),
        )
    }
}

struct CustomDesktopHttpRoutes {
    contribution_id: &'static str,
    strategy: &'static str,
}

#[async_trait]
impl PluginModuleRuntimeV2 for CustomDesktopHttpRoutes {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        context.provide(
            DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2,
            DesktopSidecarHttpRouteContributionV2 {
                contribution_id: self.contribution_id.to_owned(),
                strategy: self.strategy.to_owned(),
            },
        )
    }
}

#[test]
fn generated_rust_server_catalog_activates_the_production_host_module() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(BOOTSTRAP).expect("bootstrap profile must parse");
        // The host crate supplies HTTP modules; actual worker implementations belong to
        // the server crate. The complete production profile must fail closed without them.
        let error = match LoaderV2::for_target(
            DataPlaneTargetV2::RustServer,
            [
                rust_server_host_definition_v2(),
                rust_server_http_routes_definition_v2(),
            ],
        )
        .stage(snapshot)
        .await
        {
            Ok(_) => panic!("production server must require its worker definitions"),
            Err(error) => error,
        };
        assert!(matches!(
            error,
            RuntimeV2Error::MissingModuleDefinition(module_ref)
                if [
                    "builtin://memstack/rust-server/skill-evolution-worker",
                    "builtin://memstack/rust-server/channel-outbox-worker",
                    "builtin://memstack/rust-server/cron-scheduler-worker",
                ].contains(&module_ref.as_str())
        ));
    });
}

#[test]
fn generated_desktop_sidecar_catalog_activates_the_local_capability_module() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(BOOTSTRAP).expect("bootstrap profile must parse");
        let generation = LoaderV2::for_target(
            DataPlaneTargetV2::DesktopSidecar,
            [
                desktop_sidecar_host_definition_v2(),
                desktop_sidecar_http_routes_definition_v2(),
            ],
        )
        .stage(snapshot)
        .await
        .expect("desktop sidecar target must activate");

        let descriptor = generation
            .resolve::<TargetHostDescriptorV2>(DESKTOP_SIDECAR_HOST_SERVICE_V2, &root_scope(), None)
            .expect("desktop sidecar descriptor must be provided");
        assert_eq!(descriptor.target, "desktop-sidecar");
        assert_eq!(descriptor.strategy, "native-local-capability");
        let routes = generation
            .resolve::<DesktopSidecarHttpRouteContributionV2>(
                DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2,
                &root_scope(),
                None,
            )
            .expect("desktop sidecar HTTP route contribution must be provided");
        assert_eq!(routes.contribution_id, "memstack-desktop-local-api.v1");
        assert_eq!(routes.strategy, "axum-host-router");
        assert_eq!(generation.phases().len(), 2);
    });
}

#[test]
fn desktop_host_requires_an_explicit_routes_inject() {
    block_on(async {
        let snapshot = mutated_bootstrap_snapshot(|snapshot| {
            desktop_host_entry_mut(snapshot)["inject"] = json!({});
        });
        let error = stage_error(
            desktop_loader_with(desktop_sidecar_http_routes_definition_v2()),
            snapshot,
        )
        .await;

        assert_eq!(error.code(), "missing_required_inject");
    });
}

#[test]
fn desktop_host_rejects_an_inject_without_a_provider_entry() {
    block_on(async {
        let snapshot = mutated_bootstrap_snapshot(|snapshot| {
            let entries = snapshot["entries"].as_array_mut().expect("profile entries");
            let provider_index = entries
                .iter()
                .position(|entry| entry["entry_id"] == "builtin-desktop-sidecar-http-routes")
                .expect("desktop sidecar route provider entry");
            entries.remove(provider_index);
            entries
                .iter_mut()
                .find(|entry| entry["entry_id"] == "builtin-desktop-sidecar-local-capability")
                .expect("desktop sidecar host entry")["parent_entry_id"] = Value::Null;
        });
        let error = stage_error(
            desktop_loader_with(desktop_sidecar_http_routes_definition_v2()),
            snapshot,
        )
        .await;

        assert_eq!(error.code(), "missing_inject_provider");
    });
}

#[test]
fn desktop_host_rejects_a_route_provider_with_the_wrong_concrete_type() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(BOOTSTRAP).expect("bootstrap profile must parse");
        let routes = desktop_routes_definition(&snapshot, Arc::new(WrongTypeDesktopHttpRoutes));
        let error = stage_error(desktop_loader_with(routes), snapshot).await;

        assert_eq!(error.code(), "service_type_mismatch");
    });
}

#[test]
fn desktop_host_rejects_an_unknown_route_contribution_id() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(BOOTSTRAP).expect("bootstrap profile must parse");
        let routes = desktop_routes_definition(
            &snapshot,
            Arc::new(CustomDesktopHttpRoutes {
                contribution_id: "unknown-desktop-route-set.v1",
                strategy: DESKTOP_SIDECAR_HTTP_ROUTE_STRATEGY_V2,
            }),
        );
        let error = stage_error(desktop_loader_with(routes), snapshot).await;

        assert_eq!(
            error,
            RuntimeV2Error::Module(
                "desktop sidecar generation declares an unknown local route set".to_owned()
            )
        );
    });
}

#[test]
fn desktop_host_rejects_an_incompatible_route_strategy() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(BOOTSTRAP).expect("bootstrap profile must parse");
        let routes = desktop_routes_definition(
            &snapshot,
            Arc::new(CustomDesktopHttpRoutes {
                contribution_id: DESKTOP_SIDECAR_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2,
                strategy: "unsupported-router",
            }),
        );
        let error = stage_error(desktop_loader_with(routes), snapshot).await;

        assert_eq!(
            error,
            RuntimeV2Error::Module(
                "desktop sidecar generation declares an incompatible local route strategy"
                    .to_owned()
            )
        );
    });
}
