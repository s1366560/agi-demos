use super::*;

pub(super) fn proxy_auth_cookie_secure(headers: &HeaderMap) -> bool {
    headers
        .get("x-forwarded-proto")
        .and_then(|value| value.to_str().ok())
        .map(|value| {
            value
                .split(',')
                .next()
                .map(str::trim)
                .is_some_and(|proto| proto.eq_ignore_ascii_case("https"))
        })
        .unwrap_or(false)
        || headers
            .get("forwarded")
            .and_then(|value| value.to_str().ok())
            .map(|value| {
                value
                    .split(';')
                    .map(str::trim)
                    .any(|part| part.eq_ignore_ascii_case("proto=https"))
            })
            .unwrap_or(false)
}

pub(super) fn sandbox_proxy_auth_cookie(
    project_id: &str,
    api_key: &str,
    secure: bool,
) -> SandboxApiResult<HeaderValue> {
    let mut cookie = format!(
        "{SANDBOX_PROXY_TOKEN_COOKIE_NAME}={api_key}; HttpOnly; SameSite=Strict; Max-Age={SANDBOX_PROXY_AUTH_COOKIE_MAX_AGE_SECONDS}; Path=/api/v1/projects/{project_id}/sandbox"
    );
    if secure {
        cookie.push_str("; Secure");
    }
    HeaderValue::from_str(&cookie)
        .map_err(|_| SandboxApiError::internal("Failed to set sandbox proxy auth cookie"))
}

pub(super) fn desktop_token_cookie(
    project_id: &str,
    service_id: &str,
    api_key: &str,
) -> SandboxApiResult<HeaderValue> {
    let cookie = format!(
        "{DESKTOP_TOKEN_COOKIE_NAME}={api_key}; HttpOnly; SameSite=Strict; Max-Age={DESKTOP_TOKEN_COOKIE_MAX_AGE_SECONDS}; Path=/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy"
    );
    HeaderValue::from_str(&cookie)
        .map_err(|_| SandboxApiError::internal("Failed to set sandbox proxy auth cookie"))
}

pub(super) fn desktop_proxy_token_cookie(
    project_id: &str,
    api_key: &str,
) -> SandboxApiResult<HeaderValue> {
    let cookie = format!(
        "{DESKTOP_TOKEN_COOKIE_NAME}={api_key}; HttpOnly; SameSite=Strict; Max-Age={DESKTOP_TOKEN_COOKIE_MAX_AGE_SECONDS}; Path=/api/v1/projects/{project_id}/sandbox/desktop/proxy"
    );
    HeaderValue::from_str(&cookie)
        .map_err(|_| SandboxApiError::internal("Failed to set sandbox proxy auth cookie"))
}

pub(super) fn filter_proxy_headers(headers: &HeaderMap) -> HeaderMap {
    const BLOCKED: &[&str] = &[
        "host",
        "content-length",
        "connection",
        "authorization",
        "accept-encoding",
        "cookie",
        "proxy-authorization",
        "x-forwarded-for",
        "x-forwarded-proto",
    ];

    let mut out = HeaderMap::new();
    for (name, value) in headers {
        if BLOCKED
            .iter()
            .any(|blocked| name.as_str().eq_ignore_ascii_case(blocked))
        {
            continue;
        }
        out.append(name.clone(), value.clone());
    }
    out
}

pub(super) fn filter_desktop_proxy_headers(headers: &HeaderMap) -> HeaderMap {
    let mut out = HeaderMap::new();
    for name in [ACCEPT, ACCEPT_ENCODING, ACCEPT_LANGUAGE, CACHE_CONTROL] {
        if let Some(value) = headers.get(&name) {
            out.insert(name, value.clone());
        }
    }
    out
}

pub(super) fn filter_proxy_query(raw_query: Option<&str>) -> Option<String> {
    let raw_query = raw_query?;
    let mut serializer = url::form_urlencoded::Serializer::new(String::new());
    for (key, value) in url::form_urlencoded::parse(raw_query.as_bytes()) {
        if key != "token" {
            serializer.append_pair(&key, &value);
        }
    }
    let query = serializer.finish();
    if query.is_empty() {
        None
    } else {
        Some(query)
    }
}

pub(super) fn filter_preview_host_query(raw_query: Option<&str>) -> Option<String> {
    let raw_query = raw_query?;
    let mut serializer = url::form_urlencoded::Serializer::new(String::new());
    for (key, value) in url::form_urlencoded::parse(raw_query.as_bytes()) {
        if key != PREVIEW_SESSION_QUERY_PARAM {
            serializer.append_pair(&key, &value);
        }
    }
    let query = serializer.finish();
    if query.is_empty() {
        None
    } else {
        Some(query)
    }
}

pub(super) fn build_upstream_http_url(
    base_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(base_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid HTTP service URL"))?;
    let base_path = url.path().trim_end_matches('/');
    let extra_path = path.trim_start_matches('/');
    let final_path = match (
        base_path.is_empty() || base_path == "/",
        extra_path.is_empty(),
    ) {
        (true, true) => "/".to_string(),
        (true, false) => format!("/{extra_path}"),
        (false, true) => base_path.to_string(),
        (false, false) => format!("{base_path}/{extra_path}"),
    };
    url.set_path(&final_path);
    url.set_query(filter_proxy_query(raw_query).as_deref());
    Ok(url.to_string())
}

pub(super) fn build_upstream_preview_http_url(
    base_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(base_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid HTTP service URL"))?;
    let base_path = url.path().trim_end_matches('/');
    let extra_path = path.trim_start_matches('/');
    let final_path = match (
        base_path.is_empty() || base_path == "/",
        extra_path.is_empty(),
    ) {
        (true, true) => "/".to_string(),
        (true, false) => format!("/{extra_path}"),
        (false, true) => base_path.to_string(),
        (false, false) => format!("{base_path}/{extra_path}"),
    };
    url.set_path(&final_path);
    url.set_query(filter_preview_host_query(raw_query).as_deref());
    Ok(url.to_string())
}

pub(super) fn normalize_desktop_upstream_base(desktop_url: &str) -> String {
    desktop_url
        .strip_prefix("http://")
        .map(|rest| format!("https://{rest}"))
        .unwrap_or_else(|| desktop_url.to_string())
}

pub(super) fn build_upstream_desktop_http_url(
    desktop_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let desktop_base = normalize_desktop_upstream_base(desktop_url);
    let mut url = url::Url::parse(&desktop_base)
        .map_err(|_| SandboxApiError::bad_request("Invalid desktop service URL"))?;
    let base_path = url.path().trim_end_matches('/');
    let extra_path = path.trim_start_matches('/');
    let final_path = match (
        base_path.is_empty() || base_path == "/",
        extra_path.is_empty(),
    ) {
        (true, true) => "/".to_string(),
        (true, false) => format!("/{extra_path}"),
        (false, true) => base_path.to_string(),
        (false, false) => format!("{base_path}/{extra_path}"),
    };
    url.set_path(&final_path);
    url.set_query(filter_proxy_query(raw_query).as_deref());
    Ok(url.to_string())
}

pub(super) fn build_http_path_preview_proxy_url(project_id: &str, service_id: &str) -> String {
    format!("/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy/")
}

pub(super) fn build_http_path_preview_ws_proxy_url(project_id: &str, service_id: &str) -> String {
    format!("/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy/ws/")
}

pub(super) fn should_rewrite_http_service_content(content_type: &str) -> bool {
    let content_type = content_type.to_ascii_lowercase();
    content_type.starts_with("text/html")
        || content_type.starts_with("application/javascript")
        || content_type.starts_with("text/javascript")
        || content_type.starts_with("text/css")
}

pub(super) fn rewrite_http_service_content(
    content: &[u8],
    content_type: &str,
    project_id: &str,
    service_id: &str,
    token_param: &str,
) -> Vec<u8> {
    if !should_rewrite_http_service_content(content_type) {
        return content.to_vec();
    }

    let proxy_prefix = build_http_path_preview_proxy_url(project_id, service_id);
    let ws_proxy_prefix = build_http_path_preview_ws_proxy_url(project_id, service_id);
    let mut content = String::from_utf8_lossy(content).into_owned();

    let attr_re = regex::Regex::new(r#"(href|src|action)=(["'])/([^/"'][^"']*)"#)
        .expect("BUG: static http service attribute rewrite regex must compile");
    content = attr_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[3]), token_param);
            format!("{}={}{}", &caps[1], &caps[2], proxied)
        })
        .into_owned();

    let url_re = regex::Regex::new(r#"url\((['"]?)/([^/'")][^)'"]*)['"]?\)"#)
        .expect("BUG: static http service url() rewrite regex must compile");
    content = url_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let quote = caps.get(1).map(|m| m.as_str()).unwrap_or_default();
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[2]), token_param);
            format!("url({quote}{proxied}{quote})")
        })
        .into_owned();

    let browser_call_re = regex::Regex::new(r#"\b(fetch|EventSource)\((['"])/([^/'"][^'"]*)"#)
        .expect("BUG: static http service browser call rewrite regex must compile");
    content = browser_call_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[3]), token_param);
            format!("{}({}{proxied}", &caps[1], &caps[2])
        })
        .into_owned();

    content = content.replace(
        "ws://\" + location.host + \"/",
        &format!("ws://\" + location.host + \"{ws_proxy_prefix}"),
    );
    content = content.replace(
        "wss://\" + location.host + \"/",
        &format!("wss://\" + location.host + \"{ws_proxy_prefix}"),
    );

    let websocket_re = regex::Regex::new(r#"new WebSocket\((['"])/([^/'"][^'"]*)"#)
        .expect("BUG: static http service websocket rewrite regex must compile");
    content = websocket_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let proxied =
                append_proxy_token(&format!("{}{}", ws_proxy_prefix, &caps[2]), token_param);
            format!("new WebSocket({}{proxied}", &caps[1])
        })
        .into_owned();

    content.into_bytes()
}

pub(super) fn build_desktop_path_proxy_url(project_id: &str) -> String {
    format!("/api/v1/projects/{project_id}/sandbox/desktop/proxy/")
}

pub(super) fn build_desktop_websockify_proxy_url(project_id: &str) -> String {
    format!("/api/v1/projects/{project_id}/sandbox/desktop/proxy/websockify")
}

pub(super) fn should_rewrite_desktop_content(content_type: &str) -> bool {
    let content_type = content_type.to_ascii_lowercase();
    content_type.starts_with("text/html") || content_type.starts_with("application/javascript")
}

pub(super) fn rewrite_desktop_content(
    content: &[u8],
    content_type: &str,
    project_id: &str,
    token_param: &str,
) -> Vec<u8> {
    if !should_rewrite_desktop_content(content_type) {
        return content.to_vec();
    }

    let proxy_prefix = build_desktop_path_proxy_url(project_id);
    let mut content = String::from_utf8_lossy(content).into_owned();
    let attr_re = regex::Regex::new(r#"(href|src)=(["'])/([^"']*)"#)
        .expect("BUG: static desktop attribute rewrite regex must compile");
    content = attr_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[3]), token_param);
            format!("{}={}{}", &caps[1], &caps[2], proxied)
        })
        .into_owned();

    let mut ws_proxy_url = build_desktop_websockify_proxy_url(project_id);
    ws_proxy_url = append_proxy_token(&ws_proxy_url, token_param);
    content = content.replace(
        "ws://\" + location.host + \"/",
        &format!("ws://\" + location.host + \"{ws_proxy_url}"),
    );
    content = content.replace(
        "wss://\" + location.host + \"/",
        &format!("wss://\" + location.host + \"{ws_proxy_url}"),
    );

    content.into_bytes()
}

pub(super) fn url_authority(url: &url::Url) -> Option<String> {
    Some(match url.port() {
        Some(port) => format!("{}:{port}", url.host_str()?),
        None => url.host_str()?.to_string(),
    })
}

pub(super) fn rewrite_http_service_location(
    location: &str,
    project_id: &str,
    service_id: &str,
    token_param: &str,
    upstream_base_url: &str,
) -> String {
    if location.is_empty() {
        return location.to_string();
    }

    let proxy_prefix = build_http_path_preview_proxy_url(project_id, service_id);
    if let Ok(parsed_location) = url::Url::parse(location) {
        let Ok(upstream) = url::Url::parse(upstream_base_url) else {
            return location.to_string();
        };
        if url_authority(&parsed_location) != url_authority(&upstream) {
            return location.to_string();
        }
        let mut target = format!(
            "{}{}",
            proxy_prefix,
            parsed_location.path().trim_start_matches('/')
        );
        if let Some(query) = parsed_location.query() {
            target.push('?');
            target.push_str(query);
        }
        return append_proxy_token(&target, token_param);
    }

    if location.starts_with("//") {
        return location.to_string();
    }
    if location.starts_with('/') {
        return append_proxy_token(
            &format!("{}{}", proxy_prefix, location.trim_start_matches('/')),
            token_param,
        );
    }
    append_proxy_token(&format!("{proxy_prefix}{location}"), token_param)
}

pub(super) fn preview_public_scheme() -> &'static str {
    match std::env::var(PREVIEW_SCHEME_ENV)
        .ok()
        .map(|scheme| scheme.trim().to_ascii_lowercase())
        .as_deref()
    {
        Some("https") => "https",
        _ => "http",
    }
}

pub(super) fn preview_host_suffix() -> String {
    let raw = std::env::var(PREVIEW_HOST_SUFFIX_ENV)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "preview.localhost:8000".to_string());
    raw.strip_prefix("http://")
        .or_else(|| raw.strip_prefix("https://"))
        .unwrap_or(raw.as_str())
        .trim_matches('/')
        .to_string()
}

pub(super) fn preview_host_suffix_hostname() -> String {
    let suffix = preview_host_suffix();
    url::Url::parse(&format!("http://{suffix}"))
        .ok()
        .and_then(|url| url.host_str().map(|host| host.to_ascii_lowercase()))
        .unwrap_or_else(|| {
            suffix
                .split(':')
                .next()
                .unwrap_or(suffix.as_str())
                .to_ascii_lowercase()
        })
        .trim_matches('.')
        .to_string()
}

pub(super) fn preview_service_host_label(service_id: &str) -> String {
    let mut label = String::new();
    let mut last_dash = false;
    for ch in service_id.chars().flat_map(char::to_lowercase) {
        let next = if ch.is_ascii_alphanumeric() { ch } else { '-' };
        if next == '-' {
            if !last_dash {
                label.push(next);
                last_dash = true;
            }
        } else {
            label.push(next);
            last_dash = false;
        }
    }
    let label = label.trim_matches('-');
    let label = label.chars().take(63).collect::<String>();
    let label = label.trim_matches('-').to_string();
    if label.is_empty() {
        "service".to_string()
    } else {
        label
    }
}

pub(super) fn is_preview_host_label(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 63
        && value
            .chars()
            .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == '-')
}

pub(super) fn parse_http_preview_host(host_header: &str) -> Option<(String, String)> {
    let parsed = url::Url::parse(&format!("http://{}", host_header.trim())).ok()?;
    let hostname = parsed.host_str()?.to_ascii_lowercase();
    let hostname = hostname.trim_matches('.');
    let suffix = preview_host_suffix_hostname();
    let expected_tail = format!(".{suffix}");
    if !hostname.ends_with(&expected_tail) {
        return None;
    }
    let preview_prefix = &hostname[..hostname.len() - expected_tail.len()];
    let mut labels = preview_prefix.split('.');
    let service_label = labels.next()?;
    let project_id = labels.next()?;
    if labels.next().is_some()
        || !is_preview_host_label(service_label)
        || !is_preview_host_label(project_id)
    {
        return None;
    }
    Some((project_id.to_string(), service_label.to_string()))
}

pub(super) fn build_http_preview_proxy_url(project_id: &str, service_id: &str) -> String {
    format!(
        "{}://{}.{}.{}/",
        preview_public_scheme(),
        preview_service_host_label(service_id),
        project_id.to_ascii_lowercase(),
        preview_host_suffix()
    )
}

pub(super) fn build_http_preview_ws_proxy_url(project_id: &str, service_id: &str) -> String {
    let preview_url = build_http_preview_proxy_url(project_id, service_id);
    if let Some(rest) = preview_url.strip_prefix("https://") {
        format!("wss://{rest}")
    } else if let Some(rest) = preview_url.strip_prefix("http://") {
        format!("ws://{rest}")
    } else {
        preview_url
    }
}

pub(super) fn append_query_param(url: &str, key: &str, value: &str) -> String {
    let sep = if url.contains('?') { '&' } else { '?' };
    format!("{url}{sep}{key}={value}")
}

pub(super) fn append_proxy_token(url: &str, token_param: &str) -> String {
    if token_param.is_empty() || url.contains(&format!("{PROXY_TOKEN_QUERY_PARAM}=")) {
        return url.to_string();
    }
    append_query_param(url, PROXY_TOKEN_QUERY_PARAM, token_param)
}

pub(super) fn proxy_token_from_query(raw_query: Option<&str>) -> String {
    raw_query
        .and_then(|query| {
            url::form_urlencoded::parse(query.as_bytes())
                .find(|(key, _)| key == PROXY_TOKEN_QUERY_PARAM)
                .map(|(_, value)| value.into_owned())
        })
        .unwrap_or_default()
}

pub(super) fn extract_cookie_value(headers: &HeaderMap, name: &str) -> Option<String> {
    let cookie_header = headers.get("cookie")?.to_str().ok()?;
    cookie_header.split(';').find_map(|part| {
        let (key, value) = part.trim().split_once('=')?;
        (key == name).then(|| value.to_string())
    })
}

pub(super) fn preview_session_token_from_query(raw_query: Option<&str>) -> Option<String> {
    let raw_query = raw_query?;
    url::form_urlencoded::parse(raw_query.as_bytes())
        .find(|(key, _)| key == PREVIEW_SESSION_QUERY_PARAM)
        .map(|(_, value)| value.into_owned())
}

pub(super) fn clean_preview_session_path(path: &str, raw_query: Option<&str>) -> String {
    let mut clean = if path.is_empty() {
        "/".to_string()
    } else {
        path.to_string()
    };
    if let Some(query) = filter_preview_host_query(raw_query) {
        clean.push('?');
        clean.push_str(&query);
    }
    clean
}

pub(super) fn preview_session_cookie(
    token: &str,
    session: &PreviewSessionRecord,
    secure: bool,
) -> SandboxApiResult<HeaderValue> {
    let max_age_seconds = ((session.expires_at_ms - now_ms()) / 1000).max(1);
    let mut cookie = format!(
        "{PREVIEW_SESSION_COOKIE_NAME}={token}; HttpOnly; SameSite=Lax; Max-Age={max_age_seconds}; Path=/"
    );
    if secure {
        cookie.push_str("; Secure");
    }
    HeaderValue::from_str(&cookie)
        .map_err(|_| SandboxApiError::internal("Failed to set preview session cookie"))
}

pub(super) fn request_scheme_from_headers(headers: &HeaderMap) -> &'static str {
    if proxy_auth_cookie_secure(headers) {
        "https"
    } else {
        "http"
    }
}

pub(super) fn request_origin_from_headers(headers: &HeaderMap, fallback_origin: &str) -> String {
    headers
        .get("origin")
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|origin| !origin.is_empty())
        .map(str::to_string)
        .unwrap_or_else(|| fallback_origin.to_string())
}

pub(super) fn rewrite_http_service_host_location(
    location: &str,
    request_scheme: &str,
    request_host: &str,
    upstream_base_url: &str,
) -> String {
    if location.is_empty() {
        return location.to_string();
    }
    let Ok(parsed_location) = url::Url::parse(location) else {
        return location.to_string();
    };
    let Ok(upstream) = url::Url::parse(upstream_base_url) else {
        return location.to_string();
    };
    if url_authority(&parsed_location) != url_authority(&upstream) {
        return location.to_string();
    }
    let mut rewritten = parsed_location;
    let _ = rewritten.set_scheme(request_scheme);
    if let Some((host, port)) = request_host.rsplit_once(':') {
        if let Ok(port) = port.parse::<u16>() {
            let _ = rewritten.set_host(Some(host));
            let _ = rewritten.set_port(Some(port));
            return rewritten.to_string();
        }
    }
    let _ = rewritten.set_host(Some(request_host));
    let _ = rewritten.set_port(None);
    rewritten.to_string()
}
