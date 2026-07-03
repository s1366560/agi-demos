//! `agistack-adapters-http-llm`: the **cloud** half of the LLM/embedding ports.
//!
//! Implements [`LlmPort`] and [`EmbeddingPort`] against any
//! **OpenAI-/LiteLLM-compatible** HTTP endpoint (`POST /chat/completions`,
//! `POST /embeddings`). The Python backend's LiteLLM client served extraction,
//! agent reasoning and embeddings from one provider; this is its Rust analog.
//!
//! ## Why this lives in its own native-only crate
//! `reqwest` drags in a TLS stack and (transitively) `tokio`. Keeping it in a
//! dedicated adapter crate — never in `core` — preserves the runtime-agnostic,
//! wasm-compilable core invariant (ADR-0001). The composition root picks this
//! adapter on the server and an on-device model (llama.cpp/Candle, noted future)
//! or a `fetch`-based binding in the browser — the core never sees the seam.
//!
//! ## Agent First
//! The semantic work still happens in the model: `decide` asks it to emit a
//! structured [`AgentAction`] and `extract_memory` a structured draft. This
//! adapter is pure transport + (de)serialization — it makes no judgments, it
//! just carries the structured tool-call to/from the provider.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use agistack_core::agent::types::{AgentAction, Role, TranscriptEntry};
use agistack_core::model::{Entity, Episode};
use agistack_core::ports::{
    CoreError, CoreResult, EmbeddingPort, LlmPort, MemoryDraft, RerankHit, RerankPort,
};

/// Shared HTTP transport config: base URL, optional bearer key, model id.
#[derive(Clone)]
struct Endpoint {
    client: reqwest::Client,
    base_url: String,
    api_key: Option<String>,
    model: String,
}

impl Endpoint {
    fn new(base_url: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            client: reqwest::Client::new(),
            base_url: base_url.into().trim_end_matches('/').to_string(),
            api_key: None,
            model: model.into(),
        }
    }

    /// POST `body` to `{base}{path}` and deserialize the JSON response, mapping
    /// transport / non-2xx / decode failures to `err`.
    async fn post_json<B: Serialize, R: for<'de> Deserialize<'de>>(
        &self,
        path: &str,
        body: &B,
        err: fn(String) -> CoreError,
    ) -> CoreResult<R> {
        let url = format!("{}{}", self.base_url, path);
        let mut req = self.client.post(&url).json(body);
        if let Some(key) = &self.api_key {
            req = req.bearer_auth(key);
        }
        let resp = req.send().await.map_err(|e| err(e.to_string()))?;
        let resp = resp.error_for_status().map_err(|e| err(e.to_string()))?;
        resp.json::<R>().await.map_err(|e| err(e.to_string()))
    }
}

// ---- OpenAI-compatible wire types (only the fields we use) ----

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

#[derive(Serialize)]
struct EmbeddingRequest {
    model: String,
    input: String,
}

#[derive(Deserialize)]
struct EmbeddingResponse {
    data: Vec<EmbeddingData>,
}

#[derive(Deserialize)]
struct EmbeddingData {
    embedding: Vec<f32>,
}

// ---- Cohere/Jina/BGE-compatible rerank wire types ----

#[derive(Serialize)]
struct RerankRequest<'a> {
    model: &'a str,
    query: &'a str,
    documents: &'a [String],
    #[serde(skip_serializing_if = "Option::is_none")]
    top_n: Option<usize>,
    return_documents: bool,
}

#[derive(Deserialize)]
struct RerankResponse {
    results: Vec<RerankResultWire>,
}

#[derive(Deserialize)]
struct RerankResultWire {
    index: usize,
    // Cohere/Jina/BGE emit `relevance_score`; some servers (vLLM) emit `score`.
    #[serde(default)]
    relevance_score: Option<f32>,
    #[serde(default)]
    score: Option<f32>,
}

/// The draft shape we ask the model to return. Mirrors [`MemoryDraft`] but is a
/// `Deserialize` wire type (entities reuse the core [`Entity`], which is serde).
#[derive(Deserialize)]
struct DraftWire {
    title: String,
    content: String,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    entities: Vec<Entity>,
}

/// Strip a leading reasoning block that "thinking" models (MiniMax-M2,
/// DeepSeek-R1, QwQ, GLM in reasoning mode …) prepend to the answer, e.g.
/// `<think> … </think>\n\n{json}`. Returns the text after the closing tag; if
/// there is no well-formed `<think>…</think>` wrapper the input is returned
/// unchanged. This runs **before** [`strip_fences`] so structured JSON survives
/// a reasoning preamble.
fn strip_reasoning(s: &str) -> &str {
    let t = s.trim_start();
    let Some(rest) = t.strip_prefix("<think>") else {
        return s;
    };
    match rest.find("</think>") {
        Some(i) => rest[i + "</think>".len()..].trim_start(),
        // Unterminated reasoning block (truncated output): nothing usable after it.
        None => "",
    }
}

/// Strip a leading/trailing Markdown code fence (```json … ```), which models
/// frequently wrap JSON in. Returns the inner text trimmed.
fn strip_fences(s: &str) -> &str {
    let t = s.trim();
    let Some(rest) = t.strip_prefix("```") else {
        return t;
    };
    // Drop the optional language tag on the first line, then the trailing fence.
    let rest = rest.split_once('\n').map(|(_, rest)| rest).unwrap_or("");
    rest.trim().strip_suffix("```").unwrap_or(rest).trim()
}

/// Clean a model's chat content into the raw structured payload: drop a leading
/// reasoning block, then any Markdown code fence.
fn clean_structured(content: &str) -> &str {
    strip_fences(strip_reasoning(content))
}

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

    /// Raw single-turn completion: returns the model's message content
    /// **verbatim** (reasoning `<think>` blocks and code fences are *not*
    /// stripped — callers that need structured output use [`Self::extract_memory`]
    /// / [`Self::decide`], which parse cleaned JSON). Useful for a plain prompt
    /// and for liveness/conformance checks against a real provider.
    pub async fn complete(&self, system: &str, user: impl Into<String>) -> CoreResult<String> {
        self.chat(system, user.into()).await
    }
}

const EXTRACT_SYSTEM: &str = "You distill an episode into a memory. Respond with ONLY a JSON object: \
{\"title\": string, \"content\": string, \"tags\": string[], \"entities\": [{\"name\": string, \"kind\": string}]}. \
No prose, no code fences.";

const DECIDE_SYSTEM: &str = "You are a ReAct agent. Choose the next action and respond with ONLY a JSON object, one of: \
{\"kind\":\"call_tool\",\"tool\":string,\"input_json\":string} | \
{\"kind\":\"finish\",\"answer\":string} | \
{\"kind\":\"request_human\",\"request\":{\"id\":string,\"kind\":\"clarification\"|\"decision\"|\"env_var\"|\"permission\",\"prompt\":string}}. \
input_json must be a JSON string. No prose, no code fences.";

#[async_trait]
impl LlmPort for HttpLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        let content = self.chat(EXTRACT_SYSTEM, episode.content.clone()).await?;
        let wire: DraftWire = serde_json::from_str(clean_structured(&content))
            .map_err(|e| CoreError::Llm(format!("bad draft json: {e}")))?;
        Ok(MemoryDraft {
            title: wire.title,
            content: wire.content,
            tags: wire.tags,
            entities: wire.entities,
        })
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

/// Embedding adapter over an HTTP `/embeddings` API.
pub struct HttpEmbedding {
    ep: Endpoint,
}

impl HttpEmbedding {
    pub fn new(base_url: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            ep: Endpoint::new(base_url, model),
        }
    }

    pub fn with_api_key(mut self, key: impl Into<String>) -> Self {
        self.ep.api_key = Some(key.into());
        self
    }
}

#[async_trait]
impl EmbeddingPort for HttpEmbedding {
    async fn embed(&self, text: &str) -> CoreResult<Vec<f32>> {
        let body = EmbeddingRequest {
            model: self.ep.model.clone(),
            input: text.to_string(),
        };
        let resp: EmbeddingResponse = self
            .ep
            .post_json("/embeddings", &body, CoreError::Embedding)
            .await?;
        resp.data
            .into_iter()
            .next()
            .map(|d| d.embedding)
            .ok_or_else(|| CoreError::Embedding("no data in embedding response".into()))
    }
}

/// Reranker adapter over a **Cohere/Jina/BGE-compatible** HTTP `POST /rerank`
/// endpoint (the second stage of hybrid search). `reqwest` keeps it native-only,
/// never in `core`/wasm (ADR-0001), same as [`HttpLlm`]/[`HttpEmbedding`].
pub struct HttpRerank {
    ep: Endpoint,
}

impl HttpRerank {
    /// Point at `base_url` (e.g. `http://localhost:8081` or a Cohere/Jina base)
    /// using cross-encoder `model` (ignored by servers that pin one model).
    pub fn new(base_url: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            ep: Endpoint::new(base_url, model),
        }
    }

    pub fn with_api_key(mut self, key: impl Into<String>) -> Self {
        self.ep.api_key = Some(key.into());
        self
    }
}

#[async_trait]
impl RerankPort for HttpRerank {
    async fn rerank(&self, query: &str, documents: &[String]) -> CoreResult<Vec<RerankHit>> {
        if documents.is_empty() {
            return Ok(Vec::new());
        }
        let body = RerankRequest {
            model: &self.ep.model,
            query,
            documents,
            top_n: None,
            return_documents: false,
        };
        let resp: RerankResponse = self
            .ep
            .post_json("/rerank", &body, CoreError::Rerank)
            .await?;
        let mut hits: Vec<RerankHit> = resp
            .results
            .into_iter()
            .map(|r| RerankHit {
                index: r.index,
                score: r.relevance_score.or(r.score).unwrap_or(0.0),
            })
            .collect();
        // Providers usually pre-sort by relevance; sort defensively (desc).
        hits.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        Ok(hits)
    }
}

#[cfg(test)]
mod unit {
    use super::{clean_structured, strip_fences, strip_reasoning};

    #[test]
    fn strip_fences_handles_plain_and_fenced() {
        assert_eq!(strip_fences(r#"{"a":1}"#), r#"{"a":1}"#);
        assert_eq!(strip_fences("```json\n{\"a\":1}\n```"), r#"{"a":1}"#);
        assert_eq!(strip_fences("```\n{\"a\":1}\n```"), r#"{"a":1}"#);
    }

    #[test]
    fn strip_reasoning_removes_leading_think_block() {
        // Plain content is untouched.
        assert_eq!(strip_reasoning(r#"{"a":1}"#), r#"{"a":1}"#);
        // A leading <think>…</think> block is dropped, answer survives.
        assert_eq!(
            strip_reasoning("<think>let me consider</think>\n\n{\"a\":1}"),
            r#"{"a":1}"#
        );
        // Leading whitespace before the tag is tolerated.
        assert_eq!(strip_reasoning("  <think>x</think> hi"), "hi");
        // An unterminated (truncated) reasoning block yields nothing usable.
        assert_eq!(strip_reasoning("<think>cut off"), "");
    }

    #[test]
    fn clean_structured_strips_reasoning_then_fences() {
        // Reasoning models often wrap JSON in BOTH a think block and a fence.
        assert_eq!(
            clean_structured("<think>reasoning…</think>\n```json\n{\"a\":1}\n```"),
            r#"{"a":1}"#
        );
    }
}
