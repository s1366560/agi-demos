use super::*;
use agistack_core::ports::ToolControlOutcome;
use std::{sync::atomic::AtomicBool, time::Duration};
use tokio::sync::Notify;

struct UpstreamDrop(Arc<AtomicBool>);
impl Drop for UpstreamDrop {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}
struct PendingModel {
    entered: Arc<Notify>,
    dropped: Arc<AtomicBool>,
}
#[async_trait]
impl LlmPort for PendingModel {
    fn supports_audio_input(&self) -> bool {
        true
    }
    async fn extract_memory(
        &self,
        _: &agistack_core::model::Episode,
    ) -> CoreResult<agistack_core::ports::MemoryDraft> {
        unreachable!()
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        let _guard = UpstreamDrop(self.dropped.clone());
        self.entered.notify_one();
        std::future::pending().await
    }
    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        _: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        self.decide(goal, round, transcript, &[]).await
    }
    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        _: &[ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        on_text("provisional audio answer");
        self.decide(goal, round, transcript, &[]).await
    }
}

async fn control(
    broker: &Broker,
    receive: &mut mpsc::Receiver<Value>,
    outcome: ToolControlOutcome,
) -> (String, Option<String>) {
    let call = dispatch(broker, 2, "computer_get_app_state", "{}");
    let wire = receive.recv().await.unwrap();
    let id = wire["request_id"].as_str().unwrap().to_owned();
    broker.claim(&id, "user", "device").unwrap();
    let generation =
        (outcome == ToolControlOutcome::UserPaused).then(|| uuid::Uuid::new_v4().to_string());
    let result = outcome.result(generation.clone());
    broker
        .receive_control_result(
            "connection",
            &id,
            result.output_json,
            false,
            vec![],
            Some(outcome),
            generation.clone(),
        )
        .unwrap();
    call.await.unwrap().unwrap();
    (id, generation)
}

#[tokio::test]
async fn waiting_audio_requests_cancel_upstream_on_run_cancel_pause_stop_disconnect_and_revocation()
{
    for operation in 0..3 {
        for change in [
            "run_cancel",
            "pause",
            "stop",
            "disconnect",
            "revoked",
            "not_running",
        ] {
            let (broker, authority, mut receive) = fixture();
            let result = recording(&broker, &mut receive).await;
            let transcript = vec![
                TranscriptEntry::new(1, Role::Observation, "recorded").with_media(result.media)
            ];
            let entered = Arc::new(Notify::new());
            let dropped = Arc::new(AtomicBool::new(false));
            let model = scoped(
                &broker,
                Arc::new(PendingModel {
                    entered: entered.clone(),
                    dropped: dropped.clone(),
                }),
                "conversation",
                "engine-session",
                run(),
            );
            let delivered = Arc::new(Mutex::new(String::new()));
            let text = delivered.clone();
            let pending = tokio::spawn(async move {
                let capture = |chunk: &str| text.lock().unwrap().push_str(chunk);
                match operation {
                    0 => model.decide("listen", 2, &transcript, &[]).await,
                    1 => model.decide_with_tools("listen", 2, &transcript, &[]).await,
                    _ => {
                        model
                            .decide_with_tools_stream("listen", 2, &transcript, &[], &capture)
                            .await
                    }
                }
            });
            tokio::time::timeout(Duration::from_secs(2), entered.notified())
                .await
                .unwrap();
            // Cross the initial interval tick before revoking an already waiting request.
            tokio::time::sleep(Duration::from_millis(25)).await;
            match change {
                "run_cancel" => broker.cancel_run(&owner(), &run().run_id),
                "pause" => {
                    control(&broker, &mut receive, ToolControlOutcome::UserPaused).await;
                }
                "stop" => {
                    control(&broker, &mut receive, ToolControlOutcome::UserStopped).await;
                }
                "disconnect" => broker.disconnect("connection"),
                "revoked" => authority.current.store(false, Ordering::SeqCst),
                "not_running" => authority.running.store(false, Ordering::SeqCst),
                _ => unreachable!(),
            }
            let result = tokio::time::timeout(Duration::from_secs(2), pending)
                .await
                .unwrap()
                .unwrap();
            assert!(result.is_err(), "{operation}: {change}");
            assert!(
                dropped.load(Ordering::SeqCst),
                "upstream is cancelled for {operation}: {change}"
            );
            assert!(delivered.lock().unwrap().is_empty());
            cleanup(&broker);
        }
    }
}

struct PendingBody {
    first: bool,
    entered: Arc<Notify>,
    dropped: Arc<Notify>,
}
impl futures_util::Stream for PendingBody {
    type Item = Result<axum::body::Bytes, std::convert::Infallible>;
    fn poll_next(
        mut self: std::pin::Pin<&mut Self>,
        _: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Option<Self::Item>> {
        if self.first {
            self.first = false;
            self.entered.notify_one();
            std::task::Poll::Ready(Some(Ok(axum::body::Bytes::from_static(b": waiting\n\n"))))
        } else {
            std::task::Poll::Pending
        }
    }
}
impl Drop for PendingBody {
    fn drop(&mut self) {
        self.dropped.notify_one();
    }
}

#[tokio::test]
async fn revoking_audio_during_real_http_sse_wait_closes_upstream_body() {
    let (broker, authority, mut receive) = fixture();
    let result = recording(&broker, &mut receive).await;
    let entered = Arc::new(Notify::new());
    let dropped = Arc::new(Notify::new());
    let seen = entered.clone();
    let closed = dropped.clone();
    let router = Router::new().route(
        "/chat/completions",
        post(move |Json(body): Json<Value>| {
            let seen = seen.clone();
            let closed = closed.clone();
            async move {
                assert!(body.to_string().contains("input_audio"));
                axum::http::Response::builder()
                    .header("content-type", "text/event-stream")
                    .body(axum::body::Body::from_stream(PendingBody {
                        first: true,
                        entered: seen,
                        dropped: closed,
                    }))
                    .unwrap()
            }
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    let model = scoped(
        &broker,
        Arc::new(
            agistack_adapters_http_llm::HttpLlm::new(format!("http://{address}"), "declared")
                .with_audio_input_support(true),
        ),
        "conversation",
        "engine-session",
        run(),
    );
    let pending = tokio::spawn(async move {
        let transcript =
            vec![TranscriptEntry::new(1, Role::Observation, "recorded").with_media(result.media)];
        model
            .decide_with_tools_stream("listen", 2, &transcript, &[], &|_| {
                panic!("revoked audio cannot emit text")
            })
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), entered.notified())
        .await
        .unwrap();
    tokio::time::sleep(Duration::from_millis(25)).await;
    authority.current.store(false, Ordering::SeqCst);
    assert!(tokio::time::timeout(Duration::from_secs(2), pending)
        .await
        .unwrap()
        .unwrap()
        .is_err());
    tokio::time::timeout(Duration::from_secs(2), dropped.notified())
        .await
        .expect("HTTP response body must be cancelled");
    server.abort();
    cleanup(&broker);
}

#[tokio::test]
async fn audio_resume_requires_matching_native_generation_and_stop_stays_revoked() {
    let (broker, _, mut receive) = fixture();
    let result = recording(&broker, &mut receive).await;
    let scope = audio_input::Scope {
        broker: broker.clone(),
        owner: owner(),
        conversation: "conversation".into(),
        session: "engine-session".into(),
        run: run(),
    };
    let (id, generation) = control(&broker, &mut receive, ToolControlOutcome::UserPaused).await;
    assert!(scope.validate(&result.media[0]).await.is_err());
    let frame = |generation: String, state: &str| super::super::super::control::Frame {
        request_id: id.clone(),
        session_id: "engine-session".into(),
        control_generation: generation,
        state: state.into(),
    };
    assert!(broker
        .receive_control_state(
            "connection",
            frame(uuid::Uuid::new_v4().to_string(), "resumed")
        )
        .await
        .is_err());
    assert!(scope.validate(&result.media[0]).await.is_err());
    let generation = generation.unwrap();
    broker
        .receive_control_state("connection", frame(generation.clone(), "resumed"))
        .await
        .unwrap();
    scope.validate(&result.media[0]).await.unwrap();
    broker
        .receive_control_state("connection", frame(generation.clone(), "stopped"))
        .await
        .unwrap();
    assert!(scope.validate(&result.media[0]).await.is_err());
    broker
        .receive_control_state("connection", frame(generation, "resumed"))
        .await
        .unwrap();
    assert!(scope.validate(&result.media[0]).await.is_err());
    cleanup(&broker);
}
