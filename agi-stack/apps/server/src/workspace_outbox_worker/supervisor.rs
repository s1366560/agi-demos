use super::*;

mod accepted;
mod disposition;
mod pipeline;
mod replan;
mod terminal;

pub(super) struct SupervisorTickAdmissionHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
}

pub(super) struct AcceptedAttemptTaskProjection<'a> {
    pub(super) workspace_id: &'a str,
    pub(super) node: &'a WorkspacePlanNodeRecord,
    pub(super) attempt: &'a WorkspaceTaskSessionAttemptRecord,
    pub(super) summary: &'a str,
    pub(super) evidence_refs: &'a [String],
    pub(super) commit_ref: Option<&'a str>,
    pub(super) git_diff_summary: Option<&'a str>,
    pub(super) test_commands: &'a [String],
    pub(super) now: DateTime<Utc>,
}

struct WorktreeIntegrationEvent<'a> {
    workspace_id: &'a str,
    node: &'a WorkspacePlanNodeRecord,
    attempt_id: &'a str,
    task: &'a WorkspaceTaskRecord,
    metadata: &'a Map<String, Value>,
    event_type: &'a str,
    now: DateTime<Utc>,
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
}
