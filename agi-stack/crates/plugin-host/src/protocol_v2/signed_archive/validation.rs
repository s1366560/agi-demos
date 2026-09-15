use std::collections::BTreeSet;

use serde_json::Value;
use sha2::{Digest, Sha256};

use super::{reject, BundleArchiveV2Error};
use crate::protocol_v2::{
    validate_snapshot_semantics, BundleManifestV2, ProfileSnapshotV2, TrustKindV2,
    PLUGIN_MODULE_CATALOG_V2_JSON,
};

pub(super) fn parse_descriptor(raw: &[u8]) -> Result<BundleManifestV2, BundleArchiveV2Error> {
    let value: Value = serde_json::from_slice(raw)
        .map_err(|_| reject("bundle_descriptor_invalid", "descriptor must be JSON"))?;
    let schema: Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../shared/schemas/plugins/platform-plugin-protocol.v2.schema.json"
    )))
    .map_err(|_| reject("bundle_schema_unavailable", "protocol schema is invalid"))?;
    let validator = jsonschema::validator_for(&serde_json::json!({
        "$schema": schema["$schema"], "$defs": schema["$defs"],
        "$ref": "#/$defs/BundleManifestV2",
    }))
    .map_err(|_| {
        reject(
            "bundle_schema_unavailable",
            "protocol schema cannot compile",
        )
    })?;
    if !validator.is_valid(&value) {
        return Err(reject(
            "bundle_descriptor_invalid",
            "descriptor violates v2 schema",
        ));
    }
    let manifest: BundleManifestV2 = serde_json::from_value(value.clone())
        .map_err(|_| reject("bundle_descriptor_invalid", "descriptor violates v2 shape"))?;
    if manifest.digest != bundle_manifest_digest_v2(&manifest)? {
        return Err(reject(
            "bundle_digest_mismatch",
            "descriptor digest differs",
        ));
    }
    let snapshot = ProfileSnapshotV2 {
        schema_version: 2,
        profile_id: manifest.bundle_id.clone(),
        generation: 1,
        digest: String::new(),
        manifests: manifest.manifests.clone(),
        entries: vec![],
    };
    validate_snapshot_semantics(&snapshot)
        .map_err(|_| reject("bundle_manifest_invalid", "plugin contracts are invalid"))?;
    Ok(manifest)
}

/// Bundle v2 signs the domain representation, including explicit absent typed optional fields.
/// This differs from snapshot hashing, which signs the wire representation directly.
pub fn bundle_manifest_digest_v2(
    bundle: &BundleManifestV2,
) -> Result<String, BundleArchiveV2Error> {
    let mut value = serde_json::to_value(bundle)
        .map_err(|_| reject("bundle_descriptor_invalid", "descriptor cannot serialize"))?;
    value.as_object_mut().unwrap().remove("digest");
    value.as_object_mut().unwrap().remove("signature");
    const SCOPE: &[&str] = &["tenant_id", "project_id", "session_id"];
    const QUOTAS: &[&str] = &[
        "max_wasm_fuel",
        "max_wasm_memory_bytes",
        "max_wall_time_ms",
        "max_concurrent_calls",
        "max_output_bytes",
        "max_network_requests_per_minute",
        "max_storage_bytes",
        "max_monthly_usd_micros",
    ];
    fn absent_fields(value: &mut Value, fields: &[&str]) {
        let object = value.as_object_mut().expect("typed scope or quota object");
        for field in fields {
            object.entry((*field).to_owned()).or_insert(Value::Null);
        }
    }
    for manifest in value["manifests"].as_array_mut().unwrap() {
        absent_fields(&mut manifest["quotas"], QUOTAS);
        for module in manifest["modules"].as_array_mut().unwrap() {
            absent_fields(&mut module["artifact"], &["signature", "provenance"]);
            for requirement in module["contract"]["services"]["requires"]
                .as_array_mut()
                .unwrap()
            {
                absent_fields(requirement, &["contributes"]);
            }
        }
    }
    for layer in value["layers"].as_array_mut().unwrap() {
        absent_fields(&mut layer["scope"], SCOPE);
        for collection in ["entries", "replacements"] {
            for entry in layer[collection].as_array_mut().unwrap() {
                absent_fields(&mut entry["scope"], SCOPE);
                absent_fields(&mut entry["quotas"], QUOTAS);
            }
        }
    }
    let canonical = serde_jcs::to_vec(&value).map_err(|_| {
        reject(
            "bundle_descriptor_invalid",
            "descriptor cannot canonicalize",
        )
    })?;
    Ok(format!("sha256:{:x}", Sha256::digest(canonical)))
}

pub(super) fn validate_admission(
    bundle: &BundleManifestV2,
    approved: &BTreeSet<String>,
) -> Result<(), BundleArchiveV2Error> {
    let catalog: Value = serde_json::from_str(PLUGIN_MODULE_CATALOG_V2_JSON)
        .map_err(|_| reject("bundle_catalog_unavailable", "builtin catalog is invalid"))?;
    let builtin = catalog["modules"].as_array().ok_or_else(|| {
        reject(
            "bundle_catalog_unavailable",
            "builtin catalog lacks modules",
        )
    })?;
    let mut module_refs = BTreeSet::new();
    for manifest in &bundle.manifests {
        if manifest.trust == TrustKindV2::Builtin
            || builtin
                .iter()
                .any(|module| module["plugin_id"] == manifest.plugin_id)
        {
            return Err(reject(
                "bundle_builtin_namespace_forbidden",
                "external bundle cannot own builtin plugin",
            ));
        }
        if manifest
            .permissions
            .iter()
            .any(|permission| !approved.contains(permission))
        {
            return Err(reject(
                "bundle_permission_not_approved",
                "plugin permission lacks approval",
            ));
        }
        for module in &manifest.modules {
            if !module_refs.insert(&module.module_ref) {
                return Err(reject(
                    "duplicate_module_ref",
                    "bundle repeats module identity",
                ));
            }
            if module.module_ref.starts_with("builtin://")
                || module.artifact.source.starts_with("builtin://")
                || builtin
                    .iter()
                    .any(|item| item["module_ref"] == module.module_ref)
            {
                return Err(reject(
                    "bundle_builtin_namespace_forbidden",
                    "external bundle cannot shadow builtin module",
                ));
            }
            for target in &module.targets {
                if !bundle.artifacts.iter().any(|artifact| {
                    &artifact.target == target && artifact.digest == module.artifact.digest
                }) {
                    return Err(reject(
                        "bundle_artifact_coverage_missing",
                        "module lacks exact target and digest artifact",
                    ));
                }
            }
        }
    }
    let mut layer_ids = BTreeSet::new();
    for layer in &bundle.layers {
        if !layer_ids.insert(&layer.layer_id) {
            return Err(reject(
                "duplicate_layer_id",
                "bundle repeats layer identity",
            ));
        }
        for entry in layer.entries.iter().chain(&layer.replacements) {
            let owner = bundle
                .manifests
                .iter()
                .find(|manifest| {
                    manifest.plugin_id == entry.plugin_ref
                        && manifest
                            .modules
                            .iter()
                            .any(|module| module.module_ref == entry.module_ref)
                })
                .ok_or_else(|| {
                    reject(
                        "bundle_entry_owner_mismatch",
                        "entry belongs to another bundle",
                    )
                })?;
            if entry.permissions.iter().any(|permission| {
                !owner.permissions.contains(permission) || !approved.contains(permission)
            }) {
                return Err(reject(
                    "bundle_permission_not_approved",
                    "entry permission exceeds plugin approval",
                ));
            }
        }
    }
    Ok(())
}
