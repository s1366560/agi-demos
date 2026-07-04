use super::super::*;

pub(in crate::workspace_api) async fn create_post(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<BlackboardPostCreatePayload>,
) -> Result<(StatusCode, Json<BlackboardPostView>), WorkspaceApiError> {
    app.workspaces
        .create_post(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn list_posts(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<LimitOffset>,
) -> Result<Json<BlackboardPostListView>, WorkspaceApiError> {
    app.workspaces
        .list_posts(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            query,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn get_post(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
) -> Result<Json<BlackboardPostView>, WorkspaceApiError> {
    app.workspaces
        .get_post(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn update_post(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    Json(body): Json<BlackboardPostUpdatePayload>,
) -> Result<Json<BlackboardPostView>, WorkspaceApiError> {
    app.workspaces
        .update_post(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
            body,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn delete_post(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
) -> Result<Json<DeletedView>, WorkspaceApiError> {
    app.workspaces
        .delete_post(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn create_reply(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    Json(body): Json<BlackboardReplyCreatePayload>,
) -> Result<(StatusCode, Json<BlackboardReplyView>), WorkspaceApiError> {
    app.workspaces
        .create_reply(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn list_replies(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    Query(query): Query<LimitOffset>,
) -> Result<Json<BlackboardReplyListView>, WorkspaceApiError> {
    app.workspaces
        .list_replies(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
            query,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn update_reply(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id, reply_id)): Path<(
        String,
        String,
        String,
        String,
        String,
    )>,
    Json(body): Json<BlackboardReplyUpdatePayload>,
) -> Result<Json<BlackboardReplyView>, WorkspaceApiError> {
    app.workspaces
        .update_reply(WorkspaceReplyUpdateInput {
            user_id: &identity.user_id,
            tenant_id: &tenant_id,
            project_id: &project_id,
            workspace_id: &workspace_id,
            post_id: &post_id,
            reply_id: &reply_id,
            body,
        })
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn delete_reply(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id, reply_id)): Path<(
        String,
        String,
        String,
        String,
        String,
    )>,
) -> Result<Json<DeletedView>, WorkspaceApiError> {
    app.workspaces
        .delete_reply(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
            &reply_id,
        )
        .await
        .map(Json)
}
