use super::*;

#[tokio::test]
async fn real_mcp_call_publishes_scoped_html_app_event_and_redacts_inputs() {
    let root = test_root("app-event");
    let script = write_mock_server(&root);
    let source = fs::read_to_string(&script).unwrap().replace(
        "json.dumps(arguments, sort_keys=True)",
        "json.dumps({'message': arguments.get('message')})",
    );
    fs::write(&script, source).unwrap();
    let state = super::super::tests::test_state("app-event-session");
    let supervisor = Arc::clone(&state.mcp_supervisor);
    let active_scope = scope("local-project");
    let server = supervisor
        .create_server(
            &active_scope,
            definition("app-event", &python_executable(), &script, "normal"),
            "app-event-create",
        )
        .unwrap();
    supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .unwrap();
    let run = running_run(
        &state.session_store,
        &root,
        "app-event",
        DesktopPermissionProfile::FullAccess,
    )
    .unwrap();
    let host = McpAgentToolHost::new(
        Arc::clone(&supervisor),
        active_scope.clone(),
        run.id.clone(),
        None,
    )
    .unwrap()
    .with_app_events(
        Arc::clone(&state),
        run.conversation_id.clone(),
        run.message_id.clone(),
    );
    let tool = host
        .list_tools()
        .into_iter()
        .find(|name| name.starts_with("mcp__"))
        .unwrap();
    let output = host
        .call(
            &tool,
            r#"{"message":"real-app-marker","api_key":"must-not-persist"}"#,
        )
        .await
        .unwrap();
    assert!(output.contains("real-app-marker"));
    assert!(!output.contains("resource_html"));
    let events = state
        .session_store
        .timeline(&run.conversation_id, 30)
        .unwrap();
    let apps: Vec<_> = events
        .iter()
        .filter(|event| event["type"] == "mcp_app_result")
        .collect();
    assert_eq!(apps.len(), 1);
    let payload = &apps[0]["payload"];
    assert_eq!(payload["resource_html"], "<main>mock app</main>");
    assert_eq!(payload["resource_uri"], "ui://mock/index.html");
    assert_eq!(payload["project_id"], active_scope.project_id);
    assert_eq!(payload["tool_name"], "echo");
    assert!(payload["tool_result"]
        .to_string()
        .contains("real-app-marker"));
    assert!(!apps[0].to_string().contains("must-not-persist"));
    assert!(host.call("unknown-alias", "{}").await.is_err());
    let (_, lease) = supervisor.acquire_catalog(&active_scope).unwrap();
    assert!(supervisor
        .read_resource_pinned(
            &lease,
            &scope("different-project"),
            &server.id,
            "ui://mock/index.html"
        )
        .await
        .is_err());
    drop(host);
    drop(lease);
    let server = supervisor
        .server(&active_scope, &server.id)
        .unwrap()
        .unwrap();
    supervisor
        .delete_server(
            &active_scope,
            &server.id,
            server.revision,
            "app-event-cleanup",
        )
        .unwrap();
    let _ = fs::remove_dir_all(root);
}

#[tokio::test]
async fn app_metadata_and_html_follow_lease_when_retired_between_catalog_and_app_capture() {
    let root = test_root("app-generation");
    let script = write_mock_server(&root);
    let state = super::super::tests::test_state("app-generation-session");
    let supervisor = Arc::clone(&state.mcp_supervisor);
    let active_scope = scope("local-project");
    let server = supervisor
        .create_server(
            &active_scope,
            definition("app-generation", &python_executable(), &script, "normal"),
            "app-generation-create",
        )
        .unwrap();
    supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .unwrap();
    supervisor
        .stage_marketplace_server(&active_scope, &server.id)
        .unwrap();
    supervisor
        .publish_marketplace_generation(&active_scope, &[server.id.clone()], &[])
        .unwrap();
    let (_, lease) = supervisor.acquire_catalog(&active_scope).unwrap();
    // Force the exact race: disable/update publication after tools were captured,
    // before App metadata is captured. The old lease must remain authoritative.
    supervisor
        .publish_marketplace_generation(&active_scope, &[], &[server.id.clone()])
        .unwrap();
    assert!(supervisor.list_apps(&active_scope).unwrap().is_empty());
    let apps = supervisor.apps_pinned(&lease, &active_scope).unwrap();
    assert_eq!(apps.len(), 1);
    assert_eq!(apps[0].server_id, server.id);
    let html = supervisor
        .read_resource_pinned(
            &lease,
            &active_scope,
            &server.id,
            apps[0].resource_uri.as_deref().unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(html[0]["text"], "<main>mock app</main>");
    assert!(supervisor
        .apps_pinned(&lease, &scope("another-project"))
        .is_err());
    drop(lease);
    assert!(supervisor
        .server(&active_scope, &server.id)
        .unwrap()
        .is_none());
    let _ = fs::remove_dir_all(root);
}

#[tokio::test]
async fn app_resource_failure_emits_error_without_losing_real_tool_result() {
    let root = test_root("app-failure");
    let script = write_mock_server(&root);
    let source = fs::read_to_string(&script)
        .unwrap()
        .replace("\"uri\": uri,", "\"uri\": \"ui://wrong/resource\",");
    fs::write(&script, source).unwrap();
    let state = super::super::tests::test_state("app-failure-session");
    let supervisor = Arc::clone(&state.mcp_supervisor);
    let active_scope = scope("local-project");
    let server = supervisor
        .create_server(
            &active_scope,
            definition("app-failure", &python_executable(), &script, "normal"),
            "app-failure-create",
        )
        .unwrap();
    supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .unwrap();
    let run = running_run(
        &state.session_store,
        &root,
        "app-failure",
        DesktopPermissionProfile::FullAccess,
    )
    .unwrap();
    let host = McpAgentToolHost::new(
        Arc::clone(&supervisor),
        active_scope.clone(),
        run.id.clone(),
        None,
    )
    .unwrap()
    .with_app_events(
        Arc::clone(&state),
        run.conversation_id.clone(),
        run.message_id.clone(),
    );
    let tool = host
        .list_tools()
        .into_iter()
        .find(|name| name.starts_with("mcp__"))
        .unwrap();
    let result = host
        .call(&tool, r#"{"message":"tool-still-succeeded"}"#)
        .await
        .unwrap();
    assert!(result.contains("tool-still-succeeded"));
    let events = state
        .session_store
        .timeline(&run.conversation_id, 30)
        .unwrap();
    let app = events
        .iter()
        .find(|event| event["type"] == "mcp_app_result")
        .unwrap();
    assert_eq!(app["payload"]["error"], "local_mcp_app_html_unavailable");
    assert!(app["payload"]["resource_html"].is_null());
    assert!(app["payload"]["resource_uri"].is_null());
    drop(host);
    let server = supervisor
        .server(&active_scope, &server.id)
        .unwrap()
        .unwrap();
    supervisor
        .delete_server(
            &active_scope,
            &server.id,
            server.revision,
            "app-failure-cleanup",
        )
        .unwrap();
    let _ = fs::remove_dir_all(root);
}
