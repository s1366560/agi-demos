use std::sync::OnceLock;
use std::time::Duration;

use super::*;

fn build_proxy_client(timeout: Duration) -> Result<reqwest::Client, reqwest::Error> {
    reqwest::Client::builder()
        .timeout(timeout)
        .redirect(reqwest::redirect::Policy::none())
        .danger_accept_invalid_certs(true)
        .no_proxy()
        .build()
}

fn desktop_proxy_client() -> SandboxApiResult<&'static reqwest::Client> {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    if let Some(client) = CLIENT.get() {
        return Ok(client);
    }
    let client = build_proxy_client(Duration::from_secs(30))
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to desktop service"))?;
    Ok(CLIENT.get_or_init(|| client))
}

fn http_service_proxy_client() -> SandboxApiResult<&'static reqwest::Client> {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    if let Some(client) = CLIENT.get() {
        return Ok(client);
    }
    let client = build_proxy_client(Duration::from_secs(3))
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;
    Ok(CLIENT.get_or_init(|| client))
}

pub(super) fn desktop_upstream_headers(
    request_headers: &HeaderMap,
    runtime_auth_token: &SandboxRuntimeToken,
) -> SandboxApiResult<HeaderMap> {
    let mut headers = filter_desktop_proxy_headers(request_headers);
    headers.insert(
        AUTHORIZATION,
        sandbox_basic_auth_header(runtime_auth_token)?,
    );
    Ok(headers)
}

pub(super) async fn proxy_project_desktop_response(
    project_id: &str,
    info: &ProjectSandboxInfo,
    path: &str,
    raw_query: Option<&str>,
    request_headers: HeaderMap,
    secure_cookie: bool,
) -> SandboxApiResult<Response> {
    let desktop_url = info.desktop_url.as_deref().ok_or_else(|| {
        SandboxApiError::new(StatusCode::SERVICE_UNAVAILABLE, DESKTOP_SERVICE_NOT_RUNNING)
    })?;
    let runtime_auth_token = info.runtime_auth_token.as_ref().ok_or_else(|| {
        SandboxApiError::service_unavailable("Sandbox runtime authentication is unavailable")
    })?;
    let target_url = build_upstream_desktop_http_url(desktop_url, path, raw_query)?;
    let client = desktop_proxy_client()?;
    let upstream_headers = desktop_upstream_headers(&request_headers, runtime_auth_token)?;
    let upstream = client
        .get(target_url)
        .headers(upstream_headers)
        .send()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to desktop service"))?;

    let status = StatusCode::from_u16(upstream.status().as_u16())
        .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let upstream_headers = upstream.headers().clone();
    let content_type = upstream_headers
        .get(CONTENT_TYPE)
        .cloned()
        .unwrap_or_else(|| HeaderValue::from_static("application/octet-stream"));
    let content_type_str = content_type.to_str().unwrap_or("application/octet-stream");
    let token_param = proxy_token_from_query(raw_query);
    let body = upstream
        .bytes()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to desktop service"))?;
    let body = rewrite_desktop_content(&body, content_type_str, project_id, &token_param);

    let mut response = (status, body).into_response();
    response.headers_mut().insert(CONTENT_TYPE, content_type);
    if !token_param.is_empty() {
        response.headers_mut().append(
            SET_COOKIE,
            sandbox_proxy_auth_cookie(project_id, &token_param, secure_cookie)?,
        );
        response.headers_mut().append(
            SET_COOKIE,
            desktop_proxy_token_cookie(project_id, &token_param)?,
        );
    }
    Ok(response)
}

pub(super) struct HttpServiceProxyResponseInput<'a> {
    pub(super) project_id: &'a str,
    pub(super) service_id: &'a str,
    pub(super) service_info: &'a HttpServiceProxyInfo,
    pub(super) path: &'a str,
    pub(super) raw_query: Option<&'a str>,
    pub(super) method: Method,
    pub(super) request_headers: HeaderMap,
    pub(super) request_body: Vec<u8>,
    pub(super) raw_key: &'a str,
    pub(super) secure_cookie: bool,
}

pub(super) async fn proxy_http_service_response(
    input: HttpServiceProxyResponseInput<'_>,
) -> SandboxApiResult<Response> {
    let HttpServiceProxyResponseInput {
        project_id,
        service_id,
        service_info,
        path,
        raw_query,
        method,
        request_headers,
        request_body,
        raw_key,
        secure_cookie,
    } = input;
    if service_info.source_type != HttpServiceSourceType::SandboxInternal {
        return Err(SandboxApiError::bad_request(
            "HTTP proxy is only available for sandbox_internal services",
        ));
    }
    let target_url = build_upstream_http_url(&service_info.service_url, path, raw_query)?;
    let client = http_service_proxy_client()?;
    let upstream = client
        .request(method, target_url)
        .headers(filter_proxy_headers(&request_headers))
        .body(request_body)
        .send()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;

    let status = StatusCode::from_u16(upstream.status().as_u16())
        .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let upstream_headers = upstream.headers().clone();
    let content_type = upstream_headers
        .get(CONTENT_TYPE)
        .cloned()
        .unwrap_or_else(|| HeaderValue::from_static("application/octet-stream"));
    let content_type_str = content_type.to_str().unwrap_or("application/octet-stream");
    let token_param = raw_query
        .and_then(|query| {
            url::form_urlencoded::parse(query.as_bytes())
                .find(|(key, _)| key == PROXY_TOKEN_QUERY_PARAM)
                .map(|(_, value)| value.into_owned())
        })
        .unwrap_or_default();
    let body = upstream
        .bytes()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;
    let body = rewrite_http_service_content(
        &body,
        content_type_str,
        project_id,
        service_id,
        &token_param,
    );

    let mut response = (status, body).into_response();
    response.headers_mut().insert(CONTENT_TYPE, content_type);
    if let Some(cache_control) = upstream_headers.get(CACHE_CONTROL) {
        response
            .headers_mut()
            .insert(CACHE_CONTROL, cache_control.clone());
    }
    if let Some(location) = upstream_headers
        .get(LOCATION)
        .and_then(|value| value.to_str().ok())
    {
        let rewritten = rewrite_http_service_location(
            location,
            project_id,
            service_id,
            &token_param,
            &service_info.service_url,
        );
        let header = HeaderValue::from_str(&rewritten)
            .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;
        response.headers_mut().insert(LOCATION, header);
    }

    response.headers_mut().append(
        SET_COOKIE,
        sandbox_proxy_auth_cookie(project_id, raw_key, secure_cookie)?,
    );
    response.headers_mut().append(
        SET_COOKIE,
        desktop_token_cookie(project_id, service_id, raw_key)?,
    );
    Ok(response)
}

pub(super) async fn proxy_http_service_preview_host_response(
    sandboxes: &ProjectSandboxService,
    host_header: &str,
    path: &str,
    raw_query: Option<&str>,
    method: Method,
    request_headers: HeaderMap,
    request_body: Vec<u8>,
) -> SandboxApiResult<Response> {
    let (project_id, service_label) = parse_http_preview_host(host_header)
        .ok_or_else(|| SandboxApiError::not_found("Not found"))?;
    let service_info = sandboxes
        .get_http_service_by_preview_label(&project_id, &service_label)
        .await?
        .ok_or_else(http_service_not_found)?;
    if service_info.source_type != HttpServiceSourceType::SandboxInternal {
        return Err(SandboxApiError::bad_request(
            "HTTP preview host is only available for sandbox_internal services",
        ));
    }

    let query_token = preview_session_token_from_query(raw_query);
    let cookie_token = extract_cookie_value(&request_headers, PREVIEW_SESSION_COOKIE_NAME);
    let session_token = query_token.as_deref().or(cookie_token.as_deref());
    let session = sandboxes
        .preview_session_matches_service(session_token, &project_id, &service_info.service_id)
        .await?
        .ok_or_else(|| {
            SandboxApiError::new(
                StatusCode::UNAUTHORIZED,
                "Preview session is missing or expired",
            )
        })?;

    if let Some(query_token) = query_token {
        let mut response = (StatusCode::FOUND, Body::empty()).into_response();
        let location = HeaderValue::from_str(&clean_preview_session_path(path, raw_query))
            .map_err(|_| SandboxApiError::internal("Failed to set preview redirect location"))?;
        response.headers_mut().insert(LOCATION, location);
        response.headers_mut().append(
            SET_COOKIE,
            preview_session_cookie(
                &query_token,
                &session,
                proxy_auth_cookie_secure(&request_headers),
            )?,
        );
        return Ok(response);
    }

    let target_url = build_upstream_preview_http_url(&service_info.service_url, path, raw_query)?;
    let client = http_service_proxy_client()?;
    let upstream = client
        .request(method, target_url)
        .headers(filter_proxy_headers(&request_headers))
        .body(request_body)
        .send()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;

    let status = StatusCode::from_u16(upstream.status().as_u16())
        .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let upstream_headers = upstream.headers().clone();
    let content_type = upstream_headers
        .get(CONTENT_TYPE)
        .cloned()
        .unwrap_or_else(|| HeaderValue::from_static("application/octet-stream"));
    let body = upstream
        .bytes()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;

    let mut response = (status, body).into_response();
    response.headers_mut().insert(CONTENT_TYPE, content_type);
    if let Some(cache_control) = upstream_headers.get(CACHE_CONTROL) {
        response
            .headers_mut()
            .insert(CACHE_CONTROL, cache_control.clone());
    }
    if let Some(location) = upstream_headers
        .get(LOCATION)
        .and_then(|value| value.to_str().ok())
    {
        let rewritten = rewrite_http_service_host_location(
            location,
            request_scheme_from_headers(&request_headers),
            host_header,
            &service_info.service_url,
        );
        let header = HeaderValue::from_str(&rewritten)
            .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;
        response.headers_mut().insert(LOCATION, header);
    }
    Ok(response)
}

pub(super) async fn proxy_http_service_preview_host_ws_response(
    sandboxes: &ProjectSandboxService,
    host_header: &str,
    path: &str,
    raw_query: Option<&str>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> Response {
    let upgrade = websocket_upgrade_with_auth_protocol(ws, &headers);
    let Some((project_id, service_label)) = parse_http_preview_host(host_header) else {
        return upgrade
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(socket, "Not a preview host")
            })
            .into_response();
    };
    let service_info = match sandboxes
        .get_http_service_by_preview_label(&project_id, &service_label)
        .await
    {
        Ok(Some(service_info)) => service_info,
        Ok(None) => {
            return upgrade
                .on_upgrade(|socket| {
                    close_http_service_ws_with_policy_error(socket, "HTTP service not found")
                })
                .into_response();
        }
        Err(_) => {
            return upgrade
                .on_upgrade(close_http_preview_host_ws_with_internal_error)
                .into_response();
        }
    };
    if service_info.source_type != HttpServiceSourceType::SandboxInternal {
        return upgrade
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(
                    socket,
                    "HTTP preview host WS proxy is only available for sandbox_internal services",
                )
            })
            .into_response();
    }

    let query_token = preview_session_token_from_query(raw_query);
    let cookie_token = extract_cookie_value(&headers, PREVIEW_SESSION_COOKIE_NAME);
    let session_token = query_token.as_deref().or(cookie_token.as_deref());
    let session_matches = sandboxes
        .preview_session_matches_service(session_token, &project_id, &service_info.service_id)
        .await
        .ok()
        .flatten()
        .is_some();
    if !session_matches {
        return upgrade
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(
                    socket,
                    "Preview session is missing or expired",
                )
            })
            .into_response();
    }

    let ws_target = match build_upstream_preview_ws_url(&service_info.service_url, path, raw_query)
    {
        Ok(ws_target) => ws_target,
        Err(_) => {
            return upgrade
                .on_upgrade(close_http_preview_host_ws_with_internal_error)
                .into_response();
        }
    };
    let origin = request_origin_from_headers(&headers, &service_info.service_url);
    upgrade
        .on_upgrade(move |socket| proxy_http_service_ws_session(socket, ws_target, origin))
        .into_response()
}

pub(crate) async fn preview_host_proxy(
    State(app): State<AppState>,
    ws: Option<WebSocketUpgrade>,
    method: Method,
    uri: Uri,
    headers: HeaderMap,
    req: Request<Body>,
) -> Response {
    let path = uri.path().to_string();
    let raw_query = uri.query().map(str::to_string);
    let host_header = headers
        .get("host")
        .and_then(|value| value.to_str().ok())
        .unwrap_or_default()
        .to_string();
    if let Some(ws) = ws {
        return proxy_http_service_preview_host_ws_response(
            &app.sandboxes,
            &host_header,
            &path,
            raw_query.as_deref(),
            headers,
            ws,
        )
        .await;
    }

    let body = match to_bytes(req.into_body(), HTTP_PROXY_BODY_LIMIT_BYTES).await {
        Ok(body) => body.to_vec(),
        Err(_) => return SandboxApiError::bad_request("Request body too large").into_response(),
    };
    proxy_http_service_preview_host_response(
        &app.sandboxes,
        &host_header,
        &path,
        raw_query.as_deref(),
        method,
        headers,
        body,
    )
    .await
    .unwrap_or_else(IntoResponse::into_response)
}
