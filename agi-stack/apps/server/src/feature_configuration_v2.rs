//! Read accepted private-scope feature configuration from the shared publication ledger.

use std::collections::{BTreeMap, BTreeSet};

use agistack_plugin_host::{
    protocol_v2::{ProfileEntryV2, ProfileSourceV2},
    ScopeKindV2, ScopeV2,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use sqlx::PgPool;

use crate::feature_operation_v2::FeatureAdmissionErrorV2;

pub(crate) enum AcceptedFeatureConfigurationV2 {
    Standalone,
    Source(Value),
    Snapshot(Value),
}

#[derive(sqlx::FromRow)]
struct AppliedSourceRow {
    applied_publication_id: Option<String>,
    applied_version: Option<i64>,
    applied_digest: Option<String>,
    requested_version: Option<i64>,
    snapshot_digest: Option<String>,
    distribution: Option<Value>,
    desired: Option<Value>,
    source: Option<Value>,
}

pub(crate) async fn read_accepted_configuration(
    pool: &PgPool,
    scope: &ScopeV2,
) -> Result<AcceptedFeatureConfigurationV2, FeatureAdmissionErrorV2> {
    // Rust-only installations can have no shared publication ledger at all.
    // A successful catalog query establishes that mode; partial schemas and
    // all database errors fail closed instead of silently restoring defaults.
    let tables: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM unnest(ARRAY[\
         'platform_plugin_v2_apply_states', 'platform_plugin_v2_publications', \
         'platform_plugin_v2_publication_sources', 'platform_plugin_v2_profile_sources', \
         'platform_plugin_v2_desired_bundle_sets']) AS names(name) \
         WHERE to_regclass(name) IS NOT NULL",
    )
    .fetch_one(pool)
    .await
    .map_err(|_| FeatureAdmissionErrorV2::unavailable())?;
    if !has_shared_ledger(tables)? {
        return Ok(AcceptedFeatureConfigurationV2::Standalone);
    }
    let kind = scope_kind(scope);
    let row = sqlx::query_as::<_, AppliedSourceRow>(
        "SELECT a.applied_publication_id, a.applied_version, a.applied_digest, \
         p.requested_version, p.snapshot_digest, p.distribution, d.payload AS desired, \
         s.payload AS source FROM platform_plugin_v2_apply_states a \
         LEFT JOIN platform_plugin_v2_publications p \
           ON p.id = a.applied_publication_id AND p.scope_key = a.scope_key \
         LEFT JOIN platform_plugin_v2_publication_sources d \
           ON d.publication_id = p.id AND d.scope_key = a.scope_key \
         LEFT JOIN platform_plugin_v2_profile_sources s ON s.scope_key = a.scope_key \
           AND s.source_id = d.payload->'profile_source'->>'source_id' \
           AND s.revision = (d.payload->'profile_source'->>'revision')::bigint \
           AND s.digest = d.payload->'profile_source'->>'digest' \
         WHERE a.data_plane_id = 'python-api-v2' AND a.scope_kind = $1 \
           AND a.tenant_id IS NOT DISTINCT FROM $2 \
           AND a.project_id IS NOT DISTINCT FROM $3 AND a.session_id IS NULL",
    )
    .bind(kind)
    .bind(&scope.tenant_id)
    .bind(&scope.project_id)
    .fetch_optional(pool)
    .await
    .map_err(|_| FeatureAdmissionErrorV2::unavailable())?;
    let Some(row) = row else {
        return Err(FeatureAdmissionErrorV2::unavailable());
    };
    decode_accepted_configuration(scope, row)
}

fn decode_accepted_configuration(
    scope: &ScopeV2,
    row: AppliedSourceRow,
) -> Result<AcceptedFeatureConfigurationV2, FeatureAdmissionErrorV2> {
    if row.applied_publication_id.is_none()
        || row.applied_version != row.requested_version
        || row.applied_digest != row.snapshot_digest
    {
        return Err(FeatureAdmissionErrorV2::unavailable());
    }
    match (row.desired, row.source, row.distribution) {
        (Some(desired), Some(source), _) => {
            let reference = &desired["profile_source"];
            for key in ["source_id", "revision", "digest"] {
                if source.get(key) != reference.get(key) || source.get(key).is_none() {
                    return Err(FeatureAdmissionErrorV2::unavailable());
                }
            }
            verify_source_digest(&source)?;
            Ok(AcceptedFeatureConfigurationV2::Source(source))
        }
        // Root bootstrap publications predate scope-private source bindings.
        (None, None, Some(distribution)) if scope.kind == ScopeKindV2::Root => {
            let snapshot = distribution
                .get("snapshot")
                .cloned()
                .ok_or_else(FeatureAdmissionErrorV2::unavailable)?;
            if snapshot["digest"].as_str() != row.applied_digest.as_deref() {
                return Err(FeatureAdmissionErrorV2::unavailable());
            }
            Ok(AcceptedFeatureConfigurationV2::Snapshot(snapshot))
        }
        _ => Err(FeatureAdmissionErrorV2::unavailable()),
    }
}

fn has_shared_ledger(table_count: i64) -> Result<bool, FeatureAdmissionErrorV2> {
    match table_count {
        0 => Ok(false),
        5 => Ok(true),
        _ => Err(FeatureAdmissionErrorV2::unavailable()),
    }
}

fn verify_source_digest(source: &Value) -> Result<(), FeatureAdmissionErrorV2> {
    let typed: ProfileSourceV2 = serde_json::from_value(source.clone())
        .map_err(|_| FeatureAdmissionErrorV2::unavailable())?;
    let mut payload =
        serde_json::to_value(typed).map_err(|_| FeatureAdmissionErrorV2::unavailable())?;
    // Python source identities hash dataclass values, including nullable schema
    // fields that the compact wire representation omits. Normalize only these
    // declared fields; arbitrary instance config remains byte-for-byte semantic JSON.
    for layer in payload["layers"]
        .as_array_mut()
        .ok_or_else(FeatureAdmissionErrorV2::unavailable)?
    {
        normalize_scope(&mut layer["scope"])?;
        for field in ["entries", "replacements"] {
            for entry in layer[field]
                .as_array_mut()
                .ok_or_else(FeatureAdmissionErrorV2::unavailable)?
            {
                normalize_scope(&mut entry["scope"])?;
                let quotas = entry["quotas"]
                    .as_object_mut()
                    .ok_or_else(FeatureAdmissionErrorV2::unavailable)?;
                for field in [
                    "max_wasm_fuel",
                    "max_wasm_memory_bytes",
                    "max_wall_time_ms",
                    "max_concurrent_calls",
                    "max_output_bytes",
                    "max_network_requests_per_minute",
                    "max_storage_bytes",
                    "max_monthly_usd_micros",
                ] {
                    quotas.entry(field).or_insert(Value::Null);
                }
            }
        }
    }
    let object = payload
        .as_object_mut()
        .ok_or_else(FeatureAdmissionErrorV2::unavailable)?;
    let digest = object
        .remove("digest")
        .ok_or_else(FeatureAdmissionErrorV2::unavailable)?;
    let canonical =
        serde_jcs::to_vec(&payload).map_err(|_| FeatureAdmissionErrorV2::unavailable())?;
    if digest.as_str() != Some(format!("sha256:{:x}", Sha256::digest(canonical)).as_str()) {
        return Err(FeatureAdmissionErrorV2::unavailable());
    }
    Ok(())
}

fn normalize_scope(scope: &mut Value) -> Result<(), FeatureAdmissionErrorV2> {
    let scope = scope
        .as_object_mut()
        .ok_or_else(FeatureAdmissionErrorV2::unavailable)?;
    for field in ["tenant_id", "project_id", "session_id"] {
        scope.entry(field).or_insert(Value::Null);
    }
    Ok(())
}

pub(crate) fn feature_entries(
    accepted: AcceptedFeatureConfigurationV2,
    scope: &ScopeV2,
) -> Result<BTreeMap<String, ProfileEntryV2>, FeatureAdmissionErrorV2> {
    let mut entries = BTreeMap::new();
    match accepted {
        AcceptedFeatureConfigurationV2::Source(payload) => {
            let source: ProfileSourceV2 = serde_json::from_value(payload)
                .map_err(|_| FeatureAdmissionErrorV2::unavailable())?;
            for layer in source.layers {
                if !contains_scope(&layer.scope, scope) {
                    continue;
                }
                // Feature declarations and their ancestors are in ProfileSource.
                // Bundle-owned entries are not needed to infer feature ownership.
                for entry in layer.entries.into_iter().chain(layer.replacements) {
                    entries.insert(entry.entry_id.clone(), entry);
                }
                for id in layer.disabled_entry_ids {
                    if let Some(entry) = entries.get_mut(&id) {
                        entry.enabled = false;
                    }
                }
            }
        }
        AcceptedFeatureConfigurationV2::Snapshot(snapshot) => {
            let rows: Vec<ProfileEntryV2> = serde_json::from_value(snapshot["entries"].clone())
                .map_err(|_| FeatureAdmissionErrorV2::unavailable())?;
            entries.extend(
                rows.into_iter()
                    .map(|entry| (entry.entry_id.clone(), entry)),
            );
        }
        AcceptedFeatureConfigurationV2::Standalone => {
            return Err(FeatureAdmissionErrorV2::unavailable());
        }
    }
    Ok(entries)
}

pub(crate) fn require_enabled(
    entries: &BTreeMap<String, ProfileEntryV2>,
    feature_ids: &[&str],
) -> Result<(), FeatureAdmissionErrorV2> {
    for feature in feature_ids {
        let id = format!("builtin-web-feature-{feature}");
        let initial = if entries.contains_key(&id) {
            id.as_str()
        } else {
            "builtin-web-default-routes"
        };
        let mut current = Some(initial);
        let mut seen = BTreeSet::new();
        while let Some(id) = current {
            if !seen.insert(id) {
                return Err(FeatureAdmissionErrorV2::unavailable());
            }
            let entry = entries
                .get(id)
                .ok_or_else(FeatureAdmissionErrorV2::disabled)?;
            if !entry.enabled {
                return Err(FeatureAdmissionErrorV2::disabled());
            }
            current = entry.parent_entry_id.as_deref();
        }
    }
    Ok(())
}

fn contains_scope(parent: &ScopeV2, child: &ScopeV2) -> bool {
    (parent.tenant_id.is_none() || parent.tenant_id == child.tenant_id)
        && (parent.project_id.is_none() || parent.project_id == child.project_id)
        && (parent.session_id.is_none() || parent.session_id == child.session_id)
}

pub(crate) const fn scope_kind(scope: &ScopeV2) -> &'static str {
    match scope.kind {
        ScopeKindV2::Root => "root",
        ScopeKindV2::Tenant => "tenant",
        ScopeKindV2::Project => "project",
        ScopeKindV2::Session => "session",
    }
}

#[cfg(test)]
#[path = "feature_configuration_v2_tests.rs"]
mod tests;
