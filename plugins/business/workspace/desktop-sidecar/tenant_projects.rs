use axum::extract::OriginalUri;
use rusqlite::{params, OptionalExtension, Row};
use serde::Serialize;

use super::super::*;
use crate::local_runtime::auth_context::DesktopProject;

const SERVICE_VERSION: &str = env!("CARGO_PKG_VERSION");
const CONTRACT_VERSION: &str = "3.0.0";
const DEGRADED_REASON: &str = "local_project_configuration_projection_partial";

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(
            "/api/v1/tenant-projects",
            get(list_projects).post(create_project),
        )
        .route(
            "/api/v1/tenant-projects/:project_id",
            get(get_project).put(update_project),
        )
        .route(
            "/api/v1/tenant-projects/:project_id/archive",
            post(delete_project),
        )
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectListQuery {
    tenant_id: String,
    #[serde(default = "default_identity_catalog_page")]
    page: usize,
    #[serde(default = "default_identity_catalog_page_size")]
    page_size: usize,
    search: Option<String>,
    visibility: Option<String>,
    owner_id: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectScopeQuery {
    tenant_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectCreateRequest {
    tenant_id: String,
    name: String,
    #[serde(default)]
    description: String,
    is_public: Option<bool>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectUpdateRequest {
    name: String,
    #[serde(default)]
    description: String,
    is_public: Option<bool>,
}

async fn list_projects(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ProjectListQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, Some(&query.tenant_id))?;
    validate_list_query(&query)?;
    let mut projects = query_projects(&state, &authenticated.user.user_id, &query.tenant_id)?;
    if let Some(search) = normalized_optional(&query.search) {
        let search = search.to_lowercase();
        projects.retain(|project| {
            project.name.to_lowercase().contains(&search)
                || project
                    .description
                    .as_deref()
                    .unwrap_or_default()
                    .to_lowercase()
                    .contains(&search)
        });
    }
    if query.visibility.as_deref() == Some("public") {
        projects.clear();
    }
    if query
        .owner_id
        .as_deref()
        .is_some_and(|owner| owner != authenticated.user.user_id)
    {
        projects.clear();
    }
    let total = projects.len();
    let (offset, page_size) = identity_catalog_page_bounds(query.page, query.page_size)?;
    let projects = projects
        .into_iter()
        .skip(offset)
        .take(page_size)
        .collect::<Vec<_>>();
    let revision = authority_revision(&state, &query.tenant_id)?;
    let response = ProjectListResponse {
        projects,
        total,
        page: query.page,
        page_size: query.page_size,
        owner_ids: [authenticated.user.user_id.clone()],
        availability: "degraded",
        reason_code: DEGRADED_REASON,
        service_version: SERVICE_VERSION,
        contract_version: CONTRACT_VERSION,
        allowed_actions: allowed_actions(&authenticated),
        authority_revision: revision,
        scope: TenantProjectsScope::new(query.tenant_id),
    };
    serialize(response)
}

async fn get_project(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    Query(query): Query<ProjectScopeQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, Some(&query.tenant_id))?;
    validate_identifier(&project_id, "project")?;
    let project = query_project(
        &state,
        &authenticated.user.user_id,
        &query.tenant_id,
        &project_id,
    )?;
    serialize(project)
}

async fn create_project(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    Json(request): Json<ProjectCreateRequest>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, Some(&request.tenant_id))?;
    ensure_manager(&authenticated)?;
    let idempotency_key = require_idempotency_key(&headers)?;
    let (name, description) =
        validate_mutation(&request.name, &request.description, request.is_public)?;
    let payload_hash = mutation_payload_hash(&(
        "create",
        request.tenant_id.as_str(),
        name.as_str(),
        description.as_str(),
    ))?;
    let now_ms = Utc::now().timestamp_millis();
    let project_id = format!("local-{}", Uuid::new_v4());
    let mut connection = state.session_store.connection().map_err(store_error)?;
    let transaction = connection
        .transaction()
        .map_err(|error| store_error(error.to_string()))?;
    if let Some(response) = query_mutation_receipt(
        &transaction,
        &authenticated,
        &request.tenant_id,
        idempotency_key,
        "create",
        &payload_hash,
    )? {
        return Ok(Json(response));
    }
    transaction
        .execute(
            "INSERT INTO desktop_projects(
               id, tenant_id, name, description, status, created_at_ms, updated_at_ms
             ) VALUES (?1, ?2, ?3, ?4, 'active', ?5, ?5)",
            params![project_id, request.tenant_id, name, description, now_ms],
        )
        .map_err(|error| store_error(error.to_string()))?;
    let response = serialize_value(query_project_on(
        &transaction,
        &authenticated.user.user_id,
        &request.tenant_id,
        &project_id,
    )?)?;
    store_mutation_receipt(
        &transaction,
        &authenticated,
        &request.tenant_id,
        idempotency_key,
        "create",
        &project_id,
        &payload_hash,
        &response,
        now_ms,
    )?;
    transaction
        .commit()
        .map_err(|error| store_error(error.to_string()))?;
    Ok(Json(response))
}

async fn update_project(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    headers: HeaderMap,
    Json(request): Json<ProjectUpdateRequest>,
) -> LocalJsonResult {
    ensure_manager(&authenticated)?;
    validate_identifier(&project_id, "project")?;
    let idempotency_key = require_idempotency_key(&headers)?;
    let (name, description) =
        validate_mutation(&request.name, &request.description, request.is_public)?;
    let tenant_id = authenticated.workspace.tenant_id.clone();
    let payload_hash = mutation_payload_hash(&(
        "update",
        tenant_id.as_str(),
        project_id.as_str(),
        name.as_str(),
        description.as_str(),
    ))?;
    let now_ms = Utc::now().timestamp_millis();
    let mut connection = state.session_store.connection().map_err(store_error)?;
    let transaction = connection
        .transaction()
        .map_err(|error| store_error(error.to_string()))?;
    if let Some(response) = query_mutation_receipt(
        &transaction,
        &authenticated,
        &tenant_id,
        idempotency_key,
        "update",
        &payload_hash,
    )? {
        return Ok(Json(response));
    }
    let changed = transaction
        .execute(
            "UPDATE desktop_projects
             SET name = ?1, description = ?2, updated_at_ms = ?3
             WHERE id = ?4 AND tenant_id = ?5 AND status = 'active'",
            params![name, description, now_ms, project_id, tenant_id],
        )
        .map_err(|error| store_error(error.to_string()))?;
    if changed != 1 {
        return Err(not_found());
    };
    let response = serialize_value(query_project_on(
        &transaction,
        &authenticated.user.user_id,
        &tenant_id,
        &project_id,
    )?)?;
    store_mutation_receipt(
        &transaction,
        &authenticated,
        &tenant_id,
        idempotency_key,
        "update",
        &project_id,
        &payload_hash,
        &response,
        now_ms,
    )?;
    transaction
        .commit()
        .map_err(|error| store_error(error.to_string()))?;
    Ok(Json(response))
}

async fn delete_project(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    headers: HeaderMap,
    uri: OriginalUri,
) -> LocalJsonResult {
    reject_query(&uri)?;
    ensure_manager(&authenticated)?;
    validate_identifier(&project_id, "project")?;
    let idempotency_key = require_idempotency_key(&headers)?;
    let tenant_id = authenticated.workspace.tenant_id.clone();
    let payload_hash = mutation_payload_hash(&("delete", tenant_id.as_str(), project_id.as_str()))?;
    let now_ms = Utc::now().timestamp_millis();
    let mut connection = state.session_store.connection().map_err(store_error)?;
    let transaction = connection
        .transaction()
        .map_err(|error| store_error(error.to_string()))?;
    if let Some(response) = query_mutation_receipt(
        &transaction,
        &authenticated,
        &tenant_id,
        idempotency_key,
        "delete",
        &payload_hash,
    )? {
        return Ok(Json(response));
    }
    if authenticated.workspace.project_id == project_id {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "reason_code": "local_active_project_delete_conflict",
                "detail": "switch to another project before deleting the active project",
            })),
        ));
    }
    let changed = transaction
        .execute(
            "UPDATE desktop_projects
             SET status = 'archived', updated_at_ms = ?1
             WHERE id = ?2 AND tenant_id = ?3 AND status = 'active'",
            params![now_ms, project_id, tenant_id],
        )
        .map_err(|error| store_error(error.to_string()))?;
    if changed != 1 {
        return Err(not_found());
    }
    let response = json!({
        "success": true,
        "project_id": project_id,
    });
    store_mutation_receipt(
        &transaction,
        &authenticated,
        &tenant_id,
        idempotency_key,
        "delete",
        &project_id,
        &payload_hash,
        &response,
        now_ms,
    )?;
    transaction
        .commit()
        .map_err(|error| store_error(error.to_string()))?;
    Ok(Json(response))
}

fn query_projects(
    state: &LocalRuntimeState,
    user_id: &str,
    tenant_id: &str,
) -> Result<Vec<DesktopProject>, (StatusCode, Json<Value>)> {
    state
        .session_store
        .list_user_projects(user_id, tenant_id)
        .map_err(|error| store_error(error.to_string()))
}

fn query_project(
    state: &LocalRuntimeState,
    user_id: &str,
    tenant_id: &str,
    project_id: &str,
) -> Result<DesktopProject, (StatusCode, Json<Value>)> {
    let connection = state.session_store.connection().map_err(store_error)?;
    query_project_on(&connection, user_id, tenant_id, project_id)
}

fn query_project_on(
    connection: &rusqlite::Connection,
    user_id: &str,
    tenant_id: &str,
    project_id: &str,
) -> Result<DesktopProject, (StatusCode, Json<Value>)> {
    connection
        .query_row(
            "SELECT id, tenant_id, name, description, created_at_ms, updated_at_ms
             FROM desktop_projects
             WHERE id = ?1 AND tenant_id = ?2 AND status = 'active'",
            params![project_id, tenant_id],
            |row| project_from_row(row, user_id),
        )
        .optional()
        .map_err(|error| store_error(error.to_string()))?
        .ok_or_else(not_found)
}

fn query_mutation_receipt(
    transaction: &rusqlite::Transaction<'_>,
    authenticated: &AuthenticatedContext,
    tenant_id: &str,
    idempotency_key: &str,
    operation: &str,
    payload_hash: &str,
) -> Result<Option<Value>, (StatusCode, Json<Value>)> {
    let stored = transaction
        .query_row(
            "SELECT operation, payload_hash, response_json
             FROM desktop_tenant_project_mutation_receipts
             WHERE user_id = ?1 AND tenant_id = ?2 AND idempotency_key = ?3",
            params![authenticated.user.user_id, tenant_id, idempotency_key],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            },
        )
        .optional()
        .map_err(|error| store_error(error.to_string()))?;
    let Some((stored_operation, stored_hash, response_json)) = stored else {
        return Ok(None);
    };
    if stored_operation != operation || stored_hash != payload_hash {
        return Err(idempotency_conflict());
    }
    serde_json::from_str(&response_json)
        .map(Some)
        .map_err(|error| store_error(error.to_string()))
}

#[allow(clippy::too_many_arguments)]
fn store_mutation_receipt(
    transaction: &rusqlite::Transaction<'_>,
    authenticated: &AuthenticatedContext,
    tenant_id: &str,
    idempotency_key: &str,
    operation: &str,
    project_id: &str,
    payload_hash: &str,
    response: &Value,
    now_ms: i64,
) -> Result<(), (StatusCode, Json<Value>)> {
    let response_json =
        serde_json::to_string(response).map_err(|error| store_error(error.to_string()))?;
    transaction
        .execute(
            "INSERT INTO desktop_tenant_project_mutation_receipts(
               user_id, tenant_id, idempotency_key, operation, project_id,
               payload_hash, response_json, created_at_ms
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                authenticated.user.user_id,
                tenant_id,
                idempotency_key,
                operation,
                project_id,
                payload_hash,
                response_json,
                now_ms
            ],
        )
        .map(|_| ())
        .map_err(|error| store_error(error.to_string()))
}

fn mutation_payload_hash<T: Serialize>(payload: &T) -> Result<String, (StatusCode, Json<Value>)> {
    let encoded = serde_json::to_vec(payload).map_err(|error| store_error(error.to_string()))?;
    Ok(format!("sha256:{:x}", Sha256::digest(encoded)))
}

fn require_idempotency_key(headers: &HeaderMap) -> Result<&str, (StatusCode, Json<Value>)> {
    let key = headers
        .get("idempotency-key")
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| {
            !value.is_empty()
                && value.len() <= 255
                && value.bytes().all(|byte| (0x21..=0x7e).contains(&byte))
        })
        .ok_or_else(|| invalid("local_project_idempotency_key_invalid"))?;
    Ok(key)
}

fn project_from_row(row: &Row<'_>, user_id: &str) -> rusqlite::Result<DesktopProject> {
    Ok(DesktopProject {
        id: row.get(0)?,
        tenant_id: row.get(1)?,
        name: row.get(2)?,
        description: row.get(3)?,
        owner_id: user_id.to_string(),
        member_ids: vec![user_id.to_string()],
        memory_rules: default_memory_rules(),
        graph_config: default_graph_config(),
        graph_store_id: None,
        retrieval_store_id: None,
        is_public: false,
        agent_conversation_mode: "workspace".to_string(),
        created_at: iso_millis(row.get(4)?),
        updated_at: Some(iso_millis(row.get(5)?)),
        stats: json!({}),
    })
}

fn authority_revision(
    state: &LocalRuntimeState,
    tenant_id: &str,
) -> Result<u64, (StatusCode, Json<Value>)> {
    let connection = state.session_store.connection().map_err(store_error)?;
    let revision = connection
        .query_row(
            "SELECT COALESCE(MAX(updated_at_ms), 0)
             FROM desktop_projects WHERE tenant_id = ?1",
            [tenant_id],
            |row| row.get::<_, i64>(0),
        )
        .map_err(|error| store_error(error.to_string()))?;
    Ok(u64::try_from(revision.max(0)).unwrap_or(0))
}

fn allowed_actions(authenticated: &AuthenticatedContext) -> Vec<&'static str> {
    if matches!(authenticated.membership_role.as_str(), "owner" | "admin") {
        vec!["view", "list", "create", "update", "delete"]
    } else {
        vec!["view", "list"]
    }
}

fn ensure_manager(authenticated: &AuthenticatedContext) -> Result<(), (StatusCode, Json<Value>)> {
    if matches!(authenticated.membership_role.as_str(), "owner" | "admin") {
        return Ok(());
    }
    Err((
        StatusCode::FORBIDDEN,
        Json(json!({
            "reason_code": "local_project_mutation_forbidden",
            "detail": "tenant owner or admin authority is required",
        })),
    ))
}

fn validate_list_query(query: &ProjectListQuery) -> Result<(), (StatusCode, Json<Value>)> {
    if query.search.as_ref().is_some_and(|value| value.len() > 200) {
        return Err(invalid("local_project_search_invalid"));
    }
    if !matches!(
        query.visibility.as_deref(),
        None | Some("all" | "public" | "private")
    ) {
        return Err(invalid("local_project_visibility_filter_invalid"));
    }
    if query
        .owner_id
        .as_deref()
        .is_some_and(|value| !bounded_identifier(value))
    {
        return Err(invalid("local_project_owner_filter_invalid"));
    }
    Ok(())
}

fn validate_mutation(
    name: &str,
    description: &str,
    is_public: Option<bool>,
) -> Result<(String, String), (StatusCode, Json<Value>)> {
    let name = name.trim();
    if name.is_empty() || name.len() > 200 {
        return Err(invalid("local_project_name_invalid"));
    }
    let description = description.trim();
    if description.len() > 4_000 {
        return Err(invalid("local_project_description_invalid"));
    }
    if is_public == Some(true) {
        return Err(invalid("local_project_public_visibility_unavailable"));
    }
    Ok((name.to_string(), description.to_string()))
}

fn validate_identifier(value: &str, label: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if bounded_identifier(value) {
        return Ok(());
    }
    Err(invalid(&format!("local_{label}_identifier_invalid")))
}

fn normalized_optional(value: &Option<String>) -> Option<&str> {
    value
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
}

fn reject_query(uri: &OriginalUri) -> Result<(), (StatusCode, Json<Value>)> {
    if uri.query().is_some_and(|query| !query.is_empty()) {
        return Err(invalid("local_project_query_invalid"));
    }
    Ok(())
}

fn serialize<T: Serialize>(value: T) -> LocalJsonResult {
    serde_json::to_value(value)
        .map(Json)
        .map_err(|error| store_error(error.to_string()))
}

fn serialize_value<T: Serialize>(value: T) -> Result<Value, (StatusCode, Json<Value>)> {
    serde_json::to_value(value).map_err(|error| store_error(error.to_string()))
}

fn invalid(reason_code: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({
            "reason_code": reason_code,
            "detail": "local project request is invalid",
        })),
    )
}

fn not_found() -> (StatusCode, Json<Value>) {
    (
        StatusCode::NOT_FOUND,
        Json(json!({
            "reason_code": "local_project_not_found",
            "detail": "project is unavailable in the active local scope",
        })),
    )
}

fn idempotency_conflict() -> (StatusCode, Json<Value>) {
    (
        StatusCode::CONFLICT,
        Json(json!({
            "reason_code": "local_project_idempotency_conflict",
            "detail": "idempotency key is already bound to another tenant project mutation",
        })),
    )
}

fn store_error(error: String) -> (StatusCode, Json<Value>) {
    tracing::error!(error = %error, "local project storage operation failed");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({
            "reason_code": "local_project_store_error",
            "detail": "local project authority is temporarily unavailable",
        })),
    )
}

fn iso_millis(value: i64) -> String {
    chrono::DateTime::from_timestamp_millis(value)
        .unwrap_or(chrono::DateTime::UNIX_EPOCH)
        .to_rfc3339()
}

fn default_memory_rules() -> Value {
    json!({
        "max_episodes": 1000,
        "retention_days": 30,
        "auto_refresh": true,
        "refresh_interval": 24,
    })
}

fn default_graph_config() -> Value {
    json!({
        "max_nodes": 5000,
        "max_edges": 10000,
        "similarity_threshold": 0.7,
        "community_detection": true,
    })
}

#[derive(Serialize)]
struct ProjectListResponse {
    projects: Vec<DesktopProject>,
    total: usize,
    page: usize,
    page_size: usize,
    owner_ids: [String; 1],
    availability: &'static str,
    reason_code: &'static str,
    service_version: &'static str,
    contract_version: &'static str,
    allowed_actions: Vec<&'static str>,
    authority_revision: u64,
    scope: TenantProjectsScope,
}

#[derive(Serialize)]
struct TenantProjectsScope {
    tenant_id: String,
    project_id: Option<String>,
    workspace_id: Option<String>,
    instance_id: Option<String>,
}

impl TenantProjectsScope {
    fn new(tenant_id: String) -> Self {
        Self {
            tenant_id,
            project_id: None,
            workspace_id: None,
            instance_id: None,
        }
    }
}
