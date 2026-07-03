use super::*;

#[async_trait]
pub(crate) trait WorkerLaunchRuntimeStateStore: Send + Sync {
    async fn claim_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool>;

    async fn refresh_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool>;

    async fn agent_finished_message_id(&self, conversation_id: &str) -> CoreResult<Option<String>>;

    async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool>;

    async fn refresh_agent_running_marker(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool>;

    async fn clear_reused_session_markers(&self, conversation_id: &str) -> CoreResult<()>;
}

#[derive(Debug, Default)]
struct NoopWorkerLaunchRuntimeStateStore;

#[async_trait]
impl WorkerLaunchRuntimeStateStore for NoopWorkerLaunchRuntimeStateStore {
    async fn claim_launch_cooldown(
        &self,
        _conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        Ok(true)
    }

    async fn refresh_launch_cooldown(
        &self,
        _conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        Ok(false)
    }

    async fn agent_finished_message_id(
        &self,
        _conversation_id: &str,
    ) -> CoreResult<Option<String>> {
        Ok(None)
    }

    async fn agent_running_exists(&self, _conversation_id: &str) -> CoreResult<bool> {
        Ok(false)
    }

    async fn refresh_agent_running_marker(
        &self,
        _conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        Ok(false)
    }

    async fn clear_reused_session_markers(&self, _conversation_id: &str) -> CoreResult<()> {
        Ok(())
    }
}

#[async_trait]
impl WorkerLaunchRuntimeStateStore for agistack_adapters_redis::RedisWorkerLaunchStateStore {
    async fn claim_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.claim_worker_launch_cooldown(conversation_id, ttl_seconds)
            .await
    }

    async fn refresh_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.refresh_worker_launch_cooldown(conversation_id, ttl_seconds)
            .await
    }

    async fn agent_finished_message_id(&self, conversation_id: &str) -> CoreResult<Option<String>> {
        self.agent_finished_message_id(conversation_id).await
    }

    async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool> {
        self.agent_running_exists(conversation_id).await
    }

    async fn refresh_agent_running_marker(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.refresh_existing_agent_running_marker(conversation_id, ttl_seconds)
            .await
    }

    async fn clear_reused_session_markers(&self, conversation_id: &str) -> CoreResult<()> {
        self.clear_reused_worker_session_markers(conversation_id)
            .await
    }
}

#[async_trait]
pub(crate) trait WorkerLaunchEventStream: Send + Sync {
    async fn read_after(
        &self,
        conversation_id: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>>;
}

#[derive(Debug, Default)]
pub(super) struct NoopWorkerLaunchEventStream;

#[async_trait]
impl WorkerLaunchEventStream for NoopWorkerLaunchEventStream {
    async fn read_after(
        &self,
        _conversation_id: &str,
        _after_id: &str,
        _limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        Ok(Vec::new())
    }
}

struct EventStreamWorkerLaunchEventSource {
    events: Arc<dyn EventStream>,
}

#[async_trait]
impl WorkerLaunchEventStream for EventStreamWorkerLaunchEventSource {
    async fn read_after(
        &self,
        conversation_id: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        self.events
            .read_after(&worker_stream_topic(conversation_id), after_id, limit)
            .await
    }
}

pub(crate) fn worker_launch_event_stream_source(
    events: Arc<dyn EventStream>,
) -> Arc<dyn WorkerLaunchEventStream> {
    Arc::new(EventStreamWorkerLaunchEventSource { events })
}

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

fn worker_stream_topic(conversation_id: &str) -> String {
    format!("agent:events:{conversation_id}")
}

fn worker_stream_event_time_us(event: &Value) -> Option<i64> {
    event
        .get("event_time_us")
        .and_then(Value::as_i64)
        .or_else(|| {
            event
                .get("event_time_us")
                .and_then(Value::as_u64)
                .and_then(|value| i64::try_from(value).ok())
        })
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
    #[allow(dead_code)]
    pub(crate) fn new(store: Arc<dyn WorkspacePlanDispatchStore>) -> Self {
        Self::with_runtime_state_and_event_stream(
            store,
            Arc::new(NoopWorkerLaunchRuntimeStateStore),
            Arc::new(NoopWorkerLaunchEventStream),
        )
    }

    #[allow(dead_code)]
    pub(crate) fn with_runtime_state(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
    ) -> Self {
        Self::with_runtime_state_and_event_stream(
            store,
            runtime_state,
            Arc::new(NoopWorkerLaunchEventStream),
        )
    }

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

#[allow(dead_code)]
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

struct WorkerStreamReplayInput<'a> {
    workspace_id: &'a str,
    task_id: &'a str,
    root_goal_task_id: Option<&'a str>,
    attempt_id: &'a str,
    conversation_id: &'a str,
    actor_user_id: &'a str,
    worker_agent_id: &'a str,
    leader_agent_id: Option<&'a str>,
    plan_id: Option<&'a str>,
    node_id: Option<&'a str>,
    stream_after_id: Option<&'a str>,
    now: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct WorkerStreamReplayResult {
    replay_after_id: String,
    last_entry_id: Option<String>,
    entries_read: usize,
    terminal_seen: bool,
}

impl WorkerStreamReplayResult {
    fn empty(replay_after_id: String) -> Self {
        Self {
            replay_after_id,
            last_entry_id: None,
            entries_read: 0,
            terminal_seen: false,
        }
    }

    fn next_after_id(&self) -> &str {
        self.last_entry_id
            .as_deref()
            .unwrap_or(&self.replay_after_id)
    }

    fn is_nonterminal(&self) -> bool {
        !self.terminal_seen
    }
}

struct WorkerStreamIdleProgress {
    summary: String,
    idle_seconds: i64,
    running_exists: bool,
    finished_message_id: Option<String>,
}

#[allow(dead_code)]
#[derive(Debug, Clone)]
pub(super) struct WorkerReportPayload {
    pub(super) normalized_summary: String,
    pub(super) report_artifacts: Vec<String>,
    pub(super) merged_artifacts: Vec<String>,
    pub(super) report_verifications: Vec<String>,
    pub(super) merged_verifications: Vec<String>,
    pub(super) fingerprint: String,
}

impl WorkerLaunchAdmissionHandler {
    async fn replay_bound_worker_stream_once(
        &self,
        input: WorkerStreamReplayInput<'_>,
    ) -> CoreResult<WorkerStreamReplayResult> {
        let stream_after_id = self.worker_stream_replay_after_id(&input).await?;
        let (mut state, mut last_event_time_us) = self
            .worker_stream_state_from_replay_metadata(&input)
            .await?;
        let entries = self
            .stream_events
            .read_after(
                input.conversation_id,
                &stream_after_id,
                DEFAULT_WORKER_STREAM_REPLAY_BATCH_LIMIT,
            )
            .await?;
        if entries.is_empty() {
            if self
                .stop_orphaned_worker_stream_if_needed(&input, &mut state, None, last_event_time_us)
                .await?
            {
                return Ok(WorkerStreamReplayResult {
                    replay_after_id: stream_after_id,
                    last_entry_id: None,
                    entries_read: 0,
                    terminal_seen: true,
                });
            }
            return Ok(WorkerStreamReplayResult::empty(stream_after_id));
        }

        let mut last_entry_id = None;
        let mut terminal_seen = false;
        let mut entries_read = 0;
        for entry in entries {
            entries_read += 1;
            last_entry_id = Some(entry.id.clone());
            let event = match serde_json::from_str::<Value>(&entry.payload) {
                Ok(event) => event,
                Err(err) => json!({
                    "type": "error",
                    "data": {
                        "message": format!(
                            "Malformed worker stream payload at {}: {err}",
                            entry.id
                        )
                    }
                }),
            };
            if let Some(event_time_us) = worker_stream_event_time_us(&event) {
                last_event_time_us = Some(event_time_us);
            }
            if state.observe_event(&event).is_some() {
                terminal_seen = true;
                break;
            }
        }

        let last_entry_id = last_entry_id.as_deref();
        if !terminal_seen {
            if self
                .stop_orphaned_worker_stream_if_needed(
                    &input,
                    &mut state,
                    last_entry_id,
                    last_event_time_us,
                )
                .await?
            {
                return Ok(WorkerStreamReplayResult {
                    replay_after_id: stream_after_id,
                    last_entry_id: last_entry_id.map(ToOwned::to_owned),
                    entries_read,
                    terminal_seen: true,
                });
            }
            self.patch_worker_stream_replay_metadata(
                &input,
                last_entry_id,
                last_event_time_us,
                &state,
                None,
            )
            .await?;
            return Ok(WorkerStreamReplayResult {
                replay_after_id: stream_after_id,
                last_entry_id: last_entry_id.map(ToOwned::to_owned),
                entries_read,
                terminal_seen: false,
            });
        }

        self.persist_worker_stream_replay_terminal_outcome(
            &input,
            &state,
            last_entry_id,
            last_event_time_us,
        )
        .await?;
        Ok(WorkerStreamReplayResult {
            replay_after_id: stream_after_id,
            last_entry_id: last_entry_id.map(ToOwned::to_owned),
            entries_read,
            terminal_seen: true,
        })
    }

    async fn worker_stream_state_from_replay_metadata(
        &self,
        input: &WorkerStreamReplayInput<'_>,
    ) -> CoreResult<(worker_stream_watchdog::StreamState, Option<i64>)> {
        let Some(task) = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
        else {
            return Ok((worker_stream_watchdog::StreamState::default(), None));
        };
        let metadata = object_or_empty(task.metadata_json);
        if !worker_stream_replay_metadata_matches_attempt(&metadata, input.attempt_id) {
            return Ok((worker_stream_watchdog::StreamState::default(), None));
        }
        let mut state = worker_stream_watchdog::StreamState::default();
        state.stream_message_id = string_from_map(&metadata, "worker_stream_message_id");
        state.last_stream_event_type = string_from_map(&metadata, "worker_stream_last_event_type");
        let last_event_time_us = metadata
            .get("worker_stream_last_event_time_us")
            .and_then(Value::as_i64);
        Ok((state, last_event_time_us))
    }

    async fn stop_orphaned_worker_stream_if_needed(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        state: &mut worker_stream_watchdog::StreamState,
        last_entry_id: Option<&str>,
        last_event_time_us: Option<i64>,
    ) -> CoreResult<bool> {
        let finished_message_id = self
            .runtime_agent_finished_message_id(input.conversation_id)
            .await;
        let running_exists = self
            .runtime_agent_running_exists(input.conversation_id)
            .await;
        let idle_seconds = last_event_time_us
            .filter(|event_time_us| input.now.timestamp_micros() > *event_time_us)
            .map(|event_time_us| {
                (input.now.timestamp_micros() - event_time_us) as f64 / 1_000_000.0
            })
            .unwrap_or_default();
        let decision = worker_stream_watchdog::should_stop(
            finished_message_id.as_deref(),
            state.stream_message_id.as_deref(),
            running_exists,
            idle_seconds,
            None,
        );
        if !decision.should_stop {
            return Ok(false);
        }
        state.mark_orphaned_stream_stop(
            decision
                .reason
                .map(worker_stream_watchdog::StopReason::as_str),
        );
        self.persist_worker_stream_replay_terminal_outcome(
            input,
            state,
            last_entry_id,
            last_event_time_us,
        )
        .await?;
        Ok(true)
    }

    async fn persist_worker_stream_replay_terminal_outcome(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        state: &worker_stream_watchdog::StreamState,
        last_entry_id: Option<&str>,
        last_event_time_us: Option<i64>,
    ) -> CoreResult<()> {
        let report_recorded_for_attempt = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
            .map(|task| {
                worker_stream_watchdog::terminal_report_metadata_matches_attempt(
                    Some(&task.metadata_json),
                    Some(input.attempt_id),
                    None,
                )
            })
            .unwrap_or(false);
        let outcome = state.terminal_outcome(report_recorded_for_attempt);
        self.persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
            workspace_id: input.workspace_id,
            task_id: input.task_id,
            root_goal_task_id: input.root_goal_task_id,
            attempt_id: Some(input.attempt_id),
            conversation_id: Some(input.conversation_id),
            actor_user_id: input.actor_user_id,
            worker_agent_id: input.worker_agent_id,
            leader_agent_id: input.leader_agent_id,
            plan_id: input.plan_id,
            node_id: input.node_id,
            outcome: &outcome,
            now: input.now,
        })
        .await?;
        self.patch_worker_stream_replay_metadata(
            &input,
            last_entry_id,
            last_event_time_us,
            &state,
            Some(&outcome),
        )
        .await?;
        Ok(())
    }

    async fn enqueue_worker_stream_poll_if_needed(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        replay: &WorkerStreamReplayResult,
        conversation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        if !replay.is_nonterminal() {
            return Ok(());
        }
        if self
            .runtime_agent_finished_message_id(conversation_id)
            .await
            .is_some()
        {
            return Ok(());
        }
        let running_exists = self.runtime_agent_running_exists(conversation_id).await;
        if !running_exists && replay.entries_read == 0 {
            return Ok(());
        }
        self.store
            .enqueue_plan_outbox(worker_stream_poll_outbox(
                item,
                payload,
                conversation_id,
                replay,
                self.config.stream_poll_interval_seconds,
                now,
            ))
            .await?;
        Ok(())
    }

    async fn worker_stream_replay_after_id(
        &self,
        input: &WorkerStreamReplayInput<'_>,
    ) -> CoreResult<String> {
        if let Some(after_id) = input
            .stream_after_id
            .filter(|value| !value.trim().is_empty())
        {
            return Ok(after_id.to_string());
        }
        let after_id = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
            .and_then(|task| {
                let metadata = object_or_empty(task.metadata_json);
                if !worker_stream_replay_metadata_matches_attempt(&metadata, input.attempt_id) {
                    return None;
                }
                metadata
                    .get("worker_stream_last_entry_id")
                    .and_then(Value::as_str)
                    .filter(|value| !value.trim().is_empty())
                    .map(ToOwned::to_owned)
            })
            .unwrap_or_default();
        Ok(after_id)
    }

    async fn patch_worker_stream_replay_metadata(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        last_entry_id: Option<&str>,
        last_event_time_us: Option<i64>,
        state: &worker_stream_watchdog::StreamState,
        outcome: Option<&worker_stream_watchdog::TerminalOutcome>,
    ) -> CoreResult<()> {
        let Some(mut task) = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
        else {
            return Ok(());
        };
        let mut metadata = object_or_empty(task.metadata_json.clone());
        let idle_progress = if outcome.is_none() {
            self.worker_stream_idle_progress(input, state, last_event_time_us, &metadata)
                .await
        } else {
            None
        };
        if let Some(last_entry_id) = last_entry_id {
            metadata.insert(
                "worker_stream_last_entry_id".to_string(),
                json!(last_entry_id),
            );
        }
        if let Some(last_event_time_us) = last_event_time_us {
            metadata.insert(
                "worker_stream_last_event_time_us".to_string(),
                json!(last_event_time_us),
            );
        }
        metadata.insert(
            "worker_stream_last_replayed_at".to_string(),
            json!(input.now.to_rfc3339()),
        );
        metadata.insert(
            "worker_stream_replay_status".to_string(),
            json!(if outcome.is_some() {
                "terminal"
            } else if idle_progress.is_some() {
                "stream_idle"
            } else {
                "observed"
            }),
        );
        metadata.insert(
            "worker_stream_replay_attempt_id".to_string(),
            json!(input.attempt_id),
        );
        if let Some(last_event_type) = state
            .last_stream_event_type
            .as_deref()
            .filter(|value| !value.trim().is_empty())
        {
            metadata.insert(
                "worker_stream_last_event_type".to_string(),
                json!(last_event_type),
            );
        }
        if let Some(message_id) = state
            .stream_message_id
            .as_deref()
            .filter(|value| !value.trim().is_empty())
        {
            metadata.insert("worker_stream_message_id".to_string(), json!(message_id));
        }
        if let Some(outcome) = outcome {
            metadata.insert(
                "worker_stream_terminal_outcome".to_string(),
                json!(outcome.outcome_reason),
            );
            metadata.insert(
                "worker_stream_terminal_launch_state".to_string(),
                json!(outcome.launch_state),
            );
            metadata.insert(
                "worker_stream_terminal_should_report".to_string(),
                json!(outcome.should_report),
            );
            metadata.insert(
                "worker_stream_terminal_replayed_at".to_string(),
                json!(input.now.to_rfc3339()),
            );
        }
        if let Some(progress) = idle_progress.as_ref() {
            metadata.insert(
                "worker_stream_idle_progress_summary".to_string(),
                json!(progress.summary.clone()),
            );
            metadata.insert(
                "worker_stream_idle_seconds".to_string(),
                json!(progress.idle_seconds),
            );
            metadata.insert(
                "worker_stream_idle_progress_published_at".to_string(),
                json!(input.now.to_rfc3339()),
            );
            metadata.insert(
                "worker_stream_idle_progress_published_at_us".to_string(),
                json!(input.now.timestamp_micros()),
            );
            metadata.insert(
                "worker_stream_idle_running_exists".to_string(),
                json!(progress.running_exists),
            );
            if let Some(finished_message_id) = progress.finished_message_id.as_deref() {
                metadata.insert(
                    "worker_stream_idle_finished_message_id".to_string(),
                    json!(finished_message_id),
                );
            }
            metadata.insert(
                "execution_state".to_string(),
                worker_execution_state(
                    "in_progress",
                    &progress.summary,
                    "observe_stream_idle",
                    input.leader_agent_id.unwrap_or(input.actor_user_id),
                    input.now,
                ),
            );
        }
        task.metadata_json = Value::Object(metadata);
        task.updated_at = Some(input.now);
        self.store.save_task(task).await?;
        if let Some(progress) = idle_progress.as_ref() {
            self.mark_workspace_plan_node_stream_idle(input, progress)
                .await?;
        }
        Ok(())
    }

    async fn worker_stream_idle_progress(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        state: &worker_stream_watchdog::StreamState,
        last_event_time_us: Option<i64>,
        metadata: &Map<String, Value>,
    ) -> Option<WorkerStreamIdleProgress> {
        let last_event_time_us = last_event_time_us?;
        let now_us = input.now.timestamp_micros();
        if now_us <= last_event_time_us {
            return None;
        }
        let idle_seconds = (now_us - last_event_time_us) as f64 / 1_000_000.0;
        let last_published_at = metadata
            .get("worker_stream_idle_progress_published_at_us")
            .and_then(Value::as_i64)
            .map(|value| value as f64 / 1_000_000.0)
            .unwrap_or_default();
        let now_seconds = now_us as f64 / 1_000_000.0;
        if !worker_stream_watchdog::should_publish_idle_progress(
            idle_seconds,
            last_published_at,
            now_seconds,
            None,
        ) {
            return None;
        }
        let finished_message_id = self
            .runtime_agent_finished_message_id(input.conversation_id)
            .await;
        let running_exists = self
            .runtime_agent_running_exists(input.conversation_id)
            .await;
        let summary = worker_stream_watchdog::idle_progress_summary(
            idle_seconds,
            state.last_stream_event_type.as_deref(),
            running_exists,
            finished_message_id.as_deref(),
        );
        Some(WorkerStreamIdleProgress {
            summary,
            idle_seconds: idle_seconds as i64,
            running_exists,
            finished_message_id,
        })
    }

    async fn mark_workspace_plan_node_stream_idle(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        progress: &WorkerStreamIdleProgress,
    ) -> CoreResult<()> {
        let (Some(plan_id), Some(node_id)) = (input.plan_id, input.node_id) else {
            return Ok(());
        };
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(());
        };
        if node.current_attempt_id.as_deref() != Some(input.attempt_id) {
            return Ok(());
        }
        if node.execution != "running" {
            return Ok(());
        }

        let mut progress_json = object_or_empty(node.progress_json.clone());
        progress_json
            .entry("percent".to_string())
            .or_insert_with(|| json!(0.0));
        progress_json
            .entry("confidence".to_string())
            .or_insert_with(|| json!(1.0));
        progress_json.insert("note".to_string(), json!(progress.summary.clone()));

        let mut metadata = object_or_empty(node.metadata_json.clone());
        let reported_at = input.now.to_rfc3339();
        let progress_event = json!({
            "event_type": "worker_stream_idle",
            "source_event_type": "worker_stream_idle",
            "summary": progress.summary.clone(),
            "attempt_id": input.attempt_id,
            "worker_agent_id": input.worker_agent_id,
            "idle_seconds": progress.idle_seconds,
            "running_exists": progress.running_exists,
            "reported_at": reported_at.clone()
        });
        let mut progress_events = metadata
            .get("progress_events")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        progress_events.push(progress_event.clone());
        if progress_events.len() > 25 {
            progress_events = progress_events.split_off(progress_events.len() - 25);
        }
        metadata.insert("progress_events".to_string(), Value::Array(progress_events));
        metadata.insert("latest_worker_progress".to_string(), progress_event);
        metadata.insert("launch_state".to_string(), json!("stream_idle"));
        metadata.insert(
            "worker_stream_idle_progress_summary".to_string(),
            json!(progress.summary.clone()),
        );
        metadata.insert(
            "worker_stream_idle_progress_published_at".to_string(),
            json!(reported_at),
        );

        node.intent = "in_progress".to_string();
        node.progress_json = Value::Object(progress_json);
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(input.now);
        self.store.save_plan_node(node).await?;
        Ok(())
    }

    #[allow(dead_code)]
    pub(super) async fn persist_worker_stream_terminal_outcome(
        &self,
        input: WorkerStreamTerminalPersistence<'_>,
    ) -> CoreResult<bool> {
        let Some(mut task) = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
        else {
            return Ok(false);
        };
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        let root_goal_task_id = input
            .root_goal_task_id
            .map(ToOwned::to_owned)
            .or_else(|| string_from_map(&task_metadata, ROOT_GOAL_TASK_ID));
        if let (Some(expected), Some(actual)) = (
            input.root_goal_task_id,
            string_from_map(&task_metadata, ROOT_GOAL_TASK_ID),
        ) {
            if actual != expected {
                return Err(CoreError::Storage(
                    "worker stream terminal report task does not belong to root goal".into(),
                ));
            }
        }
        let plan_id = input
            .plan_id
            .map(ToOwned::to_owned)
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_ID));
        let node_id = input
            .node_id
            .map(ToOwned::to_owned)
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_NODE_ID));
        let v2_plan_linked = plan_id
            .as_deref()
            .is_some_and(|value| !value.trim().is_empty())
            && node_id
                .as_deref()
                .is_some_and(|value| !value.trim().is_empty());

        task_metadata.insert(
            "launch_state".to_string(),
            json!(input.outcome.launch_state),
        );

        let mut reported = false;
        if input.outcome.should_report {
            if let (Some(attempt_id), Some(report_type)) =
                (input.attempt_id, input.outcome.report_type.as_ref())
            {
                if !is_stale_terminal_worker_report(&task_metadata, attempt_id) {
                    let report_type = report_type.as_str();
                    let report = build_worker_report_payload(
                        &task_metadata,
                        report_type,
                        &input.outcome.summary,
                        &[],
                        None,
                    );
                    let pending_leader = !v2_plan_linked;
                    let last_attempt_status = if v2_plan_linked {
                        "awaiting_plan_verification"
                    } else {
                        AWAITING_LEADER_ADJUDICATION_STATUS
                    };
                    task_metadata
                        .insert("evidence_refs".to_string(), json!(report.merged_artifacts));
                    task_metadata.insert(
                        "execution_verifications".to_string(),
                        json!(report.merged_verifications),
                    );
                    task_metadata.insert("last_worker_report_type".to_string(), json!(report_type));
                    task_metadata.insert(
                        LAST_WORKER_REPORT_SUMMARY.to_string(),
                        json!(report.normalized_summary.clone()),
                    );
                    task_metadata.insert(
                        "last_worker_report_artifacts".to_string(),
                        json!(report.merged_artifacts.clone()),
                    );
                    task_metadata.insert(
                        "last_worker_report_verifications".to_string(),
                        json!(report.report_verifications.clone()),
                    );
                    task_metadata.insert(
                        "last_worker_reported_at".to_string(),
                        json!(input.now.to_rfc3339()),
                    );
                    task_metadata.insert(
                        "last_worker_report_fingerprint".to_string(),
                        json!(report.fingerprint.clone()),
                    );
                    task_metadata
                        .insert(LAST_WORKER_REPORT_ATTEMPT_ID.to_string(), json!(attempt_id));
                    task_metadata.insert(
                        PENDING_LEADER_ADJUDICATION.to_string(),
                        json!(pending_leader),
                    );
                    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
                    task_metadata.insert("last_attempt_id".to_string(), json!(attempt_id));
                    if let Some(conversation_id) = input.conversation_id {
                        task_metadata.insert(
                            CURRENT_ATTEMPT_CONVERSATION_ID.to_string(),
                            json!(conversation_id),
                        );
                    }
                    task_metadata.insert(
                        "current_attempt_worker_agent_id".to_string(),
                        json!(input.worker_agent_id),
                    );
                    if let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? {
                        task_metadata.insert(
                            "current_attempt_number".to_string(),
                            json!(attempt.attempt_number),
                        );
                    }
                    task_metadata.insert(
                        "last_attempt_status".to_string(),
                        json!(last_attempt_status),
                    );
                    task_metadata.insert(
                        "execution_state".to_string(),
                        worker_execution_state(
                            "in_progress",
                            &format!(
                                "workspace_goal_runtime.worker_report.{report_type}:{}",
                                report.normalized_summary
                            ),
                            if v2_plan_linked {
                                "await_plan_verification"
                            } else {
                                "await_leader_adjudication"
                            },
                            input.worker_agent_id,
                            input.now,
                        ),
                    );

                    let recorded = self
                        .store
                        .record_task_session_attempt_candidate_output(
                            attempt_id,
                            Some(&report.normalized_summary),
                            &report.report_artifacts,
                            &report.report_verifications,
                            input.conversation_id,
                            input.now,
                        )
                        .await?
                        .is_some();
                    if recorded {
                        reported = true;
                        if let (Some(plan_id), Some(node_id), Some(root_goal_task_id)) = (
                            plan_id.as_deref(),
                            node_id.as_deref(),
                            root_goal_task_id.as_deref(),
                        ) {
                            self.mark_workspace_plan_node_reported(
                                &input,
                                plan_id,
                                node_id,
                                root_goal_task_id,
                                report_type,
                                &report,
                            )
                            .await?;
                        }
                    }
                }
            }
        } else {
            task_metadata.insert(
                "execution_state".to_string(),
                worker_execution_state(
                    "in_progress",
                    &format!("workspace_worker_launch.{}", input.outcome.launch_state),
                    "observe",
                    input.leader_agent_id.unwrap_or(input.actor_user_id),
                    input.now,
                ),
            );
        }

        task.metadata_json = Value::Object(task_metadata);
        if task.status == "todo" {
            task.status = "in_progress".to_string();
            task.completed_at = None;
        }
        if input
            .outcome
            .report_type
            .as_ref()
            .is_some_and(|report_type| {
                report_type.as_str() == "blocked" && input.outcome.should_report
            })
        {
            task.blocker_reason = Some(input.outcome.summary.clone());
        }
        task.updated_at = Some(input.now);
        self.store.save_task(task).await?;
        Ok(reported)
    }

    async fn mark_workspace_plan_node_reported(
        &self,
        input: &WorkerStreamTerminalPersistence<'_>,
        plan_id: &str,
        node_id: &str,
        root_goal_task_id: &str,
        report_type: &str,
        report: &WorkerReportPayload,
    ) -> CoreResult<()> {
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(());
        };
        if input
            .attempt_id
            .is_some_and(|attempt_id| node.current_attempt_id.as_deref() != Some(attempt_id))
        {
            return Ok(());
        }
        let Some(attempt_id) = input.attempt_id else {
            return Ok(());
        };
        let mut progress = object_or_empty(node.progress_json.clone());
        progress
            .entry("percent".to_string())
            .or_insert_with(|| json!(0.0));
        progress
            .entry("confidence".to_string())
            .or_insert_with(|| json!(1.0));
        progress.insert("note".to_string(), json!(report.normalized_summary.clone()));

        let mut metadata = object_or_empty(node.metadata_json.clone());
        let reported_at = input.now.to_rfc3339();
        let report_event = json!({
            "event_type": "worker_report_terminal",
            "source_event_type": "worker_report_terminal",
            "summary": report.normalized_summary,
            "attempt_id": attempt_id,
            "worker_agent_id": input.worker_agent_id,
            "reported_at": reported_at
        });
        let mut progress_events = metadata
            .get("progress_events")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        progress_events.push(report_event.clone());
        if progress_events.len() > 25 {
            progress_events = progress_events.split_off(progress_events.len() - 25);
        }
        metadata.insert("progress_events".to_string(), Value::Array(progress_events));
        metadata.insert("latest_worker_progress".to_string(), report_event);
        metadata.insert(
            "launch_state".to_string(),
            json!(input.outcome.launch_state),
        );
        metadata.insert("last_worker_report_type".to_string(), json!(report_type));
        metadata.insert(
            LAST_WORKER_REPORT_SUMMARY.to_string(),
            json!(report.normalized_summary.clone()),
        );
        metadata.insert(LAST_WORKER_REPORT_ATTEMPT_ID.to_string(), json!(attempt_id));
        metadata.insert("last_worker_reported_at".to_string(), json!(reported_at));

        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some(attempt_id.to_string());
        node.progress_json = Value::Object(progress);
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(input.now);
        self.store.save_plan_node(node).await?;
        self.store
            .create_plan_event(WorkspacePlanEventRecord {
                id: generate_uuid_v4(),
                plan_id: plan_id.to_string(),
                workspace_id: input.workspace_id.to_string(),
                node_id: Some(node_id.to_string()),
                attempt_id: Some(attempt_id.to_string()),
                event_type: "worker_report_terminal".to_string(),
                source: "worker_report".to_string(),
                actor_id: Some(input.worker_agent_id.to_string()),
                payload_json: json!({
                    "report_type": report_type,
                    "summary": report.normalized_summary,
                    "artifacts": report.report_artifacts,
                    "verifications": report.report_verifications,
                    "reported_at": input.now.to_rfc3339()
                }),
                created_at: input.now,
            })
            .await?;
        self.store
            .enqueue_plan_outbox(worker_report_supervisor_tick(
                input.workspace_id,
                plan_id,
                node_id,
                attempt_id,
                root_goal_task_id,
                input.actor_user_id,
                input.leader_agent_id,
                input.now,
            ))
            .await?;
        Ok(())
    }

    async fn runtime_agent_running_exists(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .agent_running_exists(conversation_id)
            .await
        {
            Ok(exists) => exists,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: agent:running check failed for {conversation_id}: {err}"
                );
                false
            }
        }
    }

    async fn runtime_clear_reused_session_markers(&self, conversation_id: &str) {
        if let Err(err) = self
            .runtime_state
            .clear_reused_session_markers(conversation_id)
            .await
        {
            eprintln!(
                "[agistack] worker launch state: clear reused markers failed for {conversation_id}: {err}"
            );
        }
    }

    async fn runtime_refresh_bound_session_markers(&self, conversation_id: &str) {
        self.runtime_refresh_launch_cooldown(conversation_id).await;
        if self
            .runtime_agent_finished_message_id(conversation_id)
            .await
            .is_some()
        {
            return;
        }
        self.runtime_refresh_agent_running_marker(conversation_id)
            .await;
    }

    async fn runtime_refresh_launch_cooldown(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .refresh_launch_cooldown(conversation_id, WORKER_LAUNCH_COOLDOWN_SECONDS)
            .await
        {
            Ok(refreshed) => refreshed,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: cooldown refresh failed for {conversation_id}: {err}"
                );
                false
            }
        }
    }

    async fn runtime_agent_finished_message_id(&self, conversation_id: &str) -> Option<String> {
        match self
            .runtime_state
            .agent_finished_message_id(conversation_id)
            .await
        {
            Ok(message_id) => message_id,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: agent:finished read failed for {conversation_id}: {err}"
                );
                None
            }
        }
    }

    async fn runtime_refresh_agent_running_marker(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .refresh_agent_running_marker(conversation_id, WORKER_LAUNCH_COOLDOWN_SECONDS)
            .await
        {
            Ok(refreshed) => refreshed,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: agent:running refresh failed for {conversation_id}: {err}"
                );
                false
            }
        }
    }

    async fn runtime_claim_launch_cooldown(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .claim_launch_cooldown(conversation_id, WORKER_LAUNCH_COOLDOWN_SECONDS)
            .await
        {
            Ok(claimed) => claimed,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: cooldown claim failed for {conversation_id}: {err}"
                );
                true
            }
        }
    }

    async fn stale_worker_launch_reason(
        &self,
        task: &WorkspaceTaskRecord,
        plan_id: Option<&str>,
        node_id: Option<&str>,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<String>> {
        let mut reason = None;
        if let Some(attempt_id) = attempt_id {
            match self.store.get_task_session_attempt(attempt_id).await? {
                None => reason = Some("attempt_missing".to_string()),
                Some(attempt) => {
                    if attempt.workspace_task_id != task.id
                        || attempt.workspace_id != task.workspace_id
                    {
                        reason = Some("attempt_task_mismatch".to_string());
                    } else if !WORKER_LAUNCHABLE_ATTEMPT_STATUSES.contains(&attempt.status.as_str())
                    {
                        reason = Some(format!("attempt_{}", attempt.status));
                    }
                }
            }
        }

        let task_metadata = object_or_empty(task.metadata_json.clone());
        let current_task_attempt_id = string_from_map(&task_metadata, CURRENT_ATTEMPT_ID);
        if reason.is_none()
            && current_task_attempt_id.is_some()
            && current_task_attempt_id.as_deref() != attempt_id
        {
            reason = Some("task_current_attempt_changed".to_string());
        }

        if reason.is_none() {
            if let (Some(plan_id), Some(node_id)) = (plan_id, node_id) {
                if self
                    .store
                    .has_supervisor_dispose_decision_for_node(&task.workspace_id, plan_id, node_id)
                    .await?
                {
                    return Ok(Some("supervisor_disposed_node".to_string()));
                }
                if let Some(plan) = self.store.get_plan(plan_id).await? {
                    if plan.workspace_id == task.workspace_id {
                        let nodes = self.store.list_plan_nodes(plan_id).await?;
                        if let Some(node) =
                            nodes.into_iter().find(|candidate| candidate.id == node_id)
                        {
                            if node.workspace_task_id.as_deref().is_some()
                                && node.workspace_task_id.as_deref() != Some(task.id.as_str())
                            {
                                reason = Some("node_task_mismatch".to_string());
                            } else if node.current_attempt_id.as_deref().is_some()
                                && node.current_attempt_id.as_deref() != attempt_id
                            {
                                reason = Some("node_current_attempt_changed".to_string());
                            } else if node.intent == "done" || node.execution == "idle" {
                                reason = Some("node_not_launchable".to_string());
                            }
                        }
                    }
                }
            }
        }
        Ok(reason)
    }

    async fn defer_active_capacity_count(
        &self,
        workspace_id: &str,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<i64>> {
        let max_active = self.config.max_active_worker_conversations;
        if max_active <= 0 {
            return Ok(None);
        }
        if let Some(attempt_id) = attempt_id {
            if self
                .store
                .get_task_session_attempt(attempt_id)
                .await?
                .and_then(|attempt| attempt.conversation_id)
                .is_some()
            {
                return Ok(None);
            }
        }
        let active_after =
            Utc::now() - ChronoDuration::seconds(self.config.active_event_grace_seconds.max(1));
        let active_count = self
            .store
            .count_recent_running_task_session_attempts_with_conversation(
                workspace_id,
                active_after,
            )
            .await?;
        Ok((active_count >= max_active).then_some(active_count))
    }

    async fn mark_plan_node_running_after_launch_schedule(
        &self,
        plan_id: Option<&str>,
        node_id: Option<&str>,
        attempt_id: Option<&str>,
        conversation_id: Option<&str>,
        launch_state: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let (Some(plan_id), Some(node_id)) = (plan_id, node_id) else {
            return Ok(());
        };
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(());
        };
        if attempt_id.is_some()
            && node.current_attempt_id.as_deref().is_some()
            && node.current_attempt_id.as_deref() != attempt_id
        {
            return Ok(());
        }
        if !matches!(node.execution.as_str(), "dispatched" | "running") {
            return Ok(());
        }
        node.execution = "running".to_string();
        if let Some(attempt_id) = attempt_id {
            node.current_attempt_id = Some(attempt_id.to_string());
        }
        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert("launch_state".to_string(), json!(launch_state));
        metadata.insert(
            "worker_launch_admitted_at".to_string(),
            json!(now.to_rfc3339()),
        );
        if let Some(conversation_id) = conversation_id {
            metadata.insert(
                CURRENT_ATTEMPT_CONVERSATION_ID.to_string(),
                json!(conversation_id),
            );
            metadata.insert(
                "worker_launch_bound_at".to_string(),
                json!(now.to_rfc3339()),
            );
        }
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node).await?;
        Ok(())
    }

    async fn load_launch_node(
        &self,
        plan_id: Option<&str>,
        node_id: Option<&str>,
    ) -> CoreResult<Option<WorkspacePlanNodeRecord>> {
        let (Some(plan_id), Some(node_id)) = (plan_id, node_id) else {
            return Ok(None);
        };
        Ok(self
            .store
            .list_plan_nodes(plan_id)
            .await?
            .into_iter()
            .find(|candidate| candidate.id == node_id))
    }

    async fn block_task_for_worktree_setup_failure(
        &self,
        mut task: WorkspaceTaskRecord,
        mut task_metadata: Map<String, Value>,
        launch_node: Option<WorkspacePlanNodeRecord>,
        attempt_id: Option<&str>,
        context: &WorkerLaunchWorktreeContext,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let reason = context
            .setup_reason
            .as_deref()
            .unwrap_or("attempt worktree setup failed");
        let summary = format!("worktree_setup_failed: {reason}");
        merge_metadata_patch(&mut task_metadata, &context.metadata_patch);
        task_metadata.insert("launch_state".to_string(), json!("worktree_setup_failed"));
        task_metadata.insert("last_attempt_status".to_string(), json!("blocked"));
        if let Some(attempt_id) = attempt_id {
            task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        task.metadata_json = Value::Object(task_metadata);
        task.status = "blocked".to_string();
        task.blocker_reason = Some(summary.clone());
        task.completed_at = None;
        task.updated_at = Some(now);
        self.store.save_task(task).await?;

        if let Some(attempt_id) = attempt_id {
            let _ = self
                .store
                .finish_task_session_attempt(
                    attempt_id,
                    "blocked",
                    Some(&summary),
                    Some("worktree_setup_failed"),
                    now,
                )
                .await?;
        }

        if let Some(mut node) = launch_node {
            let mut node_metadata = object_or_empty(node.metadata_json);
            merge_metadata_patch(&mut node_metadata, &context.metadata_patch);
            node_metadata.insert("worktree_setup_failure_summary".to_string(), json!(summary));
            node_metadata.insert("last_attempt_status".to_string(), json!("blocked"));
            if let Some(attempt_id) = attempt_id {
                node_metadata.insert("terminal_attempt_status".to_string(), json!("blocked"));
                node_metadata.insert(
                    "terminal_attempt_reconciled_at".to_string(),
                    json!(now.to_rfc3339()),
                );
                node_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
            }
            node.intent = "blocked".to_string();
            node.execution = "idle".to_string();
            node.current_attempt_id = None;
            node.metadata_json = Value::Object(node_metadata);
            node.completed_at = None;
            node.updated_at = Some(now);
            self.store.save_plan_node(node).await?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
struct WorkerLaunchWorktreeContext {
    metadata_patch: Map<String, Value>,
    setup_failed: bool,
    setup_reason: Option<String>,
}

async fn worker_launch_worktree_context(
    workspace: Option<&WorkspaceRecord>,
    task: &WorkspaceTaskRecord,
    node: Option<&WorkspacePlanNodeRecord>,
    attempt_id: Option<&str>,
) -> CoreResult<Option<WorkerLaunchWorktreeContext>> {
    let feature = node
        .and_then(|node| node.feature_checkpoint_json.as_ref())
        .filter(|value| value.is_object())
        .or_else(|| {
            task.metadata_json
                .get("feature_checkpoint")
                .filter(|value| value.is_object())
        });
    if feature.is_none() && attempt_id.is_none() {
        return Ok(None);
    }

    let task_metadata = task.metadata_json.clone();
    let workspace_metadata = workspace
        .map(|workspace| workspace.metadata_json.clone())
        .unwrap_or(Value::Null);
    let base_ref = feature
        .and_then(|value| metadata_string_from_path(value, &["base_ref"]))
        .or_else(|| feature.and_then(|value| metadata_string_from_path(value, &["commit_ref"])))
        .unwrap_or_else(|| "HEAD".to_string());
    let sandbox_code_root = sandbox_code_root_for_integration(&task_metadata, &workspace_metadata);
    let Some(sandbox_code_root) = sandbox_code_root else {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some("sandbox_code_root is not available for this workspace"),
                workspace_root: None,
                sandbox_code_root: None,
                active_root: None,
                worktree_path: None,
                branch_name: None,
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: None,
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    };

    let worktree_path_template =
        feature.and_then(|value| metadata_string_from_path(value, &["worktree_path"]));
    let branch_name = feature
        .and_then(|value| metadata_string_from_path(value, &["branch_name"]))
        .or_else(|| {
            let attempt_id = attempt_id?;
            let node_id = node
                .map(|node| node.id.as_str())
                .unwrap_or(task.id.as_str());
            Some(worktree_branch_name(node_id, attempt_id))
        });

    if (worktree_path_template.is_none() || branch_name.is_none()) && attempt_id.is_none() {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some(
                    "feature checkpoint does not include worktree_path and branch_name",
                ),
                workspace_root: None,
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: None,
                branch_name: branch_name.as_deref(),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: None,
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    let worktree_path = match (worktree_path_template, attempt_id) {
        (Some(template), _) => template.replace("${sandbox_code_root}", &sandbox_code_root),
        (None, Some(attempt_id)) => default_attempt_worktree_path(&sandbox_code_root, attempt_id),
        (None, None) => String::new(),
    };
    let branch_name = branch_name.unwrap_or_else(|| {
        worktree_branch_name(
            node.map(|node| node.id.as_str())
                .unwrap_or(task.id.as_str()),
            attempt_id.unwrap_or("attempt"),
        )
    });

    if worktree_path.contains("${sandbox_code_root}") {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some(
                    "worktree_path still contains an unresolved sandbox_code_root placeholder",
                ),
                workspace_root: None,
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: Some(&worktree_path),
                branch_name: Some(&branch_name),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: None,
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    let worktree_path = normalize_posix_path(&worktree_path);
    if let Some(reason) = worker_launch_worktree_path_failure(&sandbox_code_root, &worktree_path) {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "failed",
                setup_reason: Some(&reason),
                workspace_root: workspace_root_for_code_root(&sandbox_code_root).as_deref(),
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: Some(&worktree_path),
                branch_name: Some(&branch_name),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: Some(&base_ref),
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    let code_root = Path::new(&sandbox_code_root);
    if !code_root.exists() {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some("sandbox_code_root is not a local path on the Rust worker host"),
                workspace_root: workspace_root_for_code_root(&sandbox_code_root).as_deref(),
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: Some(&worktree_path),
                branch_name: Some(&branch_name),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: Some(&base_ref),
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    Ok(Some(
        prepare_worker_launch_worktree_with_git(
            code_root,
            Path::new(&worktree_path),
            &branch_name,
            &base_ref,
            attempt_id,
        )
        .await?,
    ))
}

struct WorktreeContextInput<'a> {
    setup_status: &'a str,
    setup_reason: Option<&'a str>,
    workspace_root: Option<&'a str>,
    sandbox_code_root: Option<&'a str>,
    active_root: Option<&'a str>,
    worktree_path: Option<&'a str>,
    branch_name: Option<&'a str>,
    base_ref: Option<&'a str>,
    attempt_id: Option<&'a str>,
    setup_output: Option<&'a str>,
    original_base_ref: Option<&'a str>,
    resolved_base_ref: Option<&'a str>,
    fallback_reason: Option<&'a str>,
    git_fsck_summary: Option<&'a str>,
    pruned_worktrees_count: Option<i64>,
}

fn worker_launch_worktree_context_value(
    input: WorktreeContextInput<'_>,
) -> WorkerLaunchWorktreeContext {
    let active_root = input.active_root.map(ToOwned::to_owned);
    let is_isolated = active_root.is_some();
    let attempt_worktree = json!({
        "workspace_root": input.workspace_root,
        "sandbox_code_root": input.sandbox_code_root,
        "active_root": active_root,
        "worktree_path": input.worktree_path,
        "branch_name": input.branch_name,
        "base_ref": input.base_ref,
        "attempt_id": input.attempt_id,
        "is_isolated": is_isolated,
        "setup_status": input.setup_status,
        "setup_reason": input.setup_reason,
        "setup_output": input.setup_output,
        "original_base_ref": input.original_base_ref,
        "resolved_base_ref": input.resolved_base_ref,
        "fallback_reason": input.fallback_reason,
        "git_fsck_summary": input.git_fsck_summary,
        "pruned_worktrees_count": input.pruned_worktrees_count
    });
    let setup = json!({
        "status": input.setup_status,
        "reason": input.setup_reason,
        "output": input.setup_output,
        "worktree_path": input.worktree_path,
        "branch_name": input.branch_name,
        "base_ref": input.base_ref,
        "attempt_id": input.attempt_id,
        "original_base_ref": input.original_base_ref,
        "resolved_base_ref": input.resolved_base_ref,
        "fallback_reason": input.fallback_reason,
        "git_fsck_summary": input.git_fsck_summary,
        "pruned_worktrees_count": input.pruned_worktrees_count
    });
    let mut metadata_patch = Map::new();
    metadata_patch.insert("attempt_worktree".to_string(), attempt_worktree);
    metadata_patch.insert("worktree_setup".to_string(), setup);
    if let Some(active_root) = input.active_root {
        metadata_patch.insert("active_execution_root".to_string(), json!(active_root));
    }
    WorkerLaunchWorktreeContext {
        metadata_patch,
        setup_failed: input.setup_status == "failed",
        setup_reason: input.setup_reason.map(ToOwned::to_owned),
    }
}

async fn prepare_worker_launch_worktree_with_git(
    sandbox_code_root: &Path,
    worktree_path: &Path,
    branch_name: &str,
    base_ref: &str,
    attempt_id: Option<&str>,
) -> CoreResult<WorkerLaunchWorktreeContext> {
    let env: Vec<(String, String)> = Vec::new();
    let sandbox_code_root_text = sandbox_code_root.to_string_lossy().to_string();
    let worktree_path_text = worktree_path.to_string_lossy().to_string();
    let workspace_root = workspace_root_for_code_root(&sandbox_code_root.to_string_lossy());
    let git_root = run_git_command(
        sandbox_code_root,
        &["rev-parse", "--show-toplevel"],
        &env,
        30,
    )
    .await?;
    if git_root.exit_code != 0 {
        return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
            setup_status: "skipped",
            setup_reason: Some("sandbox_code_root is not a git checkout"),
            workspace_root: workspace_root.as_deref(),
            sandbox_code_root: Some(&sandbox_code_root_text),
            active_root: None,
            worktree_path: Some(&worktree_path_text),
            branch_name: Some(branch_name),
            base_ref: Some(base_ref),
            attempt_id,
            setup_output: Some(&compact_git_error(&git_root)),
            original_base_ref: Some(base_ref),
            resolved_base_ref: None,
            fallback_reason: None,
            git_fsck_summary: None,
            pruned_worktrees_count: None,
        }));
    }

    if worktree_path.exists() {
        let existing = run_git_command(
            worktree_path,
            &["rev-parse", "--is-inside-work-tree"],
            &env,
            30,
        )
        .await?;
        if existing.exit_code != 0 {
            let reason = format!(
                "worktree_path exists but is not a git worktree: {}",
                worktree_path.display()
            );
            return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
                setup_status: "failed",
                setup_reason: Some(&reason),
                workspace_root: workspace_root.as_deref(),
                sandbox_code_root: Some(&sandbox_code_root_text),
                active_root: None,
                worktree_path: Some(&worktree_path_text),
                branch_name: Some(branch_name),
                base_ref: Some(base_ref),
                attempt_id,
                setup_output: Some(&compact_git_error(&existing)),
                original_base_ref: Some(base_ref),
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            }));
        }
        let head = short_git_head(worktree_path, &env).await?;
        return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
            setup_status: "prepared",
            setup_reason: Some("attempt worktree already exists"),
            workspace_root: workspace_root.as_deref(),
            sandbox_code_root: Some(&sandbox_code_root_text),
            active_root: Some(&worktree_path_text),
            worktree_path: Some(&worktree_path_text),
            branch_name: Some(branch_name),
            base_ref: Some(base_ref),
            attempt_id,
            setup_output: Some("existing git worktree reused"),
            original_base_ref: Some(base_ref),
            resolved_base_ref: Some(&head),
            fallback_reason: None,
            git_fsck_summary: None,
            pruned_worktrees_count: None,
        }));
    }

    if let Some(parent) = worktree_path.parent() {
        tokio::fs::create_dir_all(parent).await.map_err(|err| {
            CoreError::Storage(format!(
                "create attempt worktree parent {}: {err}",
                parent.display()
            ))
        })?;
    }
    let _ = run_git_command(sandbox_code_root, &["worktree", "prune"], &env, 60).await?;
    let worktree_arg = worktree_path.to_string_lossy().to_string();
    let add = run_git_command(
        sandbox_code_root,
        &[
            "worktree",
            "add",
            "-B",
            branch_name,
            &worktree_arg,
            base_ref,
        ],
        &env,
        120,
    )
    .await?;
    if add.exit_code != 0 {
        let reason = compact_git_error(&add);
        return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
            setup_status: "failed",
            setup_reason: Some(&reason),
            workspace_root: workspace_root.as_deref(),
            sandbox_code_root: Some(&sandbox_code_root_text),
            active_root: None,
            worktree_path: Some(&worktree_path_text),
            branch_name: Some(branch_name),
            base_ref: Some(base_ref),
            attempt_id,
            setup_output: Some(&compact_text(&add.stdout, 1200)),
            original_base_ref: Some(base_ref),
            resolved_base_ref: None,
            fallback_reason: None,
            git_fsck_summary: None,
            pruned_worktrees_count: None,
        }));
    }
    let head = short_git_head(worktree_path, &env).await?;
    Ok(worker_launch_worktree_context_value(WorktreeContextInput {
        setup_status: "prepared",
        setup_reason: None,
        workspace_root: workspace_root.as_deref(),
        sandbox_code_root: Some(&sandbox_code_root_text),
        active_root: Some(&worktree_path_text),
        worktree_path: Some(&worktree_path_text),
        branch_name: Some(branch_name),
        base_ref: Some(base_ref),
        attempt_id,
        setup_output: Some(&compact_text(&add.stdout, 1200)),
        original_base_ref: Some(base_ref),
        resolved_base_ref: Some(&head),
        fallback_reason: None,
        git_fsck_summary: None,
        pruned_worktrees_count: None,
    }))
}

fn worker_launch_worktree_path_failure(
    sandbox_code_root: &str,
    worktree_path: &str,
) -> Option<String> {
    let code_root = normalize_posix_path(sandbox_code_root);
    let worktree_path = normalize_posix_path(worktree_path);
    if !worktree_path.starts_with('/') {
        return Some(format!("worktree_path is not absolute: {worktree_path}"));
    }
    if worktree_path == code_root || worktree_path.starts_with(&format!("{code_root}/")) {
        return Some(format!(
            "workspace run contract rejected worker launch path: worktree_path must not be inside sandbox_code_root; code_root={code_root}; worktree_path={worktree_path}"
        ));
    }
    None
}

fn workspace_root_for_code_root(sandbox_code_root: &str) -> Option<String> {
    let normalized = normalize_posix_path(sandbox_code_root);
    normalized
        .rsplit_once('/')
        .map(|(parent, _)| if parent.is_empty() { "/" } else { parent })
        .map(ToOwned::to_owned)
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

fn worker_stream_poll_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    conversation_id: &str,
    replay: &WorkerStreamReplayResult,
    delay_seconds: i64,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut poll_payload = payload.clone();
    poll_payload.insert("worker_stream_poll".to_string(), json!(true));
    poll_payload.insert("stream_after_id".to_string(), json!(replay.next_after_id()));
    poll_payload.insert(
        "worker_stream_poll_conversation_id".to_string(),
        json!(conversation_id),
    );
    poll_payload.remove("reuse_conversation_id");

    let mut metadata = object_or_empty(item.metadata_json.clone());
    let poll_count = metadata
        .get("stream_poll_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "source".to_string(),
        json!("workspace_plan.worker_launch.stream_poll"),
    );
    metadata.insert(
        "stream_poll_from_outbox_id".to_string(),
        json!(item.id.clone()),
    );
    metadata.insert("stream_poll_count".to_string(), json!(poll_count));
    metadata.insert(
        "stream_poll_after_id".to_string(),
        json!(replay.next_after_id()),
    );
    metadata.insert(
        "stream_poll_conversation_id".to_string(),
        json!(conversation_id),
    );
    metadata.insert(
        "stream_poll_entries_read".to_string(),
        json!(replay.entries_read),
    );

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: item.plan_id.clone(),
        workspace_id: item.workspace_id.clone(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(poll_payload),
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
