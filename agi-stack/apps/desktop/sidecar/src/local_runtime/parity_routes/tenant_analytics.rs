use axum::extract::OriginalUri;
use serde::Serialize;

use super::super::*;

const CAPABILITY: &str = "tenant_analytics";
const SERVICE_VERSION: &str = env!("CARGO_PKG_VERSION");
const CONTRACT_VERSION: &str = "3.0.0";
const DEGRADED_REASON: &str = "local_tenant_analytics_memory_projection_unavailable";
const MEMORY_REASON: &str = "local_tenant_memory_projection_unavailable";
const TENANT_STORAGE_REASON: &str = "local_tenant_storage_projection_unavailable";
const PROJECT_STORAGE_REASON: &str = "local_project_storage_projection_unavailable";
const PROJECT_MEMORY_REASON: &str = "local_project_memory_projection_unavailable";

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new().route(
        "/api/v1/tenants/:tenant_id/analytics",
        get(tenant_analytics),
    )
}

async fn tenant_analytics(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(tenant_id): Path<String>,
    uri: OriginalUri,
) -> LocalJsonResult {
    let period_days = read_period_days(&uri)?;
    ensure_tenant_scope(&authenticated, Some(&tenant_id))?;
    let tenants = state
        .session_store
        .list_user_tenants(&authenticated.user.user_id)
        .map_err(|error| analytics_store_error(error.to_string()))?;
    if !tenants.into_iter().any(|tenant| tenant.id == tenant_id) {
        return Err((
            StatusCode::NOT_FOUND,
            Json(json!({
                "reason_code": "local_tenant_analytics_not_found",
                "detail": "tenant is unavailable in the active local scope",
            })),
        ));
    }
    let projects = state
        .session_store
        .list_user_projects(&authenticated.user.user_id, &tenant_id)
        .map_err(|error| analytics_store_error(error.to_string()))?;
    let total_projects = projects.len();
    let project_storage = projects
        .into_iter()
        .map(|project| ProjectStorageProjection {
            name: project.name,
            storage_bytes: NullableNumberField::unavailable(PROJECT_STORAGE_REASON),
            memory_count: NullableNumberField::unavailable(PROJECT_MEMORY_REASON),
        })
        .collect();
    let response = TenantAnalyticsResponse {
        capability: CAPABILITY,
        availability: "degraded",
        reason_code: DEGRADED_REASON,
        service_version: SERVICE_VERSION,
        contract_version: CONTRACT_VERSION,
        allowed_actions: ["view", "retry"],
        scope: TenantAnalyticsScope {
            tenant_id,
            project_id: None,
            workspace_id: None,
            instance_id: None,
        },
        authority_revision: authenticated.workspace.revision,
        memory_growth: EmptyMemoryField {
            availability: "unavailable",
            reason_code: MEMORY_REASON,
            value: [],
        },
        project_storage: ProjectStorageField {
            availability: "degraded",
            reason_code: PROJECT_STORAGE_REASON,
            value: project_storage,
        },
        summary: AnalyticsSummary {
            total_memories: NullableNumberField::unavailable(MEMORY_REASON),
            total_storage_bytes: NullableNumberField::unavailable(TENANT_STORAGE_REASON),
            total_projects: NullableNumberField::available(total_projects),
            period_days,
        },
    };
    serde_json::to_value(response)
        .map(Json)
        .map_err(|error| analytics_store_error(error.to_string()))
}

fn read_period_days(uri: &OriginalUri) -> Result<u16, (StatusCode, Json<Value>)> {
    let Some(query) = uri.query() else {
        return Ok(30);
    };
    let mut fields = query.split('&');
    let first = fields.next().unwrap_or_default();
    if fields.next().is_some() {
        return Err(invalid_query());
    }
    let Some((name, value)) = first.split_once('=') else {
        return Err(invalid_query());
    };
    if name != "period" {
        return Err(invalid_query());
    }
    match value {
        "7d" => Ok(7),
        "30d" => Ok(30),
        "90d" => Ok(90),
        _ => Err(invalid_query()),
    }
}

fn invalid_query() -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({
            "reason_code": "local_tenant_analytics_query_invalid",
            "detail": "period must be exactly one of 7d, 30d, or 90d",
        })),
    )
}

fn analytics_store_error(error: String) -> (StatusCode, Json<Value>) {
    tracing::error!(error = %error, "local tenant analytics storage operation failed");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({
            "reason_code": "local_tenant_analytics_store_error",
            "detail": "local tenant analytics is temporarily unavailable",
        })),
    )
}

#[derive(Serialize)]
struct TenantAnalyticsResponse {
    capability: &'static str,
    availability: &'static str,
    reason_code: &'static str,
    service_version: &'static str,
    contract_version: &'static str,
    allowed_actions: [&'static str; 2],
    scope: TenantAnalyticsScope,
    authority_revision: u64,
    #[serde(rename = "memoryGrowth")]
    memory_growth: EmptyMemoryField,
    #[serde(rename = "projectStorage")]
    project_storage: ProjectStorageField,
    summary: AnalyticsSummary,
}

#[derive(Serialize)]
struct TenantAnalyticsScope {
    tenant_id: String,
    project_id: Option<String>,
    workspace_id: Option<String>,
    instance_id: Option<String>,
}

#[derive(Serialize)]
struct EmptyMemoryField {
    availability: &'static str,
    reason_code: &'static str,
    value: [Value; 0],
}

#[derive(Serialize)]
struct ProjectStorageField {
    availability: &'static str,
    reason_code: &'static str,
    value: Vec<ProjectStorageProjection>,
}

#[derive(Serialize)]
struct ProjectStorageProjection {
    name: String,
    storage_bytes: NullableNumberField,
    memory_count: NullableNumberField,
}

#[derive(Serialize)]
struct AnalyticsSummary {
    total_memories: NullableNumberField,
    total_storage_bytes: NullableNumberField,
    total_projects: NullableNumberField,
    period_days: u16,
}

#[derive(Serialize)]
struct NullableNumberField {
    availability: &'static str,
    reason_code: Option<&'static str>,
    value: Option<usize>,
}

impl NullableNumberField {
    fn available(value: usize) -> Self {
        Self {
            availability: "available",
            reason_code: None,
            value: Some(value),
        }
    }

    fn unavailable(reason_code: &'static str) -> Self {
        Self {
            availability: "unavailable",
            reason_code: Some(reason_code),
            value: None,
        }
    }
}
