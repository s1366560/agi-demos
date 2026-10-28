// Included in browser_bridge::tests to exercise the actual upgraded sockets.
async fn assert_broker_closed<S>(socket: &mut tokio_tungstenite::WebSocketStream<S>)
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
{
    let next = tokio::time::timeout(Duration::from_secs(1), socket.next())
        .await
        .expect("stopping the bridge must close upgraded sockets promptly");
    assert!(matches!(
        next,
        None | Some(Err(_)) | Some(Ok(ClientMessage::Close(_)))
    ));
}

#[tokio::test]
async fn stop_closes_the_socket_even_before_hello_is_answered() {
    let bridge = start_test_bridge().await;
    let mut socket = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
        .await
        .unwrap();
    let (_, method, _) = broker_next_request(&mut socket).await;
    assert_eq!(method, "hello");
    bridge.runtime.stop();
    assert_broker_closed(&mut socket).await;
    std::fs::remove_dir_all(bridge.root).unwrap();
}

#[cfg(unix)]
#[tokio::test]
async fn stop_expires_tcp_and_unix_sessions_and_inflight_requests() {
    let bridge = start_test_bridge().await;
    let mut chrome = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
        .await
        .unwrap();
    broker_answer_hello(&mut chrome, Some(BACKEND_CHROME_EXTENSION)).await;
    let mut iab = connect_broker_unix(
        &bridge.socket_path(),
        &bridge.registry.ws_url,
        Some(&bridge.registry.token),
    )
    .await
    .unwrap();
    broker_answer_hello(&mut iab, Some(BACKEND_IAB)).await;
    wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION, BACKEND_IAB]).await;
    let server = bridge.runtime.server();
    let old_session = server.resolve_session(BACKEND_CHROME_EXTENSION).unwrap();
    let browser_id = old_session.browser_id.clone();
    let request_server = Arc::clone(&server);
    let request =
        tokio::spawn(async move { request_server.request(METHOD_GET_TABS, json!({})).await });
    let (_, method, _) = broker_next_request(&mut chrome).await;
    assert_eq!(method, METHOD_GET_TABS);
    let mut notifications = server.notifications.subscribe();

    bridge.runtime.stop();

    assert!(tokio::time::timeout(Duration::from_secs(1), request)
        .await
        .expect("stopping must fail pending requests promptly")
        .unwrap()
        .is_err());
    assert_broker_closed(&mut chrome).await;
    assert_broker_closed(&mut iab).await;
    assert_eq!(server.browser_inventory(), json!([]));
    assert!(server.connected_backends().is_empty());
    assert!(!server.broker_connected());
    assert!(server.resolve_session(&browser_id).is_err());
    assert!(server.request(METHOD_GET_TABS, json!({})).await.is_err());
    assert!(server.side_panel_session(&old_session).is_err());
    assert!(old_session.waiters.lock().unwrap().is_empty());
    assert!(old_session.closed.load(Ordering::SeqCst));

    // Old-generation callbacks cannot feed a retained endpoint after stop.
    while notifications.try_recv().is_ok() {}
    server
        .dispatch_inbound(
            &old_session,
            &json!({
                "jsonrpc":"2.0", "method": "onCDPEvent", "params":{"tabId":7}
            })
            .to_string(),
        )
        .await;
    assert!(notifications.try_recv().is_err());
    std::fs::remove_dir_all(bridge.root).unwrap();
}

#[cfg(unix)]
#[tokio::test]
async fn stop_revokes_side_panel_minting_from_a_previously_authorized_unix_session() {
    let (_state, minter, state_root) = side_panel_fixture();
    let bridge = start_test_bridge_full(Some(minter), BROKER_HEARTBEAT_INTERVAL).await;
    let mut socket = connect_broker_unix(
        &bridge.socket_path(),
        &bridge.registry.ws_url,
        Some(&bridge.registry.token),
    )
    .await
    .unwrap();
    broker_answer_hello(&mut socket, Some(BACKEND_CHROME_EXTENSION)).await;
    wait_for_backends(&bridge.runtime, &[BACKEND_CHROME_EXTENSION]).await;
    let server = bridge.runtime.server();
    let session = server.resolve_session(BACKEND_CHROME_EXTENSION).unwrap();
    assert!(server.side_panel_session(&session).is_ok());
    bridge.runtime.stop();
    let error = server.side_panel_session(&session).unwrap_err();
    assert_eq!(error.audit_outcome, "denied");
    assert_eq!(error.message, "browser bridge connection is closed");
    assert_broker_closed(&mut socket).await;
    std::fs::remove_dir_all(bridge.root).unwrap();
    std::fs::remove_dir_all(state_root).unwrap();
}
