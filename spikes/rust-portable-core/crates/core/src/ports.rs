use async_trait::async_trait;

use crate::model::{Entity, Episode, Memory};

#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error("not found")]
    NotFound,
    #[error("llm error: {0}")]
    Llm(String),
    #[error("embedding error: {0}")]
    Embedding(String),
    #[error("storage error: {0}")]
    Storage(String),
    #[error("tool error: {0}")]
    Tool(String),
}

pub type CoreResult<T> = Result<T, CoreError>;

/// Platform-agnostic clock. Keeping `std::time` out of the core is what lets the
/// same code compile to `wasm32-unknown-unknown`, where `SystemTime` panics.
pub trait Clock: Send + Sync {
    fn now_ms(&self) -> i64;
}

/// Draft produced by a single LLM "extract" step before it becomes a [`Memory`].
#[derive(Debug, Clone)]
pub struct MemoryDraft {
    pub title: String,
    pub content: String,
    pub tags: Vec<String>,
    pub entities: Vec<Entity>,
}

/// One ReAct/skill step: turn an episode into a structured memory draft.
#[async_trait]
pub trait LlmPort: Send + Sync {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft>;
}

#[async_trait]
pub trait EmbeddingPort: Send + Sync {
    async fn embed(&self, text: &str) -> CoreResult<Vec<f32>>;
}

/// Hexagonal port for hosting **sandboxed third-party tools** (L1 third-party /
/// MCP). The host runtime is platform-swappable behind this trait:
/// - server / desktop -> Wasmtime (JIT, fuel/epoch quotas)
/// - iOS (no JIT) / mobile -> Wasmi or Wasmer
/// - browser (core is itself wasm) -> Wasmi (wasm-in-wasm) or a Web-Worker proxy
///
/// Trusted *built-in* tools do NOT go through here — they are plain `dyn Trait`
/// registrations compiled into the core (native speed, no sandbox). This is the
/// trust axis: never run untrusted code in-process; only behind a wasm sandbox.
#[async_trait]
pub trait ToolHost: Send + Sync {
    /// Capability surface: the tool names this host can dispatch.
    fn list_tools(&self) -> Vec<String>;
    /// Invoke a sandboxed tool with a JSON input, returning a JSON output.
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String>;
}

/// Mirrors `MemoryRepository` in
/// src/domain/ports/repositories/memory_repository.py — including the default
/// `search_by_project` fallback.
#[async_trait]
pub trait MemoryRepository: Send + Sync {
    async fn save(&self, memory: Memory) -> CoreResult<Memory>;
    async fn find_by_id(&self, id: &str) -> CoreResult<Option<Memory>>;
    async fn list_by_project(
        &self,
        project_id: &str,
        limit: usize,
        offset: usize,
    ) -> CoreResult<Vec<Memory>>;

    /// Default in-core search mirroring the Python fallback: case-insensitive
    /// substring over title/content. Concrete adapters override this to push
    /// search into storage (e.g. sqlite-vec / pgvector).
    async fn search_by_project(
        &self,
        project_id: &str,
        query: &str,
        limit: usize,
    ) -> CoreResult<Vec<Memory>> {
        let needle = query.to_lowercase();
        let all = self.list_by_project(project_id, limit, 0).await?;
        Ok(all
            .into_iter()
            .filter(|m| {
                m.title.to_lowercase().contains(&needle)
                    || m.content.to_lowercase().contains(&needle)
            })
            .collect())
    }

    async fn delete(&self, id: &str) -> CoreResult<bool>;
}
