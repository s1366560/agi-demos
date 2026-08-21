//! Strict v2 wire protocol and executor-neutral generation runtime.

mod distribution;
mod generated;
mod reconciler;
mod runtime;

use std::collections::{BTreeMap, BTreeSet};

pub use distribution::{
    parse_control_plane_distribution_v2, ControlPlaneDistributionV2, PluginGenerationDescriptorV2,
};
pub use generated::*;
pub use reconciler::PluginSnapshotReconcilerV2;
pub use runtime::{
    project_snapshot_entries_v2, ContextV2, FiberPhaseV2, FiberV2, GenerationLeaseV2,
    GenerationManagerV2, LoaderV2, PluginDefinitionV2, PluginModuleRuntimeV2, RuntimeGenerationV2,
    RuntimeV2Error,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use thiserror::Error;

pub const PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL_V2: &str = "types.memstack.ai/plugin.profile.v2";

#[derive(Debug, Error, PartialEq, Eq)]
pub enum PluginProtocolV2Error {
    #[error("plugin snapshot schema_version must be 2; v1 is not accepted")]
    IncompatibleSchemaVersion,
    #[error("snapshot JSON is invalid: {0}")]
    InvalidJson(String),
    #[error("snapshot shape is invalid: {0}")]
    InvalidShape(String),
    #[error("snapshot digest mismatch: expected {expected}")]
    DigestMismatch { expected: String },
    #[error("duplicate plugin_id: {0}")]
    DuplicatePluginId(String),
    #[error("duplicate entry_id: {0}")]
    DuplicateEntryId(String),
    #[error("entry {entry_id} references missing plugin {plugin_id}")]
    MissingManifest { entry_id: String, plugin_id: String },
    #[error("entry {entry_id} references a module outside plugin {plugin_id}")]
    MissingModule { entry_id: String, plugin_id: String },
    #[error("entry {entry_id} has missing parent {parent_id}")]
    MissingParent { entry_id: String, parent_id: String },
    #[error("entry parent cycle includes {0}")]
    EntryCycle(String),
    #[error("entry {0} has an inconsistent scope")]
    InvalidScope(String),
    #[error("entry {entry_id} scope is outside parent {parent_id}")]
    InvalidParentScope { entry_id: String, parent_id: String },
    #[error("entry {entry_id} targets are outside parent {parent_id}")]
    InvalidParentTargets { entry_id: String, parent_id: String },
    #[error("plugin distribution is inconsistent: {0}")]
    DistributionMismatch(String),
}

/// Parse a strict v2 snapshot and independently verify its RFC 8785 digest.
pub fn parse_profile_snapshot_v2(raw: &str) -> Result<ProfileSnapshotV2, PluginProtocolV2Error> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| PluginProtocolV2Error::InvalidJson(error.to_string()))?;
    if value.get("schema_version").and_then(Value::as_u64) != Some(2) {
        return Err(PluginProtocolV2Error::IncompatibleSchemaVersion);
    }
    let snapshot: ProfileSnapshotV2 = serde_json::from_value(value.clone())
        .map_err(|error| PluginProtocolV2Error::InvalidShape(error.to_string()))?;
    validate_snapshot_semantics(&snapshot)?;
    let expected = snapshot_digest(value)?;
    if snapshot.digest != expected {
        return Err(PluginProtocolV2Error::DigestMismatch { expected });
    }
    Ok(snapshot)
}

fn snapshot_digest(mut value: Value) -> Result<String, PluginProtocolV2Error> {
    let object = value
        .as_object_mut()
        .ok_or_else(|| PluginProtocolV2Error::InvalidShape("snapshot must be an object".into()))?;
    object.remove("digest");
    let canonical = serde_jcs::to_vec(&value)
        .map_err(|error| PluginProtocolV2Error::InvalidShape(error.to_string()))?;
    Ok(format!("{:x}", Sha256::digest(canonical)))
}

fn validate_snapshot_semantics(snapshot: &ProfileSnapshotV2) -> Result<(), PluginProtocolV2Error> {
    if snapshot.schema_version != 2 {
        return Err(PluginProtocolV2Error::IncompatibleSchemaVersion);
    }
    let mut manifest_by_id = BTreeMap::new();
    for manifest in &snapshot.manifests {
        if manifest.schema_version != 2 {
            return Err(PluginProtocolV2Error::IncompatibleSchemaVersion);
        }
        for module in &manifest.modules {
            let has_duplicate_target = module
                .targets
                .iter()
                .enumerate()
                .any(|(index, target)| module.targets[..index].contains(target));
            if module.targets.is_empty() || has_duplicate_target {
                return Err(PluginProtocolV2Error::InvalidShape(format!(
                    "module {} targets must be non-empty and unique",
                    module.module_ref
                )));
            }
        }
        if manifest_by_id
            .insert(manifest.plugin_id.clone(), manifest)
            .is_some()
        {
            return Err(PluginProtocolV2Error::DuplicatePluginId(
                manifest.plugin_id.clone(),
            ));
        }
    }
    let mut entry_by_id = BTreeMap::new();
    for entry in &snapshot.entries {
        if entry_by_id.insert(entry.entry_id.clone(), entry).is_some() {
            return Err(PluginProtocolV2Error::DuplicateEntryId(
                entry.entry_id.clone(),
            ));
        }
    }
    for entry in &snapshot.entries {
        let manifest = manifest_by_id.get(&entry.plugin_ref).ok_or_else(|| {
            PluginProtocolV2Error::MissingManifest {
                entry_id: entry.entry_id.clone(),
                plugin_id: entry.plugin_ref.clone(),
            }
        })?;
        if !manifest
            .modules
            .iter()
            .any(|module| module.module_ref == entry.module_ref)
        {
            return Err(PluginProtocolV2Error::MissingModule {
                entry_id: entry.entry_id.clone(),
                plugin_id: entry.plugin_ref.clone(),
            });
        }
        validate_scope(&entry.entry_id, &entry.scope)?;
        if let Some(parent_id) = &entry.parent_entry_id {
            let parent =
                entry_by_id
                    .get(parent_id)
                    .ok_or_else(|| PluginProtocolV2Error::MissingParent {
                        entry_id: entry.entry_id.clone(),
                        parent_id: parent_id.clone(),
                    })?;
            if !scope_contains(&parent.scope, &entry.scope) {
                return Err(PluginProtocolV2Error::InvalidParentScope {
                    entry_id: entry.entry_id.clone(),
                    parent_id: parent_id.clone(),
                });
            }
            let child_module = manifest
                .modules
                .iter()
                .find(|module| module.module_ref == entry.module_ref)
                .ok_or_else(|| PluginProtocolV2Error::MissingModule {
                    entry_id: entry.entry_id.clone(),
                    plugin_id: entry.plugin_ref.clone(),
                })?;
            let parent_manifest = manifest_by_id.get(&parent.plugin_ref).ok_or_else(|| {
                PluginProtocolV2Error::MissingManifest {
                    entry_id: parent.entry_id.clone(),
                    plugin_id: parent.plugin_ref.clone(),
                }
            })?;
            let parent_module = parent_manifest
                .modules
                .iter()
                .find(|module| module.module_ref == parent.module_ref)
                .ok_or_else(|| PluginProtocolV2Error::MissingModule {
                    entry_id: parent.entry_id.clone(),
                    plugin_id: parent.plugin_ref.clone(),
                })?;
            if !child_module
                .targets
                .iter()
                .all(|target| parent_module.targets.contains(target))
            {
                return Err(PluginProtocolV2Error::InvalidParentTargets {
                    entry_id: entry.entry_id.clone(),
                    parent_id: parent_id.clone(),
                });
            }
        }
    }
    validate_parent_tree(&entry_by_id)
}

fn validate_scope(entry_id: &str, scope: &ScopeV2) -> Result<(), PluginProtocolV2Error> {
    let valid = match scope.kind {
        ScopeKindV2::Root => {
            scope.tenant_id.is_none() && scope.project_id.is_none() && scope.session_id.is_none()
        }
        ScopeKindV2::Tenant => {
            scope.tenant_id.is_some() && scope.project_id.is_none() && scope.session_id.is_none()
        }
        ScopeKindV2::Project => {
            scope.tenant_id.is_some() && scope.project_id.is_some() && scope.session_id.is_none()
        }
        ScopeKindV2::Session => {
            scope.tenant_id.is_some() && scope.project_id.is_some() && scope.session_id.is_some()
        }
    };
    if valid {
        Ok(())
    } else {
        Err(PluginProtocolV2Error::InvalidScope(entry_id.to_owned()))
    }
}

fn validate_parent_tree(
    entries: &BTreeMap<String, &ProfileEntryV2>,
) -> Result<(), PluginProtocolV2Error> {
    fn visit(
        entry_id: &str,
        entries: &BTreeMap<String, &ProfileEntryV2>,
        visiting: &mut BTreeSet<String>,
        visited: &mut BTreeSet<String>,
    ) -> Result<(), PluginProtocolV2Error> {
        if visited.contains(entry_id) {
            return Ok(());
        }
        if !visiting.insert(entry_id.to_owned()) {
            return Err(PluginProtocolV2Error::EntryCycle(entry_id.to_owned()));
        }
        if let Some(parent_id) = entries[entry_id].parent_entry_id.as_deref() {
            visit(parent_id, entries, visiting, visited)?;
        }
        visiting.remove(entry_id);
        visited.insert(entry_id.to_owned());
        Ok(())
    }

    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    for entry_id in entries.keys() {
        visit(entry_id, entries, &mut visiting, &mut visited)?;
    }
    Ok(())
}

pub(crate) fn scope_rank(scope: &ScopeV2) -> u8 {
    match scope.kind {
        ScopeKindV2::Root => 0,
        ScopeKindV2::Tenant => 1,
        ScopeKindV2::Project => 2,
        ScopeKindV2::Session => 3,
    }
}

pub(crate) fn scope_contains(parent: &ScopeV2, child: &ScopeV2) -> bool {
    if scope_rank(parent) > scope_rank(child) {
        return false;
    }
    [
        (&parent.tenant_id, &child.tenant_id),
        (&parent.project_id, &child.project_id),
        (&parent.session_id, &child.session_id),
    ]
    .into_iter()
    .all(|(parent_value, child_value)| {
        parent_value
            .as_ref()
            .is_none_or(|value| child_value.as_ref() == Some(value))
    })
}
