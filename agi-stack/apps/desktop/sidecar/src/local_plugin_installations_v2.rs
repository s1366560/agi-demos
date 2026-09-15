//! Local installation governance. Trust anchors come from the host, never from an import request.
//! Persist bytes and approvals, not a reusable verification proof; every activation re-verifies.

use agistack_plugin_host::protocol_v2::{
    signed_archive::{
        verify_signed_bundle_archive_v2, TrustedEd25519KeyV2, VerifiedBundleArchiveV2,
    },
    BundleReferenceV2, ScopeKindV2, ScopeV2,
};
use rusqlite::{params, Connection, OptionalExtension};
use std::collections::BTreeSet;

pub(crate) struct InstalledBundleV2 {
    pub(crate) scope: ScopeV2,
    pub(crate) archive: VerifiedBundleArchiveV2,
}

fn error(value: impl std::fmt::Display) -> String {
    value.to_string()
}

pub(crate) fn initialize(db: &Connection) -> Result<(), String> {
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS desktop_local_plugin_installations_v2 (
        tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, bundle_id TEXT NOT NULL,
        reference_json TEXT NOT NULL, archive BLOB NOT NULL, permissions_json TEXT NOT NULL,
        enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
        revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
        PRIMARY KEY (tenant_id, project_id, bundle_id)
    );
    CREATE TABLE IF NOT EXISTS desktop_local_plugin_revision_v2 (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
    INSERT OR IGNORE INTO desktop_local_plugin_revision_v2 VALUES(1,0);
    CREATE TRIGGER IF NOT EXISTS local_plugin_insert_v2 AFTER INSERT ON desktop_local_plugin_installations_v2 BEGIN UPDATE desktop_local_plugin_revision_v2 SET revision=revision+1 WHERE id=1; END;
    CREATE TRIGGER IF NOT EXISTS local_plugin_update_v2 AFTER UPDATE ON desktop_local_plugin_installations_v2 BEGIN UPDATE desktop_local_plugin_revision_v2 SET revision=revision+1 WHERE id=1; END;
    CREATE TRIGGER IF NOT EXISTS local_plugin_delete_v2 AFTER DELETE ON desktop_local_plugin_installations_v2 BEGIN UPDATE desktop_local_plugin_revision_v2 SET revision=revision+1 WHERE id=1; END;",
    )
    .map_err(error)
}

fn scope_ids(scope: &ScopeV2) -> Result<(&str, &str), String> {
    if scope.kind != ScopeKindV2::Project || scope.session_id.is_some() {
        return Err("local plugin installation requires an exact project scope".into());
    }
    let tenant = scope.tenant_id.as_deref().unwrap_or_default();
    let project = scope.project_id.as_deref().unwrap_or_default();
    if [tenant, project]
        .iter()
        .any(|id| id.is_empty() || id.len() > 255 || id.trim() != *id)
    {
        return Err("local plugin installation scope is invalid".into());
    }
    Ok((tenant, project))
}

/// Caller must authorize the owning project's resource manager before granting permissions.
/// Successful verification precedes the single atomic replacement; failed imports preserve state.
pub(crate) fn install(
    db: &Connection,
    keys: &[TrustedEd25519KeyV2],
    scope: &ScopeV2,
    reference: &BundleReferenceV2,
    raw: &[u8],
    permissions: &BTreeSet<String>,
) -> Result<(), String> {
    let (tenant, project) = scope_ids(scope)?;
    let archive =
        verify_signed_bundle_archive_v2(raw, reference, keys, permissions).map_err(error)?;
    let declared: BTreeSet<_> = archive
        .manifest()
        .manifests
        .iter()
        .flat_map(|manifest| manifest.permissions.iter().cloned())
        .collect();
    if !permissions.is_subset(&declared) {
        return Err("local plugin approval includes undeclared permissions".into());
    }
    db.execute(
        "INSERT INTO desktop_local_plugin_installations_v2
        (tenant_id,project_id,bundle_id,reference_json,archive,permissions_json,enabled)
        VALUES (?1,?2,?3,?4,?5,?6,1)
        ON CONFLICT(tenant_id,project_id,bundle_id) DO UPDATE SET
        reference_json=excluded.reference_json,archive=excluded.archive,
        permissions_json=excluded.permissions_json,enabled=1,revoked=0",
        params![
            tenant,
            project,
            reference.bundle_id,
            serde_json::to_string(reference).map_err(error)?,
            raw,
            serde_json::to_string(permissions).map_err(error)?
        ],
    )
    .map_err(error)?;
    Ok(())
}

struct StoredBundle {
    reference: BundleReferenceV2,
    raw: Vec<u8>,
    permissions: BTreeSet<String>,
    enabled: bool,
    revoked: bool,
}
fn stored(
    db: &Connection,
    scope: &ScopeV2,
    reference: &BundleReferenceV2,
) -> Result<StoredBundle, String> {
    let (tenant, project) = scope_ids(scope)?;
    let result = db.query_row("SELECT reference_json,archive,permissions_json,enabled,revoked
        FROM desktop_local_plugin_installations_v2 WHERE tenant_id=?1 AND project_id=?2 AND bundle_id=?3",
        params![tenant,project,reference.bundle_id], |row| Ok((row.get::<_,String>(0)?,row.get::<_,Vec<u8>>(1)?,row.get::<_,String>(2)?,row.get::<_,bool>(3)?,row.get::<_,bool>(4)?)))
        .optional().map_err(error)?.ok_or("local plugin installation not found")?;
    let actual: BundleReferenceV2 = serde_json::from_str(&result.0).map_err(error)?;
    if actual != *reference {
        return Err("local plugin installation identity changed".into());
    }
    Ok(StoredBundle {
        reference: actual,
        raw: result.1,
        permissions: serde_json::from_str(&result.2).map_err(error)?,
        enabled: result.3,
        revoked: result.4,
    })
}

/// Reading enabled installations fails closed on damaged state or a withdrawn trust anchor.
pub(crate) fn load_enabled(
    db: &Connection,
    keys: &[TrustedEd25519KeyV2],
) -> Result<Vec<InstalledBundleV2>, String> {
    let mut query = db.prepare("SELECT tenant_id,project_id,reference_json,archive,permissions_json FROM desktop_local_plugin_installations_v2 WHERE enabled=1 AND revoked=0 ORDER BY tenant_id,project_id,bundle_id").map_err(error)?;
    let rows = query
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Vec<u8>>(3)?,
                row.get::<_, String>(4)?,
            ))
        })
        .map_err(error)?;
    rows.map(|row| {
        let (tenant, project, reference, raw, permissions) = row.map_err(error)?;
        let reference = serde_json::from_str(&reference).map_err(error)?;
        let permissions = serde_json::from_str(&permissions).map_err(error)?;
        let scope = ScopeV2 {
            kind: ScopeKindV2::Project,
            tenant_id: Some(tenant),
            project_id: Some(project),
            session_id: None,
        };
        scope_ids(&scope)?;
        Ok(InstalledBundleV2 {
            scope,
            archive: verify_signed_bundle_archive_v2(&raw, &reference, keys, &permissions)
                .map_err(error)?,
        })
    })
    .collect()
}

pub(crate) fn set_enabled(
    db: &Connection,
    keys: &[TrustedEd25519KeyV2],
    scope: &ScopeV2,
    reference: &BundleReferenceV2,
    enabled: bool,
) -> Result<(), String> {
    let row = stored(db, scope, reference)?;
    if enabled {
        if row.revoked {
            return Err("local plugin approval has been revoked".into());
        }
        verify_signed_bundle_archive_v2(&row.raw, &row.reference, keys, &row.permissions)
            .map_err(error)?;
    }
    update(
        db,
        scope,
        reference,
        if enabled { "enabled=1" } else { "enabled=0" },
    )
}
pub(crate) fn revoke(
    db: &Connection,
    scope: &ScopeV2,
    reference: &BundleReferenceV2,
) -> Result<(), String> {
    stored(db, scope, reference)?;
    update(
        db,
        scope,
        reference,
        "enabled=0,revoked=1,permissions_json='[]'",
    )
}
fn update(
    db: &Connection,
    scope: &ScopeV2,
    reference: &BundleReferenceV2,
    assignment: &str,
) -> Result<(), String> {
    let (tenant, project) = scope_ids(scope)?;
    let changed = db.execute(&format!("UPDATE desktop_local_plugin_installations_v2 SET {assignment} WHERE tenant_id=?1 AND project_id=?2 AND bundle_id=?3 AND reference_json=?4"),
        params![tenant,project,reference.bundle_id,serde_json::to_string(reference).map_err(error)?]).map_err(error)?;
    if changed != 1 {
        return Err("local plugin installation changed".into());
    }
    Ok(())
}
pub(crate) fn uninstall(
    db: &Connection,
    scope: &ScopeV2,
    reference: &BundleReferenceV2,
) -> Result<(), String> {
    let (tenant, project) = scope_ids(scope)?;
    let changed = db.execute("DELETE FROM desktop_local_plugin_installations_v2 WHERE tenant_id=?1 AND project_id=?2 AND bundle_id=?3 AND reference_json=?4",params![tenant,project,reference.bundle_id,serde_json::to_string(reference).map_err(error)?]).map_err(error)?;
    if changed != 1 {
        return Err("local plugin installation not found or changed".into());
    }
    Ok(())
}

#[derive(serde::Serialize)]
pub(crate) struct InstallationSummaryV2 {
    pub reference: BundleReferenceV2,
    pub scope: ScopeV2,
    pub enabled: bool,
    pub approved_permissions: BTreeSet<String>,
    pub authorization_status: &'static str,
}

pub(crate) fn list(db: &Connection, scope: &ScopeV2) -> Result<Vec<InstallationSummaryV2>, String> {
    let (tenant, project) = scope_ids(scope)?;
    let mut query = db.prepare("SELECT reference_json,permissions_json,enabled,revoked FROM desktop_local_plugin_installations_v2 WHERE tenant_id=?1 AND project_id=?2 ORDER BY bundle_id").map_err(error)?;
    let rows = query
        .query_map(params![tenant, project], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, bool>(2)?,
                row.get::<_, bool>(3)?,
            ))
        })
        .map_err(error)?;
    rows.map(|row| {
        let (reference, permissions, enabled, revoked) = row.map_err(error)?;
        Ok(InstallationSummaryV2 {
            reference: serde_json::from_str(&reference).map_err(error)?,
            scope: scope.clone(),
            enabled,
            authorization_status: if revoked { "revoked" } else { "approved" },
            approved_permissions: serde_json::from_str(&permissions).map_err(error)?,
        })
    })
    .collect()
}

/// Stable isolated entry coordinate derived from installation scope and the signed entry ID.
pub(crate) fn entry_id(scope: &ScopeV2, reference: &BundleReferenceV2, original: &str) -> String {
    use sha2::{Digest, Sha256};
    let identity = serde_json::json!([scope, reference, original]);
    format!(
        "local-wasm-{:x}",
        Sha256::digest(identity.to_string().as_bytes())
    )
}

pub(crate) fn authorizes(
    db: &Connection,
    keys: &[TrustedEd25519KeyV2],
    scope: &ScopeV2,
    tool: &agistack_plugin_host::protocol_v2::wasm_runtime::WasmToolAttributionV2,
) -> bool {
    let Ok(row) = stored(db, scope, &tool.bundle) else {
        return false;
    };
    if row.revoked
        || !row.enabled
        || !row.permissions.contains("tools.execute")
        || tool.entry_scope != *scope
    {
        return false;
    }
    let Ok(archive) =
        verify_signed_bundle_archive_v2(&row.raw, &row.reference, keys, &row.permissions)
    else {
        return false;
    };
    let Ok(artifact) = archive.wasm_artifact(
        &tool.plugin_id,
        &tool.module_ref,
        agistack_plugin_host::DataPlaneTargetV2::DesktopSidecar,
    ) else {
        return false;
    };
    artifact.manifest().version == tool.plugin_version
        && artifact.module().artifact.digest == tool.artifact_digest
        && artifact.module().artifact.source == tool.artifact_source
        && archive
            .manifest()
            .layers
            .iter()
            .flat_map(|layer| &layer.entries)
            .any(|entry| {
                entry.enabled
                    && entry.plugin_ref == tool.plugin_id
                    && entry.module_ref == tool.module_ref
                    && entry_id(scope, &tool.bundle, &entry.entry_id) == tool.entry_id
                    && entry
                        .config
                        .get("tool_name")
                        .and_then(serde_json::Value::as_str)
                        == Some(tool.tool_name.as_str())
            })
}

pub(crate) fn revision(db: &Connection) -> Result<u64, String> {
    db.query_row(
        "SELECT revision FROM desktop_local_plugin_revision_v2 WHERE id=1",
        [],
        |row| row.get(0),
    )
    .map_err(error)
}

pub(crate) fn for_activation(
    db: &Connection,
    keys: &[TrustedEd25519KeyV2],
    scope: &ScopeV2,
    reference: &BundleReferenceV2,
) -> Result<InstalledBundleV2, String> {
    let row = stored(db, scope, reference)?;
    if row.revoked {
        return Err("local plugin approval has been revoked".into());
    }
    Ok(InstalledBundleV2 {
        scope: scope.clone(),
        archive: verify_signed_bundle_archive_v2(&row.raw, &row.reference, keys, &row.permissions)
            .map_err(error)?,
    })
}

pub(crate) fn has_enabled(db: &Connection) -> Result<bool, String> {
    db.query_row("SELECT EXISTS(SELECT 1 FROM desktop_local_plugin_installations_v2 WHERE enabled=1 AND revoked=0)",[],|row|row.get(0)).map_err(error)
}
