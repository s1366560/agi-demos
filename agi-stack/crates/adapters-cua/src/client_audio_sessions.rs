//! Independent user audio consumers share the supervised helper, not CUA runs.
use super::*;

pub(super) struct Binding {
    owner: Value,
    generation: u64,
    pub(super) active: bool,
    terminal: bool,
}

fn identity(params: &Value) -> Result<(&str, u64, &Value), CuaError> {
    let id = params["audio_session_id"]
        .as_str()
        .filter(|id| !id.is_empty() && id.len() <= 128);
    let generation = params["generation"]
        .as_u64()
        .filter(|generation| *generation > 0);
    let owner = &params["owner"];
    let valid_owner = owner.as_object().is_some_and(|owner| {
        owner.len() == 4
            && ["user_id", "tenant_id", "project_id", "device_id"]
                .iter()
                .all(|field| {
                    owner
                        .get(*field)
                        .and_then(Value::as_str)
                        .is_some_and(|value| !value.is_empty() && value.len() <= 1024)
                })
    });
    match (id, generation, valid_owner) {
        (Some(id), Some(generation), true) => Ok((id, generation, owner)),
        _ => Err(CuaError::Request {
            kind: "invalid_audio_context".into(),
            message: "owned audio session identity is required".into(),
        }),
    }
}

impl CuaClient {
    pub fn subscribe_audio_pcm(&self) -> broadcast::Receiver<Value> {
        self.audio_pcm.subscribe()
    }
    pub fn subscribe_audio_sessions(&self) -> broadcast::Receiver<Value> {
        self.audio_events.subscribe()
    }

    /// Only host-authenticated audio management calls may enter this API.
    /// Start/resume may launch a helper; status/stop never launch a replacement.
    pub async fn audio_session_request(
        &self,
        method: &str,
        params: Value,
    ) -> Result<Value, CuaError> {
        if !matches!(
            method,
            "audio_session_start"
                | "audio_session_resume"
                | "audio_session_pause"
                | "audio_session_stop"
                | "audio_session_status"
        ) {
            return Err(CuaError::Request {
                kind: "invalid_audio_method".into(),
                message: "unsupported audio session operation".into(),
            });
        }
        let (id, generation, owner) = identity(&params)?;
        let _gate = self.audio_gate.lock().await;
        let starts = matches!(method, "audio_session_start" | "audio_session_resume");
        let connection = if starts {
            self.connection().await?
        } else {
            self.state
                .lock()
                .await
                .as_ref()
                .filter(|connection| connection.alive.load(Ordering::Acquire))
                .cloned()
                .ok_or_else(|| CuaError::Unreachable("audio helper is not running".into()))?
        };
        {
            let mut sessions = connection
                .audio_sessions
                .lock()
                .map_err(|_| CuaError::Unreachable("audio session lock failed".into()))?;
            if let Some(previous) = sessions.get(id) {
                if previous.owner != *owner
                    || generation < previous.generation
                    || (!starts && generation != previous.generation)
                {
                    return Err(CuaError::Request {
                        kind: "audio_session_owner_mismatch".into(),
                        message: "audio session identity changed".into(),
                    });
                }
            } else if !starts {
                return Err(CuaError::Request {
                    kind: "audio_session_not_found".into(),
                    message: "audio session is not active on this connection".into(),
                });
            }
            if starts {
                sessions.insert(
                    id.to_owned(),
                    Binding {
                        owner: owner.clone(),
                        generation,
                        active: true,
                        terminal: false,
                    },
                );
            }
        }
        let value = self.exchange(connection.clone(), method, params).await?;
        if !connection.audio_session_update(&value) {
            connection.abort("invalid audio session response");
            return Err(CuaError::InvalidResponse(
                "invalid audio session response".into(),
            ));
        }
        Ok(value)
    }

    /// CUA idle cleanup must not terminate an independently owned meeting.
    pub async fn shutdown_if_audio_idle(&self) {
        let _gate = self.audio_gate.lock().await;
        let has_audio = self.state.lock().await.as_ref().is_some_and(|connection| {
            connection.alive.load(Ordering::Acquire)
                && connection
                    .audio_sessions
                    .lock()
                    .map_or(true, |sessions| sessions.values().any(|value| value.active))
        });
        if !has_audio {
            self.shutdown().await;
        }
    }
}

impl Connection {
    pub(super) fn audio_pcm_update(&self, value: &Value) -> bool {
        let Ok((id, generation, owner)) = identity(value) else {
            return false;
        };
        if value["sample_rate"] != 16000
            || value["channels"] != 1
            || value["encoding"] != "pcm_s16le"
            || !matches!(value["source"].as_str(), Some("microphone" | "system"))
            || value["sequence"].as_u64().is_none()
            || value["start_ms"].as_u64().is_none()
            || value["data"].as_str().is_none_or(|data| data.len() > 4400)
        {
            return false;
        }
        let Ok(sessions) = self.audio_sessions.lock() else {
            return false;
        };
        let Some(binding) = sessions.get(id) else {
            return false;
        };
        if binding.owner != *owner || generation != binding.generation {
            return false;
        }
        if binding.active && !binding.terminal {
            let _ = self.audio_pcm.send(value.clone());
        }
        true
    }
    pub(super) fn audio_session_update(&self, value: &Value) -> bool {
        let Ok((id, generation, owner)) = identity(value) else {
            return false;
        };
        let Some(state) = value["state"]
            .as_str()
            .filter(|state| matches!(*state, "recording" | "paused" | "interrupted" | "stopped"))
        else {
            return false;
        };
        let Ok(mut sessions) = self.audio_sessions.lock() else {
            return false;
        };
        let Some(binding) = sessions.get_mut(id) else {
            return false;
        };
        if binding.owner != *owner || generation != binding.generation {
            return false;
        }
        if binding.terminal && matches!(state, "recording" | "paused") {
            return true;
        }
        binding.active = matches!(state, "recording" | "paused");
        binding.terminal = !binding.active;
        let _ = self.audio_events.send(value.clone());
        true
    }
}
