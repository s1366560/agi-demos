use super::*;

pub(super) fn websocket_upgrade_with_auth_protocol(
    ws: WebSocketUpgrade,
    headers: &HeaderMap,
) -> WebSocketUpgrade {
    match select_websocket_auth_subprotocol(headers) {
        Some(protocol) => ws.protocols([protocol]),
        None => ws,
    }
}

pub(super) fn websocket_upgrade_with_desktop_protocol(ws: WebSocketUpgrade) -> WebSocketUpgrade {
    ws.protocols([DESKTOP_WEBSOCKET_SUBPROTOCOL])
}

pub(super) async fn close_http_service_ws_with_policy_error(
    mut socket: WebSocket,
    reason: &'static str,
) {
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1008,
            reason: reason.into(),
        })))
        .await;
}

pub(super) async fn close_http_service_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(
            json!({ "error": "HTTP service WebSocket proxy failed" }).to_string(),
        ))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "HTTP service WS proxy failure".into(),
        })))
        .await;
}

pub(super) async fn close_desktop_ws_with_policy_error(
    mut socket: WebSocket,
    reason: &'static str,
) {
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1008,
            reason: reason.into(),
        })))
        .await;
}

pub(super) async fn close_desktop_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(
            json!({ "error": "Desktop WebSocket proxy failed" }).to_string(),
        ))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "Desktop WS proxy failure".into(),
        })))
        .await;
}

pub(super) async fn close_terminal_ws_with_policy_error(
    mut socket: WebSocket,
    reason: &'static str,
) {
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1008,
            reason: reason.into(),
        })))
        .await;
}

pub(super) async fn close_terminal_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(terminal_error_message()))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "Terminal WebSocket proxy failure".into(),
        })))
        .await;
}

pub(super) async fn close_mcp_ws_with_policy_error(mut socket: WebSocket, reason: &'static str) {
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1008,
            reason: reason.into(),
        })))
        .await;
}

pub(super) async fn close_mcp_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(
            json!({ "error": "MCP WebSocket proxy failed" }).to_string(),
        ))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "MCP WebSocket proxy failure".into(),
        })))
        .await;
}

pub(super) async fn close_http_preview_host_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(
            json!({ "error": "HTTP preview host WS proxy failed" }).to_string(),
        ))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "HTTP preview host WS proxy failure".into(),
        })))
        .await;
}

pub(super) async fn proxy_project_desktop_ws_impl(
    app: AppState,
    identity: Identity,
    project_id: String,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let Some(info) = app.sandboxes.get(&project_id).await? else {
        return Ok(websocket_upgrade_with_desktop_protocol(ws)
            .on_upgrade(|socket| close_desktop_ws_with_policy_error(socket, SANDBOX_NOT_FOUND))
            .into_response());
    };
    let Some(desktop_url) = info.desktop_url.as_deref() else {
        return Ok(websocket_upgrade_with_desktop_protocol(ws)
            .on_upgrade(|socket| {
                close_desktop_ws_with_policy_error(socket, DESKTOP_SERVICE_NOT_RUNNING)
            })
            .into_response());
    };
    let Some(runtime_auth_token) = info.runtime_auth_token.as_ref() else {
        return Ok(websocket_upgrade_with_desktop_protocol(ws)
            .on_upgrade(|socket| {
                close_desktop_ws_with_policy_error(
                    socket,
                    "Sandbox runtime authentication is unavailable",
                )
            })
            .into_response());
    };
    let auth_header = sandbox_basic_auth_header(runtime_auth_token)?;
    let ws_target = match build_desktop_websocket_target(desktop_url) {
        Ok(ws_target) => ws_target,
        Err(_) => {
            return Ok(websocket_upgrade_with_desktop_protocol(ws)
                .on_upgrade(close_desktop_ws_with_internal_error)
                .into_response());
        }
    };
    let origin = desktop_websocket_origin(desktop_url, &ws_target);
    Ok(websocket_upgrade_with_desktop_protocol(ws)
        .on_upgrade(move |socket| proxy_desktop_ws_session(socket, ws_target, origin, auth_header))
        .into_response())
}

pub(super) async fn proxy_project_desktop_websockify(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_desktop_ws_impl(app, identity, project_id, ws).await
}

pub(super) async fn proxy_project_terminal_ws_impl(
    app: AppState,
    identity: Identity,
    project_id: String,
    query: TerminalWsQuery,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let Some(info) = app.sandboxes.get(&project_id).await? else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| close_terminal_ws_with_policy_error(socket, SANDBOX_NOT_FOUND))
            .into_response());
    };
    let Some(terminal_url) = info.terminal_url.as_deref() else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| {
                close_terminal_ws_with_policy_error(socket, TERMINAL_SERVICE_NOT_RUNNING)
            })
            .into_response());
    };
    let Some(runtime_auth_token) = info.runtime_auth_token.as_ref() else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| {
                close_terminal_ws_with_policy_error(
                    socket,
                    "Sandbox runtime authentication is unavailable",
                )
            })
            .into_response());
    };
    let auth_header = sandbox_basic_auth_header(runtime_auth_token)?;
    let ws_target = match build_terminal_websocket_target(terminal_url) {
        Ok(ws_target) => ws_target,
        Err(_) => {
            return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
                .on_upgrade(close_terminal_ws_with_internal_error)
                .into_response());
        }
    };
    let origin = terminal_websocket_origin(terminal_url, &ws_target);
    let session_id = match query.session_id {
        Some(session_id) => session_id,
        None => try_new_terminal_session_id()?,
    };
    let initial_size = app
        .sandboxes
        .get_terminal_session(&project_id, &session_id)
        .await?
        .map(|session| session.size())
        .unwrap_or_default();
    let recorder = app
        .sandboxes
        .terminal_session_recorder(project_id, session_id.clone());
    Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
        .on_upgrade(move |socket| {
            proxy_terminal_ws_session(
                socket,
                ws_target,
                origin,
                session_id,
                initial_size,
                recorder,
                auth_header,
            )
        })
        .into_response())
}

pub(super) async fn proxy_project_terminal_websocket(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<TerminalWsQuery>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_terminal_ws_impl(app, identity, project_id, query, headers, ws).await
}

pub(super) async fn proxy_project_mcp_ws_impl(
    app: AppState,
    identity: Identity,
    project_id: String,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let Some(info) = app.sandboxes.get(&project_id).await? else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| close_mcp_ws_with_policy_error(socket, SANDBOX_NOT_FOUND))
            .into_response());
    };
    let Some(mcp_url) = info.websocket_url.as_deref().or(info.endpoint.as_deref()) else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| close_mcp_ws_with_policy_error(socket, MCP_SERVICE_NOT_RUNNING))
            .into_response());
    };
    let (ws_target, auth_header) = match build_mcp_websocket_target(mcp_url) {
        Ok(target) if info.is_local() => {
            let token = app
                .sandboxes
                .create_mcp_upstream_token(&project_id, &info.sandbox_id)
                .await?;
            (append_mcp_upstream_token(&target, &token.token)?, None)
        }
        Ok(target) => {
            let runtime_auth_token = info.runtime_auth_token.as_ref().ok_or_else(|| {
                SandboxApiError::service_unavailable(
                    "Sandbox runtime authentication is unavailable",
                )
            })?;
            (
                target,
                Some(sandbox_bearer_auth_header(runtime_auth_token)?),
            )
        }
        Err(_) => {
            return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
                .on_upgrade(close_mcp_ws_with_internal_error)
                .into_response());
        }
    };
    Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
        .on_upgrade(move |socket| proxy_mcp_ws_session(socket, ws_target, auth_header))
        .into_response())
}

pub(super) async fn proxy_project_mcp_websocket(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_mcp_ws_impl(app, identity, project_id, headers, ws).await
}

pub(super) struct HttpServiceWsRouteRequest {
    app: AppState,
    identity: Identity,
    project_id: String,
    service_id: String,
    path: String,
    raw_query: Option<String>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
}

pub(super) async fn proxy_project_http_service_ws_impl(
    input: HttpServiceWsRouteRequest,
) -> SandboxApiResult<Response> {
    let HttpServiceWsRouteRequest {
        app,
        identity,
        project_id,
        service_id,
        path,
        raw_query,
        headers,
        ws,
    } = input;
    ensure_project_access(&app, &identity, &project_id).await?;
    let Some(service_info) = app
        .sandboxes
        .get_http_service(&project_id, &service_id)
        .await?
    else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(socket, "HTTP service not found")
            })
            .into_response());
    };
    if service_info.source_type != HttpServiceSourceType::SandboxInternal {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(
                    socket,
                    "WebSocket proxy is only available for sandbox_internal services",
                )
            })
            .into_response());
    }

    let ws_target = build_upstream_ws_url(&service_info.service_url, &path, raw_query.as_deref())?;
    let origin = service_info.service_url;
    Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
        .on_upgrade(move |socket| proxy_http_service_ws_session(socket, ws_target, origin))
        .into_response())
}

pub(super) async fn proxy_project_http_service_ws_root(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, service_id)): Path<(String, String)>,
    RawQuery(raw_query): RawQuery,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_http_service_ws_impl(HttpServiceWsRouteRequest {
        app,
        identity,
        project_id,
        service_id,
        path: String::new(),
        raw_query,
        headers,
        ws,
    })
    .await
}

pub(super) async fn proxy_project_http_service_ws_path(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, service_id, path)): Path<(String, String, String)>,
    RawQuery(raw_query): RawQuery,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_http_service_ws_impl(HttpServiceWsRouteRequest {
        app,
        identity,
        project_id,
        service_id,
        path,
        raw_query,
        headers,
        ws,
    })
    .await
}
