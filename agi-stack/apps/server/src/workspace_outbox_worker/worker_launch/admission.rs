use super::*;

impl WorkerLaunchAdmissionHandler {
    pub(super) async fn runtime_launch_admission(
        &self,
        conversation_id: &str,
        reuse_existing: bool,
        stream_poll: bool,
    ) -> WorkerLaunchAdmissionSnapshot {
        if reuse_existing && self.runtime_agent_running_exists(conversation_id).await {
            return WorkerLaunchAdmissionSnapshot {
                conversation_id: conversation_id.to_string(),
                reuse_existing,
                stream_poll,
                cooldown_claimed: None,
                action: WorkerLaunchAdmissionAction::SkipAlreadyRunning,
            };
        }

        if reuse_existing {
            self.runtime_clear_reused_session_markers(conversation_id)
                .await;
        }

        let cooldown_claimed = if stream_poll {
            None
        } else {
            Some(self.runtime_claim_launch_cooldown(conversation_id).await)
        };
        let action = if cooldown_claimed == Some(false) {
            WorkerLaunchAdmissionAction::SkipCooldownActive
        } else {
            WorkerLaunchAdmissionAction::Admit
        };

        WorkerLaunchAdmissionSnapshot {
            conversation_id: conversation_id.to_string(),
            reuse_existing,
            stream_poll,
            cooldown_claimed,
            action,
        }
    }

    pub(super) async fn runtime_agent_running_exists(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .agent_running_exists(conversation_id)
            .await
        {
            Ok(exists) => exists,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: agent:running check failed for {conversation_id}: {err}"
                );
                false
            }
        }
    }

    pub(super) async fn runtime_clear_reused_session_markers(&self, conversation_id: &str) {
        if let Err(err) = self
            .runtime_state
            .clear_reused_session_markers(conversation_id)
            .await
        {
            eprintln!(
                "[agistack] worker launch state: clear reused markers failed for {conversation_id}: {err}"
            );
        }
    }

    pub(super) async fn runtime_refresh_bound_session_markers(&self, conversation_id: &str) {
        self.runtime_refresh_launch_cooldown(conversation_id).await;
        if self
            .runtime_agent_finished_message_id(conversation_id)
            .await
            .is_some()
        {
            return;
        }
        self.runtime_refresh_agent_running_marker(conversation_id)
            .await;
    }

    async fn runtime_refresh_launch_cooldown(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .refresh_launch_cooldown(conversation_id, WORKER_LAUNCH_COOLDOWN_SECONDS)
            .await
        {
            Ok(refreshed) => refreshed,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: cooldown refresh failed for {conversation_id}: {err}"
                );
                false
            }
        }
    }

    pub(super) async fn runtime_agent_finished_message_id(
        &self,
        conversation_id: &str,
    ) -> Option<String> {
        match self
            .runtime_state
            .agent_finished_message_id(conversation_id)
            .await
        {
            Ok(message_id) => message_id,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: agent:finished read failed for {conversation_id}: {err}"
                );
                None
            }
        }
    }

    async fn runtime_refresh_agent_running_marker(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .refresh_agent_running_marker(conversation_id, WORKER_LAUNCH_COOLDOWN_SECONDS)
            .await
        {
            Ok(refreshed) => refreshed,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: agent:running refresh failed for {conversation_id}: {err}"
                );
                false
            }
        }
    }

    pub(super) async fn runtime_claim_launch_cooldown(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .claim_launch_cooldown(conversation_id, WORKER_LAUNCH_COOLDOWN_SECONDS)
            .await
        {
            Ok(claimed) => claimed,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: cooldown claim failed for {conversation_id}: {err}"
                );
                true
            }
        }
    }

    pub(super) async fn stale_worker_launch_reason(
        &self,
        task: &WorkspaceTaskRecord,
        plan_id: Option<&str>,
        node_id: Option<&str>,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<String>> {
        let mut reason = None;
        if let Some(attempt_id) = attempt_id {
            match self.store.get_task_session_attempt(attempt_id).await? {
                None => reason = Some("attempt_missing".to_string()),
                Some(attempt) => {
                    if attempt.workspace_task_id != task.id
                        || attempt.workspace_id != task.workspace_id
                    {
                        reason = Some("attempt_task_mismatch".to_string());
                    } else if !WORKER_LAUNCHABLE_ATTEMPT_STATUSES.contains(&attempt.status.as_str())
                    {
                        reason = Some(format!("attempt_{}", attempt.status));
                    }
                }
            }
        }

        let task_metadata = object_or_empty(task.metadata_json.clone());
        let current_task_attempt_id = string_from_map(&task_metadata, CURRENT_ATTEMPT_ID);
        if reason.is_none()
            && current_task_attempt_id.is_some()
            && current_task_attempt_id.as_deref() != attempt_id
        {
            reason = Some("task_current_attempt_changed".to_string());
        }

        if reason.is_none() {
            if let (Some(plan_id), Some(node_id)) = (plan_id, node_id) {
                if self
                    .store
                    .has_supervisor_dispose_decision_for_node(&task.workspace_id, plan_id, node_id)
                    .await?
                {
                    return Ok(Some("supervisor_disposed_node".to_string()));
                }
                if let Some(plan) = self.store.get_plan(plan_id).await? {
                    if plan.workspace_id == task.workspace_id {
                        let nodes = self.store.list_plan_nodes(plan_id).await?;
                        if let Some(node) =
                            nodes.into_iter().find(|candidate| candidate.id == node_id)
                        {
                            if node.workspace_task_id.as_deref().is_some()
                                && node.workspace_task_id.as_deref() != Some(task.id.as_str())
                            {
                                reason = Some("node_task_mismatch".to_string());
                            } else if node.current_attempt_id.as_deref().is_some()
                                && node.current_attempt_id.as_deref() != attempt_id
                            {
                                reason = Some("node_current_attempt_changed".to_string());
                            } else if node.intent == "done" || node.execution == "idle" {
                                reason = Some("node_not_launchable".to_string());
                            }
                        }
                    }
                }
            }
        }
        Ok(reason)
    }

    pub(super) async fn defer_active_capacity_count(
        &self,
        workspace_id: &str,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<i64>> {
        let max_active = self.config.max_active_worker_conversations;
        if max_active <= 0 {
            return Ok(None);
        }
        if let Some(attempt_id) = attempt_id {
            if self
                .store
                .get_task_session_attempt(attempt_id)
                .await?
                .and_then(|attempt| attempt.conversation_id)
                .is_some()
            {
                return Ok(None);
            }
        }
        let active_after =
            Utc::now() - ChronoDuration::seconds(self.config.active_event_grace_seconds.max(1));
        let active_count = self
            .store
            .count_recent_running_task_session_attempts_with_conversation(
                workspace_id,
                active_after,
            )
            .await?;
        Ok((active_count >= max_active).then_some(active_count))
    }

    pub(super) async fn mark_plan_node_running_after_launch_schedule(
        &self,
        plan_id: Option<&str>,
        node_id: Option<&str>,
        attempt_id: Option<&str>,
        conversation_id: Option<&str>,
        launch_state: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let (Some(plan_id), Some(node_id)) = (plan_id, node_id) else {
            return Ok(());
        };
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(());
        };
        if attempt_id.is_some()
            && node.current_attempt_id.as_deref().is_some()
            && node.current_attempt_id.as_deref() != attempt_id
        {
            return Ok(());
        }
        if !matches!(node.execution.as_str(), "dispatched" | "running") {
            return Ok(());
        }
        node.execution = "running".to_string();
        if let Some(attempt_id) = attempt_id {
            node.current_attempt_id = Some(attempt_id.to_string());
        }
        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert("launch_state".to_string(), json!(launch_state));
        metadata.insert(
            "worker_launch_admitted_at".to_string(),
            json!(now.to_rfc3339()),
        );
        if let Some(conversation_id) = conversation_id {
            metadata.insert(
                CURRENT_ATTEMPT_CONVERSATION_ID.to_string(),
                json!(conversation_id),
            );
            metadata.insert(
                "worker_launch_bound_at".to_string(),
                json!(now.to_rfc3339()),
            );
        }
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node).await?;
        Ok(())
    }

    pub(super) async fn load_launch_node(
        &self,
        plan_id: Option<&str>,
        node_id: Option<&str>,
    ) -> CoreResult<Option<WorkspacePlanNodeRecord>> {
        let (Some(plan_id), Some(node_id)) = (plan_id, node_id) else {
            return Ok(None);
        };
        Ok(self
            .store
            .list_plan_nodes(plan_id)
            .await?
            .into_iter()
            .find(|candidate| candidate.id == node_id))
    }

    pub(super) async fn block_task_for_worktree_setup_failure(
        &self,
        mut task: WorkspaceTaskRecord,
        mut task_metadata: Map<String, Value>,
        launch_node: Option<WorkspacePlanNodeRecord>,
        attempt_id: Option<&str>,
        context: &WorkerLaunchWorktreeContext,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let reason = context
            .setup_reason
            .as_deref()
            .unwrap_or("attempt worktree setup failed");
        let summary = format!("worktree_setup_failed: {reason}");
        merge_metadata_patch(&mut task_metadata, &context.metadata_patch);
        task_metadata.insert("launch_state".to_string(), json!("worktree_setup_failed"));
        task_metadata.insert("last_attempt_status".to_string(), json!("blocked"));
        if let Some(attempt_id) = attempt_id {
            task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        task.metadata_json = Value::Object(task_metadata);
        task.status = "blocked".to_string();
        task.blocker_reason = Some(summary.clone());
        task.completed_at = None;
        task.updated_at = Some(now);
        self.store.save_task(task).await?;

        if let Some(attempt_id) = attempt_id {
            let _ = self
                .store
                .finish_task_session_attempt(
                    attempt_id,
                    "blocked",
                    Some(&summary),
                    Some("worktree_setup_failed"),
                    now,
                )
                .await?;
        }

        if let Some(mut node) = launch_node {
            let mut node_metadata = object_or_empty(node.metadata_json);
            merge_metadata_patch(&mut node_metadata, &context.metadata_patch);
            node_metadata.insert("worktree_setup_failure_summary".to_string(), json!(summary));
            node_metadata.insert("last_attempt_status".to_string(), json!("blocked"));
            if let Some(attempt_id) = attempt_id {
                node_metadata.insert("terminal_attempt_status".to_string(), json!("blocked"));
                node_metadata.insert(
                    "terminal_attempt_reconciled_at".to_string(),
                    json!(now.to_rfc3339()),
                );
                node_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
            }
            node.intent = "blocked".to_string();
            node.execution = "idle".to_string();
            node.current_attempt_id = None;
            node.metadata_json = Value::Object(node_metadata);
            node.completed_at = None;
            node.updated_at = Some(now);
            self.store.save_plan_node(node).await?;
        }
        Ok(())
    }
}
