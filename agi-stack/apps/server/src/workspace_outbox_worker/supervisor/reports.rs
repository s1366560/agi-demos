use super::*;

impl SupervisorTickAdmissionHandler {
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn handle_worker_report_supervisor_tick(
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

    pub(super) async fn recover_missing_attempt_nodes(
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
