use super::*;

impl SupervisorTickAdmissionHandler {
    pub(in crate::workspace_outbox_worker::supervisor) async fn reconcile_supervisor_create_repair_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
        ctx: &mut SupervisorTickContext,
    ) -> CoreResult<usize> {
        let now = Utc::now();
        let nodes_by_id = ctx
            .nodes
            .iter()
            .map(|node| (node.id.clone(), node.clone()))
            .collect::<HashMap<_, _>>();
        let mut created_nodes = Vec::new();
        let mut changed = 0;
        for node in ctx.nodes.iter_mut() {
            if node.workspace_task_id.as_deref().is_none_or(str::is_empty) {
                continue;
            }
            let mut metadata = object_or_empty(node.metadata_json.clone());
            if !supervisor_create_repair_metadata_present(&metadata) {
                continue;
            }
            if supervisor_create_repair_projection_complete(node, &metadata, &nodes_by_id) {
                continue;
            }

            let previous_attempt_id = node.current_attempt_id.clone();
            let mut evidence_refs = Vec::new();
            let summary = supervisor_create_repair_summary(&metadata);
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
                                Some(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_REASON),
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
                .project_supervisor_create_repair_to_task(
                    workspace_id,
                    node,
                    previous_attempt_id.as_deref(),
                    &summary,
                    &evidence_refs,
                    now,
                )
                .await?;

            let existing_repair_id = existing_repair_node_id_for_original(&nodes_by_id, &node.id);
            let (repair_node_id, repair_node_created) =
                if let Some(repair_node_id) = existing_repair_id {
                    (repair_node_id, false)
                } else {
                    let repair_node_id = generated_repair_node_id();
                    let repair_node = supervisor_repair_plan_node(
                        node,
                        &metadata,
                        &repair_node_id,
                        &summary,
                        &evidence_refs,
                        previous_attempt_id.as_deref(),
                        now,
                    );
                    self.store.create_plan_node(repair_node.clone()).await?;
                    created_nodes.push(repair_node);
                    (repair_node_id, true)
                };

            clear_supervisor_create_repair_node_metadata(&mut metadata);
            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "last_verification_judge_verdict".to_string(),
                json!("needs_rework"),
            );
            metadata.insert(
                "last_verification_judge_next_action_kind".to_string(),
                json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
            );
            metadata.insert(
                "last_verification_judge_required_next_action".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "blocked_by_repair_node_id".to_string(),
                json!(repair_node_id.clone()),
            );
            metadata.insert(
                "supervisor_repair_node_id".to_string(),
                json!(repair_node_id.clone()),
            );
            metadata.insert(
                "supervisor_repair_requested_at".to_string(),
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
            metadata.insert(
                "replan_source".to_string(),
                json!("verification_judge_create_repair_node"),
            );
            metadata.insert("replan_trigger".to_string(), json!("verification_failed"));
            if let Some(attempt_id) = previous_attempt_id.as_deref() {
                metadata.insert(
                    "supervisor_repair_previous_attempt_id".to_string(),
                    json!(attempt_id),
                );
            }
            if !evidence_refs.is_empty() {
                metadata.insert(
                    "verification_evidence_refs".to_string(),
                    json!(evidence_refs),
                );
            }
            push_unique_string(&mut node.depends_on_json, repair_node_id.clone());
            node.intent = "todo".to_string();
            node.execution = "idle".to_string();
            node.current_attempt_id = None;
            node.metadata_json = Value::Object(metadata);
            node.completed_at = None;
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node.id.clone()),
                    attempt_id: previous_attempt_id.clone(),
                    event_type: "supervisor_create_repair_node_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "action": SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION,
                        "reason": SUPERVISOR_DECISION_CREATE_REPAIR_NODE_REASON,
                        "rationale": summary,
                        "workspace_task_id": node.workspace_task_id.clone(),
                        "previous_attempt_id": previous_attempt_id,
                        "repair_node_id": repair_node_id,
                        "repair_node_created": repair_node_created,
                        "task_projected": task_projected,
                        "attempt_projected": attempt_projected,
                    }),
                    created_at: now,
                })
                .await?;
            changed += 1;
        }
        ctx.nodes.extend(created_nodes);
        Ok(changed)
    }

    async fn project_supervisor_create_repair_to_task(
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
            && metadata_string(metadata.get("supervisor_repair_requested_at")).is_some()
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
            "supervisor_repair_requested_at".to_string(),
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
            json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
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
