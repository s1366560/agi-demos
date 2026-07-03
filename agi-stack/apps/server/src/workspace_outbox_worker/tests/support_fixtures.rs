use super::support_dispatch::FakeWorkspacePlanDispatchStore;
use super::support_outbox::outbox;
use super::*;

pub(super) fn task_with_plan_metadata() -> WorkspaceTaskRecord {
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

pub(super) fn root_goal_task() -> WorkspaceTaskRecord {
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

pub(super) fn workspace_with_metadata(metadata_json: Value) -> WorkspaceRecord {
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

pub(super) fn workspace_with_code_root(root: &str) -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "code_context": {
            "sandbox_code_root": root
        }
    }))
}

pub(super) fn workspace_with_pipeline_contract() -> WorkspaceRecord {
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

pub(super) fn plan() -> WorkspacePlanRecord {
    WorkspacePlanRecord {
        id: "plan-test".to_string(),
        workspace_id: "workspace-test".to_string(),
        goal_id: "root-task".to_string(),
        status: "active".to_string(),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
    }
}

pub(super) fn plan_node() -> WorkspacePlanNodeRecord {
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

pub(super) fn task_session_attempt(
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

pub(super) fn worker_launch_handler(
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

pub(super) fn worker_launch_handler_with_state(
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

pub(super) fn worker_launch_handler_with_event_stream(
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

pub(super) fn worker_launch_handler_with_state_and_event_stream(
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

pub(super) fn worker_launch_item() -> WorkspacePlanOutboxRecord {
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

pub(super) fn pipeline_run_handler(
    store: Arc<FakeWorkspacePlanDispatchStore>,
) -> PipelineRunAdmissionHandler {
    PipelineRunAdmissionHandler::new(store as Arc<dyn WorkspacePlanDispatchStore>, None)
}

pub(super) fn pipeline_run_handler_with_stage_runner(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    stage_runner: Arc<dyn WorkspacePipelineStageRunner>,
) -> PipelineRunAdmissionHandler {
    PipelineRunAdmissionHandler::new(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        Some(stage_runner),
    )
}

pub(super) fn pipeline_run_item() -> WorkspacePlanOutboxRecord {
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

pub(super) fn pipeline_run_item_without_attempt() -> WorkspacePlanOutboxRecord {
    let mut item = pipeline_run_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.remove("attempt_id");
    }
    item
}

pub(super) fn pipeline_run_record(
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

pub(super) fn pipeline_stage_run_record(id: &str, run_id: &str) -> WorkspacePipelineStageRunRecord {
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

pub(super) fn supervisor_tick_handler(
    store: Arc<FakeWorkspacePlanDispatchStore>,
) -> SupervisorTickAdmissionHandler {
    SupervisorTickAdmissionHandler::new(store as Arc<dyn WorkspacePlanDispatchStore>)
}

pub(super) fn supervisor_tick_retry_item() -> WorkspacePlanOutboxRecord {
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
