//! Scope-private ordinary instance configuration over the existing V2 snapshot store.

use agistack_plugin_host::protocol_v2::{
    validate_snapshot_target_v2, BundleReferenceV2, DataPlaneTargetV2, DesiredBundleSetV2,
    PluginModuleV2, ProfileEntryV2, ProfileLayerKindV2, ProfileLayerV2, ProfileSnapshotV2,
    ProfileSourceReferenceV2, ProfileSourceV2, ScopeKindV2, ScopeV2,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

use crate::plugin_snapshots_v2::LocalProfileConfigurationV2;

#[cfg(test)]
mod tests;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct InstanceChangeV2 {
    pub(crate) entry_id: String,
    pub(crate) enabled: Option<bool>,
    pub(crate) config: Option<BTreeMap<String, Value>>,
    pub(crate) replacement: Option<ReplacementV2>,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ReplacementV2 {
    plugin_id: String,
    module_ref: String,
}

pub(crate) fn authority(scope: &ScopeV2) -> Result<String, String> {
    digest(
        &json!({"protocol":"local-plugin-profile-v2", "scope":scope}),
        false,
    )
}

fn digest(value: &Value, remove_digest: bool) -> Result<String, String> {
    let mut value = value.clone();
    if remove_digest {
        value
            .as_object_mut()
            .ok_or("configuration must be an object")?
            .remove("digest");
    }
    Ok(format!(
        "sha256:{:x}",
        Sha256::digest(serde_jcs::to_vec(&value).map_err(|error| error.to_string())?)
    ))
}

pub(crate) fn baseline(
    snapshot: &ProfileSnapshotV2,
    scope: &ScopeV2,
) -> Result<LocalProfileConfigurationV2, String> {
    let identity = authority(scope)?;
    let mut source = ProfileSourceV2 {
        schema_version: 2,
        source_id: format!("local-source-{identity}"),
        profile_id: snapshot.profile_id.clone(),
        revision: 1,
        digest: String::new(),
        provenance: None,
        layers: vec![],
    };
    source.digest = digest(&json!(source), true)?;
    let mut desired = DesiredBundleSetV2 {
        schema_version: 2,
        desired_set_id: format!("local-desired-{identity}"),
        revision: 1,
        bundles: vec![BundleReferenceV2 {
            bundle_id: "memstack-local-builtins".into(),
            version: "2.0.0".into(),
            digest: format!("sha256:{}", snapshot.digest),
            source: "builtin://memstack-local-builtins/2.0.0".into(),
        }],
        profile_source: ProfileSourceReferenceV2 {
            source_id: source.source_id.clone(),
            revision: 1,
            digest: source.digest.clone(),
        },
        digest: String::new(),
    };
    desired.digest = digest(&json!(desired), true)?;
    Ok(LocalProfileConfigurationV2 { source, desired })
}

fn public(module: &PluginModuleV2) -> bool {
    module
        .contract
        .config_schema
        .get("x-memstack-management")
        .and_then(|value| value.get("public_config"))
        .and_then(Value::as_bool)
        == Some(true)
}

fn editable(module: &PluginModuleV2) -> bool {
    module
        .contract
        .config_schema
        .get("x-memstack-management")
        .and_then(|value| value.get("editable"))
        .and_then(Value::as_bool)
        == Some(true)
}

fn module<'a>(
    snapshot: &'a ProfileSnapshotV2,
    entry: &ProfileEntryV2,
) -> Result<&'a PluginModuleV2, String> {
    snapshot
        .manifests
        .iter()
        .find(|manifest| manifest.plugin_id == entry.plugin_ref)
        .and_then(|manifest| {
            manifest
                .modules
                .iter()
                .find(|module| module.module_ref == entry.module_ref)
        })
        .ok_or_else(|| "instance module is unavailable".into())
}

fn replacements(snapshot: &ProfileSnapshotV2, current: &PluginModuleV2) -> Vec<ReplacementV2> {
    snapshot
        .manifests
        .iter()
        .flat_map(|manifest| {
            manifest.modules.iter().filter_map(|module| {
                (module.module_ref != current.module_ref
                    && module.targets == current.targets
                    && module.contract_digest == current.contract_digest
                    && editable(module))
                .then(|| ReplacementV2 {
                    plugin_id: manifest.plugin_id.clone(),
                    module_ref: module.module_ref.clone(),
                })
            })
        })
        .collect()
}

pub(crate) fn visible(owner: &ScopeV2, scope: &ScopeV2) -> bool {
    match owner.kind {
        ScopeKindV2::Root => true,
        ScopeKindV2::Tenant => owner.tenant_id == scope.tenant_id,
        ScopeKindV2::Project => {
            owner.tenant_id == scope.tenant_id && owner.project_id == scope.project_id
        }
        ScopeKindV2::Session => owner == scope,
    }
}

pub(crate) fn revise(
    base: &ProfileSnapshotV2,
    current: &LocalProfileConfigurationV2,
    scope: &ScopeV2,
    expected_revision: u64,
    changes: &[InstanceChangeV2],
) -> Result<LocalProfileConfigurationV2, String> {
    if current.desired.revision != expected_revision {
        return Err("instance_revision_conflict".into());
    }
    if changes.is_empty() || changes.len() > 500 {
        return Err("instance_change_invalid".into());
    }
    let snapshot = compose(base, current, scope)?;
    let mut seen = BTreeSet::new();
    let mut changed = Vec::new();
    for change in changes {
        if !seen.insert(&change.entry_id) {
            return Err("instance_change_invalid".into());
        }
        let original = snapshot
            .entries
            .iter()
            .find(|entry| entry.entry_id == change.entry_id)
            .ok_or("instance_change_invalid")?;
        let contract = module(&snapshot, original)?;
        // Local UI edits must not implicitly mutate the process-wide sidecar authority.
        // Signed WASM installation lifecycle has its own authorized operations.
        if !editable(contract)
            || !contract
                .targets
                .contains(&DataPlaneTargetV2::DesktopRenderer)
        {
            return Err("instance_not_editable".into());
        }
        if change.config.is_some() && !public(contract) {
            return Err("instance_config_private".into());
        }
        let mut entry = original.clone();
        entry.scope = scope.clone();
        if let Some(enabled) = change.enabled {
            entry.enabled = enabled;
        }
        if let Some(config) = &change.config {
            entry.config = config.clone();
        }
        if let Some(replacement) = &change.replacement {
            if !replacements(&snapshot, contract).contains(replacement) {
                return Err("instance_replacement_incompatible".into());
            }
            entry.plugin_ref.clone_from(&replacement.plugin_id);
            entry.module_ref.clone_from(&replacement.module_ref);
        }
        changed.push(entry);
    }
    let mut updated = current.clone();
    let revision = current
        .desired
        .revision
        .checked_add(1)
        .filter(|value| *value <= 9_007_199_254_740_991)
        .ok_or("instance_revision_exhausted")?;
    updated.source.revision = revision;
    updated.source.layers.push(ProfileLayerV2 {
        layer_id: format!("local-instances-{revision}"),
        kind: ProfileLayerKindV2::Project,
        scope: scope.clone(),
        entries: vec![],
        replacements: changed,
        disabled_entry_ids: vec![],
    });
    updated.source.digest = digest(&json!(updated.source), true)?;
    updated.desired.revision = revision;
    updated.desired.profile_source = ProfileSourceReferenceV2 {
        source_id: updated.source.source_id.clone(),
        revision,
        digest: updated.source.digest.clone(),
    };
    updated.desired.digest = digest(&json!(updated.desired), true)?;
    compose(base, &updated, scope)?;
    Ok(updated)
}

pub(crate) fn compose(
    base: &ProfileSnapshotV2,
    configuration: &LocalProfileConfigurationV2,
    scope: &ScopeV2,
) -> Result<ProfileSnapshotV2, String> {
    if configuration.source.digest != digest(&json!(configuration.source), true)?
        || configuration.desired.digest != digest(&json!(configuration.desired), true)?
        || configuration.desired.profile_source.digest != configuration.source.digest
    {
        return Err("instance_configuration_invalid".into());
    }
    let mut snapshot = base.clone();
    snapshot
        .entries
        .retain(|entry| visible(&entry.scope, scope));
    for layer in &configuration.source.layers {
        if layer.scope != *scope
            || !layer.entries.is_empty()
            || !layer.disabled_entry_ids.is_empty()
        {
            return Err("instance_scope_mismatch".into());
        }
        for replacement in &layer.replacements {
            let entry = snapshot
                .entries
                .iter_mut()
                .find(|entry| entry.entry_id == replacement.entry_id)
                .ok_or("instance_replacement_missing")?;
            if replacement.scope != *scope {
                return Err("instance_scope_mismatch".into());
            }
            *entry = replacement.clone();
        }
    }
    snapshot.generation = snapshot
        .generation
        .checked_add(configuration.desired.revision - 1)
        .filter(|value| *value <= 9_007_199_254_740_991)
        .ok_or("instance_revision_exhausted")?;
    let mut wire = json!(snapshot);
    wire["digest"] = digest(&wire, true)?.trim_start_matches("sha256:").into();
    let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&wire.to_string())
        .map_err(|error| error.to_string())?;
    validate_snapshot_target_v2(&snapshot, &DataPlaneTargetV2::DesktopRenderer)
        .map_err(|error| error.to_string())?;
    validate_contributions(&snapshot, base)?;
    Ok(snapshot)
}

fn validate_contributions(
    snapshot: &ProfileSnapshotV2,
    base: &ProfileSnapshotV2,
) -> Result<(), String> {
    let artifacts: BTreeMap<_, _> = base
        .entries
        .iter()
        .flat_map(contributions)
        .flat_map(|contribution| {
            let kind = contribution["kind"].as_str().unwrap_or_default().to_owned();
            contribution["payload"]["artifact_refs"]
                .as_array()
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter_map(move |value| value.as_str().map(|id| (id.to_owned(), kind.clone())))
        })
        .collect();
    let mut owners = BTreeSet::new();
    let mut artifact_owners = BTreeSet::new();
    for contribution in snapshot
        .entries
        .iter()
        .filter(|entry| entry.enabled)
        .filter(|entry| {
            module(snapshot, entry)
                .is_ok_and(|module| module.targets.contains(&DataPlaneTargetV2::DesktopRenderer))
        })
        .flat_map(contributions)
    {
        let key = (
            contribution["kind"].as_str().map(str::to_owned),
            contribution["id"].as_str().map(str::to_owned),
        );
        if !owners.insert(key) {
            return Err("renderer_contribution_conflict".into());
        }
        for artifact in contribution["payload"]["artifact_refs"]
            .as_array()
            .ok_or("renderer_artifact_invalid")?
        {
            let id = artifact.as_str().ok_or("renderer_artifact_invalid")?;
            let kind = artifacts.get(id).ok_or("renderer_artifact_unavailable")?;
            if contribution["kind"].as_str() != Some(kind.as_str()) {
                return Err("renderer_artifact_kind_mismatch".into());
            }
            // Aliases are declared inside one compiled artifact and keep that single owner.
            if !artifact_owners.insert(id.to_owned()) {
                return Err("renderer_artifact_conflict".into());
            }
        }
    }
    Ok(())
}

fn contributions(entry: &ProfileEntryV2) -> Vec<Value> {
    match entry.module_ref.as_str() {
        "builtin://memstack/desktop/renderer-feature"
        | "builtin://memstack/desktop/renderer-management" => entry
            .config
            .get("contributions")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default(),
        "builtin://memstack/desktop/renderer-contribution" => vec![json!(entry.config)],
        _ => vec![],
    }
}

pub(crate) fn rows(
    snapshot: &ProfileSnapshotV2,
    scope: &ScopeV2,
    can_edit: bool,
) -> Result<Vec<Value>, String> {
    snapshot.entries.iter().filter(|entry| visible(&entry.scope, scope)).filter(|entry| {
        module(snapshot, entry).is_ok_and(|module| module.targets.iter().any(|target| matches!(target, DataPlaneTargetV2::DesktopRenderer | DataPlaneTargetV2::DesktopSidecar)))
    }).map(|entry| {
        let contract = module(snapshot, entry)?;
        let editable = can_edit && editable(contract) && contract.targets.contains(&DataPlaneTargetV2::DesktopRenderer);
        let public = public(contract);
        Ok(json!({"entry_id":entry.entry_id,"plugin_id":entry.plugin_ref,"module_ref":entry.module_ref,
            "display_name":if public {entry.config.get("id").and_then(Value::as_str).unwrap_or(&entry.entry_id)} else {&entry.entry_id},
            "enabled":entry.enabled,"config":if public {json!(entry.config)} else {json!({})},
            "config_schema":if public {json!(contract.contract.config_schema)} else {json!({})},
            "editable":editable,"config_editable":editable && public,
            "reason_code":if editable {Value::Null} else {json!("instance_managed_by_deployment")},
            "inherited_from":if entry.scope==*scope {Value::Null} else {json!(entry.scope)},
            "replacement_candidates":if editable {json!(replacements(snapshot, contract))} else {json!([])},
            "state":{"status":if entry.enabled {"active"} else {"disabled"},"reason_code":null}}))
    }).collect()
}
