use super::*;

pub(super) async fn ensure_project_access(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> SandboxApiResult<()> {
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await
        .map_err(SandboxApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(SandboxApiError::forbidden("Access denied to project"))
    }
}

pub(super) async fn ensure_project_write(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> SandboxApiResult<()> {
    let allowed = app
        .auth
        .can_write_project(&identity.user_id, project_id)
        .await
        .map_err(SandboxApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(SandboxApiError::forbidden("Access denied to project"))
    }
}

pub(super) async fn ensure_project_admin(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> SandboxApiResult<()> {
    let allowed = app
        .auth
        .can_admin_project(&identity.user_id, project_id)
        .await
        .map_err(SandboxApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(SandboxApiError::forbidden("Access denied to project"))
    }
}

pub(super) async fn project_tenant_id(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> SandboxApiResult<String> {
    app.identity
        .get_project(&identity.user_id, project_id, None)
        .await
        .map(|project| project.tenant_id)
        .map_err(|err| SandboxApiError::new(err.status, err.detail))
}

pub(super) async fn current_tenant_id(
    app: &AppState,
    identity: &Identity,
) -> SandboxApiResult<String> {
    let page = app
        .identity
        .list_tenants(&identity.user_id, None, 1, 1)
        .await
        .map_err(|err| SandboxApiError::new(err.status, err.detail))?;
    page.tenants
        .into_iter()
        .next()
        .map(|tenant| tenant.id)
        .ok_or_else(|| {
            SandboxApiError::bad_request(
                "User does not belong to any tenant. Please contact administrator.",
            )
        })
}

pub(super) async fn list_project_sandboxes(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<ListProjectSandboxesQuery>,
) -> SandboxApiResult<Json<ListProjectSandboxesResponse>> {
    let tenant_id = current_tenant_id(&app, &identity).await?;
    let status = parse_status_filter(query.status.as_deref())?;
    let limit = query.limit.unwrap_or(50).clamp(1, 100);
    let offset = query.offset.unwrap_or(0).max(0);
    let sandboxes = app
        .sandboxes
        .list(&tenant_id, status.as_deref(), limit, offset)
        .await?;
    let sandboxes = sandboxes
        .into_iter()
        .map(ProjectSandboxResponse::from)
        .collect::<Vec<_>>();
    let total = sandboxes.len();
    Ok(Json(ListProjectSandboxesResponse { sandboxes, total }))
}

pub(super) async fn get_project_sandbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<ProjectSandboxResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND_WITH_CREATE_HINT))?;
    Ok(Json(info.into()))
}

pub(super) async fn ensure_project_sandbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(req): Json<EnsureSandboxRequest>,
) -> SandboxApiResult<Json<ProjectSandboxResponse>> {
    ensure_project_write(&app, &identity, &project_id).await?;
    let profile = SandboxProfile::parse(req.profile.as_deref())?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .ensure(&project_id, &tenant_id, profile)
        .await?;
    Ok(Json(info.into()))
}

pub(super) async fn check_project_sandbox_health(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<HealthCheckResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    let healthy = info.healthy();
    let status = info.status_str().to_string();
    Ok(Json(HealthCheckResponse {
        project_id,
        sandbox_id: info.sandbox_id,
        healthy,
        status,
        checked_at: rfc3339(now_ms()),
    }))
}

pub(super) async fn get_project_sandbox_stats(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxStatsResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    let now = now_ms();
    let status = info.status_str().to_string();
    let created_at_ms = info.created_at_ms;
    Ok(Json(SandboxStatsResponse {
        project_id,
        sandbox_id: info.sandbox_id,
        status,
        cpu_percent: 0.0,
        memory_usage: 0,
        memory_limit: 0,
        memory_percent: 0.0,
        disk_usage: None,
        disk_limit: None,
        disk_percent: None,
        network_rx_bytes: None,
        network_tx_bytes: None,
        pids: 0,
        uptime_seconds: Some((now - created_at_ms).max(0) / 1_000),
        created_at: Some(rfc3339(created_at_ms)),
        collected_at: rfc3339(now),
    }))
}

pub(super) async fn execute_project_sandbox_tool(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(req): Json<ExecuteToolRequest>,
) -> SandboxApiResult<Json<ExecuteToolResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let result = app
        .sandboxes
        .execute_tool(&project_id, &req.tool_name, &req.arguments, req.timeout)
        .await
        .map_err(|err| {
            if err.status == StatusCode::BAD_REQUEST {
                err
            } else {
                SandboxApiError::internal("Execution failed")
            }
        })?;
    Ok(Json(result))
}

pub(super) async fn seed_project_sandbox_proxy_auth_cookie(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Extension(raw_key): Extension<RawApiKey>,
    headers: HeaderMap,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let cookie =
        sandbox_proxy_auth_cookie(&project_id, &raw_key.0, proxy_auth_cookie_secure(&headers))?;
    let mut response = Json(SandboxProxyAuthCookieResponse {
        success: true,
        expires_in_seconds: SANDBOX_PROXY_AUTH_COOKIE_MAX_AGE_SECONDS,
    })
    .into_response();
    response.headers_mut().append(SET_COOKIE, cookie);
    Ok(response)
}

pub(super) async fn start_project_desktop(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<StartDesktopQuery>,
) -> SandboxApiResult<Json<DesktopServiceResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id).await?;
    let info = app.sandboxes.ensure(&project_id, &tenant_id, None).await?;
    Ok(Json(DesktopServiceResponse::from_info(
        &info,
        query
            .resolution
            .unwrap_or_else(|| DESKTOP_DEFAULT_RESOLUTION.to_string()),
    )))
}

pub(super) async fn stop_project_desktop(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxServiceStopResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    app.sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    Ok(Json(SandboxServiceStopResponse { success: true }))
}

pub(super) async fn start_project_terminal(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<TerminalServiceResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id).await?;
    let info = app.sandboxes.ensure(&project_id, &tenant_id, None).await?;
    let session = app.sandboxes.create_terminal_session(&project_id).await?;
    Ok(Json(TerminalServiceResponse::from_info_with_session(
        &info,
        Some(session.session_id),
    )))
}

pub(super) async fn stop_project_terminal(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxServiceStopResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    app.sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    Ok(Json(SandboxServiceStopResponse { success: true }))
}

pub(super) async fn proxy_project_desktop_impl(
    app: AppState,
    identity: Identity,
    project_id: String,
    path: String,
    raw_query: Option<String>,
    headers: HeaderMap,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    let secure_cookie = proxy_auth_cookie_secure(&headers);
    proxy_project_desktop_response(
        &project_id,
        &info,
        &path,
        raw_query.as_deref(),
        headers,
        secure_cookie,
    )
    .await
}

pub(super) async fn proxy_project_desktop_root(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    RawQuery(raw_query): RawQuery,
    headers: HeaderMap,
) -> SandboxApiResult<Response> {
    proxy_project_desktop_impl(app, identity, project_id, String::new(), raw_query, headers).await
}

pub(super) async fn proxy_project_desktop_path(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, path)): Path<(String, String)>,
    RawQuery(raw_query): RawQuery,
    headers: HeaderMap,
) -> SandboxApiResult<Response> {
    proxy_project_desktop_impl(app, identity, project_id, path, raw_query, headers).await
}

pub(super) async fn register_project_http_service(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(req): Json<RegisterHttpServiceRequest>,
) -> SandboxApiResult<Json<HttpServiceResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id).await?;
    let service = app
        .sandboxes
        .register_http_service(&project_id, &tenant_id, req)
        .await?;
    Ok(Json(service.into()))
}

pub(super) async fn list_project_http_services(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<ListHttpServicesResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let services = app
        .sandboxes
        .list_http_services(&project_id)
        .await?
        .into_iter()
        .map(HttpServiceResponse::from)
        .collect::<Vec<_>>();
    let total = services.len();
    Ok(Json(ListHttpServicesResponse { services, total }))
}

pub(super) async fn create_project_http_service_preview_session(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, service_id)): Path<(String, String)>,
) -> SandboxApiResult<Json<HttpServicePreviewSessionResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    Ok(Json(
        app.sandboxes
            .preview_session(&project_id, &service_id)
            .await?,
    ))
}

pub(super) async fn stop_project_http_service(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, service_id)): Path<(String, String)>,
) -> SandboxApiResult<Json<HttpServiceActionResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let mut removed = app
        .sandboxes
        .remove_http_service(&project_id, &service_id)
        .await?
        .ok_or_else(http_service_not_found)?;
    removed.status = "stopped".to_string();
    removed.updated_at = python_utc_offset_string(now_ms());
    Ok(Json(HttpServiceActionResponse {
        success: true,
        message: format!("HTTP service {service_id} stopped"),
        service: Some(removed.into()),
    }))
}

pub(super) struct HttpServiceRouteRequest {
    app: AppState,
    identity: Identity,
    raw_key: RawApiKey,
    project_id: String,
    service_id: String,
    path: String,
    raw_query: Option<String>,
    req: Request<Body>,
}

pub(super) async fn proxy_project_http_service_impl(
    input: HttpServiceRouteRequest,
) -> SandboxApiResult<Response> {
    let HttpServiceRouteRequest {
        app,
        identity,
        raw_key,
        project_id,
        service_id,
        path,
        raw_query,
        req,
    } = input;
    ensure_project_access(&app, &identity, &project_id).await?;
    let service_info = app
        .sandboxes
        .get_http_service(&project_id, &service_id)
        .await?
        .ok_or_else(http_service_not_found)?;
    let method = req.method().clone();
    let headers = req.headers().clone();
    let secure_cookie = proxy_auth_cookie_secure(&headers);
    let body = to_bytes(req.into_body(), HTTP_PROXY_BODY_LIMIT_BYTES)
        .await
        .map_err(|_| SandboxApiError::bad_request("Request body too large"))?
        .to_vec();
    proxy_http_service_response(HttpServiceProxyResponseInput {
        project_id: &project_id,
        service_id: &service_id,
        service_info: &service_info,
        path: &path,
        raw_query: raw_query.as_deref(),
        method,
        request_headers: headers,
        request_body: body,
        raw_key: &raw_key.0,
        secure_cookie,
    })
    .await
}

pub(super) async fn proxy_project_http_service_root(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Extension(raw_key): Extension<RawApiKey>,
    Path((project_id, service_id)): Path<(String, String)>,
    RawQuery(raw_query): RawQuery,
    req: Request<Body>,
) -> SandboxApiResult<Response> {
    proxy_project_http_service_impl(HttpServiceRouteRequest {
        app,
        identity,
        raw_key,
        project_id,
        service_id,
        path: String::new(),
        raw_query,
        req,
    })
    .await
}

pub(super) async fn proxy_project_http_service_path(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Extension(raw_key): Extension<RawApiKey>,
    Path((project_id, service_id, path)): Path<(String, String, String)>,
    RawQuery(raw_query): RawQuery,
    req: Request<Body>,
) -> SandboxApiResult<Response> {
    proxy_project_http_service_impl(HttpServiceRouteRequest {
        app,
        identity,
        raw_key,
        project_id,
        service_id,
        path,
        raw_query,
        req,
    })
    .await
}

pub(super) async fn restart_project_sandbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxActionResponse>> {
    ensure_project_admin(&app, &identity, &project_id).await?;
    let info = app.sandboxes.restart(&project_id).await?;
    let sandbox_id = info.sandbox_id.clone();
    Ok(Json(SandboxActionResponse {
        success: true,
        message: format!("Sandbox {sandbox_id} restarted successfully"),
        sandbox: Some(info.into()),
    }))
}

pub(super) async fn terminate_project_sandbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxActionResponse>> {
    ensure_project_admin(&app, &identity, &project_id).await?;
    if !app.sandboxes.terminate(&project_id).await? {
        return Err(SandboxApiError::not_found(SANDBOX_NOT_FOUND));
    }
    Ok(Json(SandboxActionResponse {
        success: true,
        message: "Sandbox terminated successfully".to_string(),
        sandbox: None,
    }))
}

pub(super) async fn sync_project_sandbox_status(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<ProjectSandboxResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND_WITH_CREATE_HINT))?;
    Ok(Json(info.into()))
}
