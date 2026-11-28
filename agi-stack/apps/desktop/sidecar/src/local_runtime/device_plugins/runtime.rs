//! A private, bounded Wasm generation for one verified package. Never published to the cloud.
use super::super::local_plugin_tool_host_v2::OperationReleaseGuardV2;
use super::*;
use crate::local_plugin_installations_v2::InstalledBundleV2;
use agistack_plugin_host::{
    protocol_v2::{
        signed_archive::VerifiedBundleArchiveV2,
        wasm_runtime::{
            WasmOperationAuthorityV2, WasmOperationV2, WasmToolAttributionV2, WasmToolSetV2,
            WASM_TOOL_SET_SERVICE_V2,
        },
        ProfileSnapshotV2,
    },
    DataPlaneTargetV2, LoaderV2, PluginSnapshotReconcilerV2,
};
use std::collections::BTreeMap;

pub(super) struct Prepared {
    runtime: PluginSnapshotReconcilerV2,
    sets: BTreeMap<String, Arc<WasmToolSetV2>>,
}

impl Prepared {
    pub async fn stage(scope: &ScopeV2, archive: VerifiedBundleArchiveV2) -> Result<Self, String> {
        let base = ProfileSnapshotV2 {
            schema_version: 2,
            profile_id: "device-package".into(),
            generation: 0,
            entries: vec![],
            manifests: vec![],
            digest: String::new(),
        };
        let (snapshot, _, archives) = packages::compose(
            &base,
            vec![InstalledBundleV2 {
                scope: scope.clone(),
                archive,
            }],
            1,
        )?;
        let loader = LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, [])
            .with_verified_archives(archives);
        let runtime = PluginSnapshotReconcilerV2::new_with_baseline(loader, snapshot)
            .await
            .map_err(|e| e.to_string())?;
        let sets = Self::tools(&runtime, scope).await;
        match sets {
            Ok(sets) => Ok(Self { runtime, sets }),
            Err(error) => {
                runtime.manager().close().await;
                Err(error)
            }
        }
    }

    async fn tools(
        runtime: &PluginSnapshotReconcilerV2,
        scope: &ScopeV2,
    ) -> Result<BTreeMap<String, Arc<WasmToolSetV2>>, String> {
        let lease = runtime.manager().acquire().map_err(|e| e.to_string())?;
        let collect = || {
            let generation = lease.generation().map_err(|e| e.to_string())?;
            let mut tools = BTreeMap::new();
            for entry in generation
                .snapshot
                .entries
                .iter()
                .filter(|e| e.enabled && e.scope == *scope)
            {
                let name = entry
                    .config
                    .get("tool_name")
                    .and_then(Value::as_str)
                    .ok_or("device_plugin_tool_missing")?;
                let set = generation
                    .resolve::<WasmToolSetV2>(
                        WASM_TOOL_SET_SERVICE_V2,
                        scope,
                        Some(&entry.entry_id),
                    )
                    .map_err(|e| e.to_string())?;
                if tools.insert(name.into(), set).is_some() {
                    return Err("device_plugin_tool_conflict".into());
                }
            }
            if tools.is_empty() {
                return Err("device_plugin_tool_missing".into());
            }
            Ok(tools)
        };
        let result = collect();
        lease.release().await.map_err(|e| e.to_string())?;
        result
    }

    pub fn names(&self) -> Vec<String> {
        self.sets.keys().cloned().collect()
    }
    pub async fn close(self) {
        self.runtime.manager().close().await;
    }

    pub async fn call(&self, authority: Arc<Authority>, input: Value) -> Result<Value, String> {
        let set = self
            .sets
            .get(&authority.tool)
            .ok_or("device_plugin_tool_missing")?;
        let lease = self
            .runtime
            .manager()
            .acquire()
            .map_err(|e| e.to_string())?;
        let operation = OperationReleaseGuardV2::new(WasmOperationV2::new(
            lease,
            authority.scope.clone(),
            uuid::Uuid::new_v4().to_string(),
            Some(authority.clone()),
        ));
        let tools = set.prepare(&operation).await;
        let result = match tools.as_slice() {
            [tool] => tool.invoke(input).await.map_err(|e| e.to_string()),
            _ => Err("device_plugin_grant_denied".into()),
        };
        operation.close().await.map_err(|e| e.to_string())?;
        authority
            .device
            .check(
                &authority.owner,
                &authority.selection.reference,
                &authority.selection.generation_id,
                &authority.selection.approved_permissions,
                Some(&authority.selection.grant_id),
            )
            .await?;
        authority.current()?;
        result
    }
}

pub(super) struct Authority {
    pub state: Arc<LocalRuntimeState>,
    pub scope: ScopeV2,
    pub owner: CloudOwner,
    pub device: Device,
    pub selection: Selection,
    pub executable: agistack_plugin_host::protocol_v2::BundleReferenceV2,
    pub tool: String,
}
impl Authority {
    fn current(&self) -> Result<(), String> {
        self.owner
            .fence(|| require_generation(&self.state, &self.selection.generation_id))
    }
}
#[async_trait::async_trait]
impl WasmOperationAuthorityV2 for Authority {
    async fn authorize(&self, operation: &WasmOperationV2, tool: &WasmToolAttributionV2) -> bool {
        if self.current().is_err()
            || operation.scope() != &self.scope
            || tool.entry_scope != self.scope
            || tool.bundle != self.executable
            || tool.tool_name != self.tool
            || !self
                .selection
                .approved_permissions
                .contains("tools.execute")
        {
            return false;
        }
        self.device
            .check(
                &self.owner,
                &self.selection.reference,
                &self.selection.generation_id,
                &self.selection.approved_permissions,
                Some(&self.selection.grant_id),
            )
            .await
            .is_ok()
            && self.current().is_ok()
    }
}
