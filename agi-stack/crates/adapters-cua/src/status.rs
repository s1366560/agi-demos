//! Authenticated native UI state. Targets are identity metadata, never image bytes.
use crate::CuaCallContext;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CuaNativeTarget {
    pub app_id: String,
    pub display_name: String,
    pub process_id: i64,
    pub identity_digest: String,
    pub window_id: Option<String>,
    pub window_title: Option<String>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CuaNativeStatus {
    pub context: CuaCallContext,
    pub phase: String,
    pub updated_at: f64,
    pub target: Option<CuaNativeTarget>,
    pub error_code: Option<String>,
    #[serde(default)]
    pub user_initiated: bool,
    pub user_action: Option<String>,
    pub can_resume: Option<bool>,
    pub resume_blocked_reason: Option<String>,
    #[serde(default)]
    pub recordings: Vec<Value>,
}
impl CuaNativeStatus {
    pub(crate) fn valid(&self) -> bool {
        matches!(
            self.phase.as_str(),
            "idle"
                | "observing"
                | "acting"
                | "awaiting_permission"
                | "paused"
                | "stopped"
                | "focus_required"
                | "error"
        ) && self.updated_at.is_finite()
            && self.user_action.as_ref().is_none_or(|action| {
                matches!(action.as_str(), "pause" | "resume" | "stop" | "audio_stop")
            })
            && self.recordings.len() <= 128
            && self.recordings.iter().all(|recording| {
                recording["recording_id"]
                    .as_str()
                    .is_some_and(|id| !id.is_empty() && id.len() <= 256)
                    && matches!(
                        recording["source"].as_str(),
                        Some("microphone" | "system" | "mixed")
                    )
                    && matches!(
                        recording["status"].as_str(),
                        Some("recording" | "stopping" | "pending_export" | "saved" | "failed")
                    )
                    && recording["started_at"]
                        .as_str()
                        .is_some_and(|date| date.len() <= 64)
                    && recording["artifacts"]
                        .as_array()
                        .is_some_and(|artifacts| artifacts.len() <= 2)
            })
            && self
                .error_code
                .as_ref()
                .is_none_or(|code| code.len() <= 256)
            && self.target.as_ref().is_none_or(|target| {
                !target.app_id.is_empty()
                    && target.app_id.len() <= 1024
                    && !target.identity_digest.is_empty()
                    && target.identity_digest.len() <= 256
                    && target.display_name.len() <= 1024
                    && target.process_id >= 0
                    && target.window_id.as_ref().is_none_or(|id| id.len() <= 256)
                    && target
                        .window_title
                        .as_ref()
                        .is_none_or(|title| title.len() <= 4096)
            })
    }
    pub fn presentation(&self) -> Value {
        json!({"phase":self.phase,"updated_at":self.updated_at,"target":self.target,
            "error_code":self.error_code,"can_resume":self.can_resume.unwrap_or(false),
            "resume_blocked_reason":self.resume_blocked_reason,"recordings":self.recordings})
    }
}
