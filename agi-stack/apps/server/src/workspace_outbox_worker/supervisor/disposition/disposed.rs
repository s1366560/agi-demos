use super::super::*;

impl SupervisorTickAdmissionHandler {
    pub(in crate::workspace_outbox_worker::supervisor) async fn reconcile_supervisor_disposed_nodes(
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
            let has_dispose_metadata = supervisor_dispose_metadata_present(node);
            let has_dispose_event = self
                .store
                .has_supervisor_dispose_decision_for_node(workspace_id, plan_id, &node.id)
                .await?;
            if !has_dispose_metadata && !has_dispose_event {
                continue;
            }

            let mut metadata = object_or_empty(node.metadata_json.clone());
            let disposition = supervisor_disposition_value(&metadata);
            let summary = supervisor_disposition_summary(&metadata);
            let already_projected_node = node.intent == "done"
                && node.execution == "idle"
                && metadata_string(metadata.get("verification_feedback_disposition")).as_deref()
                    == Some(disposition.as_str())
                && metadata_string(metadata.get("workspace_task_projection_status")).as_deref()
                    == Some("done");

            metadata.insert(
                "verification_feedback_disposition".to_string(),
                json!(disposition.clone()),
            );
            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_DISPOSE_NODE_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "supervisor_disposition_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "workspace_task_projection_status".to_string(),
                json!("done"),
            );
            metadata.insert(
                "workspace_task_projected_at".to_string(),
                json!(now.to_rfc3339()),
            );
            let original_node = node.clone();
            node.intent = "done".to_string();
            node.execution = "idle".to_string();
            node.metadata_json = Value::Object(metadata.clone());
            node.updated_at = Some(now);
            if node.completed_at.is_none() {
                node.completed_at = Some(now);
            }

            let task_projected = self
                .project_supervisor_disposition_to_task(
                    workspace_id,
                    node,
                    &summary,
                    &disposition,
                    now,
                )
                .await?;
            if !already_projected_node || task_projected {
                self.store.save_plan_node(node.clone()).await?;
                self.store
                    .create_plan_event(WorkspacePlanEventRecord {
                        id: generate_uuid_v4(),
                        plan_id: plan_id.to_string(),
                        workspace_id: workspace_id.to_string(),
                        node_id: Some(node.id.clone()),
                        attempt_id: node.current_attempt_id.clone(),
                        event_type: "supervisor_disposition_reconciled".to_string(),
                        source: "workspace_plan_supervisor_tick".to_string(),
                        actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                        payload_json: json!({
                            "action": SUPERVISOR_DECISION_DISPOSE_NODE_ACTION,
                            "disposition": disposition,
                            "rationale": summary,
                            "workspace_task_id": node.workspace_task_id.clone(),
                            "task_projected": task_projected,
                            "had_dispose_event": has_dispose_event,
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

    async fn project_supervisor_disposition_to_task(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        summary: &str,
        disposition: &str,
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
        if task.status == "done"
            && metadata_string(metadata.get("durable_plan_verdict")).as_deref() == Some("disposed")
            && metadata_string(metadata.get("durable_plan_disposition")).as_deref()
                == Some(disposition)
            && metadata_string(metadata.get("durable_plan_verification_summary")).as_deref()
                == Some(summary)
        {
            return Ok(false);
        }

        metadata.insert(PENDING_LEADER_ADJUDICATION.to_string(), json!(false));
        metadata.insert("durable_plan_verdict".to_string(), json!("disposed"));
        metadata.insert("durable_plan_disposition".to_string(), json!(disposition));
        metadata.insert(
            "durable_plan_verification_summary".to_string(),
            json!(summary),
        );
        metadata.insert(
            "durable_plan_verified_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "last_attempt_status".to_string(),
            json!(DISPOSED_ATTEMPT_STATUS),
        );
        metadata.insert(
            "last_worker_report_type".to_string(),
            json!(DISPOSED_ATTEMPT_STATUS),
        );
        metadata.insert(LAST_WORKER_REPORT_SUMMARY.to_string(), json!(summary));
        metadata.insert(
            "last_leader_adjudication_status".to_string(),
            json!(DISPOSED_ATTEMPT_STATUS),
        );
        if let Some(attempt_id) = node.current_attempt_id.as_deref() {
            metadata.insert("last_attempt_id".to_string(), json!(attempt_id));
            metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        copy_supervisor_disposition_event_payload_fields(
            &object_or_empty(node.metadata_json.clone()),
            &mut metadata,
        );

        task.metadata_json = Value::Object(metadata);
        task.status = "done".to_string();
        task.blocker_reason = None;
        task.completed_at = Some(now);
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
