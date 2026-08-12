use axum::extract::OriginalUri;
use chrono::{DateTime, Duration, Utc};
use serde::Serialize;

use super::super::*;
use crate::local_runtime::auth_context::DesktopProject;

const CAPABILITY: &str = "tenant_overview";
const SERVICE_VERSION: &str = env!("CARGO_PKG_VERSION");
const CONTRACT_VERSION: &str = "3.0.0";
const DEGRADED_REASON: &str = "local_tenant_overview_memory_projection_unavailable";
const MEMORY_REASON: &str = "local_tenant_memory_projection_unavailable";
pub(super) const PROJECT_OWNER_REASON: &str = "local_project_owner_projection_unavailable";
pub(super) const PROJECT_MEMORY_REASON: &str = "local_project_memory_projection_unavailable";
const PROJECTS_REASON: &str = "local_tenant_project_owner_projection_unavailable";

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new().route("/api/v1/tenants/:tenant_id/stats", get(tenant_overview))
}

async fn tenant_overview(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(tenant_id): Path<String>,
    uri: OriginalUri,
) -> LocalJsonResult {
    reject_query_fields(&uri)?;
    ensure_tenant_scope(&authenticated, Some(&tenant_id))?;
    let tenants = state
        .session_store
        .list_user_tenants(&authenticated.user.user_id)
        .map_err(|error| tenant_overview_store_error(error.to_string()))?;
    let Some(tenant) = tenants.into_iter().find(|tenant| tenant.id == tenant_id) else {
        return Err((
            StatusCode::NOT_FOUND,
            Json(json!({
                "reason_code": "local_tenant_overview_not_found",
                "detail": "tenant is unavailable in the active local scope",
            })),
        ));
    };
    let projects = state
        .session_store
        .list_user_projects(&authenticated.user.user_id, &tenant_id)
        .map_err(|error| tenant_overview_store_error(error.to_string()))?;
    let active = projects.len();
    let new_this_week = projects.iter().filter(is_new_this_week).count();
    let project_list = projects.into_iter().map(ProjectProjection::from).collect();
    let response = TenantOverviewResponse {
        capability: CAPABILITY,
        availability: "degraded",
        reason_code: DEGRADED_REASON,
        service_version: SERVICE_VERSION,
        contract_version: CONTRACT_VERSION,
        allowed_actions: ["view"],
        scope: TenantOverviewScope {
            tenant_id: tenant_id.clone(),
            project_id: None,
            workspace_id: None,
            instance_id: None,
        },
        authority_revision: authenticated.workspace.revision,
        tenant_info: TenantInfo {
            organization_id: format!("#TEN-{}", tenant_id.to_uppercase()),
            plan: tenant.plan,
            region: NullField::new("not_applicable", "local_tenant_region_not_applicable"),
            next_billing_date: NullField::new(
                "not_applicable",
                "local_billing_authority_not_applicable",
            ),
        },
        storage: NullField::new("unavailable", MEMORY_REASON),
        projects: ProjectsProjection {
            availability: "degraded",
            reason_code: PROJECTS_REASON,
            active,
            new_this_week,
            list: project_list,
        },
        members: MembersProjection {
            total: 1,
            new_added: 0,
        },
        memory_history: EmptyListField {
            availability: "unavailable",
            reason_code: MEMORY_REASON,
            value: [],
        },
    };
    serde_json::to_value(response)
        .map(Json)
        .map_err(|error| tenant_overview_store_error(error.to_string()))
}

pub(super) fn is_new_this_week(project: &&DesktopProject) -> bool {
    DateTime::parse_from_rfc3339(&project.created_at)
        .map(|created| created.with_timezone(&Utc) >= Utc::now() - Duration::days(7))
        .unwrap_or(false)
}

fn reject_query_fields(uri: &OriginalUri) -> Result<(), (StatusCode, Json<Value>)> {
    if uri.query().is_some_and(|query| !query.is_empty()) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({
                "reason_code": "local_tenant_overview_query_invalid",
                "detail": "tenant overview does not accept query fields",
            })),
        ));
    }
    Ok(())
}

fn tenant_overview_store_error(error: String) -> (StatusCode, Json<Value>) {
    tracing::error!(error = %error, "local tenant overview storage operation failed");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({
            "reason_code": "local_tenant_overview_store_error",
            "detail": "local tenant overview is temporarily unavailable",
        })),
    )
}

#[derive(Serialize)]
struct TenantOverviewResponse {
    capability: &'static str,
    availability: &'static str,
    reason_code: &'static str,
    service_version: &'static str,
    contract_version: &'static str,
    allowed_actions: [&'static str; 1],
    scope: TenantOverviewScope,
    authority_revision: u64,
    tenant_info: TenantInfo,
    storage: NullField,
    projects: ProjectsProjection,
    members: MembersProjection,
    memory_history: EmptyListField,
}

#[derive(Serialize)]
struct TenantOverviewScope {
    tenant_id: String,
    project_id: Option<String>,
    workspace_id: Option<String>,
    instance_id: Option<String>,
}

#[derive(Serialize)]
struct TenantInfo {
    organization_id: String,
    plan: String,
    region: NullField,
    next_billing_date: NullField,
}

#[derive(Serialize)]
struct ProjectsProjection {
    availability: &'static str,
    reason_code: &'static str,
    active: usize,
    new_this_week: usize,
    list: Vec<ProjectProjection>,
}

#[derive(Serialize)]
struct ProjectProjection {
    id: String,
    name: String,
    owner: NullField,
    memory_consumed: NullField,
    status: &'static str,
}

impl From<DesktopProject> for ProjectProjection {
    fn from(project: DesktopProject) -> Self {
        Self {
            id: project.id,
            name: project.name,
            owner: NullField::new("unavailable", PROJECT_OWNER_REASON),
            memory_consumed: NullField::new("unavailable", PROJECT_MEMORY_REASON),
            status: "active",
        }
    }
}

#[derive(Serialize)]
struct MembersProjection {
    total: usize,
    new_added: usize,
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
struct EmptyListField {
    availability: &'static str,
    reason_code: &'static str,
    value: [Value; 0],
}
