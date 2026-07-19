use super::*;

mod accepted;
mod constants;
mod disposition;
mod pipeline;
mod replan;
mod reports;
mod root_progress;
mod terminal;

pub(super) use constants::{
    AWAITING_LEADER_ADJUDICATION_STATUS, DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES,
    PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV, SUPERVISOR_BLOCKED_HUMAN_VERDICT,
    SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION, SUPERVISOR_DECISION_CREATE_REPAIR_NODE_REASON,
    SUPERVISOR_DECISION_DISPOSE_NODE_ACTION, SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_ACTION,
    SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_REASON, SUPERVISOR_DECISION_NOOP_ACTION,
    SUPERVISOR_DECISION_NOOP_REASON, SUPERVISOR_DECISION_REPLAN_NODE_ACTION,
    SUPERVISOR_DECISION_REPLAN_NODE_REASON, SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION,
    SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON, SUPERVISOR_DECISION_RETRY_SAME_NODE_ACTION,
    SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON, SUPERVISOR_DECISION_WAIT_PIPELINE_ACTION,
    SUPERVISOR_DECISION_WAIT_PIPELINE_REASON, SUPERVISOR_DISPOSED_NODE_DISPOSITION,
    SUPERVISOR_REPLAN_REQUESTED_VERDICT, TERMINAL_RETRY_ATTEMPT_STATUSES,
};

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
        let payload = object_as_map(&item.payload_json);
        let workspace_id =
            string_from_map(payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let node_id = string_from_map(payload, "retry_node_id")
            .or_else(|| string_from_map(payload, "node_id"));
        let plan_id = item
            .plan_id
            .clone()
            .or_else(|| string_from_map(payload, "plan_id"));
        let Some(node_id) = node_id else {
            let Some(plan_id) = plan_id else {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                    reason: Some("supervisor_tick_requires_full_runtime".to_string()),
                });
            };
            let plan = self.store.get_plan(&plan_id).await?.ok_or_else(|| {
                CoreError::Storage(format!(
                    "workspace plan {plan_id} not found for workspace {workspace_id}"
                ))
            })?;
            let mut ctx = SupervisorTickContext {
                plan,
                nodes: Vec::new(),
            };
            if ctx.plan.workspace_id != workspace_id {
                return Err(CoreError::Storage(format!(
                    "workspace plan {plan_id} not found for workspace {workspace_id}"
                )));
            }
            ctx.nodes = self.store.list_plan_nodes(&plan_id).await?;
            let changed_worktree_failed = self
                .reopen_failed_worktree_integration_nodes(
                    &item,
                    payload,
                    &workspace_id,
                    &plan_id,
                    &mut ctx,
                )
                .await?;
            let changed_missing = self
                .recover_missing_attempt_nodes(&item, payload, &workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_blocked_human = self
                .reconcile_supervisor_blocked_human_nodes(&workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_request_pipeline = self
                .reconcile_supervisor_request_pipeline_nodes(&workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_wait_pipeline = self
                .reconcile_supervisor_wait_pipeline_nodes(&workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_noop = self
                .reconcile_supervisor_noop_nodes(&workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_create_repair = self
                .reconcile_supervisor_create_repair_nodes(&workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_replan = self
                .reconcile_supervisor_replan_nodes(&workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_disposed = self
                .reconcile_supervisor_disposed_nodes(&workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_accepted = self
                .reconcile_accepted_terminal_attempt_nodes(&workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_supervisor_retry = self
                .reconcile_supervisor_retry_same_node_attempt_nodes(
                    &item,
                    payload,
                    &workspace_id,
                    &plan_id,
                    &mut ctx,
                )
                .await?;
            let changed_terminal = self
                .reconcile_terminal_attempt_nodes(&item, payload, &workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_reported = self
                .reconcile_reported_attempt_nodes(&workspace_id, &plan_id, &mut ctx)
                .await?;
            let changed_dirty_main_dependency_dispatch = self
                .dispatch_ready_dirty_main_dependency_node(
                    &item,
                    payload,
                    &workspace_id,
                    &plan_id,
                    &mut ctx,
                )
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
        let retry_attempt_id = string_from_map(payload, "retry_attempt_id")
            .or_else(|| string_from_map(payload, "attempt_id"));
        if retry_attempt_id.is_some()
            && node.current_attempt_id.as_deref().is_some()
            && node.current_attempt_id.as_deref() != retry_attempt_id.as_deref()
        {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let task_id = string_from_map(payload, "task_id")
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
        let task_metadata = object_as_map(&task.metadata_json);
        let Some(worker_agent_id) = string_from_map(payload, "worker_agent_id")
            .or_else(|| node.assignee_agent_id.clone())
            .or_else(|| task.assignee_agent_id.clone())
        else {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_retry_requires_worker_agent".to_string()),
            });
        };
        let actor_user_id =
            string_from_map(payload, "actor_user_id").unwrap_or_else(|| task.created_by.clone());
        let leader_agent_id = string_from_map(payload, "leader_agent_id")
            .or_else(|| string_from_map(task_metadata, "leader_agent_id"))
            .unwrap_or_else(|| WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string());
        let root_goal_task_id = string_from_map(payload, ROOT_GOAL_TASK_ID)
            .or_else(|| string_from_map(payload, "root_task_id"))
            .or_else(|| string_from_map(task_metadata, ROOT_GOAL_TASK_ID));
        if is_worker_report_supervisor_tick(&item, payload) {
            return self
                .handle_worker_report_supervisor_tick(
                    &item,
                    payload,
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
        let retry_reason = string_from_map(payload, "retry_reason")
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
                payload,
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

pub(super) struct SupervisorTickContext {
    pub(super) plan: WorkspacePlanRecord,
    pub(super) nodes: Vec<WorkspacePlanNodeRecord>,
}

struct SupervisorRetryContext {
    task_id: String,
    worker_agent_id: String,
    actor_user_id: String,
    leader_agent_id: String,
    root_goal_task_id: Option<String>,
}
