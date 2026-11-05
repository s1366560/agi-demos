//! Speech credentials are application-vault records, never public profile JSON.
use super::{store::Owner, Operation};
use crate::{application_vault::ApplicationCredentialVault, local_runtime::LocalRuntimeState};
use rusqlite::params;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use zeroize::Zeroizing;

#[derive(Clone, Deserialize, Serialize)]
pub(super) struct Profile {
    pub id: String,
    pub provider: String,
    pub name: String,
    pub app_id: String,
}
pub(super) fn initialize(db: &rusqlite::Connection) -> Result<(), String> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS desktop_speech_profiles_v1(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,device_id TEXT NOT NULL,value_json TEXT NOT NULL);")
        .map_err(|_|"speech_profile_store_unavailable".into())
}
fn vault(state: &LocalRuntimeState) -> Result<ApplicationCredentialVault, String> {
    state
        .audio_sessions
        .vault
        .lock()
        .map_err(|_| "speech_vault_unavailable")?
        .clone()
        .ok_or("speech_vault_unavailable".into())
}
fn binding(owner: &Owner, id: &str) -> String {
    use sha2::{Digest, Sha256};
    let digest = Sha256::digest(serde_json::to_vec(&(owner, id)).unwrap_or_default());
    format!("speech-profile.v1.{digest:x}")
}
pub(super) fn list(state: &LocalRuntimeState, owner: &Owner) -> Result<Vec<Profile>, String> {
    let db = state.session_store.connection()?;
    let mut query=db.prepare("SELECT value_json FROM desktop_speech_profiles_v1 WHERE user_id=?1 AND tenant_id=?2 AND project_id=?3 AND device_id=?4 ORDER BY rowid")
        .map_err(|_|"speech_profile_store_unavailable")?;
    let profiles = query
        .query_map(
            params![
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id
            ],
            |row| row.get::<_, String>(0),
        )
        .map_err(|_| "speech_profile_store_unavailable")?
        .map(|row| {
            serde_json::from_str(&row.map_err(|_| "speech_profile_store_unavailable")?)
                .map_err(|_| "speech_profile_invalid".into())
        })
        .collect();
    profiles
}
pub(super) fn get(
    state: &LocalRuntimeState,
    owner: &Owner,
    id: &str,
) -> Result<(Profile, Zeroizing<String>), String> {
    let profile = list(state, owner)?
        .into_iter()
        .find(|profile| profile.id == id)
        .ok_or("speech_profile_not_found")?;
    let token = vault(state)?
        .get(&binding(owner, id))
        .map_err(|_| "speech_vault_unavailable")?
        .ok_or("speech_credentials_required")?;
    Ok((profile, Zeroizing::new(token)))
}
pub(super) fn configure(
    state: &LocalRuntimeState,
    owner: &Owner,
    operation: &mut Operation,
) -> Result<Value, String> {
    let token = Zeroizing::new(
        operation
            .access_token
            .take()
            .ok_or("speech_credentials_required")?,
    );
    let app_id = operation
        .app_id
        .as_deref()
        .filter(|value| !value.is_empty() && value.len() <= 1024)
        .ok_or("speech_app_id_required")?;
    if token.is_empty() || token.len() > 16_384 {
        return Err("speech_credentials_invalid".into());
    }
    let id = uuid::Uuid::new_v4().to_string();
    let profile = Profile {
        id: id.clone(),
        provider: "volcengine".into(),
        name: operation
            .name
            .clone()
            .filter(|value| !value.is_empty() && value.len() <= 128)
            .unwrap_or_else(|| "Volcengine Speech".into()),
        app_id: app_id.into(),
    };
    vault(state)?
        .put(&binding(owner, &id), token.as_str())
        .map_err(|_| "speech_vault_unavailable")?;
    state
        .session_store
        .connection()?
        .execute(
            "INSERT INTO desktop_speech_profiles_v1 VALUES(?1,?2,?3,?4,?5,?6)",
            params![
                id,
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id,
                json!(profile).to_string()
            ],
        )
        .map_err(|_| "speech_profile_store_unavailable")?;
    Ok(json!(profile))
}
