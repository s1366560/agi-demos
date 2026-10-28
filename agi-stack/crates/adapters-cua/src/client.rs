//! Supervised, authenticated, multiplexed private-pipe computer-use client.

use crate::{error::CuaError, framing, IPC_PROTOCOL_VERSION};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    path::PathBuf,
    process::Stdio,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex as SyncMutex,
    },
};
use tokio::{
    process::{Child, ChildStdin, Command},
    sync::{broadcast, oneshot, watch, Mutex},
    time::{timeout, Duration},
};

#[path = "client_bindings.rs"]
mod bindings;
#[path = "client_lifecycle.rs"]
mod lifecycle;
#[path = "client_notifications.rs"]
mod notifications;
#[path = "client_protocol.rs"]
mod protocol;
use protocol::{decode_response, input_generation, mutates, random_hex, valid_proof};

const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(5);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(120);
type Pending = BTreeMap<u64, oneshot::Sender<Result<Value, CuaError>>>;

/// Authority context supplied by the host, never by model arguments.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CuaCallContext {
    pub user_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub device_id: String,
    pub conversation_id: String,
    pub run_id: String,
    pub session_id: String,
    pub input_mode: crate::CuaInputMode,
}

#[derive(Default)]
pub struct CuaClientBuilder {
    helper_path: Option<PathBuf>,
    helper_args: Vec<std::ffi::OsString>,
    request_timeout: Option<Duration>,
}
impl CuaClientBuilder {
    #[must_use]
    pub fn helper_path(mut self, path: impl Into<PathBuf>) -> Self {
        self.helper_path = Some(path.into());
        self
    }
    #[must_use]
    pub fn helper_args(
        mut self,
        args: impl IntoIterator<Item = impl Into<std::ffi::OsString>>,
    ) -> Self {
        self.helper_args = args.into_iter().map(Into::into).collect();
        self
    }
    #[must_use]
    pub fn request_timeout(mut self, duration: Duration) -> Self {
        self.request_timeout = Some(duration);
        self
    }
    pub fn build(self) -> CuaClient {
        CuaClient {
            helper_path: self.helper_path,
            helper_args: self.helper_args,
            state: Mutex::new(None),
            next_id: AtomicU64::new(1),
            request_timeout: self.request_timeout.unwrap_or(REQUEST_TIMEOUT),
            native_status: broadcast::channel(256).0,
            input_telemetry: watch::channel(BTreeMap::new()).0,
            input_bindings: Arc::new(bindings::Bindings::default()),
            shutting_down: AtomicBool::new(false),
        }
    }
}

struct Connection {
    input_binding_id: String,
    input_bindings: Arc<bindings::Bindings>,
    writer: Arc<Mutex<Option<ChildStdin>>>,
    child: SyncMutex<Option<Child>>,
    reaper: SyncMutex<Option<tokio::task::JoinHandle<()>>>,
    pending: SyncMutex<Pending>,
    sessions: Mutex<BTreeMap<String, (CuaCallContext, Option<PathBuf>)>>,
    closed_sessions: Mutex<BTreeMap<String, (CuaCallContext, Option<PathBuf>)>>,
    session_admission: Mutex<()>,
    generations: Mutex<BTreeMap<String, String>>,
    input_sequences: Mutex<BTreeMap<String, (String, u64)>>,
    observations: Mutex<BTreeMap<String, crate::coordinates::ObservationCoordinates>>,
    alive: AtomicBool,
    input_telemetry: watch::Sender<BTreeMap<String, crate::CuaInputTelemetry>>,
}
/// Dropping a partially dispatched future must not leave a usable poisoned pipe.
struct ExchangeGuard {
    connection: Arc<Connection>,
    id: u64,
    completed: bool,
}
impl Drop for ExchangeGuard {
    fn drop(&mut self) {
        if !self.completed {
            if let Ok(mut pending) = self.connection.pending.lock() {
                pending.remove(&self.id);
            }
            self.connection.abort("request cancelled or timed out");
        }
    }
}

pub struct CuaClient {
    shutting_down: AtomicBool,
    input_bindings: Arc<bindings::Bindings>,
    native_status: broadcast::Sender<crate::CuaNativeStatus>,
    input_telemetry: watch::Sender<BTreeMap<String, crate::CuaInputTelemetry>>,
    helper_path: Option<PathBuf>,
    helper_args: Vec<std::ffi::OsString>,
    state: Mutex<Option<Arc<Connection>>>,
    next_id: AtomicU64,
    request_timeout: Duration,
}
impl CuaClient {
    pub fn subscribe_native_status(&self) -> broadcast::Receiver<crate::CuaNativeStatus> {
        self.native_status.subscribe()
    }
    pub fn subscribe_input_telemetry(
        &self,
    ) -> watch::Receiver<BTreeMap<String, crate::CuaInputTelemetry>> {
        self.input_telemetry.subscribe()
    }
    pub fn current_input_generation(&self, session_id: &str) -> Option<String> {
        self.input_bindings.current(session_id)
    }
    pub fn builder() -> CuaClientBuilder {
        CuaClientBuilder::default()
    }

    async fn connection(&self) -> Result<Arc<Connection>, CuaError> {
        let mut state = self.state.lock().await;
        if self.shutting_down.load(Ordering::Acquire) {
            return Err(CuaError::Unreachable("helper is shutting down".into()));
        }
        if let Some(connection) = state.as_ref().filter(|c| c.alive.load(Ordering::Acquire)) {
            return Ok(connection.clone());
        }
        // Wait for the old helper to release input before spawning a replacement.
        if let Some(previous) = state.take() {
            previous.abort("retiring disconnected helper");
            let reaper = previous
                .reaper
                .lock()
                .ok()
                .and_then(|mut reaper| reaper.take());
            if let Some(reaper) = reaper {
                let _ = reaper.await;
            }
        }
        let helper = self
            .helper_path
            .as_ref()
            .ok_or_else(|| CuaError::HelperSpawnFailed("no helper path configured".into()))?;
        let mut child = Command::new(helper)
            .args(&self.helper_args)
            .arg("--stdio")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| CuaError::HelperSpawnFailed(e.to_string()))?;
        let mut writer = child
            .stdin
            .take()
            .ok_or_else(|| CuaError::Unreachable("missing stdin".into()))?;
        let mut reader = child
            .stdout
            .take()
            .ok_or_else(|| CuaError::Unreachable("missing stdout".into()))?;
        let secret = random_hex()?;
        let nonce = random_hex()?;
        let initialize = json!({"jsonrpc":"2.0","id":0,"method":"initialize","params":{
            "native_status_notifications":true,"input_telemetry_notifications":true,
            "client_api_version":IPC_PROTOCOL_VERSION,"nonce":nonce,"secret":secret}});
        let response = timeout(HANDSHAKE_TIMEOUT, async {
            framing::write_frame(&mut writer, initialize.to_string().as_bytes()).await?;
            framing::read_frame(&mut reader).await
        })
        .await
        .map_err(|_| CuaError::Unreachable("handshake timed out".into()))??;
        let result = decode_response(&response, 0)?;
        let version = result
            .get("server_api_version")
            .and_then(Value::as_str)
            .unwrap_or("");
        if version != IPC_PROTOCOL_VERSION {
            return Err(CuaError::IncompatibleClientVersion {
                client: IPC_PROTOCOL_VERSION.into(),
                server: version.into(),
            });
        }
        let proof = result.get("proof").and_then(Value::as_str).unwrap_or("");
        if result.get("nonce") != Some(&json!(nonce)) || !valid_proof(&secret, &nonce, proof) {
            return Err(CuaError::InvalidResponse(
                "helper authentication failed".into(),
            ));
        }
        let connection = Arc::new(Connection {
            input_binding_id: nonce,
            input_bindings: self.input_bindings.clone(),
            writer: Arc::new(Mutex::new(Some(writer))),
            child: SyncMutex::new(Some(child)),
            reaper: SyncMutex::new(None),
            pending: SyncMutex::new(BTreeMap::new()),
            sessions: Mutex::new(BTreeMap::new()),
            closed_sessions: Mutex::new(BTreeMap::new()),
            session_admission: Mutex::new(()),
            generations: Mutex::new(BTreeMap::new()),
            input_sequences: Mutex::new(BTreeMap::new()),
            observations: Mutex::new(BTreeMap::new()),
            alive: AtomicBool::new(true),
            input_telemetry: self.input_telemetry.clone(),
        });
        let weak = Arc::downgrade(&connection);
        let native_status = self.native_status.clone();
        self.input_telemetry.send_replace(BTreeMap::new());
        tokio::spawn(async move {
            loop {
                let raw = framing::read_frame(&mut reader).await;
                let Some(connection) = weak.upgrade() else {
                    return;
                };
                let raw = match raw {
                    Ok(raw) => raw,
                    Err(_) => {
                        connection.abort("helper output closed");
                        return;
                    }
                };
                let value = serde_json::from_slice::<Value>(&raw).ok();
                if let Some(value) = value.as_ref().filter(|v| v.get("id").is_none()) {
                    if !connection.notification(value, &native_status).await {
                        connection.abort("invalid native status notification");
                        return;
                    }
                    continue;
                }
                let id = value.and_then(|value| value.get("id").and_then(Value::as_u64));
                let Some(id) = id else {
                    connection.abort("invalid response id");
                    return;
                };
                let tx = connection
                    .pending
                    .lock()
                    .ok()
                    .and_then(|mut pending| pending.remove(&id));
                let Some(tx) = tx else {
                    connection.abort("unexpected response id");
                    return;
                };
                let _ = tx.send(decode_response(&raw, id));
            }
        });
        *state = Some(connection.clone());
        Ok(connection)
    }

    async fn exchange(
        &self,
        connection: Arc<Connection>,
        method: &str,
        params: Value,
    ) -> Result<Value, CuaError> {
        self.allow_during_shutdown(method)?;
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let payload = json!({"jsonrpc":"2.0","id":id,"method":method,"params":params}).to_string();
        // Validate the entire frame before reserving or dispatching anything.
        framing::encode_frame(payload.as_bytes())?;
        let (tx, rx) = oneshot::channel();
        connection
            .pending
            .lock()
            .map_err(|_| CuaError::Unreachable("pending lock poisoned".into()))?
            .insert(id, tx);
        let mut guard = ExchangeGuard {
            connection: connection.clone(),
            id,
            completed: false,
        };
        let request_timeout = if matches!(method,"locked_use_install" | "locked_use_uninstall") {
            self.request_timeout.max(Duration::from_secs(300))
        } else { self.request_timeout };
        let exchange = timeout(request_timeout, async {
            let mut writer = connection.writer.lock().await;
            self.allow_during_shutdown(method)?;
            if !connection.alive.load(Ordering::Acquire) {
                return Err(CuaError::Unreachable("helper disconnected".into()));
            }
            let pipe = writer
                .as_mut()
                .ok_or_else(|| CuaError::Unreachable("helper input closed".into()))?;
            // A partial frame write can still reach native code; mark before its first byte.
            crate::dispatch::before_frame(params.get("request_id").and_then(Value::as_str));
            framing::write_frame(pipe, payload.as_bytes()).await?;
            drop(writer);
            rx.await
                .map_err(|_| CuaError::Unreachable("helper response lost".into()))?
        })
        .await;
        match exchange {
            Ok(Ok(result)) => {
                guard.completed = true;
                Ok(result)
            }
            Ok(Err(error @ CuaError::Request { .. })) => {
                guard.completed = true;
                Err(error)
            }
            Ok(Err(error)) if mutates(method) => Err(CuaError::OutcomeUnknown(error.to_string())),
            Ok(Err(error)) => Err(error),
            Err(_) if mutates(method) => {
                Err(CuaError::OutcomeUnknown(format!("{method} timed out")))
            }
            Err(_) => Err(CuaError::Request {
                kind: "timeout".into(),
                message: format!("{method} timed out"),
            }),
        }
    }

    /// Protocol requests never retry a dispatched operation.
    pub async fn request(&self, method: &str, params: Value) -> Result<Value, CuaError> {
        self.exchange(self.connection().await?, method, params)
            .await
    }
    pub async fn request_in_session(
        &self,
        context: &CuaCallContext,
        method: &str,
        mut params: Value,
    ) -> Result<Value, CuaError> {
        if [
            &context.user_id,
            &context.tenant_id,
            &context.project_id,
            &context.device_id,
            &context.conversation_id,
            &context.run_id,
            &context.session_id,
        ]
        .iter()
        .any(|value| value.is_empty() || value.len() > 256)
        {
            return Err(CuaError::Request {
                kind: "invalid_context".into(),
                message: "all owner and session fields are required".into(),
            });
        }
        if method == "activate_app" && context.input_mode == crate::CuaInputMode::Background {
            return Err(CuaError::Request {
                kind: "background_input_requires_foreground_mode".into(),
                message: "explicit foreground input mode is required to activate an application"
                    .into(),
            });
        }
        let connection = self.connection().await?;
        let admission = connection.session_admission.lock().await;
        let bound = connection
            .sessions
            .lock()
            .await
            .get(&context.session_id)
            .cloned();
        if let Some((bound, _)) = bound {
            if bound != *context {
                return Err(CuaError::Request {
                    kind: "session_owner_mismatch".into(),
                    message: "the session belongs to another owner or run".into(),
                });
            }
        } else {
            let begun = self
                .exchange(
                    connection.clone(),
                    "begin_session",
                    serde_json::to_value(context)
                        .map_err(|e| CuaError::InvalidResponse(e.to_string()))?,
                )
                .await?;
            let generation = input_generation(&begun, context)
                .inspect_err(|_| connection.abort("invalid input binding"))?;
            connection
                .generations
                .lock()
                .await
                .insert(context.session_id.clone(), generation.clone());
            self.input_bindings.set(
                &connection.input_binding_id,
                &context.session_id,
                &generation,
            );
            let root = begun
                .get("artifact_root")
                .and_then(Value::as_str)
                .map(PathBuf::from);
            connection
                .sessions
                .lock()
                .await
                .insert(context.session_id.clone(), (context.clone(), root));
        }
        drop(admission);
        let object = params.as_object_mut().ok_or_else(|| CuaError::Request {
            kind: "invalid_params".into(),
            message: "params must be object".into(),
        })?;
        object.extend(
            serde_json::to_value(context)
                .map_err(|_| CuaError::InvalidResponse("invalid context".into()))?
                .as_object()
                .cloned()
                .ok_or_else(|| CuaError::InvalidResponse("invalid context".into()))?,
        );
        params["input_generation"] = json!(connection
            .generations
            .lock()
            .await
            .get(&context.session_id)
            .cloned()
            .ok_or_else(|| CuaError::InvalidResponse("input generation missing".into()))?);
        if matches!(
            method,
            "stop_session"
                | "end_session"
                | "cancel"
                | "reset"
                | "reset_session"
                | "pause_session"
                | "resume_session"
        ) {
            connection
                .observations
                .lock()
                .await
                .remove(&context.session_id);
        }
        let dispatched_generation = params["input_generation"].as_str().map(str::to_owned);
        let result = self.exchange(connection.clone(), method, params).await?;
        if result.get("input_generation").is_some() {
            let generation = input_generation(&result, context)?;
            let mut generations = connection.generations.lock().await;
            if generations.get(&context.session_id) != Some(&generation) {
                if !matches!(
                    method,
                    "get_app_state"
                        | "resume_session"
                        | "reset"
                        | "reset_session"
                        | "pause_session"
                ) || generations.get(&context.session_id) != dispatched_generation.as_ref()
                {
                    return Err(CuaError::InvalidResponse(
                        "stale native input generation".into(),
                    ));
                }
                // Observing another native target rotates the same binding as
                // resume/reset. A late response cannot replace a newer binding.
                connection
                    .observations
                    .lock()
                    .await
                    .remove(&context.session_id);
                self.input_bindings.set(
                    &connection.input_binding_id,
                    &context.session_id,
                    &generation,
                );
                generations.insert(context.session_id.clone(), generation);
                self.input_telemetry.send_modify(|latest| {
                    latest.remove(&context.session_id);
                });
            }
        }
        Ok(result)
    }
    pub async fn session_artifact_root(&self, session_id: &str) -> Option<PathBuf> {
        let connection = self.state.lock().await.as_ref().cloned()?;
        let root = connection
            .sessions
            .lock()
            .await
            .get(session_id)
            .and_then(|(_, root)| root.clone());
        root
    }
    pub async fn existing_session_artifact_root(&self, session_id: &str) -> Option<PathBuf> {
        if let Some(root) = self.session_artifact_root(session_id).await {
            return Some(root);
        }
        let connection = self.state.lock().await.as_ref().cloned()?;
        let root = connection
            .closed_sessions
            .lock()
            .await
            .get(session_id)
            .and_then(|(_, root)| root.clone());
        root
    }

    /// Only shrink or inspect an already-bound audio resource. Never spawn a
    /// helper or implicitly admit a new session after parent authority ended.
    pub async fn request_existing_session(
        &self,
        context: &CuaCallContext,
        method: &str,
        mut params: Value,
    ) -> Result<Value, CuaError> {
        if !matches!(method, "audio_status" | "audio_stop" | "audio_ack") {
            return Err(CuaError::Request {
                kind: "existing_session_operation_denied".into(),
                message: "only existing audio resource cleanup is allowed".into(),
            });
        }
        let connection = self
            .state
            .lock()
            .await
            .as_ref()
            .filter(|connection| connection.alive.load(Ordering::Acquire))
            .cloned()
            .ok_or_else(|| CuaError::Unreachable("helper disconnected".into()))?;
        let mut bound = connection
            .sessions
            .lock()
            .await
            .get(&context.session_id)
            .map(|(context, _)| context.clone());
        if bound.is_none() {
            bound = connection
                .closed_sessions
                .lock()
                .await
                .get(&context.session_id)
                .map(|(context, _)| context.clone());
        }
        if bound.as_ref() != Some(context) {
            return Err(CuaError::Request {
                kind: "session_owner_mismatch".into(),
                message: "an existing session with this owner is required".into(),
            });
        }
        params
            .as_object_mut()
            .ok_or_else(|| CuaError::InvalidResponse("invalid params".into()))?
            .extend(
                serde_json::to_value(context)
                    .map_err(|_| CuaError::InvalidResponse("invalid context".into()))?
                    .as_object()
                    .cloned()
                    .ok_or_else(|| CuaError::InvalidResponse("invalid context".into()))?,
            );
        params["input_generation"] = json!(connection
            .generations
            .lock()
            .await
            .get(&context.session_id)
            .cloned()
            .ok_or_else(|| CuaError::InvalidResponse("input generation missing".into()))?);
        self.exchange(connection, method, params).await
    }
    pub(crate) async fn remember_observation(
        &self,
        observation: crate::coordinates::ObservationCoordinates,
    ) -> agistack_core::CoreResult<()> {
        let connection = self
            .state
            .lock()
            .await
            .as_ref()
            .filter(|c| c.alive.load(Ordering::Acquire))
            .cloned()
            .ok_or_else(|| {
                agistack_core::CoreError::Tool("cua_snapshot_connection_closed".into())
            })?;
        if connection
            .generations
            .lock()
            .await
            .get(&observation.context.session_id)
            != Some(&observation.input_generation)
        {
            return Err(agistack_core::CoreError::Tool(
                "cua_snapshot_input_generation_mismatch".into(),
            ));
        }
        connection
            .observations
            .lock()
            .await
            .insert(observation.context.session_id.clone(), observation);
        Ok(())
    }
    pub(crate) async fn normalize_action(
        &self,
        context: &CuaCallContext,
        params: &mut Value,
    ) -> agistack_core::CoreResult<()> {
        self.transform_action(context, params, true).await
    }
    pub(crate) async fn validate_observed_action(
        &self,
        context: &CuaCallContext,
        params: &mut Value,
    ) -> agistack_core::CoreResult<()> {
        self.transform_action(context, params, false).await
    }
    async fn transform_action(
        &self,
        context: &CuaCallContext,
        params: &mut Value,
        consume: bool,
    ) -> agistack_core::CoreResult<()> {
        let missing = || {
            agistack_core::CoreError::Tool("cua_snapshot_missing: call computer_get_app_state before each action; every snapshot is single-use".into())
        };
        let connection = self
            .state
            .lock()
            .await
            .as_ref()
            .filter(|c| c.alive.load(Ordering::Acquire))
            .cloned()
            .ok_or_else(missing)?;
        let generation = connection
            .generations
            .lock()
            .await
            .get(&context.session_id)
            .cloned();
        let mut observations = connection.observations.lock().await;
        let observation = observations.get(&context.session_id).ok_or_else(missing)?;
        if generation.as_ref() != Some(&observation.input_generation) {
            return Err(agistack_core::CoreError::Tool(
                "cua_snapshot_input_generation_mismatch".into(),
            ));
        }
        observation.transform(context, params)?;
        if consume {
            observations.remove(&context.session_id);
        }
        Ok(())
    }
    pub async fn stop_session(&self, session_id: &str) -> Result<Value, CuaError> {
        self.finish_session(session_id, false, None).await
    }
    /// Preserve the lifecycle cause while using the native preemptive stop path.
    pub async fn stop_session_with_reason(
        &self,
        session_id: &str,
        reason: &str,
    ) -> Result<Value, CuaError> {
        self.finish_session(session_id, false, Some(reason)).await
    }
    pub async fn end_session(&self, session_id: &str) -> Result<Value, CuaError> {
        self.finish_session(session_id, true, None).await
    }
    async fn finish_session(
        &self,
        session_id: &str,
        end: bool,
        reason: Option<&str>,
    ) -> Result<Value, CuaError> {
        let state = self.state.lock().await;
        let Some(connection) = state
            .as_ref()
            .filter(|c| c.alive.load(Ordering::Acquire))
            .cloned()
        else {
            return Ok(json!({"stopped":true}));
        };
        drop(state);
        let context = connection
            .sessions
            .lock()
            .await
            .get(session_id)
            .map(|(context, _)| context.clone());
        let Some(context) = context else {
            return Ok(json!({"stopped":true}));
        };
        connection.observations.lock().await.remove(session_id);
        let mut params = serde_json::to_value(context)
            .map_err(|_| CuaError::InvalidResponse("invalid context".into()))?;
        params["input_generation"] =
            json!(connection.generations.lock().await.get(session_id).cloned());
        if let Some(reason) = reason {
            params["end_reason"] = json!(reason);
        }
        let result = self
            .exchange(
                connection.clone(),
                if end { "end_session" } else { "stop_session" },
                params,
            )
            .await;
        if result.is_err() {
            // A generation race must not leave held input behind after host revocation.
            connection.abort("native session cleanup failed");
        }
        self.input_telemetry.send_modify(|latest| {
            latest.remove(session_id);
        });
        if end {
            self.input_bindings
                .remove_session(&connection.input_binding_id, session_id);
            connection.input_sequences.lock().await.remove(session_id);
            if let Some(binding) = connection.sessions.lock().await.remove(session_id) {
                connection
                    .closed_sessions
                    .lock()
                    .await
                    .insert(session_id.into(), binding);
            }
        }
        result
    }
    pub async fn shutdown(&self) {
        self.input_telemetry.send_replace(BTreeMap::new());
        let connection = self.state.lock().await.take();
        if let Some(connection) = connection {
            connection.abort("runtime shutdown");
            let reaper = connection
                .reaper
                .lock()
                .ok()
                .and_then(|mut reaper| reaper.take());
            if let Some(reaper) = reaper {
                let _ = reaper.await;
            }
        }
    }
    pub async fn capabilities_if_connected(&self) -> Option<Result<Value, CuaError>> {
        let connection = self
            .state
            .lock()
            .await
            .as_ref()
            .filter(|connection| connection.alive.load(Ordering::Acquire))
            .cloned()?;
        Some(self.exchange(connection, "capabilities", json!({})).await)
    }
    pub async fn list_apps(&self) -> Result<Value, CuaError> {
        self.request("list_apps", json!({})).await
    }
    pub async fn accessibility_status(&self) -> Result<Value, CuaError> {
        self.request("accessibility_status", json!({})).await
    }
}
