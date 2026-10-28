//! Local callback failures retain their original reason before dispatch.
use super::super::callback_origin::CallbackOrigin;
use super::*;

async fn callback_target(
    fixture: &Fixture,
    id: &str,
    captured: &AppTab,
    authority: &ExecutionAuthority,
) -> CoreResult<Option<(ExecutionScope, String)>> {
    let binding = captured.binding.clone();
    let origin = CallbackOrigin::capture(id, captured, &binding).unwrap();
    let tool = legacy_exposed_tool_name(&fixture.server_id, &binding.tool_name);
    captured
        .identity
        .for_tool(
            &tool,
            origin.scope(async {
                fixture.state.mcp_app_automation.cloud_callback_target(
                    &fixture.state,
                    authority,
                    &tool,
                )
            }),
        )
        .await
}

async fn update_server(fixture: &Fixture, enabled: bool) {
    let server = fixture
        .state
        .mcp_supervisor
        .server(&fixture.scope, &fixture.server_id)
        .unwrap()
        .unwrap();
    fixture
        .state
        .mcp_supervisor
        .update_server(
            &fixture.scope,
            &fixture.server_id,
            McpServerDefinitionInput {
                name: server.name,
                description: Some("callback error regression".into()),
                transport: server.transport,
                command: server.command,
                cwd: server.cwd,
                vault_env_refs: server.vault_env_refs,
                enabled,
            },
            server.revision,
            "callback-error-update",
        )
        .unwrap();
    if enabled {
        fixture
            .state
            .mcp_supervisor
            .list_tools(&fixture.scope, &fixture.server_id)
            .await
            .unwrap();
    }
}

async fn assert_local_error(case: &str, expected: &str) {
    let fixture = Fixture::new().await;
    let id = fixture.render("render_main").await;
    fixture.attach(&id).await;
    let captured = fixture.state.mcp_app_automation.tabs.lock().unwrap()[&id].clone();
    match case {
        "disabled" => update_server(&fixture, false).await,
        "catalog" => update_server(&fixture, true).await,
        "expired" => fixture
            .state
            .mcp_app_automation
            .reset_execution(&captured.scope, captured.identity.engine_session_id()),
        _ => panic!("unknown test case"),
    }
    let error = callback_target(&fixture, &id, &captured, &fixture._authority)
        .await
        .unwrap_err();
    assert_eq!(fixture.execution.calls.load(Ordering::SeqCst), 0);
    match error {
        CoreError::Tool(reason) => assert_eq!(reason, expected),
        other => panic!("unexpected error: {other}"),
    }
}

#[tokio::test]
async fn local_callback_target_preserves_disabled_server_reason() {
    assert_local_error("disabled", "local_mcp_server_disabled").await;
}

#[tokio::test]
async fn local_callback_target_preserves_catalog_changed_reason() {
    assert_local_error("catalog", "mcp_app_catalog_changed").await;
}

#[tokio::test]
async fn local_callback_target_preserves_expired_frame_reason() {
    assert_local_error("expired", "mcp_app_frame_expired").await;
}

#[tokio::test]
async fn local_callback_target_rejects_supplied_authority_scope_mismatch_explicitly() {
    let fixture = Fixture::new().await;
    let id = fixture.render("render_main").await;
    fixture.attach(&id).await;
    let captured = fixture.state.mcp_app_automation.tabs.lock().unwrap()[&id].clone();
    let mut replacement = captured.scope.clone();
    replacement.run_revision += 2;
    // Keep the original authority registered so continuation lookup itself succeeds.
    let authority =
        ExecutionAuthority::LocalRun(execution(&fixture.state, replacement, &fixture.server_id));
    let error = callback_target(&fixture, &id, &captured, &authority)
        .await
        .unwrap_err();
    assert_eq!(fixture.execution.calls.load(Ordering::SeqCst), 0);
    match error {
        CoreError::Tool(reason) => assert_eq!(reason, "mcp_app_scope_mismatch"),
        other => panic!("unexpected error: {other}"),
    }
}

#[tokio::test]
async fn local_callback_target_keeps_the_current_scope_and_attachment() {
    let fixture = Fixture::new().await;
    let id = fixture.render("render_main").await;
    let handle = fixture.attach(&id).await;
    let captured = fixture.state.mcp_app_automation.tabs.lock().unwrap()[&id].clone();
    let target = callback_target(&fixture, &id, &captured, &fixture._authority)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(target, (captured.scope, handle));
    assert_eq!(fixture.execution.calls.load(Ordering::SeqCst), 0);
}
