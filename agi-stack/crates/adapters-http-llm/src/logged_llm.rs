//! Model operation decorator; transport adapters persist each actual attempt.

use std::sync::Arc;

use agistack_core::{
    agent::types::{AgentAction, TranscriptEntry},
    model::{Episode, Memory},
    model_request::ModelRequestLog,
    ports::{CoreResult, LlmPort, MemoryDraft, RelationshipDraft, ToolDefinition},
};
use async_trait::async_trait;

use crate::with_model_request_log;

pub struct RequestLoggedLlm {
    inner: Arc<dyn LlmPort>,
    log: Arc<dyn ModelRequestLog>,
}

impl RequestLoggedLlm {
    pub fn new(inner: Arc<dyn LlmPort>, log: Arc<dyn ModelRequestLog>) -> Self {
        Self { inner, log }
    }
}

#[async_trait]
impl LlmPort for RequestLoggedLlm {
    fn supports_audio_input(&self) -> bool {
        self.inner.supports_audio_input()
    }

    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        with_model_request_log(self.log.clone(), self.inner.extract_memory(episode)).await
    }

    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        with_model_request_log(self.log.clone(), self.inner.extract_relationships(memory)).await
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[String],
    ) -> CoreResult<AgentAction> {
        with_model_request_log(
            self.log.clone(),
            self.inner.decide(goal, round, transcript, tools),
        )
        .await
    }

    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        with_model_request_log(
            self.log.clone(),
            self.inner.decide_with_tools(goal, round, transcript, tools),
        )
        .await
    }

    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        with_model_request_log(
            self.log.clone(),
            self.inner
                .decide_with_tools_stream(goal, round, transcript, tools, on_text),
        )
        .await
    }
}
