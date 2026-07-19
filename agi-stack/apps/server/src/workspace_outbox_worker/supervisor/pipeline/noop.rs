use super::super::*;

impl SupervisorTickAdmissionHandler {
    pub(in crate::workspace_outbox_worker::supervisor) async fn reconcile_supervisor_noop_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
        ctx: &mut SupervisorTickContext,
    ) -> CoreResult<usize> {
        let now = Utc::now();
        let mut changed = 0;
        for node in ctx.nodes.iter_mut() {
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
