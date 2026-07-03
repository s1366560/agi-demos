use super::*;

impl WorkerLaunchAdmissionHandler {
    #[allow(dead_code)]
    pub(in crate::workspace_outbox_worker) async fn persist_worker_stream_terminal_outcome(
        &self,
        input: WorkerStreamTerminalPersistence<'_>,
    ) -> CoreResult<bool> {
        let Some(mut task) = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
        else {
            return Ok(false);
        };
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        let root_goal_task_id = input
            .root_goal_task_id
            .map(ToOwned::to_owned)
            .or_else(|| string_from_map(&task_metadata, ROOT_GOAL_TASK_ID));
        if let (Some(expected), Some(actual)) = (
            input.root_goal_task_id,
            string_from_map(&task_metadata, ROOT_GOAL_TASK_ID),
        ) {
            if actual != expected {
                return Err(CoreError::Storage(
                    "worker stream terminal report task does not belong to root goal".into(),
                ));
            }
        }
        let plan_id = input
            .plan_id
            .map(ToOwned::to_owned)
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_ID));
        let node_id = input
            .node_id
            .map(ToOwned::to_owned)
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_NODE_ID));
        let v2_plan_linked = plan_id
            .as_deref()
            .is_some_and(|value| !value.trim().is_empty())
            && node_id
                .as_deref()
                .is_some_and(|value| !value.trim().is_empty());

        task_metadata.insert(
            "launch_state".to_string(),
            json!(input.outcome.launch_state),
        );

        let mut reported = false;
        if input.outcome.should_report {
            if let (Some(attempt_id), Some(report_type)) =
                (input.attempt_id, input.outcome.report_type.as_ref())
            {
                if !is_stale_terminal_worker_report(&task_metadata, attempt_id) {
                    let report_type = report_type.as_str();
                    let report = build_worker_report_payload(
                        &task_metadata,
                        report_type,
                        &input.outcome.summary,
                        &[],
                        None,
                    );
                    let pending_leader = !v2_plan_linked;
                    let last_attempt_status = if v2_plan_linked {
                        "awaiting_plan_verification"
                    } else {
                        AWAITING_LEADER_ADJUDICATION_STATUS
                    };
                    task_metadata
                        .insert("evidence_refs".to_string(), json!(report.merged_artifacts));
                    task_metadata.insert(
                        "execution_verifications".to_string(),
                        json!(report.merged_verifications),
                    );
                    task_metadata.insert("last_worker_report_type".to_string(), json!(report_type));
                    task_metadata.insert(
                        LAST_WORKER_REPORT_SUMMARY.to_string(),
                        json!(report.normalized_summary.clone()),
                    );
                    task_metadata.insert(
                        "last_worker_report_artifacts".to_string(),
                        json!(report.merged_artifacts.clone()),
                    );
                    task_metadata.insert(
                        "last_worker_report_verifications".to_string(),
                        json!(report.report_verifications.clone()),
                    );
                    task_metadata.insert(
                        "last_worker_reported_at".to_string(),
                        json!(input.now.to_rfc3339()),
                    );
                    task_metadata.insert(
                        "last_worker_report_fingerprint".to_string(),
                        json!(report.fingerprint.clone()),
                    );
                    task_metadata
                        .insert(LAST_WORKER_REPORT_ATTEMPT_ID.to_string(), json!(attempt_id));
                    task_metadata.insert(
                        PENDING_LEADER_ADJUDICATION.to_string(),
                        json!(pending_leader),
                    );
                    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
                    task_metadata.insert("last_attempt_id".to_string(), json!(attempt_id));
                    if let Some(conversation_id) = input.conversation_id {
                        task_metadata.insert(
                            CURRENT_ATTEMPT_CONVERSATION_ID.to_string(),
                            json!(conversation_id),
                        );
                    }
                    task_metadata.insert(
                        "current_attempt_worker_agent_id".to_string(),
                        json!(input.worker_agent_id),
                    );
                    if let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? {
                        task_metadata.insert(
                            "current_attempt_number".to_string(),
                            json!(attempt.attempt_number),
                        );
                    }
                    task_metadata.insert(
                        "last_attempt_status".to_string(),
                        json!(last_attempt_status),
                    );
                    task_metadata.insert(
                        "execution_state".to_string(),
                        worker_execution_state(
                            "in_progress",
                            &format!(
                                "workspace_goal_runtime.worker_report.{report_type}:{}",
                                report.normalized_summary
                            ),
                            if v2_plan_linked {
                                "await_plan_verification"
                            } else {
                                "await_leader_adjudication"
                            },
                            input.worker_agent_id,
                            input.now,
                        ),
                    );

                    let recorded = self
                        .store
                        .record_task_session_attempt_candidate_output(
                            attempt_id,
                            Some(&report.normalized_summary),
                            &report.report_artifacts,
                            &report.report_verifications,
                            input.conversation_id,
                            input.now,
                        )
                        .await?
                        .is_some();
                    if recorded {
                        reported = true;
                        if let (Some(plan_id), Some(node_id), Some(root_goal_task_id)) = (
                            plan_id.as_deref(),
                            node_id.as_deref(),
                            root_goal_task_id.as_deref(),
                        ) {
                            self.mark_workspace_plan_node_reported(
                                &input,
                                plan_id,
                                node_id,
                                root_goal_task_id,
                                report_type,
                                &report,
                            )
                            .await?;
                        }
                    }
                }
            }
        } else {
            task_metadata.insert(
                "execution_state".to_string(),
                worker_execution_state(
                    "in_progress",
                    &format!("workspace_worker_launch.{}", input.outcome.launch_state),
                    "observe",
                    input.leader_agent_id.unwrap_or(input.actor_user_id),
                    input.now,
                ),
            );
        }

        task.metadata_json = Value::Object(task_metadata);
        if task.status == "todo" {
            task.status = "in_progress".to_string();
            task.completed_at = None;
        }
        if input
            .outcome
            .report_type
            .as_ref()
            .is_some_and(|report_type| {
                report_type.as_str() == "blocked" && input.outcome.should_report
            })
        {
            task.blocker_reason = Some(input.outcome.summary.clone());
        }
        task.updated_at = Some(input.now);
        self.store.save_task(task).await?;
        Ok(reported)
    }

    async fn mark_workspace_plan_node_reported(
        &self,
        input: &WorkerStreamTerminalPersistence<'_>,
        plan_id: &str,
        node_id: &str,
        root_goal_task_id: &str,
        report_type: &str,
        report: &WorkerReportPayload,
    ) -> CoreResult<()> {
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(());
        };
        if input
            .attempt_id
            .is_some_and(|attempt_id| node.current_attempt_id.as_deref() != Some(attempt_id))
        {
            return Ok(());
        }
        let Some(attempt_id) = input.attempt_id else {
            return Ok(());
        };
        let mut progress = object_or_empty(node.progress_json.clone());
        progress
            .entry("percent".to_string())
            .or_insert_with(|| json!(0.0));
        progress
            .entry("confidence".to_string())
            .or_insert_with(|| json!(1.0));
        progress.insert("note".to_string(), json!(report.normalized_summary.clone()));

        let mut metadata = object_or_empty(node.metadata_json.clone());
        let reported_at = input.now.to_rfc3339();
        let report_event = json!({
            "event_type": "worker_report_terminal",
            "source_event_type": "worker_report_terminal",
            "summary": report.normalized_summary,
            "attempt_id": attempt_id,
            "worker_agent_id": input.worker_agent_id,
            "reported_at": reported_at
        });
        let mut progress_events = metadata
            .get("progress_events")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        progress_events.push(report_event.clone());
        if progress_events.len() > 25 {
            progress_events = progress_events.split_off(progress_events.len() - 25);
        }
        metadata.insert("progress_events".to_string(), Value::Array(progress_events));
        metadata.insert("latest_worker_progress".to_string(), report_event);
        metadata.insert(
            "launch_state".to_string(),
            json!(input.outcome.launch_state),
        );
        metadata.insert("last_worker_report_type".to_string(), json!(report_type));
        metadata.insert(
            LAST_WORKER_REPORT_SUMMARY.to_string(),
            json!(report.normalized_summary.clone()),
        );
        metadata.insert(LAST_WORKER_REPORT_ATTEMPT_ID.to_string(), json!(attempt_id));
        metadata.insert("last_worker_reported_at".to_string(), json!(reported_at));

        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some(attempt_id.to_string());
        node.progress_json = Value::Object(progress);
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(input.now);
        self.store.save_plan_node(node).await?;
        self.store
            .create_plan_event(WorkspacePlanEventRecord {
                id: generate_uuid_v4(),
                plan_id: plan_id.to_string(),
                workspace_id: input.workspace_id.to_string(),
                node_id: Some(node_id.to_string()),
                attempt_id: Some(attempt_id.to_string()),
                event_type: "worker_report_terminal".to_string(),
                source: "worker_report".to_string(),
                actor_id: Some(input.worker_agent_id.to_string()),
                payload_json: json!({
                    "report_type": report_type,
                    "summary": report.normalized_summary,
                    "artifacts": report.report_artifacts,
                    "verifications": report.report_verifications,
                    "reported_at": input.now.to_rfc3339()
                }),
                created_at: input.now,
            })
            .await?;
        self.store
            .enqueue_plan_outbox(worker_report_supervisor_tick(
                input.workspace_id,
                plan_id,
                node_id,
                attempt_id,
                root_goal_task_id,
                input.actor_user_id,
                input.leader_agent_id,
                input.now,
            ))
            .await?;
        Ok(())
    }
}
