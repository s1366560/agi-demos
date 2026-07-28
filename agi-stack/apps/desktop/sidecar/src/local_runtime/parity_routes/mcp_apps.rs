use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Instant;

use axum::{
    extract::{Extension, Path, Query, State},
    http::{HeaderMap, StatusCode},
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};

use super::super::*;
use crate::local_runtime::mcp_supervisor::{
    McpAppDefinition, McpScope, McpServerDefinition, McpServerDefinitionInput, McpSupervisorError,
    McpTransport,
};

const CONTRACT_VERSION: &str = "desktop-local-mcp-v2";

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route("/api/v1/mcp", get(list_servers).post(create_server))
        .route("/api/v1/mcp/create", post(create_server))
        .route("/api/v1/mcp/capabilities", get(capabilities))
        .route("/api/v1/mcp/tools/all", get(list_all_tools))
        .route("/api/v1/mcp/tools/call", post(call_tool_by_server_id))
        .route("/api/v1/mcp/reconcile/:project_id", post(reconcile_project))
        .route("/api/v1/mcp/:server_id", get(get_server))
        .route("/api/v1/mcp/:server_id/sync", post(sync_server))
        .route("/api/v1/mcp/:server_id/test", post(test_server))
        .route("/api/v1/mcp/:server_id/health", get(server_health))
        .route("/api/v1/mcp/apps", get(list_apps))
        .route("/api/v1/mcp/apps/:app_id/tool-call", post(call_app_tool))
        .route("/api/v1/mcp/apps/proxy/tool-call", post(call_direct_tool))
        .route("/api/v1/mcp/apps/resources/read", post(read_resource))
        .route("/api/v1/mcp/apps/resources/list", post(list_resources))
}

async fn capabilities(
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ProjectQuery>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, query.project_id.as_deref())?;
    Ok(Json(json!({
        "contract_version": CONTRACT_VERSION,
        "mode": "local",
        "capability": "mcp_apps",
        "availability": "available",
        "reason_code": null,
        "transports": {
            "stdio": {
                "availability": "available",
                "protocol_negotiation": {
                    "offered": ["2024-11-05"],
                    "accepted": ["2024-11-05"],
                },
                "reason_code": null,
            },
            "http": {
                "availability": "available",
                "protocol_negotiation": {
                    "offered": ["2025-03-26"],
                    "accepted": ["2025-03-26"],
                },
                "reason_code": null,
            },
            "sse": {
                "availability": "available",
                "protocol_negotiation": {
                    "offered": ["2024-11-05"],
                    "accepted": ["2024-11-05"],
                },
                "reason_code": null,
            },
            "websocket": {
                "availability": "available",
                "protocol_negotiation": {
                    "offered": ["2025-03-26"],
                    "accepted": ["2025-03-26", "2024-11-05"],
                },
                "reason_code": null,
            },
        },
        "elicitation": {
            "availability": "unavailable",
            "reason_code": "local_mcp_elicitation_bridge_unavailable",
        },
        "credential_authority": "application_vault",
        "redirect_policy": "deny",
    })))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectQuery {
    project_id: Option<String>,
    include_disabled: Option<bool>,
    enabled_only: Option<bool>,
    skip: Option<usize>,
    limit: Option<usize>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CreateServerBody {
    name: String,
    description: Option<String>,
    server_type: McpTransport,
    transport_config: TransportConfigBody,
    #[serde(default = "default_enabled")]
    enabled: bool,
    project_id: String,
    idempotency_key: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TransportConfigBody {
    command: Option<Value>,
    #[serde(default)]
    args: Vec<String>,
    cwd: Option<String>,
    #[serde(default)]
    vault_env_refs: BTreeMap<String, String>,
    #[serde(default)]
    vault_header_refs: BTreeMap<String, String>,
    environment: Option<Value>,
    env: Option<Value>,
    url: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AppToolBody {
    tool_name: String,
    #[serde(default = "empty_object")]
    arguments: Value,
    idempotency_key: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DirectToolBody {
    project_id: String,
    server_name: String,
    tool_name: String,
    #[serde(default = "empty_object")]
    arguments: Value,
    idempotency_key: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ServerToolBody {
    server_id: String,
    tool_name: String,
    #[serde(default = "empty_object")]
    arguments: Value,
    idempotency_key: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceListBody {
    project_id: String,
    server_name: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceReadBody {
    project_id: String,
    server_name: Option<String>,
    uri: String,
}

async fn create_server(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    Json(body): Json<CreateServerBody>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, Some(&body.project_id))?;
    ensure_managed_resource_manager(&authenticated)?;
    if body.transport_config.environment.is_some() || body.transport_config.env.is_some() {
        return mcp_error(McpSupervisorError::new(
            "local_mcp_plaintext_environment_rejected",
            "MCP environment values must use application-vault references",
        ));
    }
    let idempotency_key = body
        .idempotency_key
        .clone()
        .or_else(|| header_text(&headers, "idempotency-key").map(ToString::to_string))
        .ok_or_else(|| {
            mcp_error_tuple(
                StatusCode::UNPROCESSABLE_ENTITY,
                "local_mcp_idempotency_key_required",
                "MCP server mutations require an idempotency key",
            )
        })?;
    let input = definition_input(body)?;
    let scope = active_scope(&authenticated);
    let server = state
        .mcp_supervisor
        .create_server(&scope, input, &idempotency_key)
        .map_err(mcp_error_tuple_for)?;
    Ok(Json(server_response(&server)))
}

async fn list_servers(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ProjectQuery>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, query.project_id.as_deref())?;
    let enabled_only = query.enabled_only.unwrap_or(false);
    let skip = query.skip.unwrap_or(0);
    let limit = query.limit.unwrap_or(200).clamp(1, 500);
    let values = state
        .mcp_supervisor
        .list_servers(&active_scope(&authenticated))
        .map_err(mcp_error_tuple_for)?
        .into_iter()
        .filter(|server| !enabled_only || server.enabled)
        .skip(skip)
        .take(limit)
        .map(|server| server_response(&server))
        .collect();
    Ok(Json(Value::Array(values)))
}

async fn get_server(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(server_id): Path<String>,
) -> LocalJsonResult {
    let server = state
        .mcp_supervisor
        .server(&active_scope(&authenticated), &server_id)
        .map_err(mcp_error_tuple_for)?
        .ok_or_else(|| {
            mcp_error_tuple(
                StatusCode::NOT_FOUND,
                "local_mcp_server_not_found",
                "MCP server was not found",
            )
        })?;
    Ok(Json(server_response(&server)))
}

async fn sync_server(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(server_id): Path<String>,
) -> LocalJsonResult {
    let scope = active_scope(&authenticated);
    state
        .mcp_supervisor
        .list_tools(&scope, &server_id)
        .await
        .map_err(mcp_error_tuple_for)?;
    let server = state
        .mcp_supervisor
        .server(&scope, &server_id)
        .map_err(mcp_error_tuple_for)?
        .ok_or_else(|| {
            mcp_error_tuple(
                StatusCode::NOT_FOUND,
                "local_mcp_server_not_found",
                "MCP server was not found",
            )
        })?;
    Ok(Json(server_response(&server)))
}

async fn test_server(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(server_id): Path<String>,
) -> LocalJsonResult {
    let started = Instant::now();
    let tools = state
        .mcp_supervisor
        .list_tools(&active_scope(&authenticated), &server_id)
        .await
        .map_err(mcp_error_tuple_for)?;
    Ok(Json(json!({
        "success": true,
        "message": "MCP handshake succeeded",
        "tools_discovered": tools.len(),
        "connection_time_ms": started.elapsed().as_secs_f64() * 1_000.0,
        "errors": [],
    })))
}

async fn server_health(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(server_id): Path<String>,
) -> LocalJsonResult {
    state
        .mcp_supervisor
        .health(&active_scope(&authenticated), &server_id)
        .map(|health| Json(serde_json::to_value(health).expect("serialize MCP health")))
        .map_err(mcp_error_tuple_for)
}

async fn reconcile_project(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, Some(&project_id))?;
    let scope = active_scope(&authenticated);
    let servers = state
        .mcp_supervisor
        .list_servers(&scope)
        .map_err(mcp_error_tuple_for)?;
    state
        .mcp_supervisor
        .recover_enabled(&scope)
        .await
        .map_err(mcp_error_tuple_for)?;
    let enabled = servers.iter().filter(|server| server.enabled).count();
    let healthy = state
        .mcp_supervisor
        .list_servers(&scope)
        .map_err(mcp_error_tuple_for)?
        .iter()
        .filter(|server| server.runtime_status == "healthy")
        .count();
    Ok(Json(json!({
        "project_id": project_id,
        "total_enabled_servers": enabled,
        "already_running": 0,
        "restored": healthy,
        "failed": enabled.saturating_sub(healthy),
    })))
}

async fn list_all_tools(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ProjectQuery>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, query.project_id.as_deref())?;
    let mut items = Vec::new();
    for server in state
        .mcp_supervisor
        .list_servers(&active_scope(&authenticated))
        .map_err(mcp_error_tuple_for)?
        .into_iter()
        .filter(|server| server.enabled)
    {
        for tool in server.discovered_tools {
            items.push(json!({
                "name": tool.get("name").and_then(Value::as_str).unwrap_or_default(),
                "description": tool.get("description"),
                "server_id": server.id,
                "server_name": server.name,
                "input_schema": tool.get("inputSchema").cloned().unwrap_or_else(|| json!({})),
            }));
        }
    }
    Ok(Json(json!({
        "items": items,
        "total": items.len(),
        "page": 1,
        "per_page": items.len().max(1),
        "total_pages": 1,
    })))
}

async fn call_tool_by_server_id(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<ServerToolBody>,
) -> LocalJsonResult {
    let started = Instant::now();
    let outcome = state
        .mcp_supervisor
        .call_tool(
            &active_scope(&authenticated),
            &body.server_id,
            &body.tool_name,
            body.arguments,
            body.idempotency_key.as_deref(),
        )
        .await
        .map_err(mcp_error_tuple_for)?;
    Ok(Json(json!({
        "result": outcome.result,
        "is_error": outcome.is_error,
        "error_message": null,
        "execution_time_ms": started.elapsed().as_secs_f64() * 1_000.0,
        "duplicate": outcome.duplicate,
    })))
}

async fn list_apps(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ProjectQuery>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, query.project_id.as_deref())?;
    let include_disabled = query.include_disabled.unwrap_or(false);
    let apps = state
        .mcp_supervisor
        .list_apps(&active_scope(&authenticated))
        .map_err(mcp_error_tuple_for)?
        .into_iter()
        .filter(|app| include_disabled || app.status == "healthy")
        .map(|app| app_response(&app))
        .collect();
    Ok(Json(Value::Array(apps)))
}

async fn call_app_tool(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(app_id): Path<String>,
    Json(body): Json<AppToolBody>,
) -> LocalJsonResult {
    let scope = active_scope(&authenticated);
    let app = state
        .mcp_supervisor
        .app(&scope, &app_id)
        .map_err(mcp_error_tuple_for)?
        .ok_or_else(|| {
            mcp_error_tuple(
                StatusCode::NOT_FOUND,
                "local_mcp_app_not_found",
                "MCP App was not found",
            )
        })?;
    if body.tool_name != app.tool_name {
        return Err(mcp_error_tuple(
            StatusCode::UNPROCESSABLE_ENTITY,
            "local_mcp_app_tool_not_allowed",
            "MCP App tool does not match its persisted visibility definition",
        ));
    }
    tool_call_response(
        &state,
        &scope,
        &app.server_id,
        &body.tool_name,
        body.arguments,
        body.idempotency_key.as_deref(),
    )
    .await
}

async fn call_direct_tool(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<DirectToolBody>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, Some(&body.project_id))?;
    let scope = active_scope(&authenticated);
    let server = state
        .mcp_supervisor
        .server_by_name(&scope, &body.server_name)
        .map_err(mcp_error_tuple_for)?
        .ok_or_else(|| {
            mcp_error_tuple(
                StatusCode::NOT_FOUND,
                "local_mcp_server_not_found",
                "MCP server was not found",
            )
        })?;
    tool_call_response(
        &state,
        &scope,
        &server.id,
        &body.tool_name,
        body.arguments,
        body.idempotency_key.as_deref(),
    )
    .await
}

async fn tool_call_response(
    state: &LocalRuntimeState,
    scope: &McpScope,
    server_id: &str,
    tool_name: &str,
    arguments: Value,
    idempotency_key: Option<&str>,
) -> LocalJsonResult {
    let outcome = state
        .mcp_supervisor
        .call_tool(scope, server_id, tool_name, arguments, idempotency_key)
        .await
        .map_err(mcp_error_tuple_for)?;
    Ok(Json(json!({
        "content": outcome.content,
        "is_error": outcome.is_error,
        "error_message": null,
        "error_code": null,
        "duplicate": outcome.duplicate,
    })))
}

async fn list_resources(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<ResourceListBody>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, Some(&body.project_id))?;
    let scope = active_scope(&authenticated);
    let server_id = server_id_from_name(&state, &scope, body.server_name.as_deref())?;
    state
        .mcp_supervisor
        .list_resources(&scope, server_id.as_deref())
        .await
        .map(|resources| Json(json!({ "resources": resources })))
        .map_err(mcp_error_tuple_for)
}

async fn read_resource(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<ResourceReadBody>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, Some(&body.project_id))?;
    let scope = active_scope(&authenticated);
    let server_name = body
        .server_name
        .or_else(|| server_name_from_resource_uri(&body.uri));
    let server_id =
        server_id_from_name(&state, &scope, server_name.as_deref())?.ok_or_else(|| {
            mcp_error_tuple(
                StatusCode::UNPROCESSABLE_ENTITY,
                "local_mcp_server_name_required",
                "MCP resource read requires an explicit or ui:// server name",
            )
        })?;
    state
        .mcp_supervisor
        .read_resource(&scope, &server_id, &body.uri)
        .await
        .map(|contents| Json(json!({ "contents": contents })))
        .map_err(mcp_error_tuple_for)
}

fn definition_input(
    body: CreateServerBody,
) -> Result<McpServerDefinitionInput, (StatusCode, Json<Value>)> {
    let (command, cwd, vault_refs) = match body.server_type {
        McpTransport::Stdio => {
            if body.transport_config.url.is_some()
                || !body.transport_config.vault_header_refs.is_empty()
            {
                return Err(malformed(
                    "local_mcp_stdio_config_invalid",
                    "MCP stdio transport accepts command argv and environment vault references",
                ));
            }
            (
                direct_command(&body.transport_config)?,
                body.transport_config.cwd,
                body.transport_config.vault_env_refs,
            )
        }
        McpTransport::Http | McpTransport::Sse | McpTransport::Websocket => {
            if body.transport_config.command.is_some()
                || !body.transport_config.args.is_empty()
                || body.transport_config.cwd.is_some()
                || !body.transport_config.vault_env_refs.is_empty()
            {
                return Err(malformed(
                    "local_mcp_remote_config_invalid",
                    "MCP remote transport accepts only a URL and vault header references",
                ));
            }
            (
                vec![body.transport_config.url.ok_or_else(|| {
                    malformed(
                        "local_mcp_endpoint_invalid",
                        "MCP remote transport URL is required",
                    )
                })?],
                None,
                body.transport_config.vault_header_refs,
            )
        }
    };
    Ok(McpServerDefinitionInput {
        name: body.name,
        description: body.description,
        transport: body.server_type,
        command,
        cwd,
        vault_env_refs: vault_refs,
        enabled: body.enabled,
    })
}

fn direct_command(config: &TransportConfigBody) -> Result<Vec<String>, (StatusCode, Json<Value>)> {
    let mut command = match config.command.as_ref() {
        Some(Value::String(command)) => vec![command.clone()],
        Some(Value::Array(command)) => command
            .iter()
            .map(|value| value.as_str().map(ToString::to_string))
            .collect::<Option<Vec<_>>>()
            .ok_or_else(|| malformed("local_mcp_command_invalid", "MCP command argv is invalid"))?,
        _ => {
            return Err(malformed(
                "local_mcp_command_invalid",
                "MCP stdio command is required",
            ))
        }
    };
    command.extend(config.args.iter().cloned());
    Ok(command)
}

fn server_id_from_name(
    state: &LocalRuntimeState,
    scope: &McpScope,
    server_name: Option<&str>,
) -> Result<Option<String>, (StatusCode, Json<Value>)> {
    server_name
        .map(|name| {
            state
                .mcp_supervisor
                .server_by_name(scope, name)
                .map_err(mcp_error_tuple_for)?
                .map(|server| server.id)
                .ok_or_else(|| {
                    mcp_error_tuple(
                        StatusCode::NOT_FOUND,
                        "local_mcp_server_not_found",
                        "MCP server was not found",
                    )
                })
        })
        .transpose()
}

fn server_name_from_resource_uri(uri: &str) -> Option<String> {
    uri.strip_prefix("ui://")
        .and_then(|value| value.split('/').next())
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
}

fn active_scope(authenticated: &AuthenticatedContext) -> McpScope {
    McpScope {
        tenant_id: authenticated.workspace.tenant_id.clone(),
        project_id: authenticated.workspace.project_id.clone(),
    }
}

fn server_response(server: &McpServerDefinition) -> Value {
    let is_stdio = server.transport == McpTransport::Stdio;
    json!({
        "id": server.id,
        "tenant_id": server.tenant_id,
        "project_id": server.project_id,
        "name": server.name,
        "description": server.description,
        "server_type": server.transport,
        "transport_config": {
            "command": if is_stdio { server.command.first() } else { None },
            "url": if is_stdio { None } else { server.command.first() },
            "arguments_redacted": is_stdio && server.command.len() > 1,
            "cwd": server.cwd,
            "vault_env_names": if is_stdio {
                server.vault_env_refs.keys().collect::<Vec<_>>()
            } else {
                Vec::<&String>::new()
            },
            "vault_header_names": if is_stdio {
                Vec::<&String>::new()
            } else {
                server.vault_env_refs.keys().collect::<Vec<_>>()
            },
        },
        "enabled": server.enabled,
        "runtime_status": server.runtime_status,
        "runtime_metadata": {
            "contract_version": CONTRACT_VERSION,
            "reason_code": server.reason_code,
            "revision": server.revision,
            "server_info": server.server_info,
        },
        "discovered_tools": server.discovered_tools,
        "sync_error": server.reason_code,
        "last_sync_at": server.updated_at,
        "created_at": server.created_at,
        "updated_at": server.updated_at,
    })
}

fn app_response(app: &McpAppDefinition) -> Value {
    json!({
        "id": app.id,
        "tenant_id": app.tenant_id,
        "project_id": app.project_id,
        "server_id": app.server_id,
        "server_name": app.server_name,
        "tool_name": app.tool_name,
        "ui_metadata": app.ui_metadata,
        "source": "local_supervisor",
        "status": app.status,
        "lifecycle_metadata": {
            "contract_version": CONTRACT_VERSION,
            "revision": app.revision,
            "resource_uri": app.resource_uri,
        },
        "error_message": null,
        "has_resource": app.resource_uri.is_some(),
        "resource_size_bytes": null,
    })
}

fn mcp_error(error: McpSupervisorError) -> LocalJsonResult {
    Err(mcp_error_tuple_for(error))
}

pub(super) fn mcp_error_tuple_for(error: McpSupervisorError) -> (StatusCode, Json<Value>) {
    let status = match error.reason_code() {
        "local_mcp_server_not_found" | "local_mcp_app_not_found" => StatusCode::NOT_FOUND,
        "local_mcp_idempotency_conflict"
        | "local_mcp_server_name_conflict"
        | "local_mcp_tool_call_in_progress"
        | "local_mcp_tool_call_lease_lost"
        | "local_mcp_tool_call_indeterminate" => StatusCode::CONFLICT,
        "local_mcp_elicitation_bridge_unavailable" | "local_mcp_client_request_unavailable" => {
            StatusCode::NOT_IMPLEMENTED
        }
        "local_mcp_request_timeout" => StatusCode::GATEWAY_TIMEOUT,
        "local_mcp_process_start_failed"
        | "local_mcp_process_exited"
        | "local_mcp_connection_closed"
        | "local_mcp_session_lost"
        | "local_mcp_restart_backoff"
        | "local_mcp_server_disabled"
        | "local_mcp_vault_reference_unavailable" => StatusCode::SERVICE_UNAVAILABLE,
        "local_mcp_malformed_response"
        | "local_mcp_content_type_rejected"
        | "local_mcp_http_status_error"
        | "local_mcp_redirect_rejected"
        | "local_mcp_sse_handshake_failed"
        | "local_mcp_sse_endpoint_missing"
        | "local_mcp_sse_endpoint_rejected"
        | "local_mcp_websocket_handshake_failed"
        | "local_mcp_response_too_large"
        | "local_mcp_response_correlation_failed"
        | "local_mcp_json_rpc_error" => StatusCode::BAD_GATEWAY,
        "local_mcp_storage_unavailable" => StatusCode::INTERNAL_SERVER_ERROR,
        _ => StatusCode::UNPROCESSABLE_ENTITY,
    };
    mcp_error_tuple(status, error.reason_code(), error.detail())
}

fn mcp_error_tuple(
    status: StatusCode,
    reason_code: &'static str,
    detail: &'static str,
) -> (StatusCode, Json<Value>) {
    (
        status,
        Json(json!({
            "contract_version": CONTRACT_VERSION,
            "mode": "local",
            "capability": "mcp_apps",
            "availability": if status == StatusCode::NOT_IMPLEMENTED
                || reason_code == "local_mcp_tool_call_indeterminate"
            {
                "unavailable"
            } else {
                "available"
            },
            "reason_code": reason_code,
            "code": reason_code,
            "detail": detail,
        })),
    )
}

fn malformed(reason_code: &'static str, detail: &'static str) -> (StatusCode, Json<Value>) {
    mcp_error_tuple(StatusCode::UNPROCESSABLE_ENTITY, reason_code, detail)
}

fn header_text<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|value| value.to_str().ok())
}

fn default_enabled() -> bool {
    true
}

fn empty_object() -> Value {
    json!({})
}
