//! Target catalog and generation preflight for protocol v2.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use super::{
    runtime::RuntimeV2Error, scope_contains, scope_rank, validate_plugin_contract_v2,
    DataPlaneTargetV2, EventContractV2, PluginContractV2, PluginModuleV2, ProfileEntryV2,
};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PluginModuleCatalogDocumentV2 {
    schema_version: u64,
    modules: Vec<PluginModuleCatalogEntryV2>,
    catalog_digest: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PluginModuleCatalogEntryV2 {
    pub(super) plugin_id: String,
    pub(super) plugin_version: String,
    pub(super) module_ref: String,
    pub(super) entrypoint: String,
    pub(super) artifact_digest: String,
    pub(super) artifact_source: String,
    pub(super) targets: Vec<DataPlaneTargetV2>,
    pub(super) contract: PluginContractV2,
    pub(super) contract_digest: String,
}

pub(super) fn parse_target_catalog(
    raw: &str,
    expected_catalog_digest: Option<&str>,
) -> Result<BTreeMap<String, PluginModuleCatalogEntryV2>, RuntimeV2Error> {
    let mut value: Value = serde_json::from_str(raw)
        .map_err(|error| RuntimeV2Error::InvalidTargetCatalog(error.to_string()))?;
    let document: PluginModuleCatalogDocumentV2 = serde_json::from_value(value.clone())
        .map_err(|error| RuntimeV2Error::InvalidTargetCatalog(error.to_string()))?;
    if document.schema_version != 2 {
        return Err(RuntimeV2Error::InvalidTargetCatalog(
            "schema_version must be 2".into(),
        ));
    }
    value
        .as_object_mut()
        .ok_or_else(|| RuntimeV2Error::InvalidTargetCatalog("catalog must be an object".into()))?
        .remove("catalog_digest");
    let canonical = serde_jcs::to_vec(&value)
        .map_err(|error| RuntimeV2Error::InvalidTargetCatalog(error.to_string()))?;
    let expected = format!("sha256:{:x}", Sha256::digest(canonical));
    if document.catalog_digest != expected {
        return Err(RuntimeV2Error::CatalogDigestMismatch { expected });
    }
    if expected_catalog_digest.is_some_and(|digest| digest != document.catalog_digest) {
        return Err(RuntimeV2Error::CatalogDigestMismatch {
            expected: expected_catalog_digest.unwrap_or_default().to_owned(),
        });
    }

    let mut modules = BTreeMap::new();
    for module in document.modules {
        validate_runtime_contract(
            &module.module_ref,
            &module.contract,
            &module.contract_digest,
        )?;
        if module.targets.is_empty()
            || module
                .targets
                .iter()
                .enumerate()
                .any(|(index, target)| module.targets[..index].contains(target))
        {
            return Err(RuntimeV2Error::InvalidTargetCatalog(format!(
                "module {} targets must be non-empty and unique",
                module.module_ref
            )));
        }
        let module_ref = module.module_ref.clone();
        if modules.insert(module_ref.clone(), module).is_some() {
            return Err(RuntimeV2Error::InvalidTargetCatalog(format!(
                "duplicate module_ref {module_ref}"
            )));
        }
    }
    Ok(modules)
}

pub(super) fn validate_runtime_contract(
    module_ref: &str,
    contract: &PluginContractV2,
    declared_digest: &str,
) -> Result<(), RuntimeV2Error> {
    validate_plugin_contract_v2(module_ref, contract, declared_digest).map_err(|error| {
        let detail = error.to_string();
        match error.code() {
            "contract_digest_mismatch" => {
                RuntimeV2Error::ContractDigestMismatch(module_ref.to_owned())
            }
            "invalid_contract_schema" => RuntimeV2Error::InvalidContractSchema {
                module_ref: module_ref.to_owned(),
                detail,
            },
            _ => RuntimeV2Error::InvalidTargetCatalog(detail),
        }
    })
}

pub(super) fn same_targets(left: &[DataPlaneTargetV2], right: &[DataPlaneTargetV2]) -> bool {
    left.len() == right.len() && left.iter().all(|target| right.contains(target))
}

pub(super) fn preflight_entries(
    entries: &BTreeMap<String, ProfileEntryV2>,
    modules: &BTreeMap<String, PluginModuleV2>,
) -> Result<(), RuntimeV2Error> {
    type ProviderIdentityV2 = (
        String,
        String,
        u8,
        Option<String>,
        Option<String>,
        Option<String>,
        Option<String>,
    );
    let mut provider_identities: BTreeMap<ProviderIdentityV2, String> = BTreeMap::new();
    for (entry_id, entry) in entries {
        let contract = &modules[entry_id].contract;
        let schema = serde_json::to_value(&contract.config_schema).map_err(|error| {
            RuntimeV2Error::InvalidContractSchema {
                module_ref: modules[entry_id].module_ref.clone(),
                detail: error.to_string(),
            }
        })?;
        let validator = jsonschema::draft202012::new(&schema).map_err(|error| {
            RuntimeV2Error::InvalidContractSchema {
                module_ref: modules[entry_id].module_ref.clone(),
                detail: error.to_string(),
            }
        })?;
        let config = serde_json::to_value(&entry.config).map_err(|error| {
            RuntimeV2Error::InvalidModuleConfig {
                entry_id: entry_id.clone(),
                detail: error.to_string(),
            }
        })?;
        if let Err(error) = validator.validate(&config) {
            return Err(RuntimeV2Error::InvalidModuleConfig {
                entry_id: entry_id.clone(),
                detail: error.to_string(),
            });
        }

        let requirements: BTreeMap<_, _> = contract
            .services
            .requires
            .iter()
            .map(|item| (item.alias.as_str(), item))
            .collect();
        for alias in requirements.keys() {
            if !entry.inject.contains_key(*alias) {
                return Err(RuntimeV2Error::MissingRequiredInject {
                    entry_id: entry_id.clone(),
                    alias: (*alias).to_owned(),
                });
            }
        }
        for alias in entry.inject.keys() {
            if !requirements.contains_key(alias.as_str()) {
                return Err(RuntimeV2Error::UnexpectedInject {
                    entry_id: entry_id.clone(),
                    alias: alias.clone(),
                });
            }
        }
        for (alias, requirement) in requirements {
            if entry.inject.get(alias) != Some(&requirement.service) {
                return Err(RuntimeV2Error::InjectServiceMismatch {
                    entry_id: entry_id.clone(),
                    alias: alias.to_owned(),
                    service: requirement.service.clone(),
                });
            }
        }

        let declared_services: BTreeSet<_> = contract
            .services
            .provides
            .iter()
            .map(|item| item.service.as_str())
            .chain(
                contract
                    .services
                    .requires
                    .iter()
                    .map(|item| item.service.as_str()),
            )
            .collect();
        for service in entry.isolate.keys() {
            if !declared_services.contains(service.as_str()) {
                return Err(RuntimeV2Error::UnexpectedIsolation {
                    entry_id: entry_id.clone(),
                    service: service.clone(),
                });
            }
        }

        for provision in &contract.services.provides {
            let identity = (
                provision.service.clone(),
                provision.version.clone(),
                scope_rank(&entry.scope),
                entry.scope.tenant_id.clone(),
                entry.scope.project_id.clone(),
                entry.scope.session_id.clone(),
                entry.isolate.get(&provision.service).cloned(),
            );
            if let Some(first_entry_id) = provider_identities.get(&identity) {
                return Err(RuntimeV2Error::ProviderConflict {
                    first_entry_id: first_entry_id.clone(),
                    second_entry_id: entry_id.clone(),
                    service: provision.service.clone(),
                    version: provision.version.clone(),
                });
            }
            provider_identities.insert(identity, entry_id.clone());
        }
    }
    Ok(())
}

pub(super) fn event_contract_catalog<'a>(
    modules: impl IntoIterator<Item = &'a PluginModuleV2>,
) -> Result<BTreeMap<String, EventContractV2>, RuntimeV2Error> {
    let mut declarations = BTreeMap::new();
    for module in modules {
        for declaration in module
            .contract
            .events
            .emits
            .iter()
            .chain(&module.contract.events.handles)
        {
            if declarations
                .get(&declaration.event)
                .is_some_and(|previous| previous != declaration)
            {
                return Err(RuntimeV2Error::EventContractMismatch(
                    declaration.event.clone(),
                ));
            }
            declarations.insert(declaration.event.clone(), declaration.clone());
        }
    }
    Ok(declarations)
}

pub(super) fn entry_order(
    entries: &BTreeMap<String, ProfileEntryV2>,
    modules: &BTreeMap<String, PluginModuleV2>,
    declaration_order: &[String],
) -> Result<Vec<String>, RuntimeV2Error> {
    let mut dependencies: BTreeMap<String, BTreeSet<String>> = entries
        .keys()
        .map(|entry_id| (entry_id.clone(), BTreeSet::new()))
        .collect();
    for (entry_id, entry) in entries {
        if let Some(parent_id) = &entry.parent_entry_id {
            dependencies
                .get_mut(entry_id)
                .ok_or_else(|| RuntimeV2Error::EntryDependencyCycle(entry_id.clone()))?
                .insert(parent_id.clone());
        }
        for requirement in &modules[entry_id].contract.services.requires {
            let service = &requirement.service;
            let mut providers: Vec<_> = modules
                .iter()
                .filter(|(provider_id, module)| {
                    module.contract.services.provides.iter().any(|provision| {
                        provision.service == *service && provision.version == requirement.version
                    }) && scope_contains(&entries[*provider_id].scope, &entry.scope)
                        && entries[*provider_id].isolate.get(service) == entry.isolate.get(service)
                })
                .map(|(provider_id, _)| provider_id.clone())
                .collect();
            providers.sort_by_key(|provider_id| {
                std::cmp::Reverse(scope_rank(&entries[provider_id].scope))
            });
            let Some(first) = providers.first() else {
                let has_other_version = modules.iter().any(|(provider_id, module)| {
                    module
                        .contract
                        .services
                        .provides
                        .iter()
                        .any(|provision| provision.service == *service)
                        && scope_contains(&entries[provider_id].scope, &entry.scope)
                        && entries[provider_id].isolate.get(service) == entry.isolate.get(service)
                });
                if has_other_version {
                    return Err(RuntimeV2Error::ServiceVersionMismatch {
                        entry_id: entry_id.clone(),
                        service: service.clone(),
                        version: requirement.version.clone(),
                    });
                }
                return Err(RuntimeV2Error::MissingInjectProvider {
                    entry_id: entry_id.clone(),
                    service: service.clone(),
                });
            };
            let rank = scope_rank(&entries[first].scope);
            let nearest: Vec<_> = providers
                .iter()
                .filter(|provider_id| scope_rank(&entries[*provider_id].scope) == rank)
                .collect();
            if nearest.len() != 1 {
                return Err(RuntimeV2Error::AmbiguousInjectProvider {
                    entry_id: entry_id.clone(),
                    service: service.clone(),
                });
            }
            if first != entry_id {
                dependencies
                    .get_mut(entry_id)
                    .ok_or_else(|| RuntimeV2Error::EntryDependencyCycle(entry_id.clone()))?
                    .insert(first.clone());
            }
        }
    }

    fn visit(
        entry_id: &str,
        dependencies: &BTreeMap<String, BTreeSet<String>>,
        declaration_order: &[String],
        visiting: &mut BTreeSet<String>,
        visited: &mut BTreeSet<String>,
        ordered: &mut Vec<String>,
    ) -> Result<(), RuntimeV2Error> {
        if visited.contains(entry_id) {
            return Ok(());
        }
        if !visiting.insert(entry_id.to_owned()) {
            return Err(RuntimeV2Error::EntryDependencyCycle(entry_id.to_owned()));
        }
        for dependency in declaration_order
            .iter()
            .filter(|candidate| dependencies[entry_id].contains(*candidate))
        {
            visit(
                dependency,
                dependencies,
                declaration_order,
                visiting,
                visited,
                ordered,
            )?;
        }
        visiting.remove(entry_id);
        visited.insert(entry_id.to_owned());
        ordered.push(entry_id.to_owned());
        Ok(())
    }

    let mut ordered = Vec::new();
    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    for entry_id in declaration_order {
        visit(
            entry_id,
            &dependencies,
            declaration_order,
            &mut visiting,
            &mut visited,
            &mut ordered,
        )?;
    }
    Ok(ordered)
}
