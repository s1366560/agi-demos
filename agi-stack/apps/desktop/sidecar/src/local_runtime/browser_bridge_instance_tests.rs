// Included by browser_bridge::tests so the authenticated WebSocket fixtures
// exercise production connection registration, URL lookup and operation routing.
type InstanceSocket =
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;

async fn connect_instance(
    bridge: &TestBridge,
    backend: &str,
    profile: Uuid,
    instance: Uuid,
) -> (String, InstanceSocket) {
    let before = bridge.runtime.server.browser_inventory();
    let mut socket = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
        .await
        .unwrap();
    let (id, method, _) = broker_next_request(&mut socket).await;
    assert_eq!(method, "hello");
    broker_respond(&mut socket, id, json!({"backend":backend,"profileId":profile.to_string(),"extensionInstanceId":instance.to_string()})).await;
    for _ in 0..100 {
        let inventory = bridge.runtime.server.browser_inventory();
        let selected = inventory.as_array().unwrap().iter().find(|browser| {
            browser["metadata"]["profileId"] == profile.to_string()
                && browser["metadata"]["extensionInstanceId"] == instance.to_string()
                && !before
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|prior| prior["id"] == browser["id"])
        });
        if let Some(browser) = selected {
            return (browser["id"].as_str().unwrap().to_string(), socket);
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    panic!("browser instance was not admitted");
}

async fn instance_url(
    bridge: &TestBridge,
    socket: &mut InstanceSocket,
    browser: &str,
    expected: &str,
) {
    let host = bridge.runtime.browser_tool_host();
    let input = json!({"backend":browser,"tabId":7});
    let pending = tokio::spawn(async move { host.current_url_for_input(&input, 7).await });
    let (id, method, _) = broker_next_request(socket).await;
    assert_eq!(method, "getTabs");
    broker_respond(socket, id, json!({"tabs":[{"tabId":7,"url":expected}]})).await;
    assert_eq!(pending.await.unwrap().unwrap(), expected);
}

#[tokio::test]
async fn independent_profiles_instances_and_reconnects_never_rebind_tab_handles() {
    let bridge = start_test_bridge().await;
    let profile = Uuid::new_v4();
    let instance = Uuid::new_v4();
    let (first, mut first_socket) =
        connect_instance(&bridge, BACKEND_CHROME_EXTENSION, profile, instance).await;
    let host = bridge.runtime.browser_tool_host();
    let pinned = host
        .bind_input(
            "browser_navigate",
            &json!({"backend":"chrome","tabId":7,"url":"https://first.example/next"}),
        )
        .await
        .unwrap();
    assert_eq!(pinned["backend"], first);
    let (other_profile, mut other_socket) = connect_instance(
        &bridge,
        BACKEND_CHROME_EXTENSION,
        Uuid::new_v4(),
        Uuid::new_v4(),
    )
    .await;
    let (other_instance, mut sibling_socket) =
        connect_instance(&bridge, BACKEND_CHROME_EXTENSION, profile, Uuid::new_v4()).await;
    assert_eq!(
        bridge
            .runtime
            .server
            .browser_inventory()
            .as_array()
            .unwrap()
            .len(),
        3
    );
    assert!(host
        .bind_input("browser_navigate", &json!({"backend":"chrome","tabId":7}))
        .await
        .unwrap_err()
        .to_string()
        .contains("ambiguous"));
    instance_url(&bridge, &mut first_socket, &first, "https://first.example/").await;
    instance_url(
        &bridge,
        &mut other_socket,
        &other_profile,
        "https://second.example/",
    )
    .await;
    instance_url(
        &bridge,
        &mut sibling_socket,
        &other_instance,
        "https://sibling.example/",
    )
    .await;

    let (renewed, mut renewed_socket) =
        connect_instance(&bridge, BACKEND_CHROME_EXTENSION, profile, instance).await;
    assert_ne!(renewed, first);
    assert_eq!(
        bridge
            .runtime
            .server
            .browser_inventory()
            .as_array()
            .unwrap()
            .len(),
        3
    );
    assert!(host
        .call("browser_navigate", &pinned.to_string())
        .await
        .unwrap_err()
        .to_string()
        .contains("browser_instance_expired"));
    assert!(host
        .current_url_for_input(&pinned, 7)
        .await
        .unwrap_err()
        .to_string()
        .contains("browser_instance_expired"));
    // Tab id 7 on the new connection is never reached through the old handle.
    assert!(
        tokio::time::timeout(Duration::from_millis(30), renewed_socket.next())
            .await
            .is_err()
    );
    instance_url(
        &bridge,
        &mut renewed_socket,
        &renewed,
        "https://new-document.example/",
    )
    .await;
    instance_url(
        &bridge,
        &mut other_socket,
        &other_profile,
        "https://second.example/",
    )
    .await;
    bridge.runtime.stop();
    std::fs::remove_dir_all(bridge.root).unwrap();
}

#[tokio::test]
async fn broker_notifications_are_stamped_with_the_source_connection_identity() {
    let bridge = start_test_bridge().await;
    let (first, mut source) = connect_instance(
        &bridge,
        BACKEND_CHROME_EXTENSION,
        Uuid::new_v4(),
        Uuid::new_v4(),
    )
    .await;
    let (second, _other) = connect_instance(
        &bridge,
        BACKEND_EDGE_EXTENSION,
        Uuid::new_v4(),
        Uuid::new_v4(),
    )
    .await;
    let mut notifications = bridge.runtime.server.notifications.subscribe();
    source.send(ClientMessage::Text(json!({"jsonrpc":"2.0","method":"onCDPEvent","params":{
        "backend":second,"tabId":7,"method":"Page.frameNavigated","params":{"frame":{"id":"root","url":"https://first.example/"}}
    }}).to_string())).await.unwrap();
    let event = tokio::time::timeout(Duration::from_secs(2), notifications.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(event.params["backend"], first);
    assert_ne!(event.params["backend"], second);
    bridge.runtime.stop();
    std::fs::remove_dir_all(bridge.root).unwrap();
}

#[tokio::test]
async fn iab_reconnect_expires_old_identity_without_rebinding_to_chrome() {
    let bridge = start_test_bridge().await;
    let profile = Uuid::new_v4();
    let instance = Uuid::new_v4();
    let (old, _old_socket) = connect_instance(&bridge, BACKEND_IAB, profile, instance).await;
    let (chrome, mut chrome_socket) = connect_instance(
        &bridge,
        BACKEND_CHROME_EXTENSION,
        Uuid::new_v4(),
        Uuid::new_v4(),
    )
    .await;
    let (new, mut new_socket) = connect_instance(&bridge, BACKEND_IAB, profile, instance).await;
    let host = bridge.runtime.browser_tool_host();
    let bound = host
        .bind_input("browser_snapshot", &json!({"backend":"iab","tabId":7}))
        .await
        .unwrap();
    assert_eq!(bound["backend"], new);
    assert!(host
        .bind_input("browser_snapshot", &json!({"backend":old,"tabId":7}))
        .await
        .is_err());
    instance_url(&bridge, &mut new_socket, &new, "https://iab.example/").await;
    instance_url(
        &bridge,
        &mut chrome_socket,
        &chrome,
        "https://chrome.example/",
    )
    .await;
    bridge.runtime.stop();
    std::fs::remove_dir_all(bridge.root).unwrap();
}

#[tokio::test]
async fn iab_only_connection_exposes_the_runtime_browser_facade() {
    let bridge = start_test_bridge().await;
    let (id, mut socket) =
        connect_instance(&bridge, BACKEND_IAB, Uuid::new_v4(), Uuid::new_v4()).await;
    assert!(
        !bridge.runtime.broker_connected(),
        "no extension is connected"
    );
    let state = crate::local_runtime::tests::test_state("iab-only-facade");
    *state.browser_bridge.lock().unwrap() = Some(bridge.runtime);
    let host = state
        .connected_browser_tool_host()
        .expect("IAB is sufficient");
    let browsers: Value = serde_json::from_str(
        &host
            .call("browser_read_operation", r#"{"operation":"browsers.list"}"#)
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(browsers[0]["id"], id);
    assert_eq!(browsers[0]["type"], "iab");
    let request = tokio::spawn(async move {
        host.call(
            "browser_read_operation",
            &json!({
                "operation":"tabs.list", "browserId":id,
            })
            .to_string(),
        )
        .await
    });
    let (request_id, method, _) = broker_next_request(&mut socket).await;
    assert_eq!(method, "getTabs");
    broker_respond(
        &mut socket,
        request_id,
        json!({"tabs":[{"tabId":7,"url":"https://iab.example/"}]}),
    )
    .await;
    let result: Value = serde_json::from_str(&request.await.unwrap().unwrap()).unwrap();
    assert_eq!(result["tabs"][0]["tabId"], 7);
    drop(socket);
    for _ in 0..100 {
        if state.connected_browser_tool_host().is_none() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(state.connected_browser_tool_host().is_none());
    state.browser_bridge.lock().unwrap().take().unwrap().stop();
    std::fs::remove_dir_all(bridge.root).unwrap();
}
