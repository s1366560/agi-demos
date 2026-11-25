//! A device package has one selected version per cloud origin, account, project, and machine.
use super::*;
use rusqlite::{params, Connection};

pub(super) const SCHEMA: &str = "CREATE TABLE IF NOT EXISTS desktop_cloud_device_plugins_v2 (
    owner TEXT NOT NULL, bundle_id TEXT NOT NULL, selection TEXT NOT NULL, archive BLOB NOT NULL,
    PRIMARY KEY(owner, bundle_id)
)";

#[derive(Deserialize, serde::Serialize, Clone)]
pub(super) struct Selection {
    pub reference: BundleReferenceV2,
    pub grant_id: String,
    pub generation_id: String,
    pub approved_permissions: BTreeSet<String>,
    pub tools: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub workspace: Option<std::path::PathBuf>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub local_model: Option<local_chat::LocalModel>,
    #[serde(default)]
    pub last_invoked_at: Option<String>,
    #[serde(default)]
    pub last_error: Option<String>,
}

pub(super) fn list(db: &Connection, owner: &str) -> Result<Vec<Selection>, String> {
    let mut query = db.prepare("SELECT selection FROM desktop_cloud_device_plugins_v2 WHERE owner=?1 ORDER BY bundle_id")
        .map_err(|_| "device_plugin_store_unavailable")?;
    let rows = query
        .query_map([owner], |row| row.get::<_, String>(0))
        .map_err(|_| "device_plugin_store_unavailable")?;
    rows.map(|row| {
        serde_json::from_str(&row.map_err(|_| "device_plugin_store_unavailable")?)
            .map_err(|_| "device_plugin_store_invalid".into())
    })
    .collect()
}

pub(super) fn install(
    db: &Connection,
    owner: &str,
    selection: &Selection,
    bytes: &[u8],
) -> Result<(), String> {
    let json = serde_json::to_string(selection).map_err(|_| "device_plugin_store_invalid")?;
    db.execute("INSERT INTO desktop_cloud_device_plugins_v2(owner,bundle_id,selection,archive) VALUES(?1,?2,?3,?4)
        ON CONFLICT(owner,bundle_id) DO UPDATE SET selection=excluded.selection,archive=excluded.archive",
        params![owner,selection.reference.bundle_id,json,bytes]).map_err(|_| "device_plugin_store_unavailable")?;
    Ok(())
}

pub(super) fn record_attempt(
    db: &Connection,
    owner: &str,
    selection: &Selection,
    result: &Result<Value, String>,
) -> Result<(), String> {
    let invoked_at = result
        .as_ref()
        .ok()
        .map(|_| chrono::Utc::now().to_rfc3339());
    let error_code = result.as_ref().err().map(|error| {
        if error == "device_plugin_grant_denied" {
            "device_plugin_grant_denied"
        } else {
            "device_plugin_invocation_failed"
        }
    });
    db.execute(
        "UPDATE desktop_cloud_device_plugins_v2
         SET selection=json_set(selection,'$.last_invoked_at',COALESCE(?1,json_extract(selection,'$.last_invoked_at')),'$.last_error',?2)
         WHERE owner=?3 AND bundle_id=?4 AND json_extract(selection,'$.grant_id')=?5
             AND json_extract(selection,'$.generation_id')=?6
             AND json_extract(selection,'$.reference.digest')=?7",
        params![invoked_at,error_code,owner,selection.reference.bundle_id,selection.grant_id,selection.generation_id,selection.reference.digest],
    )
    .map_err(|_| "device_plugin_store_unavailable")?;
    Ok(())
}

pub(super) fn load(
    db: &Connection,
    owner: &str,
    reference: &BundleReferenceV2,
    grant: &str,
) -> Result<(Selection, Vec<u8>), String> {
    let (raw, bytes): (String, Vec<u8>) = db.query_row("SELECT selection,archive FROM desktop_cloud_device_plugins_v2 WHERE owner=?1 AND bundle_id=?2",
        params![owner,reference.bundle_id], |row| Ok((row.get(0)?, row.get(1)?))).map_err(|_| "device_plugin_installation_missing")?;
    let selection: Selection =
        serde_json::from_str(&raw).map_err(|_| "device_plugin_store_invalid")?;
    if selection.reference != *reference || selection.grant_id != grant {
        return Err("device_plugin_installation_changed".into());
    }
    Ok((selection, bytes))
}

pub(super) fn projection(selection: &Selection) -> Value {
    let mut view = json!(selection);
    if let Some(fields) = view.as_object_mut() {
        fields.remove("workspace");
        fields.remove("local_model");
    }
    view
}
