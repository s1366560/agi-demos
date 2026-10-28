use super::*;

#[tokio::test]
async fn observing_another_window_rotates_binding_and_retires_old_snapshot_and_telemetry() {
    let helper = Helper::new("target_switch");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let host = CuaToolHost::new(client.clone()).with_context(context());
    let input = client.subscribe_input_telemetry();
    let old: Value = serde_json::from_str(
        &host
            .call(
                "computer_get_app_state",
                r#"{"app":"com.example.app","window_id":"window-1"}"#,
            )
            .await
            .unwrap(),
    )
    .unwrap();
    client
        .request("emit_input", json!({"events":[input_event(1)]}))
        .await
        .unwrap();
    assert_eq!(
        input.borrow()["session"].input_generation,
        "fixture-generation"
    );

    // Exercise the production session client before a new observation is cached.
    let next = client
        .request_in_session(
            &context(),
            "get_app_state",
            json!({"app":"com.example.app","window_id":"window-2"}),
        )
        .await
        .unwrap();
    assert_eq!(next["input_generation"], "window-generation-2");
    assert_eq!(
        client.current_input_generation("session").as_deref(),
        Some("window-generation-2")
    );
    assert!(input.borrow().is_empty());
    let old_action = json!({"app":"com.example.app","window_id":"window-1","snapshot_id":old["snapshot_id"],"element_index":0});
    assert!(host
        .call("computer_click", &old_action.to_string())
        .await
        .unwrap_err()
        .to_string()
        .contains("cua_snapshot_missing"));
    assert_eq!(helper.count("actions"), 0);

    client
        .request("emit_input", json!({"events":[input_event(2)]}))
        .await
        .unwrap();
    assert!(input.borrow().is_empty());
    let mut fresh = input_event(1);
    fresh["input_generation"] = json!("window-generation-2");
    fresh["target_window_id"] = json!("window-2");
    fresh["virtual_cursor"]["window_id"] = json!("window-2");
    client
        .request("emit_input", json!({"events":[fresh]}))
        .await
        .unwrap();
    assert_eq!(input.borrow()["session"].sequence, 1);
    let state: Value = serde_json::from_str(
        &host
            .call(
                "computer_get_app_state",
                r#"{"app":"com.example.app","window_id":"window-2"}"#,
            )
            .await
            .unwrap(),
    )
    .unwrap();
    let action = json!({"app":"com.example.app","window_id":"window-2","snapshot_id":state["snapshot_id"],"element_index":0});
    host.call("computer_click", &action.to_string())
        .await
        .unwrap();
    assert_eq!(helper.count("actions"), 1);
    assert_eq!(helper.count("pids"), 1);
    client.shutdown().await;
}

#[tokio::test]
async fn action_responses_cannot_rotate_input_generation() {
    let helper = Helper::new("action_generation");
    let client = helper.client(Duration::from_secs(2));
    let error = client
        .request_in_session(
            &context(),
            "perform_action",
            json!({"action":{"kind":"click"}}),
        )
        .await
        .unwrap_err();
    assert!(
        matches!(error, CuaError::InvalidResponse(message) if message == "stale native input generation")
    );
    assert_eq!(
        client.current_input_generation("session").as_deref(),
        Some("fixture-generation")
    );
    client.shutdown().await;
}

#[tokio::test]
async fn delayed_observation_cannot_replace_a_newer_lifecycle_generation() {
    let helper = Helper::new("delayed_observation");
    let client = Arc::new(helper.client(Duration::from_secs(3)));
    client
        .request_in_session(
            &context(),
            "get_app_state",
            json!({"app":"com.example.app","window_id":"window-1"}),
        )
        .await
        .unwrap();
    let observation = {
        let client = client.clone();
        tokio::spawn(async move {
            client
                .request_in_session(
                    &context(),
                    "get_app_state",
                    json!({"app":"com.example.app","window_id":"window-2"}),
                )
                .await
        })
    };
    tokio::time::timeout(Duration::from_secs(1), async {
        while !helper.root.join("observation_waiting").is_file() {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    client
        .request_in_session(&context(), "resume_session", json!({}))
        .await
        .unwrap();
    client
        .request("flush_observation", json!({}))
        .await
        .unwrap();
    assert!(
        matches!(observation.await.unwrap(), Err(CuaError::InvalidResponse(message)) if message == "stale native input generation")
    );
    assert_eq!(
        client.current_input_generation("session").as_deref(),
        Some("resumed-generation")
    );
    client.shutdown().await;
}

#[tokio::test]
async fn shutdown_fences_old_and_new_admission_but_allows_owned_cleanup() {
    let helper = Helper::new("normal");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    client
        .request_in_session(&context(), "list_apps", json!({}))
        .await
        .unwrap();
    client.begin_shutdown();
    assert!(client
        .request_in_session(&context(), "list_apps", json!({}))
        .await
        .is_err());
    let mut fresh = context();
    fresh.session_id = "new-session".into();
    assert!(client
        .request_in_session(&fresh, "list_apps", json!({}))
        .await
        .is_err());
    client.stop_all_sessions("session_ended").await;
    client.end_session("session").await.unwrap();
    assert!(client.current_input_generation("session").is_none());
    client.shutdown().await;
    assert!(client
        .request_in_session(&fresh, "list_apps", json!({}))
        .await
        .is_err());
    assert_eq!(helper.count("pids"), 1);
}
