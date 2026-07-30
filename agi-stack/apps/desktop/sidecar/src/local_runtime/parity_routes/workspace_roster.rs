use axum::extract::OriginalUri;
use serde::Serialize;

use super::super::*;

const MAX_PAGE_SIZE: usize = 500;

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/members",
            get(list_workspace_members),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/agents",
            get(list_workspace_agents),
        )
}

async fn list_workspace_members(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    uri: OriginalUri,
) -> LocalJsonResult {
    let query = parse_roster_query(&uri, false)?;
    ensure_workspace_scope(
        &state,
        &authenticated,
        &tenant_id,
        &project_id,
        &workspace_id,
    )?;
    if query.offset > 0 {
        return Ok(Json(json!([])));
    }

    let member = WorkspaceMemberSummary {
        id: format!(
            "local-membership:{workspace_id}:{}",
            authenticated.user.user_id
        ),
        workspace_id,
        user_id: authenticated.user.user_id.clone(),
        role: workspace_member_role(&authenticated.membership_role),
        user_email: authenticated.user.email.clone(),
        invited_by: None,
        created_at: authenticated.user.created_at.clone(),
        updated_at: None,
    };
    serde_json::to_value([member])
        .map(Json)
        .map_err(workspace_roster_store_error)
}

async fn list_workspace_agents(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    uri: OriginalUri,
) -> LocalJsonResult {
    let _query = parse_roster_query(&uri, true)?;
    ensure_workspace_scope(
        &state,
        &authenticated,
        &tenant_id,
        &project_id,
        &workspace_id,
    )?;
    Ok(Json(json!([])))
}

fn parse_roster_query(
    uri: &OriginalUri,
    allow_active_only: bool,
) -> Result<RosterQuery, (StatusCode, Json<Value>)> {
    let mut offset = 0usize;
    let mut seen = std::collections::BTreeSet::new();
    for (key, value) in url::form_urlencoded::parse(uri.query().unwrap_or_default().as_bytes()) {
        if !seen.insert(key.to_string()) {
            return Err(workspace_roster_query_error());
        }
        match key.as_ref() {
            "limit" => {
                value
                    .parse::<usize>()
                    .ok()
                    .filter(|value| (1..=MAX_PAGE_SIZE).contains(value))
                    .ok_or_else(workspace_roster_query_error)?;
            }
            "offset" => {
                offset = value
                    .parse::<usize>()
                    .map_err(|_| workspace_roster_query_error())?;
            }
            "active_only" if allow_active_only => match value.as_ref() {
                "true" | "false" => {}
                _ => return Err(workspace_roster_query_error()),
            },
            _ => return Err(workspace_roster_query_error()),
        }
    }
    Ok(RosterQuery { offset })
}

fn workspace_member_role(membership_role: &str) -> &'static str {
    if membership_role == "owner" {
        "owner"
    } else {
        "viewer"
    }
}

fn workspace_roster_query_error() -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({
            "reason_code": "local_workspace_roster_query_invalid",
            "detail": "workspace roster query fields are invalid",
        })),
    )
}

fn workspace_roster_store_error(error: serde_json::Error) -> (StatusCode, Json<Value>) {
    tracing::error!(error = %error, "local workspace roster serialization failed");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({
            "reason_code": "local_workspace_roster_serialization_error",
            "detail": "local workspace roster is temporarily unavailable",
        })),
    )
}

#[derive(Clone, Copy)]
struct RosterQuery {
    offset: usize,
}

#[derive(Serialize)]
struct WorkspaceMemberSummary {
    id: String,
    workspace_id: String,
    user_id: String,
    role: &'static str,
    user_email: String,
    invited_by: Option<String>,
    created_at: String,
    updated_at: Option<String>,
}
