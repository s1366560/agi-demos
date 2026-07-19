use super::*;

mod create_repair;

impl SupervisorTickAdmissionHandler {
    pub(super) async fn reconcile_supervisor_replan_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
        ctx: &mut SupervisorTickContext,
    ) -> CoreResult<usize> {
        let now = Utc::now();
        let mut changed = 0;
        for node in ctx.nodes.iter_mut() {
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
                    node,
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
            node.feature_checkpoint_json =
                reset_feature_checkpoint(node.feature_checkpoint_json.clone());
            node.metadata_json = Value::Object(metadata);
            node.completed_at = None;
            node.updated_at = Some(now);

            let replan_outbox = supervisor_replan_tick_outbox(SupervisorReplanTickOutboxInput {
                workspace_id,
                plan_id,
                node_id: &node.id,
                task_id: replan_task_id.as_deref(),
                worker_agent_id: replan_worker_agent_id.as_deref(),
                reason: &summary,
                previous_attempt_id: previous_attempt_id.as_deref(),
                now,
            });
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
}
