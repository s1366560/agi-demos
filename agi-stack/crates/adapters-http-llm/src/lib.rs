//! `agistack-adapters-http-llm`: the **cloud** half of the LLM/embedding ports.
//!
//! Implements [`LlmPort`] and [`EmbeddingPort`] against native HTTP providers:
//! OpenAI-/LiteLLM-compatible chat/embedding/rerank endpoints plus provider-native
//! Anthropic Messages streaming. The Python backend's LiteLLM client served
//! extraction, agent reasoning and embeddings from one provider; this is its Rust
//! analog, split by provider/feature so the transport logic can keep growing
//! without turning the crate root into a second runtime.
//!
//! ## Why this lives in its own native-only crate
//! `reqwest` drags in a TLS stack and (transitively) `tokio`. Keeping it in a
//! dedicated adapter crate, never in `core`, preserves the runtime-agnostic,
//! wasm-compilable core invariant (ADR-0001). The composition root picks this
//! adapter on the server and an on-device model (llama.cpp/Candle, noted future)
//! or a `fetch`-based binding in the browser; the core never sees the boundary.
//!
//! ## Agent First
//! The semantic work still happens in the model: `decide` asks it to emit a
//! structured `AgentAction` and `extract_memory` a structured draft. This adapter
//! is pure transport plus serialization: it makes no judgments, it just carries
//! the structured tool-call to and from the provider.

mod anthropic;
mod embedding;
mod endpoint;
mod openai;
mod rerank;
mod structured;

pub use anthropic::AnthropicLlm;
pub use embedding::HttpEmbedding;
pub use openai::HttpLlm;
pub use rerank::HttpRerank;
