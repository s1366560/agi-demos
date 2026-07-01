//! Application service orchestrating the Episode → Memory pipeline and search.
//!
//! Holds its dependencies as trait objects (`Arc<dyn _>`) so the same service is
//! wired with server adapters (Postgres/pgvector), device adapters
//! (SQLite/sqlite-vec) or browser adapters — without touching this code.

use std::sync::Arc;

use crate::model::{Episode, Memory};
use crate::ports::{
    Clock, CoreResult, EmbeddingPort, LlmPort, MemoryRepository, VectorIndexPort,
};
use crate::util::new_memory_id;

/// Episode → Memory ingestion + retrieval.
#[derive(Clone)]
pub struct MemoryService {
    repo: Arc<dyn MemoryRepository>,
    llm: Arc<dyn LlmPort>,
    embedding: Arc<dyn EmbeddingPort>,
    clock: Arc<dyn Clock>,
    /// Optional ANN index. When present, [`ingest_episode`] upserts the memory's
    /// embedding and [`semantic_search`] uses it; otherwise search falls back to
    /// the repository's keyword path.
    ///
    /// [`ingest_episode`]: MemoryService::ingest_episode
    /// [`semantic_search`]: MemoryService::semantic_search
    vectors: Option<Arc<dyn VectorIndexPort>>,
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
            vectors: None,
        }
    }

    /// Wire a vector index, enabling [`semantic_search`](Self::semantic_search).
    pub fn with_vectors(mut self, vectors: Arc<dyn VectorIndexPort>) -> Self {
        self.vectors = Some(vectors);
        self
    }

    /// Single-step "skill": extract a memory from an episode, embed it, persist
    /// it, and (if a vector index is wired) index its embedding.
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
            id: id.clone(),
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
            embedding: Some(embedding.clone()),
        };

        let saved = self.repo.save(memory).await?;
        if let Some(vectors) = &self.vectors {
            vectors.upsert(project_id, &id, &embedding).await?;
        }
        Ok(saved)
    }

    /// Direct create (no LLM extraction): persist a caller-supplied memory,
    /// embedding its content and indexing the vector when a vector index is wired.
    /// Mirrors the Python `POST /api/v1/memories/` `create_memory` path, which
    /// stores the memory as given rather than distilling it from an episode.
    #[allow(clippy::too_many_arguments)]
    pub async fn create_memory(
        &self,
        project_id: &str,
        author_id: &str,
        title: &str,
        content: &str,
        content_type: &str,
        tags: Vec<String>,
        entities: Vec<crate::model::Entity>,
    ) -> CoreResult<Memory> {
        let embedding = self.embedding.embed(content).await?;
        let created_at_ms = self.clock.now_ms();
        let id = new_memory_id(&format!("{project_id}:{title}:{created_at_ms}"));

        let memory = Memory {
            id: id.clone(),
            project_id: project_id.to_string(),
            title: title.to_string(),
            content: content.to_string(),
            author_id: author_id.to_string(),
            content_type: content_type.to_string(),
            tags,
            entities,
            version: 1,
            status: "ENABLED".to_string(),
            created_at_ms,
            embedding: Some(embedding.clone()),
        };

        let saved = self.repo.save(memory).await?;
        if let Some(vectors) = &self.vectors {
            vectors.upsert(project_id, &id, &embedding).await?;
        }
        Ok(saved)
    }

    /// Total memories in a project, optionally constrained by the same
    /// case-insensitive title/content search as [`search`](Self::search). Backs
    /// the `total` field of the paginated list contract.
    pub async fn count(&self, project_id: &str, search: Option<&str>) -> CoreResult<usize> {
        self.repo.count_by_project(project_id, search).await
    }

    /// Page through a project's memories, newest first (list contract).
    pub async fn list(
        &self,
        project_id: &str,
        limit: usize,
        offset: usize,
    ) -> CoreResult<Vec<Memory>> {
        self.repo.list_by_project(project_id, limit, offset).await
    }

    /// Keyword search (repository-backed; substring or SQL `LIKE`).
    pub async fn search(
        &self,
        project_id: &str,
        query: &str,
        limit: usize,
    ) -> CoreResult<Vec<Memory>> {
        self.repo.search_by_project(project_id, query, limit).await
    }

    /// Semantic search: embed the query, hit the vector index, and hydrate the
    /// matching memories. Falls back to keyword [`search`](Self::search) when no
    /// vector index is wired.
    pub async fn semantic_search(
        &self,
        project_id: &str,
        query: &str,
        k: usize,
    ) -> CoreResult<Vec<Memory>> {
        let Some(vectors) = &self.vectors else {
            return self.search(project_id, query, k).await;
        };
        let qvec = self.embedding.embed(query).await?;
        let hits = vectors.query(project_id, &qvec, k).await?;
        let mut out = Vec::with_capacity(hits.len());
        for hit in hits {
            if let Some(memory) = self.repo.find_by_id(&hit.id).await? {
                if memory.project_id == project_id {
                    out.push(memory);
                }
            }
        }
        Ok(out)
    }

    pub async fn get(&self, id: &str) -> CoreResult<Option<Memory>> {
        self.repo.find_by_id(id).await
    }

    pub async fn delete(&self, project_id: &str, id: &str) -> CoreResult<bool> {
        let removed = self.repo.delete(id).await?;
        if removed {
            if let Some(vectors) = &self.vectors {
                vectors.remove(project_id, id).await?;
            }
        }
        Ok(removed)
    }
}
