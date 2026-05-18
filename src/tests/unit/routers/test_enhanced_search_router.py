"""Unit tests for enhanced search router scope and query safety."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.enhanced_search import (
    memory_search,
    search_advanced,
    search_by_community,
    search_by_graph_traversal,
    search_temporal,
    search_with_facets,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User


def _neo4j_result(records: list[dict]) -> Mock:
    return Mock(records=records)


class FakeNeo4jDateTime:
    def isoformat(self) -> str:
        return "2026-05-17T12:34:56+00:00"


@pytest.mark.unit
class TestEnhancedSearchRouter:
    @pytest.mark.asyncio
    async def test_graph_traversal_uses_parameterized_relationship_types(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                _neo4j_result([]),
            ]
        )

        response = await search_by_graph_traversal(
            start_entity_uuid="entity-1",
            max_depth=2,
            relationship_types=['RELATES_TO") MATCH (n) DETACH DELETE n //'],
            limit=50,
            tenant_id=None,
            project_id=None,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response == {"results": [], "total": 0, "search_type": "graph_traversal"}
        traversal_query = neo4j_client.execute_query.await_args_list[1].args[0]
        traversal_kwargs = neo4j_client.execute_query.await_args_list[1].kwargs
        assert "type(rel) IN $relationship_types" in traversal_query
        assert "DETACH DELETE" not in traversal_query
        assert traversal_kwargs["relationship_types"] == [
            'RELATES_TO") MATCH (n) DETACH DELETE n //'
        ]
        assert traversal_kwargs["project_id"] == test_project_db.id

    @pytest.mark.asyncio
    async def test_graph_traversal_serializes_neo4j_datetime_values(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                _neo4j_result(
                    [
                        {
                            "props": {
                                "uuid": "entity-2",
                                "name": "Related Entity",
                                "summary": "A related node",
                                "created_at": FakeNeo4jDateTime(),
                            },
                            "labels": ["Entity", "Organization"],
                        }
                    ]
                ),
            ]
        )

        response = await search_by_graph_traversal(
            start_entity_uuid="entity-1",
            max_depth=2,
            relationship_types=None,
            limit=50,
            tenant_id=None,
            project_id=None,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response["total"] == 1
        result = response["results"][0]
        assert result["created_at"] == "2026-05-17T12:34:56+00:00"
        assert result["metadata"]["created_at"] == "2026-05-17T12:34:56+00:00"

    @pytest.mark.asyncio
    async def test_graph_traversal_rejects_unjoined_start_project(
        self,
        test_db: AsyncSession,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            return_value=_neo4j_result([{"props": {"project_id": "not-a-member"}}])
        )

        with pytest.raises(HTTPException) as exc_info:
            await search_by_graph_traversal(
                start_entity_uuid="entity-1",
                max_depth=2,
                relationship_types=None,
                limit=50,
                tenant_id=None,
                project_id=None,
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert neo4j_client.execute_query.await_count == 1

    @pytest.mark.asyncio
    async def test_community_search_filters_entities_and_episodes_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                _neo4j_result([]),
                _neo4j_result([]),
            ]
        )

        response = await search_by_community(
            community_uuid="community-1",
            limit=50,
            include_episodes=True,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response == {"results": [], "total": 0, "search_type": "community"}
        entity_query = neo4j_client.execute_query.await_args_list[1].args[0]
        episode_query = neo4j_client.execute_query.await_args_list[2].args[0]
        assert "e.project_id = $project_id" in entity_query
        assert "ep.project_id = $project_id" in episode_query
        assert neo4j_client.execute_query.await_args_list[1].kwargs["project_id"] == (
            test_project_db.id
        )

    @pytest.mark.asyncio
    async def test_temporal_search_without_project_is_scoped_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(return_value=_neo4j_result([]))

        response = await search_temporal(
            query="memory",
            since=None,
            until=None,
            limit=50,
            tenant_id=None,
            project_id=None,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response["total"] == 0
        query = neo4j_client.execute_query.await_args.args[0]
        kwargs = neo4j_client.execute_query.await_args.kwargs
        assert "e.project_id IN $project_ids" in query
        assert kwargs["project_ids"] == [test_project_db.id]

    @pytest.mark.asyncio
    async def test_faceted_search_without_project_is_scoped_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(return_value=_neo4j_result([]))

        response = await search_with_facets(
            query="entity",
            entity_types=None,
            tags=None,
            since=None,
            limit=50,
            offset=0,
            tenant_id=None,
            project_id=None,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response["total"] == 0
        query = neo4j_client.execute_query.await_args.args[0]
        kwargs = neo4j_client.execute_query.await_args.kwargs
        assert "e.project_id IN $project_ids" in query
        assert kwargs["project_ids"] == [test_project_db.id]

    @pytest.mark.asyncio
    async def test_advanced_search_without_project_fans_out_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graph_service = Mock()
        graph_service.search = AsyncMock(
            return_value=[{"type": "entity", "uuid": "entity-1", "name": "Entity"}]
        )

        response = await search_advanced(
            query="entity",
            strategy="COMBINED_HYBRID_SEARCH_RRF",
            focal_node_uuid=None,
            reranker=None,
            limit=10,
            tenant_id=None,
            project_id=None,
            since=None,
            current_user=test_user,
            db=test_db,
            graph_service=graph_service,
        )

        assert response["total"] == 1
        graph_service.search.assert_awaited_once_with(
            query="entity",
            project_id=test_project_db.id,
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_memory_search_does_not_treat_tenant_id_as_project_id(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graph_service = Mock()
        graph_service.search = AsyncMock(return_value=[])

        await memory_search(
            {"query": "memory", "tenant_id": "spoofed-tenant", "limit": 10},
            current_user=test_user,
            db=test_db,
            graph_service=graph_service,
        )

        graph_service.search.assert_awaited_once_with(
            query="memory",
            project_id=test_project_db.id,
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_advanced_search_failure_returns_sanitized_error(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graph_service = Mock()
        graph_service.search = AsyncMock(side_effect=RuntimeError("neo4j password leaked"))

        with pytest.raises(HTTPException) as exc_info:
            await search_advanced(
                query="entity",
                strategy="COMBINED_HYBRID_SEARCH_RRF",
                focal_node_uuid=None,
                reranker=None,
                limit=10,
                tenant_id=None,
                project_id=test_project_db.id,
                since=None,
                current_user=test_user,
                db=test_db,
                graph_service=graph_service,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Advanced search failed"

    @pytest.mark.asyncio
    async def test_graph_traversal_failure_returns_sanitized_error(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                RuntimeError("cypher secret leaked"),
            ]
        )

        with pytest.raises(HTTPException) as exc_info:
            await search_by_graph_traversal(
                start_entity_uuid="entity-1",
                max_depth=2,
                relationship_types=None,
                limit=50,
                tenant_id=None,
                project_id=None,
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Graph traversal search failed"

    @pytest.mark.asyncio
    async def test_community_search_failure_returns_sanitized_error(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                RuntimeError("internal community query failed"),
            ]
        )

        with pytest.raises(HTTPException) as exc_info:
            await search_by_community(
                community_uuid="community-1",
                limit=50,
                include_episodes=False,
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Community search failed"

    @pytest.mark.asyncio
    async def test_temporal_search_failure_returns_sanitized_error(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(side_effect=RuntimeError("internal time error"))

        with pytest.raises(HTTPException) as exc_info:
            await search_temporal(
                query="memory",
                since=None,
                until=None,
                limit=50,
                tenant_id=None,
                project_id=None,
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Temporal search failed"

    @pytest.mark.asyncio
    async def test_faceted_search_failure_returns_sanitized_error(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(side_effect=RuntimeError("internal facet error"))

        with pytest.raises(HTTPException) as exc_info:
            await search_with_facets(
                query="entity",
                entity_types=None,
                tags=None,
                since=None,
                limit=50,
                offset=0,
                tenant_id=None,
                project_id=None,
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Faceted search failed"

    @pytest.mark.asyncio
    async def test_memory_search_failure_returns_sanitized_error(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graph_service = Mock()
        graph_service.search = AsyncMock(side_effect=RuntimeError("internal memory error"))

        with pytest.raises(HTTPException) as exc_info:
            await memory_search(
                {"query": "memory", "project_id": test_project_db.id, "limit": 10},
                current_user=test_user,
                db=test_db,
                graph_service=graph_service,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Search failed"
