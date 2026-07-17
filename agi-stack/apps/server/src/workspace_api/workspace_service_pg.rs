use super::*;

#[async_trait]
impl WorkspaceService for PgWorkspaceService {
    async fn create_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: WorkspaceCreatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.pg_create_workspace(user_id, tenant_id, project_id, body)
            .await
    }

    async fn list_workspaces(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        query: WorkspaceListQuery,
    ) -> Result<Vec<WorkspaceView>, WorkspaceApiError> {
        self.pg_list_workspaces(user_id, tenant_id, project_id, query)
            .await
    }

    async fn list_project_my_work(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<ProjectMyWorkResponse, WorkspaceApiError> {
        self.pg_list_project_my_work(user_id, project_id).await
    }

    async fn get_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.pg_get_workspace(user_id, tenant_id, project_id, workspace_id)
            .await
    }

    async fn list_workspace_members(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<WorkspaceMemberView>, WorkspaceApiError> {
        self.pg_list_workspace_members(user_id, tenant_id, project_id, workspace_id, query)
            .await
    }

    async fn list_workspace_agents(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: WorkspaceAgentListQuery,
    ) -> Result<Vec<WorkspaceAgentView>, WorkspaceApiError> {
        self.pg_list_workspace_agents(user_id, tenant_id, project_id, workspace_id, query)
            .await
    }

    async fn authorize_workspace_event_subscription(
        &self,
        user_id: &str,
        workspace_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<String, WorkspaceApiError> {
        self.pg_authorize_workspace_event_subscription(user_id, workspace_id, project_id, tenant_id)
            .await
    }

    async fn send_message(
        &self,
        user_id: &str,
        sender_name: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: SendMessagePayload,
    ) -> Result<MessageView, WorkspaceApiError> {
        self.pg_send_message(
            user_id,
            sender_name,
            tenant_id,
            project_id,
            workspace_id,
            body,
        )
        .await
    }

    async fn list_messages(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: MessageListQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.pg_list_messages(user_id, tenant_id, project_id, workspace_id, query)
            .await
    }

    async fn list_mentions(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        target_id: &str,
        query: MessageMentionQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.pg_list_mentions(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            target_id,
            query,
        )
        .await
    }

    async fn get_plan_snapshot(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshotView, WorkspaceApiError> {
        self.pg_get_plan_snapshot(user_id, workspace_id, query)
            .await
    }
    async fn retry_plan_outbox(
        &self,
        user_id: &str,
        workspace_id: &str,
        outbox_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        self.pg_retry_plan_outbox(user_id, workspace_id, outbox_id, body)
            .await
    }
    async fn recover_stale_attempts(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        self.pg_recover_stale_attempts(user_id, workspace_id, body)
            .await
    }
    async fn request_delivery_pipeline_run(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanPipelineRunRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        self.pg_request_delivery_pipeline_run(user_id, workspace_id, body)
            .await
    }
    async fn request_delivery_contract_regeneration(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        self.pg_request_delivery_contract_regeneration(user_id, workspace_id, body)
            .await
    }
    async fn request_plan_node_replan(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        self.pg_request_plan_node_replan(user_id, workspace_id, node_id, body)
            .await
    }
    async fn reopen_plan_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        self.pg_reopen_plan_node(user_id, workspace_id, node_id, body)
            .await
    }
    async fn accept_plan_node_review(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        self.pg_accept_plan_node_review(user_id, workspace_id, node_id, body)
            .await
    }
    async fn trigger_autonomy_tick(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: AutonomyTickRequest,
    ) -> Result<AutonomyTickView, WorkspaceApiError> {
        self.pg_trigger_autonomy_tick(user_id, workspace_id, body)
            .await
    }
    async fn update_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: WorkspaceUpdatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.pg_update_workspace(user_id, tenant_id, project_id, workspace_id, body)
            .await
    }

    async fn delete_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.pg_delete_workspace(user_id, tenant_id, project_id, workspace_id)
            .await
    }

    async fn create_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspaceTaskCreatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.pg_create_task(user_id, workspace_id, body).await
    }

    async fn list_tasks(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: TaskListQuery,
    ) -> Result<Vec<WorkspaceTaskView>, WorkspaceApiError> {
        self.pg_list_tasks(user_id, workspace_id, query).await
    }

    async fn get_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.pg_get_task(user_id, workspace_id, task_id).await
    }

    async fn update_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        body: WorkspaceTaskUpdatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.pg_update_task(user_id, workspace_id, task_id, body)
            .await
    }

    async fn delete_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.pg_delete_task(user_id, workspace_id, task_id).await
    }

    async fn transition_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        action: TaskTransitionAction,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.pg_transition_task(user_id, workspace_id, task_id, action)
            .await
    }

    async fn create_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyNodeCreatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.pg_create_node(user_id, workspace_id, body).await
    }

    async fn list_nodes(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyNodeView>, WorkspaceApiError> {
        self.pg_list_nodes(user_id, workspace_id, query).await
    }

    async fn get_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.pg_get_node(user_id, workspace_id, node_id).await
    }

    async fn update_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: TopologyNodeUpdatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.pg_update_node(user_id, workspace_id, node_id, body)
            .await
    }

    async fn delete_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.pg_delete_node(user_id, workspace_id, node_id).await
    }

    async fn create_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyEdgeCreatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.pg_create_edge(user_id, workspace_id, body).await
    }

    async fn list_edges(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyEdgeView>, WorkspaceApiError> {
        self.pg_list_edges(user_id, workspace_id, query).await
    }

    async fn get_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.pg_get_edge(user_id, workspace_id, edge_id).await
    }

    async fn update_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
        body: TopologyEdgeUpdatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.pg_update_edge(user_id, workspace_id, edge_id, body)
            .await
    }

    async fn delete_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.pg_delete_edge(user_id, workspace_id, edge_id).await
    }

    async fn create_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: BlackboardPostCreatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.pg_create_post(user_id, tenant_id, project_id, workspace_id, body)
            .await
    }

    async fn list_posts(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardPostListView, WorkspaceApiError> {
        self.pg_list_posts(user_id, tenant_id, project_id, workspace_id, query)
            .await
    }

    async fn get_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.pg_get_post(user_id, tenant_id, project_id, workspace_id, post_id)
            .await
    }

    async fn update_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardPostUpdatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.pg_update_post(user_id, tenant_id, project_id, workspace_id, post_id, body)
            .await
    }

    async fn delete_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.pg_delete_post(user_id, tenant_id, project_id, workspace_id, post_id)
            .await
    }

    async fn create_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardReplyCreatePayload,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        self.pg_create_reply(user_id, tenant_id, project_id, workspace_id, post_id, body)
            .await
    }

    async fn list_replies(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardReplyListView, WorkspaceApiError> {
        self.pg_list_replies(user_id, tenant_id, project_id, workspace_id, post_id, query)
            .await
    }

    async fn update_reply(
        &self,
        input: WorkspaceReplyUpdateInput<'_>,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        self.pg_update_reply(input).await
    }

    async fn delete_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.pg_delete_reply(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            post_id,
            reply_id,
        )
        .await
    }

    async fn list_files(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: BlackboardFileListQuery,
    ) -> Result<BlackboardFileListView, WorkspaceApiError> {
        self.pg_list_files(user_id, tenant_id, project_id, workspace_id, query)
            .await
    }

    async fn create_directory(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: MkdirPayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.pg_create_directory(user_id, tenant_id, project_id, workspace_id, body)
            .await
    }

    async fn upload_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        upload: BlackboardUpload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.pg_upload_file(user_id, tenant_id, project_id, workspace_id, upload)
            .await
    }

    async fn download_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
    ) -> Result<BlackboardFileDownload, WorkspaceApiError> {
        self.pg_download_file(user_id, tenant_id, project_id, workspace_id, file_id)
            .await
    }

    async fn patch_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: RenameOrMoveFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.pg_patch_file(user_id, tenant_id, project_id, workspace_id, file_id, body)
            .await
    }

    async fn copy_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: CopyFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.pg_copy_file(user_id, tenant_id, project_id, workspace_id, file_id, body)
            .await
    }

    async fn delete_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        query: DeleteFileQuery,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.pg_delete_file(user_id, tenant_id, project_id, workspace_id, file_id, query)
            .await
    }
}
