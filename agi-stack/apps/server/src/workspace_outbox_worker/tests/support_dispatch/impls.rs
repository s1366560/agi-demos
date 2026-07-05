use super::*;

mod attempt;
mod conversation;
mod pipeline;
mod task_plan;

#[async_trait]
impl WorkspacePlanDispatchStore for FakeWorkspacePlanDispatchStore {
    async fn get_workspace(&self, workspace_id: &str) -> CoreResult<Option<WorkspaceRecord>> {
        task_plan::get_workspace(self, workspace_id).await
    }

    async fn get_task(
        &self,
        workspace_id: &str,
        task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskRecord>> {
        task_plan::get_task(self, workspace_id, task_id).await
    }

    async fn list_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        task_plan::list_tasks_by_root_goal_task_id(self, workspace_id, root_goal_task_id).await
    }

    async fn list_current_plan_child_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        task_plan::list_current_plan_child_tasks_by_root_goal_task_id(
            self,
            workspace_id,
            root_goal_task_id,
        )
        .await
    }

    async fn save_task(&self, task: WorkspaceTaskRecord) -> CoreResult<WorkspaceTaskRecord> {
        task_plan::save_task(self, task).await
    }

    async fn get_plan(&self, plan_id: &str) -> CoreResult<Option<WorkspacePlanRecord>> {
        task_plan::get_plan(self, plan_id).await
    }

    async fn list_plan_nodes(&self, plan_id: &str) -> CoreResult<Vec<WorkspacePlanNodeRecord>> {
        task_plan::list_plan_nodes(self, plan_id).await
    }

    async fn create_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord> {
        task_plan::create_plan_node(self, node).await
    }

    async fn save_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord> {
        task_plan::save_plan_node(self, node).await
    }

    async fn find_active_task_session_attempt(
        &self,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        attempt::find_active_task_session_attempt(self, workspace_task_id).await
    }

    async fn find_latest_accepted_task_session_attempt(
        &self,
        workspace_id: &str,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        attempt::find_latest_accepted_task_session_attempt(self, workspace_id, workspace_task_id)
            .await
    }

    async fn get_task_session_attempt(
        &self,
        attempt_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        attempt::get_task_session_attempt(self, attempt_id).await
    }

    async fn latest_pipeline_run_for_node(
        &self,
        plan_id: &str,
        node_id: &str,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        pipeline::latest_pipeline_run_for_node(self, plan_id, node_id, attempt_id).await
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
        pipeline::ensure_pipeline_contract(
            self,
            contract_id,
            workspace_id,
            plan_id,
            provider,
            code_root,
            commands_json,
            env_json,
            trigger_policy_json,
            timeout_seconds,
            auto_deploy,
            preview_port,
            health_url,
            metadata_json,
            now,
        )
        .await
    }

    async fn create_pipeline_run(
        &self,
        run: WorkspacePipelineRunRecord,
    ) -> CoreResult<WorkspacePipelineRunRecord> {
        pipeline::create_pipeline_run(self, run).await
    }

    async fn finish_pipeline_run(
        &self,
        run_id: &str,
        status: &str,
        reason: Option<&str>,
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        pipeline::finish_pipeline_run(self, run_id, status, reason, metadata_patch, completed_at)
            .await
    }

    async fn create_pipeline_stage_run(
        &self,
        stage_run: WorkspacePipelineStageRunRecord,
    ) -> CoreResult<WorkspacePipelineStageRunRecord> {
        pipeline::create_pipeline_stage_run(self, stage_run).await
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
        pipeline::finish_pipeline_stage_run(
            self,
            stage_run_id,
            status,
            exit_code,
            stdout_preview,
            stderr_preview,
            log_ref,
            artifact_refs,
            metadata_patch,
            completed_at,
        )
        .await
    }

    async fn latest_task_session_attempt_number(&self, workspace_task_id: &str) -> CoreResult<i32> {
        attempt::latest_task_session_attempt_number(self, workspace_task_id).await
    }

    async fn create_task_session_attempt(
        &self,
        attempt: WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<WorkspaceTaskSessionAttemptRecord> {
        attempt::create_task_session_attempt(self, attempt).await
    }

    async fn mark_task_session_attempt_running(
        &self,
        attempt_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        attempt::mark_task_session_attempt_running(self, attempt_id, now).await
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
        conversation::ensure_worker_launch_conversation(
            self,
            conversation_id,
            project_id,
            tenant_id,
            user_id,
            title,
            agent_config_json,
            metadata_json,
            participant_agents_json,
            focused_agent_id,
            workspace_id,
            linked_workspace_task_id,
            now,
        )
        .await
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
        conversation::ensure_workspace_agent_conversation(
            self,
            conversation_id,
            project_id,
            tenant_id,
            user_id,
            title,
            agent_config_json,
            metadata_json,
            workspace_id,
            linked_workspace_task_id,
            now,
        )
        .await
    }

    async fn list_workspace_member_user_ids(&self, workspace_id: &str) -> CoreResult<Vec<String>> {
        conversation::list_workspace_member_user_ids(self, workspace_id).await
    }

    async fn list_active_workspace_agents(
        &self,
        workspace_id: &str,
    ) -> CoreResult<Vec<WorkspaceAgentRecord>> {
        conversation::list_active_workspace_agents(self, workspace_id).await
    }

    async fn create_workspace_message(
        &self,
        message: WorkspaceMessageRecord,
    ) -> CoreResult<WorkspaceMessageRecord> {
        conversation::create_workspace_message(self, message).await
    }

    async fn enqueue_blackboard_outbox(&self, outbox: BlackboardOutboxRecord) -> CoreResult<()> {
        conversation::enqueue_blackboard_outbox(self, outbox).await
    }

    async fn bind_task_session_attempt_conversation(
        &self,
        attempt_id: &str,
        conversation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        attempt::bind_task_session_attempt_conversation(self, attempt_id, conversation_id, now)
            .await
    }

    async fn finish_task_session_attempt(
        &self,
        attempt_id: &str,
        status: &str,
        leader_feedback: Option<&str>,
        adjudication_reason: Option<&str>,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        attempt::finish_task_session_attempt(
            self,
            attempt_id,
            status,
            leader_feedback,
            adjudication_reason,
            completed_at,
        )
        .await
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
        attempt::record_task_session_attempt_candidate_output(
            self,
            attempt_id,
            summary,
            artifacts_json,
            verifications_json,
            conversation_id,
            updated_at,
        )
        .await
    }

    async fn count_recent_running_task_session_attempts_with_conversation(
        &self,
        _workspace_id: &str,
        _active_after: DateTime<Utc>,
    ) -> CoreResult<i64> {
        attempt::count_recent_running_task_session_attempts_with_conversation(self).await
    }

    async fn has_supervisor_dispose_decision_for_node(
        &self,
        workspace_id: &str,
        plan_id: &str,
        node_id: &str,
    ) -> CoreResult<bool> {
        attempt::has_supervisor_dispose_decision_for_node(self, workspace_id, plan_id, node_id)
            .await
    }

    async fn create_plan_event(
        &self,
        event: WorkspacePlanEventRecord,
    ) -> CoreResult<WorkspacePlanEventRecord> {
        conversation::create_plan_event(self, event).await
    }

    async fn enqueue_plan_outbox(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxRecord> {
        conversation::enqueue_plan_outbox(self, item).await
    }
}
