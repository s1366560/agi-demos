//! Strict v2 wire protocol and executor-neutral generation runtime.

mod context;
mod contract_runtime;
mod distribution;
mod generated;
mod generated_catalog;
mod reconciler;
mod runtime;
mod target_modules;

use std::collections::{BTreeMap, BTreeSet};

pub use distribution::{
    parse_control_plane_distribution_v2, ControlPlaneDistributionV2, PluginGenerationDescriptorV2,
};
pub use generated::*;
pub use generated_catalog::{PLUGIN_MODULE_CATALOG_DIGEST_V2, PLUGIN_MODULE_CATALOG_V2_JSON};
pub use reconciler::{PluginSnapshotReconcilerV2, PreparedSnapshotApplyV2, SnapshotPreparationV2};
pub use runtime::{
    project_snapshot_entries_v2, ContextV2, FiberPhaseV2, FiberV2, GenerationLeaseV2,
    GenerationManagerV2, GenerationRetirementV2, LoaderV2, PluginDefinitionV2,
    PluginModuleRuntimeV2, RuntimeGenerationV2, RuntimeV2Error,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
pub use target_modules::{
    desktop_sidecar_host_definition_v2, desktop_sidecar_http_routes_definition_v2,
    rust_server_host_definition_v2, rust_server_http_routes_definition_v2,
    DesktopSidecarHostModuleV2, DesktopSidecarHttpRouteContributionV2,
    DesktopSidecarHttpRoutesModuleV2, RustServerHostModuleV2, RustServerHttpRouteContributionV2,
    RustServerHttpRoutesModuleV2, TargetHostDescriptorV2,
    DESKTOP_SIDECAR_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2, DESKTOP_SIDECAR_HOST_MODULE_REF_V2,
    DESKTOP_SIDECAR_HOST_SERVICE_V2, DESKTOP_SIDECAR_HTTP_ROUTES_MODULE_REF_V2,
    DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2, DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_VERSION_V2,
    DESKTOP_SIDECAR_HTTP_ROUTE_STRATEGY_V2, RUST_SERVER_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2,
    RUST_SERVER_HOST_MODULE_REF_V2, RUST_SERVER_HOST_SERVICE_V2,
    RUST_SERVER_HTTP_ROUTES_MODULE_REF_V2, RUST_SERVER_HTTP_ROUTES_SERVICE_V2,
    RUST_SERVER_HTTP_ROUTE_STRATEGY_V2,
};
use thiserror::Error;

pub const PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL_V2: &str = "types.memstack.ai/plugin.profile.v2";
pub const JSON_SCHEMA_DIALECT_V2: &str = "https://json-schema.org/draft/2020-12/schema";

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
    #[error("module {module_ref} contract digest mismatch: expected {expected}")]
    ContractDigestMismatch {
        module_ref: String,
        expected: String,
    },
    #[error("module {module_ref} contract schema is invalid: {detail}")]
    InvalidContractSchema { module_ref: String, detail: String },
    #[error("duplicate plugin_id: {0}")]
    DuplicatePluginId(String),
    #[error("plugin {plugin_id} declares duplicate module_ref: {module_ref}")]
    DuplicateModuleRef {
        plugin_id: String,
        module_ref: String,
    },
    #[error("module {0} repeats a provided service")]
    DuplicateServiceProvision(String),
    #[error("module {0} repeats a required service alias")]
    DuplicateServiceRequirement(String),
    #[error("module {module_ref} repeats {direction} event {event}")]
    DuplicateEventContract {
        module_ref: String,
        direction: &'static str,
        event: String,
    },
    #[error("event {event} differs between {first_module_ref} and {second_module_ref}")]
    EventContractMismatch {
        event: String,
        first_module_ref: String,
        second_module_ref: String,
    },
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

impl PluginProtocolV2Error {
    /// Return the stable cross-language protocol rejection code.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::IncompatibleSchemaVersion => "incompatible_schema_version",
            Self::InvalidJson(_) => "invalid_json",
            Self::InvalidShape(_) => "invalid_shape",
            Self::DigestMismatch { .. } => "digest_mismatch",
            Self::ContractDigestMismatch { .. } => "contract_digest_mismatch",
            Self::InvalidContractSchema { .. } => "invalid_contract_schema",
            Self::DuplicatePluginId(_) => "duplicate_plugin_id",
            Self::DuplicateModuleRef { .. } => "duplicate_module_ref",
            Self::DuplicateServiceProvision(_) => "duplicate_service_provision",
            Self::DuplicateServiceRequirement(_) => "duplicate_service_requirement",
            Self::DuplicateEventContract { .. } => "duplicate_event_contract",
            Self::EventContractMismatch { .. } => "event_contract_mismatch",
            Self::DuplicateEntryId(_) => "duplicate_entry_id",
            Self::MissingManifest { .. } => "missing_manifest",
            Self::MissingModule { .. } => "missing_module",
            Self::MissingParent { .. } => "missing_parent",
            Self::EntryCycle(_) => "entry_cycle",
            Self::InvalidScope(_) => "invalid_scope",
            Self::InvalidParentScope { .. } => "invalid_parent_scope",
            Self::InvalidParentTargets { .. } => "invalid_parent_targets",
            Self::DistributionMismatch(_) => "distribution_mismatch",
        }
    }
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
        let mut module_refs = BTreeSet::new();
        for module in &manifest.modules {
            if !module_refs.insert(module.module_ref.as_str()) {
                return Err(PluginProtocolV2Error::DuplicateModuleRef {
                    plugin_id: manifest.plugin_id.clone(),
                    module_ref: module.module_ref.clone(),
                });
            }
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
            validate_module_contract(module)?;
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
    validate_event_contracts(snapshot)?;
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

/// Return the normative RFC 8785 digest for one public plugin contract.
pub fn plugin_contract_digest_v2(
    contract: &PluginContractV2,
) -> Result<String, PluginProtocolV2Error> {
    let value = serde_json::to_value(contract)
        .map_err(|error| PluginProtocolV2Error::InvalidShape(error.to_string()))?;
    let canonical = serde_jcs::to_vec(&value)
        .map_err(|error| PluginProtocolV2Error::InvalidShape(error.to_string()))?;
    Ok(format!("sha256:{:x}", Sha256::digest(canonical)))
}

fn validate_module_contract(module: &PluginModuleV2) -> Result<(), PluginProtocolV2Error> {
    validate_plugin_contract_v2(
        &module.module_ref,
        &module.contract,
        &module.contract_digest,
    )
}

pub(crate) fn validate_plugin_contract_v2(
    module_ref: &str,
    contract: &PluginContractV2,
    declared_digest: &str,
) -> Result<(), PluginProtocolV2Error> {
    validate_contract_schema(module_ref, "config_schema", &contract.config_schema, true)?;
    for (direction, events) in [
        ("emits", &contract.events.emits),
        ("handles", &contract.events.handles),
    ] {
        let mut names = BTreeSet::new();
        for event in events {
            if !names.insert(event.event.as_str()) {
                return Err(PluginProtocolV2Error::DuplicateEventContract {
                    module_ref: module_ref.to_owned(),
                    direction,
                    event: event.event.clone(),
                });
            }
            validate_contract_schema(
                module_ref,
                &format!("{direction} {} payload_schema", event.event),
                &event.payload_schema,
                false,
            )?;
            validate_contract_schema(
                module_ref,
                &format!("{direction} {} result_schema", event.event),
                &event.result_schema,
                false,
            )?;
        }
    }

    let mut provided = BTreeSet::new();
    for service in &contract.services.provides {
        if !provided.insert((service.service.as_str(), service.version.as_str())) {
            return Err(PluginProtocolV2Error::DuplicateServiceProvision(
                module_ref.to_owned(),
            ));
        }
    }
    let mut required_aliases = BTreeSet::new();
    for service in &contract.services.requires {
        if !required_aliases.insert(service.alias.as_str()) {
            return Err(PluginProtocolV2Error::DuplicateServiceRequirement(
                module_ref.to_owned(),
            ));
        }
    }

    let expected = plugin_contract_digest_v2(contract)?;
    if declared_digest != expected {
        return Err(PluginProtocolV2Error::ContractDigestMismatch {
            module_ref: module_ref.to_owned(),
            expected,
        });
    }
    Ok(())
}

fn validate_contract_schema(
    module_ref: &str,
    label: &str,
    schema: &JsonSchemaV2,
    require_object: bool,
) -> Result<(), PluginProtocolV2Error> {
    let value = serde_json::to_value(schema).map_err(|error| {
        PluginProtocolV2Error::InvalidContractSchema {
            module_ref: module_ref.to_owned(),
            detail: format!("{label}: {error}"),
        }
    })?;
    if value.get("$schema").and_then(Value::as_str) != Some(JSON_SCHEMA_DIALECT_V2) {
        return Err(PluginProtocolV2Error::InvalidContractSchema {
            module_ref: module_ref.to_owned(),
            detail: format!("{label} must declare JSON Schema draft 2020-12"),
        });
    }
    if require_object && value.get("type").and_then(Value::as_str) != Some("object") {
        return Err(PluginProtocolV2Error::InvalidContractSchema {
            module_ref: module_ref.to_owned(),
            detail: format!("{label} must describe an object"),
        });
    }
    validate_schema_restrictions(&value, "$", module_ref, label)?;
    jsonschema::draft202012::meta::validate(&value).map_err(|error| {
        PluginProtocolV2Error::InvalidContractSchema {
            module_ref: module_ref.to_owned(),
            detail: format!("{label}: {error}"),
        }
    })
}

fn validate_schema_restrictions(
    value: &Value,
    path: &str,
    module_ref: &str,
    label: &str,
) -> Result<(), PluginProtocolV2Error> {
    match value {
        Value::Object(object) => {
            if object.contains_key("default") {
                return Err(PluginProtocolV2Error::InvalidContractSchema {
                    module_ref: module_ref.to_owned(),
                    detail: format!("{label} forbids default at {path}"),
                });
            }
            if let Some(reference) = object.get("$ref") {
                if !reference
                    .as_str()
                    .is_some_and(|reference| reference.starts_with("#/"))
                {
                    return Err(PluginProtocolV2Error::InvalidContractSchema {
                        module_ref: module_ref.to_owned(),
                        detail: format!("{label} forbids remote $ref at {path}"),
                    });
                }
            }
            if let Some(dialect) = object.get("$schema") {
                if dialect.as_str() != Some(JSON_SCHEMA_DIALECT_V2) {
                    return Err(PluginProtocolV2Error::InvalidContractSchema {
                        module_ref: module_ref.to_owned(),
                        detail: format!("{label} uses a non-2020-12 dialect at {path}"),
                    });
                }
            }
            for (key, child) in object {
                validate_schema_restrictions(child, &format!("{path}.{key}"), module_ref, label)?;
            }
        }
        Value::Array(values) => {
            for (index, child) in values.iter().enumerate() {
                validate_schema_restrictions(child, &format!("{path}.{index}"), module_ref, label)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn validate_event_contracts(snapshot: &ProfileSnapshotV2) -> Result<(), PluginProtocolV2Error> {
    let mut declarations: BTreeMap<&str, (&str, &EventContractV2)> = BTreeMap::new();
    for module in snapshot
        .manifests
        .iter()
        .flat_map(|manifest| &manifest.modules)
    {
        for event in module
            .contract
            .events
            .emits
            .iter()
            .chain(&module.contract.events.handles)
        {
            if let Some((first_module_ref, previous)) = declarations.get(event.event.as_str()) {
                if *previous != event {
                    return Err(PluginProtocolV2Error::EventContractMismatch {
                        event: event.event.clone(),
                        first_module_ref: (*first_module_ref).to_owned(),
                        second_module_ref: module.module_ref.clone(),
                    });
                }
            } else {
                declarations.insert(&event.event, (&module.module_ref, event));
            }
        }
    }
    Ok(())
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
