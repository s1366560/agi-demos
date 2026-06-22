# graph/ -- Neo4j Knowledge Graph Layer

Last checked against code: 2026-06-22

## Purpose
Native knowledge graph implementation: entity/relationship extraction, hybrid search, community detection, deduplication. No Graphiti dependency.

## Key Files
- `native_graph_adapter.py` (~1404 lines) -- `NativeGraphAdapter` implements `GraphServicePort`
- `search/hybrid_search.py` (~855 lines) -- vector + keyword search with RRF fusion
- `extraction/entity_extractor.py` -- LLM-based entity extraction from text
- `extraction/relationship_extractor.py` -- LLM-based relationship extraction
- `extraction/reflexion.py` -- self-correction loop for extraction quality
- `extraction/prompts.py` -- LLM prompt templates for extraction
- `community/louvain_detector.py` -- Louvain community detection algorithm
- `community/community_updater.py` -- incremental community updates
- `dedup/hash_deduplicator.py` -- hash-based entity deduplication
- `embedding/embedding_service.py` -- embedding generation for graph nodes
- `neo4j_client.py` -- low-level Neo4j driver operations
- `schemas.py` -- `EntityNode`, `EpisodicNode`, `EpisodicEdge`, etc.
- `distributed_transaction_coordinator.py` -- cross-store consistency (PG + Neo4j)

## Hybrid Search Configuration
| Parameter | Default | Description |
|-----------|---------|-------------|
| Vector weight | 0.6 | Semantic similarity weight |
| Keyword weight | 0.4 | BM25 keyword match weight |
| RRF k | 60 | Reciprocal Rank Fusion constant |
| MMR lambda | 0.7 | Diversity vs relevance tradeoff |
| Temporal half-life | 30 days | Recency decay factor |

Search pipeline: vector search -> keyword search -> RRF fusion -> MMR diversity re-ranking -> temporal decay -> query expansion (optional)

## Extraction Pipeline
```
Text -> EntityExtractor (LLM) -> RelationshipExtractor (LLM)
     -> ReflexionChecker (LLM, max 2 iterations)
     -> HashDeduplicator -> Neo4j upsert
```
- Reflexion enabled by default, catches extraction errors/hallucinations
- Max 2 reflexion iterations to bound LLM cost

## Community Detection
- Louvain algorithm for graph partitioning
- `CommunityUpdater`: incremental updates when new entities added
- Communities used for context aggregation in search results

## Embedding Dimension Handling
- `auto_clear_embeddings` flag: when embedding model changes dimension, auto-wipes old embeddings
- Dimension mismatch detected on search -- triggers re-embedding if flag enabled
- WARNING: auto-clear drops ALL existing embeddings -- costly re-computation

## NativeGraphAdapter Key Methods
- `add_episode()` -- full pipeline: extract entities/relationships, deduplicate, store
- `process_episode()` -- entity/relationship processing entry point with schema context
- `extract_entities()` / `extract_relationships()` -- direct LLM extraction access
- `search()` -- hybrid search with configurable weights
- `search_memories()` -- memory-oriented hybrid search
- `get_graph_data()` -- graph snapshot for a project (nodes + relationships)
- `delete_episode()` / `delete_episode_by_memory_id()` -- cascade delete episode + orphaned entities
- `remove_episode()` / `remove_episode_by_memory_id()` -- alternate removal entry points

## Gotchas
- `native_graph_adapter.py` is ~1404 lines -- largest file in graph/
- Neo4j 5.26+ required (vector index features)
- Entity extraction is LLM-dependent -- quality varies by provider/model
- RRF fusion assumes both vector and keyword indexes exist -- search fails if either missing
- `distributed_transaction_coordinator.py`: PG commit + Neo4j write are NOT atomic -- partial failures possible
- Hash deduplication is exact-match only -- near-duplicates not caught (semantic dedup not implemented)
- Embedding dimension change requires full re-index -- plan model migrations carefully
