use std::collections::{HashSet, VecDeque};
use std::process::Command;
use std::sync::Mutex;

use agistack_core::ports::CoreError;
use chrono::{Duration, TimeZone};
use serde_json::json;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

use super::*;

mod pipeline_run_basic;
mod pipeline_run_drone;
mod pipeline_run_recovery;
mod pipeline_run_source_publish;
mod supervisor_accepted;
mod supervisor_dirty;
mod supervisor_disposition;
mod supervisor_pipeline;
mod supervisor_replan;
mod supervisor_reports;
mod supervisor_retry;
mod supervisor_worktree;

#[derive(Default)]
struct FakeWorkspacePlanOutboxStore {
    items: Mutex<HashMap<String, WorkspacePlanOutboxRecord>>,
}

impl FakeWorkspacePlanOutboxStore {
    fn insert(&self, item: WorkspacePlanOutboxRecord) {
        self.items.lock().unwrap().insert(item.id.clone(), item);
    }

    fn get(&self, id: &str) -> WorkspacePlanOutboxRecord {
        self.items.lock().unwrap().get(id).unwrap().clone()
    }
}

#[async_trait]
impl WorkspacePlanOutboxStore for FakeWorkspacePlanOutboxStore {
    async fn claim_due(
        &self,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
        let mut items = self.items.lock().unwrap();
        let mut due = items
            .values()
            .filter(|item| {
                let pending_due = matches!(item.status.as_str(), "pending" | "failed")
                    || (item.event_type == WORKSPACE_AGENT_MENTION_EVENT
                        && matches!(
                            item.status.as_str(),
                            "pending_runtime"
                                | WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS
                                | WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS
                        ));
                item.attempt_count < item.max_attempts
                    && ((pending_due && item.next_attempt_at.map(|due| due <= now).unwrap_or(true))
                        || (item.status == "processing"
                            && item
                                .lease_expires_at
                                .map(|expires_at| expires_at <= now)
                                .unwrap_or(false)))
            })
            .map(|item| item.id.clone())
            .collect::<Vec<_>>();
        due.sort();
        due.truncate(limit.max(0) as usize);

        let mut claimed = Vec::new();
        for id in due {
            let item = items.get_mut(&id).unwrap();
            item.status = "processing".to_string();
            item.attempt_count += 1;
            item.lease_owner = Some(lease_owner.to_string());
            item.lease_expires_at = Some(now + Duration::seconds(lease_seconds.max(1)));
            item.next_attempt_at = None;
            item.last_error = None;
            item.updated_at = Some(now);
            claimed.push(item.clone());
        }
        Ok(claimed)
    }

    async fn mark_completed(
        &self,
        outbox_id: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = "completed".to_string();
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = None;
        item.next_attempt_at = None;
        item.processed_at = Some(now);
        item.updated_at = Some(now);
        Ok(true)
    }

    async fn mark_failed(
        &self,
        outbox_id: &str,
        error_message: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = if item.attempt_count >= item.max_attempts {
            "dead_letter".to_string()
        } else {
            "failed".to_string()
        };
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = Some(error_message.to_string());
        item.next_attempt_at = Some(now + Duration::seconds(2));
        item.updated_at = Some(now);
        Ok(true)
    }

    async fn release_processing(
        &self,
        outbox_id: &str,
        error_message: Option<&str>,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = "pending".to_string();
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = error_message.map(str::to_string);
        item.next_attempt_at = None;
        item.attempt_count = (item.attempt_count - 1).max(0);
        item.updated_at = Some(now);
        Ok(true)
    }

    async fn park_processing(
        &self,
        outbox_id: &str,
        status: &str,
        metadata_patch: &Value,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = status.to_string();
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = None;
        item.next_attempt_at = None;
        let mut metadata = object_or_empty(item.metadata_json.clone());
        for (key, value) in object_or_empty(metadata_patch.clone()) {
            metadata.insert(key, value);
        }
        item.metadata_json = Value::Object(metadata);
        item.updated_at = Some(now);
        Ok(true)
    }

    async fn park_processing_with_payload_patch(
        &self,
        outbox_id: &str,
        status: &str,
        metadata_patch: &Value,
        payload_patch: &Value,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = status.to_string();
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = None;
        item.next_attempt_at = None;
        let mut metadata = object_or_empty(item.metadata_json.clone());
        for (key, value) in object_or_empty(metadata_patch.clone()) {
            metadata.insert(key, value);
        }
        item.metadata_json = Value::Object(metadata);
        let mut payload = object_or_empty(item.payload_json.clone());
        for (key, value) in object_or_empty(payload_patch.clone()) {
            payload.insert(key, value);
        }
        item.payload_json = Value::Object(payload);
        item.updated_at = Some(now);
        Ok(true)
    }
}

#[derive(Clone)]
enum HandlerBehavior {
    Complete,
    Release,
    Fail,
}

struct StaticHandler {
    behavior: HandlerBehavior,
}

#[async_trait]
impl WorkspacePlanOutboxHandler for StaticHandler {
    async fn handle(
        &self,
        _item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        match self.behavior {
            HandlerBehavior::Complete => Ok(WorkspacePlanOutboxHandlerOutcome::Complete),
            HandlerBehavior::Release => Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("shutdown".to_string()),
            }),
            HandlerBehavior::Fail => Err(CoreError::Storage("handler boom".to_string())),
        }
    }
}

struct FakeWorkspaceAgentMentionRuntime {
    result: Result<String, String>,
    prompts: Mutex<Vec<String>>,
}

impl FakeWorkspaceAgentMentionRuntime {
    fn ok(answer: &str) -> Self {
        Self {
            result: Ok(answer.to_string()),
            prompts: Mutex::new(Vec::new()),
        }
    }

    fn err(message: &str) -> Self {
        Self {
            result: Err(message.to_string()),
            prompts: Mutex::new(Vec::new()),
        }
    }

    fn prompts(&self) -> Vec<String> {
        self.prompts.lock().unwrap().clone()
    }
}

#[async_trait]
impl WorkspaceAgentMentionRuntime for FakeWorkspaceAgentMentionRuntime {
    async fn complete(&self, input: WorkspaceAgentMentionRuntimeInput) -> CoreResult<String> {
        self.prompts.lock().unwrap().push(input.user_prompt);
        self.result
            .clone()
            .map_err(|message| CoreError::Llm(message.to_string()))
    }
}

#[derive(Default)]
struct StaticPipelineStageRunner {
    results: Mutex<HashMap<String, PipelineStageResult>>,
    seen: Mutex<Vec<(String, String, String)>>,
}

impl StaticPipelineStageRunner {
    fn with_result(self, result: PipelineStageResult) -> Self {
        self.results
            .lock()
            .unwrap()
            .insert(result.stage.clone(), result);
        self
    }

    fn seen(&self) -> Vec<(String, String, String)> {
        self.seen.lock().unwrap().clone()
    }
}

#[async_trait]
impl WorkspacePipelineStageRunner for StaticPipelineStageRunner {
    async fn run_stage(
        &self,
        project_id: &str,
        _contract: &PipelineContractFoundation,
        stage: &PipelineStageSpec,
    ) -> PipelineStageResult {
        self.seen.lock().unwrap().push((
            project_id.to_string(),
            stage.stage.clone(),
            stage.command.clone(),
        ));
        self.results
            .lock()
            .unwrap()
            .get(&stage.stage)
            .cloned()
            .unwrap_or_else(|| PipelineStageResult {
                stage: stage.stage.clone(),
                status: "success".to_string(),
                command: stage.command.clone(),
                exit_code: Some(0),
                stdout_preview: "ok".to_string(),
                stderr_preview: String::new(),
                duration_ms: 25,
                log_ref: Some(format!("sandbox://pipeline/test/{}.log", stage.stage)),
                artifact_refs: vec![format!(
                    "pipeline_log:{}:sandbox://pipeline/test/{}.log",
                    stage.stage, stage.stage
                )],
                service_id: stage.service_id.clone(),
                required: stage.required,
            })
    }
}

#[derive(Default)]
struct FakeWorkerLaunchRuntimeStateStore {
    cooldowns: Mutex<HashSet<String>>,
    running: Mutex<HashSet<String>>,
    finished: Mutex<HashMap<String, String>>,
    claims: Mutex<Vec<String>>,
    clears: Mutex<Vec<String>>,
    refresh_cooldowns: Mutex<Vec<String>>,
    refresh_running: Mutex<Vec<String>>,
}

impl FakeWorkerLaunchRuntimeStateStore {
    fn insert_cooldown(&self, conversation_id: &str) {
        self.cooldowns
            .lock()
            .unwrap()
            .insert(conversation_id.to_string());
    }

    fn insert_running(&self, conversation_id: &str) {
        self.running
            .lock()
            .unwrap()
            .insert(conversation_id.to_string());
    }

    fn insert_finished(&self, conversation_id: &str) {
        self.finished
            .lock()
            .unwrap()
            .insert(conversation_id.to_string(), "msg-1".to_string());
    }

    fn has_cooldown(&self, conversation_id: &str) -> bool {
        self.cooldowns.lock().unwrap().contains(conversation_id)
    }

    fn has_finished(&self, conversation_id: &str) -> bool {
        self.finished.lock().unwrap().contains_key(conversation_id)
    }

    fn claims(&self) -> Vec<String> {
        self.claims.lock().unwrap().clone()
    }

    fn clears(&self) -> Vec<String> {
        self.clears.lock().unwrap().clone()
    }

    fn refresh_cooldowns(&self) -> Vec<String> {
        self.refresh_cooldowns.lock().unwrap().clone()
    }

    fn refresh_running(&self) -> Vec<String> {
        self.refresh_running.lock().unwrap().clone()
    }
}

#[async_trait]
impl WorkerLaunchRuntimeStateStore for FakeWorkerLaunchRuntimeStateStore {
    async fn claim_launch_cooldown(
        &self,
        conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.claims
            .lock()
            .unwrap()
            .push(conversation_id.to_string());
        let mut cooldowns = self.cooldowns.lock().unwrap();
        if cooldowns.contains(conversation_id) {
            return Ok(false);
        }
        cooldowns.insert(conversation_id.to_string());
        Ok(true)
    }

    async fn refresh_launch_cooldown(
        &self,
        conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.refresh_cooldowns
            .lock()
            .unwrap()
            .push(conversation_id.to_string());
        Ok(self.cooldowns.lock().unwrap().contains(conversation_id))
    }

    async fn agent_finished_message_id(&self, conversation_id: &str) -> CoreResult<Option<String>> {
        Ok(self.finished.lock().unwrap().get(conversation_id).cloned())
    }

    async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool> {
        Ok(self.running.lock().unwrap().contains(conversation_id))
    }

    async fn refresh_agent_running_marker(
        &self,
        conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        if self.finished.lock().unwrap().contains_key(conversation_id) {
            return Ok(false);
        }
        self.refresh_running
            .lock()
            .unwrap()
            .push(conversation_id.to_string());
        Ok(self.running.lock().unwrap().contains(conversation_id))
    }

    async fn clear_reused_session_markers(&self, conversation_id: &str) -> CoreResult<()> {
        self.clears
            .lock()
            .unwrap()
            .push(conversation_id.to_string());
        self.finished.lock().unwrap().remove(conversation_id);
        self.cooldowns.lock().unwrap().remove(conversation_id);
        Ok(())
    }
}

#[derive(Default)]
struct FakeWorkerLaunchEventStream {
    entries: Mutex<HashMap<String, Vec<StreamEntry>>>,
}

impl FakeWorkerLaunchEventStream {
    fn push(&self, conversation_id: &str, id: &str, payload: Value) {
        self.entries
            .lock()
            .unwrap()
            .entry(conversation_id.to_string())
            .or_default()
            .push(StreamEntry {
                id: id.to_string(),
                payload: payload.to_string(),
            });
    }
}

#[async_trait]
impl WorkerLaunchEventStream for FakeWorkerLaunchEventStream {
    async fn read_after(
        &self,
        conversation_id: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        let entries = self.entries.lock().unwrap();
        let mut seen_after = after_id.is_empty() || after_id == "0";
        let mut out = Vec::new();
        for entry in entries.get(conversation_id).into_iter().flatten() {
            if !seen_after {
                seen_after = entry.id == after_id;
                continue;
            }
            out.push(entry.clone());
            if out.len() >= limit {
                break;
            }
        }
        Ok(out)
    }
}

#[derive(Debug, Clone, PartialEq)]
struct FakePipelineContractRecord {
    id: String,
    workspace_id: String,
    plan_id: String,
    provider: String,
    code_root: Option<String>,
    commands_json: Value,
    env_json: Value,
    trigger_policy_json: Value,
    timeout_seconds: i32,
    auto_deploy: bool,
    preview_port: Option<i32>,
    health_url: Option<String>,
    metadata_json: Value,
    created_at: DateTime<Utc>,
    updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
struct FakeWorkerConversationRecord {
    id: String,
    project_id: String,
    tenant_id: String,
    user_id: String,
    title: String,
    agent_config_json: Value,
    metadata_json: Value,
    participant_agents_json: Vec<String>,
    focused_agent_id: String,
    workspace_id: String,
    linked_workspace_task_id: Option<String>,
    updated_at: DateTime<Utc>,
}

#[derive(Default)]
struct FakeWorkspacePlanDispatchStore {
    workspaces: Mutex<HashMap<String, WorkspaceRecord>>,
    members: Mutex<HashMap<String, HashSet<String>>>,
    agents: Mutex<HashMap<String, Vec<WorkspaceAgentRecord>>>,
    tasks: Mutex<HashMap<String, WorkspaceTaskRecord>>,
    plans: Mutex<HashMap<String, WorkspacePlanRecord>>,
    nodes: Mutex<HashMap<String, WorkspacePlanNodeRecord>>,
    attempts: Mutex<HashMap<String, WorkspaceTaskSessionAttemptRecord>>,
    conversations: Mutex<HashMap<String, FakeWorkerConversationRecord>>,
    messages: Mutex<HashMap<String, WorkspaceMessageRecord>>,
    blackboard_outbox: Mutex<Vec<BlackboardOutboxRecord>>,
    pipeline_contracts: Mutex<HashMap<(String, String), FakePipelineContractRecord>>,
    pipeline_runs: Mutex<HashMap<String, WorkspacePipelineRunRecord>>,
    pipeline_stage_runs: Mutex<HashMap<String, WorkspacePipelineStageRunRecord>>,
    plan_events: Mutex<Vec<WorkspacePlanEventRecord>>,
    outbox: Mutex<Vec<WorkspacePlanOutboxRecord>>,
    active_worker_conversations: Mutex<i64>,
    supervisor_dispose_nodes: Mutex<HashSet<(String, String, String)>>,
}

impl FakeWorkspacePlanDispatchStore {
    fn insert_workspace(&self, workspace: WorkspaceRecord) {
        self.workspaces
            .lock()
            .unwrap()
            .insert(workspace.id.clone(), workspace);
    }

    fn insert_member(&self, workspace_id: &str, user_id: &str) {
        self.members
            .lock()
            .unwrap()
            .entry(workspace_id.to_string())
            .or_default()
            .insert(user_id.to_string());
    }

    fn insert_agent(&self, workspace_id: &str, agent_id: &str, display_name: Option<&str>) {
        self.agents
            .lock()
            .unwrap()
            .entry(workspace_id.to_string())
            .or_default()
            .push(WorkspaceAgentRecord {
                id: format!("workspace-agent-{agent_id}"),
                workspace_id: workspace_id.to_string(),
                agent_id: agent_id.to_string(),
                display_name: display_name.map(ToOwned::to_owned),
            });
    }

    fn insert_task(&self, task: WorkspaceTaskRecord) {
        self.tasks.lock().unwrap().insert(task.id.clone(), task);
    }

    fn insert_plan(&self, plan: WorkspacePlanRecord) {
        self.plans.lock().unwrap().insert(plan.id.clone(), plan);
    }

    fn insert_node(&self, node: WorkspacePlanNodeRecord) {
        self.nodes.lock().unwrap().insert(node.id.clone(), node);
    }

    fn insert_attempt(&self, attempt: WorkspaceTaskSessionAttemptRecord) {
        self.attempts
            .lock()
            .unwrap()
            .insert(attempt.id.clone(), attempt);
    }

    fn insert_supervisor_dispose_decision(&self, workspace_id: &str, plan_id: &str, node_id: &str) {
        self.supervisor_dispose_nodes.lock().unwrap().insert((
            workspace_id.to_string(),
            plan_id.to_string(),
            node_id.to_string(),
        ));
    }

    fn insert_pipeline_run(&self, run: WorkspacePipelineRunRecord) {
        self.pipeline_runs
            .lock()
            .unwrap()
            .insert(run.id.clone(), run);
    }

    fn set_active_worker_conversations(&self, count: i64) {
        *self.active_worker_conversations.lock().unwrap() = count;
    }

    fn task(&self, id: &str) -> WorkspaceTaskRecord {
        self.tasks.lock().unwrap().get(id).unwrap().clone()
    }

    fn node(&self, id: &str) -> WorkspacePlanNodeRecord {
        self.nodes.lock().unwrap().get(id).unwrap().clone()
    }

    fn pipeline_run(&self, id: &str) -> WorkspacePipelineRunRecord {
        self.pipeline_runs.lock().unwrap().get(id).unwrap().clone()
    }

    fn pipeline_runs(&self) -> Vec<WorkspacePipelineRunRecord> {
        self.pipeline_runs
            .lock()
            .unwrap()
            .values()
            .cloned()
            .collect()
    }

    fn pipeline_stage_run(&self, id: &str) -> WorkspacePipelineStageRunRecord {
        self.pipeline_stage_runs
            .lock()
            .unwrap()
            .get(id)
            .unwrap()
            .clone()
    }

    fn pipeline_stage_runs(&self) -> Vec<WorkspacePipelineStageRunRecord> {
        self.pipeline_stage_runs
            .lock()
            .unwrap()
            .values()
            .cloned()
            .collect()
    }

    fn pipeline_contract(&self, workspace_id: &str, plan_id: &str) -> FakePipelineContractRecord {
        self.pipeline_contracts
            .lock()
            .unwrap()
            .get(&(workspace_id.to_string(), plan_id.to_string()))
            .unwrap()
            .clone()
    }

    fn attempts(&self) -> Vec<WorkspaceTaskSessionAttemptRecord> {
        self.attempts.lock().unwrap().values().cloned().collect()
    }

    fn attempt(&self, id: &str) -> WorkspaceTaskSessionAttemptRecord {
        self.attempts.lock().unwrap().get(id).unwrap().clone()
    }

    fn conversation(&self, id: &str) -> FakeWorkerConversationRecord {
        self.conversations
            .lock()
            .unwrap()
            .get(id)
            .cloned()
            .unwrap_or_else(|| panic!("conversation {id} not found"))
    }

    fn conversation_count(&self) -> usize {
        self.conversations.lock().unwrap().len()
    }

    fn messages(&self) -> Vec<WorkspaceMessageRecord> {
        self.messages.lock().unwrap().values().cloned().collect()
    }

    fn blackboard_outbox(&self) -> Vec<BlackboardOutboxRecord> {
        self.blackboard_outbox.lock().unwrap().clone()
    }

    fn plan_events(&self) -> Vec<WorkspacePlanEventRecord> {
        self.plan_events.lock().unwrap().clone()
    }

    fn outbox(&self) -> Vec<WorkspacePlanOutboxRecord> {
        self.outbox.lock().unwrap().clone()
    }
}

#[async_trait]
impl WorkspacePlanDispatchStore for FakeWorkspacePlanDispatchStore {
    async fn get_workspace(&self, workspace_id: &str) -> CoreResult<Option<WorkspaceRecord>> {
        Ok(self.workspaces.lock().unwrap().get(workspace_id).cloned())
    }

    async fn get_task(
        &self,
        workspace_id: &str,
        task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskRecord>> {
        Ok(self
            .tasks
            .lock()
            .unwrap()
            .get(task_id)
            .filter(|task| task.workspace_id == workspace_id)
            .cloned())
    }

    async fn list_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        let mut tasks = self
            .tasks
            .lock()
            .unwrap()
            .values()
            .filter(|task| {
                task.workspace_id == workspace_id
                    && task.archived_at.is_none()
                    && string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID).as_deref()
                        == Some(root_goal_task_id)
            })
            .cloned()
            .collect::<Vec<_>>();
        tasks.sort_by(|left, right| {
            left.created_at
                .cmp(&right.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(tasks)
    }

    async fn list_current_plan_child_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        let nodes = self.nodes.lock().unwrap().clone();
        let mut tasks = self
            .tasks
            .lock()
            .unwrap()
            .values()
            .filter(|task| {
                if task.workspace_id != workspace_id || task.archived_at.is_some() {
                    return false;
                }
                if string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID).as_deref()
                    != Some(root_goal_task_id)
                {
                    return false;
                }
                let Some(plan_id) =
                    string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_ID)
                else {
                    return false;
                };
                let Some(node_id) =
                    string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_NODE_ID)
                else {
                    return false;
                };
                nodes.get(&node_id).is_some_and(|node| {
                    node.plan_id == plan_id
                        && node.workspace_task_id.as_deref() == Some(task.id.as_str())
                })
            })
            .cloned()
            .collect::<Vec<_>>();
        tasks.sort_by(|left, right| {
            left.created_at
                .cmp(&right.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(tasks)
    }

    async fn save_task(&self, task: WorkspaceTaskRecord) -> CoreResult<WorkspaceTaskRecord> {
        self.tasks
            .lock()
            .unwrap()
            .insert(task.id.clone(), task.clone());
        Ok(task)
    }

    async fn get_plan(&self, plan_id: &str) -> CoreResult<Option<WorkspacePlanRecord>> {
        Ok(self.plans.lock().unwrap().get(plan_id).cloned())
    }

    async fn list_plan_nodes(&self, plan_id: &str) -> CoreResult<Vec<WorkspacePlanNodeRecord>> {
        Ok(self
            .nodes
            .lock()
            .unwrap()
            .values()
            .filter(|node| node.plan_id == plan_id)
            .cloned()
            .collect())
    }

    async fn create_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord> {
        self.nodes
            .lock()
            .unwrap()
            .insert(node.id.clone(), node.clone());
        Ok(node)
    }

    async fn save_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord> {
        self.nodes
            .lock()
            .unwrap()
            .insert(node.id.clone(), node.clone());
        Ok(node)
    }

    async fn find_active_task_session_attempt(
        &self,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self
            .attempts
            .lock()
            .unwrap()
            .values()
            .filter(|attempt| {
                attempt.workspace_task_id == workspace_task_id
                    && matches!(
                        attempt.status.as_str(),
                        "pending" | "running" | "awaiting_leader_adjudication"
                    )
            })
            .cloned()
            .collect::<Vec<_>>();
        attempts.sort_by(|left, right| {
            right
                .attempt_number
                .cmp(&left.attempt_number)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(attempts.into_iter().next())
    }

    async fn find_latest_accepted_task_session_attempt(
        &self,
        workspace_id: &str,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self
            .attempts
            .lock()
            .unwrap()
            .values()
            .filter(|attempt| {
                attempt.workspace_id == workspace_id
                    && attempt.workspace_task_id == workspace_task_id
                    && attempt.status == ACCEPTED_ATTEMPT_STATUS
            })
            .cloned()
            .collect::<Vec<_>>();
        attempts.sort_by(|left, right| {
            right
                .attempt_number
                .cmp(&left.attempt_number)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(attempts.into_iter().next())
    }

    async fn get_task_session_attempt(
        &self,
        attempt_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        Ok(self.attempts.lock().unwrap().get(attempt_id).cloned())
    }

    async fn latest_pipeline_run_for_node(
        &self,
        plan_id: &str,
        node_id: &str,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        let mut runs = self
            .pipeline_runs
            .lock()
            .unwrap()
            .values()
            .filter(|run| {
                run.plan_id.as_deref() == Some(plan_id)
                    && run.node_id.as_deref() == Some(node_id)
                    && attempt_id
                        .is_none_or(|attempt_id| run.attempt_id.as_deref() == Some(attempt_id))
            })
            .cloned()
            .collect::<Vec<_>>();
        runs.sort_by(|left, right| {
            right
                .created_at
                .cmp(&left.created_at)
                .then_with(|| right.id.cmp(&left.id))
        });
        Ok(runs.into_iter().next())
    }

    async fn ensure_pipeline_contract(
        &self,
        contract_id: &str,
        workspace_id: &str,
        plan_id: &str,
        provider: &str,
        code_root: Option<&str>,
        commands_json: &Value,
        env_json: &Value,
        trigger_policy_json: &Value,
        timeout_seconds: i32,
        auto_deploy: bool,
        preview_port: Option<i32>,
        health_url: Option<&str>,
        metadata_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<String> {
        let mut contracts = self.pipeline_contracts.lock().unwrap();
        let key = (workspace_id.to_string(), plan_id.to_string());
        if let Some(existing) = contracts.get_mut(&key) {
            existing.provider = provider.to_string();
            existing.code_root = code_root.map(ToOwned::to_owned);
            existing.commands_json = commands_json.clone();
            existing.env_json = env_json.clone();
            existing.trigger_policy_json = trigger_policy_json.clone();
            existing.timeout_seconds = timeout_seconds.max(1);
            existing.auto_deploy = auto_deploy;
            existing.preview_port = preview_port;
            existing.health_url = health_url.map(ToOwned::to_owned);
            existing.metadata_json = metadata_json.clone();
            existing.updated_at = Some(now);
            return Ok(existing.id.clone());
        }
        let record = FakePipelineContractRecord {
            id: contract_id.to_string(),
            workspace_id: workspace_id.to_string(),
            plan_id: plan_id.to_string(),
            provider: provider.to_string(),
            code_root: code_root.map(ToOwned::to_owned),
            commands_json: commands_json.clone(),
            env_json: env_json.clone(),
            trigger_policy_json: trigger_policy_json.clone(),
            timeout_seconds: timeout_seconds.max(1),
            auto_deploy,
            preview_port,
            health_url: health_url.map(ToOwned::to_owned),
            metadata_json: metadata_json.clone(),
            created_at: now,
            updated_at: None,
        };
        let id = record.id.clone();
        contracts.insert(key, record);
        Ok(id)
    }

    async fn create_pipeline_run(
        &self,
        run: WorkspacePipelineRunRecord,
    ) -> CoreResult<WorkspacePipelineRunRecord> {
        self.pipeline_runs
            .lock()
            .unwrap()
            .insert(run.id.clone(), run.clone());
        Ok(run)
    }

    async fn finish_pipeline_run(
        &self,
        run_id: &str,
        status: &str,
        reason: Option<&str>,
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        let mut runs = self.pipeline_runs.lock().unwrap();
        let Some(run) = runs.get_mut(run_id) else {
            return Ok(None);
        };
        run.status = status.to_string();
        run.reason = reason.map(ToOwned::to_owned);
        run.completed_at = Some(completed_at);
        run.updated_at = Some(completed_at);
        let mut metadata = object_or_empty(run.metadata_json.clone());
        for (key, value) in object_or_empty(metadata_patch.clone()) {
            metadata.insert(key, value);
        }
        run.metadata_json = Value::Object(metadata);
        Ok(Some(run.clone()))
    }

    async fn create_pipeline_stage_run(
        &self,
        stage_run: WorkspacePipelineStageRunRecord,
    ) -> CoreResult<WorkspacePipelineStageRunRecord> {
        self.pipeline_stage_runs
            .lock()
            .unwrap()
            .insert(stage_run.id.clone(), stage_run.clone());
        Ok(stage_run)
    }

    async fn finish_pipeline_stage_run(
        &self,
        stage_run_id: &str,
        status: &str,
        exit_code: Option<i32>,
        stdout_preview: Option<&str>,
        stderr_preview: Option<&str>,
        log_ref: Option<&str>,
        artifact_refs: &[String],
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineStageRunRecord>> {
        let mut stage_runs = self.pipeline_stage_runs.lock().unwrap();
        let Some(stage_run) = stage_runs.get_mut(stage_run_id) else {
            return Ok(None);
        };
        stage_run.status = status.to_string();
        stage_run.exit_code = exit_code;
        stage_run.stdout_preview = stdout_preview.map(ToOwned::to_owned);
        stage_run.stderr_preview = stderr_preview.map(ToOwned::to_owned);
        stage_run.log_ref = log_ref.map(ToOwned::to_owned);
        stage_run.artifact_refs_json = artifact_refs.to_vec();
        stage_run.completed_at = Some(completed_at);
        let duration_ms = stage_run
            .started_at
            .map(|started_at| (completed_at - started_at).num_milliseconds().max(0))
            .unwrap_or(0);
        stage_run.duration_ms = Some(i32::try_from(duration_ms).unwrap_or(i32::MAX));
        stage_run.updated_at = Some(completed_at);
        let mut metadata = object_or_empty(stage_run.metadata_json.clone());
        for (key, value) in object_or_empty(metadata_patch.clone()) {
            metadata.insert(key, value);
        }
        stage_run.metadata_json = Value::Object(metadata);
        Ok(Some(stage_run.clone()))
    }

    async fn latest_task_session_attempt_number(&self, workspace_task_id: &str) -> CoreResult<i32> {
        Ok(self
            .attempts
            .lock()
            .unwrap()
            .values()
            .filter(|attempt| attempt.workspace_task_id == workspace_task_id)
            .map(|attempt| attempt.attempt_number)
            .max()
            .unwrap_or(0))
    }

    async fn create_task_session_attempt(
        &self,
        attempt: WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<WorkspaceTaskSessionAttemptRecord> {
        self.attempts
            .lock()
            .unwrap()
            .insert(attempt.id.clone(), attempt.clone());
        Ok(attempt)
    }

    async fn mark_task_session_attempt_running(
        &self,
        attempt_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self.attempts.lock().unwrap();
        let Some(attempt) = attempts.get_mut(attempt_id) else {
            return Ok(None);
        };
        attempt.status = "running".to_string();
        attempt.updated_at = Some(now);
        Ok(Some(attempt.clone()))
    }

    async fn ensure_worker_launch_conversation(
        &self,
        conversation_id: &str,
        project_id: &str,
        tenant_id: &str,
        user_id: &str,
        title: &str,
        agent_config_json: &Value,
        metadata_json: &Value,
        participant_agents_json: &[String],
        focused_agent_id: &str,
        workspace_id: &str,
        linked_workspace_task_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let mut conversations = self.conversations.lock().unwrap();
        if let Some(existing) = conversations.get(conversation_id) {
            if existing.workspace_id != workspace_id
                || existing.linked_workspace_task_id.as_deref() != Some(linked_workspace_task_id)
            {
                return Err(CoreError::Storage(format!(
                        "worker launch conversation {conversation_id} is linked to another workspace task"
                    )));
            }
        }
        conversations.insert(
            conversation_id.to_string(),
            FakeWorkerConversationRecord {
                id: conversation_id.to_string(),
                project_id: project_id.to_string(),
                tenant_id: tenant_id.to_string(),
                user_id: user_id.to_string(),
                title: title.to_string(),
                agent_config_json: agent_config_json.clone(),
                metadata_json: metadata_json.clone(),
                participant_agents_json: participant_agents_json.to_vec(),
                focused_agent_id: focused_agent_id.to_string(),
                workspace_id: workspace_id.to_string(),
                linked_workspace_task_id: Some(linked_workspace_task_id.to_string()),
                updated_at: now,
            },
        );
        Ok(())
    }

    async fn ensure_workspace_agent_conversation(
        &self,
        conversation_id: &str,
        project_id: &str,
        tenant_id: &str,
        user_id: &str,
        title: &str,
        agent_config_json: &Value,
        metadata_json: &Value,
        workspace_id: &str,
        linked_workspace_task_id: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let mut conversations = self.conversations.lock().unwrap();
        if let Some(existing) = conversations.get_mut(conversation_id) {
            if existing.workspace_id != workspace_id {
                return Err(CoreError::Storage(format!(
                    "workspace agent conversation {conversation_id} is linked to another workspace"
                )));
            }
            existing.agent_config_json = agent_config_json.clone();
            existing.metadata_json = metadata_json.clone();
            if let Some(task_id) = linked_workspace_task_id {
                existing.linked_workspace_task_id = Some(task_id.to_string());
            }
            existing.updated_at = now;
            return Ok(());
        }
        conversations.insert(
            conversation_id.to_string(),
            FakeWorkerConversationRecord {
                id: conversation_id.to_string(),
                project_id: project_id.to_string(),
                tenant_id: tenant_id.to_string(),
                user_id: user_id.to_string(),
                title: title.to_string(),
                agent_config_json: agent_config_json.clone(),
                metadata_json: metadata_json.clone(),
                participant_agents_json: Vec::new(),
                focused_agent_id: String::new(),
                workspace_id: workspace_id.to_string(),
                linked_workspace_task_id: linked_workspace_task_id.map(ToOwned::to_owned),
                updated_at: now,
            },
        );
        Ok(())
    }

    async fn list_workspace_member_user_ids(&self, workspace_id: &str) -> CoreResult<Vec<String>> {
        let mut members = self
            .members
            .lock()
            .unwrap()
            .get(workspace_id)
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .collect::<Vec<_>>();
        members.sort();
        Ok(members)
    }

    async fn list_active_workspace_agents(
        &self,
        workspace_id: &str,
    ) -> CoreResult<Vec<WorkspaceAgentRecord>> {
        Ok(self
            .agents
            .lock()
            .unwrap()
            .get(workspace_id)
            .cloned()
            .unwrap_or_default())
    }

    async fn create_workspace_message(
        &self,
        message: WorkspaceMessageRecord,
    ) -> CoreResult<WorkspaceMessageRecord> {
        self.messages
            .lock()
            .unwrap()
            .insert(message.id.clone(), message.clone());
        Ok(message)
    }

    async fn enqueue_blackboard_outbox(&self, outbox: BlackboardOutboxRecord) -> CoreResult<()> {
        self.blackboard_outbox.lock().unwrap().push(outbox);
        Ok(())
    }

    async fn bind_task_session_attempt_conversation(
        &self,
        attempt_id: &str,
        conversation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self.attempts.lock().unwrap();
        let Some(attempt) = attempts.get_mut(attempt_id) else {
            return Ok(None);
        };
        attempt.status = "running".to_string();
        attempt.conversation_id = Some(conversation_id.to_string());
        attempt.updated_at = Some(now);
        Ok(Some(attempt.clone()))
    }

    async fn finish_task_session_attempt(
        &self,
        attempt_id: &str,
        status: &str,
        leader_feedback: Option<&str>,
        adjudication_reason: Option<&str>,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self.attempts.lock().unwrap();
        let Some(attempt) = attempts.get_mut(attempt_id) else {
            return Ok(None);
        };
        attempt.status = status.to_string();
        attempt.leader_feedback = leader_feedback.map(ToOwned::to_owned);
        attempt.adjudication_reason = adjudication_reason.map(ToOwned::to_owned);
        attempt.completed_at = Some(completed_at);
        attempt.updated_at = Some(completed_at);
        Ok(Some(attempt.clone()))
    }

    async fn record_task_session_attempt_candidate_output(
        &self,
        attempt_id: &str,
        summary: Option<&str>,
        artifacts_json: &[String],
        verifications_json: &[String],
        conversation_id: Option<&str>,
        updated_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self.attempts.lock().unwrap();
        let Some(attempt) = attempts.get_mut(attempt_id) else {
            return Ok(None);
        };
        if matches!(
            attempt.status.as_str(),
            "accepted" | "rejected" | "blocked" | "cancelled"
        ) {
            return Ok(Some(attempt.clone()));
        }
        attempt.status = AWAITING_LEADER_ADJUDICATION_STATUS.to_string();
        if let Some(conversation_id) = conversation_id {
            attempt.conversation_id = Some(conversation_id.to_string());
        }
        attempt.candidate_summary = summary.map(ToOwned::to_owned);
        attempt.candidate_artifacts_json = artifacts_json.to_vec();
        attempt.candidate_verifications_json = verifications_json.to_vec();
        attempt.updated_at = Some(updated_at);
        Ok(Some(attempt.clone()))
    }

    async fn count_recent_running_task_session_attempts_with_conversation(
        &self,
        _workspace_id: &str,
        _active_after: DateTime<Utc>,
    ) -> CoreResult<i64> {
        Ok(*self.active_worker_conversations.lock().unwrap())
    }

    async fn has_supervisor_dispose_decision_for_node(
        &self,
        workspace_id: &str,
        plan_id: &str,
        node_id: &str,
    ) -> CoreResult<bool> {
        Ok(self.supervisor_dispose_nodes.lock().unwrap().contains(&(
            workspace_id.to_string(),
            plan_id.to_string(),
            node_id.to_string(),
        )))
    }

    async fn create_plan_event(
        &self,
        event: WorkspacePlanEventRecord,
    ) -> CoreResult<WorkspacePlanEventRecord> {
        self.plan_events.lock().unwrap().push(event.clone());
        Ok(event)
    }

    async fn enqueue_plan_outbox(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxRecord> {
        self.outbox.lock().unwrap().push(item.clone());
        Ok(item)
    }
}

fn worker(
    store: Arc<FakeWorkspacePlanOutboxStore>,
    handlers: WorkspacePlanOutboxHandlers,
) -> WorkspacePlanOutboxWorker {
    WorkspacePlanOutboxWorker::new(
        store,
        WorkspacePlanOutboxWorkerConfig {
            worker_id: "worker-test".to_string(),
            batch_size: 10,
            lease_seconds: 60,
            poll_interval_millis: 5,
            autostart: false,
            production_ready: false,
        },
        handlers,
    )
}

fn handler(behavior: HandlerBehavior) -> Arc<dyn WorkspacePlanOutboxHandler> {
    Arc::new(StaticHandler { behavior })
}

fn outbox(id: &str, event_type: &str) -> WorkspacePlanOutboxRecord {
    WorkspacePlanOutboxRecord {
        id: id.to_string(),
        plan_id: Some("plan-test".to_string()),
        workspace_id: "workspace-test".to_string(),
        event_type: event_type.to_string(),
        payload_json: json!({"id": id}),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 3,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({}),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
    }
}

fn task_with_plan_metadata() -> WorkspaceTaskRecord {
    WorkspaceTaskRecord {
        id: "task-test".to_string(),
        workspace_id: "workspace-test".to_string(),
        title: "Build feature".to_string(),
        description: None,
        created_by: "actor-test".to_string(),
        assignee_user_id: None,
        assignee_agent_id: Some("agent-worker".to_string()),
        status: "todo".to_string(),
        priority: 1,
        estimated_effort: None,
        blocker_reason: None,
        metadata_json: json!({
            ROOT_GOAL_TASK_ID: "root-task",
            WORKSPACE_PLAN_ID: "plan-test",
            WORKSPACE_PLAN_NODE_ID: "node-test"
        }),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
        completed_at: None,
        archived_at: None,
    }
}

fn root_goal_task() -> WorkspaceTaskRecord {
    WorkspaceTaskRecord {
        id: "root-task".to_string(),
        workspace_id: "workspace-test".to_string(),
        title: "Finish root goal".to_string(),
        description: None,
        created_by: "actor-test".to_string(),
        assignee_user_id: None,
        assignee_agent_id: None,
        status: "todo".to_string(),
        priority: 1,
        estimated_effort: None,
        blocker_reason: None,
        metadata_json: json!({
            TASK_ROLE: GOAL_ROOT_TASK_ROLE,
            "goal_health": "healthy"
        }),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
        completed_at: None,
        archived_at: None,
    }
}

fn workspace_with_metadata(metadata_json: Value) -> WorkspaceRecord {
    WorkspaceRecord {
        id: "workspace-test".to_string(),
        tenant_id: "tenant-test".to_string(),
        project_id: "project-test".to_string(),
        name: "Workspace".to_string(),
        description: None,
        created_by: "actor-test".to_string(),
        is_archived: false,
        metadata_json,
        office_status: "active".to_string(),
        hex_layout_config_json: json!({}),
        default_blocking_categories_json: Vec::new(),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
    }
}

fn workspace_with_code_root(root: &str) -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "code_context": {
            "sandbox_code_root": root
        }
    }))
}

fn workspace_with_pipeline_contract() -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "delivery_cicd": {
            "provider": "sandbox_native",
            "code_root": "/workspace/project",
            "auto_deploy": false,
            "timeout_seconds": 120,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "contract_confidence": 0.82,
            "env": {"CI": "true"},
            "stages": [
                {
                    "stage": "test",
                    "command": "cargo test --workspace",
                    "required": true,
                    "timeout_seconds": 120
                }
            ]
        }
    }))
}

fn workspace_with_drone_pipeline_contract_missing_host_root() -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "source_control": {
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "drone": {
                "repo": "owner/repo",
                "branch": "main"
            }
        }
    }))
}

fn workspace_with_drone_pipeline_contract_missing_branch() -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "code_context": {
            "host_code_root": "/tmp/worktree",
            "sandbox_code_root": "/workspace/project"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "provider_config": {
                "drone": {
                    "repo": "owner/repo"
                }
            }
        }
    }))
}

fn workspace_with_drone_pipeline_contract_git_publish(
    host_code_root: &Path,
    remote_url: &Path,
) -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "code_context": {
            "host_code_root": host_code_root.to_string_lossy().to_string(),
            "sandbox_code_root": "/workspace/project"
        },
        "source_control": {
            "clone_url": remote_url.to_string_lossy().to_string(),
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "drone": {
                "repo": "owner/repo"
            }
        }
    }))
}

fn workspace_with_drone_api_pipeline_contract(
    server_url: &str,
    token_env: &str,
) -> WorkspaceRecord {
    workspace_with_drone_api_pipeline_contract_with_host_root(server_url, token_env, None)
}

fn workspace_with_drone_api_pipeline_contract_with_host_root(
    server_url: &str,
    token_env: &str,
    host_code_root: Option<&Path>,
) -> WorkspaceRecord {
    let mut metadata = json!({
        "source_control": {
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "drone": {
                "repo": "owner/repo",
                "branch": "main",
                "commit": "abc123",
                "server_url": server_url,
                "token_env": token_env,
                "poll_interval_seconds": 1,
                "timeout_seconds": 1,
                "params": {
                    "target": "workspace-ci"
                }
            }
        }
    });
    if let Some(host_code_root) = host_code_root {
        metadata
            .as_object_mut()
            .expect("workspace metadata object")
            .insert(
                "code_context".to_string(),
                json!({
                    "host_code_root": host_code_root.to_string_lossy().to_string(),
                    "sandbox_code_root": "/workspace/project"
                }),
            );
    }
    workspace_with_metadata(metadata)
}

fn workspace_with_drone_cli_pipeline_contract(
    server_url: &str,
    token_env: &str,
    command: &Path,
) -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "source_control": {
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "drone": {
                "repo": "owner/repo",
                "branch": "main",
                "commit": "abc123",
                "server_url": server_url,
                "token_env": token_env,
                "client": "cli",
                "command": command.to_string_lossy().to_string(),
                "poll_interval_seconds": 1,
                "timeout_seconds": 1,
                "params": {
                    "target": "workspace-ci"
                }
            }
        }
    }))
}

fn workspace_with_drone_docker_deploy_pipeline_contract(
    server_url: &str,
    token_env: &str,
) -> WorkspaceRecord {
    workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(server_url, token_env, None)
}

fn workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(
    server_url: &str,
    token_env: &str,
    host_code_root: Option<&Path>,
) -> WorkspaceRecord {
    let mut metadata = json!({
        "source_control": {
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "deploy": {
                "enabled": true,
                "mode": "docker",
                "stage": "deploy",
                "required": true,
                "target": "production",
                "docker": {
                    "trusted": true,
                    "host_port": 18080,
                    "labels": ["blue", "green"],
                    "deploy_services": [
                        {
                            "service_id": "web",
                            "container_name": "app-web",
                            "image": "registry.local/app-web:abc"
                        }
                    ]
                }
            },
            "drone": {
                "repo": "owner/repo",
                "branch": "main",
                "commit": "abc123",
                "server_url": server_url,
                "token_env": token_env,
                "poll_interval_seconds": 1,
                "timeout_seconds": 1
            }
        }
    });
    if let Some(host_code_root) = host_code_root {
        metadata
            .as_object_mut()
            .expect("workspace metadata object")
            .insert(
                "code_context".to_string(),
                json!({
                    "host_code_root": host_code_root.to_string_lossy().to_string(),
                    "sandbox_code_root": "/workspace/project"
                }),
            );
    }
    workspace_with_metadata(metadata)
}

async fn drone_api_mock(
    responses: Vec<(u16, &'static str)>,
) -> (String, Arc<tokio::sync::Mutex<Vec<String>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let captured = Arc::new(tokio::sync::Mutex::new(Vec::<String>::new()));
    let responses = Arc::new(tokio::sync::Mutex::new(VecDeque::from(responses)));
    let captured_sink = captured.clone();
    let response_queue = responses.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut socket, _)) = listener.accept().await else {
                break;
            };
            let mut request = Vec::new();
            loop {
                let mut buffer = vec![0u8; 8192];
                let read = socket.read(&mut buffer).await.unwrap_or(0);
                if read == 0 {
                    break;
                }
                request.extend_from_slice(&buffer[..read]);
                if http_request_complete(&request) {
                    break;
                }
            }
            captured_sink
                .lock()
                .await
                .push(String::from_utf8_lossy(&request).to_string());
            let (status, body) = response_queue
                .lock()
                .await
                .pop_front()
                .unwrap_or((500, r#"{"error":"unexpected request"}"#));
            let reason = if status < 400 { "OK" } else { "ERROR" };
            let response = format!(
                    "HTTP/1.1 {status} {reason}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
            let _ = socket.write_all(response.as_bytes()).await;
            let _ = socket.flush().await;
        }
    });
    (format!("http://{addr}"), captured)
}

fn http_request_complete(request: &[u8]) -> bool {
    let Some(header_end) = request.windows(4).position(|window| window == b"\r\n\r\n") else {
        return false;
    };
    let headers = String::from_utf8_lossy(&request[..header_end]).to_ascii_lowercase();
    let content_length = headers
        .lines()
        .find_map(|line| line.strip_prefix("content-length:"))
        .and_then(|value| value.trim().parse::<usize>().ok())
        .unwrap_or(0);
    request.len() >= header_end + 4 + content_length
}

struct GitPublishFixture {
    root: PathBuf,
    repo: PathBuf,
    remote: PathBuf,
    commit_ref: String,
}

impl Drop for GitPublishFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

struct DroneYamlFixture {
    root: PathBuf,
}

impl Drop for DroneYamlFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

struct DroneCliFixture {
    root: PathBuf,
    command: PathBuf,
    capture: PathBuf,
}

impl Drop for DroneCliFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn drone_yaml_fixture(content: &str) -> DroneYamlFixture {
    let root =
        std::env::temp_dir().join(format!("agistack-drone-yaml-test-{}", generate_uuid_v4()));
    std::fs::create_dir_all(&root).unwrap();
    std::fs::write(root.join(".drone.yml"), content).unwrap();
    DroneYamlFixture { root }
}

fn drone_cli_fixture() -> DroneCliFixture {
    let root = std::env::temp_dir().join(format!("agistack-drone-cli-test-{}", generate_uuid_v4()));
    std::fs::create_dir_all(&root).unwrap();
    let command = root.join("drone");
    let capture = root.join("commands.log");
    let capture_text = capture.to_string_lossy();
    std::fs::write(
            &command,
            format!(
                r#"#!/bin/sh
CAPTURE="{capture_text}"
printf 'server=%s token=%s args=%s\n' "$DRONE_SERVER" "$DRONE_TOKEN" "$*" >> "$CAPTURE"
case "$1 $2" in
  "repo info")
    printf '%s\n' '{{"active":true,"trusted":true}}'
    ;;
  "repo enable")
    printf '%s\n' enabled
    ;;
  "repo update")
    printf '%s\n' updated
    ;;
  "build ls")
    exit 0
    ;;
  "build create")
    printf '%s\n' '{{"number":51,"status":"running"}}'
    ;;
  "build info")
    printf '%s\n' '{{"number":51,"status":"success","link":"http://drone.local/owner/repo/51","stages":[{{"name":"ci","number":1,"steps":[{{"name":"test","number":1,"status":"success","exit_code":0}}]}}]}}'
    ;;
  "log view")
    printf '%s\n' 'cargo test ok'
    ;;
  "build stop")
    printf '%s\n' stopped
    ;;
  *)
    printf 'unexpected drone args: %s\n' "$*" >&2
    exit 64
    ;;
esac
"#
            ),
        )
        .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = std::fs::metadata(&command).unwrap().permissions();
        permissions.set_mode(0o700);
        std::fs::set_permissions(&command, permissions).unwrap();
    }
    DroneCliFixture {
        root,
        command,
        capture,
    }
}

fn git_publish_fixture() -> Option<GitPublishFixture> {
    if std::env::var_os("AGISTACK_RUN_GIT_PUBLISH_TESTS").is_none() {
        eprintln!(
                "[skip] set AGISTACK_RUN_GIT_PUBLISH_TESTS=1 to run subprocess-backed git publish tests"
            );
        return None;
    }
    if !git_available() {
        eprintln!("[skip] git binary is not available");
        return None;
    }
    let root = std::env::temp_dir().join(format!(
        "agistack-drone-publish-test-{}",
        generate_uuid_v4()
    ));
    let repo = root.join("repo");
    let remote = root.join("remote.git");
    std::fs::create_dir_all(&repo).unwrap();
    run_git_ok(&repo, &["init"]);
    run_git_ok(&repo, &["config", "user.email", "agent@example.test"]);
    run_git_ok(&repo, &["config", "user.name", "Agent Test"]);
    std::fs::write(repo.join("README.md"), "hello\n").unwrap();
    run_git_ok(&repo, &["add", "README.md"]);
    run_git_ok(&repo, &["commit", "-m", "initial"]);
    let commit_ref = run_git_ok(&repo, &["rev-parse", "HEAD"]).trim().to_string();
    run_git_ok(&root, &["init", "--bare", remote.to_str().unwrap()]);
    run_git_ok(
        &repo,
        &["remote", "add", "origin", remote.to_str().unwrap()],
    );
    Some(GitPublishFixture {
        root,
        repo,
        remote,
        commit_ref,
    })
}

fn git_available() -> bool {
    Command::new("git")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
}

fn run_git_ok(cwd: &Path, args: &[&str]) -> String {
    let output = Command::new("git")
        .args(args)
        .current_dir(cwd)
        .output()
        .unwrap_or_else(|err| panic!("git {} failed to start: {err}", args.join(" ")));
    assert!(
        output.status.success(),
        "git {} failed\nstdout:\n{}\nstderr:\n{}",
        args.join(" "),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn plan() -> WorkspacePlanRecord {
    WorkspacePlanRecord {
        id: "plan-test".to_string(),
        workspace_id: "workspace-test".to_string(),
        goal_id: "root-task".to_string(),
        status: "active".to_string(),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
    }
}

fn plan_node() -> WorkspacePlanNodeRecord {
    WorkspacePlanNodeRecord {
        id: "node-test".to_string(),
        plan_id: "plan-test".to_string(),
        parent_id: None,
        kind: "task".to_string(),
        title: "Build feature".to_string(),
        description: String::new(),
        depends_on_json: Vec::new(),
        inputs_schema_json: json!({}),
        outputs_schema_json: json!({}),
        acceptance_criteria_json: Vec::new(),
        feature_checkpoint_json: None,
        handoff_package_json: None,
        recommended_capabilities_json: Vec::new(),
        preferred_agent_id: None,
        estimated_effort_json: json!({}),
        priority: 1,
        intent: "blocked".to_string(),
        execution: "idle".to_string(),
        progress_json: json!({}),
        assignee_agent_id: Some("agent-worker".to_string()),
        current_attempt_id: None,
        workspace_task_id: Some("task-test".to_string()),
        metadata_json: json!({"terminal_attempt_retry_reason": "worker_crashed"}),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
        completed_at: None,
    }
}

fn task_session_attempt(
    id: &str,
    status: &str,
    conversation_id: Option<&str>,
) -> WorkspaceTaskSessionAttemptRecord {
    WorkspaceTaskSessionAttemptRecord {
        id: id.to_string(),
        workspace_task_id: "task-test".to_string(),
        root_goal_task_id: "root-task".to_string(),
        workspace_id: "workspace-test".to_string(),
        attempt_number: 1,
        status: status.to_string(),
        conversation_id: conversation_id.map(ToOwned::to_owned),
        worker_agent_id: Some("agent-worker".to_string()),
        leader_agent_id: None,
        candidate_summary: None,
        candidate_artifacts_json: Vec::new(),
        candidate_verifications_json: Vec::new(),
        leader_feedback: None,
        adjudication_reason: None,
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: Some(Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap()),
        completed_at: None,
    }
}

fn worker_launch_handler(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    max_active: i64,
) -> WorkerLaunchAdmissionHandler {
    WorkerLaunchAdmissionHandler::with_config(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        WorkerLaunchAdmissionConfig {
            max_active_worker_conversations: max_active,
            defer_seconds: 30,
            active_event_grace_seconds: 60,
            stream_poll_interval_seconds: 5,
        },
    )
}

fn worker_launch_handler_with_state(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    runtime_state: Arc<FakeWorkerLaunchRuntimeStateStore>,
    max_active: i64,
) -> WorkerLaunchAdmissionHandler {
    WorkerLaunchAdmissionHandler::with_config_and_runtime_state(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state as Arc<dyn WorkerLaunchRuntimeStateStore>,
        WorkerLaunchAdmissionConfig {
            max_active_worker_conversations: max_active,
            defer_seconds: 30,
            active_event_grace_seconds: 60,
            stream_poll_interval_seconds: 5,
        },
    )
}

fn worker_launch_handler_with_event_stream(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    stream_events: Arc<FakeWorkerLaunchEventStream>,
    max_active: i64,
) -> WorkerLaunchAdmissionHandler {
    WorkerLaunchAdmissionHandler::with_config_and_event_stream(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        stream_events as Arc<dyn WorkerLaunchEventStream>,
        WorkerLaunchAdmissionConfig {
            max_active_worker_conversations: max_active,
            defer_seconds: 30,
            active_event_grace_seconds: 60,
            stream_poll_interval_seconds: 5,
        },
    )
}

fn worker_launch_handler_with_state_and_event_stream(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    runtime_state: Arc<FakeWorkerLaunchRuntimeStateStore>,
    stream_events: Arc<FakeWorkerLaunchEventStream>,
    max_active: i64,
) -> WorkerLaunchAdmissionHandler {
    WorkerLaunchAdmissionHandler::with_config_and_runtime_state_and_event_stream(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state as Arc<dyn WorkerLaunchRuntimeStateStore>,
        stream_events as Arc<dyn WorkerLaunchEventStream>,
        WorkerLaunchAdmissionConfig {
            max_active_worker_conversations: max_active,
            defer_seconds: 30,
            active_event_grace_seconds: 60,
            stream_poll_interval_seconds: 5,
        },
    )
}

fn worker_launch_item() -> WorkspacePlanOutboxRecord {
    let mut item = outbox("job-worker-launch", WORKER_LAUNCH_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "task_id": "task-test",
        "node_id": "node-test",
        "worker_agent_id": "agent-worker",
        "actor_user_id": "actor-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
        "attempt_id": "attempt-test",
        "extra_instructions": "continue implementation"
    });
    item
}

fn pipeline_run_handler(store: Arc<FakeWorkspacePlanDispatchStore>) -> PipelineRunAdmissionHandler {
    PipelineRunAdmissionHandler::new(store as Arc<dyn WorkspacePlanDispatchStore>, None)
}

fn pipeline_run_handler_with_stage_runner(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    stage_runner: Arc<dyn WorkspacePipelineStageRunner>,
) -> PipelineRunAdmissionHandler {
    PipelineRunAdmissionHandler::new(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        Some(stage_runner),
    )
}

fn pipeline_run_item() -> WorkspacePlanOutboxRecord {
    let mut item = outbox("job-pipeline-run", PIPELINE_RUN_REQUESTED_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "node_id": "node-test",
        "attempt_id": "attempt-test",
        "reason": "operator requested harness-native pipeline"
    });
    item
}

fn pipeline_run_item_without_attempt() -> WorkspacePlanOutboxRecord {
    let mut item = pipeline_run_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.remove("attempt_id");
    }
    item
}

fn pipeline_run_record(
    id: &str,
    status: &str,
    attempt_id: Option<&str>,
    commit_ref: Option<&str>,
    metadata_json: Value,
) -> WorkspacePipelineRunRecord {
    let timestamp = Utc.with_ymd_and_hms(2026, 1, 2, 3, 5, 5).unwrap();
    WorkspacePipelineRunRecord {
        id: id.to_string(),
        contract_id: "pipeline-contract-test".to_string(),
        workspace_id: "workspace-test".to_string(),
        plan_id: Some("plan-test".to_string()),
        node_id: Some("node-test".to_string()),
        attempt_id: attempt_id.map(ToOwned::to_owned),
        commit_ref: commit_ref.map(ToOwned::to_owned),
        provider: "sandbox_native".to_string(),
        status: status.to_string(),
        reason: None,
        started_at: Some(Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap()),
        completed_at: if status == "running" {
            None
        } else {
            Some(timestamp)
        },
        metadata_json,
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 6, 5).unwrap(),
        updated_at: None,
    }
}

fn pipeline_stage_run_record(id: &str, run_id: &str) -> WorkspacePipelineStageRunRecord {
    let timestamp = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
    WorkspacePipelineStageRunRecord {
        id: id.to_string(),
        run_id: run_id.to_string(),
        workspace_id: "workspace-test".to_string(),
        stage: "test".to_string(),
        status: "running".to_string(),
        command: Some("cargo test --workspace".to_string()),
        exit_code: None,
        stdout_preview: None,
        stderr_preview: None,
        log_ref: None,
        artifact_refs_json: Vec::new(),
        started_at: Some(timestamp),
        completed_at: None,
        duration_ms: None,
        metadata_json: json!({"required": true}),
        created_at: timestamp,
        updated_at: None,
    }
}

fn supervisor_tick_handler(
    store: Arc<FakeWorkspacePlanDispatchStore>,
) -> SupervisorTickAdmissionHandler {
    SupervisorTickAdmissionHandler::new(store as Arc<dyn WorkspacePlanDispatchStore>)
}

fn supervisor_tick_retry_item() -> WorkspacePlanOutboxRecord {
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "retry_node_id": "node-test",
        "retry_attempt_id": "attempt-stale",
        "retry_reason": "stale_plan_node_no_terminal_worker_report",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
        "extra_instructions": "recover stale node"
    });
    item
}

#[test]
fn workspace_plan_outbox_handlers_register_required_foundations() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let handlers = workspace_plan_outbox_handlers(store as Arc<dyn WorkspacePlanDispatchStore>);

    assert!(missing_required_handler_event_types(&handlers).is_empty());
    assert!(handlers.contains_key(WORKSPACE_AGENT_MENTION_EVENT));
    assert_eq!(handlers.len(), required_handler_event_types().len() + 1);
}

#[tokio::test]
async fn handoff_retry_handler_projects_attempt_and_queues_worker_launch() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler =
        DurableHandoffResumeHandler::new(Arc::clone(&store) as Arc<dyn WorkspacePlanDispatchStore>);
    let mut item = outbox("job-retry", ATTEMPT_RETRY_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "task_id": "task-test",
        "node_id": "node-test",
        "worker_agent_id": "agent-worker",
        "actor_user_id": "actor-test",
        "previous_attempt_id": "attempt-old",
        "extra_instructions": "retry with context"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let attempts = store.attempts();
    assert_eq!(attempts.len(), 1);
    let attempt = &attempts[0];
    assert_eq!(attempt.workspace_task_id, "task-test");
    assert_eq!(attempt.root_goal_task_id, "root-task");
    assert_eq!(attempt.status, "running");
    assert_eq!(attempt.attempt_number, 1);
    assert_eq!(attempt.worker_agent_id.as_deref(), Some("agent-worker"));
    assert_eq!(attempt.leader_agent_id, None);

    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_ID].as_str(),
        Some(attempt.id.as_str())
    );
    assert_eq!(task.metadata_json["launch_state"], "scheduled");
    assert_eq!(task.metadata_json["last_attempt_status"], "running");

    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "dispatched");
    assert_eq!(
        node.current_attempt_id.as_deref(),
        Some(attempt.id.as_str())
    );
    assert_eq!(
        node.handoff_package_json
            .as_ref()
            .and_then(|value| value["previous_attempt_id"].as_str()),
        Some("attempt-old")
    );

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(
        queued[0].payload_json["attempt_id"].as_str(),
        Some(attempt.id.as_str())
    );
    assert_eq!(
        queued[0].payload_json["extra_instructions"].as_str(),
        Some("retry with context")
    );
    assert_eq!(
        queued[0].metadata_json["source"].as_str(),
        Some("workspace_plan.attempt_retry")
    );
}

#[tokio::test]
async fn handoff_retry_handler_preserves_worker_stream_orphan_retry_context() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut task = task_with_plan_metadata();
    task.blocker_reason =
        Some("Worker stream stopped without a terminal complete/error event".to_string());
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("42-0"));
    task_metadata.insert(
        "worker_stream_replay_attempt_id".to_string(),
        json!("attempt-old"),
    );
    task_metadata.insert("worker_stream_message_id".to_string(), json!("old-msg"));
    task_metadata.insert(
        "worker_stream_terminal_outcome".to_string(),
        json!("no_terminal_event"),
    );
    task_metadata.insert("last_worker_report_type".to_string(), json!("blocked"));
    task_metadata.insert(
        LAST_WORKER_REPORT_SUMMARY.to_string(),
        json!("old orphan report"),
    );
    task_metadata.insert(
        LAST_WORKER_REPORT_ATTEMPT_ID.to_string(),
        json!("attempt-old"),
    );
    task_metadata.insert(PENDING_LEADER_ADJUDICATION.to_string(), json!(true));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    let mut node_metadata = object_or_empty(node.metadata_json.clone());
    node_metadata.insert("worker_stream_last_entry_id".to_string(), json!("42-0"));
    node_metadata.insert(
        "worker_stream_replay_attempt_id".to_string(),
        json!("attempt-old"),
    );
    node_metadata.insert("worker_stream_message_id".to_string(), json!("old-msg"));
    node_metadata.insert("last_worker_report_type".to_string(), json!("blocked"));
    node_metadata.insert(
        LAST_WORKER_REPORT_ATTEMPT_ID.to_string(),
        json!("attempt-old"),
    );
    node.metadata_json = Value::Object(node_metadata);
    store.insert_node(node);
    let handler =
        DurableHandoffResumeHandler::new(Arc::clone(&store) as Arc<dyn WorkspacePlanDispatchStore>);
    let mut item = outbox("job-retry", ATTEMPT_RETRY_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "task_id": "task-test",
        "node_id": "node-test",
        "worker_agent_id": "agent-worker",
        "actor_user_id": "actor-test",
        "previous_attempt_id": "attempt-old",
        "retry_reason": "worker_stream_agent_not_running_stream_idle",
        "retry_origin": "worker_stream_orphan_report",
        "worker_stream_orphan_retry_reason": "worker_stream_agent_not_running_stream_idle",
        "worker_stream_orphan_summary": "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert!(task.blocker_reason.is_none());
    assert_eq!(
        task.metadata_json["last_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
        task.metadata_json["last_retry_previous_attempt_id"],
        "attempt-old"
    );
    assert_eq!(
        task.metadata_json["retry_origin"],
        "worker_stream_orphan_report"
    );
    assert_eq!(
        task.metadata_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert!(task
        .metadata_json
        .get("last_retry_context_at")
        .and_then(Value::as_str)
        .is_some());
    for key in [
        "worker_stream_last_entry_id",
        "worker_stream_replay_attempt_id",
        "worker_stream_message_id",
        "worker_stream_terminal_outcome",
        "last_worker_report_type",
        LAST_WORKER_REPORT_SUMMARY,
        LAST_WORKER_REPORT_ATTEMPT_ID,
        PENDING_LEADER_ADJUDICATION,
    ] {
        assert!(
            task.metadata_json.get(key).is_none(),
            "task metadata key {key} should be cleared for retry"
        );
    }

    let node = store.node("node-test");
    let handoff = node.handoff_package_json.as_ref().unwrap();
    assert_eq!(
        handoff["retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
            handoff["worker_stream_orphan_summary"],
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        );
    assert_eq!(
        node.metadata_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    for key in [
        "worker_stream_last_entry_id",
        "worker_stream_replay_attempt_id",
        "worker_stream_message_id",
        "last_worker_report_type",
        LAST_WORKER_REPORT_ATTEMPT_ID,
    ] {
        assert!(
            node.metadata_json.get(key).is_none(),
            "node metadata key {key} should be cleared for retry"
        );
    }

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(queued[0].payload_json["previous_attempt_id"], "attempt-old");
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
        queued[0].payload_json["retry_origin"],
        "worker_stream_orphan_report"
    );
    assert_eq!(
        queued[0].payload_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
}

#[tokio::test]
async fn handoff_retry_handler_applies_attempt_worktree_checkpoint_to_feature_node() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.feature_checkpoint_json = Some(json!({
        "commit_ref": "abcdef1234567890",
        "base_ref": "main",
        "expected_artifacts": ["src/lib.rs"]
    }));
    store.insert_node(node);
    let handler =
        DurableHandoffResumeHandler::new(Arc::clone(&store) as Arc<dyn WorkspacePlanDispatchStore>);
    let mut item = outbox("job-retry", ATTEMPT_RETRY_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "task_id": "task-test",
        "node_id": "node-test",
        "worker_agent_id": "agent-worker",
        "actor_user_id": "actor-test",
        "previous_attempt_id": "attempt-old",
        "extra_instructions": "retry with context"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    let attempt_id = node.current_attempt_id.as_deref().unwrap();
    let checkpoint = node.feature_checkpoint_json.as_ref().unwrap();
    assert_eq!(
        checkpoint["worktree_path"],
        format!("${{sandbox_code_root}}/../.memstack/worktrees/{attempt_id}")
    );
    assert_eq!(
        checkpoint["branch_name"],
        worktree_branch_name("node-test", attempt_id)
    );
    assert_eq!(checkpoint["base_ref"], "abcdef1234567890");
}

#[test]
fn worker_conversation_id_matches_python_uuid5_contract() {
    assert_eq!(
        worker_conversation_id(
            "workspace-test",
            "agent-worker",
            "task-test",
            Some("attempt-test")
        ),
        "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
    );
}

#[test]
fn should_stop_orphaned_worker_stream_matches_python_contract() {
    let finished_without_stream =
        worker_stream_watchdog::should_stop(Some("msg-1"), None, true, 0.0, Some(900));
    assert!(finished_without_stream.should_stop);
    assert_eq!(
        finished_without_stream
            .reason
            .map(worker_stream_watchdog::StopReason::as_str),
        Some("agent_finished_without_terminal_event")
    );

    let finished_matching_stream =
        worker_stream_watchdog::should_stop(Some("msg-1"), Some("msg-1"), true, 0.0, Some(900));
    assert!(finished_matching_stream.should_stop);
    assert_eq!(
        finished_matching_stream
            .reason
            .map(worker_stream_watchdog::StopReason::as_str),
        Some("agent_finished_without_terminal_event")
    );

    let finished_for_other_message =
        worker_stream_watchdog::should_stop(Some("msg-2"), Some("msg-1"), true, 999.0, Some(900));
    assert!(!finished_for_other_message.should_stop);
    assert_eq!(finished_for_other_message.reason, None);

    let not_running_below_grace =
        worker_stream_watchdog::should_stop(None, Some("msg-1"), false, 899.0, Some(900));
    assert!(!not_running_below_grace.should_stop);
    assert_eq!(not_running_below_grace.reason, None);

    let not_running_at_grace =
        worker_stream_watchdog::should_stop(None, Some("msg-1"), false, 900.0, Some(900));
    assert!(not_running_at_grace.should_stop);
    assert_eq!(
        not_running_at_grace
            .reason
            .map(worker_stream_watchdog::StopReason::as_str),
        Some("agent_not_running_stream_idle")
    );

    let running_over_grace =
        worker_stream_watchdog::should_stop(None, Some("msg-1"), true, 1200.0, Some(900));
    assert!(!running_over_grace.should_stop);
    assert_eq!(running_over_grace.reason, None);

    let clamped_grace = worker_stream_watchdog::should_stop(None, None, false, 1.0, Some(0));
    assert!(clamped_grace.should_stop);
    assert_eq!(
        clamped_grace
            .reason
            .map(worker_stream_watchdog::StopReason::as_str),
        Some("agent_not_running_stream_idle")
    );

    let empty_finished_marker =
        worker_stream_watchdog::should_stop(Some(""), None, false, 0.5, Some(1));
    assert!(!empty_finished_marker.should_stop);
    assert_eq!(empty_finished_marker.reason, None);
}

#[test]
fn worker_stream_watchdog_extracts_message_id_like_python() {
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "message",
            "data": {"id": "msg-primary", "message_id": "msg-secondary"}
        })),
        Some("msg-primary")
    );
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "message",
            "data": {"message_id": "msg-secondary"}
        })),
        Some("msg-secondary")
    );
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "message",
            "data": {"id": ""}
        })),
        None
    );
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "text_delta",
            "data": {"id": "msg-ignored"}
        })),
        None
    );
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "message",
            "data": []
        })),
        None
    );
}

#[test]
fn worker_stream_watchdog_idle_progress_matches_python_contract() {
    assert!(!worker_stream_watchdog::should_publish_idle_progress(
        59.9,
        0.0,
        100.0,
        Some(60)
    ));
    assert!(worker_stream_watchdog::should_publish_idle_progress(
        60.0,
        0.0,
        100.0,
        Some(60)
    ));
    assert!(!worker_stream_watchdog::should_publish_idle_progress(
        120.0,
        90.0,
        149.9,
        Some(60)
    ));
    assert!(worker_stream_watchdog::should_publish_idle_progress(
        120.0,
        90.0,
        150.0,
        Some(60)
    ));
    assert!(worker_stream_watchdog::should_publish_idle_progress(
        1.0,
        0.0,
        1.0,
        Some(0)
    ));

    assert_eq!(
            worker_stream_watchdog::idle_progress_summary(61.9, Some("observe"), true, None),
            "Worker stream still active; no new visible stream event for 61s; agent:running present; last_event=observe"
        );
    assert_eq!(
            worker_stream_watchdog::idle_progress_summary(
                900.0,
                Some(""),
                false,
                Some("msg-1")
            ),
            "Worker stream still active; no new visible stream event for 900s; agent:running missing; agent:finished=msg-1"
        );
}

#[test]
fn worker_stream_watchdog_launch_started_summary_matches_python_contract() {
    assert_eq!(
            worker_stream_watchdog::worker_launch_started_summary(
                Some("9"),
                Some(
                    "verification failed:\n  - clean_worktree_after_commit: ?? .playwright-cache/; ?? logs/"
                ),
            ),
            "Worker attempt #9 started from verifier feedback: verification failed: - clean_worktree_after_commit: ?? .playwright-cache/; ?? logs/"
        );
    assert_eq!(
        worker_stream_watchdog::worker_launch_started_summary(None, None),
        "Worker attempt started; session is bound and streaming."
    );
    let long_feedback = "x".repeat(WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS + 50);
    let summary =
        worker_stream_watchdog::worker_launch_started_summary(Some("10"), Some(&long_feedback));
    assert!(summary.starts_with("Worker attempt #10 started from verifier feedback: "));
    assert!(summary.ends_with("..."));
    assert!(summary.len() < WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS + 80);

    let unicode_feedback = "验".repeat(WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS + 1);
    let unicode_summary =
        worker_stream_watchdog::worker_launch_started_summary(Some("11"), Some(&unicode_feedback));
    assert!(unicode_summary.ends_with("..."));
}

#[test]
fn worker_stream_watchdog_completion_summary_matches_python_contract() {
    assert_eq!(
        worker_stream_watchdog::stream_completion_summary("Finished the implementation.", ""),
        "Finished the implementation."
    );
    assert_eq!(
        worker_stream_watchdog::stream_completion_summary("", ""),
        "Worker stream completed without an explicit workspace terminal report."
    );
    let accumulated = "x".repeat(2500);
    let summary = worker_stream_watchdog::stream_completion_summary("", &accumulated);
    assert_eq!(summary.len(), WORKER_STREAM_COMPLETION_SUMMARY_CHARS);
    assert!(summary.ends_with("..."));

    let unicode_accumulated = "完".repeat(WORKER_STREAM_COMPLETION_SUMMARY_CHARS + 1);
    let unicode_summary =
        worker_stream_watchdog::stream_completion_summary("", &unicode_accumulated);
    assert_eq!(
        unicode_summary.chars().count(),
        WORKER_STREAM_COMPLETION_SUMMARY_CHARS
    );
    assert!(unicode_summary.ends_with("..."));
}

#[test]
fn worker_stream_watchdog_terminal_report_observations_match_python_contract() {
    let denied = json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_complete",
            "result": "{\"error\": \"completion denied: protected test/review node includes failed evidence\"}",
            "error": null
        }
    });
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_observation_status(&denied)
            .map(worker_stream_watchdog::TerminalReportToolStatus::as_str),
        Some("denied")
    );
    assert!(!worker_stream_watchdog::should_synthesize_stream_completion_report(true));

    let applied = json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_blocked",
            "result": "{\"applied_report\": {\"applied\": true}}",
            "error": null
        }
    });
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_observation_status(&applied)
            .map(worker_stream_watchdog::TerminalReportToolStatus::as_str),
        Some("applied")
    );
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_report_type(&applied)
            .map(worker_stream_watchdog::TerminalReportType::as_str),
        Some("blocked")
    );

    let supervisor_only = json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_complete",
            "result": "{\"ok\": true, \"applied_report\": {\"skipped_supervisor_only\": true, \"reason\": \"WORKSPACE_WTP_V1_ONLY\"}}",
            "error": null
        }
    });
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_observation_status(&supervisor_only)
            .map(worker_stream_watchdog::TerminalReportToolStatus::as_str),
        Some("attempted")
    );

    let non_terminal_tool = json!({
        "type": "observe",
        "data": {"tool_name": "bash", "result": "done", "error": null}
    });
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_observation_status(&non_terminal_tool),
        None
    );
    assert!(worker_stream_watchdog::should_synthesize_stream_completion_report(false));
}

#[test]
fn worker_stream_watchdog_terminal_report_metadata_matches_python_contract() {
    let metadata = json!({
        "last_worker_report_attempt_id": "attempt-1",
        "last_worker_report_type": "completed"
    });
    assert!(
        worker_stream_watchdog::terminal_report_metadata_matches_attempt(
            Some(&metadata),
            Some("attempt-1"),
            Some("completed")
        )
    );
    assert!(
        !worker_stream_watchdog::terminal_report_metadata_matches_attempt(
            Some(&metadata),
            Some("attempt-2"),
            Some("completed")
        )
    );
    assert!(
        !worker_stream_watchdog::terminal_report_metadata_matches_attempt(
            Some(&metadata),
            Some("attempt-1"),
            Some("blocked")
        )
    );
    assert!(worker_stream_watchdog::should_reconcile_terminal_report_tool(true, false));
    assert!(!worker_stream_watchdog::should_reconcile_terminal_report_tool(true, true));
    assert!(!worker_stream_watchdog::should_reconcile_terminal_report_tool(false, false));
}

#[test]
fn worker_stream_watchdog_reduces_text_then_complete_like_python_stream_loop() {
    let mut state = worker_stream_watchdog::StreamState::default();
    assert_eq!(
        state.observe_event(&json!({
            "type": "message",
            "data": {"id": "msg-1"}
        })),
        None
    );
    assert_eq!(state.stream_message_id.as_deref(), Some("msg-1"));
    assert_eq!(
        state.observe_event(&json!({
            "type": "text_delta",
            "data": {"text": "Finished "}
        })),
        None
    );
    assert_eq!(
        state.observe_event(&json!({
            "type": "text_delta",
            "data": {"text": "implementation."}
        })),
        None
    );
    assert_eq!(
        state.observe_event(&json!({
            "type": "complete",
            "data": {"content": ""}
        })),
        Some(worker_stream_watchdog::StreamTerminalEvent::Complete)
    );
    assert_eq!(state.final_content, "Finished implementation.");
    assert_eq!(state.last_stream_event_type.as_deref(), Some("complete"));

    let outcome = state.terminal_outcome(false);
    assert_eq!(outcome.outcome_reason, "completed");
    assert_eq!(outcome.launch_state, "completed_via_stream");
    assert_eq!(
        outcome
            .report_type
            .map(worker_stream_watchdog::TerminalReportType::as_str),
        Some("completed")
    );
    assert_eq!(outcome.summary, "Finished implementation.");
    assert!(outcome.should_report);
    assert!(!outcome.should_reconcile);
}

#[test]
fn worker_stream_watchdog_terminal_tool_outcomes_match_python_stream_loop() {
    let mut denied = worker_stream_watchdog::StreamState::default();
    denied.observe_event(&json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_complete",
            "result": "{\"error\": \"completion denied: failed tests\"}",
            "error": null
        }
    }));
    denied.observe_event(&json!({
        "type": "complete",
        "data": {"content": "ignored fallback"}
    }));
    let denied_outcome = denied.terminal_outcome(false);
    assert_eq!(denied_outcome.outcome_reason, "terminal_report_tool_denied");
    assert_eq!(denied_outcome.launch_state, "terminal_report_tool_denied");
    assert!(!denied_outcome.should_report);

    let mut applied = worker_stream_watchdog::StreamState::default();
    applied.observe_event(&json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_blocked",
            "result": "{\"applied_report\": {\"applied\": true}}",
            "error": null
        }
    }));
    applied.observe_event(&json!({
        "type": "complete",
        "data": {"content": "blocked summary"}
    }));
    let reconcile = applied.terminal_outcome(false);
    assert_eq!(reconcile.outcome_reason, "terminal_report_tool_reconciled");
    assert_eq!(reconcile.launch_state, "terminal_report_tool_reconciled");
    assert_eq!(
        reconcile
            .report_type
            .map(worker_stream_watchdog::TerminalReportType::as_str),
        Some("blocked")
    );
    assert!(reconcile.should_report);
    assert!(reconcile.should_reconcile);

    let already_recorded = applied.terminal_outcome(true);
    assert_eq!(
        already_recorded.outcome_reason,
        "terminal_report_tool_applied"
    );
    assert!(!already_recorded.should_report);
}

#[test]
fn worker_stream_watchdog_error_and_missing_terminal_outcomes_match_python_loop() {
    let mut error = worker_stream_watchdog::StreamState::default();
    assert_eq!(
        error.observe_event(&json!({
            "type": "error",
            "data": {"message": "worker failed"}
        })),
        Some(worker_stream_watchdog::StreamTerminalEvent::Error)
    );
    let error_outcome = error.terminal_outcome(false);
    assert_eq!(error_outcome.outcome_reason, "blocked");
    assert_eq!(error_outcome.launch_state, "blocked");
    assert_eq!(
        error_outcome
            .report_type
            .map(worker_stream_watchdog::TerminalReportType::as_str),
        Some("blocked")
    );
    assert_eq!(error_outcome.summary, "worker failed");
    assert!(error_outcome.should_report);

    let mut ended = worker_stream_watchdog::StreamState::default();
    ended.mark_stream_ended_without_terminal();
    let ended_outcome = ended.terminal_outcome(false);
    assert_eq!(ended_outcome.outcome_reason, "no_terminal_event");
    assert_eq!(
        ended_outcome.summary,
        "Worker stream ended without a terminal complete/error event."
    );
    assert!(ended_outcome.should_report);

    let mut orphan = worker_stream_watchdog::StreamState::default();
    orphan.mark_orphaned_stream_stop(Some("agent_not_running_stream_idle"));
    let orphan_outcome = orphan.terminal_outcome(false);
    assert_eq!(orphan_outcome.outcome_reason, "no_terminal_event");
    assert_eq!(
            orphan_outcome.summary,
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        );
}

#[tokio::test]
async fn worker_stream_terminal_outcome_persists_completed_report_like_python() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    task.status = "in_progress".to_string();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt(
        "attempt-test",
        "running",
        Some("conversation-test"),
    ));
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut stream = worker_stream_watchdog::StreamState::default();
    stream.observe_event(&json!({
            "type": "complete",
            "data": {
                "content": "{\"summary\":\"finished from stream\",\"commit_ref\":\"abcdef1234567890\",\"test_commands\":[\"cargo test -p app\"]}"
            }
        }));
    let outcome = stream.terminal_outcome(false);

    let reported = handler
        .persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
            workspace_id: "workspace-test",
            task_id: "task-test",
            root_goal_task_id: Some("root-task"),
            attempt_id: Some("attempt-test"),
            conversation_id: Some("conversation-test"),
            actor_user_id: "actor-test",
            worker_agent_id: "agent-worker",
            leader_agent_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
            plan_id: Some("plan-test"),
            node_id: Some("node-test"),
            outcome: &outcome,
            now: Utc.with_ymd_and_hms(2026, 1, 2, 4, 0, 0).unwrap(),
        })
        .await
        .unwrap();

    assert!(reported);
    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json["launch_state"], "completed_via_stream");
    assert_eq!(task.metadata_json["last_worker_report_type"], "completed");
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
        "finished from stream"
    );
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_ATTEMPT_ID],
        "attempt-test"
    );
    assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], false);
    assert_eq!(
        task.metadata_json["last_attempt_status"],
        "awaiting_plan_verification"
    );
    assert_eq!(
        task.metadata_json["last_worker_report_artifacts"],
        json!(["commit_ref:abcdef1234567890"])
    );
    assert_eq!(
        task.metadata_json["last_worker_report_verifications"],
        json!(["test_run:cargo test -p app"])
    );
    assert_eq!(
        task.metadata_json["execution_state"]["last_agent_action"],
        "await_plan_verification"
    );
    assert_eq!(
        task.metadata_json["last_worker_report_fingerprint"]
            .as_str()
            .unwrap()
            .len(),
        64
    );
    let attempt = store.attempts().remove(0);
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(
        attempt.candidate_summary.as_deref(),
        Some("finished from stream")
    );
    assert_eq!(
        attempt.candidate_artifacts_json,
        vec!["commit_ref:abcdef1234567890".to_string()]
    );
    assert_eq!(
        attempt.candidate_verifications_json,
        vec!["test_run:cargo test -p app".to_string()]
    );
    assert_eq!(
        attempt.conversation_id.as_deref(),
        Some("conversation-test")
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.progress_json["note"], "finished from stream");
    assert_eq!(
        node.metadata_json["latest_worker_progress"]["attempt_id"],
        "attempt-test"
    );
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "worker_report_terminal");
    assert_eq!(events[0].payload_json["report_type"], "completed");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
    assert_eq!(outbox[0].metadata_json["source"], "worker_report");
}

#[tokio::test]
async fn worker_stream_terminal_outcome_persists_no_terminal_blocked_report() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut stream = worker_stream_watchdog::StreamState::default();
    stream.mark_stream_ended_without_terminal();
    let outcome = stream.terminal_outcome(false);

    let reported = handler
        .persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
            workspace_id: "workspace-test",
            task_id: "task-test",
            root_goal_task_id: Some("root-task"),
            attempt_id: Some("attempt-test"),
            conversation_id: Some("conversation-test"),
            actor_user_id: "actor-test",
            worker_agent_id: "agent-worker",
            leader_agent_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
            plan_id: Some("plan-test"),
            node_id: Some("node-test"),
            outcome: &outcome,
            now: Utc.with_ymd_and_hms(2026, 1, 2, 4, 1, 0).unwrap(),
        })
        .await
        .unwrap();

    assert!(reported);
    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json["launch_state"], "no_terminal_event");
    assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
    assert_eq!(
        task.blocker_reason.as_deref(),
        Some("Worker stream ended without a terminal complete/error event.")
    );
    let attempt = store.attempts().remove(0);
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(
        attempt.candidate_summary.as_deref(),
        Some("Worker stream ended without a terminal complete/error event.")
    );
    assert!(attempt.candidate_verifications_json.is_empty());
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    assert_eq!(
        store.plan_events()[0].payload_json["report_type"],
        "blocked"
    );
}

#[tokio::test]
async fn worker_stream_terminal_outcome_does_not_duplicate_applied_terminal_tool_report() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut stream = worker_stream_watchdog::StreamState::default();
    stream.observe_event(&json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_complete",
            "result": "{\"applied_report\":{\"applied\":true}}"
        }
    }));
    stream.observe_event(&json!({"type": "complete", "data": {"content": "done"}}));
    let outcome = stream.terminal_outcome(true);

    let reported = handler
        .persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
            workspace_id: "workspace-test",
            task_id: "task-test",
            root_goal_task_id: Some("root-task"),
            attempt_id: Some("attempt-test"),
            conversation_id: None,
            actor_user_id: "actor-test",
            worker_agent_id: "agent-worker",
            leader_agent_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
            plan_id: Some("plan-test"),
            node_id: Some("node-test"),
            outcome: &outcome,
            now: Utc.with_ymd_and_hms(2026, 1, 2, 4, 2, 0).unwrap(),
        })
        .await
        .unwrap();

    assert!(!reported);
    let task = store.task("task-test");
    assert_eq!(
        task.metadata_json["launch_state"],
        "terminal_report_tool_applied"
    );
    assert!(task.metadata_json.get("last_worker_report_type").is_none());
    let attempt = store.attempts().remove(0);
    assert_eq!(attempt.status, "running");
    assert!(attempt.candidate_summary.is_none());
    assert!(store.plan_events().is_empty());
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn worker_launch_handler_binds_conversation_and_marks_node_running() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("preferred_language".to_string(), json!("zh-CN"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut item = worker_launch_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.insert("previous_attempt_id".to_string(), json!("attempt-old"));
        payload.insert(
            "retry_reason".to_string(),
            json!("worker_stream_agent_not_running_stream_idle"),
        );
        payload.insert(
            "retry_origin".to_string(),
            json!("worker_stream_orphan_report"),
        );
        payload.insert(
            "worker_stream_orphan_retry_reason".to_string(),
            json!("worker_stream_agent_not_running_stream_idle"),
        );
        payload.insert(
                "worker_stream_orphan_summary".to_string(),
                json!(
                    "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
                ),
            );
    }

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
    );
    assert_eq!(task.metadata_json["current_attempt_number"], 1);
    assert_eq!(
        task.metadata_json["current_attempt_worker_agent_id"],
        "agent-worker"
    );
    assert!(task.metadata_json["worker_launch_admitted_at"].is_string());
    assert!(task.metadata_json["worker_launch_bound_at"].is_string());
    assert_eq!(
        task.metadata_json["last_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
        task.metadata_json["last_retry_previous_attempt_id"],
        "attempt-old"
    );
    assert_eq!(
        task.metadata_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "running");
    assert_eq!(
        attempt.conversation_id.as_deref(),
        Some("d267a78e-eefc-5d33-bfb3-ac4fa7ece855")
    );
    let conversation = store.conversation("d267a78e-eefc-5d33-bfb3-ac4fa7ece855");
    assert_eq!(conversation.project_id, "project-test");
    assert_eq!(conversation.tenant_id, "tenant-test");
    assert_eq!(conversation.user_id, "actor-test");
    assert_eq!(conversation.title, "Workspace Worker - Build feature");
    assert_eq!(
        conversation.agent_config_json["selected_agent_id"],
        "agent-worker"
    );
    assert_eq!(
        conversation.metadata_json["source"],
        "workspace_worker_launch"
    );
    assert_eq!(
        conversation.metadata_json["conversation_scope"],
        "task:task-test:attempt:attempt-test"
    );
    assert_eq!(conversation.metadata_json["preferred_language"], "zh-CN");
    assert_eq!(
        conversation.metadata_json["last_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
        conversation.metadata_json["last_retry_previous_attempt_id"],
        "attempt-old"
    );
    assert_eq!(
        conversation.metadata_json["retry_origin"],
        "worker_stream_orphan_report"
    );
    assert_eq!(
        conversation.metadata_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(conversation.participant_agents_json, vec!["agent-worker"]);
    assert_eq!(conversation.focused_agent_id, "agent-worker");
    assert_eq!(
        conversation.linked_workspace_task_id.as_deref(),
        Some("task-test")
    );
    let node = store.node("node-test");
    assert_eq!(node.execution, "running");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
    assert_eq!(node.metadata_json["launch_state"], "bound");
    assert_eq!(
        node.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
    );
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn worker_launch_handler_replays_bound_stream_complete_to_terminal_report() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "1-0",
        json!({"type": "message", "data": {"id": "msg-1"}}),
    );
    stream_events.push(
        conversation_id,
        "2-0",
        json!({"type": "text_delta", "data": {"text": "finished "}}),
    );
    stream_events.push(
            conversation_id,
            "3-0",
            json!({
                "type": "complete",
                "data": {
                    "content": "{\"summary\":\"done via event stream\",\"test_commands\":[\"cargo test -p app\"]}"
                }
            }),
        );
    let handler = worker_launch_handler_with_event_stream(Arc::clone(&store), stream_events, 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "completed_via_stream");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        conversation_id
    );
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "3-0");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "terminal"
    );
    assert_eq!(
        task.metadata_json["worker_stream_last_event_type"],
        "complete"
    );
    assert_eq!(task.metadata_json["worker_stream_message_id"], "msg-1");
    assert_eq!(
        task.metadata_json["worker_stream_terminal_outcome"],
        "completed"
    );
    assert_eq!(task.metadata_json["last_worker_report_type"], "completed");
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
        "done via event stream"
    );
    assert_eq!(
        task.metadata_json["last_worker_report_verifications"],
        json!(["test_run:cargo test -p app"])
    );

    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(
        attempt.candidate_summary.as_deref(),
        Some("done via event stream")
    );
    assert_eq!(attempt.conversation_id.as_deref(), Some(conversation_id));
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.progress_json["note"], "done via event stream");
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "worker_report_terminal");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
}

#[tokio::test]
async fn worker_launch_handler_ignores_previous_attempt_stream_cursor() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("99-0"));
    task_metadata.insert(
        "worker_stream_replay_attempt_id".to_string(),
        json!("attempt-old"),
    );
    task_metadata.insert("worker_stream_message_id".to_string(), json!("old-msg"));
    task_metadata.insert(
        "worker_stream_last_event_type".to_string(),
        json!("text_delta"),
    );
    task_metadata.insert(
        LAST_WORKER_REPORT_ATTEMPT_ID.to_string(),
        json!("attempt-old"),
    );
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "1-0",
        json!({"type": "message", "data": {"id": "msg-new"}}),
    );
    stream_events.push(
            conversation_id,
            "2-0",
            json!({
                "type": "complete",
                "data": {
                    "content": "{\"summary\":\"done after retry\",\"test_commands\":[\"cargo test -p retry\"]}"
                }
            }),
        );
    let handler = worker_launch_handler_with_event_stream(Arc::clone(&store), stream_events, 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "completed_via_stream");
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "2-0");
    assert_eq!(
        task.metadata_json["worker_stream_replay_attempt_id"],
        "attempt-test"
    );
    assert_eq!(task.metadata_json["worker_stream_message_id"], "msg-new");
    assert_eq!(task.metadata_json["last_worker_report_type"], "completed");
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
        "done after retry"
    );
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_ATTEMPT_ID],
        "attempt-test"
    );
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(
        attempt.candidate_summary.as_deref(),
        Some("done after retry")
    );
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
}

#[tokio::test]
async fn worker_launch_handler_replays_nonterminal_stream_without_reporting() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "1-0",
        json!({"type": "message", "data": {"id": "msg-1"}}),
    );
    stream_events.push(
        conversation_id,
        "2-0",
        json!({"type": "text_delta", "data": {"text": "still running"}}),
    );
    let handler = worker_launch_handler_with_event_stream(Arc::clone(&store), stream_events, 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "2-0");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "observed"
    );
    assert_eq!(
        task.metadata_json["worker_stream_last_event_type"],
        "text_delta"
    );
    assert_eq!(task.metadata_json["worker_stream_message_id"], "msg-1");
    assert!(task.metadata_json.get("last_worker_report_type").is_none());
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "running");
    assert!(attempt.candidate_summary.is_none());
    let node = store.node("node-test");
    assert_eq!(node.execution, "running");
    assert!(store.plan_events().is_empty());
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(outbox[0].payload_json["worker_stream_poll"], true);
    assert_eq!(outbox[0].payload_json["stream_after_id"], "2-0");
    assert!(outbox[0]
        .payload_json
        .get("reuse_conversation_id")
        .is_none());
    assert!(outbox[0].next_attempt_at.is_some());
    assert_eq!(
        outbox[0].metadata_json["source"],
        "workspace_plan.worker_launch.stream_poll"
    );
    assert_eq!(outbox[0].metadata_json["stream_poll_after_id"], "2-0");
}

#[tokio::test]
async fn worker_launch_handler_publishes_idle_progress_for_stale_nonterminal_stream() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_running(conversation_id);
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "1-0",
        json!({
            "type": "message",
            "event_time_us": 0,
            "data": {"id": "msg-1"}
        }),
    );
    stream_events.push(
        conversation_id,
        "2-0",
        json!({
            "type": "text_delta",
            "event_time_us": 0,
            "data": {"text": "still running"}
        }),
    );
    let handler = worker_launch_handler_with_state_and_event_stream(
        Arc::clone(&store),
        runtime_state,
        stream_events,
        4,
    );

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "stream_idle"
    );
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "2-0");
    assert_eq!(task.metadata_json["worker_stream_last_event_time_us"], 0);
    assert_eq!(
        task.metadata_json["worker_stream_idle_running_exists"],
        true
    );
    assert!(
        task.metadata_json["worker_stream_idle_seconds"]
            .as_i64()
            .unwrap()
            > DEFAULT_WORKER_STREAM_IDLE_PROGRESS_INTERVAL_SECONDS
    );
    let summary = task.metadata_json["worker_stream_idle_progress_summary"]
        .as_str()
        .unwrap();
    assert!(summary.contains("Worker stream still active"));
    assert!(summary.contains("agent:running present"));
    assert!(summary.contains("last_event=text_delta"));
    assert_eq!(
        task.metadata_json["execution_state"]["last_agent_action"],
        "observe_stream_idle"
    );
    assert!(task.metadata_json.get("last_worker_report_type").is_none());

    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "running");
    assert!(attempt.candidate_summary.is_none());
    let node = store.node("node-test");
    assert_eq!(node.execution, "running");
    assert_eq!(node.metadata_json["launch_state"], "stream_idle");
    assert_eq!(
        node.metadata_json["latest_worker_progress"]["event_type"],
        "worker_stream_idle"
    );
    assert_eq!(
        node.metadata_json["latest_worker_progress"]["attempt_id"],
        "attempt-test"
    );
    assert!(node.progress_json["note"]
        .as_str()
        .unwrap()
        .contains("Worker stream still active"));
    assert!(store.plan_events().is_empty());
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(outbox[0].payload_json["worker_stream_poll"], true);
    assert_eq!(outbox[0].payload_json["stream_after_id"], "2-0");
    assert_eq!(
        outbox[0].metadata_json["source"],
        "workspace_plan.worker_launch.stream_poll"
    );
}

#[tokio::test]
async fn worker_launch_stream_poll_bypasses_launch_gates_and_continues_from_cursor() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.set_active_worker_conversations(99);
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("2-0"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    store.insert_attempt(task_session_attempt(
        "attempt-test",
        "running",
        Some(conversation_id),
    ));
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_cooldown(conversation_id);
    runtime_state.insert_running(conversation_id);
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "2-0",
        json!({"type": "text_delta", "data": {"text": "already seen"}}),
    );
    stream_events.push(
        conversation_id,
        "3-0",
        json!({"type": "text_delta", "data": {"text": "next chunk"}}),
    );
    let handler = worker_launch_handler_with_state_and_event_stream(
        Arc::clone(&store),
        Arc::clone(&runtime_state),
        stream_events,
        1,
    );
    let mut item = worker_launch_item();
    let payload = item.payload_json.as_object_mut().unwrap();
    payload.insert("worker_stream_poll".to_string(), json!(true));
    payload.insert("stream_after_id".to_string(), json!("2-0"));

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert!(runtime_state.claims().is_empty());
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "stream_polling");
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "3-0");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "observed"
    );
    assert_eq!(
        task.metadata_json["worker_stream_last_event_type"],
        "text_delta"
    );
    let node = store.node("node-test");
    assert_eq!(node.execution, "running");
    assert_eq!(node.metadata_json["launch_state"], "stream_polling");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(outbox[0].payload_json["worker_stream_poll"], true);
    assert_eq!(outbox[0].payload_json["stream_after_id"], "3-0");
    assert_eq!(
        outbox[0].metadata_json["source"],
        "workspace_plan.worker_launch.stream_poll"
    );
    assert_eq!(outbox[0].metadata_json["stream_poll_entries_read"], 1);
    assert!(outbox[0].next_attempt_at.is_some());
}

#[tokio::test]
async fn worker_launch_stream_poll_persists_orphan_stop_when_running_marker_is_missing() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("2-0"));
    task_metadata.insert("worker_stream_message_id".to_string(), json!("msg-1"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    store.insert_attempt(task_session_attempt(
        "attempt-test",
        "running",
        Some(conversation_id),
    ));
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "2-0",
        json!({
            "type": "text_delta",
            "event_time_us": 0,
            "data": {"text": "already seen"}
        }),
    );
    stream_events.push(
        conversation_id,
        "3-0",
        json!({
            "type": "text_delta",
            "event_time_us": 0,
            "data": {"text": "last visible output"}
        }),
    );
    let handler = worker_launch_handler_with_state_and_event_stream(
        Arc::clone(&store),
        runtime_state,
        stream_events,
        4,
    );
    let mut item = worker_launch_item();
    let payload = item.payload_json.as_object_mut().unwrap();
    payload.insert("worker_stream_poll".to_string(), json!(true));
    payload.insert("stream_after_id".to_string(), json!("2-0"));

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "no_terminal_event");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "terminal"
    );
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "3-0");
    assert_eq!(
        task.metadata_json["worker_stream_terminal_outcome"],
        "no_terminal_event"
    );
    assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
    assert!(task
        .blocker_reason
        .as_deref()
        .unwrap()
        .contains("agent_not_running_stream_idle"));
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert!(attempt
        .candidate_summary
        .as_deref()
        .unwrap()
        .contains("agent_not_running_stream_idle"));
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.metadata_json["launch_state"], "no_terminal_event");
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "worker_report_terminal");
    assert_eq!(events[0].payload_json["report_type"], "blocked");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
}

#[tokio::test]
async fn worker_launch_stream_poll_persists_finished_marker_stop_without_new_entries() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("2-0"));
    task_metadata.insert("worker_stream_message_id".to_string(), json!("msg-1"));
    task_metadata.insert(
        "worker_stream_last_event_type".to_string(),
        json!("text_delta"),
    );
    task_metadata.insert("worker_stream_last_event_time_us".to_string(), json!(0));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    store.insert_attempt(task_session_attempt(
        "attempt-test",
        "running",
        Some(conversation_id),
    ));
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_finished(conversation_id);
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    let handler = worker_launch_handler_with_state_and_event_stream(
        Arc::clone(&store),
        runtime_state,
        stream_events,
        4,
    );
    let mut item = worker_launch_item();
    let payload = item.payload_json.as_object_mut().unwrap();
    payload.insert("worker_stream_poll".to_string(), json!(true));
    payload.insert("stream_after_id".to_string(), json!("2-0"));

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "no_terminal_event");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "terminal"
    );
    assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
    assert!(task.metadata_json[LAST_WORKER_REPORT_SUMMARY]
        .as_str()
        .unwrap()
        .contains("agent_finished_without_terminal_event"));
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(attempt.conversation_id.as_deref(), Some(conversation_id));
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].payload_json["report_type"], "blocked");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
}

#[tokio::test]
async fn worker_launch_handler_refreshes_runtime_markers_after_binding() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    runtime_state.insert_running(conversation_id);
    let handler =
        worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert_eq!(runtime_state.claims(), vec![conversation_id]);
    assert_eq!(runtime_state.refresh_cooldowns(), vec![conversation_id]);
    assert_eq!(runtime_state.refresh_running(), vec![conversation_id]);
    let task = store.task("task-test");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        conversation_id
    );
}

#[tokio::test]
async fn worker_launch_handler_reuses_repair_conversation_id_when_present() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut item = worker_launch_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.insert(
            "reuse_conversation_id".to_string(),
            json!("conv-existing-repair"),
        );
    }

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        "conv-existing-repair"
    );
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(
        attempt.conversation_id.as_deref(),
        Some("conv-existing-repair")
    );
    let conversation = store.conversation("conv-existing-repair");
    assert_eq!(conversation.metadata_json["attempt_id"], "attempt-test");
    assert_eq!(
        conversation.metadata_json["conversation_scope"],
        "task:task-test:attempt:attempt-test"
    );
}

#[tokio::test]
async fn worker_launch_handler_skips_duplicate_launch_when_cooldown_exists() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_cooldown("d267a78e-eefc-5d33-bfb3-ac4fa7ece855");
    let handler =
        worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert_eq!(
        runtime_state.claims(),
        vec!["d267a78e-eefc-5d33-bfb3-ac4fa7ece855"]
    );
    assert!(runtime_state.has_cooldown("d267a78e-eefc-5d33-bfb3-ac4fa7ece855"));
    assert_eq!(store.conversation_count(), 0);
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert!(attempt.conversation_id.is_none());
    let task = store.task("task-test");
    assert_eq!(task.status, "todo");
    assert!(task.metadata_json.get("launch_state").is_none());
    let node = store.node("node-test");
    assert_eq!(node.execution, "dispatched");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
}

#[tokio::test]
async fn worker_launch_handler_clears_reused_markers_before_repair_reuse() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_cooldown("conv-existing-repair");
    runtime_state.insert_finished("conv-existing-repair");
    let handler =
        worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);
    let mut item = worker_launch_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.insert(
            "reuse_conversation_id".to_string(),
            json!("conv-existing-repair"),
        );
    }

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert_eq!(runtime_state.clears(), vec!["conv-existing-repair"]);
    assert_eq!(runtime_state.claims(), vec!["conv-existing-repair"]);
    assert!(runtime_state.has_cooldown("conv-existing-repair"));
    assert!(!runtime_state.has_finished("conv-existing-repair"));
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(
        attempt.conversation_id.as_deref(),
        Some("conv-existing-repair")
    );
    assert_eq!(store.conversation_count(), 1);
    let task = store.task("task-test");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        "conv-existing-repair"
    );
}

#[tokio::test]
async fn worker_launch_handler_skips_reuse_when_agent_running_marker_exists() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_running("conv-existing-repair");
    let handler =
        worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);
    let mut item = worker_launch_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.insert(
            "reuse_conversation_id".to_string(),
            json!("conv-existing-repair"),
        );
    }

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert!(runtime_state.clears().is_empty());
    assert!(runtime_state.claims().is_empty());
    assert_eq!(store.conversation_count(), 0);
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert!(attempt.conversation_id.is_none());
    let task = store.task("task-test");
    assert_eq!(task.status, "todo");
    assert!(task.metadata_json.get("launch_state").is_none());
}

#[tokio::test]
async fn worker_launch_handler_records_skipped_worktree_context_without_sandbox_root() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(task.metadata_json["worktree_setup"]["status"], "skipped");
    assert_eq!(
        task.metadata_json["worktree_setup"]["reason"],
        "sandbox_code_root is not available for this workspace"
    );
    assert_eq!(
        task.metadata_json["attempt_worktree"]["attempt_id"],
        "attempt-test"
    );
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "running");
    assert_eq!(
        attempt.conversation_id.as_deref(),
        Some("d267a78e-eefc-5d33-bfb3-ac4fa7ece855")
    );
}

#[tokio::test]
async fn worker_launch_handler_blocks_attempt_for_rejected_worktree_path() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_code_root("/workspace/project"));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": "${sandbox_code_root}/src",
        "branch_name": "workspace/node-test-attempt",
        "base_ref": "HEAD"
    }));
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.status, "blocked");
    assert_eq!(task.metadata_json["launch_state"], "worktree_setup_failed");
    assert_eq!(task.metadata_json["worktree_setup"]["status"], "failed");
    assert!(task
        .blocker_reason
        .as_deref()
        .unwrap()
        .contains("worktree_path must not be inside sandbox_code_root"));
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "blocked");
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some("worktree_setup_failed")
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "blocked");
    assert_eq!(node.execution, "idle");
    assert!(node.current_attempt_id.is_none());
    assert_eq!(node.metadata_json["terminal_attempt_status"], "blocked");
    assert_eq!(node.metadata_json["worktree_setup"]["status"], "failed");
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn worker_launch_handler_prepares_local_git_attempt_worktree_when_available() {
    let Some(fixture) = git_publish_fixture() else {
        return;
    };
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_code_root(&fixture.repo.to_string_lossy()));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(task.metadata_json["worktree_setup"]["status"], "prepared");
    let worktree_path = task.metadata_json["worktree_setup"]["worktree_path"]
        .as_str()
        .unwrap();
    assert!(Path::new(worktree_path).exists());
    assert_eq!(task.metadata_json["active_execution_root"], worktree_path);
    let inside = run_git_ok(
        Path::new(worktree_path),
        &["rev-parse", "--is-inside-work-tree"],
    );
    assert_eq!(inside.trim(), "true");
    let node = store.node("node-test");
    assert_eq!(node.execution, "running");
    assert_eq!(node.metadata_json["launch_state"], "bound");
}

#[tokio::test]
async fn worker_launch_handler_defers_when_active_capacity_reached() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    store.set_active_worker_conversations(1);
    let handler = worker_launch_handler(Arc::clone(&store), 1);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(queued[0].status, "pending");
    assert!(queued[0].next_attempt_at.is_some());
    assert_eq!(
        queued[0].metadata_json["source"],
        "workspace_plan.worker_launch.deferred_capacity"
    );
    assert_eq!(
        queued[0].metadata_json["deferred_from_outbox_id"],
        "job-worker-launch"
    );
    assert_eq!(queued[0].metadata_json["active_worker_conversations"], 1);
    assert_eq!(
        queued[0].metadata_json["max_active_worker_conversations"],
        1
    );
    let task = store.task("task-test");
    assert_ne!(task.metadata_json["launch_state"], "runtime_admitted");
}

#[tokio::test]
async fn worker_launch_handler_skips_stale_attempt_without_projection() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-new"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-new".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert!(store.outbox().is_empty());
    let task = store.task("task-test");
    assert_eq!(task.status, "todo");
    assert_ne!(task.metadata_json["launch_state"], "runtime_admitted");
    let node = store.node("node-test");
    assert_eq!(node.execution, "dispatched");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-new"));
}

#[tokio::test]
async fn workspace_outbox_worker_marks_registered_handler_completed() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-complete", "known"));
    let worker = worker(
        Arc::clone(&store),
        HashMap::from([("known".to_string(), handler(HandlerBehavior::Complete))]),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let item = store.get("job-complete");
    assert_eq!(item.status, "completed");
    assert!(item.processed_at.is_some());
    assert_eq!(item.attempt_count, 1);
}

#[tokio::test]
async fn workspace_outbox_worker_fails_missing_handler_without_dropping_job() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-missing", "unknown"));
    let worker = worker(Arc::clone(&store), HashMap::new());

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            failed: 1,
            missing_handler: 1,
            ..Default::default()
        }
    );
    let item = store.get("job-missing");
    assert_eq!(item.status, "failed");
    assert_eq!(
        item.last_error.as_deref(),
        Some("no handler for event_type=unknown")
    );
    assert_eq!(item.attempt_count, 1);
}

#[tokio::test]
async fn workspace_outbox_worker_release_outcome_returns_attempt_budget() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-release", "known"));
    let worker = worker(
        Arc::clone(&store),
        HashMap::from([("known".to_string(), handler(HandlerBehavior::Release))]),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            released: 1,
            ..Default::default()
        }
    );
    let item = store.get("job-release");
    assert_eq!(item.status, "pending");
    assert_eq!(item.last_error.as_deref(), Some("shutdown"));
    assert_eq!(item.attempt_count, 0);
}

#[tokio::test]
async fn workspace_outbox_worker_binds_workspace_agent_mention_and_parks_runtime() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut item = outbox("job-mention", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = "pending_runtime".to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "source": "workspace_chat_mention",
        "workspace_llm_stage": "chat_mention"
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            parked: 1,
            ..Default::default()
        }
    );
    let item = outbox_store.get("job-mention");
    assert_eq!(item.status, WORKSPACE_AGENT_MENTION_RUNTIME_BOUND_STATUS);
    assert!(item.processed_at.is_none());
    assert!(item.lease_owner.is_none());
    assert!(item.lease_expires_at.is_none());
    assert_eq!(item.attempt_count, 1);
    assert_eq!(
        item.metadata_json
            .get("runtime_binding")
            .and_then(Value::as_str),
        Some("workspace_agent_mention_conversation")
    );
    assert_eq!(
        item.metadata_json
            .get("conversation_id")
            .and_then(Value::as_str),
        Some("conversation-mention")
    );

    let conversation = dispatch_store.conversation("conversation-mention");
    assert_eq!(conversation.project_id, "project-test");
    assert_eq!(conversation.tenant_id, "tenant-test");
    assert_eq!(conversation.user_id, "user-sender");
    assert_eq!(conversation.title, "Workspace Chat - Builder");
    assert_eq!(
        conversation
            .agent_config_json
            .get("selected_agent_id")
            .and_then(Value::as_str),
        Some("agent-builder")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("workspace_id")
            .and_then(Value::as_str),
        Some("workspace-test")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("agent_id")
            .and_then(Value::as_str),
        Some("agent-builder")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("source")
            .and_then(Value::as_str),
        Some("workspace_chat_mention")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("workspace_llm_stage")
            .and_then(Value::as_str),
        Some("chat_mention")
    );
    assert_eq!(dispatch_store.conversation_count(), 1);
}

#[tokio::test]
async fn workspace_outbox_worker_writes_agent_mention_runtime_response_ready() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let runtime = Arc::new(FakeWorkspaceAgentMentionRuntime::ok("Runtime answer"));
    let mut item = outbox("job-mention-runtime", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = "pending_runtime".to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "sender_name": "Ada",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "user_prompt": "Please summarize this plan.",
        "source": "workspace_chat_mention",
        "workspace_llm_stage": "chat_mention"
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers_with_runtime_state_and_event_stream(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>,
        None,
        None,
        None,
        Some(Arc::clone(&runtime) as Arc<dyn WorkspaceAgentMentionRuntime>),
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let first = worker.run_once().await.unwrap();

    assert_eq!(
        first,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            parked: 1,
            ..Default::default()
        }
    );
    assert_eq!(runtime.prompts(), vec!["Please summarize this plan."]);
    let item = outbox_store.get("job-mention-runtime");
    assert_eq!(item.status, WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS);
    assert_eq!(item.payload_json["final_content"], "Runtime answer");
    assert_eq!(item.metadata_json["runtime_writer"], "llm_port_single_turn");
    assert_eq!(dispatch_store.messages().len(), 0);

    let second = worker.run_once().await.unwrap();

    assert_eq!(
        second,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let item = outbox_store.get("job-mention-runtime");
    assert_eq!(item.status, "completed");
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    assert_eq!(messages[0].content, "Runtime answer");
    let events = dispatch_store.blackboard_outbox();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, WORKSPACE_MESSAGE_CREATED_EVENT);
}

#[tokio::test]
async fn workspace_outbox_worker_writes_agent_mention_runtime_error_ready() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let runtime = Arc::new(FakeWorkspaceAgentMentionRuntime::err(
        "provider unavailable",
    ));
    let mut item = outbox("job-mention-runtime-error", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = "pending_runtime".to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "source_message": {"content": "Please run this."}
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers_with_runtime_state_and_event_stream(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>,
        None,
        None,
        None,
        Some(runtime as Arc<dyn WorkspaceAgentMentionRuntime>),
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let first = worker.run_once().await.unwrap();

    assert_eq!(
        first,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            parked: 1,
            ..Default::default()
        }
    );
    let item = outbox_store.get("job-mention-runtime-error");
    assert_eq!(item.status, WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS);
    assert_eq!(
        item.payload_json["runtime_error_detail"],
        "llm error: provider unavailable"
    );

    let second = worker.run_once().await.unwrap();

    assert_eq!(
        second,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    assert_eq!(
        messages[0].content,
        "[Error] Builder could not process your request: llm error: provider unavailable"
    );
}

#[tokio::test]
async fn workspace_outbox_worker_posts_agent_response_when_runtime_result_ready() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let mut item = outbox("job-mention-response", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS.to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "final_content": "Done from runtime",
        "response_mentions": ["agent-reviewer"]
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let item = outbox_store.get("job-mention-response");
    assert_eq!(item.status, "completed");
    assert!(item.processed_at.is_some());
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    let message = &messages[0];
    assert_eq!(message.workspace_id, "workspace-test");
    assert_eq!(message.sender_id, "agent-builder");
    assert_eq!(message.sender_type, "agent");
    assert_eq!(message.content, "Done from runtime");
    assert_eq!(message.mentions_json, vec!["agent-reviewer"]);
    assert_eq!(message.parent_message_id.as_deref(), Some("message-1"));
    assert_eq!(
        message
            .metadata_json
            .get("sender_name")
            .and_then(Value::as_str),
        Some("Builder")
    );
    let events = dispatch_store.blackboard_outbox();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, WORKSPACE_MESSAGE_CREATED_EVENT);
    assert_eq!(
        events[0].payload_json["message"]["content"],
        "Done from runtime"
    );
    assert_eq!(events[0].payload_json["message"]["sender_type"], "agent");
    assert_eq!(
        events[0].metadata_json["runtime_bridge"],
        "p3_workspace_mention"
    );
}

#[tokio::test]
async fn workspace_outbox_worker_enqueues_agent_chain_mention_from_terminal_response() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    dispatch_store.insert_agent("workspace-test", "agent-reviewer", Some("Reviewer"));
    let mut item = outbox("job-mention-chain", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS.to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-builder",
        "conversation_scope": "objective:root-1",
        "message_id": "message-1",
        "final_content": "Reviewer should inspect this.",
        "response_mentions": ["agent-reviewer", "missing-agent", "agent-reviewer"],
        "chain_depth": 1
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    assert_eq!(
        messages[0].mentions_json,
        vec!["agent-reviewer", "missing-agent", "agent-reviewer"]
    );
    let chained = dispatch_store.outbox();
    assert_eq!(chained.len(), 1);
    let next = &chained[0];
    assert_eq!(next.event_type, WORKSPACE_AGENT_MENTION_EVENT);
    assert_eq!(next.status, WORKSPACE_AGENT_MENTION_PENDING_RUNTIME_STATUS);
    assert_eq!(next.payload_json["target_agent_id"], "agent-reviewer");
    assert_eq!(
        next.payload_json["target_workspace_agent_id"],
        "workspace-agent-agent-reviewer"
    );
    assert_eq!(next.payload_json["sender_user_id"], "user-sender");
    assert_eq!(next.payload_json["sender_name"], "Builder");
    assert_eq!(next.payload_json["source_agent_id"], "agent-builder");
    assert_eq!(
        next.payload_json["source"],
        WORKSPACE_AGENT_CHAIN_MENTION_SOURCE
    );
    assert_eq!(
        next.payload_json["workspace_llm_stage"],
        WORKSPACE_AGENT_CHAIN_MENTION_STAGE
    );
    assert_eq!(next.payload_json["chain_depth"], 2);
    assert_eq!(
        next.payload_json["user_prompt"],
        "[Workspace Chat] Builder mentioned you:\n\nReviewer should inspect this."
    );
    assert_eq!(
        next.payload_json["conversation_id"],
        workspace_agent_conversation_id(
            "workspace-test",
            "agent-reviewer",
            Some("objective:root-1")
        )
    );
    assert_eq!(next.metadata_json["chain_depth"], 2);
    assert_eq!(next.metadata_json["source_agent_id"], "agent-builder");
}

#[tokio::test]
async fn workspace_outbox_worker_does_not_enqueue_agent_chain_past_depth_limit() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    dispatch_store.insert_agent("workspace-test", "agent-reviewer", Some("Reviewer"));
    let mut item = outbox("job-mention-chain-limit", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS.to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-builder",
        "message_id": "message-1",
        "final_content": "Reviewer should inspect this.",
        "response_mentions": ["agent-reviewer"],
        "chain_depth": MAX_WORKSPACE_AGENT_MENTION_CHAIN_DEPTH
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    assert_eq!(dispatch_store.messages().len(), 1);
    assert!(dispatch_store.outbox().is_empty());
}

#[tokio::test]
async fn workspace_outbox_worker_posts_agent_error_when_runtime_error_ready() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let mut item = outbox("job-mention-error", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS.to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_display_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "runtime_error_detail": "model unavailable"
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let item = outbox_store.get("job-mention-error");
    assert_eq!(item.status, "completed");
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    let message = &messages[0];
    assert_eq!(
        message.content,
        "[Error] Builder could not process your request: model unavailable"
    );
    assert_eq!(message.sender_id, "agent-builder");
    assert_eq!(message.parent_message_id.as_deref(), Some("message-1"));
    let events = dispatch_store.blackboard_outbox();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].payload_json["message"]["content"],
        "[Error] Builder could not process your request: model unavailable"
    );
}

#[tokio::test]
async fn workspace_agent_mention_handler_patches_existing_conversation_linkage() {
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store
        .ensure_workspace_agent_conversation(
            "conversation-mention",
            "project-test",
            "tenant-test",
            "user-original",
            "Workspace Chat - Old Agent",
            &json!({ "selected_agent_id": "agent-old" }),
            &json!({
                "workspace_id": "workspace-test",
                "agent_id": "agent-old",
                "created_at": "2026-01-02T03:04:05Z"
            }),
            "workspace-test",
            None,
            Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        )
        .await
        .unwrap();
    let handler = WorkspaceAgentMentionBindingHandler::new(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>
    );
    let mut item = outbox("job-mention", WORKSPACE_AGENT_MENTION_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_display_name": "Builder",
        "conversation_id": "conversation-mention",
        "linked_workspace_task_id": "root-task",
        "source": "workspace_leader_mention",
        "workspace_llm_stage": "leader_mention"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert!(matches!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Park { ref status, .. }
            if status == WORKSPACE_AGENT_MENTION_RUNTIME_BOUND_STATUS
    ));
    let conversation = dispatch_store.conversation("conversation-mention");
    assert_eq!(conversation.title, "Workspace Chat - Old Agent");
    assert_eq!(
        conversation
            .agent_config_json
            .get("selected_agent_id")
            .and_then(Value::as_str),
        Some("agent-builder")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("agent_id")
            .and_then(Value::as_str),
        Some("agent-builder")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("workspace_task_id")
            .and_then(Value::as_str),
        Some("root-task")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("linked_workspace_task_id")
            .and_then(Value::as_str),
        Some("root-task")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("source")
            .and_then(Value::as_str),
        Some("workspace_leader_mention")
    );
    assert_eq!(
        conversation.linked_workspace_task_id.as_deref(),
        Some("root-task")
    );
    assert_eq!(dispatch_store.conversation_count(), 1);
}

#[tokio::test]
async fn workspace_outbox_worker_does_not_claim_unhandled_pending_runtime_events() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let mut item = outbox("job-future-runtime", "future_runtime_event");
    item.status = "pending_runtime".to_string();
    store.insert(item);
    let worker = worker(
        Arc::clone(&store),
        HashMap::from([(
            "future_runtime_event".to_string(),
            handler(HandlerBehavior::Complete),
        )]),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(report, WorkspacePlanOutboxRunReport::default());
    let item = store.get("job-future-runtime");
    assert_eq!(item.status, "pending_runtime");
    assert_eq!(item.attempt_count, 0);
    assert!(item.lease_owner.is_none());
}

#[tokio::test]
async fn workspace_outbox_worker_failed_handler_marks_retryable_failure() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-fail", "known"));
    let worker = worker(
        Arc::clone(&store),
        HashMap::from([("known".to_string(), handler(HandlerBehavior::Fail))]),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            failed: 1,
            ..Default::default()
        }
    );
    let item = store.get("job-fail");
    assert_eq!(item.status, "failed");
    assert_eq!(
        item.last_error.as_deref(),
        Some("storage error: handler boom")
    );
    assert_eq!(item.attempt_count, 1);
}

#[tokio::test]
async fn workspace_outbox_loop_refuses_autostart_without_handlers() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-safe", "unknown"));
    let worker = Arc::new(WorkspacePlanOutboxWorker::new(
        Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
        WorkspacePlanOutboxWorkerConfig {
            autostart: true,
            production_ready: true,
            ..WorkspacePlanOutboxWorkerConfig::default()
        },
        HashMap::new(),
    ));

    let runtime = worker.spawn_if_enabled();

    assert!(runtime.is_none());
    let item = store.get("job-safe");
    assert_eq!(item.status, "pending");
    assert_eq!(item.attempt_count, 0);
}

#[tokio::test]
async fn workspace_outbox_loop_refuses_partial_production_handlers() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-safe", HANDOFF_RESUME_EVENT));
    let worker = Arc::new(WorkspacePlanOutboxWorker::new(
        Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
        WorkspacePlanOutboxWorkerConfig {
            autostart: true,
            production_ready: true,
            ..WorkspacePlanOutboxWorkerConfig::default()
        },
        HashMap::from([(
            HANDOFF_RESUME_EVENT.to_string(),
            handler(HandlerBehavior::Complete),
        )]),
    ));

    let runtime = worker.spawn_if_enabled();

    assert!(runtime.is_none());
    let item = store.get("job-safe");
    assert_eq!(item.status, "pending");
    assert_eq!(item.attempt_count, 0);
}

#[tokio::test]
async fn workspace_outbox_loop_refuses_autostart_without_production_ready_gate() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-safe", "known"));
    let mut handlers = required_handler_event_types()
        .into_iter()
        .map(|event_type| (event_type.to_string(), handler(HandlerBehavior::Complete)))
        .collect::<WorkspacePlanOutboxHandlers>();
    handlers.insert("known".to_string(), handler(HandlerBehavior::Complete));
    let worker = Arc::new(WorkspacePlanOutboxWorker::new(
        Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
        WorkspacePlanOutboxWorkerConfig {
            autostart: true,
            production_ready: false,
            ..WorkspacePlanOutboxWorkerConfig::default()
        },
        handlers,
    ));

    let runtime = worker.spawn_if_enabled();

    assert!(runtime.is_none());
    let item = store.get("job-safe");
    assert_eq!(item.status, "pending");
    assert_eq!(item.attempt_count, 0);
}

#[tokio::test]
async fn workspace_outbox_loop_polls_until_stopped_when_handlers_exist() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-loop", "known"));
    let mut handlers = required_handler_event_types()
        .into_iter()
        .map(|event_type| (event_type.to_string(), handler(HandlerBehavior::Complete)))
        .collect::<WorkspacePlanOutboxHandlers>();
    handlers.insert("known".to_string(), handler(HandlerBehavior::Complete));
    let worker = Arc::new(WorkspacePlanOutboxWorker::new(
        Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
        WorkspacePlanOutboxWorkerConfig {
            worker_id: "worker-test".to_string(),
            batch_size: 10,
            lease_seconds: 60,
            poll_interval_millis: 5,
            autostart: true,
            production_ready: true,
        },
        handlers,
    ));
    let runtime = worker.spawn_if_enabled().expect("runtime should start");

    for _ in 0..20 {
        if store.get("job-loop").status == "completed" {
            runtime.shutdown().await;
            let item = store.get("job-loop");
            assert_eq!(item.status, "completed");
            assert_eq!(item.attempt_count, 1);
            return;
        }
        sleep(tokio::time::Duration::from_millis(5)).await;
    }
    runtime.shutdown().await;
    panic!("worker loop did not complete the job");
}
