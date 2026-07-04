use super::super::*;

pub(in crate::workspace_api) async fn create_workspace(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Json(body): Json<WorkspaceCreatePayload>,
) -> Result<(StatusCode, Json<WorkspaceView>), WorkspaceApiError> {
    app.workspaces
        .create_workspace(&identity.user_id, &tenant_id, &project_id, body)
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn list_workspaces(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Query(query): Query<WorkspaceListQuery>,
) -> Result<Json<Vec<WorkspaceView>>, WorkspaceApiError> {
    app.workspaces
        .list_workspaces(&identity.user_id, &tenant_id, &project_id, query)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn get_workspace(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
) -> Result<Json<WorkspaceView>, WorkspaceApiError> {
    app.workspaces
        .get_workspace(&identity.user_id, &tenant_id, &project_id, &workspace_id)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn send_message(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<SendMessagePayload>,
) -> Result<(StatusCode, Json<MessageView>), WorkspaceApiError> {
    app.workspaces
        .send_message(
            &identity.user_id,
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn list_messages(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<MessageListQuery>,
) -> Result<Json<MessageListView>, WorkspaceApiError> {
    app.workspaces
        .list_messages(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            query,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn list_mentions(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, target_id)): Path<(String, String, String, String)>,
    Query(query): Query<MessageMentionQuery>,
) -> Result<Json<MessageListView>, WorkspaceApiError> {
    app.workspaces
        .list_mentions(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &target_id,
            query,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn get_plan_snapshot(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Query(query): Query<WorkspacePlanSnapshotQuery>,
) -> Result<Json<WorkspacePlanSnapshotView>, WorkspaceApiError> {
    app.workspaces
        .get_plan_snapshot(&identity.user_id, &workspace_id, query)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn retry_plan_outbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, outbox_id)): Path<(String, String)>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .retry_plan_outbox(&identity.user_id, &workspace_id, &outbox_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn recover_stale_attempts(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .recover_stale_attempts(&identity.user_id, &workspace_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn request_delivery_pipeline_run(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<WorkspacePlanPipelineRunRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .request_delivery_pipeline_run(&identity.user_id, &workspace_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn request_delivery_contract_regeneration(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .request_delivery_contract_regeneration(&identity.user_id, &workspace_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn request_plan_node_replan(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .request_plan_node_replan(&identity.user_id, &workspace_id, &node_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn reopen_plan_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .reopen_plan_node(&identity.user_id, &workspace_id, &node_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn accept_plan_node_review(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .accept_plan_node_review(&identity.user_id, &workspace_id, &node_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn update_workspace(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<WorkspaceUpdatePayload>,
) -> Result<Json<WorkspaceView>, WorkspaceApiError> {
    app.workspaces
        .update_workspace(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            body,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn delete_workspace(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
) -> Result<StatusCode, WorkspaceApiError> {
    app.workspaces
        .delete_workspace(&identity.user_id, &tenant_id, &project_id, &workspace_id)
        .await
        .map(|()| StatusCode::NO_CONTENT)
}
