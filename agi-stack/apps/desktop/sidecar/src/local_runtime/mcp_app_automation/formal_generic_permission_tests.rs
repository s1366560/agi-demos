//! Ordinary tool permission must retain the App created earlier in this run.
use super::*;

#[path = "generic_permission_cross_cell_tests.rs"]
mod cross_cell;
#[path = "generic_permission_guards_tests.rs"]
mod guards;
#[path = "generic_permission_late_attachment_tests.rs"]
mod late_attachment;

async fn generic_permission(fixture: &FormalFixture) -> DesktopHitlRequest {
    let mut decision = crate::local_runtime::tests::test_decision_context();
    decision.action.name = "cua_repl_js".into();
    decision.target.kind = "tool".into();
    decision.target.id = "cua_repl_js".into();
    let mut checkpoint = SessionState::new(
        &fixture.conversation.id,
        &fixture.run.request_message,
        Some(&fixture.conversation.project_id),
    );
    checkpoint.status = SessionStatus::AwaitingInput;
    checkpoint.pending_hitl = Some(
        HitlRequest::new(
            "formal-generic-permission",
            HitlKind::Permission,
            "Allow this tool once?",
        )
        .with_decision(decision),
    );
    fixture.state.checkpoints.save(&checkpoint).await.unwrap();
    fixture
        .state
        .session_store
        .bind_checkpoint_authority(&fixture.run, &now_iso())
        .unwrap();
    let request = fixture
        .state
        .persist_pending_hitl(&fixture.conversation.id, Some(&fixture.run.id), &checkpoint)
        .unwrap()
        .unwrap();
    fixture
        .state
        .session_store
        .transition_run(
            &fixture.run.id,
            fixture.run.revision,
            DesktopRunStatus::NeedsApproval,
            None,
            &now_iso(),
        )
        .unwrap();
    request
}

#[tokio::test]
async fn formal_generic_tool_approval_keeps_original_app_visible_to_public_cua() {
    let fixture = FormalFixture::new().await;
    let older_revision = fixture.original_scope.run_revision.saturating_sub(1);
    fixture
        .state
        .mcp_app_automation
        .tabs
        .lock()
        .unwrap()
        .get_mut(&fixture.renderer_id)
        .unwrap()
        .continuation_revisions
        .insert(older_revision);
    let request = generic_permission(&fixture).await;
    let llm = fixture.llm(Some(
        "var genericBrowser = await cua.getBrowser({id:'mcpapps'}); await genericBrowser.tabs.list()".into(),
    ));
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    tokio::time::timeout(Duration::from_secs(15), llm.ready.notified())
        .await
        .unwrap();
    let transcript = llm.observed.lock().unwrap().clone();
    let output = transcript
        .iter()
        .filter_map(|content| serde_json::from_str::<Value>(content).ok())
        .find(|value| value.get("cell_id").is_some())
        .unwrap_or_else(|| panic!("missing public CUA result: {transcript:?}"));
    let current = fixture
        .state
        .session_store
        .run(&fixture.run.id)
        .unwrap()
        .unwrap();
    let mut scope = fixture.original_scope.clone();
    scope.run_revision = current.revision;
    let visible = fixture
        .state
        .mcp_app_automation
        .list(&fixture.state, &scope);
    let registry = &fixture.state.mcp_app_automation;
    assert!(registry
        .require_browser(&fixture.state, &fixture.handle, &fixture.original_scope)
        .is_err());
    for revision in [fixture.original_scope.run_revision, older_revision] {
        let mut stale = fixture.original_scope.clone();
        stale.run_revision = revision;
        assert!(registry
            .require_callback_continuation(&fixture.state, &fixture.renderer_id, &stale)
            .is_err());
    }
    let denied_callback = registry.renderer_operation(&fixture.state, json!({
        "tabId":fixture.renderer_id,"operation":"tools/call","mountNonce":"fixture-mount",
        "arguments":{"name":"increment_main","arguments":{"operation_id":"generic-is-not-callback-consent"}},
    })).await.unwrap();
    let (duplicate_status, duplicate) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    let counts = fixture.counts().await;
    let handle = fixture.handle.clone();
    let original_scope = fixture.original_scope.clone();
    let stored =
        fixture.state.mcp_app_automation.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    fixture.finish(Some(&llm)).await;
    assert_eq!(output["ok"], true, "{output}");
    assert_eq!(output["value"][0]["id"], handle, "{output}");
    assert_eq!(visible[0]["id"], handle);
    assert_eq!(stored.registration.as_deref(), Some(handle.as_str()));
    assert_eq!(stored.scope.run_revision, original_scope.run_revision + 2);
    assert!(stored.continuation_revisions.is_empty());
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
    assert_eq!(
        denied_callback["error"], "repl_tool_permission_required",
        "{denied_callback}"
    );
    assert_eq!(duplicate_status, StatusCode::OK);
    assert_eq!(duplicate["duplicate"], true);
    assert_eq!(llm.calls.load(Ordering::SeqCst), 2);
}

#[tokio::test]
async fn formal_generic_denial_does_not_renew_existing_app() {
    let fixture = FormalFixture::new().await;
    let request = generic_permission(&fixture).await;
    let llm = fixture.llm(None);
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, false),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    tokio::time::timeout(Duration::from_secs(10), llm.ready.notified())
        .await
        .unwrap();
    let tab = fixture.state.mcp_app_automation.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    let counts = fixture.counts().await;
    let original = fixture.original_scope.clone();
    fixture.finish(Some(&llm)).await;
    assert_eq!(tab.scope, original);
    assert!(tab.continuation_revisions.is_empty());
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}

#[path = "formal_clarification_late_mount_tests.rs"]
mod clarification_late_mount;

#[path = "formal_clarification_pending_guards_tests.rs"]
mod clarification_pending_guards;
