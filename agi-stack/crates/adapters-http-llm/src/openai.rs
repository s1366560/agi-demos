use async_trait::async_trait;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::json;

use agistack_core::agent::types::{AgentAction, Role, TranscriptEntry};
use agistack_core::model::{Episode, Memory};
use agistack_core::ports::{CoreError, CoreResult, LlmPort, MemoryDraft, RelationshipDraft};

use crate::endpoint::Endpoint;
use crate::structured::{clean_structured, parse_memory_draft, parse_relationship_drafts};

#[derive(Serialize)]
struct ChatMessage {
    role: &'static str,
    content: String,
}

#[derive(Serialize)]
struct ChatRequest {
    model: String,
    messages: Vec<ChatMessage>,
    temperature: f32,
    #[serde(skip_serializing_if = "Option::is_none")]
    stream: Option<bool>,
}

#[derive(Deserialize)]
struct ChatResponse {
    choices: Vec<ChatChoice>,
}

#[derive(Deserialize)]
struct ChatChoice {
    message: ChatResponseMessage,
}

#[derive(Deserialize)]
struct ChatResponseMessage {
    content: String,
}

#[derive(Deserialize)]
struct ChatStreamChunk {
    #[serde(default)]
    choices: Vec<ChatStreamChoice>,
}

#[derive(Deserialize)]
struct ChatStreamChoice {
    #[serde(default)]
    delta: ChatStreamDelta,
}

#[derive(Default, Deserialize)]
struct ChatStreamDelta {
    #[serde(default)]
    content: Option<String>,
}

const EXTRACT_SYSTEM: &str = "You distill an episode into a memory. Respond with ONLY a JSON object: \
{\"title\": string, \"content\": string, \"tags\": string[], \"entities\": [{\"name\": string, \"kind\": string}]}. \
No prose, no code fences.";

const DECIDE_SYSTEM: &str = "You are a ReAct agent. Choose the next action and respond with ONLY a JSON object, one of: \
{\"kind\":\"call_tool\",\"tool\":string,\"input_json\":string} | \
{\"kind\":\"finish\",\"answer\":string} | \
{\"kind\":\"request_human\",\"request\":{\"id\":string,\"kind\":\"clarification\"|\"decision\"|\"env_var\"|\"permission\",\"prompt\":string,\"decision\":{\"action\":{\"name\":string,\"label\":string},\"target\":{\"kind\":string,\"id\":string,\"version_id\":string|null,\"path\":string|null},\"data\":{\"summary\":string,\"redacted_fields\":string[]},\"reason\":string,\"risk\":{\"level\":\"low\"|\"medium\"|\"high\",\"rationale\":string},\"reversibility\":{\"mode\":\"reversible\"|\"partial\"|\"irreversible\",\"recovery\":string|null},\"scope\":{\"kind\":string,\"ids\":string[]},\"evidence\":[{\"kind\":string,\"id\":string,\"label\":string,\"uri\":string|null,\"digest\":string|null}]}}}. \
decision is required and must be complete for decision or permission; omit it for clarification or env_var. \
Risk, rationale, reversibility, scope, and evidence are your structured judgment and must not be delegated to prompt parsing. \
Redact secrets from data.summary and name them in redacted_fields. input_json must be a JSON string. No prose, no code fences.";

const RELATIONSHIP_SYSTEM: &str = "You extract semantic relationships between the provided entities. \
Respond with ONLY a JSON object: {\"relationships\":[{\"source\":string,\"target\":string,\"relation_type\":string,\"fact\":string,\"score\":number}]}. \
source and target must exactly match entity names from the input entity list. \
Use concise UPPER_SNAKE_CASE relation_type values. Return an empty array when no grounded relationship is present. \
No prose, no code fences.";

/// LLM adapter: extraction + ReAct `decide` over an HTTP chat-completions API.
pub struct HttpLlm {
    ep: Endpoint,
}

impl HttpLlm {
    /// Point at `base_url` (e.g. `https://api.openai.com/v1`) using `model`.
    pub fn new(base_url: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            ep: Endpoint::new(base_url, model),
        }
    }

    /// Attach a bearer API key (LiteLLM/OpenAI). Omit for keyless local proxies.
    pub fn with_api_key(mut self, key: impl Into<String>) -> Self {
        self.ep.api_key = Some(key.into());
        self
    }

    async fn chat(&self, system: &str, user: String) -> CoreResult<String> {
        let body = ChatRequest {
            model: self.ep.model.clone(),
            messages: vec![
                ChatMessage {
                    role: "system",
                    content: system.to_string(),
                },
                ChatMessage {
                    role: "user",
                    content: user,
                },
            ],
            temperature: 0.0,
            stream: None,
        };
        let resp: ChatResponse = self
            .ep
            .post_json("/chat/completions", &body, CoreError::Llm)
            .await?;
        resp.choices
            .into_iter()
            .next()
            .map(|c| c.message.content)
            .ok_or_else(|| CoreError::Llm("no choices in chat response".into()))
    }

    async fn chat_stream<F>(
        &self,
        system: &str,
        user: String,
        mut on_delta: F,
    ) -> CoreResult<String>
    where
        F: FnMut(&str),
    {
        let body = ChatRequest {
            model: self.ep.model.clone(),
            messages: vec![
                ChatMessage {
                    role: "system",
                    content: system.to_string(),
                },
                ChatMessage {
                    role: "user",
                    content: user,
                },
            ],
            temperature: 0.0,
            stream: Some(true),
        };
        let url = format!("{}/chat/completions", self.ep.base_url);
        let mut req = self.ep.client.post(&url).json(&body);
        if let Some(key) = &self.ep.api_key {
            req = req.bearer_auth(key);
        }
        let resp = req
            .send()
            .await
            .map_err(|e| CoreError::Llm(e.to_string()))?;
        let resp = resp
            .error_for_status()
            .map_err(|e| CoreError::Llm(e.to_string()))?;
        let mut chunks = resp.bytes_stream();
        let mut line_buffer = Vec::new();
        let mut content = String::new();
        let mut done = false;

        while let Some(chunk) = chunks.next().await {
            let chunk = chunk.map_err(|e| CoreError::Llm(e.to_string()))?;
            line_buffer.extend_from_slice(&chunk);
            while let Some(newline_index) = line_buffer.iter().position(|b| *b == b'\n') {
                let line: Vec<u8> = line_buffer.drain(..=newline_index).collect();
                if handle_openai_stream_line(&line, &mut content, &mut on_delta)? {
                    done = true;
                    break;
                }
            }
            if done {
                break;
            }
        }

        if !done && !line_buffer.is_empty() {
            handle_openai_stream_line(&line_buffer, &mut content, &mut on_delta)?;
        }

        Ok(content)
    }

    /// Raw single-turn completion: returns the model's message content
    /// verbatim. Callers that need structured output use [`Self::extract_memory`]
    /// or [`Self::decide`], which parse cleaned JSON.
    pub async fn complete(&self, system: &str, user: impl Into<String>) -> CoreResult<String> {
        self.chat(system, user.into()).await
    }

    /// Stream a raw single-turn completion from an OpenAI-/LiteLLM-compatible
    /// Server-Sent Events response. `on_delta` is invoked once for each
    /// `choices[].delta.content` fragment and the fully assembled content is
    /// returned when `[DONE]` is observed or the stream closes.
    ///
    /// This is intentionally an adapter-level method for now: it proves the F7
    /// token wire without adding `tokio`, `reqwest`, or stream types to the
    /// portable [`LlmPort`] signature.
    pub async fn stream_complete<F>(
        &self,
        system: &str,
        user: impl Into<String>,
        on_delta: F,
    ) -> CoreResult<String>
    where
        F: FnMut(&str),
    {
        self.chat_stream(system, user.into(), on_delta).await
    }
}

fn handle_openai_stream_line<F>(
    line: &[u8],
    content: &mut String,
    on_delta: &mut F,
) -> CoreResult<bool>
where
    F: FnMut(&str),
{
    let line = std::str::from_utf8(line)
        .map_err(|e| CoreError::Llm(format!("bad stream utf-8: {e}")))?
        .trim_end_matches(['\r', '\n']);
    let Some(payload) = line.strip_prefix("data:") else {
        return Ok(false);
    };
    let payload = payload.trim_start();
    if payload == "[DONE]" {
        return Ok(true);
    }
    if payload.is_empty() {
        return Ok(false);
    }
    let chunk: ChatStreamChunk = serde_json::from_str(payload)
        .map_err(|e| CoreError::Llm(format!("bad stream json: {e}")))?;
    for choice in chunk.choices {
        let Some(delta) = choice.delta.content.filter(|s| !s.is_empty()) else {
            continue;
        };
        on_delta(&delta);
        content.push_str(&delta);
    }
    Ok(false)
}

#[async_trait]
impl LlmPort for HttpLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        let content = self.chat(EXTRACT_SYSTEM, episode.content.clone()).await?;
        parse_memory_draft(&content)
    }

    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        let user = json!({
            "title": memory.title,
            "content": memory.content,
            "entities": memory.entities,
        })
        .to_string();
        let content = self.chat(RELATIONSHIP_SYSTEM, user).await?;
        parse_relationship_drafts(&content)
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        // Render the prompt the model reasons over. The engine still owns the
        // loop; only this single judgment is delegated to the model.
        let mut user =
            format!("Goal: {goal}\nRound: {round}\nAvailable tools: {available_tools:?}\n");
        if !transcript.is_empty() {
            user.push_str("Transcript:\n");
            for e in transcript {
                let who = match e.role {
                    Role::Thought => "thought",
                    Role::Action => "action",
                    Role::Observation => "observation",
                    Role::Human => "human",
                    Role::Answer => "answer",
                };
                user.push_str(&format!("- [{who}] {}\n", e.content));
            }
        }
        let content = self.chat(DECIDE_SYSTEM, user).await?;
        serde_json::from_str(clean_structured(&content))
            .map_err(|e| CoreError::Llm(format!("bad action json: {e}")))
    }
}
