use super::*;

impl DevWorkspaceService {
    pub(super) async fn dev_get_plan_snapshot(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshotView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let recover_stale_attempts = query.recover_stale_attempts.unwrap_or(false);
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut plans: Vec<_> = state
            .plans
            .values()
            .filter(|plan| plan.workspace_id == workspace_id)
            .cloned()
            .collect();
        plans.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(a.id.cmp(&b.id)));
        if plans.is_empty() {
            return Ok(plan_snapshot::empty_plan_snapshot(workspace_id));
        }
        let selected_plan_id = if let Some(plan_id) = query.plan_id.as_deref() {
            if !plans.iter().any(|plan| plan.id == plan_id) {
                return Err(WorkspaceApiError::plan_not_found());
            }
            plan_id.to_string()
        } else {
            plans[0].id.clone()
        };
        let include_details = query.include_details.unwrap_or(true);
        if recover_stale_attempts
            && include_details
            && plans
                .first()
                .map(|plan| plan.id.as_str() == selected_plan_id.as_str())
                .unwrap_or(false)
        {
            if let Some(plan) = plans
                .iter()
                .find(|plan| plan.id == selected_plan_id)
                .cloned()
            {
                let nodes = plan_actions::plan_nodes_for_dev(&state, &plan.id);
                plan_actions::recover_stale_plan_records_dev(
                    &mut state,
                    workspace_id,
                    &plan,
                    &nodes,
                    user_id,
                    Utc::now(),
                );
            }
        }
        let plans_with_nodes: Vec<_> = plans
            .into_iter()
            .map(|plan| {
                let mut nodes: Vec<_> = state
                    .plan_nodes
                    .values()
                    .filter(|node| node.plan_id == plan.id)
                    .cloned()
                    .collect();
                nodes.sort_by(|a, b| {
                    a.kind
                        .cmp(&b.kind)
                        .then(a.priority.cmp(&b.priority))
                        .then(a.id.cmp(&b.id))
                });
                (plan, nodes)
            })
            .collect();
        let (blackboard, outbox, events) = if include_details {
            let mut latest = HashMap::<String, WorkspacePlanBlackboardEntryRecord>::new();
            for entry in state
                .plan_blackboard
                .iter()
                .filter(|entry| entry.plan_id == selected_plan_id.as_str())
            {
                let replace = latest
                    .get(&entry.key)
                    .map(|current| {
                        entry.version > current.version
                            || (entry.version == current.version
                                && entry.created_at > current.created_at)
                    })
                    .unwrap_or(true);
                if replace {
                    latest.insert(entry.key.clone(), entry.clone());
                }
            }
            let mut blackboard: Vec<_> = latest.into_values().collect();
            blackboard.sort_by(|a, b| a.key.cmp(&b.key));
            let outbox_limit = query.outbox_limit.unwrap_or(20).clamp(0, 100) as usize;
            let mut outbox: Vec<_> = state
                .plan_outbox
                .iter()
                .filter(|item| item.plan_id.as_deref() == Some(selected_plan_id.as_str()))
                .cloned()
                .collect();
            outbox.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(b.id.cmp(&a.id)));
            outbox.truncate(outbox_limit);
            let event_limit = query.event_limit.unwrap_or(50).clamp(0, 200) as usize;
            let mut events: Vec<_> = state
                .plan_events
                .iter()
                .filter(|event| event.plan_id == selected_plan_id.as_str())
                .cloned()
                .collect();
            events.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(b.id.cmp(&a.id)));
            events.truncate(event_limit);
            (blackboard, outbox, events)
        } else {
            (Vec::new(), Vec::new(), Vec::new())
        };
        Ok(plan_snapshot::build_plan_snapshot(
            workspace_id,
            plans_with_nodes,
            &selected_plan_id,
            include_details,
            blackboard,
            outbox,
            events,
        ))
    }

    pub(super) async fn dev_retry_plan_outbox(
        &self,
        user_id: &str,
        workspace_id: &str,
        outbox_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let now = Utc::now();
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let item = state
            .plan_outbox
            .iter_mut()
            .find(|item| item.id == outbox_id && item.workspace_id == workspace_id)
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let delayed_pending = item.status == "pending"
            && item
                .next_attempt_at
                .map(|next_attempt_at| next_attempt_at > now)
                .unwrap_or(false);
        if !matches!(item.status.as_str(), "failed" | "dead_letter") && !delayed_pending {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace plan request",
            ));
        }
        let plan_id = item
            .plan_id
            .clone()
            .ok_or_else(|| WorkspaceApiError::bad_request("Invalid workspace plan request"))?;
        let previous_status = item.status.clone();
        let previous_error = item.last_error.clone();
        let previous_next_attempt_at = item.next_attempt_at.map(iso);
        let previous_event_type = item.event_type.clone();
        item.status = "pending".to_string();
        if previous_status == "dead_letter" {
            item.attempt_count = 0;
        }
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = None;
        item.next_attempt_at = None;
        item.processed_at = None;
        item.updated_at = Some(now);
        let mut metadata = match item.metadata_json.clone() {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        metadata.insert(
            "operator_retry".to_string(),
            json!({
                "actor_id": user_id,
                "reason": body.reason.clone(),
                "retried_at": iso(now),
                "previous_status": previous_status,
                "previous_error": previous_error,
                "previous_next_attempt_at": previous_next_attempt_at
            }),
        );
        item.metadata_json = Value::Object(metadata);
        state.plan_events.push(plan_actions::plan_retry_event(
            &plan_id,
            workspace_id,
            user_id,
            outbox_id,
            &previous_event_type,
            body.reason.as_deref(),
            now,
        ));
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Outbox job queued for retry.".to_string(),
            plan_id,
            node_id: None,
            outbox_id: Some(outbox_id.to_string()),
        })
    }

    pub(super) async fn dev_recover_stale_attempts(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = plan_actions::plan_nodes_for_dev(&state, &plan.id);
        let recovered = plan_actions::recover_stale_plan_records_dev(
            &mut state,
            workspace_id,
            &plan,
            &nodes,
            user_id,
            Utc::now(),
        );
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: if recovered {
                "Workspace plan stale attempt recovery queued."
            } else {
                "No stale workspace plan attempts needed recovery."
            }
            .to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: None,
        })
    }

    pub(super) async fn dev_request_delivery_pipeline_run(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanPipelineRunRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_pipeline_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = plan_actions::plan_nodes_for_dev(&state, &plan.id);
        let node = plan_actions::pipeline_target_node(&nodes, body.node_id.as_deref())
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested harness-native pipeline".to_string());
        let outbox = plan_actions::plan_action_outbox(
            &plan.id,
            workspace_id,
            PIPELINE_RUN_REQUESTED_EVENT,
            json!({
                "workspace_id": workspace_id,
                "plan_id": plan.id,
                "node_id": node.id,
                "attempt_id": node.current_attempt_id,
                "reason": reason
            }),
            json!({"source": "workspace_plan.operator_delivery_run_pipeline"}),
            Utc::now(),
        );
        let outbox_id = outbox.id.clone();
        state.plan_outbox.push(outbox);
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Harness-native pipeline run requested.".to_string(),
            plan_id: plan.id,
            node_id: Some(node.id),
            outbox_id: Some(outbox_id),
        })
    }

    pub(super) async fn dev_request_delivery_contract_regeneration(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let now = Utc::now();
        let workspace = state
            .workspaces
            .get_mut(workspace_id)
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        plan_actions::apply_delivery_contract_regeneration(
            &mut workspace.metadata_json,
            user_id,
            body.reason.as_deref(),
            now,
        );
        workspace.updated_at = Some(now);
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested delivery contract regeneration".to_string());
        let outbox = plan_actions::plan_action_outbox(
            &plan.id,
            workspace_id,
            SUPERVISOR_TICK_EVENT,
            json!({
                "workspace_id": workspace_id,
                "plan_id": plan.id,
                "reason": reason
            }),
            json!({"source": "workspace_plan.operator_delivery_regenerate_contract"}),
            now,
        );
        let outbox_id = outbox.id.clone();
        state.plan_outbox.push(outbox);
        state.plan_events.push(WorkspacePlanEventRecord {
            id: new_id(),
            plan_id: plan.id.clone(),
            workspace_id: workspace_id.to_string(),
            node_id: None,
            attempt_id: None,
            event_type: "delivery_contract_regeneration_requested".to_string(),
            source: "operator".to_string(),
            actor_id: None,
            payload_json: json!({
                "reason": body.reason,
                "requested_by": user_id,
                "requested_at": iso(now)
            }),
            created_at: now,
        });
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Delivery contract regeneration requested.".to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: Some(outbox_id),
        })
    }

    pub(super) async fn dev_request_plan_node_replan(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let mut plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = state
            .plan_nodes
            .get(node_id)
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_replan_requested",
            reason.as_deref(),
            now,
            plan_actions::done_node_has_recoverable_failure,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        state.plan_nodes.insert(node_id.to_string(), updated);
        if plan_changed {
            state.plans.insert(plan.id.clone(), plan.clone());
        }
        state.plan_events.push(plan_actions::operator_plan_event(
            plan_actions::OperatorPlanEventInput {
                plan_id: &plan.id,
                workspace_id,
                node_id,
                attempt_id,
                event_type: "operator_replan_requested",
                actor_id: user_id,
                payload_json: json!({"reason": reason}),
                created_at: now,
            },
        ));
        let outbox = plan_actions::operator_tick_outbox(
            &plan.id,
            workspace_id,
            node_id,
            user_id,
            "operator_replan_requested",
            body.reason.as_deref(),
            now,
        );
        state.plan_outbox.push(outbox);
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node sent back for supervisor recovery.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    pub(super) async fn dev_reopen_plan_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let mut plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = state
            .plan_nodes
            .get(node_id)
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        if node.intent != "blocked" {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace plan request",
            ));
        }
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_node_reopened",
            reason.as_deref(),
            now,
            |_| false,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        state.plan_nodes.insert(node_id.to_string(), updated);
        if plan_changed {
            state.plans.insert(plan.id.clone(), plan.clone());
        }
        state.plan_events.push(plan_actions::operator_plan_event(
            plan_actions::OperatorPlanEventInput {
                plan_id: &plan.id,
                workspace_id,
                node_id,
                attempt_id,
                event_type: "operator_node_reopened",
                actor_id: user_id,
                payload_json: json!({"reason": reason}),
                created_at: now,
            },
        ));
        let outbox = plan_actions::operator_tick_outbox(
            &plan.id,
            workspace_id,
            node_id,
            user_id,
            "operator_node_reopened",
            body.reason.as_deref(),
            now,
        );
        state.plan_outbox.push(outbox);
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Blocked plan node reopened.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    pub(super) async fn dev_accept_plan_node_review(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = state
            .plan_nodes
            .get(node_id)
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let task_id = node.workspace_task_id.clone();
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "Accepted after operator review.".to_string());
        let evidence_refs = plan_actions::trimmed_evidence_refs(&body.evidence_refs);
        let now = Utc::now();
        let mut updated = plan_actions::accept_node_for_operator_review(
            node,
            user_id,
            &reason,
            evidence_refs.clone(),
            now,
        )?;
        let accepted_attempt = if let Some(attempt_id) = attempt_id.as_deref() {
            state.task_attempts.get_mut(attempt_id).map(|attempt| {
                attempt.status = "accepted".to_string();
                attempt.leader_feedback = Some(reason.clone());
                attempt.adjudication_reason = Some("operator_review_accepted".to_string());
                attempt.completed_at = Some(now);
                attempt.updated_at = Some(now);
                attempt.clone()
            })
        } else {
            None
        };
        if let Some(attempt) = accepted_attempt.as_ref() {
            plan_actions::apply_human_review_acceptance_to_node_attempt(&mut updated, attempt);
        }
        state
            .plan_nodes
            .insert(node_id.to_string(), updated.clone());
        if let Some(task_id) = task_id {
            let task = state
                .tasks
                .get_mut(&task_id)
                .filter(|task| task.workspace_id == workspace_id)
                .ok_or_else(WorkspaceApiError::task_not_found)?;
            plan_actions::apply_human_review_acceptance_to_task(
                task,
                &reason,
                &updated.metadata_json,
                accepted_attempt.as_ref(),
                now,
            );
        }
        state.plan_events.push(plan_actions::operator_plan_event(
            plan_actions::OperatorPlanEventInput {
                plan_id: &plan.id,
                workspace_id,
                node_id,
                attempt_id,
                event_type: "operator_review_accepted",
                actor_id: user_id,
                payload_json: json!({"reason": reason, "evidence_refs": evidence_refs}),
                created_at: now,
            },
        ));
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node accepted after human review.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }
}
