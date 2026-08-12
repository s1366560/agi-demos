//! Public read-side compatibility handlers implemented by the Workspace extension.

use std::collections::BTreeMap;
use std::sync::Arc;

use axum::extract::{Path, Query};
use axum::http::HeaderMap;
use axum::{Extension, Json};
use bcs_db_api::{DbRow, DbStatementBuilder};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use super::{ApiError, WorkspaceCoreState};

pub(super) const USER_HEADER: &str = "x-memstack-user-id";
pub(super) const SUPERUSER_HEADER: &str = "x-memstack-user-is-superuser";
const READ_SURFACES: &[&str] = &[
    "goals",
    "discussion",
    "status",
    "collaboration",
    "members",
    "genes",
    "files",
    "notes",
    "topology",
    "settings",
];

#[derive(Debug)]
pub(super) struct Caller {
    pub(super) user_id: String,
    pub(super) is_superuser: bool,
}

#[derive(Debug, Deserialize)]
pub(super) struct WorkspaceListQuery {
    limit: Option<String>,
    offset: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct WorkspaceAgentListQuery {
    active_only: Option<String>,
    limit: Option<String>,
    offset: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct WorkspaceMemberListQuery {
    limit: Option<String>,
    offset: Option<String>,
}

#[derive(Debug, Serialize)]
pub(super) struct WorkspaceResponse {
    id: String,
    tenant_id: String,
    project_id: String,
    name: String,
    created_by: String,
    description: Option<String>,
    is_archived: bool,
    metadata: Value,
    office_status: String,
    hex_layout_config: Value,
    created_at: String,
    updated_at: Option<String>,
}

#[derive(Debug, Serialize)]
pub(super) struct WorkspaceAgentResponse {
    id: String,
    workspace_id: String,
    agent_id: String,
    display_name: Option<String>,
    description: Option<String>,
    config: Value,
    is_active: bool,
    hex_q: Option<i64>,
    hex_r: Option<i64>,
    theme_color: Option<String>,
    label: Option<String>,
    status: Option<String>,
    created_at: String,
    updated_at: Option<String>,
}

#[derive(Debug, Serialize)]
pub(super) struct WorkspaceMemberResponse {
    id: String,
    workspace_id: String,
    user_id: String,
    user_email: Option<String>,
    role: String,
    invited_by: Option<String>,
    created_at: String,
    updated_at: Option<String>,
}

#[derive(Debug, Serialize)]
struct MutationCapability {
    allowed: bool,
    revision_guarded: bool,
    idempotency_guarded: bool,
    actions: BTreeMap<&'static str, &'static [&'static str]>,
}

#[derive(Debug, Serialize)]
pub(super) struct CollaborationCapabilitiesResponse {
    service_version: &'static str,
    contract_version: &'static str,
    authority: &'static str,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    status: &'static str,
    reason_code: Option<&'static str>,
    canonical_read: bool,
    read_surfaces: &'static [&'static str],
    mutations: MutationCapability,
    allowed_actions: BTreeMap<&'static str, &'static [&'static str]>,
}

#[derive(Debug, Serialize)]
pub(super) struct CollaborationAuthorityResponse {
    contract_version: &'static str,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    revision: u64,
    cursor: String,
}

pub(super) async fn get_workspace(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
) -> Result<Json<WorkspaceResponse>, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let workspace = require_workspace_service_access(
        state.as_ref(),
        &tenant_id,
        &project_id,
        &workspace_id,
        &caller,
    )
    .await?;
    Ok(Json(workspace))
}

pub(super) async fn list_workspaces(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Query(query): Query<WorkspaceListQuery>,
    headers: HeaderMap,
) -> Result<Json<Vec<WorkspaceResponse>>, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let (limit, offset) = pagination(query.limit.as_deref(), query.offset.as_deref(), 50)?;
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "SELECT p.workspace_id, p.tenant_id, p.project_id, p.name, p.created_by, \
             p.description, p.is_archived, p.metadata_json, p.office_status, \
             p.hex_layout_config_json, p.created_at, p.updated_at \
             FROM workspace_profiles p JOIN workspace_members m \
               ON m.workspace_id = p.workspace_id AND m.user_id = ",
        )
        .bind(caller.user_id)
        .push_static(" WHERE p.tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND p.project_id = ")
        .bind(project_id)
        .push_static(" AND p.deleted_at IS NULL")
        .push_static(" ORDER BY p.created_at DESC, p.workspace_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(ApiError::Database)?;
    let workspaces = rows
        .iter()
        .map(workspace_from_row)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Json(workspaces))
}

pub(super) async fn list_workspace_agents(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<WorkspaceAgentListQuery>,
    headers: HeaderMap,
) -> Result<Json<Vec<WorkspaceAgentResponse>>, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let active_only = query_bool("active_only", query.active_only.as_deref(), false)?;
    let (limit, offset) = pagination(query.limit.as_deref(), query.offset.as_deref(), 100)?;
    let _workspace = require_workspace_service_access(
        state.as_ref(),
        &tenant_id,
        &project_id,
        &workspace_id,
        &caller,
    )
    .await?;
    let mut statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "SELECT binding_id, workspace_id, agent_id, display_name, description, config_json, \
             is_active, hex_q, hex_r, theme_color, label, status, created_at, updated_at \
             FROM workspace_agent_bindings WHERE tenant_id = ",
        )
        .bind(tenant_id)
        .push_static(" AND project_id = ")
        .bind(project_id)
        .push_static(" AND workspace_id = ")
        .bind(workspace_id);
    if active_only {
        statement = statement.push_static(" AND is_active = TRUE");
    }
    let statement = statement
        .push_static(" ORDER BY created_at ASC, binding_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(ApiError::Database)?;
    let agents = rows
        .iter()
        .map(agent_from_row)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Json(agents))
}

pub(super) async fn list_workspace_members(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<WorkspaceMemberListQuery>,
    headers: HeaderMap,
) -> Result<Json<Vec<WorkspaceMemberResponse>>, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let (limit, offset) = pagination(query.limit.as_deref(), query.offset.as_deref(), 100)?;
    let _workspace = require_workspace_service_access(
        state.as_ref(),
        &tenant_id,
        &project_id,
        &workspace_id,
        &caller,
    )
    .await?;
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "SELECT m.member_id, m.workspace_id, m.user_id, i.email AS user_email, \
             m.role, m.invited_by, m.created_at, m.updated_at \
             FROM workspace_members m LEFT JOIN workspace_principal_identities i \
               ON i.tenant_id = m.tenant_id AND i.project_id = m.project_id \
              AND i.workspace_id = m.workspace_id AND i.user_id = m.user_id \
             WHERE m.tenant_id = ",
        )
        .bind(tenant_id)
        .push_static(" AND m.project_id = ")
        .bind(project_id)
        .push_static(" AND m.workspace_id = ")
        .bind(workspace_id)
        .push_static(" ORDER BY m.created_at ASC, m.member_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(ApiError::Database)?;
    let members = rows
        .iter()
        .map(member_from_row)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Json(members))
}

pub(super) async fn get_collaboration_capabilities(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
) -> Result<Json<CollaborationCapabilitiesResponse>, ApiError> {
    let caller = caller_from_headers(&headers)?;
    require_scoped_workspace_access(
        state.as_ref(),
        &tenant_id,
        &project_id,
        &workspace_id,
        &caller,
        false,
        "Access denied",
    )
    .await?;
    let actions = collaboration_actions();
    Ok(Json(CollaborationCapabilitiesResponse {
        service_version: "0.2.0",
        contract_version: "2.0.0",
        authority: state.authority.as_str(),
        tenant_id,
        project_id,
        workspace_id,
        status: "available",
        reason_code: None,
        canonical_read: true,
        read_surfaces: READ_SURFACES,
        mutations: MutationCapability {
            allowed: true,
            revision_guarded: true,
            idempotency_guarded: true,
            actions: actions.clone(),
        },
        allowed_actions: actions,
    }))
}

pub(super) async fn get_collaboration_authority(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
) -> Result<Json<CollaborationAuthorityResponse>, ApiError> {
    let caller = caller_from_headers(&headers)?;
    require_scoped_workspace_access(
        state.as_ref(),
        &tenant_id,
        &project_id,
        &workspace_id,
        &caller,
        true,
        "Workspace access required",
    )
    .await?;
    let revision = read_authority_revision(state.as_ref(), &tenant_id, &project_id, &workspace_id)
        .await?
        .unwrap_or(0);
    let cursor = format!("workspace:{workspace_id}:revision:{revision}");
    Ok(Json(CollaborationAuthorityResponse {
        contract_version: "2.0.0",
        tenant_id,
        project_id,
        workspace_id,
        revision,
        cursor,
    }))
}

async fn read_workspace(
    state: &WorkspaceCoreState,
    workspace_id: &str,
) -> Result<Option<WorkspaceResponse>, ApiError> {
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "SELECT workspace_id, tenant_id, project_id, name, created_by, description, \
             is_archived, metadata_json, office_status, hex_layout_config_json, \
             created_at, updated_at FROM workspace_profiles WHERE workspace_id = ",
        )
        .bind(workspace_id)
        .push_static(" AND deleted_at IS NULL")
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(ApiError::Database)?;
    rows.first().map(workspace_from_row).transpose()
}

async fn require_workspace_service_access(
    state: &WorkspaceCoreState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    caller: &Caller,
) -> Result<WorkspaceResponse, ApiError> {
    let workspace = read_workspace(state, workspace_id)
        .await?
        .ok_or(ApiError::NotFound)?;
    require_membership(state, workspace_id, caller, "Access denied").await?;
    if workspace.tenant_id != tenant_id || workspace.project_id != project_id {
        return Err(ApiError::NotFound);
    }
    Ok(workspace)
}

pub(super) async fn require_scoped_workspace_access(
    state: &WorkspaceCoreState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    caller: &Caller,
    allow_superuser: bool,
    forbidden_detail: &'static str,
) -> Result<(), ApiError> {
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static("SELECT 1 AS workspace_exists FROM workspace_profiles WHERE tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND project_id = ")
        .bind(project_id)
        .push_static(" AND workspace_id = ")
        .bind(workspace_id)
        .push_static(" AND deleted_at IS NULL LIMIT 1")
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(ApiError::Database)?;
    if rows.is_empty() {
        return Err(ApiError::NotFound);
    }
    if allow_superuser && caller.is_superuser {
        return Ok(());
    }
    require_membership(state, workspace_id, caller, forbidden_detail).await
}

async fn require_membership(
    state: &WorkspaceCoreState,
    workspace_id: &str,
    caller: &Caller,
    forbidden_detail: &'static str,
) -> Result<(), ApiError> {
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static("SELECT 1 AS member_role FROM workspace_members WHERE workspace_id = ")
        .bind(workspace_id)
        .push_static(" AND user_id = ")
        .bind(caller.user_id.as_str())
        .push_static(" LIMIT 1")
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(ApiError::Database)?;
    if rows.is_empty() {
        return Err(ApiError::Forbidden(forbidden_detail));
    }
    Ok(())
}

pub(super) async fn read_authority_revision(
    state: &WorkspaceCoreState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<Option<u64>, ApiError> {
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND project_id = ")
        .bind(project_id)
        .push_static(" AND workspace_id = ")
        .bind(workspace_id)
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(ApiError::Database)?;
    let Some(row) = rows.first() else {
        return Ok(None);
    };
    let revision = required_i64(row, "revision")?;
    u64::try_from(revision)
        .map(Some)
        .map_err(|_| ApiError::InvalidDatabase("revision is negative".to_string()))
}

fn workspace_from_row(row: &DbRow) -> Result<WorkspaceResponse, ApiError> {
    Ok(WorkspaceResponse {
        id: required_string(row, "workspace_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        name: required_string(row, "name")?,
        created_by: required_string(row, "created_by")?,
        description: optional_string(row, "description")?,
        is_archived: required_bool(row, "is_archived")?,
        metadata: required_json_object(row, "metadata_json")?,
        office_status: required_string(row, "office_status")?,
        hex_layout_config: required_json_object(row, "hex_layout_config_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: optional_string(row, "updated_at")?,
    })
}

fn agent_from_row(row: &DbRow) -> Result<WorkspaceAgentResponse, ApiError> {
    Ok(WorkspaceAgentResponse {
        id: required_string(row, "binding_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        agent_id: required_string(row, "agent_id")?,
        display_name: optional_string(row, "display_name")?,
        description: optional_string(row, "description")?,
        config: required_json_object(row, "config_json")?,
        is_active: required_bool(row, "is_active")?,
        hex_q: optional_i64(row, "hex_q")?,
        hex_r: optional_i64(row, "hex_r")?,
        theme_color: optional_string(row, "theme_color")?,
        label: optional_string(row, "label")?,
        status: optional_string(row, "status")?,
        created_at: required_string(row, "created_at")?,
        updated_at: optional_string(row, "updated_at")?,
    })
}

fn member_from_row(row: &DbRow) -> Result<WorkspaceMemberResponse, ApiError> {
    Ok(WorkspaceMemberResponse {
        id: required_string(row, "member_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        user_id: required_string(row, "user_id")?,
        user_email: Some(required_string(row, "user_email")?),
        role: required_string(row, "role")?,
        invited_by: optional_string(row, "invited_by")?,
        created_at: required_string(row, "created_at")?,
        updated_at: optional_string(row, "updated_at")?,
    })
}

fn pagination(
    limit: Option<&str>,
    offset: Option<&str>,
    default_limit: i64,
) -> Result<(i64, i64), ApiError> {
    let limit = query_integer("limit", limit, default_limit, 1, Some(500))?;
    let offset = query_integer("offset", offset, 0, 0, None)?;
    Ok((limit, offset))
}

fn query_integer(
    field: &'static str,
    raw: Option<&str>,
    default: i64,
    minimum: i64,
    maximum: Option<i64>,
) -> Result<i64, ApiError> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    let value = parse_pydantic_integer(raw).ok_or_else(|| {
        validation_error(
            "int_parsing",
            field,
            "Input should be a valid integer, unable to parse string as an integer",
            raw,
            None,
        )
    })?;
    if value < minimum {
        return Err(validation_error(
            "greater_than_equal",
            field,
            &format!("Input should be greater than or equal to {minimum}"),
            raw,
            Some(json!({"ge": minimum})),
        ));
    }
    if let Some(maximum) = maximum
        && value > maximum
    {
        return Err(validation_error(
            "less_than_equal",
            field,
            &format!("Input should be less than or equal to {maximum}"),
            raw,
            Some(json!({"le": maximum})),
        ));
    }
    Ok(value)
}

fn parse_pydantic_integer(raw: &str) -> Option<i64> {
    let normalized = raw.trim();
    if let Ok(value) = normalized.parse::<i64>() {
        return Some(value);
    }
    let (integer, fraction) = normalized.split_once('.')?;
    if integer.is_empty() || fraction.is_empty() || !fraction.bytes().all(|byte| byte == b'0') {
        return None;
    }
    integer.parse::<i64>().ok()
}

fn query_bool(field: &'static str, raw: Option<&str>, default: bool) -> Result<bool, ApiError> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    match raw.to_ascii_lowercase().as_str() {
        "1" | "true" | "t" | "on" | "yes" | "y" => Ok(true),
        "0" | "false" | "f" | "off" | "no" | "n" => Ok(false),
        _ => Err(validation_error(
            "bool_parsing",
            field,
            "Input should be a valid boolean, unable to interpret input",
            raw,
            None,
        )),
    }
}

fn validation_error(
    error_type: &'static str,
    field: &'static str,
    message: &str,
    input: &str,
    context: Option<Value>,
) -> ApiError {
    let mut detail = json!({
        "type": error_type,
        "loc": ["query", field],
        "msg": message,
        "input": input,
    });
    if let Some(context) = context {
        detail["ctx"] = context;
    }
    ApiError::Validation(json!([detail]))
}

pub(super) fn caller_from_headers(headers: &HeaderMap) -> Result<Caller, ApiError> {
    let user_id = super::required_header(headers, USER_HEADER)?;
    let is_superuser = match headers.get(SUPERUSER_HEADER) {
        None => false,
        Some(value) if value == "true" => true,
        Some(value) if value == "false" => false,
        Some(_) => {
            return Err(ApiError::InvalidRequest(format!(
                "invalid {SUPERUSER_HEADER} header"
            )));
        }
    };
    Ok(Caller {
        user_id,
        is_superuser,
    })
}

fn required_string(row: &DbRow, column: &str) -> Result<String, ApiError> {
    row.get_string(column)
        .map_err(ApiError::Database)?
        .ok_or_else(|| ApiError::InvalidDatabase(format!("{column} is missing")))
}

fn optional_string(row: &DbRow, column: &str) -> Result<Option<String>, ApiError> {
    row.get_string(column).map_err(ApiError::Database)
}

fn required_i64(row: &DbRow, column: &str) -> Result<i64, ApiError> {
    row.get_i64(column)
        .map_err(ApiError::Database)?
        .ok_or_else(|| ApiError::InvalidDatabase(format!("{column} is missing")))
}

fn optional_i64(row: &DbRow, column: &str) -> Result<Option<i64>, ApiError> {
    row.get_i64(column).map_err(ApiError::Database)
}

fn required_bool(row: &DbRow, column: &str) -> Result<bool, ApiError> {
    row.get_bool(column)
        .map_err(ApiError::Database)?
        .ok_or_else(|| ApiError::InvalidDatabase(format!("{column} is missing")))
}

fn required_json_object(row: &DbRow, column: &str) -> Result<Value, ApiError> {
    let raw = required_string(row, column)?;
    let value: Value = serde_json::from_str(&raw).map_err(ApiError::Json)?;
    if !value.is_object() {
        return Err(ApiError::InvalidDatabase(format!(
            "{column} is not a JSON object"
        )));
    }
    Ok(value)
}

fn collaboration_actions() -> BTreeMap<&'static str, &'static [&'static str]> {
    BTreeMap::from([
        (
            "goals",
            &[
                "create_objective",
                "update_objective",
                "delete_objective",
                "project_objective_to_task",
                "create_task",
                "update_task",
                "delete_task",
                "assign_task_agent",
                "unassign_task_agent",
            ][..],
        ),
        (
            "discussion",
            &[
                "create_post",
                "update_post",
                "delete_post",
                "pin_post",
                "unpin_post",
                "create_reply",
                "update_reply",
                "delete_reply",
            ][..],
        ),
        ("status", &["update_task", "apply_task_recovery_action"][..]),
        (
            "collaboration",
            &[
                "bind_agent",
                "update_agent_binding",
                "unbind_agent",
                "add_member",
                "update_member_role",
                "remove_member",
                "create_task",
                "update_task",
                "delete_task",
                "assign_task_agent",
                "unassign_task_agent",
            ][..],
        ),
        (
            "members",
            &["add_member", "update_member_role", "remove_member"][..],
        ),
        ("genes", &["create_gene", "update_gene", "delete_gene"][..]),
        (
            "files",
            &[
                "create_directory",
                "upload_file",
                "update_file",
                "delete_file",
                "copy_file",
            ][..],
        ),
        ("notes", &[][..]),
        (
            "topology",
            &[
                "create_node",
                "update_node",
                "delete_node",
                "create_edge",
                "update_edge",
                "delete_edge",
            ][..],
        ),
        ("settings", &["update_workspace"][..]),
    ])
}
