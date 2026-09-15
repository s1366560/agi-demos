//! Host-configured signing trust and deterministic project-scoped local profile composition.
use crate::local_plugin_installations_v2::{entry_id, InstalledBundleV2};
use agistack_plugin_host::protocol_v2::{
    signed_archive::{
        verify_signed_bundle_archive_v2, TrustedEd25519KeyV2, VerifiedBundleArchiveV2,
    },
    wasm_runtime::WASM_TOOL_SET_SERVICE_V2,
    BundleManifestV2, BundleReferenceV2, DataPlaneTargetV2, ProfileSnapshotV2, ScopeKindV2,
    ScopeV2,
};
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    io::{Cursor, Read},
};

pub(crate) const MAX_ARCHIVE_BYTES: usize = 64 * 1024 * 1024;
const MAX_TRUST_BYTES: u64 = 1024 * 1024;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustFile {
    schema_version: u32,
    public_keys_pem: Vec<String>,
}

pub(crate) fn trusted_keys() -> Result<Vec<TrustedEd25519KeyV2>, String> {
    let Some(path) = std::env::var_os("AGISTACK_LOCAL_PLUGIN_TRUSTED_KEYS_FILE") else {
        return Ok(vec![]);
    };
    let mut file = std::fs::File::open(path).map_err(|_| "local signing trust file unavailable")?;
    if file
        .metadata()
        .map_err(|_| "local signing trust file unreadable")?
        .len()
        > MAX_TRUST_BYTES
    {
        return Err("local signing trust file exceeds limit".into());
    }
    let mut bytes = vec![];
    file.by_ref()
        .take(MAX_TRUST_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "local signing trust file unreadable")?;
    if bytes.len() as u64 > MAX_TRUST_BYTES {
        return Err("local signing trust file exceeds limit".into());
    }
    let trust: TrustFile =
        serde_json::from_slice(&bytes).map_err(|_| "local signing trust file invalid")?;
    if trust.schema_version != 1 || trust.public_keys_pem.len() > 64 {
        return Err("local signing trust schema invalid".into());
    }
    trust
        .public_keys_pem
        .iter()
        .map(|pem| TrustedEd25519KeyV2::from_spki_pem(pem).map_err(|error| error.to_string()))
        .collect()
}

/// Descriptor data supplies only the claimed identity; this returns only after real verification.
/// Using declared permissions here enables preview, not installation or runtime authority.
pub(crate) fn inspect(
    raw: &[u8],
    keys: &[TrustedEd25519KeyV2],
) -> Result<VerifiedBundleArchiveV2, String> {
    if raw.len() > MAX_ARCHIVE_BYTES {
        return Err("local plugin archive exceeds limit".into());
    }
    let mut zip =
        zip::ZipArchive::new(Cursor::new(raw)).map_err(|_| "local plugin archive invalid")?;
    let descriptor = zip
        .by_name("bundle.json")
        .map_err(|_| "local plugin descriptor missing")?;
    let mut bytes = vec![];
    descriptor
        .take(2 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "local plugin descriptor unreadable")?;
    if bytes.len() > 2 * 1024 * 1024 {
        return Err("local plugin descriptor exceeds limit".into());
    }
    let manifest: BundleManifestV2 =
        serde_json::from_slice(&bytes).map_err(|_| "local plugin descriptor invalid")?;
    let reference = BundleReferenceV2 {
        bundle_id: manifest.bundle_id.clone(),
        version: manifest.version.clone(),
        digest: manifest.digest.clone(),
        source: format!("local-file://{}/{}", manifest.bundle_id, manifest.version),
    };
    let permissions: BTreeSet<_> = manifest
        .manifests
        .iter()
        .flat_map(|item| item.permissions.iter().cloned())
        .collect();
    verify_signed_bundle_archive_v2(raw, &reference, keys, &permissions)
        .map_err(|error| error.to_string())
}

pub(crate) fn compose(
    base: &ProfileSnapshotV2,
    installations: Vec<InstalledBundleV2>,
    revision: u64,
) -> Result<(ProfileSnapshotV2, Value, Vec<VerifiedBundleArchiveV2>), String> {
    let mut snapshot = base.clone();
    let mut archives: Vec<VerifiedBundleArchiveV2> = vec![];
    for installation in installations {
        let archive = installation.archive;
        let mut local_entries = 0;
        for layer in &archive.manifest().layers {
            for original in &layer.entries {
                let Some(manifest) = archive
                    .manifest()
                    .manifests
                    .iter()
                    .find(|item| item.plugin_id == original.plugin_ref)
                else {
                    return Err("local plugin entry owner missing".into());
                };
                let Some(module) = manifest
                    .modules
                    .iter()
                    .find(|item| item.module_ref == original.module_ref)
                else {
                    return Err("local plugin entry module missing".into());
                };
                if !module.targets.contains(&DataPlaneTargetV2::DesktopSidecar) {
                    continue;
                }
                archive
                    .wasm_artifact(
                        &manifest.plugin_id,
                        &module.module_ref,
                        DataPlaneTargetV2::DesktopSidecar,
                    )
                    .map_err(|error| error.to_string())?;
                if original.parent_entry_id.is_some()
                    || !original.inject.is_empty()
                    || !original.isolate.is_empty()
                    || !scope_contains_project(&original.scope, &installation.scope)
                {
                    return Err("local standalone WASM entry topology or scope unsupported".into());
                }
                if let Some(existing) = snapshot
                    .manifests
                    .iter()
                    .find(|item| item.plugin_id == manifest.plugin_id)
                {
                    if existing != manifest {
                        return Err("local plugin manifest ownership conflict".into());
                    }
                } else {
                    snapshot.manifests.push(manifest.clone());
                }
                let mut entry = original.clone();
                entry.entry_id =
                    entry_id(&installation.scope, archive.reference(), &original.entry_id);
                entry.scope = installation.scope.clone();
                entry
                    .isolate
                    .insert(WASM_TOOL_SET_SERVICE_V2.into(), entry.entry_id.clone());
                snapshot.entries.push(entry);
                local_entries += 1;
            }
        }
        if local_entries == 0 {
            return Err("local installation has no desktop-sidecar WASM entry".into());
        }
        if !archives
            .iter()
            .any(|item| item.reference() == archive.reference())
        {
            archives.push(archive);
        }
    }
    snapshot.generation = snapshot
        .generation
        .checked_add(revision)
        .filter(|value| *value <= 9_007_199_254_740_991)
        .ok_or("local plugin generation exhausted")?;
    let mut wire = serde_json::to_value(&snapshot).map_err(|error| error.to_string())?;
    wire.as_object_mut()
        .ok_or("local profile invalid")?
        .remove("digest");
    wire["digest"] = format!(
        "{:x}",
        Sha256::digest(serde_jcs::to_vec(&wire).map_err(|error| error.to_string())?)
    )
    .into();
    let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&wire.to_string())
        .map_err(|error| error.to_string())?;
    Ok((snapshot, wire, archives))
}

fn scope_contains_project(parent: &ScopeV2, child: &ScopeV2) -> bool {
    match parent.kind {
        ScopeKindV2::Root => true,
        ScopeKindV2::Tenant => parent.tenant_id == child.tenant_id,
        ScopeKindV2::Project => parent == child,
        _ => false,
    }
}
