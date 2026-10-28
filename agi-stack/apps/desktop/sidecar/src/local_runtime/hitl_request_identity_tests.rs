use super::*;
use agistack_core::agent::types::HitlRequest;

const TOKEN: &str = "hitl-identity-session";
const RAW_ID: &str = "approve-render-main-once";

#[path = "hitl_request_binding_tests.rs"]
mod binding;

fn request() -> AgentAction {
    AgentAction::RequestHuman {
        request: HitlRequest::new(RAW_ID, HitlKind::Permission, "Allow the tool once?")
            .with_decision(test_decision_context()),
    }
}

fn conversation(state: &LocalRuntimeState, id: &str) -> LocalConversation {
    let conversation = LocalConversation {
        id: id.into(),
        project_id: "local-project".into(),
        tenant_id: "local".into(),
        title: "HITL request identity".into(),
        workspace_id: Some("local-workspace".into()),
        capability_mode: ConversationCapabilityMode::Code,
        current_mode: ConversationRunMode::Plan,
        created_at: now_iso(),
        updated_at: now_iso(),
    };
    state
        .session_store
        .insert_conversation(&conversation)
        .unwrap();
    conversation
}

async fn running(state: &Arc<LocalRuntimeState>, conversation: &LocalConversation) -> DesktopRun {
    state
        .session_store
        .replace_agent_plan_tasks(
            &conversation.id,
            &[json!({
                "id":format!("{}-task", conversation.id), "conversation_id":conversation.id,
                "content":"Execute after approval", "status":"pending", "priority":"high",
                "order_index":0, "created_at":now_iso(), "updated_at":now_iso(),
            })],
        )
        .unwrap();
    let outcome = state
        .session_store
        .approve_plan_and_start(
            &conversation.id,
            &conversation.project_id,
            &format!("{}-approve", conversation.id),
            &format!("{}-message", conversation.id),
            "Execute after approval",
            &now_iso(),
        )
        .unwrap();
    state
        .session_store
        .prepare_run_for_execution(&outcome.run.id, &now_iso())
        .unwrap()
        .unwrap()
}

async fn respond(
    state: &Arc<LocalRuntimeState>,
    request: &DesktopHitlRequest,
) -> (StatusCode, Value) {
    let response = local_router(state.clone())
        .oneshot(authenticated_json_request(
            "POST",
            "/api/v1/agent/hitl/respond",
            TOKEN,
            json!({
                "request_id":request.id, "hitl_type":"permission",
                "response_data":{"action":"allow", "granted":true, "scope":"once"},
                "expected_revision":request.authority_revision,
                "idempotency_key":format!("{}-answer", request.id),
            }),
        ))
        .await
        .unwrap();
    (response.status(), response_json(response).await)
}

#[tokio::test]
async fn hitl_identity_formal_http_resumes_only_the_selected_scoped_request_once() {
    let state = test_state(TOKEN);
    let mut cases = Vec::new();
    for id in ["identity-http-a", "identity-http-b"] {
        let conversation = conversation(&state, id);
        let run = running(&state, &conversation).await;
        let engine = engine(&state, &conversation, Some(&run), vec![request()]);
        let pending = engine
            .run(id, &run.request_message, Some(&conversation.project_id))
            .await
            .unwrap();
        state
            .session_store
            .bind_checkpoint_authority(&run, &now_iso())
            .unwrap();
        let stored = state
            .persist_pending_hitl(id, Some(&run.id), &pending)
            .unwrap()
            .unwrap();
        state
            .session_store
            .transition_run(
                &run.id,
                run.revision,
                DesktopRunStatus::NeedsApproval,
                None,
                &now_iso(),
            )
            .unwrap();
        cases.push((conversation, run, engine, pending, stored));
    }
    let (first_conversation, first_run, _, _, first) = &cases[0];
    let (second_conversation, _, second_engine, second_pending, second) = &cases[1];
    assert_ne!(first.id, second.id);
    assert!(
        second_engine
            .accept_human_response(&second_conversation.id, &first.id, "foreign")
            .await
            .is_err()
    );
    let (status, receipt) = respond(&state, first).await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    assert_eq!(receipt["duplicate"], false);
    let (status, duplicate) = respond(&state, first).await;
    assert_eq!(status, StatusCode::OK, "{duplicate}");
    assert_eq!(duplicate["duplicate"], true);
    assert_eq!(
        state
            .checkpoints
            .load(&second_conversation.id)
            .await
            .unwrap()
            .as_ref(),
        Some(second_pending)
    );
    assert_eq!(
        state
            .session_store
            .hitl_request(&second.id)
            .unwrap()
            .unwrap()
            .status,
        DesktopHitlStatus::Pending
    );
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            if state
                .session_store
                .run(&first_run.id)
                .unwrap()
                .unwrap()
                .status
                == DesktopRunStatus::ReadyReview
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let saved = state
        .checkpoints
        .load(&first_conversation.id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(saved.hitl_responses.len(), 1);
    assert_eq!(
        saved
            .transcript
            .iter()
            .filter(|entry| entry.role == Role::Human)
            .count(),
        1
    );
    let answer: Value = serde_json::from_str(saved.hitl_answer(&first.id).unwrap()).unwrap();
    assert_eq!(answer["request_id"], first.id);
    assert_eq!(answer["run_id"], first_run.id);
}

#[tokio::test]
async fn hitl_identity_reopened_checkpoint_resumes_bound_and_legacy_pending_without_rebinding() {
    for legacy in [false, true] {
        let (state, path, root) = test_state_with_file_checkpoint(TOKEN);
        let conversation = conversation(&state, "identity-restart");
        let first = engine(&state, &conversation, None, vec![request()]);
        let mut pending = first
            .run(
                &conversation.id,
                "Execute after approval",
                Some("local-project"),
            )
            .await
            .unwrap();
        if legacy {
            pending.pending_hitl.as_mut().unwrap().id = RAW_ID.into();
            state.checkpoints.save(&pending).await.unwrap();
        }
        let id = pending.pending_hitl.as_ref().unwrap().id.clone();
        let checkpoints = Arc::new(SqliteCheckpointStore::open(&path.to_string_lossy()).unwrap());
        let restarted = ReActEngine::new(
            Arc::new(ScriptedLlm::new(vec![
                request(),
                AgentAction::Finish {
                    answer: "done".into(),
                },
            ])),
            Arc::new(state.tool_host.lock().unwrap().clone()),
            checkpoints.clone(),
            state.clock.clone(),
        )
        .with_hitl_validation(
            computer_use_v2::hitl_validation::NativeHitlValidation::capture(
                &state,
                &conversation,
                None,
                "new-runtime-message",
                None,
            ),
        );
        let still_pending = restarted
            .run(
                &conversation.id,
                "Execute after approval",
                Some("local-project"),
            )
            .await
            .unwrap();
        assert_eq!(still_pending.pending_hitl.as_ref().unwrap().id, id);
        assert!(
            restarted
                .accept_human_response(&conversation.id, "foreign-request", "no")
                .await
                .is_err()
        );
        let done = restarted
            .resume(&conversation.id, &id, "approved")
            .await
            .unwrap();
        assert_eq!(done.status, SessionStatus::Finished);
        assert_eq!(done.hitl_responses.len(), 1);
        assert_eq!(done.hitl_answer(&id), Some("approved"));
        assert_eq!(
            restarted
                .resume(&conversation.id, &id, "approved")
                .await
                .unwrap(),
            done
        );
        assert_eq!(
            checkpoints.load(&conversation.id).await.unwrap().unwrap(),
            done
        );
        drop(restarted);
        drop(checkpoints);
        drop(first);
        drop(state);
        std::fs::remove_dir_all(root).unwrap();
    }
}

fn engine(
    state: &Arc<LocalRuntimeState>,
    conversation: &LocalConversation,
    run: Option<&DesktopRun>,
    script: Vec<AgentAction>,
) -> ReActEngine {
    ReActEngine::new(
        Arc::new(ScriptedLlm::new(script)),
        Arc::new(state.tool_host.lock().unwrap().clone()),
        state.checkpoints.clone(),
        state.clock.clone(),
    )
    .with_hitl_validation(
        computer_use_v2::hitl_validation::NativeHitlValidation::capture(
            state,
            conversation,
            run,
            "identity-message",
            None,
        ),
    )
}

#[tokio::test]
async fn hitl_identity_repeated_model_id_persists_independently_in_two_conversations() {
    let state = test_state(TOKEN);
    let mut requests = Vec::new();
    for id in ["identity-conversation-a", "identity-conversation-b"] {
        let conversation = conversation(&state, id);
        let engine = engine(&state, &conversation, None, vec![request()]);
        let pending = engine
            .run(id, "Execute after approval", Some("local-project"))
            .await
            .unwrap();
        assert_eq!(pending.status, SessionStatus::AwaitingInput);
        let stored = state
            .persist_pending_hitl(id, None, &pending)
            .unwrap()
            .unwrap();
        assert_eq!(stored.id, pending.pending_hitl.as_ref().unwrap().id);
        assert_eq!(
            stored,
            state
                .persist_pending_hitl(id, None, &pending)
                .unwrap()
                .unwrap()
        );
        requests.push(stored);
    }
    assert_ne!(requests[0].id, requests[1].id);
    assert!(state.session_store.hitl_request(RAW_ID).unwrap().is_none());
}

#[tokio::test]
async fn hitl_identity_same_session_new_round_requires_a_new_answer() {
    let state = test_state(TOKEN);
    let conversation = conversation(&state, "identity-repeat-round");
    let engine = engine(
        &state,
        &conversation,
        None,
        vec![
            request(),
            request(),
            AgentAction::Finish {
                answer: "done".into(),
            },
        ],
    );
    let first = engine
        .run(
            &conversation.id,
            "Execute after approval",
            Some("local-project"),
        )
        .await
        .unwrap();
    let first_id = first.pending_hitl.as_ref().unwrap().id.clone();
    let second = engine
        .resume(&conversation.id, &first_id, "allowed")
        .await
        .unwrap();
    assert_eq!(second.status, SessionStatus::AwaitingInput);
    let second_id = second.pending_hitl.as_ref().unwrap().id.clone();
    assert_ne!(first_id, second_id);
    assert_eq!(second.hitl_answer(&first_id), Some("allowed"));
    assert!(second.hitl_answer(&second_id).is_none());
    assert!(
        engine
            .accept_human_response(&conversation.id, &first_id, "stale")
            .await
            .is_err()
    );
    let done = engine
        .resume(&conversation.id, &second_id, "allowed again")
        .await
        .unwrap();
    assert_eq!(done.status, SessionStatus::Finished);
    assert_eq!(
        done.transcript
            .iter()
            .filter(|entry| entry.role == Role::Human)
            .count(),
        2
    );
}
