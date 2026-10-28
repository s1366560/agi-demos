//! Provider deadlines apply to every route before metering or failover.

use std::{future::Future, sync::Arc, time::Duration};

use agistack_core::{
    agent::types::{AgentAction, TranscriptEntry},
    model::{Episode, Memory},
    ports::{CoreError, CoreResult, LlmPort, MemoryDraft, RelationshipDraft, ToolDefinition},
};
use async_trait::async_trait;
use serde::{Deserialize, Deserializer};
use serde_json::Value;

pub(super) const DEFAULT_REQUEST_TIMEOUT_MS: u64 = 45_000;
pub(super) const MAX_REQUEST_TIMEOUT_MS: u64 = 300_000;

pub(super) fn deserialize_milliseconds<'de, D>(deserializer: D) -> Result<Option<u64>, D::Error>
where
    D: Deserializer<'de>,
{
    u64::deserialize(deserializer).map(Some)
}

pub(super) fn duration(provider: &Value) -> Result<Duration, &'static str> {
    let milliseconds = match provider.get("request_timeout_ms") {
        None => DEFAULT_REQUEST_TIMEOUT_MS,
        Some(value) => value
            .as_u64()
            .ok_or("request_timeout_ms must be an integer")?,
    };
    if !(1..=MAX_REQUEST_TIMEOUT_MS).contains(&milliseconds) {
        return Err("request_timeout_ms must be between 1 and 300000 milliseconds");
    }
    Ok(Duration::from_millis(milliseconds))
}

pub(super) struct RequestTimedLlm {
    inner: Arc<dyn LlmPort>,
    timeout: Duration,
}

impl RequestTimedLlm {
    pub(super) fn wrap(inner: Arc<dyn LlmPort>, timeout: Duration) -> Arc<dyn LlmPort> {
        Arc::new(Self { inner, timeout })
    }

    async fn request<T>(&self, operation: impl Future<Output = CoreResult<T>>) -> CoreResult<T> {
        tokio::time::timeout(self.timeout, operation)
            .await
            .unwrap_or_else(|_| {
                Err(CoreError::Llm(format!(
                    "model_timeout: LLM request exceeded {} ms",
                    self.timeout.as_millis()
                )))
            })
    }
}

#[async_trait]
impl LlmPort for RequestTimedLlm {
    fn supports_audio_input(&self) -> bool {
        self.inner.supports_audio_input()
    }

    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        self.request(self.inner.extract_memory(episode)).await
    }

    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        self.request(self.inner.extract_relationships(memory)).await
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        self.request(self.inner.decide(goal, round, transcript, available_tools))
            .await
    }

    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        self.request(self.inner.decide_with_tools(goal, round, transcript, tools))
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
        self.request(
            self.inner
                .decide_with_tools_stream(goal, round, transcript, tools, on_text),
        )
        .await
    }
}
