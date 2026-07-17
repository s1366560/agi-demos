"""Unit tests for NativeGraphAdapter."""

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.domain.model.memory.episode import Episode, SourceType
from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter
from src.infrastructure.graph.schemas import (
    EntityEdge,
    EntityNode,
    EpisodeStatus,
    HybridSearchResult,
    SearchResultItem,
)


@pytest.fixture
def mock_neo4j_client():
    """Create a mock Neo4j client."""
    client = MagicMock()
    client.execute_query = AsyncMock()
    client.save_node = AsyncMock()
    client.save_edge = AsyncMock()
    client.save_nodes_batch = AsyncMock()
    client.save_edges_batch = AsyncMock()
    client.find_node_by_uuid = AsyncMock(return_value=None)
    client.driver = MagicMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    client = MagicMock()
    client.generate_response = AsyncMock(return_value='{"entities": []}')
    return client


@pytest.fixture
def mock_embedding_service():
    """Create a mock embedding service."""
    service = MagicMock()
    service.embedding_dim = 768
    service.embed_text = AsyncMock(return_value=[0.1] * 768)
    service.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    return service


@pytest.fixture
def mock_queue_port():
    """Create a mock queue port."""
    port = MagicMock()
    port.add_episode = AsyncMock()
    return port


@pytest.fixture
def adapter(mock_neo4j_client, mock_llm_client, mock_embedding_service, mock_queue_port):
    """Create NativeGraphAdapter with mocked dependencies."""
    return NativeGraphAdapter(
        neo4j_client=mock_neo4j_client,
        llm_client=mock_llm_client,
        embedding_service=mock_embedding_service,
        queue_port=mock_queue_port,
        enable_reflexion=False,
    )


@pytest.mark.unit
class TestNativeGraphAdapterInit:
    """Tests for NativeGraphAdapter initialization."""

    def test_adapter_creation(self, mock_neo4j_client, mock_llm_client, mock_embedding_service):
        """Test creating adapter with required dependencies."""
        adapter = NativeGraphAdapter(
            neo4j_client=mock_neo4j_client,
            llm_client=mock_llm_client,
            embedding_service=mock_embedding_service,
        )

        assert adapter._neo4j_client is mock_neo4j_client
        assert adapter._llm_client is mock_llm_client
        assert adapter._embedding_service is mock_embedding_service
        assert adapter._queue_port is None
        assert adapter._enable_reflexion is True


@pytest.mark.unit
class TestNativeGraphAdapterProperties:
    """Tests for adapter properties."""

    def test_client_property(self, adapter, mock_neo4j_client):
        """Test client property returns Neo4j client (lifecycle/close only)."""
        assert adapter.client is mock_neo4j_client

    @pytest.mark.asyncio
    async def test_close_delegates_to_client(self, adapter, mock_neo4j_client):
        """close() forwards to the underlying Neo4j client."""
        await adapter.close()
        mock_neo4j_client.close.assert_awaited_once()

    def test_embedder_property(self, adapter, mock_embedding_service):
        """Test embedder property returns embedding service."""
        assert adapter.embedder is mock_embedding_service

    @pytest.mark.parametrize(
        ("project_id", "project_ids", "expected_scope"),
        [
            (
                "project-1",
                None,
                "(e.project_id = $project_id OR EXISTS { MATCH (e)<-[:MENTIONS]-(ep:Episodic) "
                "WHERE ep.project_id = $project_id })",
            ),
            (
                None,
                ["project-1"],
                "(e.project_id IN $project_ids OR EXISTS { MATCH (e)<-[:MENTIONS]-(ep:Episodic) "
                "WHERE ep.project_id IN $project_ids })",
            ),
        ],
    )
    def test_mention_scope_clause_generates_balanced_exists_subquery(
        self,
        project_id: str | None,
        project_ids: list[str] | None,
        expected_scope: str,
    ) -> None:
        """Project entity scoping must remain valid Neo4j EXISTS syntax."""
        clause = NativeGraphAdapter._mention_scope_clause("e", project_id, project_ids)

        assert clause == expected_scope
        assert clause.count("{") == clause.count("}")


@pytest.mark.unit
class TestNativeGraphAdapterEmbeddingDimension:
    """Tests for embedding dimension compatibility helpers."""

    @pytest.mark.asyncio
    async def test_check_embedding_dimension_redacts_unexpected_exception_details(
        self,
        adapter,
        caplog,
    ):
        """Unexpected dimension check failures should not write exception details to logs."""
        secret = "embedding-check-secret-9753"

        with (
            patch.object(
                adapter,
                "_get_existing_embedding_dimension",
                AsyncMock(side_effect=RuntimeError(secret)),
            ),
            caplog.at_level(
                logging.ERROR,
                logger="src.infrastructure.graph.native_graph_adapter",
            ),
        ):
            await adapter._check_embedding_dimension(force=True)

        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_get_existing_embedding_dimension_redacts_property_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Fast-path dimension lookup failures should not write exception details to logs."""
        secret = "embedding-dim-property-secret-2468"
        mock_neo4j_client.execute_query.side_effect = [
            RuntimeError(secret),
            MagicMock(records=[]),
        ]

        with caplog.at_level(
            logging.DEBUG,
            logger="src.infrastructure.graph.native_graph_adapter",
        ):
            result = await adapter._get_existing_embedding_dimension()

        assert result is None
        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_get_existing_embedding_dimension_redacts_fallback_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Fallback dimension lookup failures should not write exception details to logs."""
        secret = "embedding-dim-fallback-secret-1357"
        mock_neo4j_client.execute_query.side_effect = [
            MagicMock(records=[]),
            RuntimeError(secret),
        ]

        with caplog.at_level(
            logging.WARNING,
            logger="src.infrastructure.graph.native_graph_adapter",
        ):
            result = await adapter._get_existing_embedding_dimension()

        assert result is None
        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_clear_embeddings_by_dimension_redacts_query_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Embedding cleanup failures should not write backend details to logs."""
        secret = "clear-embedding-secret-8642"
        mock_neo4j_client.execute_query.side_effect = RuntimeError(secret)

        with caplog.at_level(
            logging.ERROR,
            logger="src.infrastructure.graph.native_graph_adapter",
        ):
            result = await adapter._clear_embeddings_by_dimension(768)

        assert result == 0
        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
class TestNativeGraphAdapterAddEpisode:
    """Tests for add_episode method."""

    @pytest.mark.asyncio
    async def test_add_episode_success(self, adapter, mock_neo4j_client, mock_queue_port):
        """Test adding episode successfully."""
        mock_neo4j_client.execute_query.return_value = MagicMock(records=[])

        episode = Episode(
            id=str(uuid4()),
            content="Test episode content",
            source_type=SourceType.TEXT,
            valid_at=datetime.now(UTC),
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            metadata={"memory_id": "mem-1"},
        )

        result = await adapter.add_episode(episode)

        assert result is episode
        mock_neo4j_client.execute_query.assert_called()
        mock_queue_port.add_episode.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_episode_processes_synchronously_without_queue(
        self,
        mock_neo4j_client,
        mock_llm_client,
        mock_embedding_service,
    ):
        """Test add_episode still extracts graph data when no queue adapter is configured."""
        mock_neo4j_client.execute_query.return_value = MagicMock(records=[])
        adapter = NativeGraphAdapter(
            neo4j_client=mock_neo4j_client,
            llm_client=mock_llm_client,
            embedding_service=mock_embedding_service,
            queue_port=None,
            enable_reflexion=False,
        )

        episode = Episode(
            id=str(uuid4()),
            content="Test episode content",
            source_type=SourceType.TEXT,
            valid_at=datetime.now(UTC),
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            metadata={"memory_id": "mem-1"},
        )

        with patch.object(adapter, "process_episode", AsyncMock()) as process_episode:
            result = await adapter.add_episode(episode)

        assert result is episode
        process_episode.assert_awaited_once_with(
            episode_uuid=episode.id,
            content=episode.content,
            project_id=episode.project_id,
            tenant_id=episode.tenant_id,
            user_id=episode.user_id,
        )

    @pytest.mark.asyncio
    async def test_add_episode_failure_log_redacts_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Add failures should propagate without writing exception details to logs."""
        secret = "add-episode-secret-1357"
        mock_neo4j_client.execute_query.side_effect = RuntimeError(secret)

        episode = Episode(
            id=str(uuid4()),
            content="Test episode content",
            source_type=SourceType.TEXT,
            valid_at=datetime.now(UTC),
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            metadata={"memory_id": "mem-1"},
        )

        with (
            caplog.at_level(
                logging.ERROR,
                logger="src.infrastructure.graph.native_graph_adapter",
            ),
            pytest.raises(RuntimeError, match=secret),
        ):
            await adapter.add_episode(episode)

        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
class TestNativeGraphAdapterProcessEpisode:
    """Tests for episode entity extraction and graph construction."""

    @pytest.mark.asyncio
    async def test_process_episode_failure_log_redacts_exception_details(
        self,
        adapter,
        caplog,
    ):
        """Process failures should mark failed without writing exception details to logs."""
        secret = "process-episode-secret-2468"
        episode_uuid = "episode-with-secret"

        with (
            patch.object(
                adapter,
                "_load_schema_context",
                AsyncMock(side_effect=RuntimeError(secret)),
            ),
            patch.object(adapter, "_update_episode_status", AsyncMock()) as update_status,
            caplog.at_level(
                logging.ERROR,
                logger="src.infrastructure.graph.native_graph_adapter",
            ),
            pytest.raises(RuntimeError, match=secret),
        ):
            await adapter.process_episode(
                episode_uuid=episode_uuid,
                content="Ada founded a lab.",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
            )

        update_status.assert_awaited_once()
        assert update_status.await_args.args == (episode_uuid, EpisodeStatus.FAILED)
        assert secret not in caplog.text
        assert episode_uuid not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_process_episode_links_existing_duplicate_entity(
        self,
        adapter,
        mock_neo4j_client,
    ):
        """Duplicate extracted entities should mention existing graph nodes, not create copies."""
        extracted = EntityNode(uuid="new-ada", name="Ada", entity_type="Person")
        existing = EntityNode(uuid="existing-ada", name="Ada", entity_type="Person")

        entity_extractor = MagicMock()
        entity_extractor.extract = AsyncMock(return_value=[extracted])
        entity_extractor.deduplicate_entity_nodes = AsyncMock(
            return_value=([], {"Ada": "existing-ada"})
        )

        relationship_extractor = MagicMock()
        relationship_extractor.extract_from_entity_nodes = AsyncMock(return_value=[])
        mock_neo4j_client.find_node_by_uuid.return_value = {"name": "Episode"}

        with (
            patch.object(
                adapter,
                "_load_schema_context",
                AsyncMock(
                    return_value={
                        "entity_types_context": [],
                        "entity_type_id_to_name": {},
                        "edge_type_map": {},
                    }
                ),
            ),
            patch.object(adapter, "_get_entity_extractor", return_value=entity_extractor),
            patch.object(adapter, "_get_existing_entities", AsyncMock(return_value=[existing])),
            patch.object(
                adapter,
                "_get_relationship_extractor",
                return_value=relationship_extractor,
            ),
            patch.object(adapter, "_save_discovered_types", AsyncMock()),
            patch.object(adapter, "_update_episode_status", AsyncMock()),
        ):
            result = await adapter.process_episode(
                episode_uuid="episode-1",
                content="Ada founded a lab.",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
            )

        assert [node.uuid for node in result.nodes] == ["existing-ada"]
        # All existing entities deduped away -> no new nodes to save.
        mock_neo4j_client.save_nodes_batch.assert_awaited_once_with([])
        mock_neo4j_client.save_edges_batch.assert_awaited_once()
        saved_edges = mock_neo4j_client.save_edges_batch.await_args.args[0]
        assert [edge["to_uuid"] for edge in saved_edges] == ["existing-ada"]
        relationship_extractor.extract_from_entity_nodes.assert_awaited_once()
        rel_entities = relationship_extractor.extract_from_entity_nodes.await_args.kwargs[
            "entity_nodes"
        ]
        assert [entity.uuid for entity in rel_entities] == ["existing-ada"]

    @pytest.mark.asyncio
    async def test_process_episode_saves_person_entities_with_person_label(
        self,
        adapter,
        mock_neo4j_client,
    ):
        """Graph writes should preserve canonical person type as a Neo4j label."""
        extracted = EntityNode(uuid="new-ada", name="Ada", entity_type="Person")

        entity_extractor = MagicMock()
        entity_extractor.extract = AsyncMock(return_value=[extracted])
        entity_extractor.deduplicate_entity_nodes = AsyncMock(return_value=([extracted], {}))

        relationship_extractor = MagicMock()
        relationship_extractor.extract_from_entity_nodes = AsyncMock(return_value=[])
        mock_neo4j_client.find_node_by_uuid.return_value = {"name": "Episode"}

        with (
            patch.object(
                adapter,
                "_load_schema_context",
                AsyncMock(
                    return_value={
                        "entity_types_context": [],
                        "entity_type_id_to_name": {},
                        "edge_type_map": {},
                    }
                ),
            ),
            patch.object(adapter, "_get_entity_extractor", return_value=entity_extractor),
            patch.object(adapter, "_get_existing_entities", AsyncMock(return_value=[])),
            patch.object(
                adapter,
                "_get_relationship_extractor",
                return_value=relationship_extractor,
            ),
            patch.object(adapter, "_save_discovered_types", AsyncMock()),
            patch.object(adapter, "_update_episode_status", AsyncMock()),
        ):
            await adapter.process_episode(
                episode_uuid="episode-1",
                content="Ada founded a lab.",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
            )

        mock_neo4j_client.save_nodes_batch.assert_awaited_once()
        saved_nodes = mock_neo4j_client.save_nodes_batch.await_args.args[0]
        assert [node["uuid"] for node in saved_nodes] == ["new-ada"]
        assert saved_nodes[0]["labels"] == [
            "Entity",
            "Person",
            "Node",
        ]

    @pytest.mark.asyncio
    async def test_save_entity_relationship_merges_supporting_episodes(
        self,
        adapter,
        mock_neo4j_client,
    ):
        """Entity relationships should union episode support instead of overwriting it."""
        relationship = EntityEdge(
            uuid="rel-1",
            source_uuid="entity-a",
            target_uuid="entity-b",
            relationship_type="WORKS_AT",
            fact="Ada works at Lab",
            episodes=["episode-1"],
        )

        await adapter._save_entity_relationship(relationship)

        query = mock_neo4j_client.execute_query.await_args.args[0]
        assert "MERGE (from)-[r:WORKS_AT]->(to)" in query
        assert "r.episodes = reduce" in query

    @pytest.mark.asyncio
    async def test_save_discovered_types_redacts_persistence_exception_details(
        self,
        adapter,
        caplog,
    ):
        """Schema persistence failures should not write exception details to logs."""
        secret = "schema-persistence-secret-9753"
        entity = EntityNode(uuid="entity-1", name="Ada", entity_type="Person")

        with (
            patch(
                "src.infrastructure.adapters.secondary.schema.dynamic_schema."
                "save_discovered_types_batch",
                new_callable=AsyncMock,
            ) as save_batch,
            caplog.at_level(
                logging.WARNING,
                logger="src.infrastructure.graph.native_graph_adapter",
            ),
        ):
            save_batch.side_effect = RuntimeError(secret)
            await adapter._save_discovered_types(
                project_id="project-1",
                entities=[entity],
                relationships=[],
                existing_entity_types=set(),
            )

        save_batch.assert_awaited_once()
        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_get_existing_entities_redacts_query_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Entity lookup failures should not write backend details to logs."""
        secret = "existing-entity-query-secret-2468"
        mock_neo4j_client.execute_query.side_effect = RuntimeError(secret)

        with caplog.at_level(
            logging.WARNING,
            logger="src.infrastructure.graph.native_graph_adapter",
        ):
            result = await adapter._get_existing_entities(project_id="project-1")

        assert result == []
        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_get_existing_entities_redacts_parse_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Malformed entity records should not write record values to logs."""
        secret = "existing-entity-parse-secret-1357"
        mock_neo4j_client.execute_query.return_value = MagicMock(
            records=[
                {
                    "e": {
                        "uuid": "entity-1",
                        "name": "Ada",
                        "entity_type": "Person",
                        "created_at": secret,
                    }
                }
            ]
        )

        with caplog.at_level(
            logging.WARNING,
            logger="src.infrastructure.graph.native_graph_adapter",
        ):
            result = await adapter._get_existing_entities(project_id="project-1")

        assert result == []
        assert secret not in caplog.text
        assert "error_type=ValueError" in caplog.text


@pytest.mark.unit
class TestNativeGraphAdapterSearch:
    """Tests for search method."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, adapter):
        """Test search returns formatted results."""
        mock_search_result = HybridSearchResult(
            items=[
                SearchResultItem(
                    type="entity",
                    uuid="entity-1",
                    name="Test Entity",
                    summary="A test entity",
                    score=0.9,
                ),
                SearchResultItem(
                    type="episode",
                    uuid="episode-1",
                    content="Test content",
                    score=0.8,
                ),
            ],
            total_results=2,
        )

        with patch.object(adapter, "_get_hybrid_search") as mock_get_search:
            mock_search = MagicMock()
            mock_search.search = AsyncMock(return_value=mock_search_result)
            mock_get_search.return_value = mock_search

            results = await adapter.search("test query", project_id="proj-1", limit=10)

            assert len(results) == 2
            assert results[0]["type"] == "entity"
            assert results[0]["name"] == "Test Entity"

    @pytest.mark.asyncio
    async def test_search_failure_log_redacts_exception_details(self, adapter, caplog):
        """Search failures should propagate without writing exception details to logs."""
        secret = "search-secret-8642"

        with patch.object(adapter, "_get_hybrid_search") as mock_get_search:
            mock_search = MagicMock()
            mock_search.search = AsyncMock(side_effect=RuntimeError(secret))
            mock_get_search.return_value = mock_search

            with (
                caplog.at_level(
                    logging.ERROR,
                    logger="src.infrastructure.graph.native_graph_adapter",
                ),
                pytest.raises(RuntimeError, match=secret),
            ):
                await adapter.search("secret query", project_id="proj-1", limit=10)

        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
class TestNativeGraphAdapterGraphData:
    """Tests for graph data retrieval."""

    @pytest.mark.asyncio
    async def test_get_graph_data_failure_log_redacts_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Graph data failures should propagate without writing exception details to logs."""
        secret = "graph-data-secret-2468"
        mock_neo4j_client.execute_query.side_effect = RuntimeError(secret)

        with (
            caplog.at_level(
                logging.ERROR,
                logger="src.infrastructure.graph.native_graph_adapter",
            ),
            pytest.raises(RuntimeError, match=secret),
        ):
            await adapter.get_graph_data(project_id="project-1")

        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
class TestNativeGraphAdapterDeleteEpisode:
    """Tests for delete_episode methods."""

    @pytest.mark.asyncio
    async def test_delete_episode_by_name(self, adapter, mock_neo4j_client):
        """Test deleting episode by name."""
        mock_neo4j_client.execute_query.return_value = MagicMock()

        result = await adapter.delete_episode("test-episode")

        assert result is True
        mock_neo4j_client.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_episode_failure_log_redacts_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Delete failures should propagate without writing exception details to logs."""
        secret = "delete-episode-secret-9753"
        mock_neo4j_client.execute_query.side_effect = RuntimeError(secret)

        with (
            caplog.at_level(
                logging.ERROR,
                logger="src.infrastructure.graph.native_graph_adapter",
            ),
            pytest.raises(RuntimeError, match=secret),
        ):
            await adapter.delete_episode("episode-with-secret")

        assert secret not in caplog.text
        assert "episode-with-secret" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_episode_by_memory_id(self, adapter, mock_neo4j_client):
        """Test deleting episode by memory_id."""
        mock_neo4j_client.execute_query.return_value = MagicMock()

        result = await adapter.delete_episode_by_memory_id("memory-123")

        assert result is True
        queries = [call.args[0] for call in mock_neo4j_client.execute_query.await_args_list]
        assert any("MATCH (:Entity)-[r]->(:Entity)" in query for query in queries)
        assert not any("[r:RELATES_TO" in query for query in queries)

    @pytest.mark.asyncio
    async def test_delete_episode_by_memory_id_failure_log_redacts_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Memory-id delete failures should return False without writing details to logs."""
        secret = "memory-delete-secret-2468"
        mock_neo4j_client.execute_query.side_effect = RuntimeError(secret)

        with caplog.at_level(
            logging.WARNING,
            logger="src.infrastructure.graph.native_graph_adapter",
        ):
            result = await adapter.delete_episode_by_memory_id("memory-with-secret")

        assert result is False
        assert secret not in caplog.text
        assert "memory-with-secret" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
class TestNativeGraphAdapterRemoveEpisode:
    """Tests for remove_episode methods."""

    @pytest.mark.asyncio
    async def test_remove_episode(self, adapter, mock_neo4j_client):
        """Test removing episode with cleanup."""
        mock_neo4j_client.execute_query.return_value = MagicMock(
            summary=MagicMock(counters=MagicMock(relationships_deleted=0))
        )

        result = await adapter.remove_episode("episode-uuid-123")

        assert result is True
        assert mock_neo4j_client.execute_query.call_count >= 3

    @pytest.mark.asyncio
    async def test_remove_episode_failure_log_redacts_exception_details(
        self,
        adapter,
        mock_neo4j_client,
        caplog,
    ):
        """Remove failures should propagate without writing exception details to logs."""
        secret = "remove-episode-secret-8642"
        mock_neo4j_client.execute_query.side_effect = RuntimeError(secret)

        with (
            caplog.at_level(
                logging.ERROR,
                logger="src.infrastructure.graph.native_graph_adapter",
            ),
            pytest.raises(RuntimeError, match=secret),
        ):
            await adapter.remove_episode("episode-with-secret")

        assert secret not in caplog.text
        assert "episode-with-secret" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
class TestNativeGraphAdapterTypedPrimitives:
    """Contract-level checks for typed GraphStorePort primitives."""

    @pytest.mark.asyncio
    async def test_search_memories_accepts_port_argument_order(self, adapter):
        expected = [{"uuid": "memory-1"}]

        with patch.object(adapter, "search", AsyncMock(return_value=expected)) as search:
            result = await adapter.search_memories(
                "find memory",
                project_id="project-1",
                limit=4,
            )

        assert result == expected
        search.assert_awaited_once_with(
            query="find memory",
            project_id="project-1",
            limit=4,
        )

    @pytest.mark.asyncio
    async def test_related_entities_defaults_non_string_entity_type(
        self,
        adapter,
        mock_neo4j_client,
    ):
        mock_neo4j_client.execute_query.return_value = MagicMock(
            records=[
                {
                    "b": {
                        "uuid": "entity-1",
                        "name": "Entity",
                        "entity_type": None,
                    }
                }
            ]
        )

        result = await adapter.related_entities("source-1")

        assert result[0].entity_type == "Entity"

    @pytest.mark.asyncio
    async def test_count_nodes_uses_validated_label(self, adapter, mock_neo4j_client):
        mock_neo4j_client.execute_query.return_value = MagicMock(records=[{"total": 3}])

        result = await adapter.count_nodes(label="Entity")

        assert result == 3
        query = mock_neo4j_client.execute_query.await_args.args[0]
        assert "MATCH (n:Entity)" in query

    @pytest.mark.asyncio
    async def test_list_episodes_uses_validated_sort_field(
        self,
        adapter,
        mock_neo4j_client,
    ):
        mock_neo4j_client.execute_query.side_effect = [
            MagicMock(records=[{"total": 1}]),
            MagicMock(records=[{"props": {"uuid": "episode-1"}}]),
        ]

        result = await adapter.list_episodes(sort_by="created_at")

        assert result == {"episodes": [{"uuid": "episode-1"}], "total": 1}
        query = mock_neo4j_client.execute_query.await_args_list[1].args[0]
        assert "ORDER BY e.created_at DESC" in query

    @pytest.mark.asyncio
    async def test_count_scoped_nodes_uses_validated_label(
        self,
        adapter,
        mock_neo4j_client,
    ):
        mock_neo4j_client.execute_query.return_value = MagicMock(records=[{"count": 2}])

        result = await adapter.count_scoped_nodes("Community", project_id="project-1")

        assert result == 2
        query = mock_neo4j_client.execute_query.await_args.args[0]
        assert "MATCH (n:Community)" in query
