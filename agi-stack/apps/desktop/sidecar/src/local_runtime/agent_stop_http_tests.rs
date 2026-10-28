//! The composer planning wire must interrupt the actual local WebSocket run.
use super::*;
use tokio_tungstenite::tungstenite::{client::IntoClientRequest, Message as WsMessage};

type Socket =
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;

async fn receive_stop_receipt(socket: &mut Socket) -> Value {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let message = socket.next().await.unwrap().unwrap();
            let value: Value = serde_json::from_str(message.to_text().unwrap()).unwrap();
            if value["action"] == "stop_session" {
                return value;
            }
        }
    })
    .await
    .unwrap()
}

async fn stop_planning_http(stage: ResponseStage) {
    let mut upstream = held_response(stage, false).await;
    let (state, conversation) = routed_state(&upstream.base).await;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let app = local_router(state.clone());
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let mut request = format!("ws://{address}/api/v1/agent/ws")
        .into_client_request()
        .unwrap();
    request.headers_mut().insert(
        "authorization",
        "Bearer http-control-session".parse().unwrap(),
    );
    request
        .headers_mut()
        .insert("x-agistack-launch", "http-control-session".parse().unwrap());
    let (mut socket, _) = tokio_tungstenite::connect_async(request).await.unwrap();
    socket
        .send(WsMessage::Text(
            json!({
                "type":"send_message", "conversation_id":conversation.id,
                "project_id":conversation.project_id, "message_id":"planning-stop-message",
                "message":"Wait for this model response",
            })
            .to_string(),
        ))
        .await
        .unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(5), &mut upstream.started)
        .await
        .expect("planning must reach the real model HTTP server")
        .unwrap();

    for message_id in [None, Some("previous-planning-message")] {
        let mut command = json!({"type":"stop_session", "conversation_id":conversation.id});
        if let Some(message_id) = message_id {
            command["message_id"] = json!(message_id);
        }
        socket
            .send(WsMessage::Text(command.to_string()))
            .await
            .unwrap();
        let receipt = receive_stop_receipt(&mut socket).await;
        assert_eq!(receipt["type"], "error");
        assert_eq!(receipt["code"], "STOP_SESSION_FAILED");
        assert!(futures_util::poll!(&mut upstream.closed).is_pending());
    }
    let command = json!({"type":"stop_session", "conversation_id":conversation.id,
        "message_id":"planning-stop-message"});
    socket
        .send(WsMessage::Text(command.to_string()))
        .await
        .unwrap();
    let receipt = receive_stop_receipt(&mut socket).await;
    assert_eq!(receipt["type"], "ack");
    assert_eq!(receipt["status"], "cancel_requested");
    assert_eq!(receipt["message_id"], "planning-stop-message");
    tokio::time::timeout(std::time::Duration::from_secs(5), &mut upstream.closed)
        .await
        .expect("composer Stop must close the model HTTP socket")
        .unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let timeline = state.session_store.timeline(&conversation.id, 100).unwrap();
            if timeline.iter().any(|item| {
                item["type"] == "cancelled" && item["data"]["message_id"] == "planning-stop-message"
            }) && !state
                .agent_runs
                .lock()
                .unwrap()
                .contains_key(&conversation.id)
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("the exact planning turn must publish its terminal cancellation");
    let checkpoint = state
        .checkpoints
        .load(&conversation.id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(checkpoint.status, SessionStatus::Cancelled);
    assert!(checkpoint.answer.is_none());
    assert!(!state
        .session_store
        .timeline(&conversation.id, 100)
        .unwrap()
        .iter()
        .any(|item| item["type"] == "assistant_message"));

    // A delayed retransmission must not cancel a newer turn in this conversation.
    let successor = state.claim_agent_run(&conversation.id, None).unwrap();
    *successor.message_id.lock().unwrap() = Some("successor-message".into());
    socket
        .send(WsMessage::Text(command.to_string()))
        .await
        .unwrap();
    let receipt = receive_stop_receipt(&mut socket).await;
    assert_eq!(receipt["code"], "STOP_SESSION_FAILED");
    assert_eq!(
        successor.directive(&conversation.id, 0).await.unwrap(),
        RunDirective::Continue
    );
    state.release_agent_run_if_control(&conversation.id, &successor);
    socket.close(None).await.unwrap();
    server.abort();
}

#[tokio::test]
async fn composer_stop_websocket_closes_planning_http_headers_and_rejects_stale_turns() {
    stop_planning_http(ResponseStage::Headers).await;
}

#[tokio::test]
async fn composer_stop_websocket_closes_partial_planning_sse_without_late_finish() {
    stop_planning_http(ResponseStage::SseBody).await;
}

#[tokio::test]
async fn composer_planning_stop_rejects_authoritative_run_and_wrong_context() {
    let (state, conversation) = routed_state("http://127.0.0.1:1/v1").await;
    let run = registered_http_run(&state, &conversation).await;
    let control = state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .unwrap();
    *control.message_id.lock().unwrap() = Some(run.message_id.clone());
    let auth = state
        .session_store
        .validate_session_credential("http-control-session", Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let command = json!({"type":"stop_session", "conversation_id":conversation.id,
        "message_id":run.message_id});
    let receipt = crate::local_runtime::agent_stop::handle_command(&state, &auth, &command);
    assert_eq!(receipt["code"], "STOP_SESSION_FAILED");
    assert_eq!(
        control.directive(&conversation.id, 0).await.unwrap(),
        RunDirective::Continue
    );
    let mut changed = auth.clone();
    changed.workspace.project_id = "other-project".into();
    let receipt = crate::local_runtime::agent_stop::handle_command(&state, &changed, &command);
    assert_eq!(receipt["code"], "STOP_SESSION_FAILED");
    assert_eq!(
        control.directive(&conversation.id, 0).await.unwrap(),
        RunDirective::Continue
    );
    state.release_agent_run_if_control(&conversation.id, &control);
}
