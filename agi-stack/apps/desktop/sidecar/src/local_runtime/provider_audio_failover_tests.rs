use super::*;

struct Candidate {
    audio: bool,
    fail: bool,
    calls: std::sync::atomic::AtomicUsize,
}

#[async_trait]
impl LlmPort for Candidate {
    fn supports_audio_input(&self) -> bool {
        self.audio
    }
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        Err(CoreError::Llm("unused fixture operation".into()))
    }
    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        _: &[agistack_core::ports::ToolDefinition],
    ) -> CoreResult<AgentAction> {
        self.decide(goal, round, transcript, &[]).await
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        transcript: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let audio = transcript
            .iter()
            .flat_map(|entry| &entry.media)
            .filter(|media| media.mime_type.starts_with("audio/"))
            .count();
        if audio > 0 && !self.audio {
            return Err(CoreError::Llm("audio_input_unsupported".into()));
        }
        if self.fail {
            return Err(CoreError::Llm(
                "provider_http_error: AudioTooLarge: limit 25000000 bytes".into(),
            ));
        }
        assert_eq!(audio, usize::from(self.audio));
        Ok(AgentAction::Finish {
            answer: "owned audio retained".into(),
        })
    }
}

#[tokio::test]
async fn audio_failover_skips_undeclared_models_and_preserves_remote_error_or_audio() {
    for mode in ["plain", "tools", "stream"] {
        for supported_fallback in [false, true] {
            let failing = Arc::new(Candidate {
                audio: true,
                fail: true,
                calls: Default::default(),
            });
            let text = Arc::new(Candidate {
                audio: false,
                fail: false,
                calls: Default::default(),
            });
            let audio = Arc::new(Candidate {
                audio: true,
                fail: false,
                calls: Default::default(),
            });
            let mut candidates: Vec<Arc<dyn LlmPort>> = vec![failing.clone(), text.clone()];
            if supported_fallback {
                candidates.push(audio.clone());
            }
            let model = FailoverLlm::from_candidates(candidates);
            let transcript = [
                TranscriptEntry::new(0, Role::Observation, "owned recording").with_media(vec![
                    agistack_core::agent::types::MediaAttachment {
                        artifact_path: "/owned/fixture.wav".into(),
                        mime_type: "audio/wav".into(),
                    },
                ]),
            ];
            let result = match mode {
                "tools" => model.decide_with_tools("listen", 1, &transcript, &[]).await,
                "stream" => {
                    model
                        .decide_with_tools_stream("listen", 1, &transcript, &[], &|_| {})
                        .await
                }
                _ => model.decide("listen", 1, &transcript, &[]).await,
            };
            if supported_fallback {
                assert!(matches!(result, Ok(AgentAction::Finish { .. })));
            } else {
                assert!(result.unwrap_err().to_string().contains("AudioTooLarge"));
            }
            assert_eq!(failing.calls.load(Ordering::SeqCst), 1);
            assert_eq!(
                text.calls.load(Ordering::SeqCst),
                0,
                "an undeclared fallback cannot replace or strip audio"
            );
            assert_eq!(
                audio.calls.load(Ordering::SeqCst),
                usize::from(supported_fallback)
            );
        }
    }
}

#[tokio::test]
async fn text_failover_remains_available_and_undeclared_audio_fails_closed() {
    let failing = Arc::new(Candidate {
        audio: false,
        fail: true,
        calls: Default::default(),
    });
    let text = Arc::new(Candidate {
        audio: false,
        fail: false,
        calls: Default::default(),
    });
    let model = FailoverLlm::from_candidates(vec![failing.clone(), text.clone()]);
    assert!(matches!(
        model.decide("text only", 1, &[], &[]).await,
        Ok(AgentAction::Finish { .. })
    ));
    assert_eq!(failing.calls.load(Ordering::SeqCst), 1);
    assert_eq!(text.calls.load(Ordering::SeqCst), 1);
    let audio = [
        TranscriptEntry::new(0, Role::Human, "owned recording").with_media(vec![
            agistack_core::agent::types::MediaAttachment {
                artifact_path: "/owned/fixture.wav".into(),
                mime_type: "audio/wav".into(),
            },
        ]),
    ];
    let error = model
        .decide_with_tools_stream("listen", 1, &audio, &[], &|_| {})
        .await
        .unwrap_err();
    assert!(error.to_string().contains("audio_input_unsupported"));
    assert_eq!(failing.calls.load(Ordering::SeqCst), 1);
    assert_eq!(text.calls.load(Ordering::SeqCst), 1);
}
