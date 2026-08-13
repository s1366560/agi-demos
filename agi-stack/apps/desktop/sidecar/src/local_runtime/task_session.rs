use std::sync::Arc;

use axum::{extract::Extension, extract::Path, extract::State, Json};
use serde_json::Value;

use super::{
    active_workspace_scope_error, auth_context::AuthenticatedContext, workspace_core_bridge,
    LocalJsonResult, LocalRuntimeState,
};

pub(super) async fn create_task_session(
    State(_state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Json(_body): Json<Value>,
) -> LocalJsonResult {
    if tenant_id != authenticated.workspace.tenant_id
        || project_id != authenticated.workspace.project_id
    {
        return Err(active_workspace_scope_error());
    }
    Err(workspace_core_bridge::unavailable(
        "Workspace Core authority is unavailable",
    ))
}
