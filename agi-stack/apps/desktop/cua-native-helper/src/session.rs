use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::sync::Mutex;

use crate::backend::{check_cancel, required, App, Backend, NativeError, Observation, Result};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Context {
    pub device_id: String,
    pub user_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub conversation_id: String,
    pub run_id: String,
    pub session_id: String,
    pub input_mode: InputMode,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum InputMode {
    Background,
    Foreground,
}

#[path = "session_lifecycle.rs"]
pub(crate) mod lifecycle;
#[cfg(test)]
#[path = "session_tests.rs"]
mod tests;

struct Snapshot {
    id: String,
    epoch: u64,
    app: App,
    observation: Observation,
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum Phase {
    Active,
    Pausing,
    Paused,
    Stopped,
}

struct Session {
    context: Context,
    input_generation: String,
    root: PathBuf,
    root_identity: (u64, u64),
    phase: Phase,
    cancel: Arc<AtomicBool>,
    snapshot: Option<Snapshot>,
}
#[derive(Default)]
struct Lease {
    owner: Option<String>,
    epoch: u64,
}

pub struct Sessions {
    backend: Arc<dyn Backend>,
    sessions: Mutex<BTreeMap<String, Arc<Mutex<Session>>>>,
    closed: Mutex<BTreeMap<String, Arc<Mutex<Session>>>>,
    audio: Arc<crate::audio_recordings::Recordings>,
    lease: Mutex<Lease>,
    operation: Mutex<()>,
}

impl Sessions {
    fn end_reason<'a>(params: &'a Value, default: &'a str) -> Result<&'a str> {
        let reason = params["end_reason"].as_str().unwrap_or(default);
        if !matches!(
            reason,
            "user_stopped"
                | "user_paused"
                | "model_stopped"
                | "session_ended"
                | "session_reset"
                | "revoked"
                | "disabled"
                | "lease_expired"
                | "cancelled"
        ) {
            return Err(NativeError::new(
                "invalid_params",
                "invalid recording end_reason",
            ));
        }
        Ok(reason)
    }
    pub fn new(backend: Arc<dyn Backend>) -> Self {
        Self {
            audio: Arc::new(crate::audio_recordings::Recordings::new(backend.clone())),
            backend,
            sessions: Mutex::new(BTreeMap::new()),
            closed: Mutex::new(BTreeMap::new()),
            lease: Mutex::new(Lease::default()),
            operation: Mutex::new(()),
        }
    }
    async fn session(&self, id: &str) -> Result<Arc<Mutex<Session>>> {
        self.sessions
            .lock()
            .await
            .get(id)
            .cloned()
            .ok_or_else(|| NativeError::new("session_not_found", "begin_session is required"))
    }
    async fn begin(&self, params: &Value) -> Result<Value> {
        let context: Context = serde_json::from_value(params.clone()).map_err(|_| {
            NativeError::new(
                "invalid_params",
                "complete host session context is required",
            )
        })?;
        for value in [
            &context.device_id,
            &context.user_id,
            &context.tenant_id,
            &context.project_id,
            &context.conversation_id,
            &context.run_id,
            &context.session_id,
        ] {
            if value.is_empty() || value.len() > 256 {
                return Err(NativeError::new(
                    "invalid_params",
                    "invalid host context identity",
                ));
            }
        }
        let mut sessions = self.sessions.lock().await;
        if let Some(closed) = self.closed.lock().await.get(&context.session_id).cloned() {
            if closed.lock().await.context != context {
                return Err(NativeError::new(
                    "session_owner_mismatch",
                    "closed session owner changed",
                ));
            }
        }
        if let Some(session) = sessions.get(&context.session_id) {
            let session = session.lock().await;
            if session.context != context {
                return Err(NativeError::new(
                    "session_owner_mismatch",
                    "session identity belongs to a different host context",
                ));
            }
            return Ok(
                json!({"session_id":context.session_id,"artifact_root":session.root,"ok":true,"input_mode":context.input_mode,"input_generation":session.input_generation}),
            );
        }
        if sessions.len() >= 64 {
            return Err(NativeError::new("session_limit", "too many live sessions"));
        }
        let root = self.backend.artifact_root().await?;
        let root_identity = lifecycle::root_identity(&root)?;
        let input_generation = uuid::Uuid::new_v4().to_string();
        let result = json!({"session_id":context.session_id,"artifact_root":root,"ok":true,"input_mode":context.input_mode,"input_generation":input_generation});
        sessions.insert(
            context.session_id.clone(),
            Arc::new(Mutex::new(Session {
                context,
                input_generation,
                root,
                root_identity,
                phase: Phase::Active,
                cancel: Arc::new(AtomicBool::new(false)),
                snapshot: None,
            })),
        );
        Ok(result)
    }
    pub async fn cancel(&self, id: &str) {
        if let Ok(session) = self.session(id).await {
            let mut session = session.lock().await;
            session.cancel.store(true, Ordering::Release);
            session.snapshot = None;
        }
        let released = {
            let mut lease = self.lease.lock().await;
            if lease.owner.as_deref() == Some(id) {
                lease.owner = None;
                lease.epoch = lease.epoch.wrapping_add(1);
                true
            } else {
                false
            }
        };
        if released {
            self.backend.release().await;
        }
    }
    pub async fn cancel_request(&self, params: &Value) -> Result<()> {
        let id = required(params, "session_id")?;
        let session = self.session(id).await?;
        let context = session.lock().await.context.clone();
        Self::validate_input_binding(&session, params).await?;
        for (field, expected) in [
            ("device_id", &context.device_id),
            ("user_id", &context.user_id),
            ("tenant_id", &context.tenant_id),
            ("project_id", &context.project_id),
            ("conversation_id", &context.conversation_id),
            ("run_id", &context.run_id),
        ] {
            if params[field].as_str() != Some(expected.as_str()) {
                return Err(NativeError::new(
                    "session_owner_mismatch",
                    "bound native host context is required",
                ));
            }
        }
        self.audio
            .request_end(&context, Self::end_reason(params, "cancelled")?)
            .await;
        self.cancel(id).await;
        Ok(())
    }
    pub async fn stop_all(&self) {
        let ids = self
            .sessions
            .lock()
            .await
            .keys()
            .cloned()
            .collect::<Vec<_>>();
        for id in ids {
            if let Ok(session) = self.session(&id).await {
                self.audio
                    .request_end(&session.lock().await.context, "session_ended")
                    .await;
            }
            self.cancel(&id).await;
            if let Ok(session) = self.session(&id).await {
                let owner = session.lock().await.context.clone();
                let _ = self.audio.stop(&owner, None, "session_ended").await;
            }
            self.backend.release_session(&id).await;
        }
    }
    pub async fn audio_notifications(&self) -> Vec<Value> {
        let mut sessions = self.closed.lock().await.clone();
        sessions.extend(self.sessions.lock().await.clone());
        let mut values = Vec::new();
        for session in sessions.into_values() {
            let (owner, phase) = {
                let state = session.lock().await;
                (state.context.clone(), state.phase)
            };
            let Ok(audio) = self.audio.status(&owner, None).await else {
                continue;
            };
            if audio["recordings"].as_array().is_none_or(Vec::is_empty) {
                continue;
            }
            values.push(json!({"context":owner,"phase":match phase { Phase::Paused | Phase::Pausing => "paused", Phase::Stopped => "stopped", Phase::Active => "idle" },
                "updated_at":chrono::Utc::now().timestamp_millis() as f64 / 1000.0,"recordings":audio["recordings"]}));
        }
        values
    }
    async fn acquire(&self, id: &str) -> Result<u64> {
        let mut lease = self.lease.lock().await;
        if lease.owner.as_ref().is_some_and(|owner| owner != id) {
            return Err(NativeError::new(
                "desktop_busy",
                "another computer-use session owns input control",
            ));
        }
        if lease.owner.is_none() {
            self.backend.acquire().await?;
            lease.epoch = lease.epoch.wrapping_add(1);
            lease.owner = Some(id.into());
        }
        Ok(lease.epoch)
    }
    async fn resolve(&self, identifier: &str, params: &Value) -> Result<App> {
        let mut candidates = self.backend.resolve(identifier).await?;
        if candidates.len() > 1 {
            if let Some(window_id) = params.get("window_id").and_then(Value::as_str) {
                let mut exact = Vec::new();
                for app in candidates {
                    if self
                        .backend
                        .windows(&app)
                        .await?
                        .iter()
                        .any(|window| window.window_id == window_id)
                    {
                        exact.push(app);
                    }
                }
                candidates = exact;
            }
        }
        if candidates.len() != 1 {
            return Err(NativeError::new(
                "app_not_found",
                "use an exact app and window id from list_apps/list_windows",
            ));
        }
        let app = candidates.remove(0);
        let executable = app
            .app_path
            .as_deref()
            .and_then(|path| std::path::Path::new(path).file_name())
            .and_then(|name| name.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        if [
            "credentialuibroker.exe",
            "systemsettings.exe",
            "seahorse",
            "gnome-keyring",
            "gnome-control-center",
        ]
        .contains(&executable.as_str())
        {
            return Err(NativeError::new(
                "cua_target_forbidden",
                "this native security application cannot be controlled",
            ));
        }
        if let Some(expected) = params
            .get("expected_identity_digest")
            .and_then(Value::as_str)
        {
            if expected.is_empty() || app.identity_digest != expected {
                return Err(NativeError::new(
                    "application_identity_changed",
                    "approved native executable identity changed",
                ));
            }
        } else if params.get("action").is_some() {
            return Err(NativeError::new(
                "application_identity_required",
                "host-approved application identity is required before input",
            ));
        }
        Ok(app)
    }
    async fn validate_input_binding(session: &Arc<Mutex<Session>>, params: &Value) -> Result<()> {
        let state = session.lock().await;
        if params["input_mode"] != json!(state.context.input_mode)
            || params["input_generation"].as_str() != Some(state.input_generation.as_str())
        {
            return Err(NativeError::new(
                "input_generation_mismatch",
                "the complete current input binding is required",
            ));
        }
        Ok(())
    }
    pub async fn dispatch(&self, method: &str, params: &Value) -> Result<Value> {
        if method == "capabilities" {
            let mut value = self.backend.capabilities().await;
            let foreground = matches!(
                value["capabilities"]["input"]["state"].as_str(),
                Some("available" | "permission_required")
            );
            value["input_support"] = json!({"background":{"supported":false,"reason":"background_input_unsupported"},"foreground":{"supported":foreground,"reason":if foreground {Value::Null} else {json!("foreground_input_unavailable")}}});
            return Ok(value);
        }
        if method == "permissions_status" {
            return Ok(self.backend.permissions().await);
        }
        if method == "begin_session" {
            return self.begin(params).await;
        }
        let id = required(params, "session_id")?;
        let session = if matches!(method, "audio_status" | "audio_stop" | "audio_ack") {
            match self.session(id).await {
                Ok(session) => session,
                Err(_) => self.closed.lock().await.get(id).cloned().ok_or_else(|| {
                    NativeError::new("session_not_found", "owned audio session is required")
                })?,
            }
        } else {
            self.session(id).await?
        };
        let owner = session.lock().await.context.clone();
        Self::validate_input_binding(&session, params).await?;
        for (field, expected) in [
            ("device_id", &owner.device_id),
            ("user_id", &owner.user_id),
            ("tenant_id", &owner.tenant_id),
            ("project_id", &owner.project_id),
            ("conversation_id", &owner.conversation_id),
            ("run_id", &owner.run_id),
        ] {
            if params[field].as_str() != Some(expected.as_str()) {
                return Err(NativeError::new(
                    "session_owner_mismatch",
                    "all native calls must retain the complete bound host context",
                ));
            }
        }
        if matches!(
            method,
            "cancel" | "stop_session" | "end_session" | "pause_session"
        ) {
            let reason = Self::end_reason(
                params,
                match method {
                    "pause_session" => "user_paused",
                    "cancel" => "cancelled",
                    _ => "session_ended",
                },
            )?;
            return self.suspend(method, id, &session, reason).await;
        }
        // Audio controls use their own gate; a long native input must not delay stopping a microphone.
        if method == "audio_stop" {
            return self
                .audio
                .stop(
                    &owner,
                    params["recording_id"].as_str(),
                    Self::end_reason(params, "model_stopped")?,
                )
                .await;
        }
        if method == "audio_status" {
            return self
                .audio
                .status(&owner, params["recording_id"].as_str())
                .await;
        }
        if method == "audio_ack" {
            return self
                .audio
                .acknowledge(&owner, required(params, "recording_id")?)
                .await;
        }
        if owner.input_mode == InputMode::Background
            && matches!(method, "perform_action" | "activate_app" | "launch_app")
        {
            return Err(NativeError::new(
                "background_input_unsupported",
                "this platform requires explicit foreground input mode",
            ));
        }
        let _operation = self.operation.lock().await;
        if method == "resume_session" {
            return self.resume(&session).await;
        }
        let (cancel, root, phase) = {
            let session = session.lock().await;
            (session.cancel.clone(), session.root.clone(), session.phase)
        };
        if matches!(method, "reset" | "reset_session") {
            match phase {
                Phase::Stopped => {
                    return Err(NativeError::new(
                        "user_stopped_session",
                        "stopped native sessions require a new session",
                    ));
                }
                Phase::Paused | Phase::Pausing => {
                    return Err(NativeError::new(
                        "session_paused",
                        "resume the paused session; reset cannot bypass pause",
                    ));
                }
                Phase::Active => {}
            }
            self.audio.request_end(&owner, "session_reset").await;
            self.cancel(id).await;
            let _ = self.audio.stop(&owner, None, "session_reset").await;
            self.backend.release_session(id).await;
            let mut session = session.lock().await;
            match session.phase {
                Phase::Stopped => {
                    return Err(NativeError::new(
                        "user_stopped_session",
                        "terminal stop superseded reset",
                    ));
                }
                Phase::Paused | Phase::Pausing => {
                    return Err(NativeError::new("session_paused", "pause superseded reset"));
                }
                Phase::Active => {}
            }
            session.snapshot = None;
            session.cancel = Arc::new(AtomicBool::new(false));
            session.phase = Phase::Active;
            session.input_generation = uuid::Uuid::new_v4().to_string();
            return Ok(
                json!({"ok":true,"input_mode":session.context.input_mode,"input_generation":session.input_generation}),
            );
        }
        if matches!(phase, Phase::Paused | Phase::Pausing) {
            return Err(NativeError::new(
                "session_paused",
                "computer use is paused; resume and obtain a fresh observation",
            ));
        }
        check_cancel(&cancel)?;
        if method == "audio_start" {
            return self
                .audio
                .start(owner, required(params, "source")?, &root, cancel)
                .await;
        }
        if matches!(
            method,
            "clipboard_read" | "clipboard_write" | "clipboard_release"
        ) {
            return self.backend.clipboard(id, method, params).await;
        }
        if method == "list_apps" {
            return Ok(json!({"apps":self.backend.apps().await?}));
        }
        if method == "accessibility_status" {
            return Ok(self.backend.capabilities().await);
        }
        if method == "permission_request" {
            return self
                .backend
                .request_permission(required(params, "capability")?)
                .await;
        }
        if matches!(
            method,
            "enable_locked_use" | "locked_use_status" | "connector_accounts" | "connector_call"
        ) {
            return Err(NativeError::unsupported(method));
        }
        if method.starts_with("calendar_")
            || method.starts_with("contacts_")
            || method.starts_with("messages_")
        {
            return Err(NativeError::unsupported("native personal-data connectors"));
        }
        let app = self.resolve(required(params, "app")?, params).await?;
        if method == "resolve_app" {
            let mut result = serde_json::to_value(&app)
                .map_err(|_| NativeError::new("internal_error", "app identity encoding failed"))?;
            match self.backend.app_icon(&app, None, &root).await {
                Ok(icon) => {
                    result["app_icon"] = icon;
                    result["app_icon_status"] = json!({"state":"available"});
                }
                Err(error) => {
                    result["app_icon_unavailable_reason"] = json!(error.kind);
                    result["app_icon_status"] =
                        json!({"state":"unavailable","reason":error.message});
                }
            }
            return Ok(result);
        }
        if method == "launch_app" {
            required(params, "expected_identity_digest")?;
            if self.backend.locked().await? {
                return Err(NativeError::new(
                    "desktop_locked",
                    "unlock the native session before launching an application",
                ));
            }
            self.acquire(id).await?;
            session.lock().await.snapshot = None;
            return self.backend.launch(&app).await;
        }
        let windows = self.backend.windows(&app).await?;
        if method == "list_windows" {
            return Ok(json!({"app":app.id,"windows":windows}));
        }
        let window = if let Some(window_id) = params.get("window_id").and_then(Value::as_str) {
            windows
                .into_iter()
                .find(|window| window.window_id == window_id)
        } else if windows.len() == 1 {
            windows.into_iter().next()
        } else {
            None
        }
        .ok_or_else(|| {
            NativeError::new(
                "window_required",
                "select an exact window_id from list_windows",
            )
        })?;
        if self.backend.locked().await? {
            self.cancel(id).await;
            return Err(NativeError::new(
                "desktop_locked",
                "desktop input is suspended until the user unlocks the session",
            ));
        }
        let epoch = self.acquire(id).await?;
        if method == "activate_app" {
            self.backend.activate(&window).await?;
            return Ok(json!({"ok":true,"app":app.id,"window_id":window.window_id}));
        }
        if method == "get_app_state" {
            let observation = self.backend.observe(&app, &window, &root).await?;
            check_cancel(&cancel)?;
            let snapshot_id = uuid::Uuid::new_v4().to_string();
            let mut result = json!({"input_mode":owner.input_mode,"input_generation":session.lock().await.input_generation,"app":app.id,"window_id":window.window_id,"snapshot_id":snapshot_id,"lease_epoch":epoch,"text":observation.text,"window_bounds":window.bounds,"screenshot":observation.screenshot});
            if let Some(tree) = observation.native.get("ax_tree") {
                result["ax_tree"] = json!({"version":1,"source":"at_spi","snapshot_id":snapshot_id,"window_id":window.window_id,"nodes":tree["nodes"],"truncated":tree["truncated"]});
            }
            match self.backend.app_icon(&app, Some(&window), &root).await {
                Ok(icon) => {
                    result["app_icon"] = icon;
                    result["app_icon_status"] = json!({"state":"available"});
                }
                Err(error) => {
                    result["app_icon_unavailable_reason"] = json!(error.kind);
                    result["app_icon_status"] =
                        json!({"state":"unavailable","reason":error.message});
                }
            }
            check_cancel(&cancel)?;
            session.lock().await.snapshot = Some(Snapshot {
                id: snapshot_id,
                epoch,
                app,
                observation,
            });
            return Ok(result);
        }
        if method == "perform_action" {
            let snapshot = session.lock().await.snapshot.take().ok_or_else(|| {
                NativeError::new("stale_element", "refresh get_app_state before acting")
            })?;
            if snapshot.id != required(params, "snapshot_id")?
                || snapshot.epoch != epoch
                || snapshot.app.id != app.id
                || snapshot.app.process_id != app.process_id
                || snapshot.observation.window != window
            {
                return Err(NativeError::new(
                    "stale_element",
                    "window or snapshot changed; refresh get_app_state",
                ));
            }
            if !window.focused {
                return Err(NativeError::new(
                    "target_not_focused",
                    "activate the observed window before acting",
                ));
            }
            let action = params
                .get("action")
                .filter(|value| value.is_object())
                .ok_or_else(|| NativeError::new("invalid_params", "action object is required"))?;
            let mut action = action.clone();
            action["_session_id"] = json!(id);
            self.backend
                .action(&snapshot.observation, &action, cancel)
                .await?;
            return Ok(json!({"ok":true}));
        }
        Err(NativeError::unsupported(method))
    }
}
