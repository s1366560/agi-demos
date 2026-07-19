use super::*;

pub(super) struct DurableHandoffResumeHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
}

impl DurableHandoffResumeHandler {
    pub(super) fn new(store: Arc<dyn WorkspacePlanDispatchStore>) -> Self {
        Self { store }
    }
}

#[async_trait]
impl WorkspacePlanOutboxHandler for DurableHandoffResumeHandler {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let payload = object_as_map(&item.payload_json);
        let workspace_id =
            string_from_map(payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let task_id = required_string(payload, "task_id")?;
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
        let actor_user_id =
            string_from_map(payload, "actor_user_id").unwrap_or_else(|| task.created_by.clone());
        let leader_agent_id = string_from_map(payload, "leader_agent_id")
            .or_else(|| string_from_map(&task_metadata, "leader_agent_id"))
            .unwrap_or_else(|| WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string());
        let worker_agent_id = string_from_map(payload, "worker_agent_id")
            .or_else(|| task.assignee_agent_id.clone())
            .ok_or_else(|| {
                CoreError::Storage(format!("workspace task {task_id} has no worker agent"))
            })?;
        let root_goal_task_id = string_from_map(payload, ROOT_GOAL_TASK_ID)
            .or_else(|| string_from_map(payload, "root_task_id"))
            .or_else(|| string_from_map(&task_metadata, ROOT_GOAL_TASK_ID))
            .ok_or_else(|| {
                CoreError::Storage(format!("workspace task {task_id} has no root goal task"))
            })?;
        let plan_id = item
            .plan_id
            .clone()
            .or_else(|| string_from_map(payload, "plan_id"))
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_ID));
        let node_id = string_from_map(payload, "node_id")
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_NODE_ID));
        let previous_attempt_id = string_from_map(payload, "previous_attempt_id");
        let force_schedule = bool_from_map(payload, "force_schedule");

        let mut should_schedule = force_schedule;
        let mut attempt = self
            .store
            .find_active_task_session_attempt(&task.id)
            .await?;
        if let Some(active) = attempt.as_ref() {
            if !force_schedule
                && previous_attempt_id.as_deref() == Some(active.id.as_str())
                && active.status == "running"
                && active.conversation_id.is_some()
            {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
        }

        let now = Utc::now();
        if attempt.is_none() {
            let next_attempt_number = self
                .store
                .latest_task_session_attempt_number(&task.id)
                .await?
                + 1;
            let created = self
                .store
                .create_task_session_attempt(WorkspaceTaskSessionAttemptRecord {
                    id: generate_uuid_v4(),
                    workspace_task_id: task.id.clone(),
                    root_goal_task_id: root_goal_task_id.clone(),
                    workspace_id: workspace_id.clone(),
                    attempt_number: next_attempt_number,
                    status: "pending".to_string(),
                    conversation_id: None,
                    worker_agent_id: Some(worker_agent_id.clone()),
                    leader_agent_id: persisted_attempt_leader_agent_id(&leader_agent_id),
                    candidate_summary: None,
                    candidate_artifacts_json: Vec::new(),
                    candidate_verifications_json: Vec::new(),
                    leader_feedback: None,
                    adjudication_reason: None,
                    created_at: now,
                    updated_at: Some(now),
                    completed_at: None,
                })
                .await?;
            attempt = Some(created);
            should_schedule = true;
        }
        let Some(mut attempt) = attempt else {
            return Err(CoreError::Storage(format!(
                "workspace task {task_id} has no active attempt after handoff resume admission"
            )));
        };
        if attempt.status == "pending" {
            attempt = self
                .store
                .mark_task_session_attempt_running(&attempt.id, now)
                .await?
                .ok_or_else(|| {
                    CoreError::Storage(format!(
                        "workspace task session attempt {} not found",
                        attempt.id
                    ))
                })?;
            should_schedule = true;
        } else if attempt.conversation_id.is_none() {
            should_schedule = true;
        }

        if let (Some(plan_id), Some(node_id)) = (plan_id.as_deref(), node_id.as_deref()) {
            self.project_attempt_to_plan_node(HandoffPlanProjection {
                workspace_id: &workspace_id,
                plan_id,
                node_id,
                item: &item,
                payload,
                attempt: &attempt,
                worker_agent_id: &worker_agent_id,
            })
            .await?;
        }

        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt.id.clone()));
        task_metadata.insert(
            "current_attempt_number".to_string(),
            json!(attempt.attempt_number),
        );
        task_metadata.insert(
            "current_attempt_worker_agent_id".to_string(),
            json!(worker_agent_id.clone()),
        );
        task_metadata.insert(CURRENT_ATTEMPT_WORKER_BINDING_ID.to_string(), Value::Null);
        task_metadata.insert("last_attempt_status".to_string(), json!("running"));
        task_metadata.insert("launch_state".to_string(), json!("scheduled"));
        if should_reset_attempt_retry_worker_state(&item.event_type, payload) {
            clear_attempt_retry_worker_stream_state(&mut task_metadata);
            task.blocker_reason = None;
        }
        apply_attempt_retry_context(&mut task_metadata, payload, now);
        task_metadata.insert(
            "execution_state".to_string(),
            json!({
                "phase": "in_progress",
                "last_agent_reason": "workspace_plan.dispatch.project_attempt",
                "last_agent_action": "start",
                "updated_by_actor_type": "agent",
                "updated_by_actor_id": leader_agent_id,
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

        if should_schedule {
            self.store
                .enqueue_plan_outbox(worker_launch_outbox(
                    plan_id.as_deref(),
                    &workspace_id,
                    &item.event_type,
                    payload,
                    &task_id,
                    &worker_agent_id,
                    &actor_user_id,
                    &leader_agent_id,
                    &attempt.id,
                    node_id.as_deref(),
                    now,
                ))
                .await?;
        }

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

impl DurableHandoffResumeHandler {
    async fn project_attempt_to_plan_node(
        &self,
        projection: HandoffPlanProjection<'_>,
    ) -> CoreResult<()> {
        let HandoffPlanProjection {
            workspace_id,
            plan_id,
            node_id,
            item,
            payload,
            attempt,
            worker_agent_id,
        } = projection;
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let mut node = nodes
            .drain(..)
            .find(|candidate| candidate.id == node_id)
            .ok_or_else(|| {
                CoreError::Storage(format!("workspace plan node {node_id} not found"))
            })?;
        let now = Utc::now();
        let handoff = json!({
            "event_type": item.event_type,
            "outbox_id": item.id,
            "previous_attempt_id": string_from_map(payload, "previous_attempt_id"),
            "attempt_id": attempt.id,
            "worker_agent_id": worker_agent_id,
        });
        let mut handoff = handoff;
        if let Some(handoff) = handoff.as_object_mut() {
            copy_retry_context_payload_fields(payload, handoff);
        }
        node.handoff_package_json = Some(handoff.clone());
        node.current_attempt_id = Some(attempt.id.clone());
        node.assignee_agent_id = Some(worker_agent_id.to_string());
        apply_attempt_worktree_checkpoint(&mut node, &attempt.id);
        if node.intent != "done" {
            node.intent = "in_progress".to_string();
            node.execution = "dispatched".to_string();
            node.completed_at = None;
        }
        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert("handoff_package".to_string(), handoff);
        metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt.id.clone()));
        metadata.insert(
            "current_attempt_number".to_string(),
            json!(attempt.attempt_number),
        );
        metadata.insert(
            "current_attempt_worker_agent_id".to_string(),
            json!(worker_agent_id),
        );
        metadata.insert("last_attempt_status".to_string(), json!("running"));
        metadata.insert("launch_state".to_string(), json!("scheduled"));
        if should_reset_attempt_retry_worker_state(&item.event_type, payload) {
            clear_attempt_retry_worker_stream_state(&mut metadata);
        }
        apply_attempt_retry_context(&mut metadata, payload, now);
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node).await?;
        Ok(())
    }
}

struct HandoffPlanProjection<'a> {
    workspace_id: &'a str,
    plan_id: &'a str,
    node_id: &'a str,
    item: &'a WorkspacePlanOutboxRecord,
    payload: &'a Map<String, Value>,
    attempt: &'a WorkspaceTaskSessionAttemptRecord,
    worker_agent_id: &'a str,
}
