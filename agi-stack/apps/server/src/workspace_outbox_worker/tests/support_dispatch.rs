use super::*;

mod impls;

#[derive(Debug, Clone, PartialEq)]
pub(super) struct FakePipelineContractRecord {
    pub(super) id: String,
    pub(super) workspace_id: String,
    pub(super) plan_id: String,
    pub(super) provider: String,
    pub(super) code_root: Option<String>,
    pub(super) commands_json: Value,
    pub(super) env_json: Value,
    pub(super) trigger_policy_json: Value,
    pub(super) timeout_seconds: i32,
    pub(super) auto_deploy: bool,
    pub(super) preview_port: Option<i32>,
    pub(super) health_url: Option<String>,
    pub(super) metadata_json: Value,
    pub(super) created_at: DateTime<Utc>,
    pub(super) updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct FakeWorkerConversationRecord {
    pub(super) id: String,
    pub(super) project_id: String,
    pub(super) tenant_id: String,
    pub(super) user_id: String,
    pub(super) title: String,
    pub(super) agent_config_json: Value,
    pub(super) metadata_json: Value,
    pub(super) participant_agents_json: Vec<String>,
    pub(super) focused_agent_id: String,
    pub(super) workspace_id: String,
    pub(super) linked_workspace_task_id: Option<String>,
    pub(super) updated_at: DateTime<Utc>,
}

#[derive(Default)]
pub(super) struct FakeWorkspacePlanDispatchStore {
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
    pub(super) fn insert_workspace(&self, workspace: WorkspaceRecord) {
        self.workspaces
            .lock()
            .unwrap()
            .insert(workspace.id.clone(), workspace);
    }

    pub(super) fn insert_member(&self, workspace_id: &str, user_id: &str) {
        self.members
            .lock()
            .unwrap()
            .entry(workspace_id.to_string())
            .or_default()
            .insert(user_id.to_string());
    }

    pub(super) fn insert_agent(
        &self,
        workspace_id: &str,
        agent_id: &str,
        display_name: Option<&str>,
    ) {
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

    pub(super) fn insert_task(&self, task: WorkspaceTaskRecord) {
        self.tasks.lock().unwrap().insert(task.id.clone(), task);
    }

    pub(super) fn insert_plan(&self, plan: WorkspacePlanRecord) {
        self.plans.lock().unwrap().insert(plan.id.clone(), plan);
    }

    pub(super) fn insert_node(&self, node: WorkspacePlanNodeRecord) {
        self.nodes.lock().unwrap().insert(node.id.clone(), node);
    }

    pub(super) fn insert_attempt(&self, attempt: WorkspaceTaskSessionAttemptRecord) {
        self.attempts
            .lock()
            .unwrap()
            .insert(attempt.id.clone(), attempt);
    }

    pub(super) fn insert_supervisor_dispose_decision(
        &self,
        workspace_id: &str,
        plan_id: &str,
        node_id: &str,
    ) {
        self.supervisor_dispose_nodes.lock().unwrap().insert((
            workspace_id.to_string(),
            plan_id.to_string(),
            node_id.to_string(),
        ));
    }

    pub(super) fn insert_pipeline_run(&self, run: WorkspacePipelineRunRecord) {
        self.pipeline_runs
            .lock()
            .unwrap()
            .insert(run.id.clone(), run);
    }

    pub(super) fn set_active_worker_conversations(&self, count: i64) {
        *self.active_worker_conversations.lock().unwrap() = count;
    }

    pub(super) fn task(&self, id: &str) -> WorkspaceTaskRecord {
        self.tasks.lock().unwrap().get(id).unwrap().clone()
    }

    pub(super) fn node(&self, id: &str) -> WorkspacePlanNodeRecord {
        self.nodes.lock().unwrap().get(id).unwrap().clone()
    }

    pub(super) fn pipeline_run(&self, id: &str) -> WorkspacePipelineRunRecord {
        self.pipeline_runs.lock().unwrap().get(id).unwrap().clone()
    }

    pub(super) fn pipeline_runs(&self) -> Vec<WorkspacePipelineRunRecord> {
        self.pipeline_runs
            .lock()
            .unwrap()
            .values()
            .cloned()
            .collect()
    }

    pub(super) fn pipeline_stage_run(&self, id: &str) -> WorkspacePipelineStageRunRecord {
        self.pipeline_stage_runs
            .lock()
            .unwrap()
            .get(id)
            .unwrap()
            .clone()
    }

    pub(super) fn pipeline_stage_runs(&self) -> Vec<WorkspacePipelineStageRunRecord> {
        self.pipeline_stage_runs
            .lock()
            .unwrap()
            .values()
            .cloned()
            .collect()
    }

    pub(super) fn pipeline_contract(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> FakePipelineContractRecord {
        self.pipeline_contracts
            .lock()
            .unwrap()
            .get(&(workspace_id.to_string(), plan_id.to_string()))
            .unwrap()
            .clone()
    }

    pub(super) fn attempts(&self) -> Vec<WorkspaceTaskSessionAttemptRecord> {
        self.attempts.lock().unwrap().values().cloned().collect()
    }

    pub(super) fn attempt(&self, id: &str) -> WorkspaceTaskSessionAttemptRecord {
        self.attempts.lock().unwrap().get(id).unwrap().clone()
    }

    pub(super) fn conversation(&self, id: &str) -> FakeWorkerConversationRecord {
        self.conversations
            .lock()
            .unwrap()
            .get(id)
            .cloned()
            .unwrap_or_else(|| panic!("conversation {id} not found"))
    }

    pub(super) fn conversation_count(&self) -> usize {
        self.conversations.lock().unwrap().len()
    }

    pub(super) fn messages(&self) -> Vec<WorkspaceMessageRecord> {
        self.messages.lock().unwrap().values().cloned().collect()
    }

    pub(super) fn blackboard_outbox(&self) -> Vec<BlackboardOutboxRecord> {
        self.blackboard_outbox.lock().unwrap().clone()
    }

    pub(super) fn plan_events(&self) -> Vec<WorkspacePlanEventRecord> {
        self.plan_events.lock().unwrap().clone()
    }

    pub(super) fn outbox(&self) -> Vec<WorkspacePlanOutboxRecord> {
        self.outbox.lock().unwrap().clone()
    }
}
