use super::*;
use crate::local_runtime::{
    authority_store::DesktopRunStatus, authorized_tool_host::AuthorizedRunToolHost, now_iso,
    LocalRunControl,
};
use agistack_core::agent::{
    react::{ReActControl, RunDirective},
    types::{HitlKind, HitlRequest, SessionState, SessionStatus},
};
use std::time::Duration;

#[tokio::test]
async fn owner_cancellation_cannot_be_overwritten_by_a_late_pause() {
    let fixture = Fixture::new().await;
    let control = LocalRunControl::new(fixture.state.session_store.clone(), Some(&fixture.run.id));
    control.request_cancel();
    control.request_pause();
    assert_eq!(
        control
            .directive(&fixture.conversation.id, 0)
            .await
            .unwrap(),
        RunDirective::Cancel
    );
    fixture.finish().await;
}

#[tokio::test]
async fn a_new_ownerless_claim_does_not_inherit_the_previous_session_owner() {
    let fixture = Fixture::new().await;
    let previous = agent_access::scope(Some(fixture.authorization()), async {
        fixture
            .state
            .claim_agent_run(&fixture.conversation.id, Some(&fixture.run.id))
            .unwrap()
    })
    .await;
    fixture
        .state
        .release_agent_run_if_control(&fixture.conversation.id, &previous);
    let replacement = fixture
        .state
        .claim_agent_run(&fixture.conversation.id, Some(&fixture.run.id))
        .unwrap();
    assert!(!fixture
        .state
        .run_owners
        .lock()
        .unwrap()
        .contains_key(&fixture.conversation.id));
    post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/auth/signout",
        json!({}),
    )
    .await;
    assert_eq!(
        replacement
            .directive(&fixture.conversation.id, 0)
            .await
            .unwrap(),
        RunDirective::Continue
    );
    assert!(Arc::ptr_eq(
        &fixture.state.control_for_run(&fixture.run).unwrap(),
        &replacement,
    ));
    fixture
        .state
        .release_agent_run_if_control(&fixture.conversation.id, &replacement);
    fixture.finish().await;
}

#[tokio::test]
async fn owner_signout_cancels_an_active_run_finishing_into_input_wait() {
    let fixture = Fixture::new().await;
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
    checkpoint.status = SessionStatus::AwaitingInput;
    checkpoint.pending_hitl = Some(HitlRequest::new(
        "finishing-owner-input",
        HitlKind::Clarification,
        "Continue this execution?",
    ));
    fixture.state.checkpoints.save(&checkpoint).await.unwrap();
    fixture
        .state
        .session_store
        .bind_checkpoint_authority(&fixture.run, &now_iso())
        .unwrap();

    post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/auth/signout",
        json!({}),
    )
    .await;
    assert_eq!(
        control
            .directive(&fixture.conversation.id, 0)
            .await
            .unwrap(),
        RunDirective::Cancel
    );

    // The engine already returned this state before receiving cancellation;
    // the host still owns its exact claim while persisting the final result.
    fixture
        .state
        .persist_pending_hitl(&fixture.conversation.id, Some(&fixture.run.id), &checkpoint)
        .unwrap();
    let waiting = fixture
        .state
        .persist_authoritative_run_outcome(
            &fixture.run,
            DesktopRunStatus::NeedsInput,
            None,
            &now_iso(),
        )
        .await
        .unwrap();
    assert_eq!(waiting.status, DesktopRunStatus::NeedsInput);
    fixture
        .state
        .release_agent_run_if_control(&fixture.conversation.id, &control);
    drop(control);

    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let run = fixture
                .state
                .session_store
                .run(&fixture.run.id)
                .unwrap()
                .unwrap();
            if run.status == DesktopRunStatus::Cancelled
                && !fixture
                    .state
                    .agent_runs
                    .lock()
                    .unwrap()
                    .contains_key(&fixture.conversation.id)
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("revoked owner must cancel the run after the active claim releases");
    let cancelled = fixture
        .state
        .checkpoints
        .load(&fixture.conversation.id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(cancelled.status, SessionStatus::Cancelled);
    assert!(cancelled.pending_hitl.is_none());
    assert!(cancelled.answer.is_none());
    assert!(fixture.state.agent_runs.lock().unwrap().is_empty());
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 0);
    fixture.finish().await;
}

struct BrowserProbe(Arc<AtomicUsize>);

#[async_trait]
impl ToolHost for BrowserProbe {
    fn list_tools(&self) -> Vec<String> {
        vec!["browser_snapshot".into()]
    }

    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok("{}".into())
    }
}

#[tokio::test]
async fn direct_browser_host_rejects_its_captured_owner_after_signout() {
    let fixture = Fixture::new().await;
    let browser = agent_access::scope(Some(fixture.authorization()), async {
        fixture.retained();
        AuthorizedRunToolHost::new(
            Arc::new(BrowserProbe(fixture.calls.clone())),
            fixture.state.session_store.clone(),
            fixture.run.clone(),
        )
    })
    .await;
    browser.call("browser_snapshot", "{}").await.unwrap();
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);

    post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/auth/signout",
        json!({}),
    )
    .await;
    let result = browser.call("browser_snapshot", "{}").await;
    assert!(result.is_err());
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
    fixture.finish().await;
}
