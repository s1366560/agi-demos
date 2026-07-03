use super::*;

impl SupervisorTickAdmissionHandler {
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn reconcile_terminal_attempt_nodes(
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
                    .project_accepted_attempt_to_task(AcceptedAttemptTaskProjection {
                        workspace_id,
                        node: &node,
                        attempt: &accepted_attempt,
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

    pub(super) async fn reconcile_supervisor_retry_same_node_attempt_nodes(
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

    pub(super) async fn reconcile_reported_attempt_nodes(
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

    pub(super) async fn retry_context_for_node(
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
