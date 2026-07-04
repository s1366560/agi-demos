use super::*;

#[tokio::test]
async fn gateway_proxies_p5_sandbox_ws_to_rust_with_protocol_auth_passthrough() {
    let rust_mock = Router::new()
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop/proxy/websockify",
            get(ws_echo),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal/proxy/ws",
            get(ws_echo),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/mcp/proxy",
            get(ws_echo),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws",
            get(ws_echo),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws/*path",
            get(ws_echo),
        )
        .fallback(get(echo))
        .with_state("rust");
    let python_mock = Router::new().fallback(get(echo)).with_state("python");

    let rust_url = spawn(rust_mock).await;
    let python_url = spawn(python_mock).await;
    let gateway_url = spawn(app(gateway_state(Upstreams {
        rust: rust_url,
        python: python_url,
    })))
    .await;

    for (path, protocol, expected_selected_protocol) in [
        (
            "/api/v1/projects/p1/sandbox/terminal/proxy/ws?session_id=term1",
            "memstack.auth, ms_sk_ws_p5",
            "memstack.auth",
        ),
        (
            "/api/v1/projects/p1/sandbox/mcp/proxy?token=ms_sk_ws_p5",
            "memstack.auth, ms_sk_ws_p5",
            "memstack.auth",
        ),
        (
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/ws?token=ms_sk_ws_p5",
            "memstack.auth, ms_sk_ws_p5",
            "memstack.auth",
        ),
        (
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/socket?token=ms_sk_ws_p5",
            "memstack.auth, ms_sk_ws_p5",
            "memstack.auth",
        ),
        (
            "/api/v1/projects/p1/sandbox/desktop/proxy/websockify?token=ms_sk_ws_p5",
            "binary",
            "binary",
        ),
    ] {
        let ws_url = gateway_url.replacen("http://", "ws://", 1) + path;
        let mut request = ws_url.into_client_request().unwrap();
        request.headers_mut().insert(
            "sec-websocket-protocol",
            HeaderValue::from_str(protocol).unwrap(),
        );
        request.headers_mut().insert(
            "authorization",
            HeaderValue::from_static("Bearer ms_sk_ws_header"),
        );

        let (mut ws, response) = connect_async(request).await.unwrap();
        assert_eq!(
            response
                .headers()
                .get("sec-websocket-protocol")
                .and_then(|v| v.to_str().ok()),
            Some(expected_selected_protocol),
            "{path}"
        );

        ws.send(TungsteniteMessage::Text(
            "{\"type\":\"p5_probe\"}".to_string(),
        ))
        .await
        .unwrap();
        let message = ws.next().await.unwrap().unwrap();
        let TungsteniteMessage::Text(body) = message else {
            panic!("expected text message, got {message:?}");
        };
        assert!(body.contains("\"backend\":\"rust\""), "{body}");
        assert!(
            body.contains("\"auth\":\"Bearer ms_sk_ws_header\""),
            "{body}"
        );
        assert!(body.contains("\"type\":\"p5_probe\""), "{body}");
        assert!(
            body.contains(&format!("\"protocol\":\"{protocol}\"")),
            "{body}"
        );
    }
}
