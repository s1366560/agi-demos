//! Signed, generation-local WASM ToolSets. Optional native execution, never an implicit grant.

mod host;
mod operation;
pub use operation::{
    AuthorizedWasmToolV2, WasmOperationAuthorityV2, WasmOperationV2, WasmToolAttributionV2,
    WasmToolSetV2,
};

use super::{
    contract_runtime::PluginModuleCatalogEntryV2,
    signed_archive::{VerifiedBundleArchiveV2, VerifiedWasmArtifactV2},
    ContextV2, DataPlaneTargetV2, PluginDefinitionV2, PluginModuleRuntimeV2, ProfileEntryV2,
    ProfileSnapshotV2, RuntimeV2Error,
};
use async_trait::async_trait;
use serde_json::Value;
use std::{
    collections::BTreeMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

pub const WASM_TOOL_SET_SERVICE_V2: &str = "service:wasm-tool-set";
pub const WASM_SCORE_ABI_V1: &str = "memstack.wasm.score-json-utf8.v1";

type ResolvedExternalModulesV2 = (
    BTreeMap<String, PluginModuleCatalogEntryV2>,
    BTreeMap<String, PluginDefinitionV2>,
);

pub(super) fn failure(message: impl Into<String>) -> RuntimeV2Error {
    RuntimeV2Error::Module(message.into())
}

pub(super) fn admit_external_definitions(
    snapshot: &ProfileSnapshotV2,
    target: &DataPlaneTargetV2,
    mut catalog: BTreeMap<String, PluginModuleCatalogEntryV2>,
    definitions: &BTreeMap<String, PluginDefinitionV2>,
    archives: &[VerifiedBundleArchiveV2],
) -> Result<ResolvedExternalModulesV2, RuntimeV2Error> {
    let mut resolved = definitions.clone();
    for manifest in &snapshot.manifests {
        for module in &manifest.modules {
            if !module.targets.contains(target) || catalog.contains_key(&module.module_ref) {
                continue;
            }
            if target != &DataPlaneTargetV2::DesktopSidecar
                && target != &DataPlaneTargetV2::RustServer
            {
                return Err(failure(
                    "external WASM factory requires a native Rust target",
                ));
            }
            if resolved.contains_key(&module.module_ref) {
                return Err(failure("external preloaded definition is forbidden"));
            }
            let owners: Vec<_> = archives
                .iter()
                .filter(|archive| {
                    archive
                        .manifest()
                        .manifests
                        .iter()
                        .any(|item| item.plugin_id == manifest.plugin_id)
                })
                .collect();
            if owners.is_empty() {
                return Err(RuntimeV2Error::MissingTargetCatalog(
                    module.module_ref.clone(),
                ));
            }
            if owners.len() != 1 {
                return Err(failure(
                    "external module requires exactly one verified archive owner",
                ));
            }
            let artifact = owners[0]
                .wasm_artifact(&manifest.plugin_id, &module.module_ref, target.clone())
                .map_err(|error| failure(error.to_string()))?;
            if artifact.manifest() != manifest || artifact.module() != module {
                return Err(failure("snapshot module differs from signed archive"));
            }
            let entries: Vec<_> = snapshot
                .entries
                .iter()
                .filter(|entry| {
                    entry.plugin_ref == manifest.plugin_id && entry.module_ref == module.module_ref
                })
                .collect();
            for entry in &entries {
                if entry.permissions.iter().any(|permission| {
                    !manifest.permissions.contains(permission)
                        || !owners[0].approved_permissions().contains(permission)
                }) {
                    return Err(failure(
                        "entry permissions exceed verified archive approval",
                    ));
                }
            }
            let definition = create_verified_wasm_definition_v2(artifact, snapshot, entries)?;
            catalog.insert(
                module.module_ref.clone(),
                PluginModuleCatalogEntryV2 {
                    plugin_id: manifest.plugin_id.clone(),
                    plugin_version: manifest.version.clone(),
                    module_ref: module.module_ref.clone(),
                    entrypoint: module.entrypoint.clone(),
                    artifact_digest: module.artifact.digest.clone(),
                    artifact_source: module.artifact.source.clone(),
                    targets: module.targets.clone(),
                    contract: module.contract.clone(),
                    contract_digest: module.contract_digest.clone(),
                },
            );
            resolved.insert(module.module_ref.clone(), definition);
        }
    }
    Ok((catalog, resolved))
}

/// This constructor consumes an unforgeable, borrowed archive artifact. It does not authorize tools.
fn create_verified_wasm_definition_v2(
    artifact: VerifiedWasmArtifactV2<'_>,
    snapshot: &ProfileSnapshotV2,
    entries: Vec<&ProfileEntryV2>,
) -> Result<PluginDefinitionV2, RuntimeV2Error> {
    let contract = &artifact.module().contract;
    if artifact.module().entrypoint != "score"
        || !artifact
            .manifest()
            .permissions
            .iter()
            .any(|p| p == "tools.execute")
        || !contract.services.requires.is_empty()
        || contract.services.provides.len() != 1
        || contract.services.provides[0].service != WASM_TOOL_SET_SERVICE_V2
        || contract.services.provides[0].version != "1.0.0"
        || !contract.events.emits.is_empty()
        || !contract.events.handles.is_empty()
    {
        return Err(failure("unsupported native WASM ToolSet contract"));
    }
    let module = WasmModule {
        bytes: artifact.bytes().to_vec(),
        manifest: artifact.manifest().clone(),
        reference: artifact.reference().clone(),
        module: artifact.module().clone(),
        snapshot: (
            snapshot.profile_id.clone(),
            snapshot.generation,
            snapshot.digest.clone(),
        ),
        entries: entries
            .into_iter()
            .map(|entry| (entry.entry_id.clone(), entry.clone()))
            .collect(),
    };
    Ok(PluginDefinitionV2 {
        module_ref: artifact.module().module_ref.clone(),
        contract_digest: artifact.module().contract_digest.clone(),
        module: Arc::new(module),
    })
}

struct WasmModule {
    bytes: Vec<u8>,
    manifest: super::PluginManifestV2,
    reference: super::BundleReferenceV2,
    module: super::PluginModuleV2,
    snapshot: (String, u64, String),
    entries: BTreeMap<String, ProfileEntryV2>,
}

#[async_trait]
impl PluginModuleRuntimeV2 for WasmModule {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        let name = config
            .get("tool_name")
            .and_then(Value::as_str)
            .ok_or_else(|| failure("tool_name required"))?;
        if name.is_empty()
            || name.len() > 128
            || !name
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        {
            return Err(failure("invalid tool_name"));
        }
        let entry = self
            .entries
            .get(context.entry_id())
            .ok_or_else(|| failure("entry is absent from admitted snapshot"))?;
        let limits = host::Limits::new(&self.manifest.quotas, &entry.quotas)?;
        if !entry
            .permissions
            .iter()
            .any(|permission| permission == "tools.execute")
        {
            return Err(failure("entry must explicitly request tools.execute"));
        }
        let bytes = self.bytes.clone();
        let host = host::blocking(move || host::ScoreHost::compile(&bytes, limits)).await?;
        let host = Arc::new(host);
        let active = Arc::new(AtomicBool::new(true));
        let set = WasmToolSetV2::new(
            Arc::clone(&host),
            Arc::clone(&active),
            WasmToolAttributionV2 {
                bundle: self.reference.clone(),
                plugin_id: self.manifest.plugin_id.clone(),
                plugin_version: self.manifest.version.clone(),
                module_ref: self.module.module_ref.clone(),
                artifact_digest: self.module.artifact.digest.clone(),
                artifact_source: self.module.artifact.source.clone(),
                entry_id: context.entry_id().to_owned(),
                tool_name: name.to_owned(),
                entry_scope: context.scope().clone(),
                profile_id: self.snapshot.0.clone(),
                generation: self.snapshot.1,
                snapshot_digest: self.snapshot.2.clone(),
            },
        );
        context.effect(
            "signed-wasm-tool-set",
            Box::new(move || {
                Box::pin(async move {
                    active.store(false, Ordering::Release);
                    host.interrupt();
                    Ok(())
                })
            }),
        )?;
        context.provide(WASM_TOOL_SET_SERVICE_V2, set)
    }
}
