use super::super::{
    computer_use_v2::call_identity::CallIdentity,
    execution_authority::{
        with_cell_lifetime, with_file_roots, with_human_wait_clock, with_step_id, with_step_origin,
        ExecutionAuthority, ExecutionScope, HumanWaitClock, StepOrigin,
    },
};
use super::{
    config::RuntimeConfig,
    external::{self, ExternalDispatch, ExternalRequest},
    kernel::{Kernel, FRAME_LIMIT},
    media, process,
};
use agistack_core::{
    agent::types::MediaAttachment,
    ports::{CoreError, CoreResult, PermissionKind, ToolControlOutcome, ToolResult},
};
use futures_util::{stream::FuturesUnordered, StreamExt};
#[path = "runtime_jobs.rs"]
mod jobs;
use jobs::{suspend_reads, OperationJob};
use serde_json::{json, Value};
use std::{
    collections::{HashMap, HashSet},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tokio::sync::{mpsc, Mutex as AsyncMutex};

#[derive(Default)]
pub(crate) struct ReplRuntime {
    sessions: Mutex<HashMap<String, Arc<Slot>>>,
}
struct Slot {
    state: AsyncMutex<Session>,
    cancelled: AtomicBool,
    run: Mutex<String>,
    context: Mutex<Option<ActiveCellContext>>,
    cloud_authority: Mutex<Option<Arc<ExecutionAuthority>>>,
}
#[derive(Clone)]
pub(crate) struct ActiveCellContext {
    pub request_id: Option<String>,
    identity: CallIdentity,
    lifetime: Arc<AtomicBool>,
    external: mpsc::Sender<ExternalRequest>,
}
impl ActiveCellContext {
    pub(crate) fn engine_session_id(&self) -> &str {
        self.identity.engine_session_id()
    }
    pub(crate) async fn submit(&self, dispatch: ExternalDispatch) -> CoreResult<Value> {
        if !self.lifetime.load(Ordering::SeqCst) {
            return Err(CoreError::Tool("repl_callback_cell_inactive".into()));
        }
        external::submit(&self.external, dispatch, self.request_id.clone()).await
    }
}
struct Session {
    config: RuntimeConfig,
    kernel: Option<Kernel>,
    cell: Option<Cell>,
    modules: Vec<std::path::PathBuf>,
}
struct Cell {
    id: String,
    code: String,
    run_id: String,
    conversation_id: String,
    execution_scope: ExecutionScope,
    approval: Option<PendingApproval>,
    identity: CallIdentity,
    seen: HashSet<String>,
    outputs: Vec<Value>,
    output_order: Vec<Value>,
    media: Vec<MediaAttachment>,
    bytes: usize,
    elapsed: Duration,
    pending: Option<Pending>,
    jobs: FuturesUnordered<OperationJob>,
    suspended_reads: Vec<Pending>,
    resume_reads_after: Option<String>,
    lifetime: Arc<AtomicBool>,
    external_tx: mpsc::Sender<ExternalRequest>,
    external_rx: mpsc::Receiver<ExternalRequest>,
    human_wait: Arc<HumanWaitClock>,
}
struct PendingApproval {
    step_id: String,
    tool: String,
    key: String,
}

struct Pending {
    frame: Value,
    step_id: String,
    parent_request_id: Option<String>,
    external: Option<ExternalRequest>,
    interrupted: bool,
}
enum RpcOutput {
    Value(Value),
    Control(ToolResult),
    Permission(ToolResult),
}
impl RpcOutput {
    async fn from_tool(result: ToolResult) -> Result<Self, String> {
        if result.permission_required.is_some() {
            if result.control_outcome.is_some() || result.control_generation.is_some() {
                return Err("repl_invalid_permission_control".into());
            }
            Ok(Self::Permission(result))
        } else if result.control_outcome.is_some() {
            Ok(Self::Control(result))
        } else {
            media::tool_value(&result).await.map(Self::Value)
        }
    }
}

impl ReplRuntime {
    pub(crate) fn pending_permission_scope(
        &self,
        conversation: &str,
        run: &str,
        step: &str,
        tool: &str,
    ) -> Option<(ExecutionScope, String)> {
        self.sessions.lock().ok()?.values().find_map(|slot| {
            if slot.cancelled.load(Ordering::SeqCst) {
                return None;
            }
            let session = slot.state.try_lock().ok()?;
            let cell = session.cell.as_ref()?;
            let approval = cell.approval.as_ref()?;
            if cell.conversation_id != conversation
                || cell.run_id != run
                || approval.step_id != step
                || approval.tool != tool
                || cell.pending.as_ref()?.step_id != step
            {
                return None;
            }
            Some((
                cell.execution_scope.clone(),
                cell.identity.engine_session_id().into(),
            ))
        })
    }

    pub(super) fn pending_permission_key(
        &self,
        conversation: &str,
        run: &str,
        engine: Option<&str>,
        step: &str,
        tool: &str,
    ) -> Option<String> {
        self.sessions.lock().ok()?.values().find_map(|slot| {
            if slot.cancelled.load(Ordering::SeqCst) {
                return None;
            }
            let session = slot.state.try_lock().ok()?;
            let cell = session.cell.as_ref()?;
            if cell.run_id != run
                || cell.conversation_id != conversation
                || engine.is_some_and(|engine| engine != cell.identity.engine_session_id())
            {
                return None;
            }
            let approval = cell.approval.as_ref()?;
            (approval.step_id == step && approval.tool == tool).then(|| approval.key.clone())
        })
    }

    pub(crate) fn active_context_for(&self, run: &str, engine: &str) -> Option<ActiveCellContext> {
        self.sessions.lock().ok()?.values().find_map(|slot| {
            if slot.cancelled.load(Ordering::SeqCst) || *slot.run.lock().ok()? != run {
                return None;
            }
            slot.context.lock().ok()?.clone().filter(|context| {
                context.lifetime.load(Ordering::SeqCst) && context.engine_session_id() == engine
            })
        })
    }
    pub(crate) fn cancel_run(&self, run_id: &str) {
        for slot in self.sessions.lock().expect("REPL sessions").values() {
            if *slot.run.lock().expect("REPL run") == run_id {
                slot.cancelled.store(true, Ordering::SeqCst);
                if let Ok(mut session) = slot.state.try_lock() {
                    session.kernel.take();
                    session.cell.take();
                }
            }
        }
    }
    pub(crate) fn shutdown(&self) {
        for slot in self.sessions.lock().expect("REPL sessions").values() {
            slot.cancelled.store(true, Ordering::SeqCst);
            if let Ok(mut session) = slot.state.try_lock() {
                session.kernel.take();
                session.cell.take();
            }
        }
    }

    pub(super) async fn execute(
        &self,
        key: String,
        authority: Arc<ExecutionAuthority>,
        identity: CallIdentity,
        tool: &str,
        input: Value,
        configure: impl FnOnce() -> Result<RuntimeConfig, String>,
    ) -> CoreResult<ToolResult> {
        authority.current()?;
        let slot = {
            let mut sessions = self.sessions.lock().expect("REPL sessions");
            sessions.retain(|_, slot| !slot.cancelled.load(Ordering::SeqCst));
            if sessions
                .get(&key)
                .is_some_and(|slot| slot.cancelled.load(Ordering::SeqCst))
            {
                sessions.remove(&key);
            }
            if let Some(slot) = sessions.get(&key) {
                slot.clone()
            } else {
                let config = configure().map_err(CoreError::Tool)?;
                let slot = Arc::new(Slot {
                    state: AsyncMutex::new(Session {
                        config,
                        kernel: None,
                        cell: None,
                        modules: vec![],
                    }),
                    cancelled: AtomicBool::new(false),
                    run: Mutex::new(authority.scope().run_id.clone()),
                    context: Mutex::new(None),
                    cloud_authority: Mutex::new(None),
                });
                sessions.insert(key, slot.clone());
                slot
            }
        };
        let mut session = slot
            .state
            .try_lock()
            .map_err(|_| CoreError::Tool("repl_cell_busy".into()))?;
        // A rejected source correction is not an execution failure. Preserve
        // only the same authorized scope and engine's suspended operation;
        // unrelated execution identities retain the destructive error path.
        if tool == "cua_repl_js"
            && !slot.cancelled.load(Ordering::SeqCst)
            && input["code"].as_str().is_some_and(|code| {
                code.len() <= 1024 * 1024
                    && session.cell.as_ref().is_some_and(|cell| {
                        // Match the existing MCP App continuation identity rule:
                        // authenticated revisions may advance, other scope facts cannot.
                        let mut expected = cell.execution_scope.clone();
                        expected.run_revision = authority.scope().run_revision;
                        cell.pending.is_some()
                            && expected == *authority.scope()
                            && authority.scope().run_revision >= cell.execution_scope.run_revision
                            && cell.identity.engine_session_id() == identity.engine_session_id()
                            && cell.code != code
                    })
            })
        {
            return Err(CoreError::Tool(format!(
                "repl_pending_cell_requires_exact_code_and_run: cell {} is retained; retry with byte-identical original code, including comments and whitespace",
                session.cell.as_ref().expect("pending cell").id,
            )));
        }
        if tool == "cua_repl_js" && session.kernel.is_none() {
            let sessions = self.sessions.lock().expect("REPL sessions");
            let active = sessions
                .values()
                .filter(|other| !Arc::ptr_eq(other, &slot))
                .filter(|other| {
                    other.state.try_lock().map_or(true, |session| {
                        session.kernel.is_some() || session.cell.is_some()
                    })
                })
                .count();
            if active >= 16 {
                return Err(CoreError::Tool(
                    "repl_session_limit_reset_an_inactive_session".into(),
                ));
            }
        }
        *slot.run.lock().expect("REPL run") = authority.scope().run_id.clone();
        // Cloud backends hold Weak<State>; keeping them alive preserves scoped MCP App tabs.
        if matches!(&*authority, ExecutionAuthority::CloudClaim(_)) {
            *slot.cloud_authority.lock().expect("REPL cloud authority") = Some(authority.clone());
        }
        let timeout = input["timeout_ms"]
            .as_u64()
            .unwrap_or(30_000)
            .clamp(1, 300_000);
        let result = session
            .execute(
                &slot,
                authority,
                identity,
                tool,
                input,
                Duration::from_millis(timeout),
            )
            .await;
        if result.is_err()
            || result
                .as_ref()
                .is_ok_and(|result| result.control_outcome == Some(ToolControlOutcome::UserStopped))
        {
            session.kernel.take();
            session.cell.take();
        }
        if tool == "cua_repl_reset" && result.is_ok() {
            slot.context.lock().expect("REPL cell context").take();
            slot.cloud_authority
                .lock()
                .expect("REPL cloud authority")
                .take();
            if session.modules.is_empty() {
                slot.cancelled.store(true, Ordering::SeqCst);
            }
        }
        result.map_err(CoreError::Tool)
    }
}

impl Session {
    async fn ensure_kernel(&mut self) -> Result<(), String> {
        if self.kernel.is_none() {
            self.config.sandbox.module_roots = self.modules.clone();
            let mut kernel = Kernel::start(&self.config).await?;
            for root in &self.modules {
                let id = uuid::Uuid::new_v4().to_string();
                kernel
                    .send(&json!({"type":"add_module_dir","id":id,"path":root}))
                    .await?;
                let response = kernel.read().await?;
                if response["id"] != id || response["ok"] != true {
                    return Err("repl_module_registration_failed".into());
                }
            }
            self.kernel = Some(kernel);
        }
        Ok(())
    }
    async fn execute(
        &mut self,
        slot: &Slot,
        authority: Arc<ExecutionAuthority>,
        identity: CallIdentity,
        tool: &str,
        input: Value,
        timeout: Duration,
    ) -> Result<ToolResult, String> {
        if tool == "cua_repl_reset" {
            self.kernel.take();
            self.cell.take();
            return Ok(ToolResult::text(
                json!({"reset":true,"module_directories_preserved":true}).to_string(),
            ));
        }
        if tool == "cua_repl_add_module_dir" {
            if self.cell.is_some() {
                return Err("repl_cell_busy".into());
            }
            let root =
                std::path::Path::new(input["path"].as_str().ok_or("repl_module_path_required")?)
                    .canonicalize()
                    .map_err(|_| "repl_module_path_missing")?;
            if !root.is_dir()
                || self
                    .config
                    .sandbox
                    .protected
                    .iter()
                    .any(|protected| root.starts_with(protected) || protected.starts_with(&root))
            {
                return Err("repl_module_path_forbidden".into());
            }
            if self.modules.len() >= 32 {
                return Err("repl_module_limit".into());
            }
            if !self.modules.contains(&root) {
                self.modules.push(root);
                self.kernel.take();
            }
            return Ok(ToolResult::text(
                json!({"registered":true,"kernel_reset":true}).to_string(),
            ));
        }
        let code = input["code"].as_str().ok_or("repl_code_required")?;
        if code.len() > 1024 * 1024 {
            return Err("repl_code_too_large".into());
        }
        self.ensure_kernel().await?;
        if let Some(cell) = &self.cell {
            if cell.code != code
                || cell.run_id != authority.scope().run_id
                || cell.identity.engine_session_id() != identity.engine_session_id()
            {
                return Err("repl_pending_cell_requires_exact_code_and_run".into());
            }
        } else {
            let id = uuid::Uuid::new_v4().to_string();
            self.kernel.as_mut().expect("kernel").send(&json!({"type":"execute","id":id,"code":code,"context":{"cwd":self.config.sandbox.workspace,"temporaryDirectory":self.config.sandbox.temporary,"enabledSurfaces":["browser","computer"],"platform":"darwin","requestMeta":{"engine_session_id":identity.engine_session_id(),"conversation_id":authority.scope().conversation_id,"run_id":authority.scope().run_id,"cell_id":id}}})).await?;
            let (external_tx, external_rx) = mpsc::channel(32);
            self.cell = Some(Cell {
                external_tx,
                external_rx,
                human_wait: Arc::new(HumanWaitClock::default()),
                id,
                code: code.into(),
                run_id: authority.scope().run_id.clone(),
                conversation_id: authority.scope().conversation_id.clone(),
                execution_scope: authority.scope().clone(),
                approval: None,
                identity,
                seen: HashSet::new(),
                outputs: vec![],
                output_order: vec![],
                media: vec![],
                bytes: 0,
                elapsed: Duration::ZERO,
                pending: None,
                jobs: FuturesUnordered::new(),
                suspended_reads: Vec::new(),
                resume_reads_after: None,
                lifetime: Arc::new(AtomicBool::new(true)),
            });
        }
        let previous_scope = self.cell.as_ref().expect("cell").execution_scope.clone();
        self.cell.as_mut().expect("cell").execution_scope = authority.scope().clone();
        if let Some(pending) = self.cell.as_mut().expect("cell").pending.take() {
            self.cell.as_mut().expect("cell").approval = None;
            self.cell.as_mut().expect("cell").lifetime = Arc::new(AtomicBool::new(true));
            let continuation = (!pending.interrupted).then_some(previous_scope);
            self.enqueue(authority.clone(), pending, continuation);
        }
        let cell = self.cell.as_ref().expect("cell");
        *slot.context.lock().expect("REPL cell context") = Some(ActiveCellContext {
            request_id: authority.request_id().map(str::to_string),
            identity: cell.identity.clone(),
            lifetime: cell.lifetime.clone(),
            external: cell.external_tx.clone(),
        });
        let started = Instant::now();
        let excluded_at_start = cell.human_wait.excluded();
        loop {
            if slot.cancelled.load(Ordering::SeqCst) {
                return Err("repl_cancelled".into());
            }
            let cell = self.cell.as_mut().expect("cell");
            let charged = started
                .elapsed()
                .saturating_sub(cell.human_wait.excluded().saturating_sub(excluded_at_start));
            if charged + cell.elapsed >= timeout {
                return Err("repl_execution_timeout".into());
            }
            let frame = tokio::select! {
                biased;
                completed = cell.jobs.next(), if !cell.jobs.is_empty() => {
                    let (mut pending, result) = completed.ok_or("repl_rpc_job_missing")?;
                    if let Ok(RpcOutput::Permission(mut result)) = result {
                        let permission = result.permission_required.as_ref().expect("typed permission");
                        let binding = permission.binding();
                        if binding.cell_id.as_deref() != Some(cell.id.as_str())
                            || binding.step_id.as_deref() != Some(pending.step_id.as_str())
                            || binding.engine_session_id.as_deref() != Some(cell.identity.engine_session_id()) {
                            return Err("repl_permission_binding_mismatch".into());
                        }
                        let demand = permission.demand();
                        cell.approval = if permission.kind() == PermissionKind::ToolStep {
                            if demand["step_id"] != pending.step_id || demand["tool_name"] != binding.tool_name {
                                return Err("repl_permission_demand_mismatch".into());
                            }
                            Some(PendingApproval {
                                step_id: pending.step_id.clone(),
                                tool: binding.tool_name.clone(),
                                key: super::super::authorized_tool_host::step_permission_key(&pending.step_id, &binding.tool_name, &demand["arguments"])
                                    .map_err(|error| error.to_string())?,
                            })
                        } else { None };
                        cell.resume_reads_after = Some(pending.step_id.clone());
                        cell.suspended_reads.extend(suspend_reads(&mut cell.jobs));
                        cell.pending = Some(pending);
                        cell.lifetime.store(false, Ordering::SeqCst);
                        cell.elapsed += charged;
                        let display: Value = serde_json::from_str(&result.output_json).unwrap_or_else(|_| json!({"text":result.output_json}));
                        let mut display = if display.is_object() { display } else { json!({"value":display}) };
                        display["repl_continuation"] = json!({"cell_id":cell.id,"resume":"Request the returned permission, then call cua_repl_js with exactly the same code. Only the pending operation resumes; completed steps are never replayed."});
                        result.output_json = display.to_string();
                        return Ok(result);
                    }
                    if let Ok(RpcOutput::Control(result)) = result {
                        cell.lifetime.store(false, Ordering::SeqCst);
                        cell.elapsed += charged;
                        if result.control_outcome == Some(ToolControlOutcome::UserPaused) {
                            // A native interruption may have partial effects. Never dispatch it twice.
                            pending.interrupted = true;
                            cell.pending = Some(pending);
                        }
                        return Ok(result);
                    }
                    let result = result.map(|value| match value { RpcOutput::Value(value) => value, RpcOutput::Control(_) | RpcOutput::Permission(_) => unreachable!("handled control or permission") });
                    if cell.resume_reads_after.as_deref() == Some(pending.step_id.as_str()) {
                        self.resume_reads(authority.clone(), result.as_ref().err()).await?;
                    }
                    if let Some(external) = pending.external {
                        let _ = external.response.send(result);
                        continue;
                    }
                    let response = match result { Ok(value) => json!({"type":"rpc_response","id":pending.frame["id"],"result":value}),
                        Err(message) => json!({"type":"rpc_response","id":pending.frame["id"],"error":{"code":"repl_operation_failed","message":message}}) };
                    self.kernel.as_mut().expect("kernel").send(&response).await?;
                    continue;
                }
                external = cell.external_rx.recv() => {
                    let external = external.ok_or("repl_callback_channel_closed")?;
                    if cell.jobs.len() + cell.suspended_reads.len() >= 32 { let _ = external.response.send(Err("repl_concurrent_operation_limit".into())); continue; }
                    authority.current().map_err(|error|error.to_string())?;
                    let pending = Pending { frame:Value::Null,step_id:external.step_id.clone(),parent_request_id:external.parent_request_id.clone(),external:Some(external),interrupted:false };
                    self.enqueue(authority.clone(),pending,None);
                    continue;
                }
                frame = self.kernel.as_mut().expect("kernel").read() => frame?,
                _ = tokio::time::sleep(Duration::from_millis(100)) => {
                    authority.current().map_err(|error|error.to_string())?;
                    continue;
                },
            };
            match frame["type"].as_str() {
                Some("rpc") => {
                    authority.current().map_err(|error| error.to_string())?;
                    let cell = self.cell.as_mut().expect("cell");
                    let id = frame["id"]
                        .as_str()
                        .ok_or("repl_rpc_id_required")?
                        .to_string();
                    if frame["executionId"] != cell.id
                        || !cell.seen.insert(id)
                        || cell.seen.len() > 10_000
                    {
                        return Err("repl_rpc_replayed_or_stale".into());
                    }
                    if cell.jobs.len() + cell.suspended_reads.len() >= 32 {
                        return Err("repl_concurrent_operation_limit".into());
                    }
                    self.enqueue(
                        authority.clone(),
                        Pending {
                            frame,
                            step_id: uuid::Uuid::new_v4().to_string(),
                            parent_request_id: authority.request_id().map(str::to_string),
                            external: None,
                            interrupted: false,
                        },
                        None,
                    );
                }
                Some("output") => {
                    let cell = self.cell.as_mut().expect("cell");
                    if frame["id"] != cell.id {
                        return Err("repl_output_stale".into());
                    }
                    cell.bytes += frame.to_string().len();
                    if cell.bytes > FRAME_LIMIT * 2 {
                        return Err("repl_output_budget_exceeded".into());
                    }
                    let emitted = if frame["content"].get("filename").is_some() {
                        let (media, bytes) = super::file_media::materialize(
                            &self.config.artifact_root.join(&cell.id),
                            &self.config.sandbox.temporary,
                            &frame["content"],
                        )
                        .await?;
                        cell.bytes = cell
                            .bytes
                            .checked_add(bytes)
                            .ok_or("repl_output_budget_exceeded")?;
                        if cell.bytes > FRAME_LIMIT * 2 {
                            return Err("repl_output_budget_exceeded".into());
                        }
                        Some(media)
                    } else {
                        media::from_output(
                            &self.config.artifact_root.join(&cell.id),
                            &frame["content"],
                        )
                        .await?
                    };
                    if let Some(media) = emitted {
                        cell.output_order
                            .push(json!({"source":"media","index":cell.media.len()}));
                        cell.media.push(media);
                    } else {
                        cell.output_order
                            .push(json!({"source":"text","index":cell.outputs.len()}));
                        cell.outputs.push(frame["content"].clone());
                    }
                }
                Some("result") => {
                    let mut cell = self.cell.take().expect("cell");
                    if frame["id"] != cell.id {
                        return Err("repl_result_stale".into());
                    }
                    if !cell.jobs.is_empty()
                        || cell.pending.is_some()
                        || !cell.suspended_reads.is_empty()
                        || cell.resume_reads_after.is_some()
                    {
                        return Err("repl_result_before_operations_settled".into());
                    }
                    return Ok(ToolResult { output_json: json!({"cell_id":cell.id,"ok":frame["ok"],"value":frame["value"],"error":frame["error"],"outputs":cell.outputs,"output_order":cell.output_order}).to_string(), media: std::mem::take(&mut cell.media), control_outcome: None, control_generation: None, permission_required: None });
                }
                _ => return Err("repl_unexpected_protocol_frame".into()),
            }
        }
    }

    async fn resume_reads(
        &mut self,
        authority: Arc<ExecutionAuthority>,
        failure: Option<&String>,
    ) -> Result<(), String> {
        let cell = self.cell.as_mut().expect("cell");
        cell.resume_reads_after = None;
        let reads = std::mem::take(&mut cell.suspended_reads);
        for pending in reads {
            if let Some(failure) = failure {
                self.kernel
                    .as_mut()
                    .expect("kernel")
                    .send(&json!({
                        "type":"rpc_response","id":pending.frame["id"],
                        "error":{"code":"repl_operation_failed","message":failure}
                    }))
                    .await?;
            } else {
                // The exact pending operation has succeeded through fresh policy
                // admission. Re-admit each read independently with current scope.
                self.enqueue(authority.clone(), pending, None);
            }
        }
        Ok(())
    }

    fn enqueue(
        &mut self,
        authority: Arc<ExecutionAuthority>,
        pending: Pending,
        continuation_scope: Option<super::super::execution_authority::ExecutionScope>,
    ) {
        let cell = self.cell.as_mut().expect("cell");
        let identity = cell.identity.clone();
        let config = self.config.clone();
        let lifetime = cell.lifetime.clone();
        let human_wait = cell.human_wait.clone();
        let origin = StepOrigin {
            cell_id: cell.id.clone(),
            parent_request_id: pending.parent_request_id.clone(),
            continuation_scope,
        };
        let roots = vec![
            config.sandbox.workspace.clone(),
            config.sandbox.temporary.clone(),
        ];
        let read = jobs::pending_read(&pending);
        let future = Box::pin(async move {
            let operation = async {
                if pending.interrupted {
                    return Err("repl_native_operation_interrupted: action may have partial effects; observe current application state before choosing another action".into());
                }
                if let Some(external) = &pending.external {
                    if external.response.is_closed() {
                        return Err("repl_callback_cancelled_before_dispatch".into());
                    }
                    let result = (external.dispatch)(authority.clone())
                        .await
                        .map_err(|error| error.to_string())?;
                    RpcOutput::from_tool(result).await
                } else {
                    dispatch(&config, &authority, &pending.frame).await
                }
            };
            // Task-local scopes retain their input future as well as their scoped
            // state. Box the operation before nesting scopes so each level carries
            // a pointer instead of repeatedly embedding the dispatch state machine.
            let operation = Box::pin(operation);
            let scoped = with_human_wait_clock(
                human_wait,
                with_file_roots(
                    roots,
                    with_step_origin(
                        origin,
                        with_cell_lifetime(
                            lifetime,
                            with_step_id(
                                pending.step_id.clone(),
                                identity.for_tool("cua_repl_js", operation),
                            ),
                        ),
                    ),
                ),
            );
            #[cfg(test)]
            assert!(
                std::mem::size_of_val(&scoped) <= 16 * 1024,
                "REPL operation scopes must leave room for nested policy and tool dispatch"
            );
            let result = scoped.await;
            (pending, result)
        });
        cell.jobs.push(OperationJob::from_parts(read, future));
    }
}

async fn dispatch(
    config: &RuntimeConfig,
    authority: &ExecutionAuthority,
    frame: &Value,
) -> Result<RpcOutput, String> {
    let params = &frame["params"];
    let (tool, arguments) = match frame["method"].as_str() {
        Some("computer.call" | "browser.call") => {
            let tool = params["tool"].as_str().ok_or("repl_tool_required")?;
            let family = if frame["method"] == "computer.call" {
                "computer_"
            } else {
                "browser_"
            };
            if !tool.starts_with(family) {
                return Err("repl_service_tool_mismatch".into());
            }
            (
                tool.to_string(),
                params
                    .get("arguments")
                    .cloned()
                    .unwrap_or_else(|| json!({})),
            )
        }
        Some("browser.operation") => (
            agistack_adapters_browser::facade::operation_effect(params)
                .map_err(|error| error.to_string())?
                .tool()
                .to_string(),
            params.clone(),
        ),
        Some("process.spawn") => {
            authority.current().map_err(|error| error.to_string())?;
            return process::execute(config, params).await.map(RpcOutput::Value);
        }
        _ => return Err("repl_service_unknown".into()),
    };
    let result = authority
        .call(&tool, &arguments.to_string())
        .await
        .map_err(|error| error.to_string())?;
    RpcOutput::from_tool(result).await
}

impl Drop for Session {
    fn drop(&mut self) {
        self.kernel.take();
        let _ = std::fs::remove_dir_all(&self.config.sandbox.temporary);
    }
}
impl Drop for Cell {
    fn drop(&mut self) {
        self.lifetime.store(false, Ordering::SeqCst);
    }
}

#[cfg(all(test, target_os = "macos"))]
#[path = "runtime_tests.rs"]
mod tests;
