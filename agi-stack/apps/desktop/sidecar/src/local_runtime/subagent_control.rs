//! Controls only registered child executions; never resolves child ids as parent runs.

use std::collections::{BTreeMap, VecDeque};

use super::*;

#[derive(Default)]
pub(super) struct SubagentControls {
    executions: Mutex<HashMap<String, Arc<SubagentControl>>>,
}

pub(super) struct SubagentControl {
    execution_id: String,
    conversation_id: String,
    parent_run_id: String,
    parent_revision: u64,
    subagent_id: String,
    parent_agent_id: String,
    parent: Arc<LocalRunControl>,
    inner: Mutex<ControlState>,
}

#[derive(Default)]
struct ControlState {
    cancelled: bool,
    terminal: bool,
    steering: VecDeque<SteeringInstruction>,
    receipts: BTreeMap<String, (Value, Value)>,
}

impl SubagentControls {
    pub(super) fn register(
        &self,
        execution_id: &str,
        conversation_id: &str,
        run: &DesktopRun,
        subagent_id: &str,
        parent_agent_id: &str,
        parent: Arc<LocalRunControl>,
    ) -> CoreResult<Arc<SubagentControl>> {
        let mut executions = self.executions.lock().map_err(|_| control_error())?;
        // Completed parents cannot retain an unbounded in-memory receipt ledger.
        executions.retain(|_, entry| {
            entry.conversation_id != conversation_id || entry.parent_run_id == run.id
        });
        if let Some(existing) = executions.get(execution_id).cloned() {
            drop(executions);
            if existing.conversation_id == conversation_id
                && existing.parent_run_id == run.id
                && existing.parent_revision == run.revision
                && existing.subagent_id == subagent_id
                && existing.parent_agent_id == parent_agent_id
                && Arc::ptr_eq(&existing.parent, &parent)
                && existing.inner.lock().map_err(|_| control_error())?.terminal
            {
                return Ok(existing);
            }
            return Err(CoreError::Tool(
                "SubAgent execution is already registered".to_string(),
            ));
        }
        let control = Arc::new(SubagentControl {
            execution_id: execution_id.to_string(),
            conversation_id: conversation_id.to_string(),
            parent_run_id: run.id.clone(),
            parent_revision: run.revision,
            subagent_id: subagent_id.to_string(),
            parent_agent_id: parent_agent_id.to_string(),
            parent,
            inner: Mutex::new(ControlState::default()),
        });
        executions.insert(execution_id.to_string(), Arc::clone(&control));
        Ok(control)
    }

    pub(super) fn plugin_execution_current(&self, execution_id: &str, conversation_id: &str, run: &DesktopRun, subagent_id: &str, parent: Option<&Arc<LocalRunControl>>) -> bool {
        let Some(parent) = parent else { return false; };
        let Some(control) = self.get(execution_id) else { return false; };
        control.conversation_id == conversation_id && control.parent_run_id == run.id && control.parent_revision == run.revision && control.subagent_id == subagent_id && Arc::ptr_eq(&control.parent, parent) && parent.directive.load(Ordering::Acquire) == LocalRunControl::CONTINUE && control.inner.lock().is_ok_and(|inner| !inner.cancelled && !inner.terminal)
    }

    fn get(&self, execution_id: &str) -> Option<Arc<SubagentControl>> {
        self.executions.lock().ok()?.get(execution_id).cloned()
    }

    pub(super) fn is_registered(&self, execution_id: &str) -> bool {
        self.get(execution_id).is_some()
    }

    pub(super) fn is_terminal(&self, execution_id: &str) -> bool {
        self.get(execution_id).is_some_and(|control| {
            control
                .inner
                .lock()
                .map(|inner| inner.terminal)
                .unwrap_or(true)
        })
    }

    pub(super) fn participants(&self, conversation_id: &str) -> Vec<String> {
        self.executions
            .lock()
            .map(|entries| {
                entries
                    .values()
                    .filter(|entry| entry.conversation_id == conversation_id)
                    .map(|entry| entry.subagent_id.clone())
                    .collect::<BTreeSet<_>>()
                    .into_iter()
                    .collect()
            })
            .unwrap_or_default()
    }

    pub(super) fn complete(&self, execution_id: &str) -> bool {
        let Some(control) = self.get(execution_id) else {
            return false;
        };
        let Ok(mut inner) = control.inner.lock() else {
            return false;
        };
        inner.terminal = true;
        inner.steering.clear();
        inner.cancelled
            || control.parent.directive.load(Ordering::Acquire) == LocalRunControl::CANCEL
    }

    pub(super) fn release_parent(&self, parent: &Arc<LocalRunControl>) {
        if let Ok(mut executions) = self.executions.lock() {
            executions.retain(|_, execution| !Arc::ptr_eq(&execution.parent, parent));
        }
    }
}

#[async_trait]
impl ReActControl for SubagentControl {
    async fn directive(&self, session_id: &str, _round: u64) -> CoreResult<RunDirective> {
        if session_id != self.execution_id {
            return Err(control_error());
        }
        let inner = self.inner.lock().map_err(|_| control_error())?;
        if inner.cancelled
            || self.parent.directive.load(Ordering::Acquire) == LocalRunControl::CANCEL
        {
            return Ok(RunDirective::Cancel);
        }
        if self.parent.directive.load(Ordering::Acquire) == LocalRunControl::PAUSE {
            return Ok(RunDirective::Pause);
        }
        if inner.terminal {
            return Err(control_error());
        }
        Ok(inner
            .steering
            .front()
            .cloned()
            .map(RunDirective::Steer)
            .unwrap_or(RunDirective::Continue))
    }

    async fn acknowledge_steering(
        &self,
        session_id: &str,
        instruction_id: &str,
        _round: u64,
    ) -> CoreResult<()> {
        if session_id != self.execution_id {
            return Err(control_error());
        }
        let mut inner = self.inner.lock().map_err(|_| control_error())?;
        // A cancellation can clear the queue while the engine persists an
        // already-delivered instruction. Let the next boundary persist Cancel.
        if inner.cancelled
            || self.parent.directive.load(Ordering::Acquire) == LocalRunControl::CANCEL
        {
            return Ok(());
        }
        if inner
            .steering
            .front()
            .is_some_and(|instruction| instruction.id == instruction_id)
        {
            inner.steering.pop_front();
            Ok(())
        } else {
            Err(control_error())
        }
    }
}

fn control_error() -> CoreError {
    CoreError::Tool("SubAgent control authority is unavailable".to_string())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlCommand {
    #[serde(rename = "type")]
    action: String,
    conversation_id: String,
    run_id: String,
    expected_run_revision: u64,
    idempotency_key: String,
    instruction: Option<String>,
    #[serde(default)]
    cascade: bool,
}

pub(super) async fn handle_command(
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    payload: &Value,
) -> Value {
    let mut receipt = json!({
        "type": "control_command_ack",
        "action": payload["type"],
        "accepted": false,
        "duplicate": false,
        "conversation_id": payload["conversation_id"],
        "run_id": payload["run_id"],
        "run_revision": Value::Null,
        "idempotency_key": payload["idempotency_key"],
        "project_id": authenticated.workspace.project_id,
        "cascade": payload["cascade"].as_bool().unwrap_or(false),
        "reason_code": "invalid_control_command",
    });
    let Ok(command) = serde_json::from_value::<ControlCommand>(payload.clone()) else {
        return receipt;
    };
    if !matches!(command.action.as_str(), "steer" | "kill_run")
        || command.expected_run_revision == 0
        || command.idempotency_key.trim().is_empty()
        || command.idempotency_key.len() > 255
        || command.run_id.is_empty()
        || command.cascade
        || (command.action == "steer"
            && command.instruction.as_ref().map_or(true, |text| {
                text.trim().is_empty() || text.len() > 64 * 1024 || text.contains('\0')
            }))
    {
        return receipt;
    }
    let Ok(conversation) = scoped_conversation(state, authenticated, &command.conversation_id)
    else {
        receipt["reason_code"] = json!("control_scope_denied");
        return receipt;
    };
    let Some(control) = state
        .subagent_controls
        .get(&command.run_id)
        .filter(|control| control.conversation_id == conversation.id)
    else {
        receipt["reason_code"] = json!("subagent_control_denied");
        return receipt;
    };
    receipt["run_revision"] = json!(control.parent_revision);
    if !state
        .session_store
        .session_context_is_current(authenticated, Utc::now().timestamp_millis())
        .unwrap_or(false)
    {
        receipt["reason_code"] = json!("stale_workspace_context");
        return receipt;
    }
    if command.expected_run_revision != control.parent_revision {
        receipt["reason_code"] = json!("run_revision_conflict");
        return receipt;
    }
    let Some(parent_snapshot) = state
        .session_store
        .run(&control.parent_run_id)
        .ok()
        .flatten()
    else {
        receipt["reason_code"] = json!("no_active_run");
        return receipt;
    };
    // Reuse the parent operation's persisted checkpoint ownership and authority
    // guard. No control or registry mutex is held across checkpoint I/O.
    if ensure_checkpoint_control_authority(state, &parent_snapshot)
        .await
        .is_err()
    {
        receipt["reason_code"] = json!("checkpoint_control_authority_unavailable");
        return receipt;
    }
    if !state
        .session_store
        .session_context_is_current(authenticated, Utc::now().timestamp_millis())
        .unwrap_or(false)
    {
        receipt["reason_code"] = json!("stale_workspace_context");
        return receipt;
    }
    let Ok(mut inner) = control.inner.lock() else {
        return receipt;
    };
    if let Some((original, accepted)) = inner.receipts.get(&command.idempotency_key) {
        if original != payload {
            receipt["reason_code"] = json!("control_idempotency_conflict");
            return receipt;
        }
        let mut duplicate = accepted.clone();
        duplicate["duplicate"] = json!(true);
        return duplicate;
    }
    let Some(run) = state
        .session_store
        .run(&control.parent_run_id)
        .ok()
        .flatten()
    else {
        receipt["reason_code"] = json!("no_active_run");
        return receipt;
    };
    if run.conversation_id != conversation.id
        || run.project_id != conversation.project_id
        || run.revision != command.expected_run_revision
        || run.status != DesktopRunStatus::Running
        || !state
            .control_for_run(&run)
            .is_some_and(|parent| Arc::ptr_eq(&parent, &control.parent))
    {
        receipt["reason_code"] = json!("run_revision_conflict");
        return receipt;
    }
    if ensure_checkpoint_run_ownership(state, &run).is_err() {
        receipt["reason_code"] = json!("checkpoint_control_authority_unavailable");
        return receipt;
    }
    if inner.terminal
        || inner.cancelled
        || control.parent.directive.load(Ordering::Acquire) == LocalRunControl::CANCEL
    {
        receipt["reason_code"] = json!("subagent_control_execution_terminal");
        return receipt;
    }
    if inner.receipts.len() >= 1024 {
        receipt["reason_code"] = json!("subagent_control_capacity_exceeded");
        return receipt;
    }
    if !currently_authorized(
        state,
        &conversation,
        &control.subagent_id,
        &control.parent_agent_id,
    ) {
        receipt["reason_code"] = json!("subagent_control_denied");
        return receipt;
    }
    if command.action == "kill_run" {
        inner.cancelled = true;
        inner.steering.clear();
    } else {
        inner.steering.push_back(SteeringInstruction {
            id: format!("{}:{}", command.run_id, command.idempotency_key),
            content: command.instruction.unwrap_or_default(),
        });
    }
    receipt["accepted"] = json!(true);
    receipt["reason_code"] = Value::Null;
    inner
        .receipts
        .insert(command.idempotency_key, (payload.clone(), receipt.clone()));
    drop(inner);
    let event = state.timeline_item(
        "ack",
        conversation.id.clone(),
        None,
        None,
        None,
        json!({"run_id":control.execution_id, "parent_run_id":control.parent_run_id,
            "subagent_id":control.subagent_id, "action":command.action,
            "control_kind":"subagent", "accepted":true,
            "idempotency_key":payload["idempotency_key"],
            "instruction_bytes":payload["instruction"].as_str().map(str::len).unwrap_or(0)}),
    );
    state.append_timeline(&conversation.id, event);
    receipt
}

fn currently_authorized(
    state: &LocalRuntimeState,
    conversation: &LocalConversation,
    subagent_id: &str,
    parent_agent_id: &str,
) -> bool {
    let Ok(selection) = state.session_store.execution_selection(&conversation.id) else {
        return false;
    };
    let selection = selection.unwrap_or_default();
    if selection
        .subagent_id
        .as_deref()
        .is_some_and(|attached| attached != subagent_id)
    {
        return false;
    }
    let agent_id = selection
        .agent_id
        .as_deref()
        .unwrap_or("builtin:all-access");
    if agent_id != parent_agent_id {
        return false;
    }
    let Ok(Some(agent)) = state.session_store.managed_resource(
        ManagedResourceKind::Agent,
        "project",
        &conversation.project_id,
        agent_id,
    ) else {
        return false;
    };
    let Ok(resources) = state.session_store.list_managed_resources(
        ManagedResourceKind::SubAgent,
        "tenant",
        &conversation.tenant_id,
    ) else {
        return false;
    };
    subagent_agent_tool_host::authorized_subagent_resources(
        &agent,
        &resources,
        &conversation.project_id,
    )
    .is_ok_and(|resources| {
        resources
            .iter()
            .any(|resource| resource["id"].as_str() == Some(subagent_id))
    })
}
