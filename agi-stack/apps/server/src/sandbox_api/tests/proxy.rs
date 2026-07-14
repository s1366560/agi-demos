use std::time::Duration;

use super::super::*;
use super::*;

#[test]
fn http_service_proxy_helpers_match_python_path_contract() {
    assert_eq!(
        build_http_path_preview_proxy_url("p1", "web"),
        "/api/v1/projects/p1/sandbox/http-services/web/proxy/"
    );
    assert_eq!(
        build_http_path_preview_ws_proxy_url("p1", "web"),
        "/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/"
    );
    assert_eq!(
        filter_proxy_query(Some("token=ms_sk_secret&q=hello+world&empty=")).as_deref(),
        Some("q=hello+world&empty=")
    );
    assert_eq!(
        build_upstream_http_url(
            "http://127.0.0.1:3000/docs",
            "assets/app.js",
            Some("token=ms_sk_secret&q=hello+world")
        )
        .unwrap(),
        "http://127.0.0.1:3000/docs/assets/app.js?q=hello+world"
    );
    assert_eq!(
        build_upstream_ws_url(
            "https://example.test/docs",
            "socket",
            Some("token=ms_sk_secret&q=hello+world")
        )
        .unwrap(),
        "wss://example.test/docs/socket?q=hello+world"
    );
    assert_eq!(
        build_upstream_preview_ws_url(
            "https://example.test/docs",
            "socket",
            Some("ms_preview_session=secret&q=hello+world")
        )
        .unwrap(),
        "wss://example.test/docs/socket?q=hello+world"
    );
    assert_eq!(
        parse_http_preview_host("web.p1.preview.localhost:8000"),
        Some(("p1".to_string(), "web".to_string()))
    );
    assert_eq!(parse_http_preview_host("web.p1.other.localhost:8000"), None);
    assert_eq!(
        filter_preview_host_query(Some("ms_preview_session=secret&q=hello+world&empty="))
            .as_deref(),
        Some("q=hello+world&empty=")
    );
    assert_eq!(
        build_upstream_preview_http_url(
            "http://127.0.0.1:3000/docs",
            "assets/app.js",
            Some("ms_preview_session=secret&q=hello+world")
        )
        .unwrap(),
        "http://127.0.0.1:3000/docs/assets/app.js?q=hello+world"
    );
    assert_eq!(
        rewrite_http_service_host_location(
            "http://127.0.0.1:3000/docs/login?next=%2F",
            "https",
            "web.p1.preview.localhost:8000",
            "http://127.0.0.1:3000/docs",
        ),
        "https://web.p1.preview.localhost:8000/docs/login?next=%2F"
    );

    let mut headers = HeaderMap::new();
    headers.insert(
        "authorization",
        HeaderValue::from_static("Bearer ms_sk_secret"),
    );
    headers.insert("cookie", HeaderValue::from_static("a=b"));
    headers.insert("x-trace-id", HeaderValue::from_static("trace-1"));
    headers.insert(
        "sec-websocket-protocol",
        HeaderValue::from_static("ms_sk_secret, memstack.auth"),
    );
    let filtered = filter_proxy_headers(&headers);
    assert!(!filtered.contains_key("authorization"));
    assert!(!filtered.contains_key("cookie"));
    assert_eq!(
        filtered
            .get("x-trace-id")
            .and_then(|value| value.to_str().ok()),
        Some("trace-1")
    );
    assert_eq!(
        select_websocket_auth_subprotocol(&headers),
        Some(WEBSOCKET_AUTH_SUBPROTOCOL)
    );
    assert_eq!(
        request_origin_from_headers(&headers, "http://127.0.0.1:3000"),
        "http://127.0.0.1:3000"
    );
    headers.insert("origin", HeaderValue::from_static("https://frontend.test"));
    assert_eq!(
        request_origin_from_headers(&headers, "http://127.0.0.1:3000"),
        "https://frontend.test"
    );

    let rewritten = rewrite_http_service_location(
        "http://127.0.0.1:3000/docs/login?next=%2F",
        "p1",
        "web",
        "ms_sk_secret",
        "http://127.0.0.1:3000/docs",
    );
    assert_eq!(
        rewritten,
        "/api/v1/projects/p1/sandbox/http-services/web/proxy/docs/login?next=%2F&token=ms_sk_secret"
    );
    assert_eq!(
        rewrite_http_service_location(
            "https://other.test/login",
            "p1",
            "web",
            "ms_sk_secret",
            "http://127.0.0.1:3000/docs",
        ),
        "https://other.test/login"
    );

    let body = br#"<link href="/assets/app.css"><script>fetch('/api/data');new WebSocket('/socket')</script>"#;
    let rewritten = rewrite_http_service_content(
        body,
        "text/html; charset=utf-8",
        "p1",
        "web",
        "ms_sk_secret",
    );
    let rewritten = String::from_utf8(rewritten).unwrap();
    assert!(rewritten.contains(
        r#"href="/api/v1/projects/p1/sandbox/http-services/web/proxy/assets/app.css?token=ms_sk_secret""#
    ));
    assert!(rewritten.contains(
        r#"fetch('/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data?token=ms_sk_secret'"#
    ));
    assert!(rewritten.contains(
        r#"new WebSocket('/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/socket?token=ms_sk_secret'"#
    ));
}
#[test]
fn desktop_proxy_helpers_match_python_path_contract() {
    assert_eq!(
        build_desktop_path_proxy_url("p1"),
        "/api/v1/projects/p1/sandbox/desktop/proxy/"
    );
    assert_eq!(
        build_desktop_websockify_proxy_url("p1"),
        "/api/v1/projects/p1/sandbox/desktop/proxy/websockify"
    );
    assert_eq!(
        normalize_desktop_upstream_base("http://127.0.0.1:6080"),
        "https://127.0.0.1:6080"
    );
    assert_eq!(
        build_upstream_desktop_http_url(
            "http://127.0.0.1:6080/vnc",
            "index.html",
            Some("token=ms_sk_secret&q=hello+world")
        )
        .unwrap(),
        "https://127.0.0.1:6080/vnc/index.html?q=hello+world"
    );
    assert_eq!(
        build_desktop_websocket_target("http://127.0.0.1:6080/vnc").unwrap(),
        "wss://127.0.0.1:6080/vnc/websockify"
    );
    assert_eq!(
        build_desktop_websocket_target("https://localhost:6080").unwrap(),
        "wss://localhost:6080/websockify"
    );
    assert_eq!(
        build_desktop_websocket_target("ws://127.0.0.1:6080/base").unwrap(),
        "ws://127.0.0.1:6080/base/websockify"
    );
    assert_eq!(
        desktop_websocket_origin("http://127.0.0.1:6080", "wss://127.0.0.1:6080/websockify"),
        "https://127.0.0.1:6080"
    );
    assert_eq!(
        desktop_websocket_origin(
            "ws://127.0.0.1:6080/base",
            "ws://127.0.0.1:6080/base/websockify"
        ),
        "ws://127.0.0.1:6080/base"
    );
    assert_eq!(
        build_terminal_websocket_target("ws://127.0.0.1:7681?token=ms_sk_secret").unwrap(),
        "ws://127.0.0.1:7681/"
    );
    assert_eq!(
        build_terminal_websocket_target("https://127.0.0.1:7681/terminal").unwrap(),
        "wss://127.0.0.1:7681/terminal"
    );
    assert_eq!(
        terminal_websocket_origin(
            "https://127.0.0.1:7681/terminal",
            "wss://127.0.0.1:7681/terminal"
        ),
        "https://127.0.0.1:7681/terminal"
    );
    assert_eq!(
        build_mcp_websocket_target("ws://127.0.0.1:8765/mcp/sandbox?auth=keep").unwrap(),
        "ws://127.0.0.1:8765/mcp/sandbox?auth=keep"
    );
    assert!(build_mcp_websocket_target("http://127.0.0.1:8765/mcp").is_err());

    let mut headers = HeaderMap::new();
    headers.insert(ACCEPT, HeaderValue::from_static("text/html"));
    headers.insert(ACCEPT_ENCODING, HeaderValue::from_static("gzip"));
    headers.insert(ACCEPT_LANGUAGE, HeaderValue::from_static("en-US"));
    headers.insert(CACHE_CONTROL, HeaderValue::from_static("no-cache"));
    headers.insert(
        "authorization",
        HeaderValue::from_static("Bearer ms_sk_secret"),
    );
    headers.insert("cookie", HeaderValue::from_static("a=b"));
    headers.insert("x-trace-id", HeaderValue::from_static("trace-1"));
    let filtered = filter_desktop_proxy_headers(&headers);
    assert_eq!(
        filtered.get(ACCEPT).and_then(|value| value.to_str().ok()),
        Some("text/html")
    );
    assert_eq!(
        filtered
            .get(ACCEPT_ENCODING)
            .and_then(|value| value.to_str().ok()),
        Some("gzip")
    );
    assert_eq!(
        filtered
            .get(ACCEPT_LANGUAGE)
            .and_then(|value| value.to_str().ok()),
        Some("en-US")
    );
    assert_eq!(
        filtered
            .get(CACHE_CONTROL)
            .and_then(|value| value.to_str().ok()),
        Some("no-cache")
    );
    assert!(!filtered.contains_key("authorization"));
    assert!(!filtered.contains_key("cookie"));
    assert!(!filtered.contains_key("x-trace-id"));

    let runtime_token = SandboxRuntimeToken::from_exposed("private-capability");
    let upstream_headers = desktop_upstream_headers(&headers, &runtime_token).unwrap();
    assert_eq!(
        upstream_headers
            .get(AUTHORIZATION)
            .and_then(|value| value.to_str().ok()),
        Some("Basic c2FuZGJveDpwcml2YXRlLWNhcGFiaWxpdHk=")
    );
    assert!(!upstream_headers.contains_key("cookie"));

    let cookie = desktop_proxy_token_cookie("p1", "ms_sk_secret").unwrap();
    assert_eq!(
        cookie.to_str().unwrap(),
        "desktop_token=ms_sk_secret; HttpOnly; SameSite=Strict; Max-Age=86400; Path=/api/v1/projects/p1/sandbox/desktop/proxy"
    );

    let body = br#"<link href="/assets/app.css"><script src="/app.js"></script><script>const ws = "ws://" + location.host + "/"; const wss = "wss://" + location.host + "/";</script>"#;
    let rewritten = rewrite_desktop_content(body, "text/html; charset=utf-8", "p1", "ms_sk_secret");
    let rewritten = String::from_utf8(rewritten).unwrap();
    assert!(rewritten.contains(
        r#"href="/api/v1/projects/p1/sandbox/desktop/proxy/assets/app.css?token=ms_sk_secret""#
    ));
    assert!(rewritten
        .contains(r#"src="/api/v1/projects/p1/sandbox/desktop/proxy/app.js?token=ms_sk_secret""#));
    assert!(rewritten.contains(
        r#"ws://" + location.host + "/api/v1/projects/p1/sandbox/desktop/proxy/websockify?token=ms_sk_secret""#
    ));
    assert!(rewritten.contains(
        r#"wss://" + location.host + "/api/v1/projects/p1/sandbox/desktop/proxy/websockify?token=ms_sk_secret""#
    ));

    let css = br#"body { background: url("/wall.png"); }"#;
    assert_eq!(
        rewrite_desktop_content(css, "text/css", "p1", "ms_sk_secret"),
        css
    );
}
#[test]
fn mcp_upstream_token_replaces_stale_query_token() {
    let target =
        build_mcp_websocket_target("ws://127.0.0.1:8765/mcp/sandbox?auth=keep&token=old&q=1")
            .unwrap();
    let signed = append_mcp_upstream_token(&target, "fresh-token").unwrap();
    let url = url::Url::parse(&signed).unwrap();
    let params: Vec<(String, String)> = url
        .query_pairs()
        .map(|(key, value)| (key.into_owned(), value.into_owned()))
        .collect();

    assert_eq!(url.path(), "/mcp/sandbox");
    assert_eq!(
        params,
        vec![
            ("auth".to_string(), "keep".to_string()),
            ("q".to_string(), "1".to_string()),
            ("token".to_string(), "fresh-token".to_string()),
        ]
    );
}
#[test]
fn mcp_proxy_normalizes_html_resource_mime_type() {
    let response = json!({
        "jsonrpc": "2.0",
        "id": 7,
        "result": {
            "contents": [
                {"uri": "ui://index.html", "mimeType": "text/html", "text": "<html></html>"},
                {"uri": "ui://style.css", "mimeType": "text/css", "text": "body{}"}
            ]
        }
    })
    .to_string();
    let normalized = normalize_mcp_resource_mime_type(&response);
    let parsed: Value = serde_json::from_str(&normalized).unwrap();
    assert_eq!(
        parsed["result"]["contents"][0]["mimeType"],
        MCP_APP_MIME_TYPE
    );
    assert_eq!(parsed["result"]["contents"][1]["mimeType"], "text/css");

    let passthrough = r#"{"jsonrpc":"2.0","method":"tools/list"}"#;
    assert_eq!(normalize_mcp_resource_mime_type(passthrough), passthrough);
}
#[tokio::test]
async fn desktop_proxy_requires_running_desktop_service() {
    let info = sample_info();
    let err = proxy_project_desktop_response(
        "p1",
        &info,
        "index.html",
        Some("token=ms_sk_secret"),
        HeaderMap::new(),
        false,
    )
    .await
    .unwrap_err();
    assert_eq!(err.status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(err.detail, DESKTOP_SERVICE_NOT_RUNNING);
}
fn spawn_http_proxy_fixture() -> (String, std::sync::mpsc::Receiver<String>) {
    let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let addr = listener.local_addr().unwrap();
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        use std::io::{Read, Write};

        let (mut stream, _) = listener.accept().unwrap();
        let mut buf = [0_u8; 8192];
        let n = stream.read(&mut buf).unwrap();
        tx.send(String::from_utf8_lossy(&buf[..n]).into_owned())
            .unwrap();
        let body = r#"<html><link href="/assets/app.css"><script>fetch('/api/data');new WebSocket('/socket')</script></html>"#;
        let response = format!(
            "HTTP/1.1 302 Found\r\ncontent-type: text/html; charset=utf-8\r\ncache-control: no-store\r\nlocation: /login\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        stream.write_all(response.as_bytes()).unwrap();
    });
    (format!("http://{addr}/base"), rx)
}
fn spawn_preview_host_proxy_fixture() -> (String, std::sync::mpsc::Receiver<String>) {
    let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let addr = listener.local_addr().unwrap();
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        use std::io::{Read, Write};

        let (mut stream, _) = listener.accept().unwrap();
        let mut buf = [0_u8; 8192];
        let n = stream.read(&mut buf).unwrap();
        tx.send(String::from_utf8_lossy(&buf[..n]).into_owned())
            .unwrap();
        let body = "preview-host";
        let response = format!(
            "HTTP/1.1 302 Found\r\ncontent-type: text/plain\r\ncache-control: no-store\r\nlocation: http://{addr}/base/login?next=%2F\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        stream.write_all(response.as_bytes()).unwrap();
    });
    (format!("http://{addr}/base"), rx)
}
#[tokio::test]
async fn http_service_proxy_forwards_rewrites_and_filters_headers() {
    let (service_url, rx) = spawn_http_proxy_fixture();
    let service_info = HttpServiceProxyInfo {
        service_id: "web".to_string(),
        name: "Docs".to_string(),
        source_type: HttpServiceSourceType::SandboxInternal,
        status: "running".to_string(),
        service_url,
        preview_url: build_http_preview_proxy_url("p1", "web"),
        ws_preview_url: Some(build_http_preview_ws_proxy_url("p1", "web")),
        sandbox_id: Some("s1".to_string()),
        auto_open: true,
        restart_token: Some("1700000000000".to_string()),
        updated_at: "1970-01-01T00:00:00.000+00:00".to_string(),
    };
    let mut headers = HeaderMap::new();
    headers.insert(
        "authorization",
        HeaderValue::from_static("Bearer ms_sk_secret"),
    );
    headers.insert("cookie", HeaderValue::from_static("a=b"));
    headers.insert("x-forwarded-proto", HeaderValue::from_static("https"));
    headers.insert("x-trace-id", HeaderValue::from_static("trace-1"));

    let response = proxy_http_service_response(HttpServiceProxyResponseInput {
        project_id: "p1",
        service_id: "web",
        service_info: &service_info,
        path: "echo",
        raw_query: Some("token=ms_sk_secret&q=hello+world"),
        method: Method::POST,
        request_headers: headers,
        request_body: b"payload".to_vec(),
        raw_key: "ms_sk_secret",
        secure_cookie: true,
    })
    .await
    .unwrap();

    assert_eq!(response.status(), StatusCode::FOUND);
    assert_eq!(
        response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|value| value.to_str().ok()),
        Some("text/html; charset=utf-8")
    );
    assert_eq!(
        response
            .headers()
            .get(CACHE_CONTROL)
            .and_then(|value| value.to_str().ok()),
        Some("no-store")
    );
    assert_eq!(
        response
            .headers()
            .get(LOCATION)
            .and_then(|value| value.to_str().ok()),
        Some("/api/v1/projects/p1/sandbox/http-services/web/proxy/login?token=ms_sk_secret")
    );
    let cookies = response
        .headers()
        .get_all(SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .collect::<Vec<_>>();
    assert!(cookies.iter().any(|cookie| cookie.contains(
        "sandbox_proxy_token=ms_sk_secret; HttpOnly; SameSite=Strict; Max-Age=3600; Path=/api/v1/projects/p1/sandbox; Secure"
    )));
    assert!(cookies.iter().any(|cookie| cookie.contains(
        "desktop_token=ms_sk_secret; HttpOnly; SameSite=Strict; Max-Age=86400; Path=/api/v1/projects/p1/sandbox/http-services/web/proxy"
    )));

    let body = to_bytes(response.into_body(), HTTP_PROXY_BODY_LIMIT_BYTES)
        .await
        .unwrap();
    let body = String::from_utf8(body.to_vec()).unwrap();
    assert!(body.contains(
        r#"href="/api/v1/projects/p1/sandbox/http-services/web/proxy/assets/app.css?token=ms_sk_secret""#
    ));
    assert!(body.contains(
        r#"fetch('/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data?token=ms_sk_secret'"#
    ));
    assert!(body.contains(
        r#"new WebSocket('/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/socket?token=ms_sk_secret'"#
    ));

    let request = rx
        .recv_timeout(Duration::from_secs(2))
        .expect("upstream request");
    assert!(request.starts_with("POST /base/echo?q=hello+world HTTP/1.1"));
    assert!(request.contains("x-trace-id: trace-1"));
    assert!(!request.to_ascii_lowercase().contains("authorization:"));
    assert!(!request.to_ascii_lowercase().contains("cookie:"));
    assert!(request.ends_with("payload"));
}
#[tokio::test]
async fn http_service_preview_host_sets_session_cookie_and_proxies() {
    let (service_url, rx) = spawn_preview_host_proxy_fixture();
    let service =
        ProjectSandboxService::new(Arc::new(InMemoryContainerRuntime::new()), "redis:7-alpine");
    service
        .upsert_http_service(
            "p1",
            HttpServiceProxyInfo {
                service_id: "web".to_string(),
                name: "Docs".to_string(),
                source_type: HttpServiceSourceType::SandboxInternal,
                status: "running".to_string(),
                service_url,
                preview_url: build_http_preview_proxy_url("p1", "web"),
                ws_preview_url: Some(build_http_preview_ws_proxy_url("p1", "web")),
                sandbox_id: Some("s1".to_string()),
                auto_open: true,
                restart_token: Some("1700000000000".to_string()),
                updated_at: "1970-01-01T00:00:00.000+00:00".to_string(),
            },
        )
        .await
        .unwrap();
    let preview = service.preview_session("p1", "web").await.unwrap();
    let preview_url = url::Url::parse(&preview.preview_url).unwrap();
    let token = preview_session_token_from_query(preview_url.query()).unwrap();
    let host = "web.p1.preview.localhost:8000";

    let mut token_headers = HeaderMap::new();
    token_headers.insert(
        "host",
        HeaderValue::from_static("web.p1.preview.localhost:8000"),
    );
    token_headers.insert("x-forwarded-proto", HeaderValue::from_static("https"));
    let response = proxy_http_service_preview_host_response(
        &service,
        host,
        "/docs",
        Some(&format!("{PREVIEW_SESSION_QUERY_PARAM}={token}&q=1")),
        Method::GET,
        token_headers,
        Vec::new(),
    )
    .await
    .unwrap();
    assert_eq!(response.status(), StatusCode::FOUND);
    assert_eq!(
        response
            .headers()
            .get(LOCATION)
            .and_then(|value| value.to_str().ok()),
        Some("/docs?q=1")
    );
    let session_cookie = response
        .headers()
        .get(SET_COOKIE)
        .and_then(|value| value.to_str().ok())
        .unwrap();
    assert!(session_cookie.contains(&format!("{PREVIEW_SESSION_COOKIE_NAME}={token}")));
    assert!(session_cookie.contains("HttpOnly; SameSite=Lax"));
    assert!(session_cookie.ends_with("; Secure"));

    let mut headers = HeaderMap::new();
    headers.insert(
        "host",
        HeaderValue::from_static("web.p1.preview.localhost:8000"),
    );
    headers.insert(
        "cookie",
        HeaderValue::from_str(&format!("{PREVIEW_SESSION_COOKIE_NAME}={token}; other=1")).unwrap(),
    );
    headers.insert(
        "authorization",
        HeaderValue::from_static("Bearer ms_sk_secret"),
    );
    headers.insert("x-forwarded-proto", HeaderValue::from_static("https"));
    headers.insert("x-trace-id", HeaderValue::from_static("trace-1"));
    let response = proxy_http_service_preview_host_response(
        &service,
        host,
        "/echo",
        Some("q=hello+world"),
        Method::POST,
        headers,
        b"payload".to_vec(),
    )
    .await
    .unwrap();

    assert_eq!(response.status(), StatusCode::FOUND);
    assert_eq!(
        response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|value| value.to_str().ok()),
        Some("text/plain")
    );
    assert_eq!(
        response
            .headers()
            .get(CACHE_CONTROL)
            .and_then(|value| value.to_str().ok()),
        Some("no-store")
    );
    assert_eq!(
        response
            .headers()
            .get(LOCATION)
            .and_then(|value| value.to_str().ok()),
        Some("https://web.p1.preview.localhost:8000/base/login?next=%2F")
    );
    let body = to_bytes(response.into_body(), HTTP_PROXY_BODY_LIMIT_BYTES)
        .await
        .unwrap();
    assert_eq!(body.as_ref(), b"preview-host");

    let request = rx
        .recv_timeout(Duration::from_secs(2))
        .expect("upstream request");
    assert!(request.starts_with("POST /base/echo?q=hello+world HTTP/1.1"));
    assert!(request.contains("x-trace-id: trace-1"));
    assert!(!request.to_ascii_lowercase().contains("authorization:"));
    assert!(!request.to_ascii_lowercase().contains("cookie:"));
    assert!(request.ends_with("payload"));
}
