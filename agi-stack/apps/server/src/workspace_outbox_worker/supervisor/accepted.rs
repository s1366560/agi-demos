use super::*;

mod worktree;

impl SupervisorTickAdmissionHandler {
    pub(super) async fn reopen_failed_worktree_integration_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
        ctx: &mut SupervisorTickContext,
    ) -> CoreResult<usize> {
        let mut changed = 0;
        for node in ctx.nodes.iter_mut() {
            if !done_node_needs_worktree_integration_retry(node) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let previous_metadata = object_or_empty(node.metadata_json.clone());
            let previous_attempt_id =
                metadata_string(previous_metadata.get("worktree_integration_attempt_id"))
                    .or_else(|| node.current_attempt_id.clone());
            let previous_commit_ref = node_verified_commit_ref(node);
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

    pub(super) async fn dispatch_ready_dirty_main_dependency_node(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
        ctx: &mut SupervisorTickContext,
    ) -> CoreResult<usize> {
        let mut sorted_node_ids = ctx
            .nodes
            .iter()
            .map(|node| (node.priority, node.id.clone()))
            .collect::<Vec<_>>();
        sorted_node_ids
            .sort_by(|left, right| left.0.cmp(&right.0).then_with(|| left.1.cmp(&right.1)));
        let nodes_by_id = ctx
            .nodes
            .iter()
            .map(|node| (node.id.clone(), node.clone()))
            .collect::<HashMap<_, _>>();

        for (_, node_id) in sorted_node_ids {
            let Some(node) = ctx.nodes.iter_mut().find(|node| node.id == node_id) else {
                continue;
            };
            if !dirty_main_dependency_dispatch_candidate(node) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, node)
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
                dependency_dispatch_blockers(node, &nodes_by_id);
            if !blocking_dependencies.is_empty() || dirty_main_seed_dependencies.is_empty() {
                continue;
            }

            let dependency_base_ref = dependency_base_ref_for_dispatch(node, &nodes_by_id);
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

    pub(super) async fn reconcile_accepted_terminal_attempt_nodes(
        &self,
        workspace_id: &str,
        _plan_id: &str,
        ctx: &mut SupervisorTickContext,
    ) -> CoreResult<usize> {
        let now = Utc::now();
        let mut changed = 0;
        for node in ctx.nodes.iter_mut() {
            if supervisor_blocked_human_metadata_present(&object_or_empty(
                node.metadata_json.clone(),
            )) {
                continue;
            }
            let Some(attempt_id) = recoverable_node_attempt_id(node) else {
                continue;
            };
            let Some(mut attempt) = self.store.get_task_session_attempt(&attempt_id).await? else {
                continue;
            };
            if attempt.status.trim().to_ascii_lowercase() != ACCEPTED_ATTEMPT_STATUS {
                if !done_idle_node_has_accepted_supervisor_judge(node) {
                    continue;
                }
                let summary = accepted_supervisor_judge_summary(node, &attempt);
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
                .accepted_projection_already_complete(workspace_id, node, &attempt)
                .await?
            {
                continue;
            }
            if !accepted_attempt_matches_node_expected_commit(node, &attempt) {
                continue;
            }

            let evidence_refs = accepted_attempt_evidence_refs(&attempt);
            let commit_ref = first_valid_commit_ref(&evidence_refs);
            let git_diff_summary = first_prefixed_ref(&evidence_refs, "git_diff_summary:");
            let test_commands = prefixed_refs(&evidence_refs, "test_run:");
            let summary = accepted_attempt_summary(&attempt);
            let Some(integration_metadata) = self
                .project_accepted_attempt_to_task(AcceptedAttemptTaskProjection {
                    workspace_id,
                    node,
                    attempt: &attempt,
                    summary: &summary,
                    evidence_refs: &evidence_refs,
                    commit_ref: commit_ref.as_deref(),
                    git_diff_summary: git_diff_summary.as_deref(),
                    test_commands: &test_commands,
                    now,
                })
                .await?
            else {
                continue;
            };

            let mut metadata = accepted_attempt_projection_base_metadata(node, &attempt);
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
                accepted_attempt_projection_feature_checkpoint(node, &attempt);
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            changed += 1;
        }
        Ok(changed)
    }
}
