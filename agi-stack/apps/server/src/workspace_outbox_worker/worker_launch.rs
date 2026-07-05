use super::worker_launch_runtime::{
    NoopWorkerLaunchRuntimeStateStore, WorkerLaunchEventStream, WorkerLaunchRuntimeStateStore,
};
use super::worker_launch_worktree::{worker_launch_worktree_context, WorkerLaunchWorktreeContext};
use super::*;

mod admission;
mod conversation;
mod outbox;
mod stream;
mod terminal;

pub(crate) use conversation::worker_conversation_id;
use conversation::{worker_conversation_metadata, worker_conversation_title};
use outbox::deferred_worker_launch_outbox;
pub(super) use outbox::{
    worker_launch_outbox, WorkerReportPayload, WorkerStreamTerminalPersistence,
};
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
