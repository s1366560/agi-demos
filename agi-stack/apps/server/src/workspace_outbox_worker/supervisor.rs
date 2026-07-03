use super::*;

pub(super) struct SupervisorTickAdmissionHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
}

impl SupervisorTickAdmissionHandler {
    pub(super) fn new(store: Arc<dyn WorkspacePlanDispatchStore>) -> Self {
        Self { store }
    }
}

#[async_trait]
impl WorkspacePlanOutboxHandler for SupervisorTickAdmissionHandler {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let payload = object_or_empty(item.payload_json.clone());
        let workspace_id =
            string_from_map(&payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let node_id = string_from_map(&payload, "retry_node_id")
            .or_else(|| string_from_map(&payload, "node_id"));
        let plan_id = item
            .plan_id
            .clone()
            .or_else(|| string_from_map(&payload, "plan_id"));
        let Some(node_id) = node_id else {
            let Some(plan_id) = plan_id else {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                    reason: Some("supervisor_tick_requires_full_runtime".to_string()),
                });
            };
            let changed_worktree_failed = self
                .reopen_failed_worktree_integration_nodes(&item, &payload, &workspace_id, &plan_id)
                .await?;
            let changed_missing = self
                .recover_missing_attempt_nodes(&item, &payload, &workspace_id, &plan_id)
                .await?;
            let changed_blocked_human = self
                .reconcile_supervisor_blocked_human_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_request_pipeline = self
                .reconcile_supervisor_request_pipeline_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_wait_pipeline = self
                .reconcile_supervisor_wait_pipeline_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_noop = self
                .reconcile_supervisor_noop_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_create_repair = self
                .reconcile_supervisor_create_repair_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_replan = self
                .reconcile_supervisor_replan_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_disposed = self
                .reconcile_supervisor_disposed_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_accepted = self
                .reconcile_accepted_terminal_attempt_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_supervisor_retry = self
                .reconcile_supervisor_retry_same_node_attempt_nodes(
                    &item,
                    &payload,
                    &workspace_id,
                    &plan_id,
                )
                .await?;
            let changed_terminal = self
                .reconcile_terminal_attempt_nodes(&item, &payload, &workspace_id, &plan_id)
                .await?;
            let changed_reported = self
                .reconcile_reported_attempt_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_dirty_main_dependency_dispatch = self
                .dispatch_ready_dirty_main_dependency_node(&item, &payload, &workspace_id, &plan_id)
                .await?;
            if changed_worktree_failed
                + changed_missing
                + changed_blocked_human
                + changed_request_pipeline
                + changed_wait_pipeline
                + changed_noop
                + changed_create_repair
                + changed_replan
                + changed_disposed
                + changed_accepted
                + changed_supervisor_retry
                + changed_terminal
                + changed_reported
                + changed_dirty_main_dependency_dispatch
                > 0
            {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
            return Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_requires_full_runtime".to_string()),
            });
        };
        let plan_id = plan_id.ok_or_else(|| {
            CoreError::Storage("supervisor_tick retry requires plan_id".to_string())
        })?;
        let plan = self.store.get_plan(&plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let mut nodes = self.store.list_plan_nodes(&plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        };
        if node.intent == "done" {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }
        let retry_attempt_id = string_from_map(&payload, "retry_attempt_id")
            .or_else(|| string_from_map(&payload, "attempt_id"));
        if retry_attempt_id.is_some()
            && node.current_attempt_id.as_deref().is_some()
            && node.current_attempt_id.as_deref() != retry_attempt_id.as_deref()
        {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let task_id = string_from_map(&payload, "task_id")
            .or_else(|| node.workspace_task_id.clone())
            .ok_or_else(|| {
                CoreError::Storage(format!(
                    "supervisor_tick retry node {node_id} has no workspace task"
                ))
            })?;
        let task = self
            .store
            .get_task(&workspace_id, &task_id)
            .await?
            .ok_or_else(|| {
                CoreError::Storage(format!(
                    "workspace task {task_id} not found for workspace {workspace_id}"
                ))
            })?;
        let task_metadata = object_or_empty(task.metadata_json.clone());
        let Some(worker_agent_id) = string_from_map(&payload, "worker_agent_id")
            .or_else(|| node.assignee_agent_id.clone())
            .or_else(|| task.assignee_agent_id.clone())
        else {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_retry_requires_worker_agent".to_string()),
            });
        };
        let actor_user_id =
            string_from_map(&payload, "actor_user_id").unwrap_or_else(|| task.created_by.clone());
        let leader_agent_id = string_from_map(&payload, "leader_agent_id")
            .or_else(|| string_from_map(&task_metadata, "leader_agent_id"))
            .unwrap_or_else(|| WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string());
        let root_goal_task_id = string_from_map(&payload, ROOT_GOAL_TASK_ID)
            .or_else(|| string_from_map(&payload, "root_task_id"))
            .or_else(|| string_from_map(&task_metadata, ROOT_GOAL_TASK_ID));
        if is_worker_report_supervisor_tick(&item, &payload) {
            return self
                .handle_worker_report_supervisor_tick(
                    &item,
                    &payload,
                    &workspace_id,
                    &plan_id,
                    node,
                    &task_id,
                    &worker_agent_id,
                    &actor_user_id,
                    &leader_agent_id,
                    root_goal_task_id.as_deref(),
                    retry_attempt_id.as_deref(),
                )
                .await;
        }
        let retry_reason = string_from_map(&payload, "retry_reason")
            .unwrap_or_else(|| "supervisor_tick_retry".to_string());

        let now = Utc::now();
        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert(
            "supervisor_tick_status".to_string(),
            json!("retry_admitted"),
        );
        metadata.insert(
            "supervisor_tick_admitted_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "supervisor_tick_outbox_id".to_string(),
            json!(item.id.clone()),
        );
        metadata.insert(
            "supervisor_tick_retry_reason".to_string(),
            json!(retry_reason.clone()),
        );
        if let Some(attempt_id) = retry_attempt_id.as_deref() {
            metadata.insert(
                "supervisor_tick_retry_attempt_id".to_string(),
                json!(attempt_id),
            );
        }
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node).await?;

        self.store
            .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                &item,
                &payload,
                &workspace_id,
                &plan_id,
                &node_id,
                &task_id,
                &worker_agent_id,
                &actor_user_id,
                &leader_agent_id,
                root_goal_task_id.as_deref(),
                retry_attempt_id.as_deref(),
                &retry_reason,
                now,
            ))
            .await?;

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

struct SupervisorRetryContext {
    task_id: String,
    worker_agent_id: String,
    actor_user_id: String,
    leader_agent_id: String,
    root_goal_task_id: Option<String>,
}

impl SupervisorTickAdmissionHandler {
    #[allow(clippy::too_many_arguments)]
    async fn handle_worker_report_supervisor_tick(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
        mut node: WorkspacePlanNodeRecord,
        task_id: &str,
        worker_agent_id: &str,
        actor_user_id: &str,
        leader_agent_id: &str,
        root_goal_task_id: Option<&str>,
        attempt_id: Option<&str>,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let Some(attempt_id) = attempt_id else {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        };
        let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? else {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        };
        if attempt.status != AWAITING_LEADER_ADJUDICATION_STATUS
            || !attempt_has_candidate_output(&attempt)
        {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let now = Utc::now();
        let node_metadata = object_or_empty(node.metadata_json.clone());
        if let Some(retry_reason) =
            worker_stream_orphan_report_retry_reason(&node_metadata, &attempt)
        {
            self.store
                .finish_task_session_attempt(
                    attempt_id,
                    "blocked",
                    attempt.candidate_summary.as_deref(),
                    Some(&retry_reason),
                    now,
                )
                .await?;
            let max_retries = plan_terminal_attempt_max_retries();
            let retry_exhausted =
                release_node_for_terminal_retry(&mut node, &retry_reason, now, max_retries);
            let mut metadata = object_or_empty(node.metadata_json.clone());
            let retry_count = metadata
                .get("terminal_attempt_retry_count")
                .and_then(Value::as_i64)
                .unwrap_or_default();
            let retry_status = if retry_exhausted {
                "orphan_retry_exhausted"
            } else {
                "orphan_retry_admitted"
            };
            metadata.insert(
                "worker_report_supervisor_tick_status".to_string(),
                json!(retry_status),
            );
            metadata.insert(
                "worker_stream_orphan_retry_reason".to_string(),
                json!(retry_reason.clone()),
            );
            metadata.insert(
                "worker_stream_orphan_retry_exhausted".to_string(),
                json!(retry_exhausted),
            );
            metadata.insert(
                "worker_stream_orphan_retry_count".to_string(),
                json!(retry_count),
            );
            metadata.insert(
                "worker_stream_orphan_retry_max_retries".to_string(),
                json!(max_retries),
            );
            node.metadata_json = Value::Object(metadata);
            self.store.save_plan_node(node.clone()).await?;

            let retry_event_type = if retry_exhausted {
                "worker_stream_orphan_retry_exhausted"
            } else {
                "worker_stream_orphan_retry_admitted"
            };
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node.id.clone()),
                    attempt_id: Some(attempt_id.to_string()),
                    event_type: retry_event_type.to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "retry_reason": retry_reason.clone(),
                        "summary": attempt.candidate_summary.clone(),
                        "retry_exhausted": retry_exhausted,
                        "retry_count": retry_count,
                        "max_retries": max_retries,
                    }),
                    created_at: now,
                })
                .await?;

            if !retry_exhausted {
                let mut retry_payload = payload.clone();
                retry_payload.insert(
                    "retry_origin".to_string(),
                    json!("worker_stream_orphan_report"),
                );
                retry_payload.insert(
                    "worker_stream_orphan_retry_reason".to_string(),
                    json!(retry_reason.clone()),
                );
                if let Some(summary) = attempt.candidate_summary.as_deref() {
                    retry_payload
                        .insert("worker_stream_orphan_summary".to_string(), json!(summary));
                }
                self.store
                    .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                        item,
                        &retry_payload,
                        workspace_id,
                        plan_id,
                        &node.id,
                        task_id,
                        worker_agent_id,
                        actor_user_id,
                        leader_agent_id,
                        root_goal_task_id,
                        Some(attempt_id),
                        &retry_reason,
                        now,
                    ))
                    .await?;
            }
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert(
            "reported_attempt_reconciled_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "reported_attempt_status".to_string(),
            json!(AWAITING_LEADER_ADJUDICATION_STATUS),
        );
        metadata.insert(
            "worker_report_supervisor_tick_status".to_string(),
            json!("reported_candidate_observed"),
        );
        node.execution = "reported".to_string();
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node.clone()).await?;
        self.store
            .create_plan_event(WorkspacePlanEventRecord {
                id: generate_uuid_v4(),
                plan_id: plan_id.to_string(),
                workspace_id: workspace_id.to_string(),
                node_id: Some(node.id.clone()),
                attempt_id: Some(attempt_id.to_string()),
                event_type: "auto_reported_attempt_reconciled".to_string(),
                source: "workspace_plan_supervisor_tick".to_string(),
                actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                payload_json: json!({
                    "reason": "worker_report_supervisor_tick",
                    "node_ids": [node.id]
                }),
                created_at: now,
            })
            .await?;
        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }

    async fn reopen_failed_worktree_integration_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if !done_node_needs_worktree_integration_retry(&node) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let previous_metadata = object_or_empty(node.metadata_json.clone());
            let previous_attempt_id =
                metadata_string(previous_metadata.get("worktree_integration_attempt_id"))
                    .or_else(|| node.current_attempt_id.clone());
            let previous_commit_ref = node_verified_commit_ref(&node);
            let previous_summary =
                metadata_string(previous_metadata.get("worktree_integration_summary"))
                    .unwrap_or_else(|| "accepted worktree integration failed".to_string());

            let mut metadata =
                clear_failed_worktree_retry_stale_attempt_metadata(previous_metadata);
            metadata.insert("last_verification_passed".to_string(), json!(false));
            metadata.insert(
                "last_verification_summary".to_string(),
                json!(format!(
                    "accepted worktree integration failed after verification: {previous_summary}"
                )),
            );
            metadata.insert(
                "terminal_attempt_retry_reason".to_string(),
                json!("worktree_integration_failed"),
            );
            metadata.insert(
                "worktree_integration_failed_done_reopened_at".to_string(),
                json!(now.to_rfc3339()),
            );
            if let Some(previous_attempt_id) = previous_attempt_id.as_deref() {
                metadata.insert(
                    "worktree_integration_failed_previous_attempt_id".to_string(),
                    json!(previous_attempt_id),
                );
            }
            if let Some(previous_commit_ref) = previous_commit_ref.as_deref() {
                metadata.insert(
                    "worktree_integration_failed_previous_commit_ref".to_string(),
                    json!(previous_commit_ref),
                );
            }
            metadata.insert(
                "worktree_integration_failed_previous_summary".to_string(),
                json!(previous_summary.clone()),
            );

            let node_id = node.id.clone();
            node.intent = "todo".to_string();
            node.execution = "idle".to_string();
            node.assignee_agent_id = None;
            node.current_attempt_id = None;
            node.feature_checkpoint_json =
                reset_feature_checkpoint(node.feature_checkpoint_json.clone());
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            node.completed_at = None;
            self.store.save_plan_node(node.clone()).await?;
            changed += 1;

            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node_id.clone()),
                    attempt_id: previous_attempt_id.clone(),
                    event_type: "worktree_integration_failed_done_node_reopened".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "previous_attempt_id": previous_attempt_id,
                        "previous_commit_ref": previous_commit_ref,
                        "summary": "done node reopened because accepted worktree integration failed",
                        "worktree_integration_summary": previous_summary,
                    }),
                    created_at: now,
                })
                .await?;

            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node_id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    previous_attempt_id.as_deref(),
                    "worktree_integration_failed",
                    now,
                ))
                .await?;
        }
        Ok(changed)
    }

    async fn recover_missing_attempt_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if supervisor_blocked_human_metadata_present(&object_or_empty(
                node.metadata_json.clone(),
            )) {
                continue;
            }
            let Some(attempt_id) = recoverable_node_attempt_id(&node) else {
                continue;
            };
            if self
                .store
                .get_task_session_attempt(&attempt_id)
                .await?
                .is_some()
            {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let node_id = node.id.clone();
            let retry_exhausted = release_node_for_terminal_retry(
                &mut node,
                "missing_attempt",
                now,
                plan_terminal_attempt_max_retries(),
            );
            self.store.save_plan_node(node).await?;
            changed += 1;

            if retry_exhausted {
                continue;
            }
            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node_id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    Some(&attempt_id),
                    "missing_attempt",
                    now,
                ))
                .await?;
        }
        Ok(changed)
    }

    async fn dispatch_ready_dirty_main_dependency_node(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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
        nodes.sort_by(|left, right| {
            left.priority
                .cmp(&right.priority)
                .then_with(|| left.id.cmp(&right.id))
        });
        let nodes_by_id = nodes
            .iter()
            .map(|node| (node.id.clone(), node.clone()))
            .collect::<HashMap<_, _>>();

        for mut node in nodes {
            if !dirty_main_dependency_dispatch_candidate(&node) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };
            if self
                .store
                .find_active_task_session_attempt(&context.task_id)
                .await?
                .is_some()
            {
                continue;
            }
            let (blocking_dependencies, dirty_main_seed_dependencies) =
                dependency_dispatch_blockers(&node, &nodes_by_id);
            if !blocking_dependencies.is_empty() || dirty_main_seed_dependencies.is_empty() {
                continue;
            }

            let dependency_base_ref = dependency_base_ref_for_dispatch(&node, &nodes_by_id);
            if let Some(base_ref) = dependency_base_ref.as_deref() {
                node.feature_checkpoint_json = feature_checkpoint_with_base_ref(
                    node.feature_checkpoint_json.clone(),
                    base_ref,
                );
            }
            let now = Utc::now();
            let mut metadata = object_or_empty(node.metadata_json.clone());
            metadata.insert(
                "dirty_main_dependency_dispatch_status".to_string(),
                json!("queued"),
            );
            metadata.insert(
                "dirty_main_dependency_dispatch_outbox_id".to_string(),
                json!(item.id.clone()),
            );
            metadata.insert(
                "dirty_main_dependency_dispatch_queued_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "dirty_main_dependency_seed_node_ids".to_string(),
                json!(dirty_main_seed_dependencies),
            );
            if let Some(base_ref) = dependency_base_ref.as_deref() {
                metadata.insert(
                    "dirty_main_dependency_base_ref".to_string(),
                    json!(base_ref),
                );
            }
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node.id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    None,
                    "dirty_main_dependency_ready",
                    now,
                ))
                .await?;
            return Ok(1);
        }

        Ok(0)
    }

    async fn reconcile_accepted_terminal_attempt_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if supervisor_blocked_human_metadata_present(&object_or_empty(
                node.metadata_json.clone(),
            )) {
                continue;
            }
            let Some(attempt_id) = recoverable_node_attempt_id(&node) else {
                continue;
            };
            let Some(mut attempt) = self.store.get_task_session_attempt(&attempt_id).await? else {
                continue;
            };
            if attempt.status.trim().to_ascii_lowercase() != ACCEPTED_ATTEMPT_STATUS {
                if !done_idle_node_has_accepted_supervisor_judge(&node) {
                    continue;
                }
                let summary = accepted_supervisor_judge_summary(&node, &attempt);
                let Some(updated) = self
                    .store
                    .finish_task_session_attempt(
                        &attempt_id,
                        ACCEPTED_ATTEMPT_STATUS,
                        Some(&summary),
                        Some("supervisor_decision_accept_node_reconciled"),
                        now,
                    )
                    .await?
                else {
                    continue;
                };
                attempt = updated;
            }
            if self
                .accepted_projection_already_complete(workspace_id, &node, &attempt)
                .await?
            {
                continue;
            }
            if !accepted_attempt_matches_node_expected_commit(&node, &attempt) {
                continue;
            }

            let evidence_refs = accepted_attempt_evidence_refs(&attempt);
            let commit_ref = first_valid_commit_ref(&evidence_refs);
            let git_diff_summary = first_prefixed_ref(&evidence_refs, "git_diff_summary:");
            let test_commands = prefixed_refs(&evidence_refs, "test_run:");
            let summary = accepted_attempt_summary(&attempt);
            let Some(integration_metadata) = self
                .project_accepted_attempt_to_task(
                    workspace_id,
                    &node,
                    &attempt,
                    &summary,
                    &evidence_refs,
                    commit_ref.as_deref(),
                    git_diff_summary.as_deref(),
                    &test_commands,
                    now,
                )
                .await?
            else {
                continue;
            };

            let mut metadata = accepted_attempt_projection_base_metadata(&node, &attempt);
            metadata.insert(
                "terminal_attempt_status".to_string(),
                json!(ACCEPTED_ATTEMPT_STATUS),
            );
            metadata.insert(
                "terminal_attempt_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert("last_verification_summary".to_string(), json!(summary));
            metadata.insert("last_verification_passed".to_string(), json!(true));
            metadata.insert("last_verification_hard_fail".to_string(), json!(false));
            metadata.insert(
                "last_verification_attempt_id".to_string(),
                json!(attempt.id.clone()),
            );
            metadata.insert(
                "last_verification_ran_at".to_string(),
                json!(now.to_rfc3339()),
            );
            if !attempt.candidate_artifacts_json.is_empty() {
                metadata.insert(
                    "candidate_artifacts".to_string(),
                    json!(attempt.candidate_artifacts_json.clone()),
                );
            }
            if !attempt.candidate_verifications_json.is_empty() {
                metadata.insert(
                    "candidate_verifications".to_string(),
                    json!(attempt.candidate_verifications_json.clone()),
                );
            }
            metadata.extend(integration_metadata);
            node.intent = "done".to_string();
            node.execution = "idle".to_string();
            node.current_attempt_id = Some(attempt.id.clone());
            node.feature_checkpoint_json =
                accepted_attempt_projection_feature_checkpoint(&node, &attempt);
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node).await?;
            changed += 1;
        }
        Ok(changed)
    }

    async fn reconcile_supervisor_request_pipeline_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if node.intent == "done" {
                continue;
            }
            let mut metadata = object_or_empty(node.metadata_json.clone());
            if !supervisor_request_pipeline_metadata_present(&metadata) {
                continue;
            }
            if supervisor_request_pipeline_projection_complete(&metadata) {
                continue;
            }

            let attempt_id = node
                .current_attempt_id
                .clone()
                .or_else(|| metadata_string(metadata.get("last_verification_attempt_id")));
            let mut evidence_refs = Vec::new();
            let summary = supervisor_request_pipeline_summary(&metadata);
            if let Some(attempt_id) = attempt_id.as_deref() {
                if let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? {
                    evidence_refs = accepted_attempt_evidence_refs(&attempt);
                    if !attempt.candidate_artifacts_json.is_empty() {
                        metadata.insert(
                            "candidate_artifacts".to_string(),
                            json!(attempt.candidate_artifacts_json.clone()),
                        );
                    }
                    if !attempt.candidate_verifications_json.is_empty() {
                        metadata.insert(
                            "candidate_verifications".to_string(),
                            json!(attempt.candidate_verifications_json.clone()),
                        );
                    }
                }
            }
            for value in metadata_string_values(metadata.get("verification_evidence_refs")) {
                if !value.trim().is_empty() {
                    evidence_refs.push(value);
                }
            }
            if let Some(commit_ref) = supervisor_pipeline_source_commit_ref(&metadata) {
                evidence_refs.push(format!("commit_ref:{commit_ref}"));
                metadata.insert("verified_commit_ref".to_string(), json!(commit_ref.clone()));
                metadata.insert(
                    "source_publish_source_commit_ref".to_string(),
                    json!(commit_ref),
                );
            }
            dedup_strings(&mut evidence_refs);

            let outbox = supervisor_request_pipeline_outbox(
                workspace_id,
                plan_id,
                &node.id,
                attempt_id.as_deref(),
                &summary,
                &metadata,
                now,
            );
            let outbox_id = outbox.id.clone();

            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert("pipeline_required".to_string(), json!(true));
            metadata
                .entry("pipeline_provider".to_string())
                .or_insert_with(|| json!("sandbox_native"));
            metadata.insert("pipeline_status".to_string(), json!("requested"));
            metadata.insert("pipeline_gate_status".to_string(), json!("requested"));
            metadata.insert(
                "pipeline_request_count".to_string(),
                json!(metadata_positive_i64(metadata.get("pipeline_request_count")) + 1),
            );
            metadata.insert("pipeline_requested_at".to_string(), json!(now.to_rfc3339()));
            metadata.insert(
                "pipeline_request_reason".to_string(),
                json!(SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON),
            );
            metadata.insert(
                "supervisor_pipeline_requested_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "supervisor_pipeline_outbox_id".to_string(),
                json!(outbox_id.clone()),
            );
            metadata.insert(
                "last_verification_summary".to_string(),
                json!(summary.clone()),
            );
            metadata.insert("last_verification_passed".to_string(), json!(false));
            metadata.insert("last_verification_hard_fail".to_string(), json!(false));
            if let Some(attempt_id) = attempt_id.as_deref() {
                metadata.insert(
                    "last_verification_attempt_id".to_string(),
                    json!(attempt_id),
                );
                metadata.insert(
                    "pipeline_requested_attempt_id".to_string(),
                    json!(attempt_id),
                );
            }
            if !evidence_refs.is_empty() {
                metadata.insert(
                    "verification_evidence_refs".to_string(),
                    json!(evidence_refs),
                );
            }
            node.intent = "in_progress".to_string();
            node.execution = "idle".to_string();
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            self.store.enqueue_plan_outbox(outbox).await?;
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node.id.clone()),
                    attempt_id: attempt_id.clone(),
                    event_type: "supervisor_request_pipeline_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "action": SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION,
                        "reason": SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON,
                        "rationale": summary,
                        "workspace_task_id": node.workspace_task_id.clone(),
                        "attempt_id": attempt_id,
                        "outbox_id": outbox_id,
                    }),
                    created_at: now,
                })
                .await?;
            changed += 1;
        }
        Ok(changed)
    }

    async fn reconcile_supervisor_wait_pipeline_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if node.intent == "done" {
                continue;
            }
            let mut metadata = object_or_empty(node.metadata_json.clone());
            if !supervisor_wait_pipeline_metadata_present(&metadata) {
                continue;
            }
            if supervisor_wait_pipeline_projection_complete(&metadata) {
                continue;
            }

            let attempt_id = node
                .current_attempt_id
                .clone()
                .or_else(|| metadata_string(metadata.get("last_verification_attempt_id")));
            let mut evidence_refs = Vec::new();
            let summary = supervisor_wait_pipeline_summary(&metadata);
            if let Some(attempt_id) = attempt_id.as_deref() {
                if let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? {
                    evidence_refs = accepted_attempt_evidence_refs(&attempt);
                    if !attempt.candidate_artifacts_json.is_empty() {
                        metadata.insert(
                            "candidate_artifacts".to_string(),
                            json!(attempt.candidate_artifacts_json.clone()),
                        );
                    }
                    if !attempt.candidate_verifications_json.is_empty() {
                        metadata.insert(
                            "candidate_verifications".to_string(),
                            json!(attempt.candidate_verifications_json.clone()),
                        );
                    }
                }
            }
            for value in metadata_string_values(metadata.get("verification_evidence_refs")) {
                if !value.trim().is_empty() {
                    evidence_refs.push(value);
                }
            }
            if let Some(commit_ref) = supervisor_pipeline_source_commit_ref(&metadata) {
                evidence_refs.push(format!("commit_ref:{commit_ref}"));
                metadata.insert("verified_commit_ref".to_string(), json!(commit_ref.clone()));
                metadata.insert(
                    "source_publish_source_commit_ref".to_string(),
                    json!(commit_ref),
                );
            }
            dedup_strings(&mut evidence_refs);

            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_WAIT_PIPELINE_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert("pipeline_required".to_string(), json!(true));
            let provider = metadata_string(metadata.get("pipeline_provider"))
                .unwrap_or_else(|| "sandbox_native".to_string());
            let pipeline_status = metadata_string(metadata.get("pipeline_status"))
                .unwrap_or_else(|| "requested".to_string());
            let pipeline_gate_status = metadata_string(metadata.get("pipeline_gate_status"))
                .unwrap_or_else(|| "requested".to_string());
            metadata.insert("pipeline_provider".to_string(), json!(provider));
            metadata.insert("pipeline_status".to_string(), json!(pipeline_status));
            metadata.insert(
                "pipeline_gate_status".to_string(),
                json!(pipeline_gate_status),
            );
            metadata.insert(
                "pipeline_wait_reason".to_string(),
                json!(SUPERVISOR_DECISION_WAIT_PIPELINE_REASON),
            );
            metadata.insert(
                "supervisor_wait_pipeline_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "last_verification_summary".to_string(),
                json!(summary.clone()),
            );
            metadata.insert("last_verification_passed".to_string(), json!(false));
            metadata.insert("last_verification_hard_fail".to_string(), json!(false));
            if let Some(attempt_id) = attempt_id.as_deref() {
                metadata.insert(
                    "last_verification_attempt_id".to_string(),
                    json!(attempt_id),
                );
                metadata.insert("pipeline_wait_attempt_id".to_string(), json!(attempt_id));
            }
            if !evidence_refs.is_empty() {
                metadata.insert(
                    "verification_evidence_refs".to_string(),
                    json!(evidence_refs),
                );
            }
            node.intent = "in_progress".to_string();
            node.execution = "reported".to_string();
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node.id.clone()),
                    attempt_id: attempt_id.clone(),
                    event_type: "supervisor_wait_pipeline_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "action": SUPERVISOR_DECISION_WAIT_PIPELINE_ACTION,
                        "reason": SUPERVISOR_DECISION_WAIT_PIPELINE_REASON,
                        "rationale": summary,
                        "workspace_task_id": node.workspace_task_id.clone(),
                        "attempt_id": attempt_id,
                    }),
                    created_at: now,
                })
                .await?;
            changed += 1;
        }
        Ok(changed)
    }

    async fn reconcile_supervisor_noop_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if node.intent == "done" {
                continue;
            }
            let mut metadata = object_or_empty(node.metadata_json.clone());
            if !supervisor_noop_metadata_present(&metadata) {
                continue;
            }
            if supervisor_noop_projection_complete(&metadata) {
                continue;
            }

            let attempt_id = node
                .current_attempt_id
                .clone()
                .or_else(|| metadata_string(metadata.get("last_verification_attempt_id")));
            let summary = supervisor_noop_summary(&metadata);
            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_NOOP_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "supervisor_noop_reason".to_string(),
                json!(SUPERVISOR_DECISION_NOOP_REASON),
            );
            metadata.insert(
                "supervisor_noop_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            if let Some(attempt_id) = attempt_id.as_deref() {
                metadata.insert("supervisor_noop_attempt_id".to_string(), json!(attempt_id));
            }

            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node.id.clone()),
                    attempt_id: attempt_id.clone(),
                    event_type: "supervisor_noop_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "action": SUPERVISOR_DECISION_NOOP_ACTION,
                        "reason": SUPERVISOR_DECISION_NOOP_REASON,
                        "rationale": summary,
                        "workspace_task_id": node.workspace_task_id.clone(),
                        "attempt_id": attempt_id,
                    }),
                    created_at: now,
                })
                .await?;
            changed += 1;
        }
        Ok(changed)
    }

    async fn reconcile_supervisor_create_repair_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let now = Utc::now();
        let nodes = self.store.list_plan_nodes(plan_id).await?;
        let nodes_by_id = nodes
            .iter()
            .map(|node| (node.id.clone(), node.clone()))
            .collect::<HashMap<_, _>>();
        let mut changed = 0;
        for mut node in nodes {
            if node.workspace_task_id.as_deref().is_none_or(str::is_empty) {
                continue;
            }
            let mut metadata = object_or_empty(node.metadata_json.clone());
            if !supervisor_create_repair_metadata_present(&metadata) {
                continue;
            }
            if supervisor_create_repair_projection_complete(&node, &metadata, &nodes_by_id) {
                continue;
            }

            let previous_attempt_id = node.current_attempt_id.clone();
            let mut evidence_refs = Vec::new();
            let summary = supervisor_create_repair_summary(&metadata);
            let mut attempt_projected = false;
            if let Some(attempt_id) = previous_attempt_id.as_deref() {
                if let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? {
                    evidence_refs = accepted_attempt_evidence_refs(&attempt);
                    let status = attempt.status.trim().to_ascii_lowercase();
                    if matches!(
                        status.as_str(),
                        "pending" | "running" | AWAITING_LEADER_ADJUDICATION_STATUS
                    ) {
                        self.store
                            .finish_task_session_attempt(
                                attempt_id,
                                REJECTED_ATTEMPT_STATUS,
                                Some(&summary),
                                Some(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_REASON),
                                now,
                            )
                            .await?;
                        attempt_projected = true;
                    }
                    if !attempt.candidate_artifacts_json.is_empty() {
                        metadata.insert(
                            "candidate_artifacts".to_string(),
                            json!(attempt.candidate_artifacts_json.clone()),
                        );
                    }
                    if !attempt.candidate_verifications_json.is_empty() {
                        metadata.insert(
                            "candidate_verifications".to_string(),
                            json!(attempt.candidate_verifications_json.clone()),
                        );
                    }
                }
            }
            for value in metadata_string_values(metadata.get("verification_evidence_refs")) {
                if !value.trim().is_empty() {
                    evidence_refs.push(value);
                }
            }
            dedup_strings(&mut evidence_refs);

            let task_projected = self
                .project_supervisor_create_repair_to_task(
                    workspace_id,
                    &node,
                    previous_attempt_id.as_deref(),
                    &summary,
                    &evidence_refs,
                    now,
                )
                .await?;

            let existing_repair_id = existing_repair_node_id_for_original(&nodes_by_id, &node.id);
            let (repair_node_id, repair_node_created) =
                if let Some(repair_node_id) = existing_repair_id {
                    (repair_node_id, false)
                } else {
                    let repair_node_id = generated_repair_node_id();
                    let repair_node = supervisor_repair_plan_node(
                        &node,
                        &metadata,
                        &repair_node_id,
                        &summary,
                        &evidence_refs,
                        previous_attempt_id.as_deref(),
                        now,
                    );
                    self.store.create_plan_node(repair_node).await?;
                    (repair_node_id, true)
                };

            clear_supervisor_create_repair_node_metadata(&mut metadata);
            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "last_verification_judge_verdict".to_string(),
                json!("needs_rework"),
            );
            metadata.insert(
                "last_verification_judge_next_action_kind".to_string(),
                json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
            );
            metadata.insert(
                "last_verification_judge_required_next_action".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "blocked_by_repair_node_id".to_string(),
                json!(repair_node_id.clone()),
            );
            metadata.insert(
                "supervisor_repair_node_id".to_string(),
                json!(repair_node_id.clone()),
            );
            metadata.insert(
                "supervisor_repair_requested_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "workspace_task_projection_status".to_string(),
                json!(SUPERVISOR_REPLAN_REQUESTED_VERDICT),
            );
            metadata.insert(
                "workspace_task_projected_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "replan_source".to_string(),
                json!("verification_judge_create_repair_node"),
            );
            metadata.insert("replan_trigger".to_string(), json!("verification_failed"));
            if let Some(attempt_id) = previous_attempt_id.as_deref() {
                metadata.insert(
                    "supervisor_repair_previous_attempt_id".to_string(),
                    json!(attempt_id),
                );
            }
            if !evidence_refs.is_empty() {
                metadata.insert(
                    "verification_evidence_refs".to_string(),
                    json!(evidence_refs),
                );
            }
            push_unique_string(&mut node.depends_on_json, repair_node_id.clone());
            node.intent = "todo".to_string();
            node.execution = "idle".to_string();
            node.current_attempt_id = None;
            node.metadata_json = Value::Object(metadata);
            node.completed_at = None;
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node.id.clone()),
                    attempt_id: previous_attempt_id.clone(),
                    event_type: "supervisor_create_repair_node_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "action": SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION,
                        "reason": SUPERVISOR_DECISION_CREATE_REPAIR_NODE_REASON,
                        "rationale": summary,
                        "workspace_task_id": node.workspace_task_id.clone(),
                        "previous_attempt_id": previous_attempt_id,
                        "repair_node_id": repair_node_id,
                        "repair_node_created": repair_node_created,
                        "task_projected": task_projected,
                        "attempt_projected": attempt_projected,
                    }),
                    created_at: now,
                })
                .await?;
            changed += 1;
        }
        Ok(changed)
    }

    async fn project_supervisor_create_repair_to_task(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt_id: Option<&str>,
        summary: &str,
        evidence_refs: &[String],
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let Some(task_id) = node.workspace_task_id.as_deref() else {
            return Ok(false);
        };
        let Some(mut task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(false);
        };
        if task.workspace_id != workspace_id {
            return Ok(false);
        }
        let mut metadata = object_or_empty(task.metadata_json.clone());
        if task.status == "in_progress"
            && metadata_string(metadata.get("durable_plan_verdict")).as_deref()
                == Some(SUPERVISOR_REPLAN_REQUESTED_VERDICT)
            && metadata_string(metadata.get("durable_plan_verification_summary")).as_deref()
                == Some(summary)
            && metadata_string(metadata.get("supervisor_repair_requested_at")).is_some()
        {
            return Ok(false);
        }

        metadata.insert(PENDING_LEADER_ADJUDICATION.to_string(), json!(false));
        metadata.remove("retry_verification_only");
        metadata.insert(
            "durable_plan_verdict".to_string(),
            json!(SUPERVISOR_REPLAN_REQUESTED_VERDICT),
        );
        metadata.insert(
            "durable_plan_verification_summary".to_string(),
            json!(summary),
        );
        metadata.insert(
            "durable_plan_verified_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "supervisor_repair_requested_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "last_attempt_status".to_string(),
            json!(REJECTED_ATTEMPT_STATUS),
        );
        metadata.insert(
            "last_worker_report_type".to_string(),
            json!(SUPERVISOR_REPLAN_REQUESTED_VERDICT),
        );
        metadata.insert(LAST_WORKER_REPORT_SUMMARY.to_string(), json!(summary));
        metadata.insert(
            "last_leader_adjudication_status".to_string(),
            json!(REJECTED_ATTEMPT_STATUS),
        );
        metadata.insert(
            "last_supervisor_decision_action".to_string(),
            json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
        );
        if let Some(attempt_id) = attempt_id {
            metadata.insert("last_attempt_id".to_string(), json!(attempt_id));
            metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        if !evidence_refs.is_empty() {
            metadata.insert("evidence_refs".to_string(), json!(evidence_refs));
        }

        task.metadata_json = Value::Object(metadata);
        task.status = "in_progress".to_string();
        task.blocker_reason = None;
        task.completed_at = None;
        task.updated_at = Some(now);
        self.store.save_task(task).await?;
        Ok(true)
    }

    async fn reconcile_supervisor_replan_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if node.workspace_task_id.as_deref().is_none_or(str::is_empty) {
                continue;
            }
            let mut metadata = object_or_empty(node.metadata_json.clone());
            if !supervisor_replan_metadata_present(&metadata) {
                continue;
            }
            if node.current_attempt_id.is_none()
                && node.intent == "todo"
                && node.execution == "idle"
                && metadata_string(metadata.get("workspace_task_projection_status")).as_deref()
                    == Some(SUPERVISOR_REPLAN_REQUESTED_VERDICT)
                && metadata_string(metadata.get("supervisor_replan_outbox_id")).is_some()
            {
                continue;
            }

            let previous_attempt_id = node.current_attempt_id.clone();
            let replan_task_id = node.workspace_task_id.clone();
            let replan_worker_agent_id = node.assignee_agent_id.clone();
            let mut evidence_refs = Vec::new();
            let summary = supervisor_replan_summary(&metadata);
            let mut attempt_projected = false;
            if let Some(attempt_id) = previous_attempt_id.as_deref() {
                if let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? {
                    evidence_refs = accepted_attempt_evidence_refs(&attempt);
                    let status = attempt.status.trim().to_ascii_lowercase();
                    if matches!(
                        status.as_str(),
                        "pending" | "running" | AWAITING_LEADER_ADJUDICATION_STATUS
                    ) {
                        self.store
                            .finish_task_session_attempt(
                                attempt_id,
                                REJECTED_ATTEMPT_STATUS,
                                Some(&summary),
                                Some(SUPERVISOR_DECISION_REPLAN_NODE_REASON),
                                now,
                            )
                            .await?;
                        attempt_projected = true;
                    }
                    if !attempt.candidate_artifacts_json.is_empty() {
                        metadata.insert(
                            "candidate_artifacts".to_string(),
                            json!(attempt.candidate_artifacts_json.clone()),
                        );
                    }
                    if !attempt.candidate_verifications_json.is_empty() {
                        metadata.insert(
                            "candidate_verifications".to_string(),
                            json!(attempt.candidate_verifications_json.clone()),
                        );
                    }
                }
            }
            for value in metadata_string_values(metadata.get("verification_evidence_refs")) {
                if !value.trim().is_empty() {
                    evidence_refs.push(value);
                }
            }
            dedup_strings(&mut evidence_refs);

            let task_projected = self
                .project_supervisor_replan_to_task(
                    workspace_id,
                    &node,
                    previous_attempt_id.as_deref(),
                    &summary,
                    &evidence_refs,
                    now,
                )
                .await?;

            clear_supervisor_replan_node_metadata(&mut metadata);
            let confidence = node
                .progress_json
                .get("confidence")
                .and_then(Value::as_f64)
                .unwrap_or(0.0);
            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_REPLAN_NODE_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "supervisor_replan_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "workspace_task_projection_status".to_string(),
                json!(SUPERVISOR_REPLAN_REQUESTED_VERDICT),
            );
            metadata.insert(
                "workspace_task_projected_at".to_string(),
                json!(now.to_rfc3339()),
            );
            if let Some(attempt_id) = previous_attempt_id.as_deref() {
                metadata.insert(
                    "supervisor_replan_previous_attempt_id".to_string(),
                    json!(attempt_id),
                );
            }
            if !evidence_refs.is_empty() {
                metadata.insert(
                    "verification_evidence_refs".to_string(),
                    json!(evidence_refs),
                );
            }
            metadata.insert(
                "operator_action".to_string(),
                json!({
                    "action": "operator_replan_requested",
                    "actor_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
                    "reason": summary,
                    "created_at": now.to_rfc3339(),
                    "source": "supervisor_decision"
                }),
            );

            node.intent = "todo".to_string();
            node.execution = "idle".to_string();
            node.progress_json = json!({
                "percent": 0,
                "confidence": confidence,
                "note": "Supervisor requested replan."
            });
            node.assignee_agent_id = None;
            node.current_attempt_id = None;
            node.feature_checkpoint_json = reset_feature_checkpoint(node.feature_checkpoint_json);
            node.metadata_json = Value::Object(metadata);
            node.completed_at = None;
            node.updated_at = Some(now);

            let replan_outbox = supervisor_replan_tick_outbox(
                workspace_id,
                plan_id,
                &node.id,
                replan_task_id.as_deref(),
                replan_worker_agent_id.as_deref(),
                &summary,
                previous_attempt_id.as_deref(),
                now,
            );
            let replan_outbox_id = replan_outbox.id.clone();
            let mut node_metadata = object_or_empty(node.metadata_json.clone());
            node_metadata.insert(
                "supervisor_replan_outbox_id".to_string(),
                json!(replan_outbox_id.clone()),
            );
            node.metadata_json = Value::Object(node_metadata);
            self.store.save_plan_node(node.clone()).await?;
            self.store.enqueue_plan_outbox(replan_outbox).await?;
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node.id.clone()),
                    attempt_id: previous_attempt_id.clone(),
                    event_type: "supervisor_replan_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "action": SUPERVISOR_DECISION_REPLAN_NODE_ACTION,
                        "reason": SUPERVISOR_DECISION_REPLAN_NODE_REASON,
                        "rationale": summary,
                        "workspace_task_id": node.workspace_task_id.clone(),
                        "previous_attempt_id": previous_attempt_id,
                        "task_projected": task_projected,
                        "attempt_projected": attempt_projected,
                        "outbox_id": replan_outbox_id,
                    }),
                    created_at: now,
                })
                .await?;
            changed += 1;
        }
        Ok(changed)
    }

    async fn project_supervisor_replan_to_task(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt_id: Option<&str>,
        summary: &str,
        evidence_refs: &[String],
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let Some(task_id) = node.workspace_task_id.as_deref() else {
            return Ok(false);
        };
        let Some(mut task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(false);
        };
        if task.workspace_id != workspace_id {
            return Ok(false);
        }
        let mut metadata = object_or_empty(task.metadata_json.clone());
        if task.status == "in_progress"
            && metadata_string(metadata.get("durable_plan_verdict")).as_deref()
                == Some(SUPERVISOR_REPLAN_REQUESTED_VERDICT)
            && metadata_string(metadata.get("durable_plan_verification_summary")).as_deref()
                == Some(summary)
            && metadata_string(metadata.get("supervisor_replan_requested_at")).is_some()
        {
            return Ok(false);
        }

        metadata.insert(PENDING_LEADER_ADJUDICATION.to_string(), json!(false));
        metadata.remove("retry_verification_only");
        metadata.insert(
            "durable_plan_verdict".to_string(),
            json!(SUPERVISOR_REPLAN_REQUESTED_VERDICT),
        );
        metadata.insert(
            "durable_plan_verification_summary".to_string(),
            json!(summary),
        );
        metadata.insert(
            "durable_plan_verified_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "supervisor_replan_requested_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "last_attempt_status".to_string(),
            json!(REJECTED_ATTEMPT_STATUS),
        );
        metadata.insert(
            "last_worker_report_type".to_string(),
            json!(SUPERVISOR_REPLAN_REQUESTED_VERDICT),
        );
        metadata.insert(LAST_WORKER_REPORT_SUMMARY.to_string(), json!(summary));
        metadata.insert(
            "last_leader_adjudication_status".to_string(),
            json!(REJECTED_ATTEMPT_STATUS),
        );
        metadata.insert(
            "last_supervisor_decision_action".to_string(),
            json!(SUPERVISOR_DECISION_REPLAN_NODE_ACTION),
        );
        if let Some(attempt_id) = attempt_id {
            metadata.insert("last_attempt_id".to_string(), json!(attempt_id));
            metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        if !evidence_refs.is_empty() {
            metadata.insert("evidence_refs".to_string(), json!(evidence_refs));
        }

        task.metadata_json = Value::Object(metadata);
        task.status = "in_progress".to_string();
        task.blocker_reason = None;
        task.completed_at = None;
        task.updated_at = Some(now);
        self.store.save_task(task).await?;
        Ok(true)
    }

    async fn reconcile_supervisor_blocked_human_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if node.workspace_task_id.as_deref().is_none_or(str::is_empty) {
                continue;
            }
            let mut metadata = object_or_empty(node.metadata_json.clone());
            if !supervisor_blocked_human_metadata_present(&metadata) {
                continue;
            }

            let summary = supervisor_blocked_human_summary(&metadata);
            let already_projected_node = node.intent == "blocked"
                && node.execution == "idle"
                && metadata_string(metadata.get("last_verification_judge_verdict")).as_deref()
                    == Some(SUPERVISOR_BLOCKED_HUMAN_VERDICT)
                && metadata_string(metadata.get("workspace_task_projection_status")).as_deref()
                    == Some("blocked");
            let mut attempt_projected = false;
            let mut evidence_refs = Vec::new();
            if let Some(attempt_id) = node.current_attempt_id.as_deref() {
                if let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? {
                    evidence_refs = accepted_attempt_evidence_refs(&attempt);
                    let status = attempt.status.trim().to_ascii_lowercase();
                    if status == AWAITING_LEADER_ADJUDICATION_STATUS {
                        self.store
                            .finish_task_session_attempt(
                                attempt_id,
                                "blocked",
                                Some(&summary),
                                Some(SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_REASON),
                                now,
                            )
                            .await?;
                        attempt_projected = true;
                    }
                    if !attempt.candidate_artifacts_json.is_empty() {
                        metadata.insert(
                            "candidate_artifacts".to_string(),
                            json!(attempt.candidate_artifacts_json.clone()),
                        );
                    }
                    if !attempt.candidate_verifications_json.is_empty() {
                        metadata.insert(
                            "candidate_verifications".to_string(),
                            json!(attempt.candidate_verifications_json.clone()),
                        );
                    }
                }
            }
            for value in metadata_string_values(metadata.get("verification_evidence_refs")) {
                if !value.trim().is_empty() {
                    evidence_refs.push(value);
                }
            }
            dedup_strings(&mut evidence_refs);

            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "last_verification_judge_verdict".to_string(),
                json!(SUPERVISOR_BLOCKED_HUMAN_VERDICT),
            );
            metadata.insert("last_verification_passed".to_string(), json!(false));
            metadata.insert("last_verification_hard_fail".to_string(), json!(true));
            metadata.insert(
                "last_verification_summary".to_string(),
                json!(summary.clone()),
            );
            if let Some(attempt_id) = node.current_attempt_id.as_deref() {
                metadata.insert(
                    "last_verification_attempt_id".to_string(),
                    json!(attempt_id),
                );
                metadata.insert("terminal_attempt_status".to_string(), json!("blocked"));
            }
            metadata.insert(
                "supervisor_blocked_human_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "workspace_task_projection_status".to_string(),
                json!("blocked"),
            );
            metadata.insert(
                "workspace_task_projected_at".to_string(),
                json!(now.to_rfc3339()),
            );
            if !evidence_refs.is_empty() {
                metadata.insert(
                    "verification_evidence_refs".to_string(),
                    json!(evidence_refs),
                );
            }

            node.intent = "blocked".to_string();
            node.execution = "idle".to_string();
            node.metadata_json = Value::Object(metadata.clone());
            node.updated_at = Some(now);

            let task_projected = self
                .project_supervisor_blocked_human_to_task(workspace_id, &node, &summary, now)
                .await?;
            if !already_projected_node || task_projected || attempt_projected {
                self.store.save_plan_node(node.clone()).await?;
                self.store
                    .create_plan_event(WorkspacePlanEventRecord {
                        id: generate_uuid_v4(),
                        plan_id: plan_id.to_string(),
                        workspace_id: workspace_id.to_string(),
                        node_id: Some(node.id.clone()),
                        attempt_id: node.current_attempt_id.clone(),
                        event_type: "supervisor_blocked_human_reconciled".to_string(),
                        source: "workspace_plan_supervisor_tick".to_string(),
                        actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                        payload_json: json!({
                            "action": SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_ACTION,
                            "reason": SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_REASON,
                            "rationale": summary,
                            "workspace_task_id": node.workspace_task_id.clone(),
                            "task_projected": task_projected,
                            "attempt_projected": attempt_projected,
                        }),
                        created_at: now,
                    })
                    .await?;
                changed += 1;
            }
        }
        Ok(changed)
    }

    async fn project_supervisor_blocked_human_to_task(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        summary: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let Some(task_id) = node.workspace_task_id.as_deref() else {
            return Ok(false);
        };
        let Some(mut task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(false);
        };
        if task.workspace_id != workspace_id {
            return Ok(false);
        }
        let mut metadata = object_or_empty(task.metadata_json.clone());
        if task.status == "blocked"
            && task.blocker_reason.as_deref() == Some(summary)
            && metadata_string(metadata.get("durable_plan_verdict")).as_deref() == Some("blocked")
            && metadata_string(metadata.get("durable_plan_verification_summary")).as_deref()
                == Some(summary)
        {
            return Ok(false);
        }

        metadata.insert(PENDING_LEADER_ADJUDICATION.to_string(), json!(false));
        metadata.insert("durable_plan_verdict".to_string(), json!("blocked"));
        metadata.insert(
            "durable_plan_verification_summary".to_string(),
            json!(summary),
        );
        metadata.insert(
            "durable_plan_verified_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert("last_attempt_status".to_string(), json!("blocked"));
        metadata.insert("last_worker_report_type".to_string(), json!("blocked"));
        metadata.insert(LAST_WORKER_REPORT_SUMMARY.to_string(), json!(summary));
        metadata.insert(
            "last_leader_adjudication_status".to_string(),
            json!("blocked"),
        );
        metadata.insert(
            "last_supervisor_decision_action".to_string(),
            json!(SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_ACTION),
        );
        metadata.insert(
            "last_verification_judge_verdict".to_string(),
            json!(SUPERVISOR_BLOCKED_HUMAN_VERDICT),
        );
        if let Some(attempt_id) = node.current_attempt_id.as_deref() {
            metadata.insert("last_attempt_id".to_string(), json!(attempt_id));
            metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        let node_metadata = object_or_empty(node.metadata_json.clone());
        let evidence_refs = metadata_string_values(node_metadata.get("verification_evidence_refs"));
        if !evidence_refs.is_empty() {
            metadata.insert("evidence_refs".to_string(), json!(evidence_refs));
        }

        task.metadata_json = Value::Object(metadata);
        task.status = "blocked".to_string();
        task.blocker_reason = Some(summary.to_string());
        task.completed_at = None;
        task.updated_at = Some(now);
        let saved_task = self.store.save_task(task).await?;
        if let Some(root_goal_task_id) =
            string_from_value_object(&saved_task.metadata_json, ROOT_GOAL_TASK_ID)
        {
            if root_goal_task_id != saved_task.id {
                self.reconcile_root_goal_progress(workspace_id, &root_goal_task_id, now)
                    .await?;
            }
        }
        Ok(true)
    }

    async fn reconcile_supervisor_disposed_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if node.workspace_task_id.as_deref().is_none_or(str::is_empty) {
                continue;
            }
            let has_dispose_metadata = supervisor_dispose_metadata_present(&node);
            let has_dispose_event = self
                .store
                .has_supervisor_dispose_decision_for_node(workspace_id, plan_id, &node.id)
                .await?;
            if !has_dispose_metadata && !has_dispose_event {
                continue;
            }

            let mut metadata = object_or_empty(node.metadata_json.clone());
            let disposition = supervisor_disposition_value(&metadata);
            let summary = supervisor_disposition_summary(&metadata);
            let already_projected_node = node.intent == "done"
                && node.execution == "idle"
                && metadata_string(metadata.get("verification_feedback_disposition")).as_deref()
                    == Some(disposition.as_str())
                && metadata_string(metadata.get("workspace_task_projection_status")).as_deref()
                    == Some("done");

            metadata.insert(
                "verification_feedback_disposition".to_string(),
                json!(disposition.clone()),
            );
            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_DISPOSE_NODE_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "supervisor_disposition_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "workspace_task_projection_status".to_string(),
                json!("done"),
            );
            metadata.insert(
                "workspace_task_projected_at".to_string(),
                json!(now.to_rfc3339()),
            );
            node.intent = "done".to_string();
            node.execution = "idle".to_string();
            node.metadata_json = Value::Object(metadata.clone());
            node.updated_at = Some(now);
            if node.completed_at.is_none() {
                node.completed_at = Some(now);
            }

            let task_projected = self
                .project_supervisor_disposition_to_task(
                    workspace_id,
                    &node,
                    &summary,
                    &disposition,
                    now,
                )
                .await?;
            if !already_projected_node || task_projected {
                self.store.save_plan_node(node.clone()).await?;
                self.store
                    .create_plan_event(WorkspacePlanEventRecord {
                        id: generate_uuid_v4(),
                        plan_id: plan_id.to_string(),
                        workspace_id: workspace_id.to_string(),
                        node_id: Some(node.id.clone()),
                        attempt_id: node.current_attempt_id.clone(),
                        event_type: "supervisor_disposition_reconciled".to_string(),
                        source: "workspace_plan_supervisor_tick".to_string(),
                        actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                        payload_json: json!({
                            "action": SUPERVISOR_DECISION_DISPOSE_NODE_ACTION,
                            "disposition": disposition,
                            "rationale": summary,
                            "workspace_task_id": node.workspace_task_id.clone(),
                            "task_projected": task_projected,
                            "had_dispose_event": has_dispose_event,
                        }),
                        created_at: now,
                    })
                    .await?;
                changed += 1;
            }
        }
        Ok(changed)
    }

    async fn project_supervisor_disposition_to_task(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        summary: &str,
        disposition: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let Some(task_id) = node.workspace_task_id.as_deref() else {
            return Ok(false);
        };
        let Some(mut task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(false);
        };
        if task.workspace_id != workspace_id {
            return Ok(false);
        }
        let mut metadata = object_or_empty(task.metadata_json.clone());
        if task.status == "done"
            && metadata_string(metadata.get("durable_plan_verdict")).as_deref() == Some("disposed")
            && metadata_string(metadata.get("durable_plan_disposition")).as_deref()
                == Some(disposition)
            && metadata_string(metadata.get("durable_plan_verification_summary")).as_deref()
                == Some(summary)
        {
            return Ok(false);
        }

        metadata.insert(PENDING_LEADER_ADJUDICATION.to_string(), json!(false));
        metadata.insert("durable_plan_verdict".to_string(), json!("disposed"));
        metadata.insert("durable_plan_disposition".to_string(), json!(disposition));
        metadata.insert(
            "durable_plan_verification_summary".to_string(),
            json!(summary),
        );
        metadata.insert(
            "durable_plan_verified_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "last_attempt_status".to_string(),
            json!(DISPOSED_ATTEMPT_STATUS),
        );
        metadata.insert(
            "last_worker_report_type".to_string(),
            json!(DISPOSED_ATTEMPT_STATUS),
        );
        metadata.insert(LAST_WORKER_REPORT_SUMMARY.to_string(), json!(summary));
        metadata.insert(
            "last_leader_adjudication_status".to_string(),
            json!(DISPOSED_ATTEMPT_STATUS),
        );
        if let Some(attempt_id) = node.current_attempt_id.as_deref() {
            metadata.insert("last_attempt_id".to_string(), json!(attempt_id));
            metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        copy_supervisor_disposition_event_payload_fields(
            &object_or_empty(node.metadata_json.clone()),
            &mut metadata,
        );

        task.metadata_json = Value::Object(metadata);
        task.status = "done".to_string();
        task.blocker_reason = None;
        task.completed_at = Some(now);
        task.updated_at = Some(now);
        let saved_task = self.store.save_task(task).await?;
        if let Some(root_goal_task_id) =
            string_from_value_object(&saved_task.metadata_json, ROOT_GOAL_TASK_ID)
        {
            if root_goal_task_id != saved_task.id {
                self.reconcile_root_goal_progress(workspace_id, &root_goal_task_id, now)
                    .await?;
            }
        }
        Ok(true)
    }

    #[allow(clippy::too_many_arguments)]
    async fn project_accepted_attempt_to_task(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        summary: &str,
        evidence_refs: &[String],
        commit_ref: Option<&str>,
        git_diff_summary: Option<&str>,
        test_commands: &[String],
        now: DateTime<Utc>,
    ) -> CoreResult<Option<Map<String, Value>>> {
        let task_id = node
            .workspace_task_id
            .as_ref()
            .unwrap_or(&attempt.workspace_task_id);
        let Some(mut task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(Some(Map::new()));
        };
        if task.workspace_id != workspace_id {
            return Ok(Some(Map::new()));
        }

        let integration_metadata = self
            .integrate_accepted_attempt_worktree(
                workspace_id,
                node,
                &attempt.id,
                &task,
                commit_ref,
                now,
            )
            .await?;
        let Some(integration_metadata) = integration_metadata else {
            return Ok(None);
        };

        let mut metadata = object_or_empty(task.metadata_json.clone());
        metadata.insert("pending_leader_adjudication".to_string(), json!(false));
        metadata.remove("retry_verification_only");
        metadata.insert("durable_plan_verdict".to_string(), json!("accepted"));
        metadata.insert(
            "durable_plan_verification_summary".to_string(),
            json!(summary),
        );
        metadata.insert(
            "durable_plan_verified_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "last_attempt_status".to_string(),
            json!(ACCEPTED_ATTEMPT_STATUS),
        );
        metadata.insert("last_attempt_id".to_string(), json!(attempt.id.clone()));
        metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt.id.clone()));
        metadata.insert("last_worker_report_type".to_string(), json!("completed"));
        metadata.insert("last_worker_report_summary".to_string(), json!(summary));
        metadata.insert(
            "last_leader_adjudication_status".to_string(),
            json!(ACCEPTED_ATTEMPT_STATUS),
        );
        if !evidence_refs.is_empty() {
            metadata.insert("evidence_refs".to_string(), json!(evidence_refs));
        }
        apply_verification_checkpoint_metadata(
            &mut metadata,
            summary,
            commit_ref,
            git_diff_summary,
            test_commands,
            now,
        );
        metadata.extend(integration_metadata.clone());

        task.metadata_json = Value::Object(metadata);
        task.status = "done".to_string();
        task.blocker_reason = None;
        task.completed_at = Some(now);
        task.updated_at = Some(now);
        let saved_task = self.store.save_task(task).await?;
        self.reconcile_root_goal_progress_for_task(workspace_id, &saved_task, attempt, now)
            .await?;
        Ok(Some(integration_metadata))
    }

    async fn reconcile_root_goal_progress_for_task(
        &self,
        workspace_id: &str,
        task: &WorkspaceTaskRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let Some(root_goal_task_id) = root_goal_task_id_for_progress(task, attempt) else {
            return Ok(());
        };
        if root_goal_task_id == task.id {
            return Ok(());
        }
        self.reconcile_root_goal_progress(workspace_id, &root_goal_task_id, now)
            .await
    }

    async fn reconcile_root_goal_progress(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let Some(mut root_task) = self.store.get_task(workspace_id, root_goal_task_id).await?
        else {
            return Ok(());
        };
        if !is_goal_root_task(&root_task) {
            return Ok(());
        }

        let mut child_tasks = self
            .store
            .list_current_plan_child_tasks_by_root_goal_task_id(workspace_id, root_goal_task_id)
            .await?;
        if child_tasks.is_empty() {
            child_tasks = select_root_progress_child_tasks(
                self.store
                    .list_tasks_by_root_goal_task_id(workspace_id, root_goal_task_id)
                    .await?,
            );
        }

        let active_child_task_ids = child_tasks
            .iter()
            .filter(|task| task.status != "done" && task.archived_at.is_none())
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        let blocked_tasks = child_tasks
            .iter()
            .filter(|task| task.status == "blocked")
            .collect::<Vec<_>>();
        let blocked_child_task_ids = blocked_tasks
            .iter()
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        let in_progress_count = child_tasks
            .iter()
            .filter(|task| task.status == "in_progress")
            .count();
        let done_count = child_tasks
            .iter()
            .filter(|task| task.status == "done")
            .count();
        let assigned_count = child_tasks
            .iter()
            .filter(|task| task.assignee_agent_id.is_some() || task.assignee_user_id.is_some())
            .count();
        let total_count = child_tasks.len();
        let all_children_done = total_count > 0 && done_count == total_count;

        let (goal_health, blocked_reason, remediation_status, remediation_summary) =
            if root_task.status == "done" {
                ("achieved", None, "none", None)
            } else if let Some(blocked_task) = blocked_tasks.first() {
                (
                    "blocked",
                    blocked_task
                        .blocker_reason
                        .clone()
                        .or_else(|| Some(blocked_task.title.clone())),
                    "replan_required",
                    Some(format!(
                        "{} child task(s) blocked; root goal requires replan or intervention",
                        blocked_tasks.len()
                    )),
                )
            } else if in_progress_count > 0 {
                ("healthy", None, "none", None)
            } else if all_children_done {
                (
                "achieved",
                None,
                "ready_for_completion",
                Some(
                    "All child tasks are done; root goal should now validate completion evidence"
                        .to_string(),
                ),
            )
            } else {
                ("healthy", None, "none", None)
            };

        let progress_summary = format!(
            "{done_count}/{total_count} child tasks done; {in_progress_count} in progress; {} blocked; {assigned_count}/{total_count} assigned",
            blocked_tasks.len()
        );
        let mut metadata = object_or_empty(root_task.metadata_json);
        metadata.insert("goal_progress_summary".to_string(), json!(progress_summary));
        metadata.insert("last_progress_at".to_string(), json!(now.to_rfc3339()));
        metadata.insert(
            "active_child_task_ids".to_string(),
            json!(active_child_task_ids),
        );
        metadata.insert(
            "blocked_child_task_ids".to_string(),
            json!(blocked_child_task_ids),
        );
        metadata.insert(
            "blocked_reason".to_string(),
            blocked_reason.map_or(Value::Null, Value::String),
        );
        metadata.insert("goal_health".to_string(), json!(goal_health));
        metadata.insert(REMEDIATION_STATUS.to_string(), json!(remediation_status));
        metadata.insert(
            REMEDIATION_SUMMARY.to_string(),
            remediation_summary.map_or(Value::Null, Value::String),
        );
        root_task.metadata_json = Value::Object(metadata);
        root_task.updated_at = Some(now);
        self.store.save_task(root_task).await?;
        Ok(())
    }

    async fn integrate_accepted_attempt_worktree(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt_id: &str,
        task: &WorkspaceTaskRecord,
        commit_ref: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<Map<String, Value>>> {
        let Some(commit_ref) = commit_ref
            .and_then(commit_ref_token)
            .or_else(|| accepted_attempt_integration_commit_ref(node))
        else {
            return Ok(Some(Map::new()));
        };
        let Some(workspace) = self.store.get_workspace(workspace_id).await? else {
            return Ok(Some(worktree_integration_metadata(
                "skipped",
                "workspace not found",
                attempt_id,
                Some(commit_ref.as_str()),
                None,
                now,
                None,
            )));
        };
        let Some(sandbox_code_root) =
            sandbox_code_root_for_integration(&task.metadata_json, &workspace.metadata_json)
        else {
            return Ok(Some(worktree_integration_metadata(
                "skipped",
                "sandbox_code_root is not available for accepted worktree integration",
                attempt_id,
                Some(commit_ref.as_str()),
                None,
                now,
                None,
            )));
        };
        let Some(worktree_path) = accepted_attempt_worktree_path(
            node,
            &task.metadata_json,
            &sandbox_code_root,
            attempt_id,
        ) else {
            return Ok(Some(worktree_integration_metadata(
                "skipped",
                "accepted attempt has no worktree_path",
                attempt_id,
                Some(commit_ref.as_str()),
                None,
                now,
                None,
            )));
        };
        if normalize_posix_path(&worktree_path) == normalize_posix_path(&sandbox_code_root) {
            let metadata = worktree_integration_metadata(
                "already_merged",
                "accepted attempt already ran in sandbox_code_root",
                attempt_id,
                Some(commit_ref.as_str()),
                Some(worktree_path.as_str()),
                now,
                None,
            );
            self.record_worktree_integration_event(
                workspace_id,
                node,
                attempt_id,
                task,
                &metadata,
                "accepted_worktree_integration_skipped",
                now,
            )
            .await?;
            return Ok(Some(metadata));
        }
        let integration = integrate_accepted_attempt_worktree_with_git(
            Path::new(&sandbox_code_root),
            Path::new(&worktree_path),
            &commit_ref,
        )
        .await?;
        let metadata = worktree_integration_metadata(
            &integration.status,
            &integration.summary,
            attempt_id,
            Some(integration.commit_ref.as_str()),
            Some(worktree_path.as_str()),
            now,
            integration.dirty_signature.as_deref(),
        );
        let event_type = worktree_integration_event_type(&integration.status);
        self.record_worktree_integration_event(
            workspace_id,
            node,
            attempt_id,
            task,
            &metadata,
            event_type,
            now,
        )
        .await?;
        Ok(Some(metadata))
    }

    async fn record_worktree_integration_event(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt_id: &str,
        task: &WorkspaceTaskRecord,
        metadata: &Map<String, Value>,
        event_type: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        self.store
            .create_plan_event(WorkspacePlanEventRecord {
                id: generate_uuid_v4(),
                plan_id: node.plan_id.clone(),
                workspace_id: workspace_id.to_string(),
                node_id: Some(node.id.clone()),
                attempt_id: Some(attempt_id.to_string()),
                event_type: event_type.to_string(),
                source: "workspace_plan.accepted_worktree_integration".to_string(),
                actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                payload_json: json!({
                    "status": metadata.get("worktree_integration_status").cloned().unwrap_or(Value::Null),
                    "summary": metadata.get("worktree_integration_summary").cloned().unwrap_or(Value::Null),
                    "commit_ref": metadata.get("worktree_integration_commit_ref").cloned().unwrap_or(Value::Null),
                    "worktree_path": metadata.get("worktree_integration_worktree_path").cloned().unwrap_or(Value::Null),
                    "workspace_task_id": task.id.clone(),
                    "dirty_signature": metadata.get("worktree_integration_dirty_signature").cloned().unwrap_or(Value::Null),
                }),
                created_at: now,
            })
            .await?;
        Ok(())
    }

    async fn accepted_projection_already_complete(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<bool> {
        let metadata = object_or_empty(node.metadata_json.clone());
        if !accepted_projection_already_complete_base(node, attempt, &metadata) {
            return Ok(false);
        }
        if metadata_string(metadata.get("worktree_integration_status")).as_deref()
            != Some("blocked_dirty_main")
        {
            return Ok(true);
        }
        self.blocked_dirty_main_projection_still_current(workspace_id, node, attempt, &metadata)
            .await
    }

    async fn blocked_dirty_main_projection_still_current(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        metadata: &Map<String, Value>,
    ) -> CoreResult<bool> {
        let task_id = node
            .workspace_task_id
            .as_ref()
            .unwrap_or(&attempt.workspace_task_id);
        let Some(task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(false);
        };
        if task.workspace_id != workspace_id {
            return Ok(false);
        }
        let task_metadata = object_or_empty(task.metadata_json.clone());
        let Some(stored_signature) =
            metadata_string(metadata.get("worktree_integration_dirty_signature")).or_else(|| {
                metadata_string(task_metadata.get("worktree_integration_dirty_signature"))
            })
        else {
            return Ok(false);
        };
        let Some(workspace) = self.store.get_workspace(workspace_id).await? else {
            return Ok(false);
        };
        let Some(sandbox_code_root) =
            sandbox_code_root_for_integration(&task.metadata_json, &workspace.metadata_json)
        else {
            return Ok(false);
        };
        let current = current_worktree_dirty_signature(Path::new(&sandbox_code_root)).await?;
        Ok(current.as_deref() == Some(stored_signature.as_str()))
    }

    async fn reconcile_terminal_attempt_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if supervisor_blocked_human_metadata_present(&object_or_empty(
                node.metadata_json.clone(),
            )) {
                continue;
            }
            let Some(attempt_id) = recoverable_node_attempt_id(&node) else {
                continue;
            };
            let Some(attempt) = self.store.get_task_session_attempt(&attempt_id).await? else {
                continue;
            };
            let status = attempt.status.trim().to_ascii_lowercase();
            if terminal_attempt_pending_pipeline_verification(&node, &status) {
                continue;
            }
            if !TERMINAL_RETRY_ATTEMPT_STATUSES.contains(&status.as_str()) {
                continue;
            }
            if let Some(accepted_attempt) = self
                .reconciling_accepted_attempt_for_terminal_attempt(workspace_id, &node, &attempt)
                .await?
            {
                let now = Utc::now();
                let evidence_refs = accepted_attempt_evidence_refs(&accepted_attempt);
                let commit_ref = first_valid_commit_ref(&evidence_refs);
                let git_diff_summary = first_prefixed_ref(&evidence_refs, "git_diff_summary:");
                let test_commands = prefixed_refs(&evidence_refs, "test_run:");
                let summary = accepted_attempt_summary(&accepted_attempt);
                let Some(integration_metadata) = self
                    .project_accepted_attempt_to_task(
                        workspace_id,
                        &node,
                        &accepted_attempt,
                        &summary,
                        &evidence_refs,
                        commit_ref.as_deref(),
                        git_diff_summary.as_deref(),
                        &test_commands,
                        now,
                    )
                    .await?
                else {
                    continue;
                };

                let mut metadata =
                    accepted_attempt_projection_base_metadata(&node, &accepted_attempt);
                metadata.insert(
                    "terminal_attempt_status".to_string(),
                    json!(ACCEPTED_ATTEMPT_STATUS),
                );
                metadata.insert(
                    "terminal_attempt_reconciled_at".to_string(),
                    json!(now.to_rfc3339()),
                );
                metadata.insert(
                    "terminal_attempt_superseded_attempt_id".to_string(),
                    json!(attempt.id.clone()),
                );
                metadata.insert(
                    "terminal_attempt_superseded_status".to_string(),
                    json!(status.clone()),
                );
                if let Some(reason) = attempt
                    .adjudication_reason
                    .as_deref()
                    .or(attempt.leader_feedback.as_deref())
                {
                    metadata.insert(
                        "terminal_attempt_superseded_reason".to_string(),
                        json!(reason),
                    );
                }
                metadata.insert("last_verification_summary".to_string(), json!(summary));
                metadata.insert("last_verification_passed".to_string(), json!(true));
                metadata.insert("last_verification_hard_fail".to_string(), json!(false));
                metadata.insert(
                    "last_verification_attempt_id".to_string(),
                    json!(accepted_attempt.id.clone()),
                );
                metadata.insert(
                    "last_verification_ran_at".to_string(),
                    json!(now.to_rfc3339()),
                );
                if !accepted_attempt.candidate_artifacts_json.is_empty() {
                    metadata.insert(
                        "candidate_artifacts".to_string(),
                        json!(accepted_attempt.candidate_artifacts_json.clone()),
                    );
                }
                if !accepted_attempt.candidate_verifications_json.is_empty() {
                    metadata.insert(
                        "candidate_verifications".to_string(),
                        json!(accepted_attempt.candidate_verifications_json.clone()),
                    );
                }
                metadata.extend(integration_metadata);

                node.intent = "done".to_string();
                node.execution = "idle".to_string();
                node.current_attempt_id = Some(accepted_attempt.id.clone());
                node.feature_checkpoint_json =
                    accepted_attempt_projection_feature_checkpoint(&node, &accepted_attempt);
                node.metadata_json = Value::Object(metadata);
                node.updated_at = Some(now);
                self.store.save_plan_node(node).await?;
                changed += 1;
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let node_id = node.id.clone();
            let retry_reason = format!("terminal_attempt_{status}");
            let retry_exhausted = release_node_for_terminal_retry(
                &mut node,
                &retry_reason,
                now,
                plan_terminal_attempt_max_retries(),
            );
            self.store.save_plan_node(node).await?;
            changed += 1;

            if retry_exhausted {
                continue;
            }
            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node_id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    Some(&attempt_id),
                    &retry_reason,
                    now,
                ))
                .await?;
        }
        Ok(changed)
    }

    async fn reconcile_supervisor_retry_same_node_attempt_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if !supervisor_retry_same_node_reconcilable_node(&node) {
                continue;
            }
            let mut metadata = object_or_empty(node.metadata_json.clone());
            if metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
                != Some(SUPERVISOR_DECISION_RETRY_SAME_NODE_ACTION)
            {
                continue;
            }
            let Some(attempt_id) = node.current_attempt_id.clone() else {
                continue;
            };
            let Some(attempt) = self.store.get_task_session_attempt(&attempt_id).await? else {
                continue;
            };
            if attempt.status.trim().to_ascii_lowercase() != AWAITING_LEADER_ADJUDICATION_STATUS {
                continue;
            }
            if !attempt_has_candidate_output(&attempt) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let summary = supervisor_retry_same_node_summary(&metadata, &attempt);
            let retry_not_before =
                future_metadata_datetime_utc(metadata.get("retry_not_before"), now);
            let Some(rejected_attempt) = self
                .store
                .finish_task_session_attempt(
                    &attempt_id,
                    REJECTED_ATTEMPT_STATUS,
                    Some(&summary),
                    Some(SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON),
                    now,
                )
                .await?
            else {
                continue;
            };

            let node_id = node.id.clone();
            let retry_exhausted = release_node_for_terminal_retry(
                &mut node,
                SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON,
                now,
                plan_terminal_attempt_max_retries(),
            );
            metadata = object_or_empty(node.metadata_json.clone());
            metadata.insert(
                "supervisor_decision_retry_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "supervisor_decision_retry_attempt_id".to_string(),
                json!(rejected_attempt.id.clone()),
            );
            metadata.insert(
                "supervisor_decision_retry_attempt_status".to_string(),
                json!(REJECTED_ATTEMPT_STATUS),
            );
            node.metadata_json = Value::Object(metadata.clone());
            self.store.save_plan_node(node).await?;
            changed += 1;

            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node_id.clone()),
                    attempt_id: Some(rejected_attempt.id.clone()),
                    event_type: "supervisor_decision_retry_same_node_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "reason": SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON,
                        "action": SUPERVISOR_DECISION_RETRY_SAME_NODE_ACTION,
                        "rationale": metadata.get("last_supervisor_decision_rationale").cloned().unwrap_or(Value::Null),
                        "confidence": metadata.get("last_supervisor_decision_confidence").cloned().unwrap_or(Value::Null),
                        "feedback_items": metadata.get("last_supervisor_decision_feedback_items").cloned().unwrap_or(Value::Null),
                        "workspace_task_id": context.task_id.clone(),
                        "retry_exhausted": retry_exhausted,
                    }),
                    created_at: now,
                })
                .await?;

            if retry_exhausted {
                continue;
            }
            let mut retry_outbox = supervisor_retry_attempt_outbox(
                item,
                payload,
                workspace_id,
                plan_id,
                &node_id,
                &context.task_id,
                &context.worker_agent_id,
                &context.actor_user_id,
                &context.leader_agent_id,
                context.root_goal_task_id.as_deref(),
                Some(&attempt_id),
                SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON,
                now,
            );
            if let Some(retry_at) = retry_not_before {
                retry_outbox.next_attempt_at = Some(retry_at);
                if let Value::Object(retry_payload) = &mut retry_outbox.payload_json {
                    retry_payload
                        .insert("retry_not_before".to_string(), json!(retry_at.to_rfc3339()));
                }
            }
            self.store.enqueue_plan_outbox(retry_outbox).await?;
        }
        Ok(changed)
    }

    async fn reconciling_accepted_attempt_for_terminal_attempt(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        terminal_attempt: &WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let Some(accepted_attempt) = self
            .store
            .find_latest_accepted_task_session_attempt(
                workspace_id,
                &terminal_attempt.workspace_task_id,
            )
            .await?
        else {
            return Ok(None);
        };
        if accepted_attempt.id == terminal_attempt.id {
            return Ok(None);
        }
        if !accepted_attempt_matches_node_expected_commit(node, &accepted_attempt) {
            return Ok(None);
        }
        if accepted_attempt.attempt_number > terminal_attempt.attempt_number
            || attempt_cancelled_because_parent_done_without_output(terminal_attempt)
        {
            return Ok(Some(accepted_attempt));
        }
        Ok(None)
    }

    async fn reconcile_reported_attempt_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
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

        let now = Utc::now();
        let mut changed = Vec::new();
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if !reported_reconcilable_node(&node) {
                continue;
            }
            let Some(attempt_id) = node.current_attempt_id.as_deref() else {
                continue;
            };
            let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? else {
                continue;
            };
            if attempt.status != AWAITING_LEADER_ADJUDICATION_STATUS {
                continue;
            }
            if !attempt_has_candidate_output(&attempt) {
                continue;
            }

            let mut metadata = object_or_empty(node.metadata_json.clone());
            metadata.insert(
                "reported_attempt_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "reported_attempt_status".to_string(),
                json!(AWAITING_LEADER_ADJUDICATION_STATUS),
            );
            node.execution = "reported".to_string();
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            changed.push(node);
        }

        if let Some(first) = changed.first() {
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(first.id.clone()),
                    attempt_id: first.current_attempt_id.clone(),
                    event_type: "auto_reported_attempt_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "reason": "active_plan_node_points_to_reported_attempt",
                        "node_ids": changed.iter().map(|node| node.id.clone()).collect::<Vec<_>>()
                    }),
                    created_at: now,
                })
                .await?;
        }

        Ok(changed.len())
    }

    async fn retry_context_for_node(
        &self,
        payload: &Map<String, Value>,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
    ) -> CoreResult<Option<SupervisorRetryContext>> {
        let Some(task_id) =
            string_from_map(payload, "task_id").or_else(|| node.workspace_task_id.clone())
        else {
            return Ok(None);
        };
        let Some(task) = self.store.get_task(workspace_id, &task_id).await? else {
            return Ok(None);
        };
        let task_metadata = object_or_empty(task.metadata_json.clone());
        let Some(worker_agent_id) = string_from_map(payload, "worker_agent_id")
            .or_else(|| node.assignee_agent_id.clone())
            .or_else(|| task.assignee_agent_id.clone())
        else {
            return Ok(None);
        };
        let actor_user_id =
            string_from_map(payload, "actor_user_id").unwrap_or_else(|| task.created_by.clone());
        let leader_agent_id = string_from_map(payload, "leader_agent_id")
            .or_else(|| string_from_map(&task_metadata, "leader_agent_id"))
            .unwrap_or_else(|| WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string());
        let root_goal_task_id = string_from_map(payload, ROOT_GOAL_TASK_ID)
            .or_else(|| string_from_map(payload, "root_task_id"))
            .or_else(|| string_from_map(&task_metadata, ROOT_GOAL_TASK_ID));
        Ok(Some(SupervisorRetryContext {
            task_id,
            worker_agent_id,
            actor_user_id,
            leader_agent_id,
            root_goal_task_id,
        }))
    }
}
