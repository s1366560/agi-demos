use super::super::*;
use super::*;

async fn spawn_http_service_ws_upstream(
) -> (String, std::sync::mpsc::Receiver<(String, Option<String>)>) {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .unwrap();
    let addr = listener.local_addr().unwrap();
    let (tx, rx) = std::sync::mpsc::channel();
    tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        // accept_hdr_async fixes this callback result type to tungstenite's ErrorResponse.
        #[allow(clippy::result_large_err)]
        let ws =
            tokio_tungstenite::accept_hdr_async(stream, |req: &WsHandshakeRequest, response| {
                capture_ws_origin_request(req, response, &tx)
            })
            .await
            .unwrap();
        let (mut sink, mut stream) = ws.split();
        while let Some(Ok(message)) = stream.next().await {
            match message {
                TungsteniteMessage::Text(text) => {
                    sink.send(TungsteniteMessage::Text(format!("echo:{text}")))
                        .await
                        .unwrap();
                    break;
                }
                TungsteniteMessage::Binary(binary) => {
                    sink.send(TungsteniteMessage::Binary(binary)).await.unwrap();
                    break;
                }
                TungsteniteMessage::Close(close) => {
                    let _ = sink.send(TungsteniteMessage::Close(close)).await;
                    break;
                }
                _ => {}
            }
        }
    });
    (format!("http://{addr}/base"), rx)
}
async fn spawn_http_service_ws_proxy(ws_target: String, origin: String) -> String {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .unwrap();
    let addr = listener.local_addr().unwrap();
    let app = Router::new().route(
        "/proxy/ws",
        get(move |ws: WebSocketUpgrade| {
            let ws_target = ws_target.clone();
            let origin = origin.clone();
            async move {
                ws.protocols([WEBSOCKET_AUTH_SUBPROTOCOL])
                    .on_upgrade(move |socket| {
                        proxy_http_service_ws_session(socket, ws_target, origin)
                    })
                    .into_response()
            }
        }),
    );
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    format!("ws://{addr}/proxy/ws")
}
async fn spawn_desktop_ws_upstream() -> (
    String,
    std::sync::mpsc::Receiver<(String, Option<String>, Option<String>)>,
) {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .unwrap();
    let addr = listener.local_addr().unwrap();
    let (tx, rx) = std::sync::mpsc::channel();
    tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        // accept_hdr_async fixes this callback result type to tungstenite's ErrorResponse.
        #[allow(clippy::result_large_err)]
        let ws =
            tokio_tungstenite::accept_hdr_async(stream, |req: &WsHandshakeRequest, response| {
                capture_desktop_ws_request(req, response, &tx)
            })
            .await
            .unwrap();
        let (mut sink, mut stream) = ws.split();
        while let Some(Ok(message)) = stream.next().await {
            match message {
                TungsteniteMessage::Text(text) => {
                    sink.send(TungsteniteMessage::Text(format!("echo:{text}")))
                        .await
                        .unwrap();
                    break;
                }
                TungsteniteMessage::Binary(binary) => {
                    sink.send(TungsteniteMessage::Binary(binary)).await.unwrap();
                    break;
                }
                TungsteniteMessage::Close(close) => {
                    let _ = sink.send(TungsteniteMessage::Close(close)).await;
                    break;
                }
                _ => {}
            }
        }
    });
    (format!("ws://{addr}/base"), rx)
}
async fn spawn_desktop_ws_proxy(ws_target: String, origin: String) -> String {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .unwrap();
    let addr = listener.local_addr().unwrap();
    let app = Router::new().route(
        "/desktop/proxy/websockify",
        get(move |ws: WebSocketUpgrade| {
            let ws_target = ws_target.clone();
            let origin = origin.clone();
            async move {
                websocket_upgrade_with_desktop_protocol(ws)
                    .on_upgrade(move |socket| proxy_desktop_ws_session(socket, ws_target, origin))
                    .into_response()
            }
        }),
    );
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    format!("ws://{addr}/desktop/proxy/websockify")
}
async fn spawn_terminal_ws_upstream() -> (
    String,
    std::sync::mpsc::Receiver<(String, Option<String>)>,
    std::sync::mpsc::Receiver<Vec<u8>>,
) {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .unwrap();
    let addr = listener.local_addr().unwrap();
    let (request_tx, request_rx) = std::sync::mpsc::channel();
    let (frame_tx, frame_rx) = std::sync::mpsc::channel();
    tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        // accept_hdr_async fixes this callback result type to tungstenite's ErrorResponse.
        #[allow(clippy::result_large_err)]
        let ws =
            tokio_tungstenite::accept_hdr_async(stream, |req: &WsHandshakeRequest, response| {
                capture_ws_origin_request(req, response, &request_tx)
            })
            .await
            .unwrap();
        let (mut sink, mut stream) = ws.split();
        while let Some(Ok(message)) = stream.next().await {
            match message {
                TungsteniteMessage::Text(text) => {
                    let frame = text.as_bytes().to_vec();
                    frame_tx.send(frame.clone()).unwrap();
                    if frame.first() == Some(&TTYD_INPUT_COMMAND) {
                        let mut output = b"0echo:".to_vec();
                        output.extend_from_slice(&frame[1..]);
                        sink.send(TungsteniteMessage::Binary(output)).await.unwrap();
                        break;
                    }
                }
                TungsteniteMessage::Binary(binary) => {
                    let frame = binary.to_vec();
                    frame_tx.send(frame.clone()).unwrap();
                    if frame.first() == Some(&TTYD_INPUT_COMMAND) {
                        let mut output = b"0echo:".to_vec();
                        output.extend_from_slice(&frame[1..]);
                        sink.send(TungsteniteMessage::Binary(output)).await.unwrap();
                        break;
                    }
                }
                TungsteniteMessage::Close(close) => {
                    let _ = sink.send(TungsteniteMessage::Close(close)).await;
                    break;
                }
                _ => {}
            }
        }
    });
    (format!("ws://{addr}/term"), request_rx, frame_rx)
}
async fn spawn_terminal_ws_proxy(
    ws_target: String,
    origin: String,
    registry: SharedHttpServiceRegistry,
    project_id: String,
) -> String {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .unwrap();
    let addr = listener.local_addr().unwrap();
    let app = Router::new().route(
        "/terminal/proxy/ws",
        get(
            move |ws: WebSocketUpgrade,
                  headers: HeaderMap,
                  Query(query): Query<TerminalWsQuery>| {
                let ws_target = ws_target.clone();
                let origin = origin.clone();
                let registry = registry.clone();
                let project_id = project_id.clone();
                async move {
                    let session_id = query.session_id.unwrap_or_else(new_terminal_session_id);
                    let initial_size = registry
                        .get_terminal_session(&project_id, &session_id)
                        .await
                        .unwrap()
                        .map(|session| session.size())
                        .unwrap_or_default();
                    let recorder = TerminalSessionRecorder::new(
                        registry,
                        project_id,
                        session_id.clone(),
                        terminal_session_ttl_seconds(),
                    );
                    websocket_upgrade_with_auth_protocol(ws, &headers)
                        .on_upgrade(move |socket| {
                            proxy_terminal_ws_session(
                                socket,
                                ws_target,
                                origin,
                                session_id,
                                initial_size,
                                recorder,
                            )
                        })
                        .into_response()
                }
            },
        ),
    );
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    format!("ws://{addr}/terminal/proxy/ws")
}
async fn spawn_mcp_ws_upstream() -> (String, std::sync::mpsc::Receiver<String>) {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .unwrap();
    let addr = listener.local_addr().unwrap();
    let (tx, rx) = std::sync::mpsc::channel();
    tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        // accept_hdr_async fixes this callback result type to tungstenite's ErrorResponse.
        #[allow(clippy::result_large_err)]
        let ws =
            tokio_tungstenite::accept_hdr_async(stream, |req: &WsHandshakeRequest, response| {
                capture_mcp_ws_request(req, response, &tx)
            })
            .await
            .unwrap();
        let (mut sink, mut stream) = ws.split();
        while let Some(Ok(message)) = stream.next().await {
            if matches!(message, TungsteniteMessage::Text(_)) {
                let response = json!({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "contents": [{
                            "uri": "ui://index.html",
                            "mimeType": "text/html",
                            "text": "<html></html>"
                        }]
                    }
                });
                sink.send(TungsteniteMessage::Text(response.to_string()))
                    .await
                    .unwrap();
                break;
            }
        }
    });
    (format!("ws://{addr}/mcp/sandbox?auth=keep"), rx)
}
async fn spawn_mcp_ws_proxy(ws_target: String) -> String {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .unwrap();
    let addr = listener.local_addr().unwrap();
    let app = Router::new().route(
        "/sandbox/mcp/proxy",
        get(move |ws: WebSocketUpgrade, headers: HeaderMap| {
            let ws_target = ws_target.clone();
            async move {
                websocket_upgrade_with_auth_protocol(ws, &headers)
                    .on_upgrade(move |socket| proxy_mcp_ws_session(socket, ws_target))
                    .into_response()
            }
        }),
    );
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    format!("ws://{addr}/sandbox/mcp/proxy")
}
async fn spawn_http_preview_host_ws_proxy(sandboxes: Arc<ProjectSandboxService>) -> String {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .unwrap();
    let addr = listener.local_addr().unwrap();
    let app = Router::new().route(
        "/*path",
        get(move |ws: WebSocketUpgrade, headers: HeaderMap, uri: Uri| {
            let sandboxes = sandboxes.clone();
            async move {
                let host_header = headers
                    .get("host")
                    .and_then(|value| value.to_str().ok())
                    .unwrap_or_default()
                    .to_string();
                let raw_query = uri.query().map(str::to_string);
                proxy_http_service_preview_host_ws_response(
                    &sandboxes,
                    &host_header,
                    uri.path(),
                    raw_query.as_deref(),
                    headers,
                    ws,
                )
                .await
            }
        }),
    );
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    format!("ws://{addr}")
}
#[tokio::test]
async fn http_service_ws_proxy_relays_frames_and_filters_token_query() {
    let (service_url, rx) = spawn_http_service_ws_upstream().await;
    let ws_target = build_upstream_ws_url(
        &service_url,
        "socket",
        Some("token=ms_sk_secret&q=hello+world"),
    )
    .unwrap();
    let proxy_url = spawn_http_service_ws_proxy(ws_target, service_url.clone()).await;
    let mut request = proxy_url.into_client_request().unwrap();
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static(WEBSOCKET_AUTH_SUBPROTOCOL),
    );

    let (mut client, response) = connect_async(request).await.unwrap();
    assert_eq!(
        response
            .headers()
            .get("sec-websocket-protocol")
            .and_then(|value| value.to_str().ok()),
        Some(WEBSOCKET_AUTH_SUBPROTOCOL)
    );

    client
        .send(TungsteniteMessage::Text("ping".into()))
        .await
        .unwrap();
    let reply = client.next().await.unwrap().unwrap();
    assert_eq!(reply, TungsteniteMessage::Text("echo:ping".into()));

    let (uri, origin) = rx
        .recv_timeout(Duration::from_secs(2))
        .expect("upstream ws request");
    assert_eq!(uri, "/base/socket?q=hello+world");
    assert_eq!(origin.as_deref(), Some(service_url.as_str()));
}
#[tokio::test]
async fn desktop_ws_proxy_relays_binary_and_uses_binary_subprotocol() {
    let (desktop_url, rx) = spawn_desktop_ws_upstream().await;
    let ws_target = build_desktop_websocket_target(&desktop_url).unwrap();
    let origin = desktop_websocket_origin(&desktop_url, &ws_target);
    let proxy_url = spawn_desktop_ws_proxy(ws_target, origin).await;
    let mut request = proxy_url.into_client_request().unwrap();
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static(DESKTOP_WEBSOCKET_SUBPROTOCOL),
    );

    let (mut client, response) = connect_async(request).await.unwrap();
    assert_eq!(
        response
            .headers()
            .get("sec-websocket-protocol")
            .and_then(|value| value.to_str().ok()),
        Some(DESKTOP_WEBSOCKET_SUBPROTOCOL)
    );

    client
        .send(TungsteniteMessage::Binary(vec![1_u8, 2, 3]))
        .await
        .unwrap();
    let reply = client.next().await.unwrap().unwrap();
    assert_eq!(reply, TungsteniteMessage::Binary(vec![1_u8, 2, 3]));

    let (uri, origin, protocol) = rx
        .recv_timeout(Duration::from_secs(2))
        .expect("upstream desktop ws request");
    assert_eq!(uri, "/base/websockify");
    assert_eq!(origin.as_deref(), Some(desktop_url.as_str()));
    assert_eq!(protocol.as_deref(), Some(DESKTOP_WEBSOCKET_SUBPROTOCOL));
}
#[tokio::test]
async fn terminal_ws_proxy_speaks_python_envelope_over_ttyd() {
    let (terminal_url, request_rx, frame_rx) = spawn_terminal_ws_upstream().await;
    let ws_target = build_terminal_websocket_target(&terminal_url).unwrap();
    let origin = terminal_websocket_origin(&terminal_url, &ws_target);
    let registry = in_memory_http_service_registry();
    let project_id = "project-terminal".to_string();
    registry
        .upsert_terminal_session(
            TerminalSessionRecord::new(
                project_id.clone(),
                "session-secret".to_string(),
                TerminalSize {
                    cols: 100,
                    rows: 32,
                },
                false,
                now_ms(),
                terminal_session_ttl_seconds(),
            ),
            terminal_session_ttl_seconds(),
        )
        .await
        .unwrap();
    let proxy_url =
        spawn_terminal_ws_proxy(ws_target, origin, registry.clone(), project_id.clone()).await;
    let mut request = format!("{proxy_url}?session_id=session-secret")
        .into_client_request()
        .unwrap();
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static(WEBSOCKET_AUTH_SUBPROTOCOL),
    );

    let (mut client, response) = connect_async(request).await.unwrap();
    assert_eq!(
        response
            .headers()
            .get("sec-websocket-protocol")
            .and_then(|value| value.to_str().ok()),
        Some(WEBSOCKET_AUTH_SUBPROTOCOL)
    );

    let connected = client.next().await.unwrap().unwrap();
    let TungsteniteMessage::Text(connected) = connected else {
        panic!("expected connected text frame");
    };
    let connected: Value = serde_json::from_str(&connected).unwrap();
    assert_eq!(connected["type"], "connected");
    assert_eq!(connected["session_id"], "session-secret");
    assert_eq!(connected["cols"], 100);
    assert_eq!(connected["rows"], 32);
    let stored = registry
        .get_terminal_session(&project_id, "session-secret")
        .await
        .unwrap()
        .unwrap();
    assert!(stored.connected);
    assert_eq!(
        stored.size(),
        TerminalSize {
            cols: 100,
            rows: 32
        }
    );

    client
        .send(TungsteniteMessage::Text(
            json!({ "type": "ping" }).to_string(),
        ))
        .await
        .unwrap();
    let pong = client.next().await.unwrap().unwrap();
    let TungsteniteMessage::Text(pong) = pong else {
        panic!("expected pong text frame");
    };
    let pong: Value = serde_json::from_str(&pong).unwrap();
    assert_eq!(pong["type"], "pong");

    client
        .send(TungsteniteMessage::Text(
            json!({ "type": "resize", "cols": 120, "rows": 40 }).to_string(),
        ))
        .await
        .unwrap();
    client
        .send(TungsteniteMessage::Text(
            json!({ "type": "input", "data": "ls\n" }).to_string(),
        ))
        .await
        .unwrap();
    let output = client.next().await.unwrap().unwrap();
    let TungsteniteMessage::Text(output) = output else {
        panic!("expected output text frame");
    };
    let output: Value = serde_json::from_str(&output).unwrap();
    assert_eq!(output["type"], "output");
    assert_eq!(output["data"], "echo:ls\n");

    let (uri, origin) = request_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("upstream terminal ws request");
    assert_eq!(uri, "/term");
    assert_eq!(origin.as_deref(), Some(terminal_url.as_str()));

    let init = frame_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("ttyd init frame");
    let init: Value = serde_json::from_slice(&init).unwrap();
    assert_eq!(init["AuthToken"], "");
    assert_eq!(init["columns"], 100);
    assert_eq!(init["rows"], 32);

    let resize = frame_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("ttyd resize frame");
    assert_eq!(resize.first().copied(), Some(TTYD_RESIZE_COMMAND));
    let resize: Value = serde_json::from_slice(&resize[1..]).unwrap();
    assert_eq!(resize["columns"], 120);
    assert_eq!(resize["rows"], 40);

    let input = frame_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("ttyd input frame");
    assert_eq!(input.first().copied(), Some(TTYD_INPUT_COMMAND));
    assert_eq!(&input[1..], b"ls\n");
    drop(client);

    let mut final_session = None;
    for _ in 0..20 {
        let session = registry
            .get_terminal_session(&project_id, "session-secret")
            .await
            .unwrap()
            .unwrap();
        if !session.connected
            && session.size()
                == (TerminalSize {
                    cols: 120,
                    rows: 40,
                })
        {
            final_session = Some(session);
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let final_session = final_session.expect("terminal session should be marked disconnected");
    assert_eq!(final_session.session_id, "session-secret");
}
#[tokio::test]
async fn mcp_ws_proxy_relays_jsonrpc_and_normalizes_app_resource_mime() {
    let (mcp_url, rx) = spawn_mcp_ws_upstream().await;
    let upstream_token = agistack_adapters_secrets::generate_urlsafe_token(32);
    let ws_target = append_mcp_upstream_token(
        &build_mcp_websocket_target(&mcp_url).unwrap(),
        &upstream_token,
    )
    .unwrap();
    let proxy_url = spawn_mcp_ws_proxy(ws_target).await;
    let (mut client, _response) = connect_async(&proxy_url).await.unwrap();
    client
        .send(TungsteniteMessage::Text(
            json!({ "jsonrpc": "2.0", "id": 1, "method": "resources/read" }).to_string(),
        ))
        .await
        .unwrap();

    let reply = client.next().await.unwrap().unwrap();
    let TungsteniteMessage::Text(text) = reply else {
        panic!("expected json-rpc text frame");
    };
    let parsed: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(
        parsed["result"]["contents"][0]["mimeType"],
        MCP_APP_MIME_TYPE
    );

    let uri = rx
        .recv_timeout(Duration::from_secs(2))
        .expect("upstream mcp ws request");
    assert!(uri.starts_with("/mcp/sandbox?"), "unexpected uri: {uri}");
    let query = uri
        .split_once('?')
        .map(|(_, query)| query)
        .unwrap_or_default();
    let params: BTreeMap<String, String> = url::form_urlencoded::parse(query.as_bytes())
        .map(|(key, value)| (key.into_owned(), value.into_owned()))
        .collect();
    assert_eq!(params.get("auth").map(String::as_str), Some("keep"));
    assert_eq!(
        params.get(MCP_UPSTREAM_TOKEN_QUERY_PARAM),
        Some(&upstream_token)
    );
    assert!(agistack_parity::is_urlsafe_token_32(&upstream_token));
}
#[tokio::test]
async fn http_service_preview_host_ws_proxy_relays_and_filters_session_query() {
    let (service_url, rx) = spawn_http_service_ws_upstream().await;
    let service = Arc::new(ProjectSandboxService::new(
        Arc::new(InMemoryContainerRuntime::new()),
        "redis:7-alpine",
    ));
    service
        .upsert_http_service(
            "p1",
            HttpServiceProxyInfo {
                service_id: "web".to_string(),
                name: "Docs".to_string(),
                source_type: HttpServiceSourceType::SandboxInternal,
                status: "running".to_string(),
                service_url: service_url.clone(),
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
    let proxy_url = spawn_http_preview_host_ws_proxy(service.clone()).await;
    let mut request =
        format!("{proxy_url}/socket?{PREVIEW_SESSION_QUERY_PARAM}={token}&q=hello+world")
            .into_client_request()
            .unwrap();
    request.headers_mut().insert(
        "host",
        HeaderValue::from_static("web.p1.preview.localhost:8000"),
    );
    request
        .headers_mut()
        .insert("origin", HeaderValue::from_static("https://frontend.test"));
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static(WEBSOCKET_AUTH_SUBPROTOCOL),
    );

    let (mut client, response) = connect_async(request).await.unwrap();
    assert_eq!(
        response
            .headers()
            .get("sec-websocket-protocol")
            .and_then(|value| value.to_str().ok()),
        Some(WEBSOCKET_AUTH_SUBPROTOCOL)
    );

    client
        .send(TungsteniteMessage::Text("preview".into()))
        .await
        .unwrap();
    let reply = client.next().await.unwrap().unwrap();
    assert_eq!(reply, TungsteniteMessage::Text("echo:preview".into()));

    let (uri, origin) = rx
        .recv_timeout(Duration::from_secs(2))
        .expect("upstream preview host ws request");
    assert_eq!(uri, "/base/socket?q=hello+world");
    assert_eq!(origin.as_deref(), Some("https://frontend.test"));
}
