use super::super::*;

impl SupervisorTickAdmissionHandler {
    pub(in crate::workspace_outbox_worker::supervisor) async fn reconcile_supervisor_blocked_human_nodes(
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

            let original_node = node.clone();
            node.intent = "blocked".to_string();
            node.execution = "idle".to_string();
            node.metadata_json = Value::Object(metadata.clone());
            node.updated_at = Some(now);

            let task_projected = self
                .project_supervisor_blocked_human_to_task(workspace_id, node, &summary, now)
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
            } else {
                *node = original_node;
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
}
