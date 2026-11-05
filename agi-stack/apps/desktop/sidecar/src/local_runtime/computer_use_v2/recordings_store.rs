//! Durable recording receipts. Native file locations never appear in UI snapshots.
use super::*;
use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};

#[derive(Clone, Deserialize, Serialize)]
pub(super) struct Record {
    pub owner: Owner,
    #[serde(deserialize_with = "recording_context")]
    pub context: CuaCallContext,
    pub root: PathBuf,
    pub native: Value,
    pub receipt: Value,
    #[serde(default)]
    pub acknowledged: bool,
    /// Issued by the engine at audio_start; never accepted from a native receipt.
    #[serde(default)]
    pub engine_session_id: Option<String>,
}

// IPC-2 recordings predate mode selection and used foreground input. This
// compatibility read is limited to durable receipts; IPC-3 remains strict.
fn recording_context<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<CuaCallContext, D::Error> {
    let mut value = Value::deserialize(deserializer)?;
    if let Some(object) = value.as_object_mut() {
        object
            .entry("input_mode")
            .or_insert_with(|| json!("foreground"));
    }
    serde_json::from_value(value).map_err(serde::de::Error::custom)
}

pub(super) fn initialize(db: &rusqlite::Connection) -> Result<(), String> {
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS desktop_cua_recordings_v2 (
        recording_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,
        project_id TEXT NOT NULL,device_id TEXT NOT NULL,record_json TEXT NOT NULL);",
    )
    .map_err(|_| "cua_recording_storage_unavailable".into())
}

pub(super) fn get(state: &LocalRuntimeState, id: &str) -> Result<Option<Record>, String> {
    let raw: Option<String> = state
        .session_store
        .connection()?
        .query_row(
            "SELECT record_json FROM desktop_cua_recordings_v2 WHERE recording_id=?1",
            [id],
            |row| row.get(0),
        )
        .optional()
        .map_err(|_| "cua_recording_storage_unavailable")?;
    raw.map(|raw| serde_json::from_str(&raw).map_err(|_| "cua_recording_invalid".into()))
        .transpose()
}

pub(super) fn save(state: &LocalRuntimeState, record: &Record) -> Result<(), String> {
    let id = record.receipt["recording_id"]
        .as_str()
        .ok_or("cua_recording_invalid")?;
    let serialized = serde_json::to_string(record).map_err(|_| "cua_recording_invalid")?;
    let changed = state
        .session_store
        .connection()?
        .execute(
            "INSERT INTO desktop_cua_recordings_v2 VALUES(?1,?2,?3,?4,?5,?6)
         ON CONFLICT(recording_id) DO UPDATE SET record_json=excluded.record_json
         WHERE user_id=excluded.user_id AND tenant_id=excluded.tenant_id
         AND project_id=excluded.project_id AND device_id=excluded.device_id",
            params![
                id,
                record.owner.user_id,
                record.owner.tenant_id,
                record.owner.project_id,
                record.owner.device_id,
                serialized
            ],
        )
        .map_err(|_| "cua_recording_storage_unavailable")?;
    if changed != 1 {
        return Err("cua_recording_scope_mismatch".into());
    }
    Ok(())
}

pub(super) fn list(state: &LocalRuntimeState, owner: &Owner) -> Result<Vec<Record>, String> {
    let db = state.session_store.connection()?;
    let mut query = db
        .prepare(
            "SELECT record_json FROM desktop_cua_recordings_v2
        WHERE user_id=?1 AND tenant_id=?2 AND project_id=?3 AND device_id=?4 ORDER BY rowid DESC",
        )
        .map_err(|_| "cua_recording_storage_unavailable")?;
    let records = query
        .query_map(
            params![
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id
            ],
            |row| row.get::<_, String>(0),
        )
        .map_err(|_| "cua_recording_storage_unavailable")?
        .map(|row| {
            serde_json::from_str(&row.map_err(|_| "cua_recording_storage_unavailable")?)
                .map_err(|_| "cua_recording_invalid".into())
        })
        .collect();
    records
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn old_recording_context_remains_readable_without_relaxing_the_native_context() {
        let context = json!({"user_id":"u","tenant_id":"t","project_id":"p","device_id":"d","conversation_id":"c","run_id":"r","session_id":"s"});
        assert!(serde_json::from_value::<CuaCallContext>(context.clone()).is_err());
        let record = json!({"owner":{"user_id":"u","tenant_id":"t","project_id":"p","device_id":"d"},"context":context,"root":"/owned/recording","native":{},"receipt":{}});
        let decoded: Record = serde_json::from_value(record.clone()).unwrap();
        assert_eq!(
            decoded.context.input_mode,
            agistack_adapters_cua::CuaInputMode::Foreground
        );
        let mut invalid = record;
        invalid["context"]["input_mode"] = json!("untrusted-backend");
        assert!(serde_json::from_value::<Record>(invalid).is_err());
    }
}
