//! Configuration validation without starting effects or loading executable modules.

use std::collections::BTreeMap;

use super::{
    contract_runtime::{entry_order, preflight_entries},
    project_snapshot_entries_v2, DataPlaneTargetV2, ProfileSnapshotV2, RuntimeV2Error,
};

/// Callers must obtain manifests from the generated catalog or verified installed archives.
pub fn validate_snapshot_target_v2(
    snapshot: &ProfileSnapshotV2,
    target: &DataPlaneTargetV2,
) -> Result<(), RuntimeV2Error> {
    let declared: BTreeMap<_, _> = snapshot
        .manifests
        .iter()
        .flat_map(|manifest| {
            manifest.modules.iter().map(move |module| {
                (
                    (manifest.plugin_id.as_str(), module.module_ref.as_str()),
                    module,
                )
            })
        })
        .collect();
    let projected = project_snapshot_entries_v2(snapshot, target);
    let entries: BTreeMap<_, _> = projected
        .iter()
        .map(|entry| (entry.entry_id.clone(), (**entry).clone()))
        .collect();
    let modules = entries
        .iter()
        .map(|(id, entry)| {
            declared
                .get(&(entry.plugin_ref.as_str(), entry.module_ref.as_str()))
                .map(|module| (id.clone(), (**module).clone()))
                .ok_or_else(|| RuntimeV2Error::MissingModuleDefinition(entry.module_ref.clone()))
        })
        .collect::<Result<BTreeMap<_, _>, _>>()?;
    preflight_entries(&entries, &modules)?;
    let order = projected
        .iter()
        .filter(|entry| entry.enabled)
        .map(|entry| entry.entry_id.clone())
        .collect::<Vec<_>>();
    let enabled = entries
        .into_iter()
        .filter(|(_, entry)| entry.enabled)
        .collect::<BTreeMap<_, _>>();
    for entry in enabled.values() {
        if let Some(parent_id) = &entry.parent_entry_id {
            if !enabled.contains_key(parent_id) {
                return Err(RuntimeV2Error::InactiveParentEntry {
                    entry_id: entry.entry_id.clone(),
                    parent_id: parent_id.clone(),
                });
            }
        }
    }
    let enabled_modules = modules
        .into_iter()
        .filter(|(id, _)| enabled.contains_key(id))
        .collect();
    entry_order(&enabled, &enabled_modules, &order)?;
    Ok(())
}
