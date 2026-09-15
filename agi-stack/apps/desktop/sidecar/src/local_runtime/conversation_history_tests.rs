use super::*;

#[derive(Default)]
struct HistoryCapturingLlm {
    calls: Mutex<Vec<(String, Vec<TranscriptEntry>)>>,
}

#[async_trait]
impl LlmPort for HistoryCapturingLlm {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!("chat only")
    }

    async fn decide(
        &self,
        goal: &str,
        _: u64,
        transcript: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        self.calls
            .lock()
            .unwrap()
            .push((goal.to_owned(), transcript.to_vec()));
        Ok(AgentAction::Finish {
            answer: "score: 20260914".to_owned(),
        })
    }
}

#[tokio::test]
async fn followup_provider_receives_persisted_history_without_other_conversations() {
    let state = test_state("history-test");
    let llm = Arc::new(HistoryCapturingLlm::default());
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    seed_plan_conversation(&state, "history-own");
    seed_plan_conversation(&state, "history-other");
    for (conversation, message, id) in [
        ("history-other", "OTHER_CONVERSATION_SECRET", "other-1"),
        ("history-own", "NATIVE_PLUGIN_VISIBLE_RESULT", "own-1"),
        (
            "history-own",
            "Recall the previous marker and score",
            "own-2",
        ),
    ] {
        Arc::clone(&state)
            .run_agent_message(
                conversation.to_owned(),
                "local-project".to_owned(),
                message.to_owned(),
                id.to_owned(),
                None,
                None,
            )
            .await;
    }
    let calls = llm.calls.lock().unwrap();
    let (goal, transcript) = calls.last().expect("followup reached provider");
    assert!(goal.contains("Recall the previous marker"));
    let context = serde_json::to_string(transcript).unwrap();
    assert!(
        context.contains("NATIVE_PLUGIN_VISIBLE_RESULT"),
        "provider history: {context}"
    );
    assert!(context.contains("20260914"));
    assert!(!context.contains("OTHER_CONVERSATION_SECRET"));
    assert!(
        !context.contains("Recall the previous marker"),
        "current goal must not duplicate history"
    );
}

#[test]
fn history_preserves_public_tool_evidence_but_not_execution_authority_or_private_events() {
    let state = test_state("history-test");
    seed_plan_conversation(&state, "history-tools");
    for (kind, message_id, content, data) in [
        (
            "user_message",
            Some("previous"),
            Some("NATIVE_PLUGIN_VISIBLE_RESULT"),
            json!({}),
        ),
        (
            "act",
            None,
            None,
            json!({"tool_name":"plugin__authorized", "tool_input":"{\"input\":\"NATIVE_PLUGIN_VISIBLE_RESULT\"}"}),
        ),
        (
            "observe",
            None,
            None,
            json!({"tool_name":"plugin__authorized", "tool_output":"{\"score\":20260914}", "is_error":false}),
        ),
        (
            "observe",
            None,
            None,
            json!({"tool_name":"unknown", "tool_output":"[UNAVAILABLE]"}),
        ),
        (
            "subagent_tool_result",
            None,
            None,
            json!({"tool_output":"PRIVATE_CHILD_RESULT"}),
        ),
        (
            "permission_asked",
            None,
            None,
            json!({"secret":"PRIVATE_AUTHORIZATION"}),
        ),
        (
            "user_message",
            Some("current"),
            Some("current goal"),
            json!({}),
        ),
    ] {
        let event = state.timeline_item(
            kind,
            "history-tools".to_owned(),
            message_id.map(str::to_owned),
            None,
            content.map(str::to_owned),
            data,
        );
        state
            .session_store
            .append_timeline("history-tools", &event)
            .unwrap();
    }
    let checkpoint = state
        .conversation_turn_checkpoint("history-tools", "local-project", "current", "current goal")
        .unwrap();
    let context = serde_json::to_string(&checkpoint.transcript).unwrap();
    assert!(context.contains("NATIVE_PLUGIN_VISIBLE_RESULT"));
    assert!(context.contains("20260914"));
    assert!(context.contains("[UNAVAILABLE]"));
    assert!(!context.contains("PRIVATE_"));
    assert!(!context.contains("current goal"));
    assert_eq!(checkpoint.round, 0);
    assert!(checkpoint.completed_tool_calls.is_empty());
    assert!(checkpoint.hitl_responses.is_empty());
    assert!(checkpoint.pending_hitl.is_none());
    assert!(checkpoint.applied_steering_ids.is_empty());
    assert!(checkpoint.answer.is_none());
    assert_eq!(checkpoint.status, SessionStatus::Running);
    assert!(state
        .conversation_turn_checkpoint("history-tools", "other-project", "next", "x")
        .is_err());
}

#[tokio::test]
async fn authoritative_new_turn_restores_history_and_resume_keeps_checkpoint_exactly() {
    let state = test_state("history-test");
    let (conversation, run) = seed_queued_authoritative_run(&state, "history-approved");
    let event = state.timeline_item(
        "assistant_message",
        conversation.id.clone(),
        Some("earlier".to_owned()),
        Some("assistant"),
        Some("Confirmed plan marker 20260914".to_owned()),
        json!({}),
    );
    state
        .session_store
        .append_timeline(&conversation.id, &event)
        .unwrap();
    let mut old = SessionState::new(&conversation.id, "previous goal", Some("local-project"));
    old.status = SessionStatus::Finished;
    old.round = 10;
    old.answer = Some("old answer".to_owned());
    state.checkpoints.save(&old).await.unwrap();
    assert!(state
        .ensure_authoritative_launch_checkpoint(&run)
        .await
        .unwrap());
    let first = state
        .checkpoints
        .load(&conversation.id)
        .await
        .unwrap()
        .unwrap();
    assert!(serde_json::to_string(&first.transcript)
        .unwrap()
        .contains("Confirmed plan marker 20260914"));
    assert_eq!(first.goal, run.request_message);
    assert_eq!(first.round, 0);
    assert!(first.answer.is_none());
    assert!(!state
        .ensure_authoritative_launch_checkpoint(&run)
        .await
        .unwrap());
    assert_eq!(
        state
            .checkpoints
            .load(&conversation.id)
            .await
            .unwrap()
            .unwrap(),
        first
    );
}

#[tokio::test]
async fn followup_http_provider_wire_contains_previous_user_and_answer() {
    let requests = Arc::new(tokio::sync::Mutex::new(Vec::<Value>::new()));
    let app = Router::new().route("/v1/chat/completions", post({
        let requests = requests.clone();
        move |Json(body): Json<Value>| {
            let requests = requests.clone();
            async move {
                requests.lock().await.push(body);
                Json(json!({"choices":[{"message":{"content":"{\"kind\":\"finish\",\"answer\":\"score: 20260914\"}"}}]}))
            }
        }
    }));
    let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let state = test_state("history-wire");
    seed_plan_conversation(&state, "history-wire");
    *state.test_llm_override.lock().unwrap() = Some(Arc::new(HttpLlm::new(
        format!("http://{address}/v1"),
        "test-model",
    )));
    for (message, id) in [
        ("NATIVE_PLUGIN_VISIBLE_RESULT", "wire-first"),
        ("Recall prior marker and score", "wire-second"),
    ] {
        Arc::clone(&state)
            .run_agent_message(
                "history-wire".to_owned(),
                "local-project".to_owned(),
                message.to_owned(),
                id.to_owned(),
                None,
                None,
            )
            .await;
    }
    let requests = requests.lock().await;
    assert_eq!(requests.len(), 2);
    let wire = serde_json::to_string(&requests[1]["messages"]).unwrap();
    assert!(
        wire.contains("NATIVE_PLUGIN_VISIBLE_RESULT"),
        "provider wire: {wire}"
    );
    assert!(wire.contains("score: 20260914"));
    assert!(wire.contains("Recall prior marker and score"));
    server.abort();
}

#[tokio::test]
async fn display_content_is_persisted_while_provider_receives_raw_planning_prompt() {
    let state = test_state("display-test");
    let llm = Arc::new(HistoryCapturingLlm::default());
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    seed_plan_conversation(&state, "display-own");
    let raw = "Runtime planning constraints\nOriginal objective";
    let body = json!({"project_id":"local-project", "message":raw,
        "message_id":"display-message", "display_content":"Original objective"});
    let response = local_router(state.clone()).oneshot(authenticated_json_request(
        "POST", "/api/v1/agent/conversations/display-own/messages", "display-test", body.clone(),
    )).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            if state.session_store.timeline("display-own", 100).unwrap().iter()
                .any(|item| item["type"] == "assistant_message") { break; }
            tokio::task::yield_now().await;
        }
    }).await.unwrap();
    let timeline = state.session_store.timeline("display-own", 100).unwrap();
    let user = timeline.iter().find(|item| item["type"] == "user_message").unwrap();
    assert_eq!(user["content"], raw);
    assert_eq!(user["payload"]["display_content"], "Original objective");
    assert_eq!(user["data"]["display_content"], "Original objective");
    assert!(llm.calls.lock().unwrap()[0].0.contains(raw));
    let mut changed = body;
    changed["display_content"] = json!("Different objective");
    let response = local_router(state.clone()).oneshot(authenticated_json_request(
        "POST", "/api/v1/agent/conversations/display-own/messages", "display-test", changed,
    )).await.unwrap();
    assert_eq!(response.status(), StatusCode::CONFLICT);
}

#[test]
fn display_content_http_schema_rejects_non_string_blank_and_oversized_values() {
    for invalid in [Value::Null, json!(3), json!("  "), json!("字".repeat(21846))] {
        assert!(serde_json::from_value::<RunConversationBody>(json!({
            "message":"raw", "display_content":invalid,
        })).is_err());
    }
    assert!(serde_json::from_value::<RunConversationBody>(json!({"message":"legacy"})).is_ok());
}

#[tokio::test]
async fn display_content_websocket_validates_and_persists_explicit_user_text() {
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::client::IntoClientRequest;
    let state = test_state("display-ws-test");
    let llm = Arc::new(HistoryCapturingLlm::default());
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    seed_plan_conversation(&state, "display-ws");
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let app = local_router(state.clone());
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap(); });
    let mut request = format!("ws://{address}/api/v1/agent/ws").into_client_request().unwrap();
    request.headers_mut().insert("authorization", "Bearer display-ws-test".parse().unwrap());
    request.headers_mut().insert("x-agistack-launch", "display-ws-test".parse().unwrap());
    let (mut socket, _) = tokio_tungstenite::connect_async(request).await.unwrap();
    let mut body = json!({"type":"send_message", "project_id":"local-project", "conversation_id":"display-ws", "message_id":"display-ws-message", "message":"Raw runtime constraints: revise plan", "display_content":null});
    socket.send(tokio_tungstenite::tungstenite::Message::Text(body.to_string())).await.unwrap();
    let rejected = socket.next().await.unwrap().unwrap().into_text().unwrap();
    assert_eq!(serde_json::from_str::<Value>(&rejected).unwrap()["code"], "invalid_display_content");
    assert!(llm.calls.lock().unwrap().is_empty());
    body["display_content"] = json!("Original revision feedback");
    socket.send(tokio_tungstenite::tungstenite::Message::Text(body.to_string())).await.unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            if state.session_store.timeline("display-ws", 100).unwrap().iter()
                .any(|item| item["type"] == "assistant_message") { break; }
            tokio::task::yield_now().await;
        }
    }).await.unwrap();
    let timeline = state.session_store.timeline("display-ws", 100).unwrap();
    let user = timeline.iter().find(|item| item["type"] == "user_message").unwrap();
    assert_eq!(user["content"], body["message"]);
    assert_eq!(user["data"]["display_content"], body["display_content"]);
    assert!(llm.calls.lock().unwrap()[0].0.contains(body["message"].as_str().unwrap()));
    server.abort();
}

async fn assert_websocket_client_turn_identity(first_http: bool, changed_field: Option<&str>, second_http: bool) {
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::client::IntoClientRequest;
    let state = test_state("ws-identity-test");
    let llm = Arc::new(HistoryCapturingLlm::default());
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    seed_plan_conversation(&state, "ws-identity");
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let app = local_router(state.clone());
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap(); });
    let mut request = format!("ws://{address}/api/v1/agent/ws").into_client_request().unwrap();
    request.headers_mut().insert("authorization", "Bearer ws-identity-test".parse().unwrap());
    request.headers_mut().insert("x-agistack-launch", "ws-identity-test".parse().unwrap());
    let (mut socket, _) = tokio_tungstenite::connect_async(request).await.unwrap();
    let mut body = json!({"type":"send_message", "project_id":"local-project", "conversation_id":"ws-identity", "message_id":"same-turn", "message":"First raw instruction", "display_content":"First objective"});
    if first_http {
        let response = local_router(state.clone()).oneshot(authenticated_json_request(
            "POST", "/api/v1/agent/conversations/ws-identity/messages", "ws-identity-test", body.clone(),
        )).await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
    } else {
        socket.send(tokio_tungstenite::tungstenite::Message::Text(body.to_string())).await.unwrap();
        let ack = socket.next().await.unwrap().unwrap().into_text().unwrap();
        assert_eq!(serde_json::from_str::<Value>(&ack).unwrap()["type"], "ack");
    }
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let completed = state.session_store.timeline("ws-identity", 100).unwrap().iter()
                .any(|item| item["type"] == "assistant_message");
            let active = state.agent_runs.lock().unwrap().contains_key("ws-identity");
            if completed && !active { break; }
            tokio::task::yield_now().await;
        }
    }).await.unwrap();
    assert_eq!(llm.calls.lock().unwrap().len(), 1);
    if second_http {
        let response = local_router(state.clone()).oneshot(authenticated_json_request(
            "POST", "/api/v1/agent/conversations/ws-identity/messages", "ws-identity-test", body,
        )).await.unwrap();
        let status = response.status();
        let result = response_json(response).await;
        server.abort();
        assert_eq!(status, StatusCode::OK);
        assert_eq!(result["replayed"], true, "cross-transport replay must reuse the original turn: {result}");
        assert_eq!(llm.calls.lock().unwrap().len(), 1);
        return;
    }
    let initial_selection = state.session_store.execution_selection("ws-identity").unwrap();
    if let Some(field) = changed_field {
        body[field] = json!(if field == "agent_id" { "builtin:all-access" } else { "Different request value" });
    }
    socket.send(tokio_tungstenite::tungstenite::Message::Text(body.to_string())).await.unwrap();
    // Read the second request's ack/error, skipping buffered first-turn timeline events.
    let receipt = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let event = socket.next().await.unwrap().unwrap().into_text().unwrap();
            let event: Value = serde_json::from_str(&event).unwrap();
            if event["type"] == "ack" || event["type"] == "error" { break event; }
        }
    }).await.unwrap();
    if changed_field.is_some() {
        server.abort();
        assert_eq!(receipt["code"], "MESSAGE_ID_CONFLICT", "request conflict must not be acknowledged: {receipt}");
        assert_eq!(state.session_store.execution_selection("ws-identity").unwrap(), initial_selection);
    } else {
        // A successful replay must not start another provider decision after the first run ended.
        let second_decision = tokio::time::timeout(std::time::Duration::from_millis(250), async {
            loop {
                if llm.calls.lock().unwrap().len() > 1 { break; }
                tokio::task::yield_now().await;
            }
        }).await;
        server.abort();
        assert!(second_decision.is_err(), "same client turn reached provider twice after terminal completion");
    }
}

#[tokio::test]
async fn websocket_client_turn_replay_after_completion_does_not_execute_again() {
    assert_websocket_client_turn_identity(false, None, false).await;
}

#[tokio::test]
async fn websocket_client_turn_replay_after_http_completion_does_not_execute_again() {
    assert_websocket_client_turn_identity(true, None, false).await;
}

#[tokio::test]
async fn websocket_client_turn_same_id_different_display_is_a_conflict() {
    assert_websocket_client_turn_identity(false, Some("display_content"), false).await;
}

#[tokio::test]
async fn websocket_client_turn_same_id_different_raw_content_is_a_conflict() {
    assert_websocket_client_turn_identity(false, Some("message"), false).await;
}

#[tokio::test]
async fn websocket_client_turn_can_be_replayed_through_http_without_execution() {
    assert_websocket_client_turn_identity(false, None, true).await;
}

#[tokio::test]
async fn websocket_client_turn_invalid_message_ids_have_no_side_effects() {
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::client::IntoClientRequest;
    let state = test_state("ws-invalid-id-test");
    let llm = Arc::new(HistoryCapturingLlm::default());
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    seed_plan_conversation(&state, "ws-invalid-id");
    let original = execution_selection::ExecutionSelection {
        agent_id: Some("retained-agent".to_owned()), ..Default::default()
    };
    state.session_store.save_execution_selection("ws-invalid-id", "original", &original, &now_iso()).unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let app = local_router(state.clone());
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap(); });
    let mut request = format!("ws://{address}/api/v1/agent/ws").into_client_request().unwrap();
    request.headers_mut().insert("authorization", "Bearer ws-invalid-id-test".parse().unwrap());
    request.headers_mut().insert("x-agistack-launch", "ws-invalid-id-test".parse().unwrap());
    let (mut socket, _) = tokio_tungstenite::connect_async(request).await.unwrap();
    for invalid in [Value::Null, json!(17), json!(""), json!(" "), json!("a".repeat(256))] {
        let body = json!({"type":"send_message", "project_id":"local-project", "conversation_id":"ws-invalid-id", "message_id":invalid, "message":"Must never execute", "agent_id":"builtin:all-access"});
        socket.send(tokio_tungstenite::tungstenite::Message::Text(body.to_string())).await.unwrap();
        let reply = socket.next().await.unwrap().unwrap().into_text().unwrap();
        let reply: Value = serde_json::from_str(&reply).unwrap();
        assert_eq!(reply["code"], "INVALID_MESSAGE_ID", "{reply}");
        assert!(llm.calls.lock().unwrap().is_empty());
        assert_eq!(state.session_store.execution_selection("ws-invalid-id").unwrap(), Some(original.clone()));
        assert!(state.session_store.timeline("ws-invalid-id", 100).unwrap().is_empty());
    }
    server.abort();
}

#[tokio::test]
async fn websocket_client_turn_conflict_does_not_overwrite_execution_selection() {
    assert_websocket_client_turn_identity(false, Some("agent_id"), false).await;
}
