use super::*;

mod accepted;
mod replan;

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
