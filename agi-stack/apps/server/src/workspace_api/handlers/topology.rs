use super::super::*;

pub(in crate::workspace_api) async fn create_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<TopologyNodeCreatePayload>,
) -> Result<(StatusCode, Json<TopologyNodeView>), WorkspaceApiError> {
    app.workspaces
        .create_node(&identity.user_id, &workspace_id, body)
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn list_nodes(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Query(query): Query<LimitOffset>,
) -> Result<Json<Vec<TopologyNodeView>>, WorkspaceApiError> {
    app.workspaces
        .list_nodes(&identity.user_id, &workspace_id, query)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn get_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
) -> Result<Json<TopologyNodeView>, WorkspaceApiError> {
    app.workspaces
        .get_node(&identity.user_id, &workspace_id, &node_id)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn update_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    Json(body): Json<TopologyNodeUpdatePayload>,
) -> Result<Json<TopologyNodeView>, WorkspaceApiError> {
    app.workspaces
        .update_node(&identity.user_id, &workspace_id, &node_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn delete_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
) -> Result<StatusCode, WorkspaceApiError> {
    app.workspaces
        .delete_node(&identity.user_id, &workspace_id, &node_id)
        .await
        .map(|()| StatusCode::NO_CONTENT)
}

pub(in crate::workspace_api) async fn create_edge(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<TopologyEdgeCreatePayload>,
) -> Result<(StatusCode, Json<TopologyEdgeView>), WorkspaceApiError> {
    app.workspaces
        .create_edge(&identity.user_id, &workspace_id, body)
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

pub(in crate::workspace_api) async fn list_edges(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Query(query): Query<LimitOffset>,
) -> Result<Json<Vec<TopologyEdgeView>>, WorkspaceApiError> {
    app.workspaces
        .list_edges(&identity.user_id, &workspace_id, query)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn get_edge(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, edge_id)): Path<(String, String)>,
) -> Result<Json<TopologyEdgeView>, WorkspaceApiError> {
    app.workspaces
        .get_edge(&identity.user_id, &workspace_id, &edge_id)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn update_edge(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, edge_id)): Path<(String, String)>,
    Json(body): Json<TopologyEdgeUpdatePayload>,
) -> Result<Json<TopologyEdgeView>, WorkspaceApiError> {
    app.workspaces
        .update_edge(&identity.user_id, &workspace_id, &edge_id, body)
        .await
        .map(Json)
}

pub(in crate::workspace_api) async fn delete_edge(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, edge_id)): Path<(String, String)>,
) -> Result<StatusCode, WorkspaceApiError> {
    app.workspaces
        .delete_edge(&identity.user_id, &workspace_id, &edge_id)
        .await
        .map(|()| StatusCode::NO_CONTENT)
}
