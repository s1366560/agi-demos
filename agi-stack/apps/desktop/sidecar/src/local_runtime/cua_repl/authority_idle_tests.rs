use super::*;
use crate::local_runtime::{
    authority_store::{DesktopHitlStatus, DesktopRunStatus},
    now_iso,
    tests::test_decision_context,
};
use agistack_core::agent::types::{HitlKind, HitlRequest, SessionState, SessionStatus};

const OTHER_RUN: &str = "unrelated-run-with-once-grants";

async fn suspend_owned_run(fixture: &Fixture, status: DesktopRunStatus) -> DesktopRun {
    let control = agent_access::scope(Some(fixture.authorization()), async {
        fixture
            .state
            .claim_agent_run(&fixture.conversation.id, Some(&fixture.run.id))
            .unwrap()
    })
    .await;
    let mut checkpoint = SessionState::new(
        &fixture.conversation.id,
        &fixture.run.request_message,
        Some(&fixture.run.project_id),
    );
    checkpoint.status = if status == DesktopRunStatus::Paused {
        SessionStatus::Paused
    } else {
        SessionStatus::AwaitingInput
    };
    if status != DesktopRunStatus::Paused {
        let kind = if status == DesktopRunStatus::NeedsApproval {
            HitlKind::Permission
        } else {
            HitlKind::Clarification
        };
        let mut request = HitlRequest::new("owner-idle-input", kind, "Continue this execution?");
        if kind == HitlKind::Permission {
            request = request.with_decision(test_decision_context());
        }
        checkpoint.pending_hitl = Some(request);
    }
    fixture.state.checkpoints.save(&checkpoint).await.unwrap();
    fixture
        .state
        .session_store
        .bind_checkpoint_authority(&fixture.run, &now_iso())
        .unwrap();
    fixture
        .state
        .persist_pending_hitl(&fixture.conversation.id, Some(&fixture.run.id), &checkpoint)
        .unwrap();
    let waiting = fixture
        .state
        .session_store
        .transition_run(
            &fixture.run.id,
            fixture.run.revision,
            status,
            None,
            &now_iso(),
        )
        .unwrap();
    fixture
        .state
        .release_agent_run_if_control(&fixture.conversation.id, &control);
    drop(control);
    assert!(fixture.state.agent_runs.lock().unwrap().is_empty());
    for run_id in [fixture.run.id.as_str(), OTHER_RUN] {
        fixture
            .state
            .browser_once_consents
            .lock()
            .unwrap()
            .insert((run_id.to_owned(), "fixture.test".into()));
        fixture
            .state
            .run_once_tool_permissions
            .lock()
            .unwrap()
            .insert((run_id.to_owned(), "write".into()));
    }
    waiting
}

async fn unrelated_signout_preserves_idle_run(fixture: &Fixture, waiting: &DesktopRun) {
    let other = post(
        &fixture.state,
        None,
        "/api/v1/auth/local-session",
        json!({}),
    )
    .await;
    post(
        &fixture.state,
        Some(other["access_token"].as_str().unwrap()),
        "/api/v1/auth/signout",
        json!({}),
    )
    .await;
    let unchanged = fixture
        .state
        .session_store
        .run(&waiting.id)
        .unwrap()
        .unwrap();
    assert_eq!(unchanged.status, waiting.status);
    assert_eq!(unchanged.revision, waiting.revision);
    assert_eq!(fixture.state.browser_once_consents.lock().unwrap().len(), 2);
    assert_eq!(
        fixture
            .state
            .run_once_tool_permissions
            .lock()
            .unwrap()
            .len(),
        2
    );
}

async fn assert_idle_run_cancelled(fixture: &Fixture, waiting: &DesktopRun) {
    let cancelled = fixture
        .state
        .session_store
        .run(&waiting.id)
        .unwrap()
        .unwrap();
    assert_eq!(cancelled.status, DesktopRunStatus::Cancelled);
    assert_eq!(cancelled.revision, waiting.revision + 1);
    assert!(cancelled.completed_at.is_some());
    let checkpoint = fixture
        .state
        .checkpoints
        .load(&fixture.conversation.id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(checkpoint.status, SessionStatus::Cancelled);
    assert!(checkpoint.pending_hitl.is_none());
    assert!(checkpoint.hitl_responses.is_empty());
    assert!(checkpoint.answer.is_none());
    if waiting.status != DesktopRunStatus::Paused {
        let history = fixture
            .state
            .session_store
            .hitl_request("owner-idle-input")
            .unwrap()
            .unwrap();
        assert_eq!(history.status, DesktopHitlStatus::Pending);
        assert!(history.response_data.is_none());
    }
    assert!(fixture
        .state
        .session_store
        .conversation_session_snapshot(&fixture.conversation.id)
        .unwrap()
        .unwrap()
        .pending_hitl
        .is_empty());
    let browser_grants = fixture.state.browser_once_consents.lock().unwrap();
    assert_eq!(browser_grants.len(), 1);
    assert!(browser_grants.contains(&(OTHER_RUN.into(), "fixture.test".into())));
    let tool_grants = fixture.state.run_once_tool_permissions.lock().unwrap();
    assert_eq!(tool_grants.len(), 1);
    assert!(tool_grants.contains(&(OTHER_RUN.into(), "write".into())));
    assert!(fixture.state.agent_runs.lock().unwrap().is_empty());
}

#[tokio::test]
async fn owner_signout_cancels_idle_runs_and_clears_only_their_once_grants() {
    for status in [
        DesktopRunStatus::NeedsInput,
        DesktopRunStatus::NeedsApproval,
        DesktopRunStatus::Paused,
    ] {
        let fixture = Fixture::new().await;
        let waiting = suspend_owned_run(&fixture, status).await;
        unrelated_signout_preserves_idle_run(&fixture, &waiting).await;
        post(
            &fixture.state,
            Some(&fixture.token),
            "/api/v1/auth/signout",
            json!({}),
        )
        .await;
        assert_idle_run_cancelled(&fixture, &waiting).await;
        fixture.finish().await;
    }
}

#[tokio::test]
async fn workspace_switch_cancels_idle_runs_and_clears_only_their_once_grants() {
    for status in [
        DesktopRunStatus::NeedsInput,
        DesktopRunStatus::NeedsApproval,
        DesktopRunStatus::Paused,
    ] {
        let fixture = Fixture::new().await;
        let waiting = suspend_owned_run(&fixture, status).await;
        unrelated_signout_preserves_idle_run(&fixture, &waiting).await;
        post(
            &fixture.state,
            Some(&fixture.token),
            "/api/v1/workspace-context/switch",
            json!({
                "tenant_id": "northstar",
                "project_id": "desktop-client",
                "expected_revision": fixture.auth.workspace.revision,
                "idempotency_key": "idle-owner-workspace-switch"
            }),
        )
        .await;
        assert_idle_run_cancelled(&fixture, &waiting).await;
        fixture.finish().await;
    }
}
