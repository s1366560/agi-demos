//! Contract test: model-visible => logged (I2 invariant, Rust half).
//!
//! The engine's semantic decision port (`LlmPort::decide`) receives the
//! session transcript by construction; this test records every transcript
//! snapshot the model actually observed and asserts each observed entry is
//! present in the durable session log (final state + checkpoint), so no
//! ephemeral, unlogged content can reach the model.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use futures::executor::block_on;

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore};
use agistack_core::model::Episode;
use agistack_core::ports::{
    CheckpointStore, CoreError, CoreResult, LlmPort, MemoryDraft, ToolHost,
};
use agistack_core::{AgentAction, ReActEngine, Role, SessionStatus, TranscriptEntry};

/// Records the exact transcript the model saw at every decision round.
struct RecordingLlm {
    script: Vec<AgentAction>,
    seen: Mutex<Vec<Vec<TranscriptEntry>>>,
}

#[async_trait]
impl LlmPort for RecordingLlm {
    async fn extract_memory(&self, _episode: &Episode) -> CoreResult<MemoryDraft> {
        Err(CoreError::Llm("RecordingLlm does not extract memory".into()))
    }

    async fn decide(
        &self,
        _goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        _available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        self.seen
            .lock()
            .expect("seen lock")
            .push(transcript.to_vec());
        Ok(self
            .script
            .get(round as usize)
            .cloned()
            .unwrap_or(AgentAction::Finish {
                answer: "script exhausted".into(),
            }))
    }
}

struct EchoToolHost;

#[async_trait]
impl ToolHost for EchoToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["work".into()]
    }
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        Ok(serde_json::json!({ "tool": tool, "echo": input_json }).to_string())
    }
}

fn transcript_contains(log: &[TranscriptEntry], entry: &TranscriptEntry) -> bool {
    log.iter().any(|e| {
        e.round == entry.round && e.role == entry.role && e.content == entry.content
    })
}

#[test]
fn every_model_visible_entry_is_in_the_session_log() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let llm = Arc::new(RecordingLlm {
        script: vec![
            AgentAction::CallTool {
                tool: "work".into(),
                input_json: r#"{"text":"deploy"}"#.into(),
            },
            AgentAction::Finish {
                answer: "deployed".into(),
            },
        ],
        seen: Mutex::new(Vec::new()),
    });
    let engine = ReActEngine::new(
        llm.clone(),
        Arc::new(EchoToolHost),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    let done = block_on(engine.run("s-visible", "deploy the app", Some("p1"))).unwrap();
    assert_eq!(done.status, SessionStatus::Finished);

    let seen = llm.seen.lock().expect("seen lock");
    assert!(seen.len() >= 2, "model decided at least twice: {:?}", seen.len());
    // Round 1 must have observed round 0's tool activity (the observation entry).
    let round_one = &seen[1];
    assert!(
        round_one.iter().any(|e| e.role == Role::Observation),
        "model saw the tool observation: {round_one:?}"
    );

    // Invariant: everything the model saw is in the durable session log.
    for snapshot in seen.iter() {
        for entry in snapshot {
            assert!(
                transcript_contains(&done.transcript, entry),
                "model-visible entry missing from session log: {entry:?}"
            );
        }
    }

    // And it is durable: the checkpoint carries the same log.
    let saved = block_on(checkpoints.load("s-visible")).unwrap().unwrap();
    for snapshot in seen.iter() {
        for entry in snapshot {
            assert!(
                transcript_contains(&saved.transcript, entry),
                "model-visible entry missing from checkpoint log: {entry:?}"
            );
        }
    }
}
