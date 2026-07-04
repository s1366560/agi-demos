use super::*;

#[tokio::test]
async fn gateway_routes_preview_host_ws_to_rust_and_preserves_host() {
    let rust_mock = Router::new().fallback(get(ws_echo)).with_state("rust");
    let python_mock = Router::new().fallback(get(echo)).with_state("python");

    let rust_url = spawn(rust_mock).await;
    let python_url = spawn(python_mock).await;
    let gateway_url = spawn(app(gateway_state(Upstreams {
        rust: rust_url,
        python: python_url,
    })))
    .await;

    let ws_url =
        gateway_url.replacen("http://", "ws://", 1) + "/socket?ms_preview_session=session1";
    let mut request = ws_url.into_client_request().unwrap();
    request.headers_mut().insert(
        "host",
        HeaderValue::from_static("web.p1.preview.localhost:8000"),
    );
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static("memstack.auth, ms_sk_preview_ws"),
    );
    request.headers_mut().insert(
        "authorization",
        HeaderValue::from_static("Bearer ms_sk_preview_ws_header"),
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
        "{\"type\":\"preview_probe\"}".to_string(),
    ))
    .await
    .unwrap();
    let message = ws.next().await.unwrap().unwrap();
    let TungsteniteMessage::Text(body) = message else {
        panic!("expected text message, got {message:?}");
    };
    assert!(body.contains("\"backend\":\"rust\""), "{body}");
    assert!(body.contains("\"path\":\"/socket\""), "{body}");
    assert!(
        body.contains("\"host\":\"web.p1.preview.localhost:8000\""),
        "{body}"
    );
    assert!(
        body.contains("\"protocol\":\"memstack.auth, ms_sk_preview_ws\""),
        "{body}"
    );
    assert!(
        body.contains("\"auth\":\"Bearer ms_sk_preview_ws_header\""),
        "{body}"
    );
    assert!(body.contains("\"type\":\"preview_probe\""), "{body}");
}
