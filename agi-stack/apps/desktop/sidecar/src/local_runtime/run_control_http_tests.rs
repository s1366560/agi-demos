use super::*;
use std::sync::atomic::AtomicUsize;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

#[path = "run_owner_http_tests.rs"]
mod run_owner_http_tests;
#[path = "agent_stop_http_tests.rs"]
mod agent_stop_http_tests;

#[derive(Clone, Copy)]
enum ResponseStage {
    Headers,
    JsonBody,
    SseBody,
}

struct HeldResponse {
    base: String,
    started: tokio::sync::oneshot::Receiver<Value>,
    closed: tokio::sync::oneshot::Receiver<()>,
    task: tokio::task::JoinHandle<()>,
}

impl Drop for HeldResponse {
    fn drop(&mut self) {
        self.task.abort();
    }
}

async fn read_request(socket: &mut tokio::net::TcpStream) -> Value {
    let mut bytes = Vec::new();
    let (header_end, content_length) = loop {
        let mut buffer = [0_u8; 4096];
        let count = socket.read(&mut buffer).await.unwrap();
        assert_ne!(count, 0, "request closed before its headers");
        bytes.extend_from_slice(&buffer[..count]);
        if let Some(index) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
            let headers = std::str::from_utf8(&bytes[..index]).unwrap();
            let length = headers.lines().find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().unwrap())
            });
            break (index + 4, length.expect("HTTP request content length"));
        }
    };
    while bytes.len() < header_end + content_length {
        let mut buffer = [0_u8; 4096];
        let count = socket.read(&mut buffer).await.unwrap();
        assert_ne!(count, 0, "request closed before its body");
        bytes.extend_from_slice(&buffer[..count]);
    }
    serde_json::from_slice(&bytes[header_end..header_end + content_length]).unwrap()
}

async fn held_response(stage: ResponseStage, resume: bool) -> HeldResponse {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}/v1", listener.local_addr().unwrap());
    let (started_tx, started) = tokio::sync::oneshot::channel();
    let (closed_tx, closed) = tokio::sync::oneshot::channel();
    let task = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let request = read_request(&mut socket).await;
        let response = match stage {
            ResponseStage::Headers => String::new(),
            ResponseStage::JsonBody => concat!(
                "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n",
                "content-length: 1000000\r\n\r\n{\"choices\":["
            ).to_string(),
            ResponseStage::SseBody => format!(
                "HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ncontent-length: 1000000\r\n\r\ndata: {}\n\n",
                json!({"choices":[{"delta":{"content":r#"{"kind":"finish","answer":"partial"#}}]})
            ),
        };
        socket.write_all(response.as_bytes()).await.unwrap();
        socket.flush().await.unwrap();
        started_tx.send(request).unwrap();
        let mut next = [0_u8; 1];
        match socket.read(&mut next).await {
            Ok(0) => {}
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::ConnectionReset | std::io::ErrorKind::BrokenPipe
                ) => {}
            result => panic!("interruption must close the held HTTP response: {result:?}"),
        }
        closed_tx.send(()).unwrap();
        if resume {
            let (mut socket, _) = listener.accept().await.unwrap();
            let request = read_request(&mut socket).await;
            assert_eq!(request["model"], "controlled-model");
            let body = json!({"choices":[{"message":{"content":r#"{"kind":"finish","answer":"resumed answer"}"#}}]}).to_string();
            socket.write_all(format!(
                "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}", body.len()
            ).as_bytes()).await.unwrap();
        }
    });
    HeldResponse {
        base,
        started,
        closed,
        task,
    }
}

#[derive(Default)]
struct ControlObserver {
    text: Mutex<String>,
    delta: tokio::sync::Notify,
    ends: AtomicUsize,
    finishes: AtomicUsize,
}

#[async_trait]
impl ReActObserver for ControlObserver {
    fn on_text_delta(&self, _: &str, _: u64, delta: &str) {
        self.text.lock().unwrap().push_str(delta);
        self.delta.notify_one();
    }

    fn on_text_end(&self, _: &str, _: u64) {
        self.ends.fetch_add(1, Ordering::SeqCst);
    }

    async fn on_finish(&self, _: &str, _: u64, _: &str) -> CoreResult<()> {
        self.finishes.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

async fn routed_state(base: &str) -> (Arc<LocalRuntimeState>, LocalConversation) {
    let state = test_state("http-control-session");
    state.mock_llm_enabled.store(0, Ordering::Release);
    let app = local_router(state.clone());
    let response = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "http-control-session",
            json!({"provider_type":"openai_compatible", "base_url":base, "auth_method":"none",
            "llm_model":"controlled-model", "allowed_models":["controlled-model"],
            "is_active":true, "expected_revision":0}),
        ))
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let response = app.oneshot(authenticated_json_request(
        "POST", "/api/v1/agent/conversations", "http-control-session",
        json!({"project_id":"local-project", "title":"Interrupt real model HTTP",
            "agent_config":{"selected_agent_id":"builtin:all-access", "capability_mode":"work",
                "llm_model_override":"controlled-model",
                "llm_route_override":{"provider_id":"local-runtime", "model_id":"controlled-model"}}}),
    )).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let value = response_json(response).await;
    let conversation = state
        .session_store
        .conversation(value["id"].as_str().unwrap())
        .unwrap()
        .unwrap();
    (state, conversation)
}

async fn interrupt_http(stage: ResponseStage, pause: bool) {
    interrupt_http_with_handler(stage, pause, false).await;
}

async fn registered_http_run(
    state: &Arc<LocalRuntimeState>,
    conversation: &LocalConversation,
) -> DesktopRun {
    state
        .session_store
        .replace_agent_plan_tasks(
            &conversation.id,
            &[json!({
                "id":"http-control-task", "conversation_id":conversation.id,
                "content":"Wait for the model", "status":"pending", "priority":"high",
                "order_index":0, "created_at":now_iso(), "updated_at":now_iso(),
            })],
        )
        .unwrap();
    let outcome = state
        .session_store
        .approve_plan_and_start(
            &conversation.id,
            &conversation.project_id,
            "http-control-key",
            "http-control-message",
            "Wait for the model",
            &now_iso(),
        )
        .unwrap();
    let run = state
        .session_store
        .prepare_run_for_execution(&outcome.run.id, &now_iso())
        .unwrap()
        .unwrap();
    state
        .ensure_authoritative_launch_checkpoint(&run)
        .await
        .unwrap();
    run
}

async fn interrupt_http_with_handler(stage: ResponseStage, pause: bool, through_handler: bool) {
    let mut upstream = held_response(stage, pause).await;
    let (state, conversation) = routed_state(&upstream.base).await;
    let run = if through_handler {
        Some(registered_http_run(&state, &conversation).await)
    } else {
        None
    };
    let llm = state
        .llm_for_role(&conversation, LlmWorkloadRole::Default)
        .await
        .unwrap();
    let tools = Arc::new(state.tool_host.lock().unwrap().clone());
    let engine = ReActEngine::new(llm, tools, state.checkpoints.clone(), state.clock.clone());
    let control = if let Some(run) = run.as_ref() {
        state
            .claim_agent_run(&conversation.id, Some(&run.id))
            .unwrap()
    } else {
        Arc::new(LocalRunControl::new(state.session_store.clone(), None))
    };
    let observer = Arc::new(ControlObserver::default());
    let task = tokio::spawn({
        let engine = engine.clone();
        let control = control.clone();
        let observer = observer.clone();
        let conversation = conversation.clone();
        async move {
            engine
                .run_observed_controlled(
                    &conversation.id,
                    "Wait for the model",
                    Some("local-project"),
                    observer,
                    control,
                )
                .await
        }
    });
    let request = tokio::time::timeout(std::time::Duration::from_secs(5), &mut upstream.started)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(request["model"], "controlled-model");
    assert_eq!(request["stream"], true);
    if matches!(stage, ResponseStage::SseBody) {
        tokio::time::timeout(std::time::Duration::from_secs(5), observer.delta.notified())
            .await
            .unwrap();
        assert_eq!(*observer.text.lock().unwrap(), "partial");
    }
    if let Some(run) = run.as_ref() {
        let app = local_router(state.clone());
        let action = if pause { "pause" } else { "cancel" };
        let path = format!("/api/v1/agent/runs/{}/{action}", run.id);
        let stale = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                &path,
                "http-control-session",
                json!({"expected_revision":run.revision - 1}),
            ))
            .await
            .unwrap();
        assert_eq!(stale.status(), StatusCode::CONFLICT);
        assert!(
            !task.is_finished(),
            "a rejected command must leave the HTTP request active"
        );
        assert_eq!(
            control.directive(&conversation.id, 0).await.unwrap(),
            RunDirective::Continue
        );
        let response = app
            .oneshot(authenticated_json_request(
                "POST",
                &path,
                "http-control-session",
                json!({"expected_revision":run.revision}),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let response = response_json(response).await;
        assert_eq!(response["accepted"], true);
        assert_eq!(response["status"], format!("{action}_requested"));
        assert_eq!(response["run"]["id"], run.id);
    } else if pause {
        control.request_pause();
    } else {
        control.request_cancel();
    }
    let result = tokio::time::timeout(std::time::Duration::from_secs(5), task)
        .await
        .expect("control must finish without releasing the upstream response")
        .unwrap()
        .unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(5), &mut upstream.closed)
        .await
        .expect("control must drop the actual HTTP response body")
        .unwrap();
    let expected = if pause {
        SessionStatus::Paused
    } else {
        SessionStatus::Cancelled
    };
    assert_eq!(result.status, expected);
    assert_eq!(result.round, 0);
    assert!(result.answer.is_none());
    assert!(result.completed_tool_calls.is_empty());
    assert!(!result
        .transcript
        .iter()
        .any(|entry| matches!(entry.role, Role::Action | Role::Answer)));
    assert_eq!(observer.finishes.load(Ordering::SeqCst), 0);
    assert_eq!(
        observer.ends.load(Ordering::SeqCst),
        usize::from(matches!(stage, ResponseStage::SseBody))
    );
    let saved = state
        .checkpoints
        .load(&conversation.id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(saved.status, expected);
    assert!(saved.answer.is_none());
    if pause {
        engine
            .accept_controlled_resume(&conversation.id)
            .await
            .unwrap();
        let resumed = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            engine.run_controlled(
                &conversation.id,
                "Wait for the model",
                Some("local-project"),
                Arc::new(LocalRunControl::new(state.session_store.clone(), None)),
            ),
        )
        .await
        .unwrap()
        .unwrap();
        assert_eq!(resumed.status, SessionStatus::Finished);
        assert_eq!(resumed.answer.as_deref(), Some("resumed answer"));
        assert!(resumed.completed_tool_calls.is_empty());
    }
}

#[tokio::test]
async fn pause_drops_http_waiting_for_headers_and_can_resume() {
    interrupt_http(ResponseStage::Headers, true).await;
}

#[tokio::test]
async fn cancel_drops_http_waiting_for_headers() {
    interrupt_http(ResponseStage::Headers, false).await;
}

#[tokio::test]
async fn pause_drops_incomplete_json_response_and_can_resume() {
    interrupt_http(ResponseStage::JsonBody, true).await;
}

#[tokio::test]
async fn cancel_drops_incomplete_json_response() {
    interrupt_http(ResponseStage::JsonBody, false).await;
}

#[tokio::test]
async fn pause_drops_partial_sse_without_finishing_and_can_resume() {
    interrupt_http(ResponseStage::SseBody, true).await;
}

#[tokio::test]
async fn cancel_drops_partial_sse_without_finishing() {
    interrupt_http(ResponseStage::SseBody, false).await;
}

#[tokio::test]
async fn pause_handler_interrupts_real_sse_and_preserves_a_resumable_checkpoint() {
    interrupt_http_with_handler(ResponseStage::SseBody, true, true).await;
}

#[tokio::test]
async fn cancel_handler_interrupts_real_http_before_response_headers() {
    interrupt_http_with_handler(ResponseStage::Headers, false, true).await;
}

#[tokio::test]
async fn parent_control_interrupts_all_waiting_children_and_late_waiters() {
    for pause in [true, false] {
        let state = test_state("http-control-parent");
        let (conversation, run) = seed_controlled_run(&state, "http-control-parent");
        let parent = state
            .claim_agent_run(&conversation.id, Some(&run.id))
            .unwrap();
        let mut children = Vec::new();
        for id in ["child-a", "child-b", "child-late"] {
            children.push(
                state
                    .subagent_controls
                    .register(
                        id,
                        &conversation.id,
                        &run,
                        "child-agent",
                        "builtin:all-access",
                        parent.clone(),
                    )
                    .unwrap(),
            );
        }
        let mut first = Box::pin(children[0].wait_for_interrupt("child-a", 0));
        let mut second = Box::pin(children[1].wait_for_interrupt("child-b", 0));
        assert!(futures_util::poll!(first.as_mut()).is_pending());
        assert!(futures_util::poll!(second.as_mut()).is_pending());
        if pause {
            parent.request_pause();
        } else {
            parent.request_cancel();
        }
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            first.await.unwrap();
            second.await.unwrap();
            children[2]
                .wait_for_interrupt("child-late", 0)
                .await
                .unwrap();
        })
        .await
        .expect("a parent command wakes all child subscribers");
        for (child, id) in children.iter().zip(["child-a", "child-b", "child-late"]) {
            assert_eq!(
                child.directive(id, 0).await.unwrap(),
                if pause {
                    RunDirective::Pause
                } else {
                    RunDirective::Cancel
                }
            );
        }
    }
}

#[tokio::test]
async fn authorized_child_kill_wakes_only_the_target_interrupt_waiter() {
    let state = test_state("http-control-child");
    let auth = state
        .session_store
        .validate_session_credential("http-control-child", Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let (conversation, run) = seed_controlled_run(&state, "http-control-child");
    state
        .ensure_authoritative_launch_checkpoint(&run)
        .await
        .unwrap();
    state.session_store.put_managed_resource(
        ManagedResourceKind::SubAgent, "tenant", "local", "control-reader", "active", None,
        json!({"id":"control-reader", "name":"control-reader", "status":"active", "enabled":true,
            "project_id":"local-project", "system_prompt":"Inspect only.", "allowed_tools":[], "allowed_skills":[], "allowed_mcp_servers":[]}),
        Utc::now().timestamp_millis(),
    ).unwrap();
    let parent = state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .unwrap();
    let child = state
        .subagent_controls
        .register(
            "child-target",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            parent.clone(),
        )
        .unwrap();
    let sibling = state
        .subagent_controls
        .register(
            "child-sibling",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            parent.clone(),
        )
        .unwrap();
    let mut target_wait = Box::pin(child.wait_for_interrupt("child-target", 0));
    let mut sibling_wait = Box::pin(sibling.wait_for_interrupt("child-sibling", 0));
    assert!(futures_util::poll!(target_wait.as_mut()).is_pending());
    assert!(futures_util::poll!(sibling_wait.as_mut()).is_pending());
    let command = json!({"type":"kill_run", "conversation_id":conversation.id, "run_id":"child-target",
        "expected_run_revision":run.revision, "idempotency_key":"kill-http-child", "cascade":false});
    let receipt = subagent_control::handle_command(&state, &auth, &command).await;
    assert_eq!(receipt["accepted"], true, "{receipt}");
    tokio::time::timeout(std::time::Duration::from_secs(2), target_wait)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        child.directive("child-target", 0).await.unwrap(),
        RunDirective::Cancel
    );
    assert!(futures_util::poll!(sibling_wait.as_mut()).is_pending());
    assert_eq!(
        parent.directive(&conversation.id, 0).await.unwrap(),
        RunDirective::Continue
    );
}
