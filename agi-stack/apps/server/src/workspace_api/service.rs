use std::sync::Arc;

use async_trait::async_trait;

use super::*;

pub(crate) type SharedWorkspaces = Arc<dyn WorkspaceService>;

#[async_trait]
pub(crate) trait WorkspaceService: Send + Sync {
    async fn create_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: WorkspaceCreatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError>;

    async fn list_workspaces(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        query: WorkspaceListQuery,
    ) -> Result<Vec<WorkspaceView>, WorkspaceApiError>;

    async fn get_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<WorkspaceView, WorkspaceApiError>;

    async fn send_message(
        &self,
        user_id: &str,
        sender_name: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: SendMessagePayload,
    ) -> Result<MessageView, WorkspaceApiError>;

    async fn list_messages(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: MessageListQuery,
    ) -> Result<MessageListView, WorkspaceApiError>;

    async fn list_mentions(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        target_id: &str,
        query: MessageMentionQuery,
    ) -> Result<MessageListView, WorkspaceApiError>;

    async fn get_plan_snapshot(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshotView, WorkspaceApiError>;

    async fn retry_plan_outbox(
        &self,
        user_id: &str,
        workspace_id: &str,
        outbox_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn recover_stale_attempts(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn request_delivery_pipeline_run(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanPipelineRunRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn request_delivery_contract_regeneration(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn request_plan_node_replan(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn reopen_plan_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn accept_plan_node_review(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn update_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: WorkspaceUpdatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError>;

    async fn delete_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<(), WorkspaceApiError>;

    async fn create_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspaceTaskCreatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError>;

    async fn list_tasks(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: TaskListQuery,
    ) -> Result<Vec<WorkspaceTaskView>, WorkspaceApiError>;

    async fn get_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError>;

    async fn update_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        body: WorkspaceTaskUpdatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError>;

    async fn delete_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<(), WorkspaceApiError>;

    async fn transition_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        action: TaskTransitionAction,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError>;

    async fn create_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyNodeCreatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError>;

    async fn list_nodes(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyNodeView>, WorkspaceApiError>;

    async fn get_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<TopologyNodeView, WorkspaceApiError>;

    async fn update_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: TopologyNodeUpdatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError>;

    async fn delete_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<(), WorkspaceApiError>;

    async fn create_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyEdgeCreatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError>;

    async fn list_edges(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyEdgeView>, WorkspaceApiError>;

    async fn get_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<TopologyEdgeView, WorkspaceApiError>;

    async fn update_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
        body: TopologyEdgeUpdatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError>;

    async fn delete_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<(), WorkspaceApiError>;

    async fn create_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: BlackboardPostCreatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError>;

    async fn list_posts(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardPostListView, WorkspaceApiError>;

    async fn get_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<BlackboardPostView, WorkspaceApiError>;

    async fn update_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardPostUpdatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError>;

    async fn delete_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError>;

    async fn create_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardReplyCreatePayload,
    ) -> Result<BlackboardReplyView, WorkspaceApiError>;

    async fn list_replies(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardReplyListView, WorkspaceApiError>;

    async fn update_reply(
        &self,
        input: WorkspaceReplyUpdateInput<'_>,
    ) -> Result<BlackboardReplyView, WorkspaceApiError>;

    async fn delete_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError>;

    async fn list_files(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: BlackboardFileListQuery,
    ) -> Result<BlackboardFileListView, WorkspaceApiError>;

    async fn create_directory(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: MkdirPayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError>;

    async fn upload_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        upload: BlackboardUpload,
    ) -> Result<BlackboardFileView, WorkspaceApiError>;

    async fn download_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
    ) -> Result<BlackboardFileDownload, WorkspaceApiError>;

    async fn patch_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: RenameOrMoveFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError>;

    async fn copy_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: CopyFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError>;

    async fn delete_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        query: DeleteFileQuery,
    ) -> Result<DeletedView, WorkspaceApiError>;
}
