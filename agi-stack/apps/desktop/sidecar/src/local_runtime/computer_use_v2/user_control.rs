//! Explicit user control is distinct from revoked authority and native failures.
use super::*;
use agistack_core::ports::ToolControlOutcome;
use rusqlite::{params, Connection};

#[derive(Default)]
pub(super) struct Control {
    inner: Mutex<ControlState>,
}
#[derive(Default)]
struct ControlState {
    current: Option<String>,
    states: BTreeMap<String, &'static str>,
    stopped: bool,
    pause_revision: u64,
}
impl Control {
    pub(super) fn pause(&self) -> String {
        let mut state = self.inner.lock().expect("user control");
        state.pause_revision = state.pause_revision.wrapping_add(1);
        if let Some(generation) = state
            .current
            .as_ref()
            .filter(|generation| state.states.get(*generation) == Some(&"paused"))
        {
            return generation.clone();
        }
        let generation = Uuid::new_v4().to_string();
        state.states.insert(generation.clone(), "paused");
        state.current = Some(generation.clone());
        generation
    }
    pub(super) fn pause_revision(&self) -> u64 {
        self.inner.lock().expect("user control").pause_revision
    }
    pub(super) fn resume_if_current(&self, revision: u64, paused: &AtomicBool) -> bool {
        let mut state = self.inner.lock().expect("user control");
        if state.stopped || state.pause_revision != revision {
            return false;
        }
        if let Some(generation) = state.current.clone() {
            state.states.insert(generation, "resumed");
        }
        paused.store(false, Ordering::SeqCst);
        true
    }
    #[cfg(test)]
    pub(super) fn resume(&self) {
        self.resume_if_current(self.pause_revision(), &AtomicBool::new(true));
    }
    pub(super) fn stop(&self) {
        let mut state = self.inner.lock().expect("user control");
        state.stopped = true;
        if let Some(generation) = state.current.clone() {
            state.states.insert(generation, "stopped");
        }
    }
    pub(super) fn outcome(&self, paused: bool) -> Option<ToolResult> {
        let mut state = self.inner.lock().expect("user control");
        if state.stopped {
            return Some(ToolControlOutcome::UserStopped.result(None));
        }
        if !paused {
            return None;
        }
        // Snapshot intent and generation under one lock: Stop cannot leave a
        // newly-created pause generation without a terminal receipt.
        let generation = state
            .current
            .clone()
            .unwrap_or_else(|| Uuid::new_v4().to_string());
        state.states.entry(generation.clone()).or_insert("paused");
        state.current = Some(generation.clone());
        Some(ToolControlOutcome::UserPaused.result(Some(generation)))
    }
    pub(super) fn completed(&self, generation: &str) -> Option<&'static str> {
        self.inner
            .lock()
            .expect("user control")
            .states
            .get(generation)
            .copied()
            .filter(|state| *state != "paused")
    }
}

pub(super) struct Receipt {
    pub engine_session_id: String,
    pub generation: String,
    pub control: Arc<Control>,
}
pub(super) fn initialize(db: &Connection) -> Result<(), String> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS desktop_cua_user_stops_v2(user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,device_id TEXT NOT NULL,run_id TEXT NOT NULL,PRIMARY KEY(user_id,tenant_id,project_id,device_id,run_id));").map_err(|error|error.to_string())
}
pub(super) fn persist_stop(db: &Connection, owner: &Owner, run: &str) -> Result<(), String> {
    db.execute(
        "INSERT OR IGNORE INTO desktop_cua_user_stops_v2 VALUES(?1,?2,?3,?4,?5)",
        params![
            owner.user_id,
            owner.tenant_id,
            owner.project_id,
            owner.device_id,
            run
        ],
    )
    .map(|_| ())
    .map_err(|error| error.to_string())
}
pub(super) fn stopped(state: &LocalRuntimeState, owner: &Owner, run: &str) -> CoreResult<bool> {
    if state
        .computer_use
        .stopped_cloud_runs
        .lock()
        .expect("stopped runs")
        .contains(&(owner.clone(), run.into()))
    {
        return Ok(true);
    }
    state.session_store.connection().map_err(CoreError::Storage)?.query_row("SELECT EXISTS(SELECT 1 FROM desktop_cua_user_stops_v2 WHERE user_id=?1 AND tenant_id=?2 AND project_id=?3 AND device_id=?4 AND run_id=?5)",params![owner.user_id,owner.tenant_id,owner.project_id,owner.device_id,run],|row|row.get(0)).map_err(|error|CoreError::Storage(error.to_string()))
}

pub(super) struct StoppedHost;
#[async_trait::async_trait]
impl ToolHost for StoppedHost {
    fn list_tools(&self) -> Vec<String> {
        denials::DeniedHost.list_tools()
    }
    fn tool_definition(&self, tool: &str) -> Option<ToolDefinition> {
        denials::DeniedHost.tool_definition(tool)
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<String> {
        Ok(self.call_with_content(tool, input).await?.output_json)
    }
    async fn call_with_content(&self, _: &str, _: &str) -> CoreResult<ToolResult> {
        Ok(ToolControlOutcome::UserStopped.result(None))
    }
}
