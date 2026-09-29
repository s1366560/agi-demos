use super::*;
use tokio::sync::Notify;

struct GatedStreamingLlm {
    release: Notify,
    fail: bool,
}

#[async_trait]
impl LlmPort for GatedStreamingLlm {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!("chat only")
    }

    async fn decide(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        panic!("runtime must preserve the streaming method through every wrapper")
    }

    async fn decide_with_tools_stream(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[agistack_core::ports::ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        on_text("Hello");
        self.release.notified().await;
        if self.fail {
            return Err(CoreError::Llm("stream interrupted".into()));
        }
        on_text(" world");
        Ok(AgentAction::Finish {
            answer: "Hello world".into(),
        })
    }
}

async fn next_text_delta(events: &mut broadcast::Receiver<Value>) -> Value {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let event = events.recv().await.unwrap();
            if event["type"] == "text_delta" {
                return event;
            }
        }
    })
    .await
    .expect("first token must arrive before the provider is released")
}

#[tokio::test]
async fn runtime_streams_before_completion_and_persists_one_final_answer() {
    let state = test_state("streaming-test");
    seed_plan_conversation(&state, "streaming-conversation");
    let llm = Arc::new(GatedStreamingLlm {
        release: Notify::new(),
        fail: false,
    });
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    let mut events = state.events.subscribe();
    let run = tokio::spawn(Arc::clone(&state).run_agent_message(
        "streaming-conversation".into(),
        "local-project".into(),
        "Greet me".into(),
        "streaming-message".into(),
        None,
        None,
    ));
    let first = next_text_delta(&mut events).await;
    assert_eq!(first["data"]["delta"], "Hello");
    assert!(!run.is_finished());
    let pending = state
        .session_store
        .timeline("streaming-conversation", 100)
        .unwrap();
    assert!(!pending
        .iter()
        .any(|item| item["type"] == "assistant_message"));
    assert!(!pending.iter().any(|item| item["type"] == "text_delta"));
    llm.release.notify_one();
    run.await.unwrap();
    let final_items = state
        .session_store
        .timeline("streaming-conversation", 100)
        .unwrap();
    let answers = final_items
        .iter()
        .filter(|item| item["type"] == "assistant_message")
        .collect::<Vec<_>>();
    assert_eq!(answers.len(), 1);
    assert_eq!(answers[0]["content"], "Hello world");
    assert_eq!(answers[0]["message_id"], first["message_id"]);
}

#[tokio::test]
async fn streaming_failure_does_not_fail_over_after_visible_text() {
    let first = Arc::new(GatedStreamingLlm {
        release: Notify::new(),
        fail: true,
    });
    first.release.notify_one();
    let failover = FailoverLlm::from_candidates(vec![first, Arc::new(UnconfiguredLocalLlm)]);
    let text = Mutex::new(String::new());
    let result = failover
        .decide_with_tools_stream("greet", 0, &[], &[], &|delta| {
            text.lock().unwrap().push_str(delta);
        })
        .await;
    assert!(result
        .unwrap_err()
        .to_string()
        .contains("stream interrupted"));
    assert_eq!(*text.lock().unwrap(), "Hello");
}

#[tokio::test]
async fn failed_stream_never_persists_a_successful_answer() {
    let state = test_state("streaming-failure");
    seed_plan_conversation(&state, "failed-stream");
    let llm = Arc::new(GatedStreamingLlm {
        release: Notify::new(),
        fail: true,
    });
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    let mut events = state.events.subscribe();
    let run = tokio::spawn(Arc::clone(&state).run_agent_message(
        "failed-stream".into(),
        "local-project".into(),
        "Greet me".into(),
        "failed-message".into(),
        None,
        None,
    ));
    next_text_delta(&mut events).await;
    llm.release.notify_one();
    run.await.unwrap();
    let timeline = state.session_store.timeline("failed-stream", 100).unwrap();
    assert!(!timeline
        .iter()
        .any(|item| item["type"] == "assistant_message"));
    assert!(timeline.iter().any(|item| item["type"] == "error"));
}

#[tokio::test]
async fn dropped_stream_ends_only_its_provisional_text_block() {
    let state = test_state("streaming-cancel");
    seed_plan_conversation(&state, "cancelled-stream");
    let llm = Arc::new(GatedStreamingLlm {
        release: Notify::new(),
        fail: false,
    });
    *state.test_llm_override.lock().unwrap() = Some(llm);
    let mut events = state.events.subscribe();
    let run = tokio::spawn(Arc::clone(&state).run_agent_message(
        "cancelled-stream".into(),
        "local-project".into(),
        "Greet me".into(),
        "cancelled-message".into(),
        None,
        None,
    ));
    let first = next_text_delta(&mut events).await;
    run.abort();
    assert!(run.await.unwrap_err().is_cancelled());
    let end = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let event = events.recv().await.unwrap();
            if event["type"] == "text_end" {
                break event;
            }
        }
    })
    .await
    .expect("dropping the decision must close its text block");
    assert_eq!(end["message_id"], first["message_id"]);
    assert!(end["data"].get("full_text").is_none());
    let timeline = state
        .session_store
        .timeline("cancelled-stream", 100)
        .unwrap();
    assert!(!timeline
        .iter()
        .any(|item| item["type"] == "assistant_message"));
}

#[tokio::test]
async fn anthropic_agent_wrapper_delivers_answer_before_message_stop() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let (release, wait) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut request = [0; 8192];
        socket.read(&mut request).await.unwrap();
        let delta = |fragment: &str| {
            format!(
                "data: {}\n\n",
                json!({
                    "type": "content_block_delta", "delta": {"type": "text_delta", "text": fragment}
                })
            )
        };
        let first = delta(r#"{"kind":"finish","answer":"Hello "#);
        let last = format!(
            "{}data: {{\"type\":\"message_stop\"}}\n\n",
            delta("world\"}")
        );
        let headers = format!(
            "HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ncontent-length: {}\r\n\r\n",
            first.len() + last.len()
        );
        socket.write_all(headers.as_bytes()).await.unwrap();
        socket.write_all(first.as_bytes()).await.unwrap();
        socket.flush().await.unwrap();
        wait.await.unwrap();
        socket.write_all(last.as_bytes()).await.unwrap();
    });
    let llm = AnthropicAgentLlm {
        inner: AnthropicLlm::new(base, "test-model"),
    };
    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
    let decision = tokio::spawn(async move {
        llm.decide_with_tools_stream("hello", 0, &[], &[], &|delta| {
            tx.send(delta.to_owned()).unwrap();
        })
        .await
    });
    let delta = tokio::time::timeout(std::time::Duration::from_secs(5), rx.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(delta, "Hello ");
    assert!(!decision.is_finished());
    release.send(()).unwrap();
    assert!(
        matches!(decision.await.unwrap().unwrap(), AgentAction::Finish { answer } if answer == "Hello world")
    );
    server.await.unwrap();
}
