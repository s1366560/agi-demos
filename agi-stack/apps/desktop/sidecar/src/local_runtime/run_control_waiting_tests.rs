use std::sync::{atomic::Ordering, Arc};

use agistack_core::agent::types::{HitlKind, HitlRequest, SessionState, SessionStatus};
use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use serde_json::{json, Value};
use tower::ServiceExt;

use super::super::{
    authority_store::{DesktopHitlStatus, DesktopRun, DesktopRunStatus},
    local_router, now_iso,
    session_store::{HitlResponseCommit, HitlResponseCommitError},
    tests::{seed_controlled_run, test_decision_context, test_state},
    LocalConversation, LocalRuntimeState,
};

async fn waiting_run(
    kind: HitlKind,
) -> (
    Arc<LocalRuntimeState>,
    LocalConversation,
    DesktopRun,
    String,
) {
    let state = test_state("waiting-cancel-secret");
    let (conversation, running) = seed_controlled_run(&state, "waiting-cancel");
    let request_id = "old-unanswered-request".to_string();
    let mut checkpoint = SessionState::new(
        &conversation.id,
        "Execute under human control",
        Some("local-project"),
    );
    checkpoint.status = SessionStatus::AwaitingInput;
    let mut request = HitlRequest::new(&request_id, kind, "Continue the pending work?");
    if kind == HitlKind::Permission {
        request = request.with_decision(test_decision_context());
    }
    checkpoint.pending_hitl = Some(request);
    state.checkpoints.save(&checkpoint).await.unwrap();
    state
        .session_store
        .bind_checkpoint_authority(&running, &now_iso())
        .unwrap();
    state
        .persist_pending_hitl(&conversation.id, Some(&running.id), &checkpoint)
        .unwrap();
    let status = if kind == HitlKind::Permission {
        DesktopRunStatus::NeedsApproval
    } else {
        DesktopRunStatus::NeedsInput
    };
    let waiting = state
        .session_store
        .transition_run(&running.id, running.revision, status, None, &now_iso())
        .unwrap();
    (state, conversation, waiting, request_id)
}

async fn cancel(state: Arc<LocalRuntimeState>, run: &DesktopRun, revision: u64) -> StatusCode {
    local_router(state)
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(format!("/api/v1/agent/runs/{}/cancel", run.id))
                .header("authorization", "Bearer waiting-cancel-secret")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({"expected_revision":revision}).to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap()
        .status()
}

#[tokio::test]
async fn waiting_input_and_approval_stop_without_answer_or_restart() {
    for kind in [HitlKind::Clarification, HitlKind::Permission] {
        let (state, conversation, run, request_id) = waiting_run(kind).await;
        state
            .browser_once_consents
            .lock()
            .unwrap()
            .insert((run.id.clone(), "fixture.test".into()));
        state
            .run_once_tool_permissions
            .lock()
            .unwrap()
            .insert((run.id.clone(), "write".into()));
        let response = local_router(state.clone()).oneshot(
            Request::builder().uri(format!(
                "/api/v1/agent/conversations/{}/session?tenant_id=local&project_id=local-project&workspace_id=local-workspace",
                conversation.id,
            )).header("authorization", "Bearer waiting-cancel-secret")
                .body(Body::empty()).unwrap(),
        ).await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .unwrap();
        let projection: Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(projection["capabilities"]["run_actions"], json!(["cancel"]));
        assert_eq!(projection["pending_hitl"][0]["id"], request_id);

        assert_eq!(
            cancel(state.clone(), &run, run.revision).await,
            StatusCode::OK
        );
        let cancelled = state.session_store.run(&run.id).unwrap().unwrap();
        assert_eq!(cancelled.status, DesktopRunStatus::Cancelled);
        assert_eq!(cancelled.revision, run.revision + 1);
        assert!(cancelled.completed_at.is_some());
        let checkpoint = state
            .checkpoints
            .load(&conversation.id)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(checkpoint.status, SessionStatus::Cancelled);
        assert!(checkpoint.pending_hitl.is_none());
        assert!(checkpoint.hitl_responses.is_empty());
        assert!(checkpoint.answer.is_none());
        let history = state
            .session_store
            .hitl_request(&request_id)
            .unwrap()
            .unwrap();
        assert_eq!(history.status, DesktopHitlStatus::Pending);
        assert!(history.response_data.is_none());
        assert!(state
            .session_store
            .conversation_session_snapshot(&conversation.id)
            .unwrap()
            .unwrap()
            .pending_hitl
            .is_empty());
        assert!(state.browser_once_consents.lock().unwrap().is_empty());
        assert!(state.run_once_tool_permissions.lock().unwrap().is_empty());
        assert!(state.agent_runs.lock().unwrap().is_empty());
    }
}

#[tokio::test]
async fn waiting_stop_rejects_stale_revision_and_an_inflight_human_response() {
    let (state, conversation, run, _) = waiting_run(HitlKind::Permission).await;
    assert_eq!(
        cancel(state.clone(), &run, run.revision - 1).await,
        StatusCode::CONFLICT
    );
    let control = state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .unwrap();
    assert_eq!(
        cancel(state.clone(), &run, run.revision).await,
        StatusCode::CONFLICT
    );
    assert_eq!(
        state.session_store.run(&run.id).unwrap().unwrap().revision,
        run.revision
    );
    assert_eq!(
        state
            .checkpoints
            .load(&conversation.id)
            .await
            .unwrap()
            .unwrap()
            .status,
        SessionStatus::AwaitingInput
    );
    state.release_agent_run_if_control(&conversation.id, &control);
    assert_eq!(
        cancel(state.clone(), &run, run.revision).await,
        StatusCode::OK
    );
}

#[tokio::test]
async fn cancelled_waiting_run_rejects_old_human_response_before_grant_commit() {
    let (state, _conversation, run, request_id) = waiting_run(HitlKind::Permission).await;
    assert_eq!(
        cancel(state.clone(), &run, run.revision).await,
        StatusCode::OK
    );
    let before = state.agent_run_claim_attempts.load(Ordering::SeqCst);
    let response_data = json!({"action":"allow","granted":true,"scope":"once"});
    let error = state
        .session_store
        .mark_hitl_responded(
            &request_id,
            HitlResponseCommit {
                expected_authority_revision: 1,
                response_data: &response_data,
                response_actor: "local_user",
                response_revision: None,
                idempotency_key: "stale-cancelled-answer",
                workspace_tool_grant: None,
                now: &now_iso(),
            },
        )
        .unwrap_err();
    assert_eq!(error, HitlResponseCommitError::RunNotWaiting);
    let response = local_router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/agent/hitl/respond")
                .header("authorization", "Bearer waiting-cancel-secret")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({"request_id":request_id,"hitl_type":"permission",
                "response_data":response_data,"expected_revision":1,
                "idempotency_key":"stale-cancelled-answer"})
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::CONFLICT);
    assert_eq!(
        state.agent_run_claim_attempts.load(Ordering::SeqCst),
        before
    );
    let request = state
        .session_store
        .hitl_request(&request_id)
        .unwrap()
        .unwrap();
    assert_eq!(request.authority_revision, 1);
    assert!(request.response_data.is_none());
    assert!(state.run_once_tool_permissions.lock().unwrap().is_empty());
}

#[tokio::test]
async fn cancelled_checkpoint_blocks_response_before_run_reconciliation() {
    let (state, conversation, run, request_id) = waiting_run(HitlKind::Permission).await;
    let mut checkpoint = state
        .checkpoints
        .load(&conversation.id)
        .await
        .unwrap()
        .unwrap();
    checkpoint.status = SessionStatus::Cancelled;
    checkpoint.pending_hitl = None;
    state.checkpoints.save(&checkpoint).await.unwrap();
    let response = local_router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/agent/hitl/respond")
                .header("authorization", "Bearer waiting-cancel-secret")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({"request_id":request_id,"hitl_type":"permission",
                "response_data":{"action":"allow","granted":true,"scope":"once"},
                "expected_revision":1,"idempotency_key":"cancelled-checkpoint-response"})
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::CONFLICT);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .unwrap();
    let body: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(body["reason_code"], "hitl_run_not_waiting");
    let request = state
        .session_store
        .hitl_request(&request_id)
        .unwrap()
        .unwrap();
    assert!(request.response_data.is_none());
    assert_eq!(request.authority_revision, 1);
    assert_eq!(
        state.session_store.run(&run.id).unwrap().unwrap().revision,
        run.revision
    );
    assert!(state.agent_runs.lock().unwrap().is_empty());
}
