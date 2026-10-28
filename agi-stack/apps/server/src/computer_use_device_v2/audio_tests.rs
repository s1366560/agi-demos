use super::*;
use agistack_core::agent::types::{AgentAction, MediaAttachment};
use std::sync::atomic::Ordering;
#[path = "audio_guard_tests.rs"]
mod guard_tests;

fn wav() -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"RIFF");
    bytes.extend_from_slice(&40u32.to_le_bytes());
    bytes.extend_from_slice(b"WAVEfmt ");
    bytes.extend_from_slice(&16u32.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&24_000u32.to_le_bytes());
    bytes.extend_from_slice(&48_000u32.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&16u16.to_le_bytes());
    bytes.extend_from_slice(b"data");
    bytes.extend_from_slice(&4u32.to_le_bytes());
    bytes.extend_from_slice(&[0; 4]);
    bytes
}

async fn recording(broker: &Broker, receive: &mut mpsc::Receiver<Value>) -> ToolResult {
    let call = dispatch(broker, 1, "computer_get_app_state", "{}");
    let control = receive.recv().await.unwrap();
    let id = control["request_id"].as_str().unwrap();
    broker.claim(id, "user", "device").unwrap();
    let bytes = wav();
    broker
        .receive_result(
            "connection",
            id,
            json!({"recording":{"artifact_id":"audio","mime_type":"audio/wav"}}).to_string(),
            false,
            vec![broker::Descriptor {
                artifact_id: "audio".into(),
                mime_type: "audio/wav".into(),
                size_bytes: bytes.len() as u64,
            }],
        )
        .unwrap();
    assert!(broker
        .receive_media(
            "connection",
            id,
            "audio",
            "audio/wav",
            0,
            &STANDARD.encode(bytes),
            true
        )
        .unwrap());
    broker.complete(id).await.unwrap();
    call.await.unwrap().unwrap()
}

fn scoped(
    broker: &Broker,
    model: Arc<dyn LlmPort>,
    conversation: &str,
    session: &str,
    authority: authority::RunAuthority,
) -> audio_input::AudioInputLlm {
    audio_input::AudioInputLlm::new(
        model,
        Some(audio_input::Scope {
            broker: broker.clone(),
            owner: owner(),
            conversation: conversation.into(),
            session: session.into(),
            run: authority,
        }),
    )
}

fn cleanup(broker: &Broker) {
    if let Some(root) = broker.cache.lock().unwrap().take() {
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[tokio::test]
async fn owned_recording_reaches_real_http_only_for_explicit_exact_model_declaration() {
    let (broker, _, mut receive) = fixture();
    let result = recording(&broker, &mut receive).await;
    assert_eq!(result.media.len(), 1);
    assert_eq!(
        std::fs::read(&result.media[0].artifact_path).unwrap(),
        wav()
    );
    assert!(!result.output_json.contains("artifact_path"));
    let transcript = vec![
        TranscriptEntry::new(1, Role::Observation, result.output_json.clone())
            .with_media(result.media.clone()),
    ];
    let captured = Arc::new(Mutex::new(Vec::<Value>::new()));
    let capture = captured.clone();
    let router = Router::new().route("/chat/completions", post(move |Json(body): Json<Value>| {
        let capture = capture.clone();
        async move {
            capture.lock().unwrap().push(body);
            Json(json!({"choices":[{"message":{"content":"{\"kind\":\"finish\",\"answer\":\"heard\"}"}}]}))
        }
    }));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    let declared = crate::provider_audio_declaration::parse(Some(r#"["explicit-audio"]"#)).unwrap();
    for (model_id, supported) in [
        ("gpt-4o-audio-preview", false),
        ("explicit-audio-other", false),
        ("explicit-audio", true),
    ] {
        let model = agistack_adapters_http_llm::HttpLlm::new(format!("http://{address}"), model_id)
            .with_audio_input_support(declared.contains(model_id));
        scoped(
            &broker,
            Arc::new(model),
            "conversation",
            "engine-session",
            run(),
        )
        .decide_with_tools("listen", 2, &transcript, &[])
        .await
        .unwrap();
        let request = captured.lock().unwrap().last().unwrap().clone();
        let serialized = request.to_string();
        assert_eq!(serialized.contains("input_audio"), supported);
        if supported {
            assert!(serialized.contains(&STANDARD.encode(wav())));
        } else {
            assert!(serialized.contains("audio_input_unsupported"));
            assert!(!serialized.contains(&STANDARD.encode(wav())));
        }
        assert!(!serialized.contains(&result.media[0].artifact_path));
    }
    assert_eq!(transcript[0].media.len(), 1, "UI transcript stays intact");
    server.abort();
    cleanup(&broker);
}

#[tokio::test]
async fn audio_authority_binds_owner_conversation_engine_session_run_and_actual_artifact() {
    let (broker, authority, mut receive) = fixture();
    let result = recording(&broker, &mut receive).await;
    let scope = audio_input::Scope {
        broker: broker.clone(),
        owner: owner(),
        conversation: "conversation".into(),
        session: "engine-session".into(),
        run: run(),
    };
    let attachment = result.media[0].clone();
    scope.validate(&attachment).await.unwrap();
    let mut foreign = scope.clone();
    foreign.owner.user_id = "other-user".into();
    assert!(foreign.validate(&attachment).await.is_err());
    foreign = scope.clone();
    foreign.owner.tenant_id = "other-tenant".into();
    assert!(foreign.validate(&attachment).await.is_err());
    foreign = scope.clone();
    foreign.owner.project_id = "other-project".into();
    assert!(foreign.validate(&attachment).await.is_err());
    foreign = scope.clone();
    foreign.conversation = "other-conversation".into();
    assert!(foreign.validate(&attachment).await.is_err());
    foreign = scope.clone();
    foreign.session = "child-session".into();
    assert!(foreign.validate(&attachment).await.is_err());
    foreign = scope.clone();
    foreign.run.authorization_revision += 1;
    assert!(foreign.validate(&attachment).await.is_err());
    let mut forged = attachment.clone();
    forged.mime_type = "audio/mp3".into();
    assert!(scope.validate(&forged).await.is_err());
    forged = attachment.clone();
    forged.artifact_path.push_str(".other");
    assert!(scope.validate(&forged).await.is_err());
    authority.running.store(false, Ordering::SeqCst);
    assert!(scope.validate(&attachment).await.is_err());
    authority.running.store(true, Ordering::SeqCst);
    authority.current.store(false, Ordering::SeqCst);
    assert!(scope.validate(&attachment).await.is_err());
    authority.current.store(true, Ordering::SeqCst);
    let mut changed = wav();
    changed[47] = 1;
    std::fs::write(&attachment.artifact_path, changed).unwrap();
    assert!(scope.validate(&attachment).await.is_err());
    std::fs::write(&attachment.artifact_path, wav()).unwrap();
    scope.validate(&attachment).await.unwrap();
    #[cfg(unix)]
    {
        let path = std::path::Path::new(&attachment.artifact_path);
        let target = path.with_extension("original");
        std::fs::rename(path, &target).unwrap();
        std::os::unix::fs::symlink(&target, path).unwrap();
        assert!(scope.validate(&attachment).await.is_err());
        std::fs::remove_file(path).unwrap();
        std::fs::rename(target, path).unwrap();
    }
    broker.disconnect("connection");
    assert!(scope.validate(&attachment).await.is_err());
    cleanup(&broker);
}

struct RecordingModel {
    seen: Arc<Mutex<Vec<TranscriptEntry>>>,
    revoke: Option<Arc<Authority>>,
}
#[async_trait]
impl LlmPort for RecordingModel {
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
        transcript: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        *self.seen.lock().unwrap() = transcript.to_vec();
        if let Some(authority) = &self.revoke {
            authority.current.store(false, Ordering::SeqCst);
        }
        Ok(AgentAction::Finish {
            answer: "heard".into(),
        })
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
        on_text("provisional");
        self.decide(goal, round, transcript, &[]).await
    }
}

#[tokio::test]
async fn unauthorized_observation_is_explicitly_omitted_but_human_audio_is_rejected() {
    let seen = Arc::new(Mutex::new(vec![]));
    let model = audio_input::AudioInputLlm::new(
        Arc::new(RecordingModel {
            seen: seen.clone(),
            revoke: None,
        }),
        None,
    );
    let audio = MediaAttachment {
        artifact_path: "/not-owned/audio.wav".into(),
        mime_type: "audio/wav".into(),
    };
    let transcript = vec![
        TranscriptEntry::new(1, Role::Observation, "recorded").with_media(vec![audio.clone()])
    ];
    model.decide("listen", 2, &transcript, &[]).await.unwrap();
    assert!(seen.lock().unwrap()[0].media.is_empty());
    assert!(seen.lock().unwrap()[0]
        .content
        .contains("audio_input_authority_unavailable"));
    assert_eq!(transcript[0].media.len(), 1);
    let human = vec![TranscriptEntry::new(1, Role::Human, "listen").with_media(vec![audio])];
    assert!(model.decide("listen", 2, &human, &[]).await.is_err());
}

#[tokio::test]
async fn revocation_during_each_model_operation_discards_result_and_streamed_text() {
    let (broker, authority, mut receive) = fixture();
    let result = recording(&broker, &mut receive).await;
    let transcript =
        vec![TranscriptEntry::new(1, Role::Observation, "recorded").with_media(result.media)];
    for operation in 0..3 {
        authority.current.store(true, Ordering::SeqCst);
        let model = scoped(
            &broker,
            Arc::new(RecordingModel {
                seen: Arc::new(Mutex::new(vec![])),
                revoke: Some(authority.clone()),
            }),
            "conversation",
            "engine-session",
            run(),
        );
        let text = Mutex::new(String::new());
        let capture = |chunk: &str| text.lock().unwrap().push_str(chunk);
        let result = match operation {
            0 => model.decide("listen", 2, &transcript, &[]).await,
            1 => model.decide_with_tools("listen", 2, &transcript, &[]).await,
            _ => {
                model
                    .decide_with_tools_stream("listen", 2, &transcript, &[], &capture)
                    .await
            }
        };
        assert!(result.is_err());
        assert!(text.lock().unwrap().is_empty());
    }
    cleanup(&broker);
}
