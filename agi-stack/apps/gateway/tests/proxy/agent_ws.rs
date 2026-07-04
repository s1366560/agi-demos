use super::*;

#[tokio::test]
async fn gateway_proxies_agent_ws_to_rust_with_protocol_auth_passthrough() {
    let rust_mock = Router::new()
        .route("/api/v1/agent/ws", get(ws_echo))
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

    let ws_url = gateway_url.replacen("http://", "ws://", 1) + "/api/v1/agent/ws?session_id=s1";
    let mut request = ws_url.into_client_request().unwrap();
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static("memstack.auth, ms_sk_ws_e2e"),
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
        Some("memstack.auth")
    );

    ws.send(TungsteniteMessage::Text(
        "{\"type\":\"heartbeat\"}".to_string(),
    ))
    .await
    .unwrap();
    let message = ws.next().await.unwrap().unwrap();
    let TungsteniteMessage::Text(body) = message else {
        panic!("expected text message, got {message:?}");
    };
    assert!(body.contains("\"backend\":\"rust\""), "{body}");
    assert!(body.contains("\"path\":\"/api/v1/agent/ws\""), "{body}");
    assert!(
        body.contains("\"protocol\":\"memstack.auth, ms_sk_ws_e2e\""),
        "{body}"
    );
    assert!(
        body.contains("\"auth\":\"Bearer ms_sk_ws_header\""),
        "{body}"
    );
    assert!(body.contains("\"type\":\"heartbeat\""), "{body}");
}
