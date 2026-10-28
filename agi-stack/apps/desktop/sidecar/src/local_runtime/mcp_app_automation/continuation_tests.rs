//! Real MCP effects with host-issued approval continuations. The enclosing
//! callback fixture supplies the process and exact once-only tool grants.
use super::super::callback_origin::CallbackOrigin;
use super::*;
use crate::local_runtime::{
    authority_store::{
        DesktopHitlRequest, DesktopHitlStatus, DesktopPermissionProfile, DesktopRun,
        DesktopRunStatus,
    },
    execution_authority::with_step_id,
};
use agistack_core::agent::types::HitlKind;

fn approved_transition(
    scope: &ExecutionScope,
) -> (
    DesktopRun,
    DesktopRun,
    DesktopHitlRequest,
    (ExecutionScope, String),
) {
    let waiting = DesktopRun {
        id: scope.run_id.clone(),
        conversation_id: scope.conversation_id.clone(),
        project_id: scope.project_id.clone(),
        plan_version_id: "continuation-plan".into(),
        idempotency_key: "continuation-run".into(),
        message_id: "continuation-message".into(),
        request_message: "Continue the exact approved App operation".into(),
        status: DesktopRunStatus::NeedsApproval,
        revision: scope.run_revision + 1,
        created_at: "2026-10-23T00:00:00Z".into(),
        updated_at: "2026-10-23T00:00:00Z".into(),
        started_at: None,
        completed_at: None,
        last_heartbeat_at: None,
        error: None,
        environment: None,
        permission_profile: DesktopPermissionProfile::ReadOnly,
        authorization_snapshot: json!({"agent":"continuation-fixture"}),
    };
    let mut resumed = waiting.clone();
    resumed.status = DesktopRunStatus::Running;
    resumed.revision += 1;
    let mut decision = crate::local_runtime::tests::test_decision_context();
    decision.target.kind = "repl_step".into();
    decision.target.id = "continuation-step".into();
    decision.action.name = "browser_read_operation".into();
    let request = DesktopHitlRequest {
        id: format!("continuation-hitl-{}", scope.run_revision),
        conversation_id: scope.conversation_id.clone(),
        run_id: Some(scope.run_id.clone()),
        round: 1,
        kind: HitlKind::Permission,
        prompt: "Allow this exact App operation?".into(),
        decision: Some(decision),
        a2ui_action: None,
        status: DesktopHitlStatus::Responded,
        authority_revision: 2,
        created_at: waiting.created_at.clone(),
        responded_at: Some(waiting.updated_at.clone()),
        response_data: Some(json!({"granted":true,"scope":"once"})),
        response_actor: Some("local_user".into()),
        response_revision: Some(2),
        idempotency_key: Some("continuation-response".into()),
    };
    let pending = (scope.clone(), scope.engine_session_id.clone());
    (waiting, resumed, request, pending)
}

fn bind_revision(
    fixture: &Fixture,
    scope: ExecutionScope,
) -> (Arc<Execution>, Arc<ExecutionAuthority>) {
    let execution = execution(&fixture.state, scope, &fixture.server_id);
    let authority = Arc::new(ExecutionAuthority::LocalRun(execution.clone()));
    fixture
        .state
        .mcp_app_automation
        .register_authority(authority.clone());
    (execution, authority)
}

#[tokio::test]
async fn approved_claim_preserves_attachment_but_ordinary_old_scope_is_rejected() {
    let fixture = Fixture::new().await;
    let tab = fixture.render("render_main").await;
    let handle = fixture.attach(&tab).await;
    let original = fixture.execution.scope.clone();
    let (waiting, resumed, request, pending) = approved_transition(&original);
    let mut current = original.clone();
    current.run_revision = resumed.revision;
    let (_, authority) = bind_revision(&fixture, current.clone());
    let registry = &fixture.state.mcp_app_automation;

    // This is the original native failure: the replacement run is current, but
    // the attached App still carries the pre-approval execution revision.
    assert!(registry
        .browser_operation(&fixture.state, &authority, &handle, "tab.claim", json!([]))
        .await
        .unwrap_err()
        .to_string()
        .contains("mcp_app_scope_mismatch"));
    registry.resume_local_permission(&waiting, &resumed, &request, Some(&pending));
    assert_eq!(
        registry
            .browser_operation(&fixture.state, &authority, &handle, "tab.claim", json!([]))
            .await
            .unwrap()["id"],
        handle
    );
    assert_eq!(fixture.registration(&tab), handle);
    assert_eq!(fixture.events().len(), 1);
    assert_eq!(registry.list(&fixture.state, &current)[0]["id"], handle);
    assert!(registry
        .list(&fixture.state, &original)
        .as_array()
        .unwrap()
        .is_empty());
    assert!(registry
        .require_browser(&fixture.state, &handle, &original)
        .is_err());

    // Replaying a committed response cannot extend the lineage again.
    registry.resume_local_permission(&waiting, &resumed, &request, Some(&pending));
    let stored = registry.tabs.lock().unwrap().get(&tab).unwrap().clone();
    assert_eq!(stored.scope, current);
    assert_eq!(
        stored.continuation_revisions,
        BTreeSet::from([original.run_revision])
    );
}

#[tokio::test]
async fn parent_scope_uses_the_captured_cell_engine_instead_of_the_empty_scope_fallback() {
    let fixture = Fixture::new().await;
    let tab = fixture.render("render_main").await;
    let handle = fixture.attach(&tab).await;
    let registry = &fixture.state.mcp_app_automation;
    let mut parent_scope = fixture.execution.scope.clone();
    parent_scope.engine_session_id.clear();
    registry.tabs.lock().unwrap().get_mut(&tab).unwrap().scope = parent_scope.clone();
    let (waiting, resumed, request, mut pending) = approved_transition(&parent_scope);
    let mut current = parent_scope.clone();
    current.run_revision = resumed.revision;
    let (_, authority) = bind_revision(&fixture, current.clone());

    // A blank parent fallback does not identify the actual pending cell.
    registry.resume_local_permission(&waiting, &resumed, &request, Some(&pending));
    assert_eq!(registry.tabs.lock().unwrap()[&tab].scope, parent_scope);
    pending.1 = fixture.execution.scope.engine_session_id.clone();
    registry.resume_local_permission(&waiting, &resumed, &request, Some(&pending));
    assert_eq!(registry.tabs.lock().unwrap()[&tab].scope, current);
    assert_eq!(
        registry
            .browser_operation(&fixture.state, &authority, &handle, "tab.claim", json!([]),)
            .await
            .unwrap()["id"],
        handle
    );
}

#[tokio::test]
async fn captured_callback_origin_survives_exact_approvals_without_republishing_or_replay() {
    let fixture = Fixture::new().await;
    let tab_id = fixture.render("render_main").await;
    let handle = fixture.attach(&tab_id).await;
    let registry = &fixture.state.mcp_app_automation;
    let mut scope = fixture.execution.scope.clone();
    let mut retained_authorities = vec![];

    for sequence in 1..=2 {
        let captured = registry.tabs.lock().unwrap().get(&tab_id).unwrap().clone();
        let binding = fixture
            .state
            .mcp_supervisor
            .resolve_tool(&fixture.scope, &fixture.server_id, "increment_main")
            .unwrap();
        let origin = CallbackOrigin::capture(&tab_id, &captured, &binding).unwrap();
        let (waiting, resumed, request, pending) = approved_transition(&scope);
        registry.resume_local_permission(&waiting, &resumed, &request, Some(&pending));
        scope.run_revision = resumed.revision;
        let (execution, authority) = bind_revision(&fixture, scope.clone());
        let tool = legacy_exposed_tool_name(&fixture.server_id, "increment_main");
        let arguments = json!({"operation_id":format!("approved-callback-{sequence}")});
        *execution.permit.lock().unwrap() = Some((tool.clone(), arguments.clone()));
        let (continued, _) = registry
            .require_callback_continuation(&fixture.state, &tab_id, &captured.scope)
            .unwrap();
        assert_eq!(continued.registration, captured.registration);
        assert_eq!(continued.scope, *authority.scope());
        assert!(registry
            .require_browser(&fixture.state, &handle, &captured.scope)
            .is_err());

        // Exercise the production result-publication guard using the origin
        // captured before HITL, rather than fabricating a fresh callback origin.
        let result = captured
            .identity
            .for_tool(
                &tool,
                with_step_id(
                    format!("callback-step-{sequence}"),
                    origin
                        .clone()
                        .scope(authority.call(&tool, &arguments.to_string())),
                ),
            )
            .await
            .unwrap();
        let result: Value = serde_json::from_str(&result.output_json).unwrap();
        assert_eq!(payload(&result)["counts"]["main"], sequence);
        assert_eq!(execution.calls.load(Ordering::SeqCst), 1);
        assert_eq!(fixture.registration(&tab_id), handle);
        assert_eq!(fixture.events().len(), 1);

        let duplicate = captured
            .identity
            .for_tool(
                &tool,
                with_step_id(
                    format!("callback-step-{sequence}"),
                    origin.scope(authority.call(&tool, &arguments.to_string())),
                ),
            )
            .await;
        assert!(duplicate
            .unwrap_err()
            .to_string()
            .contains("exact_callback_approval_required"));
        assert_eq!(execution.calls.load(Ordering::SeqCst), 1);
        retained_authorities.push(authority);
    }
    assert_eq!(
        fixture.counts().await,
        json!({"main":2,"sibling":0,"hidden":0})
    );
}

#[tokio::test]
async fn continuation_rejects_untrusted_revision_status_owner_and_permission_changes() {
    let fixture = Fixture::new().await;
    let tab_id = fixture.render("render_main").await;
    fixture.attach(&tab_id).await;
    let registry = &fixture.state.mcp_app_automation;
    let original = fixture.execution.scope.clone();
    for changed in [
        "missing_pending",
        "wrong_engine",
        "captured_revision",
        "waiting_revision",
        "resumed_revision",
        "pause",
        "cancel",
        "resumed_pause",
        "resumed_cancel",
        "request_pending",
        "request_denied",
        "request_response_missing",
        "request_kind",
        "request_run",
        "request_conversation",
        "run",
        "conversation",
        "project",
        "plan",
        "permission",
        "authorization",
        "generation",
        "device",
        "connection_epoch",
        "tenant",
        "engine",
    ] {
        let (mut waiting, mut resumed, mut request, mut pending) = approved_transition(&original);
        match changed {
            "missing_pending" => {}
            "wrong_engine" => pending.1 = "other-engine".into(),
            "captured_revision" => pending.0.run_revision += 1,
            "waiting_revision" => waiting.revision += 1,
            "resumed_revision" => resumed.revision += 1,
            "pause" => waiting.status = DesktopRunStatus::Paused,
            "cancel" => waiting.status = DesktopRunStatus::Cancelled,
            "resumed_pause" => resumed.status = DesktopRunStatus::Paused,
            "resumed_cancel" => resumed.status = DesktopRunStatus::Cancelled,
            "request_pending" => request.status = DesktopHitlStatus::Pending,
            "request_denied" => {
                request.response_data = Some(json!({"granted":false,"scope":"once"}))
            }
            "request_response_missing" => request.response_data = None,
            "request_kind" => request.kind = HitlKind::Clarification,
            "request_run" => request.run_id = Some("different-run".into()),
            "request_conversation" => request.conversation_id = "different-conversation".into(),
            "run" => resumed.id = "different-run".into(),
            "conversation" => resumed.conversation_id = "different-conversation".into(),
            "project" => resumed.project_id = "different-project".into(),
            "plan" => resumed.plan_version_id = "different-plan".into(),
            "permission" => resumed.permission_profile = DesktopPermissionProfile::FullAccess,
            "authorization" => resumed.authorization_snapshot = json!({"different":true}),
            "generation" => pending.0.generation += 1,
            "device" => pending.0.device_id = Some("different-device".into()),
            "connection_epoch" => pending.0.connection_epoch = Some(9),
            "tenant" => pending.0.tenant_id = "different-tenant".into(),
            "engine" => pending.0.engine_session_id = "different-engine".into(),
            _ => unreachable!(),
        }
        registry.resume_local_permission(
            &waiting,
            &resumed,
            &request,
            (changed != "missing_pending").then_some(&pending),
        );
        let tab = registry.tabs.lock().unwrap().get(&tab_id).unwrap().clone();
        assert_eq!(tab.scope, original, "{changed}");
        assert!(tab.continuation_revisions.is_empty(), "{changed}");
    }
}

#[tokio::test]
async fn arbitrary_scope_replacement_and_stop_revocation_cannot_reuse_approved_handles() {
    let fixture = Fixture::new().await;
    let tab = fixture.render("render_main").await;
    let handle = fixture.attach(&tab).await;
    let registry = &fixture.state.mcp_app_automation;
    let initial = fixture.execution.scope.clone();
    let (waiting, resumed, request, pending) = approved_transition(&initial);
    registry.resume_local_permission(&waiting, &resumed, &request, Some(&pending));
    let mut current = initial.clone();
    current.run_revision = resumed.revision;
    let (_, current_authority) = bind_revision(&fixture, current.clone());
    registry
        .require_callback_continuation(&fixture.state, &tab, &initial)
        .unwrap();
    for field in ["revision", "generation", "connection_epoch"] {
        let mut replacement = current.clone();
        match field {
            "revision" => replacement.run_revision += 1,
            "generation" => replacement.generation += 1,
            "connection_epoch" => replacement.connection_epoch = Some(17),
            _ => unreachable!(),
        }
        let (_, replacement_authority) = bind_revision(&fixture, replacement.clone());
        assert!(registry
            .require_browser(&fixture.state, &handle, &replacement)
            .is_err());
        assert!(registry
            .require_callback_continuation(&fixture.state, &tab, &initial)
            .is_err());
        registry.register_authority(current_authority.clone());
        drop(replacement_authority);
    }
    registry.revoke_run(&current.run_id);
    registry.resume_local_permission(&waiting, &resumed, &request, Some(&pending));
    registry.register_authority(current_authority);
    assert!(registry
        .require_browser(&fixture.state, &handle, &current)
        .is_err());
    assert!(registry
        .require_callback_continuation(&fixture.state, &tab, &initial)
        .is_err());
    assert!(registry
        .list(&fixture.state, &current)
        .as_array()
        .unwrap()
        .is_empty());
    assert_eq!(
        fixture.counts().await,
        json!({"main":0,"sibling":0,"hidden":0})
    );
}

#[tokio::test]
async fn reset_expires_handles_and_lineage_without_revoking_a_sibling_execution() {
    let fixture = Fixture::new().await;
    let tab = fixture.render("render_main").await;
    let handle = fixture.attach(&tab).await;
    let registry = &fixture.state.mcp_app_automation;
    let initial = fixture.execution.scope.clone();
    let (waiting, resumed, request, pending) = approved_transition(&initial);
    registry.resume_local_permission(&waiting, &resumed, &request, Some(&pending));
    let mut current = initial.clone();
    current.run_revision = resumed.revision;
    let (_, authority) = bind_revision(&fixture, current.clone());
    let mut sibling = registry.tabs.lock().unwrap().get(&tab).unwrap().clone();
    sibling.scope.engine_session_id = "sibling-engine".into();
    sibling.identity = call_identity::scope(
        &ToolPolicyContext {
            session_id: "sibling-engine",
            round: 1,
            tool: "render_main",
        },
        async { call_identity::active().unwrap() },
    )
    .await;
    sibling.child = Some(ChildIdentityV2 {
        execution_id: "sibling-engine".into(),
        subagent_id: "sibling-agent".into(),
        run_id: current.run_id.clone(),
        revision: current.run_revision,
    });
    registry
        .tabs
        .lock()
        .unwrap()
        .insert("sibling-tab".into(), sibling.clone());
    let (child_waiting, child_resumed, child_request, child_pending) =
        approved_transition(&sibling.scope);
    registry.resume_local_permission(
        &child_waiting,
        &child_resumed,
        &child_request,
        Some(&child_pending),
    );
    assert_eq!(
        registry.tabs.lock().unwrap()["sibling-tab"].scope,
        sibling.scope
    );

    registry.reset_execution(&current, &current.engine_session_id);
    registry.register_authority(authority);
    assert!(registry
        .require_browser(&fixture.state, &handle, &current)
        .is_err());
    assert!(registry
        .require_callback_continuation(&fixture.state, &tab, &initial)
        .is_err());
    assert_eq!(
        registry.tabs.lock().unwrap()["sibling-tab"].scope,
        sibling.scope
    );
    assert_eq!(registry.tabs.lock().unwrap().len(), 1);
    registry.resume_local_permission(&waiting, &resumed, &request, Some(&pending));
    assert!(registry.require(&fixture.state, &tab, None).is_err());
}
