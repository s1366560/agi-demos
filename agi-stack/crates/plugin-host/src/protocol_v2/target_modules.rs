//! Builtin target-host modules backed by the generated protocol-v2 catalog.

use std::{collections::BTreeMap, sync::Arc};

use async_trait::async_trait;
use serde_json::Value;

use super::{ContextV2, PluginDefinitionV2, PluginModuleRuntimeV2, RuntimeV2Error};

pub const RUST_SERVER_HOST_MODULE_REF_V2: &str = "builtin://memstack/rust-server/generation-host";
pub const RUST_SERVER_HTTP_ROUTES_MODULE_REF_V2: &str =
    "builtin://memstack/rust-server/http-routes";
pub const DESKTOP_SIDECAR_HOST_MODULE_REF_V2: &str =
    "builtin://memstack/desktop-sidecar/local-capability";
pub const RUST_SERVER_HOST_SERVICE_V2: &str = "service:rust-server.runtime-descriptor";
pub const RUST_SERVER_HTTP_ROUTES_SERVICE_V2: &str = "service:rust-server.http-route-contribution";
pub const DESKTOP_SIDECAR_HOST_SERVICE_V2: &str = "service:desktop-sidecar.local-capability";
pub const RUST_SERVER_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2: &str = "memstack-rust-default-api.v1";
pub const RUST_SERVER_HTTP_ROUTE_STRATEGY_V2: &str = "axum-host-router";

const RUST_SERVER_HOST_CONTRACT_DIGEST_V2: &str =
    "sha256:8848f378b02460e0ba80ef8708a65e2f30f789033c7eb3ccf7d25e5460fa6e7e";
const RUST_SERVER_HTTP_ROUTES_CONTRACT_DIGEST_V2: &str =
    "sha256:75443a63ac79d996d7bcba1a2015ab84320702e0157897cbd62970669a79d2b2";
const DESKTOP_SIDECAR_HOST_CONTRACT_DIGEST_V2: &str =
    "sha256:417fd72b2a8177362bf2362158c113ed423ff84b1106634b271cddf17dbfbf46";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TargetHostDescriptorV2 {
    pub target: String,
    pub strategy: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RustServerHttpRouteContributionV2 {
    pub contribution_id: String,
    pub strategy: String,
}

pub struct RustServerHostModuleV2;

pub struct RustServerHttpRoutesModuleV2;

#[async_trait]
impl PluginModuleRuntimeV2 for RustServerHostModuleV2 {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        let strategy = required_strategy_v2(config)?;
        context.provide(
            RUST_SERVER_HOST_SERVICE_V2,
            TargetHostDescriptorV2 {
                target: "rust-server".to_owned(),
                strategy,
            },
        )?;
        Ok(())
    }
}

#[async_trait]
impl PluginModuleRuntimeV2 for RustServerHttpRoutesModuleV2 {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        let contribution_id = config
            .get("contribution_id")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .ok_or_else(|| {
                RuntimeV2Error::Module(
                    "rust server HTTP route contribution_id is required".to_owned(),
                )
            })?;
        let strategy = required_strategy_v2(config)?;
        context.provide(
            RUST_SERVER_HTTP_ROUTES_SERVICE_V2,
            RustServerHttpRouteContributionV2 {
                contribution_id,
                strategy,
            },
        )?;
        Ok(())
    }
}

pub struct DesktopSidecarHostModuleV2;

#[async_trait]
impl PluginModuleRuntimeV2 for DesktopSidecarHostModuleV2 {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        let strategy = required_strategy_v2(config)?;
        context.provide(
            DESKTOP_SIDECAR_HOST_SERVICE_V2,
            TargetHostDescriptorV2 {
                target: "desktop-sidecar".to_owned(),
                strategy,
            },
        )?;
        Ok(())
    }
}

#[must_use]
pub fn rust_server_host_definition_v2() -> PluginDefinitionV2 {
    PluginDefinitionV2 {
        module_ref: RUST_SERVER_HOST_MODULE_REF_V2.to_owned(),
        contract_digest: RUST_SERVER_HOST_CONTRACT_DIGEST_V2.to_owned(),
        module: Arc::new(RustServerHostModuleV2),
    }
}

#[must_use]
pub fn rust_server_http_routes_definition_v2() -> PluginDefinitionV2 {
    PluginDefinitionV2 {
        module_ref: RUST_SERVER_HTTP_ROUTES_MODULE_REF_V2.to_owned(),
        contract_digest: RUST_SERVER_HTTP_ROUTES_CONTRACT_DIGEST_V2.to_owned(),
        module: Arc::new(RustServerHttpRoutesModuleV2),
    }
}

#[must_use]
pub fn desktop_sidecar_host_definition_v2() -> PluginDefinitionV2 {
    PluginDefinitionV2 {
        module_ref: DESKTOP_SIDECAR_HOST_MODULE_REF_V2.to_owned(),
        contract_digest: DESKTOP_SIDECAR_HOST_CONTRACT_DIGEST_V2.to_owned(),
        module: Arc::new(DesktopSidecarHostModuleV2),
    }
}

fn required_strategy_v2(config: &BTreeMap<String, Value>) -> Result<String, RuntimeV2Error> {
    config
        .get("strategy")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| RuntimeV2Error::Module("target host strategy is required".to_owned()))
}
