use super::*;

impl SupervisorTickAdmissionHandler {
    pub(in crate::workspace_outbox_worker::supervisor) async fn reconcile_supervisor_retry_same_node_attempt_nodes(
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
}
