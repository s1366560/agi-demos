use agistack_plugin_host::{
    desktop_sidecar_host_definition_v2, parse_profile_snapshot_v2, rust_server_host_definition_v2,
    rust_server_http_routes_definition_v2, DataPlaneTargetV2, LoaderV2,
    RustServerHttpRouteContributionV2, ScopeKindV2, ScopeV2, TargetHostDescriptorV2,
    DESKTOP_SIDECAR_HOST_SERVICE_V2, RUST_SERVER_HOST_SERVICE_V2,
    RUST_SERVER_HTTP_ROUTES_SERVICE_V2,
};
use futures::executor::block_on;

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

#[test]
fn generated_rust_server_catalog_activates_the_production_host_module() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(BOOTSTRAP).expect("bootstrap profile must parse");
        let generation = LoaderV2::for_target(
            DataPlaneTargetV2::RustServer,
            [
                rust_server_host_definition_v2(),
                rust_server_http_routes_definition_v2(),
            ],
        )
        .stage(snapshot)
        .await
        .expect("rust server target must activate");

        let descriptor = generation
            .resolve::<TargetHostDescriptorV2>(RUST_SERVER_HOST_SERVICE_V2, &root_scope(), None)
            .expect("rust server descriptor must be provided");
        assert_eq!(descriptor.target, "rust-server");
        assert_eq!(descriptor.strategy, "generated-catalog-bootstrap");
        let routes = generation
            .resolve::<RustServerHttpRouteContributionV2>(
                RUST_SERVER_HTTP_ROUTES_SERVICE_V2,
                &root_scope(),
                None,
            )
            .expect("rust server HTTP route contribution must be provided");
        assert_eq!(routes.contribution_id, "memstack-rust-default-api.v1");
        assert_eq!(routes.strategy, "axum-host-router");
        assert_eq!(generation.phases().len(), 2);
    });
}

#[test]
fn generated_desktop_sidecar_catalog_activates_the_local_capability_module() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(BOOTSTRAP).expect("bootstrap profile must parse");
        let generation = LoaderV2::for_target(
            DataPlaneTargetV2::DesktopSidecar,
            [desktop_sidecar_host_definition_v2()],
        )
        .stage(snapshot)
        .await
        .expect("desktop sidecar target must activate");

        let descriptor = generation
            .resolve::<TargetHostDescriptorV2>(DESKTOP_SIDECAR_HOST_SERVICE_V2, &root_scope(), None)
            .expect("desktop sidecar descriptor must be provided");
        assert_eq!(descriptor.target, "desktop-sidecar");
        assert_eq!(descriptor.strategy, "native-local-capability");
        assert_eq!(generation.phases().len(), 1);
    });
}
