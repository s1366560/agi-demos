use super::worker_launch_runtime::{
    NoopWorkerLaunchRuntimeStateStore, WorkerLaunchEventStream, WorkerLaunchRuntimeStateStore,
};
use super::worker_launch_worktree::{worker_launch_worktree_context, WorkerLaunchWorktreeContext};
use super::*;

mod admission;
mod stream;
mod terminal;

use stream::WorkerStreamReplayInput;

pub(crate) struct WorkerLaunchAdmissionConfig {
    pub max_active_worker_conversations: i64,
    pub defer_seconds: i64,
    pub active_event_grace_seconds: i64,
    pub stream_poll_interval_seconds: i64,
}

impl WorkerLaunchAdmissionConfig {
    fn from_env() -> Self {
        Self {
            max_active_worker_conversations: i64_env(
                WORKER_LAUNCH_MAX_ACTIVE_ENV,
                DEFAULT_WORKER_LAUNCH_MAX_ACTIVE,
            ),
            defer_seconds: positive_i64_env(
                WORKER_LAUNCH_DEFER_SECONDS_ENV,
                DEFAULT_WORKER_LAUNCH_DEFER_SECONDS,
            ),
            active_event_grace_seconds: positive_i64_env(
                WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS_ENV,
                DEFAULT_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS,
            ),
            stream_poll_interval_seconds: positive_i64_env(
                WORKER_STREAM_POLL_INTERVAL_SECONDS_ENV,
                DEFAULT_WORKER_STREAM_POLL_INTERVAL_SECONDS,
            ),
        }
    }
}

fn worker_conversation_scope_for_task(task_id: &str, attempt_id: Option<&str>) -> String {
    attempt_id
        .map(|attempt_id| format!("task:{task_id}:attempt:{attempt_id}"))
        .unwrap_or_else(|| format!("task:{task_id}"))
}

pub(crate) fn worker_conversation_id(
    workspace_id: &str,
    worker_agent_id: &str,
    task_id: &str,
    attempt_id: Option<&str>,
) -> String {
    let scope = worker_conversation_scope_for_task(task_id, attempt_id);
    let name = format!("workspace:{workspace_id}:agent:{worker_agent_id}:scope:{scope}");
    Uuid::new_v5(&Uuid::NAMESPACE_DNS, name.as_bytes()).to_string()
}

fn worker_conversation_title(task: &WorkspaceTaskRecord) -> String {
    let title_prefix = task.title.chars().take(80).collect::<String>();
    format!("Workspace Worker - {title_prefix}")
}

fn worker_conversation_metadata(
    workspace_id: &str,
    task: &WorkspaceTaskRecord,
    task_metadata: &Map<String, Value>,
    worker_agent_id: &str,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    now: DateTime<Utc>,
) -> Value {
    let mut metadata = json!({
        "workspace_id": workspace_id,
        "agent_id": worker_agent_id,
        "workspace_agent_binding_id": Value::Null,
        "workspace_task_id": task.id,
        "linked_workspace_task_id": task.id,
        ROOT_GOAL_TASK_ID: attempt.root_goal_task_id,
        "attempt_id": attempt.id,
        "conversation_scope": worker_conversation_scope_for_task(&task.id, Some(&attempt.id)),
        "source": WORKER_LAUNCH_CONVERSATION_SOURCE,
        "workspace_llm_stage": WORKER_LAUNCH_CONVERSATION_STAGE,
        "created_at": now.to_rfc3339(),
    });
    if let Some(preferred_language) = string_from_map(task_metadata, "preferred_language") {
        if let Some(map) = metadata.as_object_mut() {
            map.insert("preferred_language".to_string(), json!(preferred_language));
        }
    }
    if let Some(map) = metadata.as_object_mut() {
        for key in [
            "last_retry_reason",
            "last_retry_previous_attempt_id",
            "retry_origin",
            "worker_stream_orphan_retry_reason",
            "worker_stream_orphan_summary",
        ] {
            copy_metadata_string_field(task_metadata, map, key);
        }
    }
    metadata
}

pub(crate) struct WorkerLaunchAdmissionHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
    runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
    stream_events: Arc<dyn WorkerLaunchEventStream>,
    config: WorkerLaunchAdmissionConfig,
}

impl WorkerLaunchAdmissionHandler {
    pub(crate) fn with_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
    ) -> Self {
        Self::with_runtime_state_and_event_stream(
            store,
            Arc::new(NoopWorkerLaunchRuntimeStateStore),
            stream_events,
        )
    }

    pub(crate) fn with_runtime_state_and_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
    ) -> Self {
        Self {
            store,
            runtime_state,
            stream_events,
            config: WorkerLaunchAdmissionConfig::from_env(),
        }
    }

    #[cfg(test)]
    pub(super) fn with_config(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state: Arc::new(NoopWorkerLaunchRuntimeStateStore),
            stream_events: Arc::new(NoopWorkerLaunchEventStream),
            config,
        }
    }

    #[cfg(test)]
    pub(super) fn with_config_and_runtime_state(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state,
            stream_events: Arc::new(NoopWorkerLaunchEventStream),
            config,
        }
    }

    #[cfg(test)]
    pub(super) fn with_config_and_runtime_state_and_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state,
            stream_events,
            config,
        }
    }

    #[cfg(test)]
    pub(super) fn with_config_and_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state: Arc::new(NoopWorkerLaunchRuntimeStateStore),
            stream_events,
            config,
        }
    }
}

#[async_trait]
impl WorkspacePlanOutboxHandler for WorkerLaunchAdmissionHandler {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let payload = object_or_empty(item.payload_json.clone());
        let workspace_id =
            string_from_map(&payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let task_id = required_string(&payload, "task_id")?;
        let actor_user_id = required_string(&payload, "actor_user_id")?;
        let leader_agent_id = string_from_map(&payload, "leader_agent_id")
            .unwrap_or_else(|| WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string());
        let mut task = self
            .store
            .get_task(&workspace_id, &task_id)
            .await?
            .ok_or_else(|| {
                CoreError::Storage(format!(
                    "workspace task {task_id} not found for workspace {workspace_id}"
                ))
            })?;
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        let worker_agent_id = string_from_map(&payload, "worker_agent_id")
            .or_else(|| task.assignee_agent_id.clone())
            .ok_or_else(|| {
                CoreError::Storage(format!("workspace task {task_id} has no worker agent"))
            })?;
        let plan_id = item
            .plan_id
            .clone()
            .or_else(|| string_from_map(&payload, "plan_id"))
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_ID));
        let node_id = string_from_map(&payload, "node_id")
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_NODE_ID));
        let attempt_id = string_from_map(&payload, "attempt_id");
        let is_stream_poll = bool_from_map(&payload, "worker_stream_poll");

        if self
            .stale_worker_launch_reason(
                &task,
                plan_id.as_deref(),
                node_id.as_deref(),
                attempt_id.as_deref(),
            )
            .await?
            .is_some()
        {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        if !is_stream_poll {
            if let Some(active_count) = self
                .defer_active_capacity_count(&workspace_id, attempt_id.as_deref())
                .await?
            {
                self.store
                    .enqueue_plan_outbox(deferred_worker_launch_outbox(
                        &item,
                        &payload,
                        active_count,
                        self.config.max_active_worker_conversations,
                        self.config.defer_seconds,
                        Utc::now(),
                    ))
                    .await?;
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
        }

        let workspace = self
            .store
            .get_workspace(&workspace_id)
            .await?
            .ok_or_else(|| {
                CoreError::Storage(format!(
                    "workspace {workspace_id} not found for worker launch"
                ))
            })?;
        let launch_node = self
            .load_launch_node(plan_id.as_deref(), node_id.as_deref())
            .await?;
        let worktree_context = if is_stream_poll {
            None
        } else {
            worker_launch_worktree_context(
                Some(&workspace),
                &task,
                launch_node.as_ref(),
                attempt_id.as_deref(),
            )
            .await?
        };
        let now = Utc::now();
        if let Some(context) = worktree_context.as_ref() {
            merge_metadata_patch(&mut task_metadata, &context.metadata_patch);
            if context.setup_failed {
                self.block_task_for_worktree_setup_failure(
                    task,
                    task_metadata,
                    launch_node,
                    attempt_id.as_deref(),
                    context,
                    now,
                )
                .await?;
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
        }

        let mut bound_attempt = None;
        let mut current_attempt_conversation_id = None;
        if let Some(attempt_id) = attempt_id.as_deref() {
            let attempt = self
                .store
                .get_task_session_attempt(attempt_id)
                .await?
                .ok_or_else(|| {
                    CoreError::Storage(format!(
                        "workspace task session attempt {attempt_id} not found"
                    ))
                })?;
            let reuse_conversation_id = string_from_map(&payload, "reuse_conversation_id");
            let conversation_id = reuse_conversation_id
                .clone()
                .or_else(|| attempt.conversation_id.clone())
                .unwrap_or_else(|| {
                    worker_conversation_id(
                        &workspace_id,
                        &worker_agent_id,
                        &task.id,
                        Some(attempt_id),
                    )
                });
            if reuse_conversation_id.is_some()
                && self.runtime_agent_running_exists(&conversation_id).await
            {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
            if reuse_conversation_id.is_some() {
                self.runtime_clear_reused_session_markers(&conversation_id)
                    .await;
            }
            if !is_stream_poll && !self.runtime_claim_launch_cooldown(&conversation_id).await {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
            apply_attempt_retry_context(&mut task_metadata, &payload, now);
            let agent_config = json!({
                "selected_agent_id": worker_agent_id,
                "agent_definition_id": worker_agent_id,
            });
            let conversation_metadata = worker_conversation_metadata(
                &workspace_id,
                &task,
                &task_metadata,
                &worker_agent_id,
                &attempt,
                now,
            );
            let participant_agents = vec![worker_agent_id.clone()];
            self.store
                .ensure_worker_launch_conversation(
                    &conversation_id,
                    &workspace.project_id,
                    &workspace.tenant_id,
                    &actor_user_id,
                    &worker_conversation_title(&task),
                    &agent_config,
                    &conversation_metadata,
                    &participant_agents,
                    &worker_agent_id,
                    &workspace_id,
                    &task.id,
                    now,
                )
                .await?;
            let attempt = self
                .store
                .bind_task_session_attempt_conversation(attempt_id, &conversation_id, now)
                .await?
                .ok_or_else(|| {
                    CoreError::Storage(format!(
                        "workspace task session attempt {attempt_id} not found"
                    ))
                })?;
            self.runtime_refresh_bound_session_markers(&conversation_id)
                .await;
            current_attempt_conversation_id = Some(conversation_id);
            bound_attempt = Some(attempt);
        }

        let launch_state = if is_stream_poll && current_attempt_conversation_id.is_some() {
            "stream_polling"
        } else if current_attempt_conversation_id.is_some() {
            "bound"
        } else {
            "runtime_admitted"
        };
        task_metadata.insert("launch_state".to_string(), json!(launch_state));
        task_metadata.insert(
            "worker_launch_admitted_at".to_string(),
            json!(now.to_rfc3339()),
        );
        if current_attempt_conversation_id.is_some() {
            task_metadata.insert(
                "worker_launch_bound_at".to_string(),
                json!(now.to_rfc3339()),
            );
        }
        task_metadata.insert(
            "worker_launch_admitted_by".to_string(),
            json!(leader_agent_id.clone()),
        );
        task_metadata.insert(
            "current_attempt_worker_agent_id".to_string(),
            json!(worker_agent_id),
        );
        task_metadata.insert(CURRENT_ATTEMPT_WORKER_BINDING_ID.to_string(), Value::Null);
        if let Some(attempt) = bound_attempt.as_ref() {
            task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt.id.clone()));
            task_metadata.insert(
                "current_attempt_number".to_string(),
                json!(attempt.attempt_number),
            );
            if let Some(conversation_id) = current_attempt_conversation_id.as_deref() {
                task_metadata.insert(
                    CURRENT_ATTEMPT_CONVERSATION_ID.to_string(),
                    json!(conversation_id),
                );
            }
        } else if let Some(attempt_id) = attempt_id.as_deref() {
            task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        task_metadata.insert(
            "execution_state".to_string(),
            json!({
                "phase": "in_progress",
                "last_agent_reason": if current_attempt_conversation_id.is_some() {
                    "workspace_worker_launch.bind_conversation"
                } else {
                    "workspace_plan.worker_launch.admitted"
                },
                "last_agent_action": "schedule",
                "updated_by_actor_type": "agent",
                "updated_by_actor_id": task_metadata
                    .get("worker_launch_admitted_by")
                    .and_then(Value::as_str)
                    .unwrap_or(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
                "actor_user_id": actor_user_id,
                "updated_at": now.to_rfc3339()
            }),
        );
        task.metadata_json = Value::Object(task_metadata);
        if task.status != "done" {
            task.status = "in_progress".to_string();
            task.completed_at = None;
        }
        task.updated_at = Some(now);
        self.store.save_task(task).await?;

        self.mark_plan_node_running_after_launch_schedule(
            plan_id.as_deref(),
            node_id.as_deref(),
            attempt_id.as_deref(),
            current_attempt_conversation_id.as_deref(),
            launch_state,
            now,
        )
        .await?;

        if let (Some(conversation_id), Some(attempt_id)) = (
            current_attempt_conversation_id.as_deref(),
            attempt_id.as_deref(),
        ) {
            let stream_after_id = string_from_map(&payload, "stream_after_id")
                .or_else(|| string_from_map(&payload, "worker_stream_after_id"));
            let root_goal_task_id = string_from_map(&payload, ROOT_GOAL_TASK_ID);
            let replay = self
                .replay_bound_worker_stream_once(WorkerStreamReplayInput {
                    workspace_id: &workspace_id,
                    task_id: &task_id,
                    root_goal_task_id: root_goal_task_id.as_deref(),
                    attempt_id,
                    conversation_id,
                    actor_user_id: &actor_user_id,
                    worker_agent_id: &worker_agent_id,
                    leader_agent_id: Some(&leader_agent_id),
                    plan_id: plan_id.as_deref(),
                    node_id: node_id.as_deref(),
                    stream_after_id: stream_after_id.as_deref(),
                    now,
                })
                .await?;
            self.enqueue_worker_stream_poll_if_needed(
                &item,
                &payload,
                &replay,
                conversation_id,
                now,
            )
            .await?;
        }

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

pub(super) struct WorkerStreamTerminalPersistence<'a> {
    pub(super) workspace_id: &'a str,
    pub(super) task_id: &'a str,
    pub(super) root_goal_task_id: Option<&'a str>,
    pub(super) attempt_id: Option<&'a str>,
    pub(super) conversation_id: Option<&'a str>,
    pub(super) actor_user_id: &'a str,
    pub(super) worker_agent_id: &'a str,
    pub(super) leader_agent_id: Option<&'a str>,
    pub(super) plan_id: Option<&'a str>,
    pub(super) node_id: Option<&'a str>,
    pub(super) outcome: &'a worker_stream_watchdog::TerminalOutcome,
    pub(super) now: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub(super) struct WorkerReportPayload {
    pub(super) normalized_summary: String,
    pub(super) report_artifacts: Vec<String>,
    pub(super) merged_artifacts: Vec<String>,
    pub(super) report_verifications: Vec<String>,
    pub(super) merged_verifications: Vec<String>,
    pub(super) fingerprint: String,
}

#[allow(clippy::too_many_arguments)]
pub(super) fn worker_launch_outbox(
    plan_id: Option<&str>,
    workspace_id: &str,
    source_event_type: &str,
    payload: &Map<String, Value>,
    task_id: &str,
    worker_agent_id: &str,
    actor_user_id: &str,
    leader_agent_id: &str,
    attempt_id: &str,
    node_id: Option<&str>,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut launch_payload = Map::new();
    launch_payload.insert("workspace_id".to_string(), json!(workspace_id));
    launch_payload.insert("task_id".to_string(), json!(task_id));
    launch_payload.insert("worker_agent_id".to_string(), json!(worker_agent_id));
    launch_payload.insert("actor_user_id".to_string(), json!(actor_user_id));
    launch_payload.insert("leader_agent_id".to_string(), json!(leader_agent_id));
    launch_payload.insert("attempt_id".to_string(), json!(attempt_id));
    if let Some(node_id) = node_id {
        launch_payload.insert("node_id".to_string(), json!(node_id));
    }
    for optional_key in [
        "extra_instructions",
        "reuse_conversation_id",
        "repair_brief_prompt",
    ] {
        if let Some(value) = payload.get(optional_key) {
            launch_payload.insert(optional_key.to_string(), value.clone());
        }
    }
    copy_retry_context_payload_fields(payload, &mut launch_payload);
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: plan_id.map(ToOwned::to_owned),
        workspace_id: workspace_id.to_string(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(launch_payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": format!("workspace_plan.{source_event_type}"),
            "previous_attempt_id": string_from_map(payload, "previous_attempt_id")
        }),
        created_at,
        updated_at: None,
    }
}

fn deferred_worker_launch_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    active_count: i64,
    max_active: i64,
    delay_seconds: i64,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut metadata = object_or_empty(item.metadata_json.clone());
    let defer_count = metadata
        .get("defer_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "source".to_string(),
        json!("workspace_plan.worker_launch.deferred_capacity"),
    );
    metadata.insert(
        "deferred_from_outbox_id".to_string(),
        json!(item.id.clone()),
    );
    metadata.insert("defer_count".to_string(), json!(defer_count));
    metadata.insert(
        "active_worker_conversations".to_string(),
        json!(active_count),
    );
    metadata.insert(
        "max_active_worker_conversations".to_string(),
        json!(max_active),
    );
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: item.plan_id.clone(),
        workspace_id: item.workspace_id.clone(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(payload.clone()),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: item.max_attempts,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: Some(now + ChronoDuration::seconds(delay_seconds.max(1))),
        processed_at: None,
        metadata_json: Value::Object(metadata),
        created_at: now,
        updated_at: None,
    }
}
