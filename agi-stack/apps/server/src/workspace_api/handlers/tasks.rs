use super::super::*;

pub(in crate::workspace_api) async fn create_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<WorkspaceTaskCreatePayload>,
) -> Result<(StatusCode, Json<WorkspaceTaskView>), WorkspaceApiError> {
    app.workspaces
        .create_task(&identity.user_id, &workspace_id, body)
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn list_tasks(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Query(query): Query<TaskListQuery>,
) -> Result<Json<Vec<WorkspaceTaskView>>, WorkspaceApiError> {
    app.workspaces
        .list_tasks(&identity.user_id, &workspace_id, query)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn get_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    app.workspaces
        .get_task(&identity.user_id, &workspace_id, &task_id)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn update_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    Json(body): Json<WorkspaceTaskUpdatePayload>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    app.workspaces
        .update_task(&identity.user_id, &workspace_id, &task_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn delete_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<StatusCode, WorkspaceApiError> {
    app.workspaces
        .delete_task(&identity.user_id, &workspace_id, &task_id)
        .await
        .map(|()| StatusCode::NO_CONTENT)
}

async fn transition_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    action: TaskTransitionAction,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    app.workspaces
        .transition_task(&identity.user_id, &workspace_id, &task_id, action)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn claim_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::Claim,
    )
    .await
}

pub(in crate::workspace_api) async fn start_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::Start,
    )
    .await
}

pub(in crate::workspace_api) async fn block_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::Block,
    )
    .await
}

pub(in crate::workspace_api) async fn complete_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::Complete,
    )
    .await
}

pub(in crate::workspace_api) async fn unassign_agent(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::UnassignAgent,
    )
    .await
}
