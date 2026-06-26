use std::sync::Arc;

use crate::model::{Episode, Memory};
use crate::ports::{Clock, CoreResult, EmbeddingPort, LlmPort, MemoryRepository};
use crate::util::new_memory_id;

/// Application service that orchestrates the Episode -> Memory pipeline.
///
/// Holds its dependencies as trait objects (`Arc<dyn _>`) so the same service
/// can be wired with server adapters (Postgres/pgvector), device adapters
/// (SQLite/sqlite-vec) or wasm adapters — without touching this code.
#[derive(Clone)]
pub struct MemoryService {
    repo: Arc<dyn MemoryRepository>,
    llm: Arc<dyn LlmPort>,
    embedding: Arc<dyn EmbeddingPort>,
    clock: Arc<dyn Clock>,
}

impl MemoryService {
    pub fn new(
        repo: Arc<dyn MemoryRepository>,
        llm: Arc<dyn LlmPort>,
        embedding: Arc<dyn EmbeddingPort>,
        clock: Arc<dyn Clock>,
    ) -> Self {
        Self {
            repo,
            llm,
            embedding,
            clock,
        }
    }

    /// Single-step "skill": extract a memory from an episode, embed it, persist it.
    pub async fn ingest_episode(
        &self,
        project_id: &str,
        author_id: &str,
        episode: &Episode,
    ) -> CoreResult<Memory> {
        let draft = self.llm.extract_memory(episode).await?;
        let embedding = self.embedding.embed(&draft.content).await?;
        let created_at_ms = self.clock.now_ms();
        let id = new_memory_id(&format!("{project_id}:{}:{created_at_ms}", draft.title));

        let memory = Memory {
            id,
            project_id: project_id.to_string(),
            title: draft.title,
            content: draft.content,
            author_id: author_id.to_string(),
            content_type: "text".to_string(),
            tags: draft.tags,
            entities: draft.entities,
            version: 1,
            status: "ENABLED".to_string(),
            created_at_ms,
            embedding: Some(embedding),
        };

        self.repo.save(memory).await
    }

    pub async fn search(
        &self,
        project_id: &str,
        query: &str,
        limit: usize,
    ) -> CoreResult<Vec<Memory>> {
        self.repo.search_by_project(project_id, query, limit).await
    }

    pub async fn get(&self, id: &str) -> CoreResult<Option<Memory>> {
        self.repo.find_by_id(id).await
    }
}
