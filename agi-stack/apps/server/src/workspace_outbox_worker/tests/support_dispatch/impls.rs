use super::*;

#[async_trait]
impl WorkspacePlanDispatchStore for FakeWorkspacePlanDispatchStore {
    async fn get_workspace(&self, workspace_id: &str) -> CoreResult<Option<WorkspaceRecord>> {
        Ok(self.workspaces.lock().unwrap().get(workspace_id).cloned())
    }

    async fn get_task(
        &self,
        workspace_id: &str,
        task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskRecord>> {
        Ok(self
            .tasks
            .lock()
            .unwrap()
            .get(task_id)
            .filter(|task| task.workspace_id == workspace_id)
            .cloned())
    }

    async fn list_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        let mut tasks = self
            .tasks
            .lock()
            .unwrap()
            .values()
            .filter(|task| {
                task.workspace_id == workspace_id
                    && task.archived_at.is_none()
                    && string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID).as_deref()
                        == Some(root_goal_task_id)
            })
            .cloned()
            .collect::<Vec<_>>();
        tasks.sort_by(|left, right| {
            left.created_at
                .cmp(&right.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(tasks)
    }

    async fn list_current_plan_child_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        let nodes = self.nodes.lock().unwrap().clone();
        let mut tasks = self
            .tasks
            .lock()
            .unwrap()
            .values()
            .filter(|task| {
                if task.workspace_id != workspace_id || task.archived_at.is_some() {
                    return false;
                }
                if string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID).as_deref()
                    != Some(root_goal_task_id)
                {
                    return false;
                }
                let Some(plan_id) =
                    string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_ID)
                else {
                    return false;
                };
                let Some(node_id) =
                    string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_NODE_ID)
                else {
                    return false;
                };
                nodes.get(&node_id).is_some_and(|node| {
                    node.plan_id == plan_id
                        && node.workspace_task_id.as_deref() == Some(task.id.as_str())
                })
            })
            .cloned()
            .collect::<Vec<_>>();
        tasks.sort_by(|left, right| {
            left.created_at
                .cmp(&right.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(tasks)
    }

    async fn save_task(&self, task: WorkspaceTaskRecord) -> CoreResult<WorkspaceTaskRecord> {
        self.tasks
            .lock()
            .unwrap()
            .insert(task.id.clone(), task.clone());
        Ok(task)
    }

    async fn get_plan(&self, plan_id: &str) -> CoreResult<Option<WorkspacePlanRecord>> {
        Ok(self.plans.lock().unwrap().get(plan_id).cloned())
    }

    async fn list_plan_nodes(&self, plan_id: &str) -> CoreResult<Vec<WorkspacePlanNodeRecord>> {
        Ok(self
            .nodes
            .lock()
            .unwrap()
            .values()
            .filter(|node| node.plan_id == plan_id)
            .cloned()
            .collect())
    }

    async fn create_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord> {
        self.nodes
            .lock()
            .unwrap()
            .insert(node.id.clone(), node.clone());
        Ok(node)
    }

    async fn save_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord> {
        self.nodes
            .lock()
            .unwrap()
            .insert(node.id.clone(), node.clone());
        Ok(node)
    }

    async fn find_active_task_session_attempt(
        &self,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self
            .attempts
            .lock()
            .unwrap()
            .values()
            .filter(|attempt| {
                attempt.workspace_task_id == workspace_task_id
                    && matches!(
                        attempt.status.as_str(),
                        "pending" | "running" | "awaiting_leader_adjudication"
                    )
            })
            .cloned()
            .collect::<Vec<_>>();
        attempts.sort_by(|left, right| {
            right
                .attempt_number
                .cmp(&left.attempt_number)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(attempts.into_iter().next())
    }

    async fn find_latest_accepted_task_session_attempt(
        &self,
        workspace_id: &str,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self
            .attempts
            .lock()
            .unwrap()
            .values()
            .filter(|attempt| {
                attempt.workspace_id == workspace_id
                    && attempt.workspace_task_id == workspace_task_id
                    && attempt.status == ACCEPTED_ATTEMPT_STATUS
            })
            .cloned()
            .collect::<Vec<_>>();
        attempts.sort_by(|left, right| {
            right
                .attempt_number
                .cmp(&left.attempt_number)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(attempts.into_iter().next())
    }

    async fn get_task_session_attempt(
        &self,
        attempt_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        Ok(self.attempts.lock().unwrap().get(attempt_id).cloned())
    }

    async fn latest_pipeline_run_for_node(
        &self,
        plan_id: &str,
        node_id: &str,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        let mut runs = self
            .pipeline_runs
            .lock()
            .unwrap()
            .values()
            .filter(|run| {
                run.plan_id.as_deref() == Some(plan_id)
                    && run.node_id.as_deref() == Some(node_id)
                    && attempt_id
                        .is_none_or(|attempt_id| run.attempt_id.as_deref() == Some(attempt_id))
            })
            .cloned()
            .collect::<Vec<_>>();
        runs.sort_by(|left, right| {
            right
                .created_at
                .cmp(&left.created_at)
                .then_with(|| right.id.cmp(&left.id))
        });
        Ok(runs.into_iter().next())
    }

    async fn ensure_pipeline_contract(
        &self,
        contract_id: &str,
        workspace_id: &str,
        plan_id: &str,
        provider: &str,
        code_root: Option<&str>,
        commands_json: &Value,
        env_json: &Value,
        trigger_policy_json: &Value,
        timeout_seconds: i32,
        auto_deploy: bool,
        preview_port: Option<i32>,
        health_url: Option<&str>,
        metadata_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<String> {
        let mut contracts = self.pipeline_contracts.lock().unwrap();
        let key = (workspace_id.to_string(), plan_id.to_string());
        if let Some(existing) = contracts.get_mut(&key) {
            existing.provider = provider.to_string();
            existing.code_root = code_root.map(ToOwned::to_owned);
            existing.commands_json = commands_json.clone();
            existing.env_json = env_json.clone();
            existing.trigger_policy_json = trigger_policy_json.clone();
            existing.timeout_seconds = timeout_seconds.max(1);
            existing.auto_deploy = auto_deploy;
            existing.preview_port = preview_port;
            existing.health_url = health_url.map(ToOwned::to_owned);
            existing.metadata_json = metadata_json.clone();
            existing.updated_at = Some(now);
            return Ok(existing.id.clone());
        }
        let record = FakePipelineContractRecord {
            id: contract_id.to_string(),
            workspace_id: workspace_id.to_string(),
            plan_id: plan_id.to_string(),
            provider: provider.to_string(),
            code_root: code_root.map(ToOwned::to_owned),
            commands_json: commands_json.clone(),
            env_json: env_json.clone(),
            trigger_policy_json: trigger_policy_json.clone(),
            timeout_seconds: timeout_seconds.max(1),
            auto_deploy,
            preview_port,
            health_url: health_url.map(ToOwned::to_owned),
            metadata_json: metadata_json.clone(),
            created_at: now,
            updated_at: None,
        };
        let id = record.id.clone();
        contracts.insert(key, record);
        Ok(id)
    }

    async fn create_pipeline_run(
        &self,
        run: WorkspacePipelineRunRecord,
    ) -> CoreResult<WorkspacePipelineRunRecord> {
        self.pipeline_runs
            .lock()
            .unwrap()
            .insert(run.id.clone(), run.clone());
        Ok(run)
    }

    async fn finish_pipeline_run(
        &self,
        run_id: &str,
        status: &str,
        reason: Option<&str>,
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        let mut runs = self.pipeline_runs.lock().unwrap();
        let Some(run) = runs.get_mut(run_id) else {
            return Ok(None);
        };
        run.status = status.to_string();
        run.reason = reason.map(ToOwned::to_owned);
        run.completed_at = Some(completed_at);
        run.updated_at = Some(completed_at);
        let mut metadata = object_or_empty(run.metadata_json.clone());
        for (key, value) in object_or_empty(metadata_patch.clone()) {
            metadata.insert(key, value);
        }
        run.metadata_json = Value::Object(metadata);
        Ok(Some(run.clone()))
    }

    async fn create_pipeline_stage_run(
        &self,
        stage_run: WorkspacePipelineStageRunRecord,
    ) -> CoreResult<WorkspacePipelineStageRunRecord> {
        self.pipeline_stage_runs
            .lock()
            .unwrap()
            .insert(stage_run.id.clone(), stage_run.clone());
        Ok(stage_run)
    }

    async fn finish_pipeline_stage_run(
        &self,
        stage_run_id: &str,
        status: &str,
        exit_code: Option<i32>,
        stdout_preview: Option<&str>,
        stderr_preview: Option<&str>,
        log_ref: Option<&str>,
        artifact_refs: &[String],
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineStageRunRecord>> {
        let mut stage_runs = self.pipeline_stage_runs.lock().unwrap();
        let Some(stage_run) = stage_runs.get_mut(stage_run_id) else {
            return Ok(None);
        };
        stage_run.status = status.to_string();
        stage_run.exit_code = exit_code;
        stage_run.stdout_preview = stdout_preview.map(ToOwned::to_owned);
        stage_run.stderr_preview = stderr_preview.map(ToOwned::to_owned);
        stage_run.log_ref = log_ref.map(ToOwned::to_owned);
        stage_run.artifact_refs_json = artifact_refs.to_vec();
        stage_run.completed_at = Some(completed_at);
        let duration_ms = stage_run
            .started_at
            .map(|started_at| (completed_at - started_at).num_milliseconds().max(0))
            .unwrap_or(0);
        stage_run.duration_ms = Some(i32::try_from(duration_ms).unwrap_or(i32::MAX));
        stage_run.updated_at = Some(completed_at);
        let mut metadata = object_or_empty(stage_run.metadata_json.clone());
        for (key, value) in object_or_empty(metadata_patch.clone()) {
            metadata.insert(key, value);
        }
        stage_run.metadata_json = Value::Object(metadata);
        Ok(Some(stage_run.clone()))
    }

    async fn latest_task_session_attempt_number(&self, workspace_task_id: &str) -> CoreResult<i32> {
        Ok(self
            .attempts
            .lock()
            .unwrap()
            .values()
            .filter(|attempt| attempt.workspace_task_id == workspace_task_id)
            .map(|attempt| attempt.attempt_number)
            .max()
            .unwrap_or(0))
    }

    async fn create_task_session_attempt(
        &self,
        attempt: WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<WorkspaceTaskSessionAttemptRecord> {
        self.attempts
            .lock()
            .unwrap()
            .insert(attempt.id.clone(), attempt.clone());
        Ok(attempt)
    }

    async fn mark_task_session_attempt_running(
        &self,
        attempt_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self.attempts.lock().unwrap();
        let Some(attempt) = attempts.get_mut(attempt_id) else {
            return Ok(None);
        };
        attempt.status = "running".to_string();
        attempt.updated_at = Some(now);
        Ok(Some(attempt.clone()))
    }

    async fn ensure_worker_launch_conversation(
        &self,
        conversation_id: &str,
        project_id: &str,
        tenant_id: &str,
        user_id: &str,
        title: &str,
        agent_config_json: &Value,
        metadata_json: &Value,
        participant_agents_json: &[String],
        focused_agent_id: &str,
        workspace_id: &str,
        linked_workspace_task_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let mut conversations = self.conversations.lock().unwrap();
        if let Some(existing) = conversations.get(conversation_id) {
            if existing.workspace_id != workspace_id
                || existing.linked_workspace_task_id.as_deref() != Some(linked_workspace_task_id)
            {
                return Err(CoreError::Storage(format!(
                        "worker launch conversation {conversation_id} is linked to another workspace task"
                    )));
            }
        }
        conversations.insert(
            conversation_id.to_string(),
            FakeWorkerConversationRecord {
                id: conversation_id.to_string(),
                project_id: project_id.to_string(),
                tenant_id: tenant_id.to_string(),
                user_id: user_id.to_string(),
                title: title.to_string(),
                agent_config_json: agent_config_json.clone(),
                metadata_json: metadata_json.clone(),
                participant_agents_json: participant_agents_json.to_vec(),
                focused_agent_id: focused_agent_id.to_string(),
                workspace_id: workspace_id.to_string(),
                linked_workspace_task_id: Some(linked_workspace_task_id.to_string()),
                updated_at: now,
            },
        );
        Ok(())
    }

    async fn ensure_workspace_agent_conversation(
        &self,
        conversation_id: &str,
        project_id: &str,
        tenant_id: &str,
        user_id: &str,
        title: &str,
        agent_config_json: &Value,
        metadata_json: &Value,
        workspace_id: &str,
        linked_workspace_task_id: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let mut conversations = self.conversations.lock().unwrap();
        if let Some(existing) = conversations.get_mut(conversation_id) {
            if existing.workspace_id != workspace_id {
                return Err(CoreError::Storage(format!(
                    "workspace agent conversation {conversation_id} is linked to another workspace"
                )));
            }
            existing.agent_config_json = agent_config_json.clone();
            existing.metadata_json = metadata_json.clone();
            if let Some(task_id) = linked_workspace_task_id {
                existing.linked_workspace_task_id = Some(task_id.to_string());
            }
            existing.updated_at = now;
            return Ok(());
        }
        conversations.insert(
            conversation_id.to_string(),
            FakeWorkerConversationRecord {
                id: conversation_id.to_string(),
                project_id: project_id.to_string(),
                tenant_id: tenant_id.to_string(),
                user_id: user_id.to_string(),
                title: title.to_string(),
                agent_config_json: agent_config_json.clone(),
                metadata_json: metadata_json.clone(),
                participant_agents_json: Vec::new(),
                focused_agent_id: String::new(),
                workspace_id: workspace_id.to_string(),
                linked_workspace_task_id: linked_workspace_task_id.map(ToOwned::to_owned),
                updated_at: now,
            },
        );
        Ok(())
    }

    async fn list_workspace_member_user_ids(&self, workspace_id: &str) -> CoreResult<Vec<String>> {
        let mut members = self
            .members
            .lock()
            .unwrap()
            .get(workspace_id)
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .collect::<Vec<_>>();
        members.sort();
        Ok(members)
    }

    async fn list_active_workspace_agents(
        &self,
        workspace_id: &str,
    ) -> CoreResult<Vec<WorkspaceAgentRecord>> {
        Ok(self
            .agents
            .lock()
            .unwrap()
            .get(workspace_id)
            .cloned()
            .unwrap_or_default())
    }

    async fn create_workspace_message(
        &self,
        message: WorkspaceMessageRecord,
    ) -> CoreResult<WorkspaceMessageRecord> {
        self.messages
            .lock()
            .unwrap()
            .insert(message.id.clone(), message.clone());
        Ok(message)
    }

    async fn enqueue_blackboard_outbox(&self, outbox: BlackboardOutboxRecord) -> CoreResult<()> {
        self.blackboard_outbox.lock().unwrap().push(outbox);
        Ok(())
    }

    async fn bind_task_session_attempt_conversation(
        &self,
        attempt_id: &str,
        conversation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self.attempts.lock().unwrap();
        let Some(attempt) = attempts.get_mut(attempt_id) else {
            return Ok(None);
        };
        attempt.status = "running".to_string();
        attempt.conversation_id = Some(conversation_id.to_string());
        attempt.updated_at = Some(now);
        Ok(Some(attempt.clone()))
    }

    async fn finish_task_session_attempt(
        &self,
        attempt_id: &str,
        status: &str,
        leader_feedback: Option<&str>,
        adjudication_reason: Option<&str>,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self.attempts.lock().unwrap();
        let Some(attempt) = attempts.get_mut(attempt_id) else {
            return Ok(None);
        };
        attempt.status = status.to_string();
        attempt.leader_feedback = leader_feedback.map(ToOwned::to_owned);
        attempt.adjudication_reason = adjudication_reason.map(ToOwned::to_owned);
        attempt.completed_at = Some(completed_at);
        attempt.updated_at = Some(completed_at);
        Ok(Some(attempt.clone()))
    }

    async fn record_task_session_attempt_candidate_output(
        &self,
        attempt_id: &str,
        summary: Option<&str>,
        artifacts_json: &[String],
        verifications_json: &[String],
        conversation_id: Option<&str>,
        updated_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let mut attempts = self.attempts.lock().unwrap();
        let Some(attempt) = attempts.get_mut(attempt_id) else {
            return Ok(None);
        };
        if matches!(
            attempt.status.as_str(),
            "accepted" | "rejected" | "blocked" | "cancelled"
        ) {
            return Ok(Some(attempt.clone()));
        }
        attempt.status = AWAITING_LEADER_ADJUDICATION_STATUS.to_string();
        if let Some(conversation_id) = conversation_id {
            attempt.conversation_id = Some(conversation_id.to_string());
        }
        attempt.candidate_summary = summary.map(ToOwned::to_owned);
        attempt.candidate_artifacts_json = artifacts_json.to_vec();
        attempt.candidate_verifications_json = verifications_json.to_vec();
        attempt.updated_at = Some(updated_at);
        Ok(Some(attempt.clone()))
    }

    async fn count_recent_running_task_session_attempts_with_conversation(
        &self,
        _workspace_id: &str,
        _active_after: DateTime<Utc>,
    ) -> CoreResult<i64> {
        Ok(*self.active_worker_conversations.lock().unwrap())
    }

    async fn has_supervisor_dispose_decision_for_node(
        &self,
        workspace_id: &str,
        plan_id: &str,
        node_id: &str,
    ) -> CoreResult<bool> {
        Ok(self.supervisor_dispose_nodes.lock().unwrap().contains(&(
            workspace_id.to_string(),
            plan_id.to_string(),
            node_id.to_string(),
        )))
    }

    async fn create_plan_event(
        &self,
        event: WorkspacePlanEventRecord,
    ) -> CoreResult<WorkspacePlanEventRecord> {
        self.plan_events.lock().unwrap().push(event.clone());
        Ok(event)
    }

    async fn enqueue_plan_outbox(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxRecord> {
        self.outbox.lock().unwrap().push(item.clone());
        Ok(item)
    }
}
