use super::super::files;
use super::super::*;

pub(in crate::workspace_api) async fn list_files(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<BlackboardFileListQuery>,
) -> Result<Json<BlackboardFileListView>, WorkspaceApiError> {
    app.workspaces
        .list_files(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            query,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn create_directory(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<MkdirPayload>,
) -> Result<(StatusCode, Json<BlackboardFileView>), WorkspaceApiError> {
    app.workspaces
        .create_directory(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn upload_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    multipart: Multipart,
) -> Result<(StatusCode, Json<BlackboardFileView>), WorkspaceApiError> {
    let upload = files::parse_upload(multipart).await?;
    app.workspaces
        .upload_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            upload,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn download_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    headers: HeaderMap,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
) -> Result<Response, WorkspaceApiError> {
    let download = app
        .workspaces
        .download_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &file_id,
        )
        .await?;
    if let Some(if_none_match) = headers
        .get(IF_NONE_MATCH)
        .and_then(|value| value.to_str().ok())
    {
        let candidates = if_none_match.split(',').map(str::trim);
        if candidates
            .into_iter()
            .any(|candidate| candidate == download.etag)
        {
            return files::response_with_headers(StatusCode::NOT_MODIFIED, &download, Vec::new());
        }
    }
    let bytes = download.bytes.clone();
    files::response_with_headers(StatusCode::OK, &download, bytes)
}

pub(in crate::workspace_api) async fn patch_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    Json(body): Json<RenameOrMoveFilePayload>,
) -> Result<Json<BlackboardFileView>, WorkspaceApiError> {
    app.workspaces
        .patch_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &file_id,
            body,
        )
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn copy_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    Json(body): Json<CopyFilePayload>,
) -> Result<(StatusCode, Json<BlackboardFileView>), WorkspaceApiError> {
    app.workspaces
        .copy_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &file_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn delete_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    Query(query): Query<DeleteFileQuery>,
) -> Result<Json<DeletedView>, WorkspaceApiError> {
    app.workspaces
        .delete_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &file_id,
            query,
        )
        .await
        .map(Json)
}
