//! A clarification answer preserves its original surface without granting effects.
use super::*;

pub(super) async fn clarification(fixture: &FormalFixture) -> DesktopHitlRequest {
    let mut checkpoint = SessionState::new(
        &fixture.conversation.id,
        &fixture.run.request_message,
        Some(&fixture.conversation.project_id),
    );
    checkpoint.status = SessionStatus::AwaitingInput;
    checkpoint.pending_hitl = Some(HitlRequest::new(
        "formal-clarification",
        HitlKind::Clarification,
        "Confirm the original App is still mounted.",
    ));
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
            DesktopRunStatus::NeedsInput,
            None,
            &now_iso(),
        )
        .unwrap();
    request
}

pub(super) fn answer(request: &DesktopHitlRequest, answer: Value) -> Value {
    json!({
        "request_id":request.id,
        "hitl_type":"clarification",
        "expected_revision":request.authority_revision,
        "idempotency_key":"formal-clarification-response",
        "response_data":{"answer":answer},
    })
}

#[tokio::test]
async fn formal_clarification_preserves_original_app_without_callback_consent() {
    let fixture = FormalFixture::new().await;
    let registry = &fixture.state.mcp_app_automation;
    registry
        .tabs
        .lock()
        .unwrap()
        .get_mut(&fixture.renderer_id)
        .unwrap()
        .continuation_revisions
        .insert(fixture.original_scope.run_revision.saturating_sub(1));
    let before = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    let request = clarification(&fixture).await;
    let llm = fixture.llm(Some(
        "var clarificationBrowser = await cua.getBrowser({id:'mcpapps'}); await clarificationBrowser.tabs.list()".into(),
    ));
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        answer(&request, json!("The original App is still mounted.")),
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
    let mut current_scope = fixture.original_scope.clone();
    current_scope.run_revision = current.revision;
    let public_handle_is_live = registry
        .require_browser(&fixture.state, &fixture.handle, &current_scope)
        .is_ok();
    let stale_handle_is_denied = registry
        .require_browser(&fixture.state, &fixture.handle, &fixture.original_scope)
        .is_err();
    let stale_callback_is_denied = registry
        .require_callback_continuation(
            &fixture.state,
            &fixture.renderer_id,
            &fixture.original_scope,
        )
        .is_err();
    let denied_callback = registry.renderer_operation(&fixture.state, json!({
        "tabId":fixture.renderer_id,"operation":"tools/call","mountNonce":"fixture-mount",
        "arguments":{"name":"increment_main","arguments":{"operation_id":"clarification-is-not-consent"}},
    })).await;
    let (duplicate_status, duplicate) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        answer(&request, json!("The original App is still mounted.")),
    )
    .await;
    let stored = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    let once_permissions = fixture
        .state
        .run_once_tool_permissions
        .lock()
        .unwrap()
        .len();
    let counts = fixture.counts().await;
    let handle = fixture.handle.clone();
    let original_revision = fixture.original_scope.run_revision;
    fixture.finish(Some(&llm)).await;
    assert_eq!(current.revision, original_revision + 2);
    assert!(public_handle_is_live, "original App handle must survive accepted clarification; old revision={original_revision}, resumed revision={}", current.revision);
    assert_eq!(output["ok"], true, "{output}");
    assert_eq!(output["value"][0]["id"], handle, "{output}");
    assert!(stale_handle_is_denied);
    assert!(stale_callback_is_denied);
    assert_eq!(stored.scope.run_revision, current.revision);
    assert_eq!(stored.mount_nonce, before.mount_nonce);
    assert_eq!(stored.registration, before.registration);
    assert_eq!(stored.app, before.app);
    assert_eq!(stored.identity.round(), before.identity.round());
    assert!(stored.continuation_revisions.is_empty());
    assert_eq!(once_permissions, 0);
    let denied_callback = denied_callback.unwrap();
    assert_eq!(
        denied_callback["error"], "repl_tool_permission_required",
        "{denied_callback}"
    );
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
    assert_eq!(duplicate_status, StatusCode::OK);
    assert_eq!(duplicate["duplicate"], true);
    assert_eq!(llm.calls.load(Ordering::SeqCst), 2);
}

#[tokio::test]
async fn formal_clarification_rejects_invalid_answers_without_renewing_surface() {
    let fixture = FormalFixture::new().await;
    let request = clarification(&fixture).await;
    for invalid in [
        Value::Null,
        json!(false),
        json!(1),
        json!(""),
        json!(" \n\t "),
    ] {
        let (status, _) = post(
            &fixture.state,
            Some(&fixture.token),
            "/api/v1/agent/hitl/respond",
            answer(&request, invalid),
        )
        .await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
        let waiting = fixture
            .state
            .session_store
            .run(&fixture.run.id)
            .unwrap()
            .unwrap();
        assert_eq!(waiting.status, DesktopRunStatus::NeedsInput);
        assert_eq!(waiting.revision, fixture.run.revision + 1);
        assert_eq!(
            fixture.state.mcp_app_automation.tabs.lock().unwrap()[&fixture.renderer_id].scope,
            fixture.original_scope
        );
        assert!(fixture
            .state
            .run_once_tool_permissions
            .lock()
            .unwrap()
            .is_empty());
    }
    let counts = fixture.counts().await;
    fixture.finish(None).await;
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}

#[tokio::test]
async fn clarification_surface_resume_rejects_malformed_answers_and_changed_authority() {
    let fixture = FormalFixture::new().await;
    let mut request = clarification(&fixture).await;
    let registry = &fixture.state.mcp_app_automation;
    let waiting = fixture
        .state
        .session_store
        .run(&fixture.run.id)
        .unwrap()
        .unwrap();
    let captured = registry
        .capture_local_human_response(
            &waiting,
            &request,
            &fixture.conversation.tenant_id,
            &fixture.conversation.id,
        )
        .unwrap();
    let resumed = fixture
        .state
        .session_store
        .transition_run(
            &waiting.id,
            waiting.revision,
            DesktopRunStatus::Running,
            None,
            &now_iso(),
        )
        .unwrap();
    request.status = DesktopHitlStatus::Responded;
    request.response_data = Some(json!({"answer":"The original App is mounted."}));
    let generation = fixture
        .state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    let original_tab = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    for change in [
        "missing-answer",
        "blank-answer",
        "boolean-answer",
        "permission-is-not-answer",
        "pending",
        "decision",
        "env-var",
        "request-run",
        "request-conversation",
        "waiting-approval",
        "wrong-revision",
        "changed-plan",
        "changed-authorization",
        "cancelled-mount",
        "replaced-mount",
        "replaced-handle",
        "changed-scope",
        "cloud",
        "wrong-engine",
    ] {
        let mut current_request = request.clone();
        let mut current_waiting = waiting.clone();
        let mut current_resumed = resumed.clone();
        let mut tab = original_tab.clone();
        let mut engine = fixture.conversation.id.clone();
        match change {
            "missing-answer" => current_request.response_data = None,
            "blank-answer" => current_request.response_data = Some(json!({"answer":"  "})),
            "boolean-answer" => current_request.response_data = Some(json!({"answer":true})),
            "permission-is-not-answer" => {
                current_request.response_data = Some(json!({"granted":true}))
            }
            "pending" => current_request.status = DesktopHitlStatus::Pending,
            "decision" => current_request.kind = HitlKind::Decision,
            "env-var" => current_request.kind = HitlKind::EnvVar,
            "request-run" => current_request.run_id = Some("another-run".into()),
            "request-conversation" => current_request.conversation_id.push_str("-other"),
            "waiting-approval" => current_waiting.status = DesktopRunStatus::NeedsApproval,
            "wrong-revision" => current_resumed.revision += 1,
            "changed-plan" => current_resumed.plan_version_id.push_str("-other"),
            "changed-authorization" => {
                current_resumed.authorization_snapshot = json!({"changed":true})
            }
            "cancelled-mount" => tab.mount_cancelled = true,
            "replaced-mount" => tab.mount_nonce = Some("another-mount".into()),
            "replaced-handle" => tab.registration = Some("another-handle".into()),
            "changed-scope" => tab.scope.project_id.push_str("-other"),
            "cloud" => tab.local_origin = false,
            "wrong-engine" => engine.push_str("-other"),
            _ => unreachable!(),
        }
        let expected_scope = tab.scope.clone();
        registry
            .tabs
            .lock()
            .unwrap()
            .insert(fixture.renderer_id.clone(), tab);
        registry.resume_local_human_response(
            &fixture.state,
            &current_waiting,
            &current_resumed,
            &current_request,
            &captured,
            &engine,
            &generation,
        );
        assert_eq!(
            registry.tabs.lock().unwrap()[&fixture.renderer_id].scope,
            expected_scope,
            "{change}"
        );
    }
    registry
        .tabs
        .lock()
        .unwrap()
        .insert(fixture.renderer_id.clone(), original_tab);
    fixture
        .state
        .session_store
        .transition_run(
            &resumed.id,
            resumed.revision,
            DesktopRunStatus::Cancelled,
            None,
            &now_iso(),
        )
        .unwrap();
    registry.resume_local_human_response(
        &fixture.state,
        &waiting,
        &resumed,
        &request,
        &captured,
        &fixture.conversation.id,
        &generation,
    );
    let final_scope = registry.tabs.lock().unwrap()[&fixture.renderer_id]
        .scope
        .clone();
    let expected_scope = fixture.original_scope.clone();
    let counts = fixture.counts().await;
    fixture.finish(None).await;
    assert_eq!(final_scope, expected_scope);
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}
