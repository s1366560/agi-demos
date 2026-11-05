//! User-owned meetings are durable records, never children of agent runs.
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Owner {
    pub user_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub device_id: String,
}

#[derive(Clone, Deserialize, Serialize)]
pub(super) struct Session {
    pub owner: Owner,
    pub audio_session_id: String,
    pub generation: u64,
    pub mode: String,
    pub source: String,
    pub state: String,
    pub started_at: String,
    pub captured_ms: u64,
    pub max_duration_ms: u64,
    pub segments: Vec<Value>,
    #[serde(default)]
    pub transcript: Vec<Value>,
    #[serde(default)]
    pub summary: Option<Value>,
    #[serde(default)]
    pub provider_profile_id: Option<String>,
    #[serde(default)]
    pub sync_audio: bool,
    #[serde(default)]
    pub private_root: Option<String>,
    #[serde(default)]
    pub error_code: Option<String>,
}
impl Session {
    pub fn public(&self) -> Value {
        let mut value = json!(self);
        if let Some(object) = value.as_object_mut() {
            object.remove("private_root");
            object.remove("owner");
        }
        if let Some(segments) = value["segments"].as_array_mut() {
            for segment in segments {
                if let Some(object) = segment.as_object_mut() {
                    object.remove("url");
                    object.remove("path");
                }
            }
        }
        value
    }
}

pub(super) fn initialize(db: &Connection) -> Result<(), String> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS desktop_audio_sessions_v1 (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,
        device_id TEXT NOT NULL,generation INTEGER NOT NULL,state TEXT NOT NULL,value_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS desktop_speech_jobs_v1 (
        id TEXT PRIMARY KEY,session_id TEXT NOT NULL,generation INTEGER NOT NULL,segment_id TEXT NOT NULL,
        operation TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
        result_json TEXT,UNIQUE(session_id,generation,segment_id,operation));")
        .map_err(|_| "audio_session_store_unavailable".into())
}

pub(super) fn list(db: &Connection, owner: &Owner) -> Result<Vec<Session>, String> {
    let mut query = db
        .prepare(
            "SELECT value_json FROM desktop_audio_sessions_v1
        WHERE user_id=?1 AND tenant_id=?2 AND project_id=?3 AND device_id=?4 ORDER BY rowid DESC",
        )
        .map_err(|_| "audio_session_store_unavailable")?;
    let rows = query
        .query_map(
            params![
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id
            ],
            |row| row.get::<_, String>(0),
        )
        .map_err(|_| "audio_session_store_unavailable")?;
    rows.map(|row| {
        serde_json::from_str(&row.map_err(|_| "audio_session_store_unavailable")?)
            .map_err(|_| "audio_session_record_invalid".into())
    })
    .collect()
}

pub(super) fn get(db: &Connection, owner: &Owner, id: &str) -> Result<Session, String> {
    let value: Option<String> = db
        .query_row(
            "SELECT value_json FROM desktop_audio_sessions_v1
        WHERE id=?1 AND user_id=?2 AND tenant_id=?3 AND project_id=?4 AND device_id=?5",
            params![
                id,
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id
            ],
            |row| row.get(0),
        )
        .optional()
        .map_err(|_| "audio_session_store_unavailable")?;
    serde_json::from_str(&value.ok_or("audio_session_not_found")?)
        .map_err(|_| "audio_session_record_invalid".into())
}

pub(super) fn save(db: &Connection, session: &Session) -> Result<(), String> {
    let changed = db.execute("INSERT INTO desktop_audio_sessions_v1 VALUES(?1,?2,?3,?4,?5,?6,?7,?8)
        ON CONFLICT(id) DO UPDATE SET generation=excluded.generation,state=excluded.state,value_json=excluded.value_json
        WHERE user_id=excluded.user_id AND tenant_id=excluded.tenant_id AND project_id=excluded.project_id
        AND device_id=excluded.device_id AND generation<=excluded.generation",
        params![session.audio_session_id,session.owner.user_id,session.owner.tenant_id,session.owner.project_id,
            session.owner.device_id,session.generation,session.state,serde_json::to_string(session).map_err(|_| "audio_session_record_invalid")?])
        .map_err(|_| "audio_session_store_unavailable")?;
    if changed != 1 {
        return Err("audio_session_generation_stale".into());
    }
    Ok(())
}

pub(super) fn recover(db: &Connection) -> Result<(), String> {
    let mut query = db.prepare("SELECT value_json FROM desktop_audio_sessions_v1 WHERE state IN ('recording','starting','stopping')")
        .map_err(|_| "audio_session_store_unavailable")?;
    let rows = query
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(|_| "audio_session_store_unavailable")?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| "audio_session_store_unavailable")?;
    drop(query);
    for row in rows {
        let mut session: Session =
            serde_json::from_str(&row).map_err(|_| "audio_session_record_invalid")?;
        session.state = "interrupted".into();
        session.error_code = Some("process_ended".into());
        save(db, &session)?;
    }
    db.execute(
        "UPDATE desktop_speech_jobs_v1 SET status='pending' WHERE status='processing'",
        [],
    )
    .map_err(|_| "audio_session_store_unavailable")?;
    Ok(())
}

pub(super) fn enqueue(db: &Connection, session: &Session, segment: &Value) -> Result<(), String> {
    if session.provider_profile_id.is_none() {
        return Ok(());
    }
    let id = segment["segment_id"]
        .as_str()
        .ok_or("audio_segment_invalid")?;
    db.execute("INSERT OR IGNORE INTO desktop_speech_jobs_v1(id,session_id,generation,segment_id,operation)
        VALUES(?1,?2,?3,?4,'transcribe')", params![uuid::Uuid::new_v4().to_string(),session.audio_session_id,session.generation,id])
        .map_err(|_| "audio_session_store_unavailable")?;
    Ok(())
}
