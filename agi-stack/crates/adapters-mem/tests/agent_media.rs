use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm, StubLlm};
use agistack_core::agent::tool_policy::{
    ToolExecutionPolicy, ToolPolicyContext, ToolPolicyDecision, ToolPolicyResult,
};
use agistack_core::agent::types::{CompletedCall, MediaAttachment, Role, TranscriptEntry};
use agistack_core::model::Episode;
use agistack_core::ports::{
    CheckpointStore, CoreError, CoreResult, LlmPort, MemoryDraft, ToolHost, ToolResult,
};
use agistack_core::{AgentAction, ReActEngine, SessionState};
use async_trait::async_trait;
use futures::executor::block_on;

fn screenshot() -> MediaAttachment {
    MediaAttachment {
        artifact_path: "/trusted/artifacts/screen.png".into(),
        mime_type: "image/png".into(),
    }
}

struct VisualLlm;
#[async_trait]
impl LlmPort for VisualLlm {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!()
    }
    async fn decide(
        &self,
        _: &str,
        round: u64,
        entries: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        if round == 0 {
            return Ok(AgentAction::CallTool {
                tool: "observe".into(),
                input_json: "{}".into(),
            });
        }
        let observation = entries
            .iter()
            .find(|entry| entry.role == Role::Observation)
            .unwrap();
        assert_eq!(observation.media, vec![screenshot()]);
        assert_eq!(observation.content, "screen text");
        Ok(AgentAction::Finish {
            answer: "image received".into(),
        })
    }
    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        entries: &[TranscriptEntry],
        _: &[agistack_core::ports::ToolDefinition],
    ) -> CoreResult<AgentAction> {
        self.decide(goal, round, entries, &[]).await
    }
}

struct VisualHost(AtomicUsize);
#[async_trait]
impl ToolHost for VisualHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["observe".into()]
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        panic!("structured host result must be used")
    }
    async fn call_with_content(&self, _: &str, _: &str) -> CoreResult<ToolResult> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok(ToolResult {
            control_outcome: None,
            control_generation: None,
            permission_required: None,
            output_json: "screen text".into(),
            media: vec![screenshot()],
        })
    }
}

#[test]
fn image_observation_reaches_model_and_survives_checkpoint_recovery() {
    for resume in [false, true] {
        let host = Arc::new(VisualHost(AtomicUsize::new(0)));
        let checkpoints = Arc::new(InMemoryCheckpointStore::new());
        if resume {
            let mut state = SessionState::new("media", "inspect", Some("p1"));
            state.completed_tool_calls.push(CompletedCall {
                control_outcome: None,
                control_generation: None,
                round: 0,
                tool: "observe".into(),
                input_json: "{}".into(),
                output_json: "screen text".into(),
                media: vec![screenshot()],
                metadata: serde_json::json!({}),
                failed: false,
            });
            block_on(checkpoints.save(&state)).unwrap();
        }
        let engine = ReActEngine::new(
            Arc::new(VisualLlm),
            host.clone(),
            checkpoints.clone(),
            Arc::new(FixedClock(0)),
        );
        let state = block_on(engine.run("media", "inspect", Some("p1"))).unwrap();
        assert_eq!(host.0.load(Ordering::SeqCst), usize::from(!resume));
        assert_eq!(state.completed_tool_calls[0].media, vec![screenshot()]);
        let saved = block_on(checkpoints.load("media")).unwrap().unwrap();
        assert_eq!(
            saved
                .transcript
                .iter()
                .find(|entry| entry.role == Role::Observation)
                .unwrap()
                .media,
            vec![screenshot()]
        );
    }
}

#[test]
fn old_transcripts_and_completed_calls_decode_without_media() {
    let entry: TranscriptEntry =
        serde_json::from_str(r#"{"round":0,"role":"observation","content":"old text"}"#).unwrap();
    assert!(entry.media.is_empty());
    let call: CompletedCall = serde_json::from_str(
        r#"{"round":0,"tool":"read","input_json":"{}","output_json":"old text"}"#,
    )
    .unwrap();
    assert!(call.media.is_empty());
    assert!(serde_json::to_value(entry).unwrap().get("media").is_none());
}

#[test]
fn text_only_model_adapter_reports_unsupported_media_instead_of_dropping_it() {
    let transcript =
        vec![TranscriptEntry::new(0, Role::Observation, "screen").with_media(vec![screenshot()])];
    let error = block_on(StubLlm.decide_with_tools("inspect", 1, &transcript, &[])).unwrap_err();
    assert!(error.to_string().contains("vision_unsupported"));
}

struct WithholdingPolicy;
#[async_trait]
impl ToolExecutionPolicy for WithholdingPolicy {
    async fn before_execute(
        &self,
        _: &ToolPolicyContext<'_>,
        input: &str,
        _: Option<&serde_json::Value>,
    ) -> CoreResult<ToolPolicyDecision> {
        Ok(ToolPolicyDecision::Allow {
            input_json: input.into(),
        })
    }
    async fn execute_with_content(
        &self,
        context: &ToolPolicyContext<'_>,
        tools: &dyn ToolHost,
        input: &str,
    ) -> CoreResult<ToolResult> {
        tools.call_with_content(context.tool, input).await
    }
    async fn transform_result(
        &self,
        _: &ToolPolicyContext<'_>,
        result: ToolPolicyResult,
    ) -> CoreResult<ToolPolicyResult> {
        assert_eq!(result.media, vec![screenshot()]);
        Err(CoreError::Tool("policy rejected result".into()))
    }
}

#[test]
fn failed_result_policy_withholds_image_attachments_from_model_and_checkpoint() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::CallTool {
            tool: "observe".into(),
            input_json: "{}".into(),
        }])),
        Arc::new(VisualHost(AtomicUsize::new(0))),
        checkpoints,
        Arc::new(FixedClock(0)),
    )
    .with_tool_policy(Arc::new(WithholdingPolicy));
    let state = block_on(engine.run("withheld", "inspect", Some("p1"))).unwrap();
    assert!(state.completed_tool_calls[0].failed);
    assert!(state.completed_tool_calls[0].media.is_empty());
    assert!(state.transcript.iter().all(|entry| entry.media.is_empty()));
}
