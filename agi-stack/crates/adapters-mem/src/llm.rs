//! Deterministic, offline LLM stand-ins implementing both halves of
//! [`LlmPort`]: the memory-extraction skill and the ReAct `decide` step. No
//! network, fully reproducible — the spike's robustness/agent tests depend on
//! that determinism.

use async_trait::async_trait;
use agistack_core::agent::types::{AgentAction, Role, TranscriptEntry};
use agistack_core::model::Episode;
use agistack_core::ports::{CoreError, CoreResult, LlmPort, MemoryDraft};

/// A naive but deterministic LLM: extraction takes the first line as a title and
/// long words as tags; `decide` runs a fixed one-tool-then-finish policy so an
/// end-to-end agent loop can be exercised without a real model.
pub struct StubLlm;

#[async_trait]
impl LlmPort for StubLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        let content = episode.content.trim().to_string();
        let title = content
            .lines()
            .next()
            .unwrap_or("Untitled")
            .chars()
            .take(60)
            .collect::<String>();
        let mut tags: Vec<String> = content
            .split_whitespace()
            .filter(|w| w.len() > 5)
            .map(|w| w.to_lowercase())
            .collect();
        tags.sort();
        tags.dedup();
        tags.truncate(5);
        Ok(MemoryDraft {
            title,
            content,
            tags,
            entities: vec![],
        })
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        // Round 0: if any tool is available, call the first one with the goal as
        // input. (Agent First in spirit: a real LLM picks here; this stub is a
        // deterministic placeholder for tests, never a production policy.)
        if round == 0 {
            if let Some(tool) = available_tools.first() {
                return Ok(AgentAction::CallTool {
                    tool: tool.clone(),
                    input_json: serde_json::json!({ "text": goal }).to_string(),
                });
            }
        }
        // Otherwise finish, echoing the most recent observation if we have one.
        let answer = transcript
            .iter()
            .rev()
            .find(|e| e.role == Role::Observation)
            .map(|e| e.content.clone())
            .unwrap_or_else(|| format!("done: {goal}"));
        Ok(AgentAction::Finish { answer })
    }
}

/// An LLM whose `decide` replays a fixed script indexed by round — the tool for
/// driving exact ReAct sequences (including crash-recovery) in tests. Past the
/// end of the script it finishes.
pub struct ScriptedLlm {
    script: Vec<AgentAction>,
}

impl ScriptedLlm {
    pub fn new(script: Vec<AgentAction>) -> Self {
        Self { script }
    }
}

#[async_trait]
impl LlmPort for ScriptedLlm {
    async fn extract_memory(&self, _episode: &Episode) -> CoreResult<MemoryDraft> {
        Err(CoreError::Llm("ScriptedLlm does not extract memory".into()))
    }

    async fn decide(
        &self,
        _goal: &str,
        round: u64,
        _transcript: &[TranscriptEntry],
        _available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        Ok(self
            .script
            .get(round as usize)
            .cloned()
            .unwrap_or(AgentAction::Finish {
                answer: "script exhausted".into(),
            }))
    }
}
