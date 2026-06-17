"""Unit tests for data_export, maintenance, and tasks routers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.data_export import (
    _resolve_graph_export_scope,
    _resolve_tenant_scope,
    cleanup_data,
    export_data,
    get_graph_stats,
)
from src.infrastructure.adapters.primary.web.routers.maintenance import (
    check_embedding_dimensions,
    deduplicate_entities,
    get_embedding_status,
    get_maintenance_status,
    get_native_embedding_status,
    incremental_refresh,
    invalidate_stale_edges,
    migrate_embeddings,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    UserProject,
    UserTenant,
)


def _neo4j_result(records: list[dict]) -> Mock:
    return Mock(records=records)


@pytest.mark.unit
class TestDataExportRouter:
    """Test cases for data_export router endpoints."""

    @pytest.mark.asyncio
    async def test_resolve_tenant_scope_defaults_to_user_tenant(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Non-admin graph operations are scoped to the caller's tenant."""
        tenant_id = await _resolve_tenant_scope(None, test_db, test_user)

        assert tenant_id == test_project_db.tenant_id

    @pytest.mark.asyncio
    async def test_resolve_tenant_scope_rejects_non_member(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ):
        """Users cannot request graph data for tenants they do not belong to."""
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_tenant_scope(test_project_db.tenant_id, test_db, another_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_resolve_tenant_scope_requires_admin_for_cleanup_execution(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ):
        """Actual cleanup requires tenant admin/owner membership."""
        test_db.add(
            UserTenant(
                id=str(uuid4()),
                user_id=another_user.id,
                tenant_id=test_project_db.tenant_id,
                role="member",
                permissions={"read": True},
            )
        )
        await test_db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await _resolve_tenant_scope(
                test_project_db.tenant_id,
                test_db,
                another_user,
                require_admin=True,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_resolve_graph_export_scope_rejects_non_member_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ):
        """Project-scoped graph exports require membership in that project."""
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_graph_export_scope(
                None,
                test_project_db.id,
                test_db,
                another_user,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_export_data_all(self, client, mock_graphiti_client):
        """Test exporting all data types."""
        # Mock responses
        mock_result = Mock()
        mock_result.records = []
        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.post(
            "/api/v1/data/export",
            json={
                "include_episodes": True,
                "include_entities": True,
                "include_relationships": True,
                "include_communities": True,
            },
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "exported_at" in data
        assert "episodes" in data
        assert "entities" in data
        assert "relationships" in data
        assert "communities" in data

    @pytest.mark.asyncio
    async def test_export_data_filter_by_tenant(self, client, mock_graphiti_client):
        """Test exporting data with tenant filter."""
        # Mock response
        mock_result = Mock()
        mock_result.records = []
        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.post(
            "/api/v1/data/export",
            json={"tenant_id": "tenant_123", "include_episodes": True},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tenant_id"] == "tenant_123"

    @pytest.mark.asyncio
    async def test_export_data_relationships_filter_both_tenants(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Relationship exports cannot leak edges that cross tenant boundaries."""
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([]),
            ]
        )

        await export_data(
            tenant_id=test_project_db.tenant_id,
            project_id=None,
            include_episodes=False,
            include_entities=False,
            include_relationships=True,
            include_communities=False,
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        rel_query = graphiti_client.driver.execute_query.await_args.args[0]
        assert "a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id" in rel_query

    @pytest.mark.asyncio
    async def test_export_data_filters_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Project exports only include nodes and relationships inside the requested project."""
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([]),
                _neo4j_result([]),
                _neo4j_result([]),
                _neo4j_result([]),
            ]
        )

        data = await export_data(
            tenant_id=None,
            project_id=test_project_db.id,
            include_episodes=True,
            include_entities=True,
            include_relationships=True,
            include_communities=True,
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        episode_query = graphiti_client.driver.execute_query.await_args_list[0].args[0]
        entity_query = graphiti_client.driver.execute_query.await_args_list[1].args[0]
        rel_query = graphiti_client.driver.execute_query.await_args_list[2].args[0]
        community_query = graphiti_client.driver.execute_query.await_args_list[3].args[0]
        rel_kwargs = graphiti_client.driver.execute_query.await_args_list[2].kwargs

        assert data["project_id"] == test_project_db.id
        assert "e.project_id = $project_id" in episode_query
        assert "e.project_id = $project_id" in entity_query
        assert "project_episode.project_id = $project_id" in entity_query
        assert "a.project_id = $project_id" in rel_query
        assert "b.project_id = $project_id" in rel_query
        assert "project_episode.project_id = $project_id" in rel_query
        assert "c.project_id = $project_id" in community_query
        assert rel_kwargs["project_id"] == test_project_db.id

    @pytest.mark.asyncio
    async def test_graph_stats_relationships_filter_both_tenants(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Relationship counts only include edges fully inside the tenant scope."""
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"count": 1}]),
                _neo4j_result([{"count": 2}]),
                _neo4j_result([{"count": 3}]),
                _neo4j_result([{"count": 4}]),
            ]
        )

        stats = await get_graph_stats(
            tenant_id=test_project_db.tenant_id,
            project_id=None,
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        rel_query = graphiti_client.driver.execute_query.await_args_list[3].args[0]
        assert "a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id" in rel_query
        assert stats["relationships"] == 4

    @pytest.mark.asyncio
    async def test_graph_stats_filters_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Graph stats count only nodes and edges inside the requested project."""
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"count": 1}]),
                _neo4j_result([{"count": 2}]),
                _neo4j_result([{"count": 3}]),
                _neo4j_result([{"count": 4}]),
            ]
        )

        stats = await get_graph_stats(
            tenant_id=None,
            project_id=test_project_db.id,
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        entity_query = graphiti_client.driver.execute_query.await_args_list[0].args[0]
        rel_query = graphiti_client.driver.execute_query.await_args_list[3].args[0]
        rel_kwargs = graphiti_client.driver.execute_query.await_args_list[3].kwargs

        assert "e.project_id = $project_id" in entity_query
        assert "project_episode.project_id = $project_id" in entity_query
        assert "a.project_id = $project_id" in rel_query
        assert "b.project_id = $project_id" in rel_query
        assert "project_episode.project_id = $project_id" in rel_query
        assert rel_kwargs["project_id"] == test_project_db.id
        assert stats["project_id"] == test_project_db.id
        assert stats["relationships"] == 4

    @pytest.mark.asyncio
    async def test_export_data_failure_returns_error(self, client, mock_graphiti_client):
        """Test export failures are not reported as empty successful exports."""
        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(
            side_effect=RuntimeError("neo4j down")
        )

        response = client.post(
            "/api/v1/data/export",
            json={"include_episodes": True},
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to export data"

    @pytest.mark.asyncio
    async def test_get_graph_stats(self, client, mock_graphiti_client):
        """Test getting graph statistics."""

        # Mock count responses
        def mock_query(query, **kwargs):
            result = Mock()
            if "Entity" in query:
                # records[0]["count"] needs to work
                record = Mock()
                record.__getitem__ = lambda self, key: 100
                result.records = [record]
            elif "Episodic" in query:
                record = Mock()
                record.__getitem__ = lambda self, key: 50
                result.records = [record]
            elif "Community" in query:
                record = Mock()
                record.__getitem__ = lambda self, key: 10
                result.records = [record]
            else:
                record = Mock()
                record.__getitem__ = lambda self, key: 200
                result.records = [record]
            return result

        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(side_effect=mock_query)

        # Make request
        response = client.get("/api/v1/data/stats")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "entities" in data
        assert "episodes" in data
        assert "communities" in data
        assert "relationships" in data
        assert "total_nodes" in data

    @pytest.mark.asyncio
    async def test_cleanup_data_dry_run(self, client, mock_graphiti_client):
        """Test data cleanup in dry run mode."""
        # Mock count response - use dict for record to support subscript access
        count_result = Mock()
        count_result.records = [{"count": 25}]

        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=count_result)

        # Make request
        response = client.post(
            "/api/v1/data/cleanup?dry_run=true&older_than_days=90",
            json={},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["dry_run"] is True
        assert data["would_delete"] == 25
        assert "cutoff_date" in data

    @pytest.mark.asyncio
    async def test_cleanup_data_execute(self, client, mock_graphiti_client):
        """Test actual data cleanup execution."""
        # Mock responses - use dicts for records to support subscript access
        responses = [
            Mock(records=[{"count": 10}]),  # Count query
            Mock(records=[{"deleted": 10}]),  # Delete query
        ]

        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(side_effect=responses)

        # Make request
        response = client.post(
            "/api/v1/data/cleanup?dry_run=false&older_than_days=30",
            json={},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["dry_run"] is False
        assert data["deleted"] == 10

    @pytest.mark.asyncio
    async def test_cleanup_data_dry_run_filters_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Cleanup dry-runs count only episodes inside the requested project."""
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(return_value=_neo4j_result([{"count": 5}]))

        response = await cleanup_data(
            dry_run=True,
            older_than_days=30,
            tenant_id=None,
            project_id=test_project_db.id,
            body=None,
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        query = graphiti_client.driver.execute_query.await_args.args[0]
        query_kwargs = graphiti_client.driver.execute_query.await_args.kwargs
        assert "e.project_id = $project_id" in query
        assert query_kwargs["project_id"] == test_project_db.id
        assert response["project_id"] == test_project_db.id
        assert response["would_delete"] == 5

    @pytest.mark.asyncio
    async def test_cleanup_data_execute_filters_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Cleanup execution deletes only episodes inside the requested project."""
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"count": 5}]),
                _neo4j_result([{"deleted": 5}]),
            ]
        )

        response = await cleanup_data(
            dry_run=False,
            older_than_days=30,
            tenant_id=None,
            project_id=test_project_db.id,
            body=None,
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        delete_query = graphiti_client.driver.execute_query.await_args_list[1].args[0]
        delete_kwargs = graphiti_client.driver.execute_query.await_args_list[1].kwargs
        assert "e.project_id = $project_id" in delete_query
        assert delete_kwargs["project_id"] == test_project_db.id
        assert response["project_id"] == test_project_db.id
        assert response["deleted"] == 5

    @pytest.mark.asyncio
    async def test_cleanup_data_rejects_non_positive_body_days(
        self,
        test_db: AsyncSession,
        test_user: User,
    ):
        """Body overrides cannot bypass the positive older_than_days constraint."""
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await cleanup_data(
                dry_run=True,
                older_than_days=30,
                tenant_id=None,
                project_id=None,
                body={"older_than_days": 0},
                current_user=test_user,
                db=test_db,
                graphiti_client=graphiti_client,
            )

        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        graphiti_client.driver.execute_query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_data_rejects_invalid_body_dry_run(
        self,
        test_db: AsyncSession,
        test_user: User,
    ):
        """Body overrides must use a parseable dry_run boolean."""
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await cleanup_data(
                dry_run=True,
                older_than_days=30,
                tenant_id=None,
                project_id=None,
                body={"dry_run": "maybe"},
                current_user=test_user,
                db=test_db,
                graphiti_client=graphiti_client,
            )

        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        graphiti_client.driver.execute_query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_data_failure_returns_sanitized_error(self, client, mock_graphiti_client):
        """Cleanup failures do not expose internal exception text."""
        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(
            side_effect=RuntimeError("neo4j credential leaked in stack")
        )

        response = client.post(
            "/api/v1/data/cleanup?dry_run=true&older_than_days=90",
            json={},
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to cleanup data"


@pytest.mark.unit
class TestMaintenanceRouter:
    """Test cases for maintenance router endpoints."""

    @pytest.mark.asyncio
    async def test_deduplicate_entities_dry_run(self, client, mock_neo4j_client):
        """Test entity deduplication in dry run mode."""
        # Mock response with duplicates
        mock_records = [
            {
                "name": "Duplicate Entity",
                "entities": [{"uuid": "ent_1"}, {"uuid": "ent_2"}],
            }
        ]

        mock_result = Mock()
        mock_result.records = mock_records
        mock_neo4j_client.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.post(
            "/api/v1/maintenance/deduplicate",
            json={"similarity_threshold": 0.9, "dry_run": True},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["dry_run"] is True
        assert data["duplicates_found"] == 1
        assert "duplicate_groups" in data

    @pytest.mark.asyncio
    async def test_incremental_refresh_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
        mock_workflow_engine,
    ):
        """Incremental refresh cannot submit work for an unjoined project."""
        neo4j_client = Mock()

        with pytest.raises(HTTPException) as exc_info:
            await incremental_refresh(
                episode_uuids=None,
                rebuild_communities=False,
                project_id="not-a-member",
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
                workflow_engine=mock_workflow_engine,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        mock_workflow_engine.start_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deduplicate_entities_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
        mock_workflow_engine,
    ):
        """Users cannot scan duplicate entities for projects they cannot access."""
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await deduplicate_entities(
                similarity_threshold=0.9,
                dry_run=True,
                project_id="not-a-member",
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
                workflow_engine=mock_workflow_engine,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        neo4j_client.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduplicate_entities_dry_run_scopes_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        mock_workflow_engine,
    ):
        """Duplicate detection defaults to the caller's project memberships."""
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            return_value=_neo4j_result(
                [{"name": "Duplicate Entity", "entities": [{"uuid": "a"}, {"uuid": "b"}]}]
            )
        )

        response = await deduplicate_entities(
            similarity_threshold=0.9,
            dry_run=True,
            project_id=None,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
            workflow_engine=mock_workflow_engine,
        )

        query = neo4j_client.execute_query.await_args.args[0]
        query_kwargs = neo4j_client.execute_query.await_args.kwargs
        assert "e.project_id IN $project_ids" in query
        assert query_kwargs["project_ids"] == [test_project_db.id]
        assert response["duplicates_found"] == 1

    @pytest.mark.asyncio
    async def test_invalidate_stale_edges_scopes_query_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Stale edge scans are limited to relationships within accessible projects."""
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            return_value=_neo4j_result([{"rel_type": "RELATES_TO", "count": 2}])
        )

        response = await invalidate_stale_edges(
            days_since_update=30,
            dry_run=True,
            project_id=None,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        query = neo4j_client.execute_query.await_args.args[0]
        query_kwargs = neo4j_client.execute_query.await_args.kwargs
        assert "a.project_id IN $project_ids AND b.project_id IN $project_ids" in query
        assert query_kwargs["project_ids"] == [test_project_db.id]
        assert response["stale_edges_found"] == 2

    @pytest.mark.asyncio
    async def test_invalidate_stale_edges_delete_uses_project_scope(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Deleting stale edges uses the same project filter as the dry-run scan."""
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"rel_type": "RELATES_TO", "count": 2}]),
                _neo4j_result([{"deleted": 2}]),
            ]
        )

        response = await invalidate_stale_edges(
            days_since_update=30,
            dry_run=False,
            project_id=None,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        delete_query = neo4j_client.execute_query.await_args_list[1].args[0]
        delete_kwargs = neo4j_client.execute_query.await_args_list[1].kwargs
        assert "a.project_id IN $project_ids AND b.project_id IN $project_ids" in delete_query
        assert delete_kwargs["project_ids"] == [test_project_db.id]
        assert response["deleted"] == 2

    @pytest.mark.asyncio
    async def test_get_maintenance_status_scopes_counts_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Maintenance status only counts graph data in the caller's projects."""
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"count": 10}]),
                _neo4j_result([{"count": 5}]),
                _neo4j_result([{"count": 1}]),
                _neo4j_result([{"count": 0}]),
            ]
        )

        response = await get_maintenance_status(
            project_id=None,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        for call in neo4j_client.execute_query.await_args_list:
            assert call.kwargs["project_ids"] == [test_project_db.id]
        assert (
            "n.project_id IN $project_ids" in neo4j_client.execute_query.await_args_list[0].args[0]
        )
        assert (
            "e.project_id IN $project_ids" in neo4j_client.execute_query.await_args_list[3].args[0]
        )
        assert response["stats"] == {
            "entities": 10,
            "episodes": 5,
            "communities": 1,
            "old_episodes": 0,
        }

    @pytest.mark.asyncio
    async def test_get_maintenance_status_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
    ):
        """Project-specific status requires project membership."""
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_maintenance_status(
                project_id="not-a-member",
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        neo4j_client.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_embedding_status_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
    ):
        """Embedding status cannot be requested for projects outside the caller's scope."""
        graphiti_client = Mock()

        with pytest.raises(HTTPException) as exc_info:
            await get_embedding_status(
                project_id="not-a-member",
                current_user=test_user,
                db=test_db,
                graphiti_client=graphiti_client,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_get_embedding_status_uses_local_dimension_queries(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Graphiti embedding status no longer imports a missing helper module."""

        class ProviderFactory:
            async def resolve_provider(self, tenant_id: str):
                return SimpleNamespace(provider="openai")

        monkeypatch.setattr(
            "src.infrastructure.llm.provider_factory.get_ai_service_factory",
            lambda: ProviderFactory(),
        )

        driver = Mock()
        driver.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"dim": 1536}]),
                _neo4j_result([{"missing_count": 3}]),
            ]
        )
        graphiti_client = SimpleNamespace(
            embedder=SimpleNamespace(embedding_dim=1536),
            driver=driver,
        )

        response = await get_embedding_status(
            project_id=None,
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        first_query = driver.execute_query.await_args_list[0].args[0]
        second_query = driver.execute_query.await_args_list[1].args[0]
        assert "n.project_id IN $project_ids" in first_query
        assert "n.project_id IN $project_ids" in second_query
        assert driver.execute_query.await_args_list[0].kwargs["project_ids"] == [test_project_db.id]
        assert response["existing_dimension"] == 1536
        assert response["missing_embeddings"] == 3

    @pytest.mark.asyncio
    async def test_check_embedding_dimensions_uses_local_detector(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Dimension checks use scoped local Cypher instead of a missing module."""
        driver = Mock()
        driver.execute_query = AsyncMock(
            return_value=_neo4j_result(
                [
                    {"dim": 1536, "count": 2},
                    {"dim": 1024, "count": 1},
                ]
            )
        )
        graphiti_client = SimpleNamespace(
            embedder=SimpleNamespace(embedding_dim=1536),
            driver=driver,
        )

        response = await check_embedding_dimensions(
            project_id=None,
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        query = driver.execute_query.await_args.args[0]
        query_kwargs = driver.execute_query.await_args.kwargs
        assert "n.project_id = $project_id" in query
        assert query_kwargs["project_id"] == test_project_db.id
        assert response["has_mixed_dimensions"] is True
        assert response["action_required"] == "clear_mixed"

    @pytest.mark.asyncio
    async def test_get_native_embedding_status_scopes_distribution_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Native embedding distribution scans only the caller's projects."""

        class ProviderFactory:
            async def resolve_provider(self, tenant_id: str):
                return SimpleNamespace(provider="openai")

        monkeypatch.setattr(
            "src.infrastructure.llm.provider_factory.get_ai_service_factory",
            lambda: ProviderFactory(),
        )

        neo4j_client = Mock()
        neo4j_client.get_vector_index_dimension = AsyncMock(return_value=1536)
        neo4j_client.execute_query = AsyncMock(
            return_value=_neo4j_result([{"dim": 1536, "total": 4}])
        )

        response = await get_native_embedding_status(
            project_id=None,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        query = neo4j_client.execute_query.await_args.args[0]
        query_kwargs = neo4j_client.execute_query.await_args.kwargs
        assert "n.project_id IN $project_ids" in query
        assert query_kwargs["project_ids"] == [test_project_db.id]
        assert response["total_embeddings"] == 4

    @pytest.mark.asyncio
    async def test_migrate_embeddings_dry_run_without_records_does_not_clear(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Dry-run migration returns a report even when no embeddings exist."""
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(return_value=_neo4j_result([]))
        neo4j_client.create_vector_index = AsyncMock()

        response = await migrate_embeddings(
            target_model="openai",
            project_id=None,
            dry_run=True,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        query = neo4j_client.execute_query.await_args.args[0]
        query_kwargs = neo4j_client.execute_query.await_args.kwargs
        assert "n.project_id IN $project_ids" in query
        assert query_kwargs["project_ids"] == [test_project_db.id]
        assert response["dry_run"] is True
        assert response["total_embeddings"] == 0
        neo4j_client.create_vector_index.assert_not_called()

    @pytest.mark.asyncio
    async def test_migrate_embeddings_execute_requires_single_project_scope(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Executing migration across multiple accessible projects requires a project_id."""
        second_project = Project(
            id="second-project",
            tenant_id=test_project_db.tenant_id,
            name="Second Project",
            description="Another project",
            owner_id=test_user.id,
            memory_rules={},
            graph_config={},
        )
        test_db.add(second_project)
        test_db.add(
            UserProject(
                id=str(uuid4()),
                user_id=test_user.id,
                project_id=second_project.id,
                role="owner",
            )
        )
        await test_db.commit()

        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(return_value=_neo4j_result([]))
        neo4j_client.create_vector_index = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await migrate_embeddings(
                target_model="openai",
                project_id=None,
                dry_run=False,
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        neo4j_client.create_vector_index.assert_not_called()


@pytest.mark.unit
class TestTasksRouter:
    """Test cases for tasks router endpoints."""

    @pytest.mark.asyncio
    async def test_get_task_stats(self, client, test_db):
        """Test getting task statistics."""
        # Make request
        response = client.get("/api/v1/tasks/stats")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "total" in data
        assert "pending" in data
        assert "processing" in data
        assert "completed" in data
        assert "failed" in data
        assert "throughput_per_minute" in data
        assert "error_rate" in data
