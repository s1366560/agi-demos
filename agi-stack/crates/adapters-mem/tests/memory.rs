//! Memory pipeline: ingest an episode, then retrieve it by keyword and by
//! semantic (vector) search. Runs under a generic executor (`block_on`) with no
//! tokio — the core's runtime-agnostic invariant in action.

use std::sync::Arc;

use agistack_adapters_mem::{
    FixedClock, HashEmbedding, InMemoryMemoryRepository, InMemoryVectorIndex, StubLlm,
};
use agistack_core::ports::CoreResult;
use agistack_core::{
    EmbeddingPort, Episode, Memory, MemoryRepository, MemoryService, SourceType, VectorIndexPort,
};
use futures::executor::block_on;

fn episode(content: &str) -> Episode {
    Episode {
        content: content.to_string(),
        source_type: SourceType::Text,
        valid_at_ms: 0,
        name: None,
        project_id: Some("p1".into()),
        user_id: None,
    }
}

#[test]
fn ingest_then_keyword_search() {
    let service = MemoryService::new(
        Arc::new(InMemoryMemoryRepository::new()),
        Arc::new(StubLlm),
        Arc::new(HashEmbedding::new(16)),
        Arc::new(FixedClock(1_700_000_000_000)),
    );

    let memory = block_on(service.ingest_episode(
        "p1",
        "u1",
        &episode("Vector databases enable semantic memory retrieval"),
    ))
    .unwrap();
    assert_eq!(memory.project_id, "p1");
    assert_eq!(memory.embedding.as_ref().unwrap().len(), 16);

    let hit = block_on(service.search("p1", "semantic", 10)).unwrap();
    assert_eq!(hit.len(), 1);
    assert_eq!(hit[0].id, memory.id);

    let miss = block_on(service.search("p1", "nonexistent", 10)).unwrap();
    assert!(miss.is_empty());

    // Tenancy: another project sees nothing.
    let other = block_on(service.search("p2", "semantic", 10)).unwrap();
    assert!(other.is_empty());
}

#[test]
fn semantic_search_ranks_by_vector_similarity() {
    let vectors = Arc::new(InMemoryVectorIndex::new());
    let service = MemoryService::new(
        Arc::new(InMemoryMemoryRepository::new()),
        Arc::new(StubLlm),
        Arc::new(HashEmbedding::new(32)),
        Arc::new(FixedClock(1_700_000_000_000)),
    )
    .with_vectors(vectors);

    let m_vec = block_on(service.ingest_episode(
        "p1",
        "u1",
        &episode("vector database similarity search with embeddings"),
    ))
    .unwrap();
    let _m_cook = block_on(service.ingest_episode(
        "p1",
        "u1",
        &episode("roasted vegetables with olive oil and garlic"),
    ))
    .unwrap();

    // A query close to the first memory should rank it first.
    let hits = block_on(service.semantic_search("p1", "embeddings similarity vector", 2)).unwrap();
    assert!(!hits.is_empty());
    assert_eq!(hits[0].id, m_vec.id, "nearest memory should rank first");

    // Tenancy holds through the vector path too.
    let none = block_on(service.semantic_search("p2", "embeddings", 5)).unwrap();
    assert!(none.is_empty());
}

#[test]
fn semantic_search_falls_back_to_keyword_without_vectors() {
    // No vector index wired -> semantic_search delegates to keyword search.
    let service = MemoryService::new(
        Arc::new(InMemoryMemoryRepository::new()),
        Arc::new(StubLlm),
        Arc::new(HashEmbedding::new(16)),
        Arc::new(FixedClock(1)),
    );
    block_on(service.ingest_episode("p1", "u1", &episode("alpha beta gamma keyword"))).unwrap();
    let hits = block_on(service.semantic_search("p1", "keyword", 10)).unwrap();
    assert_eq!(hits.len(), 1);
}

/// Repo wrapper whose `find_by_ids` returns rows in reverse id order, standing
/// in for adapters (e.g. `WHERE id = ANY(...)`) whose batch fetch order is
/// unspecified. `semantic_search` must still emit in vector-rank order.
struct ReversingRepo {
    inner: InMemoryMemoryRepository,
}

#[async_trait::async_trait]
impl MemoryRepository for ReversingRepo {
    async fn save(&self, memory: Memory) -> CoreResult<Memory> {
        self.inner.save(memory).await
    }

    async fn find_by_id(&self, id: &str) -> CoreResult<Option<Memory>> {
        self.inner.find_by_id(id).await
    }

    async fn find_by_ids(&self, ids: &[String]) -> CoreResult<Vec<Memory>> {
        let mut out = self.inner.find_by_ids(ids).await?;
        out.reverse();
        Ok(out)
    }

    async fn list_by_project(
        &self,
        project_id: &str,
        limit: usize,
        offset: usize,
    ) -> CoreResult<Vec<Memory>> {
        self.inner.list_by_project(project_id, limit, offset).await
    }

    async fn delete(&self, id: &str) -> CoreResult<bool> {
        self.inner.delete(id).await
    }
}

#[test]
fn semantic_search_reorders_batch_hydration_by_vector_rank() {
    let vectors = Arc::new(InMemoryVectorIndex::new());
    let embedding = Arc::new(HashEmbedding::new(32));
    let service = MemoryService::new(
        Arc::new(ReversingRepo {
            inner: InMemoryMemoryRepository::new(),
        }),
        Arc::new(StubLlm),
        embedding.clone(),
        Arc::new(FixedClock(1_700_000_000_000)),
    )
    .with_vectors(vectors.clone());

    for content in [
        "vector database similarity search with embeddings",
        "embeddings for semantic memory retrieval over vectors",
        "roasted vegetables with olive oil and garlic",
    ] {
        block_on(service.ingest_episode("p1", "u1", &episode(content))).unwrap();
    }

    let query = "embeddings similarity vector";
    let qvec = block_on(embedding.embed(query)).unwrap();
    let want: Vec<String> = block_on(vectors.query("p1", &qvec, 3))
        .unwrap()
        .into_iter()
        .map(|hit| hit.id)
        .collect();

    let hits = block_on(service.semantic_search("p1", query, 3)).unwrap();
    let got: Vec<&str> = hits.iter().map(|m| m.id.as_str()).collect();
    let want: Vec<&str> = want.iter().map(String::as_str).collect();
    assert_eq!(got, want, "results must follow vector rank, not repo order");
}
