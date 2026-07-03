use super::*;

impl SupervisorTickAdmissionHandler {
    pub(super) async fn reconcile_supervisor_request_pipeline_nodes(
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

    pub(super) async fn reconcile_supervisor_wait_pipeline_nodes(
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

    pub(super) async fn reconcile_supervisor_noop_nodes(
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
}
