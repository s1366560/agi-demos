use super::*;

impl PgWorkspaceService {
    pub(super) async fn pg_get_plan_snapshot(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshotView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        let recover_stale_attempts = query.recover_stale_attempts.unwrap_or(false);
        let mut plans = self
            .repo
            .list_plans(workspace_id, 50)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if plans.is_empty() {
            return Ok(plan_snapshot::empty_plan_snapshot(workspace_id));
        }
        let selected_plan_id = if let Some(plan_id) = query.plan_id.as_deref() {
            if !plans.iter().any(|plan| plan.id == plan_id) {
                let plan = self
                    .repo
                    .get_plan(plan_id)
                    .await
                    .map_err(WorkspaceApiError::internal)?
                    .filter(|plan| plan.workspace_id == workspace_id)
                    .ok_or_else(WorkspaceApiError::plan_not_found)?;
                plans.push(plan);
            }
            plan_id.to_string()
        } else {
            plans[0].id.clone()
        };
        // One batch fetch for all plans' nodes instead of a sequential query
        // per plan (this endpoint is polled by the UI). Grouping preserves the
        // batch query's per-plan row order.
        let plan_ids: Vec<String> = plans.iter().map(|plan| plan.id.clone()).collect();
        let all_nodes = self
            .repo
            .list_plan_nodes_by_plan_ids(&plan_ids)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let mut nodes_by_plan: HashMap<String, Vec<WorkspacePlanNodeRecord>> = HashMap::new();
        for node in all_nodes {
            nodes_by_plan
                .entry(node.plan_id.clone())
                .or_default()
                .push(node);
        }
        let mut plans_with_nodes = Vec::with_capacity(plans.len());
        for plan in plans {
            let nodes = nodes_by_plan.remove(&plan.id).unwrap_or_default();
            plans_with_nodes.push((plan, nodes));
        }
        let include_details = query.include_details.unwrap_or(true);
        if recover_stale_attempts
            && include_details
            && plans_with_nodes
                .first()
                .map(|(plan, _)| plan.id.as_str() == selected_plan_id.as_str())
                .unwrap_or(false)
            && self
                .repo
                .user_can_access_workspace(user_id, workspace_id, WorkspaceAccess::Write)
                .await
                .map_err(WorkspaceApiError::internal)?
        {
            if let Some((plan, nodes)) = plans_with_nodes
                .iter()
                .find(|(plan, _)| plan.id == selected_plan_id)
            {
                plan_actions::recover_stale_plan_records_pg(
                    &self.repo,
                    workspace_id,
                    plan,
                    nodes,
                    user_id,
                )
                .await?;
            }
        }
        let (blackboard, outbox, events) = if include_details {
            (
                self.repo
                    .list_plan_blackboard_latest(&selected_plan_id)
                    .await
                    .map_err(WorkspaceApiError::internal)?,
                self.repo
                    .list_plan_outbox(
                        &selected_plan_id,
                        query.outbox_limit.unwrap_or(20).clamp(0, 100),
                    )
                    .await
                    .map_err(WorkspaceApiError::internal)?,
                self.repo
                    .list_plan_events(
                        &selected_plan_id,
                        query.event_limit.unwrap_or(50).clamp(0, 200),
                    )
                    .await
                    .map_err(WorkspaceApiError::internal)?,
            )
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

    pub(super) async fn pg_retry_plan_outbox(
        &self,
        user_id: &str,
        workspace_id: &str,
        outbox_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let now = Utc::now();
        let item = self
            .repo
            .retry_plan_outbox_now(
                outbox_id,
                workspace_id,
                Some(user_id),
                body.reason.as_deref(),
                now,
            )
            .await
            .map_err(plan_actions::map_plan_outbox_retry_error)?
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let plan_id = item
            .plan_id
            .clone()
            .ok_or_else(|| WorkspaceApiError::bad_request("Invalid workspace plan request"))?;
        self.repo
            .create_plan_event(plan_actions::plan_retry_event(
                &plan_id,
                workspace_id,
                user_id,
                outbox_id,
                &item.event_type,
                body.reason.as_deref(),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Outbox job queued for retry.".to_string(),
            plan_id,
            node_id: None,
            outbox_id: Some(outbox_id.to_string()),
        })
    }

    pub(super) async fn pg_recover_stale_attempts(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let recovered = plan_actions::recover_stale_plan_records_pg(
            &self.repo,
            workspace_id,
            &plan,
            &nodes,
            user_id,
        )
        .await?;
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

    pub(super) async fn pg_request_delivery_pipeline_run(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanPipelineRunRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_pipeline_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let node = plan_actions::pipeline_target_node(&nodes, body.node_id.as_deref())
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested harness-native pipeline".to_string());
        let outbox = self
            .repo
            .enqueue_plan_outbox(plan_actions::plan_action_outbox(
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
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Harness-native pipeline run requested.".to_string(),
            plan_id: plan.id,
            node_id: Some(node.id),
            outbox_id: Some(outbox.id),
        })
    }

    pub(super) async fn pg_request_delivery_contract_regeneration(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let now = Utc::now();
        let mut workspace = self
            .repo
            .get_workspace(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        plan_actions::apply_delivery_contract_regeneration(
            &mut workspace.metadata_json,
            user_id,
            body.reason.as_deref(),
            now,
        );
        workspace.updated_at = Some(now);
        self.repo
            .save_workspace(workspace)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested delivery contract regeneration".to_string());
        let outbox = self
            .repo
            .enqueue_plan_outbox(plan_actions::plan_action_outbox(
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
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        self.repo
            .create_plan_event(WorkspacePlanEventRecord {
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
            })
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Delivery contract regeneration requested.".to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: Some(outbox.id),
        })
    }

    pub(super) async fn pg_request_plan_node_replan(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .find(|node| node.id == node_id)
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
        self.repo
            .save_plan_node(updated)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if plan_changed {
            self.repo
                .save_plan(plan.clone())
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        self.repo
            .create_plan_event(plan_actions::operator_plan_event(
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
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        self.repo
            .enqueue_plan_outbox(plan_actions::operator_tick_outbox(
                &plan.id,
                workspace_id,
                node_id,
                user_id,
                "operator_replan_requested",
                body.reason.as_deref(),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node sent back for supervisor recovery.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    pub(super) async fn pg_reopen_plan_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .find(|node| node.id == node_id)
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
        self.repo
            .save_plan_node(updated)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if plan_changed {
            self.repo
                .save_plan(plan.clone())
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        self.repo
            .create_plan_event(plan_actions::operator_plan_event(
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
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        self.repo
            .enqueue_plan_outbox(plan_actions::operator_tick_outbox(
                &plan.id,
                workspace_id,
                node_id,
                user_id,
                "operator_node_reopened",
                body.reason.as_deref(),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Blocked plan node reopened.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    pub(super) async fn pg_accept_plan_node_review(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .find(|node| node.id == node_id)
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
            self.repo
                .finish_task_session_attempt(
                    attempt_id,
                    "accepted",
                    Some(&reason),
                    Some("operator_review_accepted"),
                    now,
                )
                .await
                .map_err(WorkspaceApiError::internal)?
        } else {
            None
        };
        if let Some(attempt) = accepted_attempt.as_ref() {
            plan_actions::apply_human_review_acceptance_to_node_attempt(&mut updated, attempt);
        }
        self.repo
            .save_plan_node(updated.clone())
            .await
            .map_err(WorkspaceApiError::internal)?;
        if let Some(task_id) = task_id {
            let mut task = self
                .repo
                .get_task(workspace_id, &task_id)
                .await
                .map_err(WorkspaceApiError::internal)?
                .ok_or_else(WorkspaceApiError::task_not_found)?;
            plan_actions::apply_human_review_acceptance_to_task(
                &mut task,
                &reason,
                &updated.metadata_json,
                accepted_attempt.as_ref(),
                now,
            );
            self.repo
                .save_task(task)
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        self.repo
            .create_plan_event(plan_actions::operator_plan_event(
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
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node accepted after human review.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }
}
