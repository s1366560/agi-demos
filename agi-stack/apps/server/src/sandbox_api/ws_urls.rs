use serde_json::Value;

use super::{
    filter_preview_host_query, filter_proxy_query, normalize_desktop_upstream_base,
    SandboxApiError, SandboxApiResult, MCP_APP_MIME_TYPE, MCP_UPSTREAM_TOKEN_QUERY_PARAM,
};

pub(super) fn build_desktop_websocket_target(desktop_url: &str) -> SandboxApiResult<String> {
    let desktop_base = normalize_desktop_upstream_base(desktop_url);
    let mut url = url::Url::parse(&desktop_base)
        .map_err(|_| SandboxApiError::bad_request("Invalid desktop service URL"))?;
    let scheme = match url.scheme() {
        "http" => "ws",
        "https" => "wss",
        "ws" => "ws",
        "wss" => "wss",
        _ => return Err(SandboxApiError::bad_request("Invalid desktop service URL")),
    };
    url.set_scheme(scheme)
        .map_err(|_| SandboxApiError::bad_request("Invalid desktop service URL"))?;
    let base_path = url.path().trim_end_matches('/');
    let final_path = if base_path.is_empty() || base_path == "/" {
        "/websockify".to_string()
    } else {
        format!("{base_path}/websockify")
    };
    url.set_path(&final_path);
    url.set_query(None);
    Ok(url.to_string())
}

pub(super) fn desktop_websocket_origin(desktop_url: &str, ws_target: &str) -> String {
    match url::Url::parse(ws_target).map(|url| url.scheme() == "wss") {
        Ok(true) => normalize_desktop_upstream_base(desktop_url),
        _ => desktop_url.to_string(),
    }
}

pub(super) fn build_terminal_websocket_target(terminal_url: &str) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(terminal_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid terminal service URL"))?;
    let scheme = match url.scheme() {
        "http" => "ws",
        "https" => "wss",
        "ws" => "ws",
        "wss" => "wss",
        _ => return Err(SandboxApiError::bad_request("Invalid terminal service URL")),
    };
    url.set_scheme(scheme)
        .map_err(|_| SandboxApiError::bad_request("Invalid terminal service URL"))?;
    url.set_query(None);
    Ok(url.to_string())
}

pub(super) fn terminal_websocket_origin(terminal_url: &str, ws_target: &str) -> String {
    match url::Url::parse(ws_target).map(|url| url.scheme() == "wss") {
        Ok(true) => terminal_url
            .strip_prefix("ws://")
            .map(|rest| format!("https://{rest}"))
            .unwrap_or_else(|| terminal_url.to_string()),
        _ => terminal_url.to_string(),
    }
}

pub(super) fn build_mcp_websocket_target(mcp_url: &str) -> SandboxApiResult<String> {
    let url = url::Url::parse(mcp_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid MCP service URL"))?;
    match url.scheme() {
        "ws" | "wss" => Ok(url.to_string()),
        _ => Err(SandboxApiError::bad_request("Invalid MCP service URL")),
    }
}

pub(super) fn append_mcp_upstream_token(ws_target: &str, token: &str) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(ws_target)
        .map_err(|_| SandboxApiError::bad_request("Invalid MCP service URL"))?;
    let existing: Vec<(String, String)> = url
        .query_pairs()
        .filter(|(key, _)| key != MCP_UPSTREAM_TOKEN_QUERY_PARAM)
        .map(|(key, value)| (key.into_owned(), value.into_owned()))
        .collect();
    url.set_query(None);
    {
        let mut pairs = url.query_pairs_mut();
        for (key, value) in existing {
            pairs.append_pair(&key, &value);
        }
        pairs.append_pair(MCP_UPSTREAM_TOKEN_QUERY_PARAM, token);
    }
    Ok(url.to_string())
}

pub(super) fn normalize_mcp_resource_mime_type(message: &str) -> String {
    let Ok(mut data) = serde_json::from_str::<Value>(message) else {
        return message.to_string();
    };
    let mut modified = false;
    if let Some(contents) = data
        .get_mut("result")
        .and_then(Value::as_object_mut)
        .and_then(|result| result.get_mut("contents"))
        .and_then(Value::as_array_mut)
    {
        for item in contents {
            let Some(item) = item.as_object_mut() else {
                continue;
            };
            let is_plain_html = item
                .get("mimeType")
                .and_then(Value::as_str)
                .map(str::trim)
                .is_some_and(|mime| mime.eq_ignore_ascii_case("text/html"));
            if is_plain_html {
                item.insert(
                    "mimeType".to_string(),
                    Value::String(MCP_APP_MIME_TYPE.to_string()),
                );
                modified = true;
            }
        }
    }
    if modified {
        data.to_string()
    } else {
        message.to_string()
    }
}

pub(super) fn build_upstream_ws_url(
    base_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(base_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid HTTP service URL"))?;
    let scheme = if url.scheme() == "https" { "wss" } else { "ws" };
    url.set_scheme(scheme)
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

pub(super) fn build_upstream_preview_ws_url(
    base_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(base_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid HTTP service URL"))?;
    let scheme = if url.scheme() == "https" { "wss" } else { "ws" };
    url.set_scheme(scheme)
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
