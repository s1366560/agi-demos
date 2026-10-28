use super::*;
use agistack_core::agent::types::MediaAttachment;
use std::sync::Mutex;

struct Model {
    name: &'static str,
    seen: Arc<Mutex<Vec<Vec<TranscriptEntry>>>>,
}
#[async_trait]
impl LlmPort for Model {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!()
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        transcript: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        self.seen.lock().unwrap().push(transcript.to_vec());
        Ok(AgentAction::Finish {
            answer: self.name.into(),
        })
    }
}
fn fixture() -> (VisualInputLlm, Arc<Mutex<Vec<Vec<TranscriptEntry>>>>) {
    let seen = Arc::new(Mutex::new(Vec::new()));
    (
        VisualInputLlm {
            default: Arc::new(Model {
                name: "text",
                seen: seen.clone(),
            }),
            vision: Arc::new(Model {
                name: "vision",
                seen: seen.clone(),
            }),
            audio_authority: None,
        },
        seen,
    )
}
fn attachment(mime: &str) -> MediaAttachment {
    MediaAttachment {
        artifact_path: "/owned/not-read-by-routing".into(),
        mime_type: mime.into(),
    }
}
#[tokio::test]
async fn typed_images_use_vision_and_text_mention_does_not() {
    let (model, _) = fixture();
    let mut transcript = vec![TranscriptEntry::new(
        0,
        Role::Observation,
        "image screenshot base64 file://fake.png",
    )];
    assert!(
        matches!(model.decide("goal",1,&transcript,&[]).await.unwrap(), AgentAction::Finish{answer} if answer=="text")
    );
    transcript[0].media.push(attachment("image/png"));
    assert!(
        matches!(model.decide("goal",1,&transcript,&[]).await.unwrap(), AgentAction::Finish{answer} if answer=="vision")
    );
}
#[tokio::test]
async fn emitted_audio_remains_in_persisted_result_but_never_selects_vision_or_reads_files() {
    let (model, seen) = fixture();
    let transcript = vec![
        TranscriptEntry::new(0, Role::Observation, "recording saved")
            .with_media(vec![attachment("audio/wav")]),
    ];
    for mode in 0..3 {
        let result = match mode {
            0 => model.decide("report", 1, &transcript, &[]).await,
            1 => model.decide_with_tools("report", 1, &transcript, &[]).await,
            _ => {
                model
                    .decide_with_tools_stream("report", 1, &transcript, &[], &|_| {})
                    .await
            }
        }
        .unwrap();
        assert!(matches!(result, AgentAction::Finish{answer} if answer=="text"));
    }
    assert_eq!(transcript[0].media.len(), 1);
    assert_eq!(transcript[0].content, "recording saved");
    for delivered in seen.lock().unwrap().iter() {
        assert!(delivered[0].media.is_empty());
        assert!(delivered[0]
            .content
            .contains("Audio bytes were not sent to this model"));
    }
}
#[tokio::test]
async fn mixed_tool_output_keeps_only_images_on_the_vision_route() {
    let (model, seen) = fixture();
    let transcript = vec![
        TranscriptEntry::new(0, Role::Observation, "screen and recording")
            .with_media(vec![attachment("audio/mpeg"), attachment("image/png")]),
    ];
    assert!(
        matches!(model.decide("report",1,&transcript,&[]).await.unwrap(), AgentAction::Finish{answer} if answer=="vision")
    );
    assert_eq!(
        seen.lock().unwrap()[0][0].media,
        vec![attachment("image/png")]
    );
    assert_eq!(transcript[0].media.len(), 2);
}
#[tokio::test]
async fn explicit_human_audio_without_native_authority_is_not_silently_dropped() {
    let (model, seen) = fixture();
    let transcript = vec![TranscriptEntry::new(0, Role::Human, "listen to this")
        .with_media(vec![attachment("audio/wav")])];
    assert!(model
        .decide("listen", 1, &transcript, &[])
        .await
        .unwrap_err()
        .to_string()
        .contains("audio_input_authority_required"));
    assert!(seen.lock().unwrap().is_empty());
}
