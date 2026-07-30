use axum::extract::OriginalUri;
use rusqlite::{params, Connection};
use serde::Serialize;

use super::super::*;
use crate::local_runtime::auth_context::DesktopProject;
use crate::local_runtime::search_projection;

const PROJECT_OVERVIEW_CAPABILITY: &str = "project_overview";
const PROJECT_OVERVIEW_SERVICE_VERSION: &str = env!("CARGO_PKG_VERSION");
const PROJECT_OVERVIEW_CONTRACT_VERSION: &str = "3.0.0";
const PROJECT_OVERVIEW_DEGRADED_REASON: &str = "local_project_overview_timeline_projection_only";
const PROJECT_GRAPH_UNAVAILABLE_REASON: &str = "local_project_graph_projection_unavailable";
const PROJECT_STORAGE_NOT_APPLICABLE_REASON: &str = "local_project_storage_quota_not_applicable";
const PROJECT_COLLABORATION_NOT_APPLICABLE_REASON: &str =
    "local_project_collaboration_governance_not_applicable";
const PROJECT_OVERVIEW_RECENT_LIMIT: usize = 5;
const TIMELINE_SOURCE: &str = "desktop_timeline";

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new().route(
        "/api/v1/projects/:project_id/overview",
        get(project_overview),
    )
}

async fn project_overview(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    uri: OriginalUri,
) -> LocalJsonResult {
    reject_query_fields(&uri)?;
    ensure_project_scope(&authenticated, Some(&project_id))?;

    let projects = state
        .session_store
        .list_user_projects(
            &authenticated.user.user_id,
            &authenticated.workspace.tenant_id,
        )
        .map_err(|error| project_overview_store_error(error.to_string()))?;
    let Some(project) = projects
        .into_iter()
        .find(|project| project.id == project_id)
    else {
        return Err((
            StatusCode::NOT_FOUND,
            Json(json!({
                "reason_code": "local_project_overview_not_found",
                "detail": "project is unavailable in the active local scope",
            })),
        ));
    };

    let conversation_count = state
        .session_store
        .list_conversations(&project_id, None)
        .map_err(project_overview_store_error)?
        .len();

    let mut connection = state
        .session_store
        .connection()
        .map_err(project_overview_store_error)?;
    let projection = search_projection::refresh_projection(
        &mut connection,
        &authenticated.workspace.tenant_id,
        &project_id,
    )
    .map_err(project_overview_store_error)?;
    let (projected_item_count, recent_items) =
        recent_knowledge_items(&connection, &authenticated.workspace.tenant_id, &project_id)
            .map_err(project_overview_store_error)?;

    let response = ProjectOverviewResponse {
        capability: PROJECT_OVERVIEW_CAPABILITY,
        availability: "degraded",
        reason_code: PROJECT_OVERVIEW_DEGRADED_REASON,
        service_version: PROJECT_OVERVIEW_SERVICE_VERSION,
        contract_version: PROJECT_OVERVIEW_CONTRACT_VERSION,
        allowed_actions: ["view"],
        scope: ProjectOverviewScope {
            tenant_id: authenticated.workspace.tenant_id.clone(),
            project_id,
            workspace_id: None,
            instance_id: None,
        },
        authority_revision: projection.revision,
        backfill_cursor: projection.backfill_cursor,
        project: AvailableField::new(ProjectSummary::from(project)),
        conversation_count: AvailableField::new(conversation_count),
        recent_knowledge_items: RecentKnowledgeField {
            availability: "degraded",
            reason_code: PROJECT_OVERVIEW_DEGRADED_REASON,
            source: TIMELINE_SOURCE,
            total: projected_item_count,
            value: recent_items,
        },
        active_nodes: NullField::new("unavailable", PROJECT_GRAPH_UNAVAILABLE_REASON),
        storage_quota: NullField::new("not_applicable", PROJECT_STORAGE_NOT_APPLICABLE_REASON),
        collaborators: NullField::new(
            "not_applicable",
            PROJECT_COLLABORATION_NOT_APPLICABLE_REASON,
        ),
    };
    serde_json::to_value(response)
        .map(Json)
        .map_err(|error| project_overview_store_error(error.to_string()))
}

fn reject_query_fields(uri: &OriginalUri) -> Result<(), (StatusCode, Json<Value>)> {
    if uri.query().is_some_and(|query| !query.is_empty()) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({
                "reason_code": "local_project_overview_query_invalid",
                "detail": "project overview does not accept query fields",
            })),
        ));
    }
    Ok(())
}

fn project_overview_store_error(error: String) -> (StatusCode, Json<Value>) {
    tracing::error!(error = %error, "local project overview storage operation failed");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({
            "reason_code": "local_project_overview_store_error",
            "detail": "local project overview is temporarily unavailable",
        })),
    )
}

fn recent_knowledge_items(
    connection: &Connection,
    tenant_id: &str,
    project_id: &str,
) -> Result<(usize, Vec<RecentKnowledgeItem>), String> {
    let total = connection
        .query_row(
            "SELECT COUNT(*)
             FROM desktop_search_documents
             WHERE tenant_id = ?1 AND project_id = ?2 AND source = ?3",
            params![tenant_id, project_id, TIMELINE_SOURCE],
            |row| row.get::<_, i64>(0),
        )
        .map_err(|error| error.to_string())?;
    let total = usize::try_from(total).map_err(|error| error.to_string())?;

    let mut statement = connection
        .prepare(
            "SELECT source_id, conversation_id, title, content, result_type, source,
                    created_at, tags_json
             FROM desktop_search_documents
             WHERE tenant_id = ?1 AND project_id = ?2 AND source = ?3
             ORDER BY source_rowid DESC
             LIMIT ?4",
        )
        .map_err(|error| error.to_string())?;
    let rows = statement
        .query_map(
            params![
                tenant_id,
                project_id,
                TIMELINE_SOURCE,
                PROJECT_OVERVIEW_RECENT_LIMIT as i64
            ],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, Option<String>>(6)?,
                    row.get::<_, String>(7)?,
                ))
            },
        )
        .map_err(|error| error.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| error.to_string())?;
    let items = rows
        .into_iter()
        .map(
            |(id, conversation_id, title, content, result_type, source, created_at, tags_json)| {
                let tags = serde_json::from_str::<Vec<String>>(&tags_json)
                    .map_err(|error| error.to_string())?;
                Ok(RecentKnowledgeItem {
                    id,
                    conversation_id,
                    title,
                    content,
                    result_type,
                    source,
                    created_at,
                    tags,
                })
            },
        )
        .collect::<Result<Vec<_>, String>>()?;
    Ok((total, items))
}

#[derive(Serialize)]
struct ProjectOverviewResponse {
    capability: &'static str,
    availability: &'static str,
    reason_code: &'static str,
    service_version: &'static str,
    contract_version: &'static str,
    allowed_actions: [&'static str; 1],
    scope: ProjectOverviewScope,
    authority_revision: i64,
    backfill_cursor: Option<String>,
    project: AvailableField<ProjectSummary>,
    conversation_count: AvailableField<usize>,
    recent_knowledge_items: RecentKnowledgeField,
    active_nodes: NullField,
    storage_quota: NullField,
    collaborators: NullField,
}

#[derive(Serialize)]
struct ProjectOverviewScope {
    tenant_id: String,
    project_id: String,
    workspace_id: Option<String>,
    instance_id: Option<String>,
}

#[derive(Serialize)]
struct AvailableField<T> {
    availability: &'static str,
    reason_code: Option<&'static str>,
    value: T,
}

impl<T> AvailableField<T> {
    fn new(value: T) -> Self {
        Self {
            availability: "available",
            reason_code: None,
            value,
        }
    }
}

#[derive(Serialize)]
struct NullField {
    availability: &'static str,
    reason_code: &'static str,
    value: Option<()>,
}

impl NullField {
    fn new(availability: &'static str, reason_code: &'static str) -> Self {
        Self {
            availability,
            reason_code,
            value: None,
        }
    }
}

#[derive(Serialize)]
struct ProjectSummary {
    id: String,
    tenant_id: String,
    name: String,
    description: Option<String>,
    agent_conversation_mode: String,
    created_at: String,
}

impl From<DesktopProject> for ProjectSummary {
    fn from(project: DesktopProject) -> Self {
        Self {
            id: project.id,
            tenant_id: project.tenant_id,
            name: project.name,
            description: project.description,
            agent_conversation_mode: project.agent_conversation_mode,
            created_at: project.created_at,
        }
    }
}

#[derive(Serialize)]
struct RecentKnowledgeField {
    availability: &'static str,
    reason_code: &'static str,
    source: &'static str,
    total: usize,
    value: Vec<RecentKnowledgeItem>,
}

#[derive(Serialize)]
struct RecentKnowledgeItem {
    id: String,
    conversation_id: String,
    title: String,
    content: String,
    result_type: String,
    source: String,
    created_at: Option<String>,
    tags: Vec<String>,
}
