//! User-controlled audio sessions survive agent completion and renderer navigation.
use crate::local_runtime::{LocalRuntimeService, LocalRuntimeState};
use crate::trusted_session::TrustedSessionBroker;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};
mod authority;
mod profiles;
mod store;
#[cfg(test)]
mod tests;
use store::{Owner, Session};

#[derive(Default)]
pub(super) struct Runtime {
    gate: tokio::sync::Mutex<()>,
    pub(super) vault: Mutex<Option<crate::application_vault::ApplicationCredentialVault>>,
    initialized: AtomicBool,
    listening: AtomicBool,
    cloud_owner: Mutex<BTreeMap<(u64, String, String), Owner>>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    mode: String,
    tenant_id: String,
    project_id: String,
    #[serde(default)]
    credential: String,
    operation: Operation,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Operation {
    action: String,
    audio_session_id: Option<String>,
    generation: Option<u64>,
    source: Option<String>,
    max_duration_ms: Option<u64>,
    provider_profile_id: Option<String>,
    app_id: Option<String>,
    access_token: Option<String>,
    name: Option<String>,
}
impl LocalRuntimeService {
    pub(crate) async fn audio_sessions_manage_v2(
        &self,
        broker: &TrustedSessionBroker,
        input: Value,
    ) -> Result<Value, String> {
        let request: Request =
            serde_json::from_value(input).map_err(|_| "audio_session_request_invalid")?;
        let (owner, epoch) = authority::resolve(&self.state, broker, &request).await?;
        let result = operate(&self.state, &owner, request.operation).await?;
        authority::current(broker, epoch)?;
        Ok(result)
    }
}
fn snapshot(state: &LocalRuntimeState, owner: &Owner) -> Result<Value, String> {
    Ok(
        json!({"scope":{"tenant_id":owner.tenant_id,"project_id":owner.project_id},
        "profiles":profiles::list(state,owner)?,"sessions":store::list(&*state.session_store.connection()?,owner)?.iter().map(Session::public).collect::<Vec<_>>()}),
    )
}
async fn operate(
    state: &Arc<LocalRuntimeState>,
    owner: &Owner,
    mut operation: Operation,
) -> Result<Value, String> {
    let _gate = state.audio_sessions.gate.lock().await;
    if !state.audio_sessions.initialized.load(Ordering::Acquire) {
        let db = state.session_store.connection()?;
        store::initialize(&db)?;
        profiles::initialize(&db)?;
        store::recover(&db)?;
        state
            .audio_sessions
            .initialized
            .store(true, Ordering::Release);
    }
    if operation.action == "configure_provider" {
        profiles::configure(state, owner, &mut operation)?;
        return snapshot(state, owner);
    }
    let client = state.computer_use.client()?;
    listen(state, &client);
    if operation.action == "list" {
        let sessions = store::list(&*state.session_store.connection()?, owner)?;
        for session in sessions
            .into_iter()
            .filter(|row| matches!(row.state.as_str(), "recording" | "paused" | "stopping"))
        {
            if let Ok(value) = client
                .audio_session_request("audio_session_status", native_input(&session))
                .await
            {
                ingest(state, &owner, &value)?;
            }
        }
        return snapshot(state, owner);
    }
    let mut session = if operation.action == "start" {
        if let Some(id) = operation.provider_profile_id.as_deref() {
            profiles::get(state, owner, id)?;
        }
        let source = operation.source.as_deref().unwrap_or("mixed");
        if !matches!(source, "microphone" | "system" | "mixed") {
            return Err("audio_session_source_invalid".into());
        }
        let duration = operation.max_duration_ms.unwrap_or(28_800_000);
        if !(100..=28_800_000).contains(&duration) {
            return Err("audio_session_duration_invalid".into());
        }
        let id = uuid::Uuid::new_v4().to_string();
        let root = private_root(state, &id)?;
        Session {
            owner: owner.clone(),
            audio_session_id: id,
            generation: 1,
            mode: "meeting".into(),
            source: source.into(),
            state: "starting".into(),
            started_at: chrono::Utc::now().to_rfc3339(),
            captured_ms: 0,
            max_duration_ms: duration,
            segments: vec![],
            transcript: vec![],
            summary: None,
            provider_profile_id: operation.provider_profile_id,
            sync_audio: false,
            private_root: Some(root),
            error_code: None,
        }
    } else {
        let session = store::get(
            &*state.session_store.connection()?,
            owner,
            operation
                .audio_session_id
                .as_deref()
                .ok_or("audio_session_required")?,
        )?;
        if operation.generation != Some(session.generation) {
            return Err("audio_session_generation_stale".into());
        }
        session
    };
    let method = match operation.action.as_str() {
        "start" => "audio_session_start",
        "pause" if session.state == "recording" => "audio_session_pause",
        "resume" if matches!(session.state.as_str(), "paused" | "interrupted") => {
            session.generation = session
                .generation
                .checked_add(1)
                .ok_or("audio_session_generation_exhausted")?;
            "audio_session_resume"
        }
        "stop" if !matches!(session.state.as_str(), "stopped" | "completed") => {
            "audio_session_stop"
        }
        "status" => "audio_session_status",
        "stop" => return snapshot(state, owner),
        _ => return Err("audio_session_transition_invalid".into()),
    };
    store::save(&*state.session_store.connection()?, &session)?;
    match client
        .audio_session_request(method, native_input(&session))
        .await
    {
        Ok(value) => ingest(state, owner, &value)?,
        Err(error) => {
            session.error_code = Some(error.to_string());
            if operation.action == "start" || operation.action == "resume" {
                session.state = "interrupted".into();
            }
            store::save(&*state.session_store.connection()?, &session)?;
            return Err("audio_session_native_failed".into());
        }
    }
    snapshot(state, owner)
}
fn native_input(session: &Session) -> Value {
    json!({"owner":session.owner,"audio_session_id":session.audio_session_id,"generation":session.generation,
        "mode":session.mode,"source":session.source,"max_duration_ms":session.max_duration_ms,"artifact_root":session.private_root})
}
fn private_root(state: &LocalRuntimeState, id: &str) -> Result<String, String> {
    let root = state
        .app_data_dir
        .as_ref()
        .ok_or("audio_session_storage_unavailable")?
        .join("audio-sessions")
        .join(id);
    std::fs::create_dir_all(&root).map_err(|_| "audio_session_storage_unavailable")?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .map_err(|_| "audio_session_storage_unavailable")?;
    }
    Ok(root
        .canonicalize()
        .map_err(|_| "audio_session_storage_unavailable")?
        .to_string_lossy()
        .into())
}
fn ingest(state: &LocalRuntimeState, owner: &Owner, value: &Value) -> Result<(), String> {
    let id = value["audio_session_id"]
        .as_str()
        .ok_or("audio_session_result_invalid")?;
    let mut session = store::get(&*state.session_store.connection()?, owner, id)?;
    if value["generation"].as_u64() != Some(session.generation) {
        return Ok(());
    }
    let phase = value["state"]
        .as_str()
        .filter(|phase| {
            matches!(
                *phase,
                "recording" | "paused" | "stopped" | "completed" | "interrupted" | "failed"
            )
        })
        .ok_or("audio_session_result_invalid")?;
    session.state = phase.into();
    session.captured_ms = value["captured_ms"].as_u64().unwrap_or(session.captured_ms);
    session.error_code = value["error_code"].as_str().map(str::to_owned);
    if let Some(segments) = value["segments"].as_array() {
        for segment in segments {
            let segment_id = segment["segment_id"]
                .as_str()
                .ok_or("audio_segment_invalid")?;
            if !session
                .segments
                .iter()
                .any(|prior| prior["segment_id"] == segment_id)
            {
                session.segments.push(segment.clone());
                store::enqueue(&*state.session_store.connection()?, &session, segment)?;
            }
        }
    }
    store::save(&*state.session_store.connection()?, &session)
}
fn listen(state: &Arc<LocalRuntimeState>, client: &Arc<agistack_adapters_cua::CuaClient>) {
    if state.audio_sessions.listening.swap(true, Ordering::AcqRel) {
        return;
    }
    let mut receiver = client.subscribe_audio_sessions();
    let state = Arc::downgrade(state);
    tokio::spawn(async move {
        loop {
            let value = match receiver.recv().await {
                Ok(value) => value,
                Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => continue,
                Err(_) => break,
            };
            let Some(state) = state.upgrade() else { break };
            let _gate = state.audio_sessions.gate.lock().await;
            let Ok(owner) = serde_json::from_value::<Owner>(value["owner"].clone()) else {
                continue;
            };
            if let Err(error) = ingest(&state, &owner, &value) {
                tracing::warn!(code=%error,"Audio session notification could not be persisted");
            }
        }
    });
}
