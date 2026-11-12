//! First-party native factory registered with the ordinary V2 generation loader.
use agistack_plugin_host::protocol_v2::{
    ContextV2, PluginDefinitionV2, PluginModuleRuntimeV2, RuntimeV2Error,
    PLUGIN_MODULE_CATALOG_V2_JSON,
};
use async_trait::async_trait;
use serde_json::Value;
use std::{collections::BTreeMap, sync::Arc};

pub(super) const MODULE_REF: &str = "builtin://memstack/computer-use/native";
pub(super) const SERVICE: &str = "service:desktop-sidecar.computer-use";
pub(super) const VERSION: &str = "1.0.0";

pub(super) struct ComputerUseFactoryV2;
struct ComputerUseModuleV2;

#[async_trait]
impl PluginModuleRuntimeV2 for ComputerUseModuleV2 {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        if config.get("strategy").and_then(Value::as_str) != Some("managed-native-device") {
            return Err(RuntimeV2Error::Module(
                "computer-use strategy is invalid".into(),
            ));
        }
        context.provide(SERVICE, ComputerUseFactoryV2)
    }
}

pub(in crate::local_runtime) fn definition() -> Result<PluginDefinitionV2, String> {
    let catalog: Value =
        serde_json::from_str(PLUGIN_MODULE_CATALOG_V2_JSON).map_err(|error| error.to_string())?;
    let digest = catalog["modules"]
        .as_array()
        .and_then(|modules| {
            modules
                .iter()
                .find(|module| module["module_ref"] == MODULE_REF)
        })
        .and_then(|module| module["contract_digest"].as_str())
        .ok_or("computer-use module catalog unavailable")?;
    Ok(PluginDefinitionV2 {
        module_ref: MODULE_REF.into(),
        contract_digest: digest.into(),
        module: Arc::new(ComputerUseModuleV2),
    })
}
