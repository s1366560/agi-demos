//! Legacy-path Workspace topology HTTP handlers over the Avernet authority.

use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::extract::{Path, Query};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Extension, Json, Router};
use memstack_workspace_service::{
    PublicCreateTopologyEdgeInput, PublicCreateTopologyNodeInput, PublicUpdateTopologyEdgeFields,
    PublicUpdateTopologyNodeFields, PublicWorkspaceTopologyContext, PublicWorkspaceTopologyEdge,
    PublicWorkspaceTopologyError, PublicWorkspaceTopologyErrorKind, PublicWorkspaceTopologyNode,
    PublicWorkspaceTopologyService,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection, optional_header};
use super::public_api::caller_from_headers;
use super::workspace_scope::{WorkspaceScopeError, resolve_workspace_scope};
use super::{ApiError, WorkspaceCoreState};

const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const IF_MATCH_HEADER: &str = "if-match";
const NODE_TYPES: &[&str] = &[
    "user",
    "agent",
    "task",
    "note",
    "corridor",
    "human_seat",
    "objective",
];

#[derive(Debug, Deserialize)]
struct PageQuery {
    limit: Option<String>,
    offset: Option<String>,
}

#[derive(Debug, Clone, Copy)]
enum ScopeNotFound {
    InvalidRequest,
    Topology,
    Node,
    Edge,
}

pub(super) fn router() -> Router {
    Router::new()
        .route(
            "/api/v1/workspaces/{workspace_id}/topology/nodes",
            get(list_nodes).post(create_node),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/topology/nodes/{node_id}",
            get(get_node).patch(update_node).delete(delete_node),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/topology/edges",
            get(list_edges).post(create_edge),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/topology/edges/{edge_id}",
            get(get_edge).patch(update_edge).delete(delete_edge),
        )
}

async fn create_node(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(workspace_id): Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> TopologyResult<(StatusCode, Json<PublicWorkspaceTopologyNode>)> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = topology_context(
        &state,
        workspace_id,
        &headers,
        ScopeNotFound::InvalidRequest,
    )
    .await?;
    let input = parse_create_node(context, &request)?;
    let outcome = service(&state)
        .create_node(&input)
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::InvalidRequest))?;
    Ok((StatusCode::CREATED, Json(outcome.value)))
}

async fn list_nodes(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(workspace_id): Path<String>,
    Query(query): Query<PageQuery>,
    headers: HeaderMap,
) -> TopologyResult<Json<Vec<PublicWorkspaceTopologyNode>>> {
    let context = topology_context(&state, workspace_id, &headers, ScopeNotFound::Topology).await?;
    let limit = query_integer("limit", query.limit.as_deref(), 1000)?;
    let offset = query_integer("offset", query.offset.as_deref(), 0)?;
    let nodes = service(&state)
        .list_nodes(&context, limit, offset)
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::Topology))?;
    Ok(Json(nodes))
}

async fn get_node(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TopologyResult<Json<PublicWorkspaceTopologyNode>> {
    let context = topology_context(&state, workspace_id, &headers, ScopeNotFound::Node).await?;
    let node = service(&state)
        .get_node(&context, node_id.as_str())
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::Node))?;
    Ok(Json(node))
}

async fn update_node(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> TopologyResult<Json<PublicWorkspaceTopologyNode>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = topology_context(&state, workspace_id, &headers, ScopeNotFound::Node).await?;
    let fields = parse_update_node(&request)?;
    let outcome = service(&state)
        .update_node(&context, node_id.as_str(), &fields)
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::Node))?;
    Ok(Json(outcome.value))
}

async fn delete_node(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TopologyResult<StatusCode> {
    let context = topology_context(&state, workspace_id, &headers, ScopeNotFound::Node).await?;
    let _outcome = service(&state)
        .delete_node(&context, node_id.as_str())
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::Node))?;
    Ok(StatusCode::NO_CONTENT)
}

async fn create_edge(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(workspace_id): Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> TopologyResult<(StatusCode, Json<PublicWorkspaceTopologyEdge>)> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = topology_context(
        &state,
        workspace_id,
        &headers,
        ScopeNotFound::InvalidRequest,
    )
    .await?;
    let input = parse_create_edge(context, &request)?;
    let outcome = service(&state)
        .create_edge(&input)
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::InvalidRequest))?;
    Ok((StatusCode::CREATED, Json(outcome.value)))
}

async fn list_edges(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(workspace_id): Path<String>,
    Query(query): Query<PageQuery>,
    headers: HeaderMap,
) -> TopologyResult<Json<Vec<PublicWorkspaceTopologyEdge>>> {
    let context = topology_context(&state, workspace_id, &headers, ScopeNotFound::Topology).await?;
    let limit = query_integer("limit", query.limit.as_deref(), 2000)?;
    let offset = query_integer("offset", query.offset.as_deref(), 0)?;
    let edges = service(&state)
        .list_edges(&context, limit, offset)
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::Topology))?;
    Ok(Json(edges))
}

async fn get_edge(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, edge_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TopologyResult<Json<PublicWorkspaceTopologyEdge>> {
    let context = topology_context(&state, workspace_id, &headers, ScopeNotFound::Edge).await?;
    let edge = service(&state)
        .get_edge(&context, edge_id.as_str())
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::Edge))?;
    Ok(Json(edge))
}

async fn update_edge(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, edge_id)): Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> TopologyResult<Json<PublicWorkspaceTopologyEdge>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = topology_context(&state, workspace_id, &headers, ScopeNotFound::Edge).await?;
    let fields = parse_update_edge(&request)?;
    let outcome = service(&state)
        .update_edge(&context, edge_id.as_str(), &fields)
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::Edge))?;
    Ok(Json(outcome.value))
}

async fn delete_edge(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, edge_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TopologyResult<StatusCode> {
    let context = topology_context(&state, workspace_id, &headers, ScopeNotFound::Edge).await?;
    let _outcome = service(&state)
        .delete_edge(&context, edge_id.as_str())
        .await
        .map_err(|error| map_topology_error(error, ScopeNotFound::Edge))?;
    Ok(StatusCode::NO_CONTENT)
}

fn service(state: &WorkspaceCoreState) -> PublicWorkspaceTopologyService<'_> {
    PublicWorkspaceTopologyService::new(state.db.as_ref(), state.sql_flavor)
}

async fn topology_context(
    state: &WorkspaceCoreState,
    workspace_id: String,
    headers: &HeaderMap,
    not_found: ScopeNotFound,
) -> TopologyResult<PublicWorkspaceTopologyContext> {
    let caller = caller_from_headers(headers)?;
    let scope = resolve_workspace_scope(state, workspace_id.as_str(), caller.user_id.as_str())
        .await
        .map_err(|error| map_scope_error(error, not_found))?;
    Ok(PublicWorkspaceTopologyContext {
        tenant_id: scope.tenant_id,
        project_id: scope.project_id,
        workspace_id: scope.workspace_id,
        user_id: caller.user_id,
        expected_revision: optional_header(headers, IF_MATCH_HEADER)?
            .map(|value| parse_if_match(value.as_str()))
            .transpose()?,
        idempotency_key: optional_header(headers, IDEMPOTENCY_HEADER)?,
    })
}

fn parse_create_node(
    context: PublicWorkspaceTopologyContext,
    request: &Value,
) -> TopologyResult<PublicCreateTopologyNodeInput> {
    let fields = request_object(request)?;
    reject_extra_fields(
        fields,
        request,
        &[
            "node_type",
            "ref_id",
            "title",
            "position_x",
            "position_y",
            "hex_q",
            "hex_r",
            "status",
            "tags",
            "data",
        ],
    )?;
    Ok(PublicCreateTopologyNodeInput {
        context,
        node_type: required_enum(fields, "node_type", request, NODE_TYPES)?,
        ref_id: optional_string(fields, "ref_id")?,
        title: optional_string(fields, "title")?.unwrap_or_default(),
        position_x: optional_f64(fields, "position_x")?.unwrap_or(0.0),
        position_y: optional_f64(fields, "position_y")?.unwrap_or(0.0),
        hex_q: optional_i64(fields, "hex_q")?,
        hex_r: optional_i64(fields, "hex_r")?,
        status: optional_string(fields, "status")?.unwrap_or_else(|| "active".to_string()),
        tags: optional_array(fields, "tags")?.unwrap_or_else(|| json!([])),
        data: optional_object(fields, "data")?.unwrap_or_else(|| json!({})),
    })
}

fn parse_update_node(request: &Value) -> TopologyResult<PublicUpdateTopologyNodeFields> {
    let fields = request_object(request)?;
    reject_extra_fields(
        fields,
        request,
        &[
            "node_type",
            "ref_id",
            "title",
            "position_x",
            "position_y",
            "hex_q",
            "hex_r",
            "status",
            "tags",
            "data",
        ],
    )?;
    Ok(PublicUpdateTopologyNodeFields {
        node_type: optional_enum(fields, "node_type", NODE_TYPES)?,
        ref_id: optional_string(fields, "ref_id")?,
        title: optional_string(fields, "title")?,
        position_x: optional_f64(fields, "position_x")?,
        position_y: optional_f64(fields, "position_y")?,
        hex_q: optional_i64(fields, "hex_q")?,
        hex_r: optional_i64(fields, "hex_r")?,
        status: optional_string(fields, "status")?,
        tags: optional_array(fields, "tags")?,
        data: optional_object(fields, "data")?,
    })
}

fn parse_create_edge(
    context: PublicWorkspaceTopologyContext,
    request: &Value,
) -> TopologyResult<PublicCreateTopologyEdgeInput> {
    let fields = request_object(request)?;
    reject_extra_fields(
        fields,
        request,
        &[
            "source_node_id",
            "target_node_id",
            "label",
            "direction",
            "auto_created",
            "data",
        ],
    )?;
    Ok(PublicCreateTopologyEdgeInput {
        context,
        source_node_id: required_string(fields, "source_node_id", request)?,
        target_node_id: required_string(fields, "target_node_id", request)?,
        label: optional_string(fields, "label")?,
        direction: optional_string(fields, "direction")?,
        auto_created: optional_bool(fields, "auto_created")?.unwrap_or(false),
        data: optional_object(fields, "data")?.unwrap_or_else(|| json!({})),
    })
}

fn parse_update_edge(request: &Value) -> TopologyResult<PublicUpdateTopologyEdgeFields> {
    let fields = request_object(request)?;
    reject_extra_fields(
        fields,
        request,
        &[
            "source_node_id",
            "target_node_id",
            "label",
            "direction",
            "auto_created",
            "data",
        ],
    )?;
    Ok(PublicUpdateTopologyEdgeFields {
        source_node_id: optional_string(fields, "source_node_id")?,
        target_node_id: optional_string(fields, "target_node_id")?,
        label: optional_string(fields, "label")?,
        direction: optional_string(fields, "direction")?,
        auto_created: optional_bool(fields, "auto_created")?,
        data: optional_object(fields, "data")?,
    })
}

fn parse_if_match(value: &str) -> TopologyResult<u64> {
    let value = value.trim();
    let value = value.strip_prefix("W/").unwrap_or(value);
    let value = value
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or(value);
    value.parse::<u64>().map_err(|_| {
        TopologyHttpError::response(
            StatusCode::BAD_REQUEST,
            "If-Match must contain a non-negative Workspace revision",
        )
    })
}

fn request_object(request: &Value) -> TopologyResult<&Map<String, Value>> {
    request.as_object().ok_or_else(|| {
        body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request.clone(),
            None,
        )
        .into()
    })
}

fn reject_extra_fields(
    fields: &Map<String, Value>,
    _request: &Value,
    allowed: &[&str],
) -> TopologyResult<()> {
    if let Some((field, value)) = fields
        .iter()
        .find(|(field, _)| !allowed.contains(&field.as_str()))
    {
        return Err(ApiError::Validation(json!([{
            "type": "extra_forbidden",
            "loc": ["body", field],
            "msg": "Extra inputs are not permitted",
            "input": value,
        }]))
        .into());
    }
    Ok(())
}

fn required_string(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
) -> TopologyResult<String> {
    let value = fields.get(field).ok_or_else(|| {
        body_validation_error(
            "missing",
            Some(field),
            "Field required",
            request.clone(),
            None,
        )
    })?;
    value.as_str().map(str::to_string).ok_or_else(|| {
        body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        )
        .into()
    })
}

fn required_enum(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
    allowed: &[&str],
) -> TopologyResult<String> {
    let value = required_string(fields, field, request)?;
    if !allowed.contains(&value.as_str()) {
        return Err(field_validation_error(
            "enum",
            field,
            "Input should be a valid enum",
            json!(value),
        ));
    }
    Ok(value)
}

fn optional_enum(
    fields: &Map<String, Value>,
    field: &'static str,
    allowed: &[&str],
) -> TopologyResult<Option<String>> {
    let value = optional_string(fields, field)?;
    if value
        .as_ref()
        .is_some_and(|value| !allowed.contains(&value.as_str()))
    {
        return Err(field_validation_error(
            "enum",
            field,
            "Input should be a valid enum",
            fields.get(field).cloned().unwrap_or(Value::Null),
        ));
    }
    Ok(value)
}

fn optional_string(
    fields: &Map<String, Value>,
    field: &'static str,
) -> TopologyResult<Option<String>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(value) => Err(field_validation_error(
            "string_type",
            field,
            "Input should be a valid string",
            value.clone(),
        )),
    }
}

fn optional_bool(fields: &Map<String, Value>, field: &'static str) -> TopologyResult<Option<bool>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Bool(value)) => Ok(Some(*value)),
        Some(value) => Err(field_validation_error(
            "bool_type",
            field,
            "Input should be a valid boolean",
            value.clone(),
        )),
    }
}

fn optional_f64(fields: &Map<String, Value>, field: &'static str) -> TopologyResult<Option<f64>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(value)) => value.as_f64().map(Some).ok_or_else(|| {
            field_validation_error(
                "float_type",
                field,
                "Input should be a valid number",
                Value::Number(value.clone()),
            )
        }),
        Some(value) => Err(field_validation_error(
            "float_type",
            field,
            "Input should be a valid number",
            value.clone(),
        )),
    }
}

fn optional_i64(fields: &Map<String, Value>, field: &'static str) -> TopologyResult<Option<i64>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(value)) => value.as_i64().map(Some).ok_or_else(|| {
            field_validation_error(
                "int_type",
                field,
                "Input should be a valid integer",
                Value::Number(value.clone()),
            )
        }),
        Some(value) => Err(field_validation_error(
            "int_type",
            field,
            "Input should be a valid integer",
            value.clone(),
        )),
    }
}

fn optional_array(
    fields: &Map<String, Value>,
    field: &'static str,
) -> TopologyResult<Option<Value>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(value @ Value::Array(_)) => Ok(Some(value.clone())),
        Some(value) => Err(field_validation_error(
            "list_type",
            field,
            "Input should be a valid list",
            value.clone(),
        )),
    }
}

fn optional_object(
    fields: &Map<String, Value>,
    field: &'static str,
) -> TopologyResult<Option<Value>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(value @ Value::Object(_)) => Ok(Some(value.clone())),
        Some(value) => Err(field_validation_error(
            "dict_type",
            field,
            "Input should be a valid dictionary",
            value.clone(),
        )),
    }
}

fn field_validation_error(
    error_type: &'static str,
    field: &'static str,
    message: &str,
    input: Value,
) -> TopologyHttpError {
    body_validation_error(error_type, Some(field), message, input, None).into()
}

fn query_integer(field: &'static str, raw: Option<&str>, default: i64) -> TopologyResult<i64> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    raw.parse::<i64>().map_err(|_| {
        ApiError::Validation(json!([{
            "type": "int_parsing",
            "loc": ["query", field],
            "msg": "Input should be a valid integer, unable to parse string as an integer",
            "input": raw,
        }]))
        .into()
    })
}

fn map_scope_error(error: WorkspaceScopeError, not_found: ScopeNotFound) -> TopologyHttpError {
    match error {
        WorkspaceScopeError::NotFound => not_found_error(not_found),
        WorkspaceScopeError::AccessRequired => {
            TopologyHttpError::response(StatusCode::FORBIDDEN, "User must be a workspace member")
        }
        WorkspaceScopeError::InvalidRecord(_) | WorkspaceScopeError::Database(_) => {
            ApiError::InvalidDatabase(error.to_string()).into()
        }
    }
}

fn map_topology_error(
    error: PublicWorkspaceTopologyError,
    not_found: ScopeNotFound,
) -> TopologyHttpError {
    match &error {
        PublicWorkspaceTopologyError::WorkspaceNotFound => return not_found_error(not_found),
        PublicWorkspaceTopologyError::NodeNotFound => {
            return TopologyHttpError::response(StatusCode::NOT_FOUND, "Topology node not found");
        }
        PublicWorkspaceTopologyError::EdgeNotFound => {
            return TopologyHttpError::response(StatusCode::NOT_FOUND, "Topology edge not found");
        }
        PublicWorkspaceTopologyError::MembershipRequired => {
            return TopologyHttpError::response(
                StatusCode::FORBIDDEN,
                "User must be a workspace member",
            );
        }
        PublicWorkspaceTopologyError::Forbidden => {
            return TopologyHttpError::response(StatusCode::FORBIDDEN, "Access denied");
        }
        PublicWorkspaceTopologyError::EndpointScope => {
            return TopologyHttpError::response(
                StatusCode::BAD_REQUEST,
                "Edge endpoints must exist in same workspace",
            );
        }
        _ => {}
    }
    match error.kind() {
        PublicWorkspaceTopologyErrorKind::InvalidRequest => {
            TopologyHttpError::response(StatusCode::BAD_REQUEST, "Invalid topology request")
        }
        PublicWorkspaceTopologyErrorKind::NotFound => not_found_error(not_found),
        PublicWorkspaceTopologyErrorKind::Forbidden => {
            TopologyHttpError::response(StatusCode::FORBIDDEN, "Access denied")
        }
        PublicWorkspaceTopologyErrorKind::Conflict => TopologyHttpError::response(
            StatusCode::CONFLICT,
            "Workspace topology authority conflict",
        ),
        PublicWorkspaceTopologyErrorKind::Unavailable => {
            ApiError::InvalidDatabase(error.to_string()).into()
        }
    }
}

fn not_found_error(not_found: ScopeNotFound) -> TopologyHttpError {
    match not_found {
        ScopeNotFound::InvalidRequest => {
            TopologyHttpError::response(StatusCode::BAD_REQUEST, "Invalid topology request")
        }
        ScopeNotFound::Topology => {
            TopologyHttpError::response(StatusCode::NOT_FOUND, "Topology not found")
        }
        ScopeNotFound::Node => {
            TopologyHttpError::response(StatusCode::NOT_FOUND, "Topology node not found")
        }
        ScopeNotFound::Edge => {
            TopologyHttpError::response(StatusCode::NOT_FOUND, "Topology edge not found")
        }
    }
}

type TopologyResult<T> = Result<T, TopologyHttpError>;

#[derive(Debug)]
enum TopologyHttpError {
    Core(ApiError),
    Response(StatusCode, String),
}

impl TopologyHttpError {
    fn response(status: StatusCode, detail: impl Into<String>) -> Self {
        Self::Response(status, detail.into())
    }
}

impl From<ApiError> for TopologyHttpError {
    fn from(error: ApiError) -> Self {
        Self::Core(error)
    }
}

impl IntoResponse for TopologyHttpError {
    fn into_response(self) -> Response {
        match self {
            Self::Core(error) => error.into_response(),
            Self::Response(status, detail) => {
                (status, Json(json!({"detail": detail}))).into_response()
            }
        }
    }
}
