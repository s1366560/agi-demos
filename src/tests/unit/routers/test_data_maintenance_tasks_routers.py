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
        """Test exporting all data types delegates to the store's data_export."""
        from src.domain.model.graph.dtos import GraphExportDTO

        captured = {}

        async def _capture(**kwargs):
            captured.update(kwargs)
            return GraphExportDTO(
                exported_at="t",
                tenant_id=kwargs.get("tenant_id"),
                project_id=kwargs.get("project_id"),
            )

        mock_graphiti_client.data_export = AsyncMock(side_effect=_capture)

        response = client.post(
            "/api/v1/data/export",
            json={
                "include_episodes": True,
                "include_entities": True,
                "include_relationships": True,
                "include_communities": True,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "exported_at" in data
        assert "episodes" in data
        assert "entities" in data
        assert "relationships" in data
        assert "communities" in data
        assert captured["include_episodes"] is True
        assert captured["include_relationships"] is True

    @pytest.mark.asyncio
    async def test_export_data_filter_by_tenant(self, client, mock_graphiti_client):
        """Test exporting data with tenant filter forwards tenant_id to the store."""
        from src.domain.model.graph.dtos import GraphExportDTO

        captured = {}

        async def _capture(**kwargs):
            captured.update(kwargs)
            return GraphExportDTO(
                exported_at="t", tenant_id=kwargs.get("tenant_id"), project_id=None
            )

        mock_graphiti_client.data_export = AsyncMock(side_effect=_capture)

        response = client.post(
            "/api/v1/data/export",
            json={"tenant_id": "tenant_123", "include_episodes": True},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["tenant_id"] == "tenant_123"
        assert captured["tenant_id"] is not None

    @pytest.mark.asyncio
    async def test_export_data_filters_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Project exports forward the resolved project_id to the store primitive."""
        from src.domain.model.graph.dtos import GraphExportDTO

        graph_store = Mock()
        captured: dict = {}

        async def _capture(**kwargs):
            captured.update(kwargs)
            return GraphExportDTO(
                exported_at="t", tenant_id=None, project_id=kwargs.get("project_id")
            )

        graph_store.data_export = AsyncMock(side_effect=_capture)

        data = await export_data(
            tenant_id=None,
            project_id=test_project_db.id,
            include_episodes=True,
            include_entities=True,
            include_relationships=True,
            include_communities=True,
            current_user=test_user,
            db=test_db,
            graph_store=graph_store,
        )

        assert data["project_id"] == test_project_db.id
        assert captured["project_id"] == test_project_db.id
        assert captured["include_entities"] is True

    @pytest.mark.asyncio
    async def test_graph_stats_relationships_filter_both_tenants(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Tenant-scoped stats forward tenant_id to the store."""
        graph_store = Mock()
        captured: dict = {}

        async def _capture(**kwargs):
            captured.update(kwargs)
            return {
                "entities": 1,
                "episodes": 2,
                "communities": 3,
                "relationships": 4,
                "total_nodes": 6,
            }

        graph_store.count_stats = AsyncMock(side_effect=_capture)

        stats = await get_graph_stats(
            tenant_id=test_project_db.tenant_id,
            project_id=None,
            current_user=test_user,
            db=test_db,
            graph_store=graph_store,
        )

        assert captured["tenant_id"] == test_project_db.tenant_id
        assert stats["relationships"] == 4

    @pytest.mark.asyncio
    async def test_graph_stats_filters_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Graph stats forward the resolved project_id to count_stats."""
        graph_store = Mock()
        captured: dict = {}

        async def _capture(**kwargs):
            captured.update(kwargs)
            return {
                "entities": 1,
                "episodes": 2,
                "communities": 3,
                "relationships": 4,
                "total_nodes": 6,
            }

        graph_store.count_stats = AsyncMock(side_effect=_capture)

        stats = await get_graph_stats(
            tenant_id=None,
            project_id=test_project_db.id,
            current_user=test_user,
            db=test_db,
            graph_store=graph_store,
        )

        assert captured["project_id"] == test_project_db.id
        assert stats["project_id"] == test_project_db.id
        assert stats["relationships"] == 4
        assert stats["total_nodes"] == 6

    @pytest.mark.asyncio
    async def test_export_data_failure_returns_error(self, client, mock_graphiti_client):
        """Test export failures surface a sanitized error, not the store exception."""
        mock_graphiti_client.data_export = AsyncMock(side_effect=RuntimeError("neo4j down"))

        response = client.post(
            "/api/v1/data/export",
            json={"include_episodes": True},
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to export data"

    @pytest.mark.asyncio
    async def test_get_graph_stats(self, client, mock_graphiti_client):
        """Test getting graph statistics returns the store's counts."""
        mock_graphiti_client.count_stats = AsyncMock(
            return_value={
                "entities": 100,
                "episodes": 50,
                "communities": 10,
                "relationships": 200,
                "total_nodes": 160,
            }
        )

        response = client.get("/api/v1/data/stats")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["entities"] == 100
        assert data["episodes"] == 50
        assert data["communities"] == 10
        assert data["relationships"] == 200
        assert data["total_nodes"] == 160

    @pytest.mark.asyncio
    async def test_cleanup_data_dry_run(self, client, mock_graphiti_client):
        """Dry-run cleanup counts via count_episodes_by_age without deleting."""
        mock_graphiti_client.count_episodes_by_age = AsyncMock(return_value=25)
        mock_graphiti_client.delete_episodes_by_age = AsyncMock(return_value=0)

        response = client.post(
            "/api/v1/data/cleanup?dry_run=true&older_than_days=90",
            json={},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["dry_run"] is True
        assert data["would_delete"] == 25
        assert "cutoff_date" in data
        mock_graphiti_client.delete_episodes_by_age.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_data_execute(self, client, mock_graphiti_client):
        """Actual cleanup deletes via delete_episodes_by_age."""
        mock_graphiti_client.count_episodes_by_age = AsyncMock(return_value=0)
        mock_graphiti_client.delete_episodes_by_age = AsyncMock(return_value=10)

        response = client.post(
            "/api/v1/data/cleanup?dry_run=false&older_than_days=30",
            json={},
        )

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
        """Cleanup dry-run forwards the resolved project_id to the store."""
        graph_store = Mock()
        captured: dict = {}

        async def _count(**kwargs):
            captured.update(kwargs)
            return 5

        graph_store.count_episodes_by_age = AsyncMock(side_effect=_count)
        graph_store.delete_episodes_by_age = AsyncMock(return_value=0)

        response = await cleanup_data(
            dry_run=True,
            older_than_days=30,
            tenant_id=None,
            project_id=test_project_db.id,
            body=None,
            current_user=test_user,
            db=test_db,
            graph_store=graph_store,
        )

        assert captured["project_id"] == test_project_db.id
        assert response["project_id"] == test_project_db.id
        assert response["would_delete"] == 5

    @pytest.mark.asyncio
    async def test_cleanup_data_execute_filters_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Cleanup execution forwards the resolved project_id to the store."""
        graph_store = Mock()
        captured: dict = {}

        async def _delete(**kwargs):
            captured.update(kwargs)
            return 5

        graph_store.count_episodes_by_age = AsyncMock(return_value=0)
        graph_store.delete_episodes_by_age = AsyncMock(side_effect=_delete)

        response = await cleanup_data(
            dry_run=False,
            older_than_days=30,
            tenant_id=None,
            project_id=test_project_db.id,
            body=None,
            current_user=test_user,
            db=test_db,
            graph_store=graph_store,
        )

        assert captured["project_id"] == test_project_db.id
        assert response["project_id"] == test_project_db.id
        assert response["deleted"] == 5

    @pytest.mark.asyncio
    async def test_cleanup_data_rejects_non_positive_body_days(
        self,
        test_db: AsyncSession,
        test_user: User,
    ):
        """Body overrides cannot bypass the positive older_than_days constraint."""
        graph_store = Mock()
        graph_store.count_episodes_by_age = AsyncMock()
        graph_store.delete_episodes_by_age = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await cleanup_data(
                dry_run=True,
                older_than_days=30,
                tenant_id=None,
                project_id=None,
                body={"older_than_days": 0},
                current_user=test_user,
                db=test_db,
                graph_store=graph_store,
            )

        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        graph_store.count_episodes_by_age.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_data_rejects_invalid_body_dry_run(
        self,
        test_db: AsyncSession,
        test_user: User,
    ):
        """Body overrides must use a parseable dry_run boolean."""
        graph_store = Mock()
        graph_store.count_episodes_by_age = AsyncMock()
        graph_store.delete_episodes_by_age = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await cleanup_data(
                dry_run=True,
                older_than_days=30,
                tenant_id=None,
                project_id=None,
                body={"dry_run": "maybe"},
                current_user=test_user,
                db=test_db,
                graph_store=graph_store,
            )

        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_cleanup_data_failure_returns_sanitized_error(self, client, mock_graphiti_client):
        """Cleanup failures do not expose internal exception text."""
        mock_graphiti_client.count_episodes_by_age = AsyncMock(
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

    def _store(self) -> Mock:
        store = Mock()
        store.embedder = SimpleNamespace(embedding_dim=1536)
        store.find_duplicate_entities = AsyncMock(return_value=[])
        store.find_stale_edges = AsyncMock(return_value={})
        store.delete_stale_edges = AsyncMock(return_value=0)
        store.count_scoped_nodes = AsyncMock(return_value=0)
        store.count_old_episodes = AsyncMock(return_value=0)
        store.count_missing_embeddings = AsyncMock(return_value=0)
        store.get_existing_embedding_dimension = AsyncMock(return_value=None)
        store.detect_mixed_dimensions = AsyncMock(
            return_value={
                "has_mixed_dimensions": False,
                "counts": {},
                "dimensions": [],
                "total_embeddings": 0,
            }
        )
        store.get_vector_index_dimension = AsyncMock(return_value=None)
        store.get_embedding_dimension_distribution = AsyncMock(return_value=({}, 0))
        store.clear_entity_embeddings = AsyncMock(return_value=0)
        store.create_vector_index = AsyncMock(return_value=None)
        return store

    @pytest.mark.asyncio
    async def test_deduplicate_entities_dry_run(self, client, mock_neo4j_client):
        """Test entity deduplication in dry run mode delegates to the store."""
        # mock_graphiti_client (aliased to mock_graph_service) is wired by the
        # client fixture; override find_duplicate_entities on it.
        from src.infrastructure.adapters.primary.web.dependencies import get_graph_store
        client.app.dependency_overrides[get_graph_store].side_effect = None
        store = self._store()
        store.find_duplicate_entities = AsyncMock(
            return_value=[{"name": "Duplicate Entity", "count": 2, "uuids": ["ent_1", "ent_2"]}]
        )
        client.app.dependency_overrides[get_graph_store] = lambda: store

        response = client.post(
            "/api/v1/maintenance/deduplicate",
            json={"similarity_threshold": 0.9, "dry_run": True},
        )

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
        with pytest.raises(HTTPException) as exc_info:
            await incremental_refresh(
                episode_uuids=None,
                rebuild_communities=False,
                project_id="not-a-member",
                current_user=test_user,
                db=test_db,
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
        store = self._store()

        with pytest.raises(HTTPException) as exc_info:
            await deduplicate_entities(
                similarity_threshold=0.9,
                dry_run=True,
                project_id="not-a-member",
                current_user=test_user,
                db=test_db,
                graph_store=store,
                workflow_engine=mock_workflow_engine,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        store.find_duplicate_entities.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deduplicate_entities_dry_run_scopes_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        mock_workflow_engine,
    ):
        """Duplicate detection defaults to the caller's project memberships."""
        store = self._store()
        store.find_duplicate_entities = AsyncMock(
            return_value=[{"name": "Duplicate Entity", "count": 2, "uuids": ["a", "b"]}]
        )

        response = await deduplicate_entities(
            similarity_threshold=0.9,
            dry_run=True,
            project_id=None,
            current_user=test_user,
            db=test_db,
            graph_store=store,
            workflow_engine=mock_workflow_engine,
        )

        kwargs = store.find_duplicate_entities.await_args.kwargs
        assert kwargs["allowed_project_ids"] == [test_project_db.id]
        assert response["duplicates_found"] == 1

    @pytest.mark.asyncio
    async def test_invalidate_stale_edges_scopes_query_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Stale edge scans are limited to relationships within accessible projects."""
        store = self._store()
        store.find_stale_edges = AsyncMock(return_value={"RELATES_TO": 2})

        response = await invalidate_stale_edges(
            days_since_update=30,
            dry_run=True,
            project_id=None,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        kwargs = store.find_stale_edges.await_args.kwargs
        assert kwargs["allowed_project_ids"] == [test_project_db.id]
        assert response["stale_edges_found"] == 2

    @pytest.mark.asyncio
    async def test_invalidate_stale_edges_delete_uses_project_scope(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Deleting stale edges forwards the project scope to the store."""
        store = self._store()
        store.find_stale_edges = AsyncMock(return_value={})
        store.delete_stale_edges = AsyncMock(return_value=2)

        response = await invalidate_stale_edges(
            days_since_update=30,
            dry_run=False,
            project_id=None,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        kwargs = store.delete_stale_edges.await_args.kwargs
        assert kwargs["allowed_project_ids"] == [test_project_db.id]
        assert response["deleted"] == 2

    @pytest.mark.asyncio
    async def test_get_maintenance_status_scopes_counts_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Maintenance status only counts graph data in the caller's projects."""
        store = self._store()
        store.count_scoped_nodes = AsyncMock(side_effect=[10, 5, 1])
        store.count_old_episodes = AsyncMock(return_value=0)

        response = await get_maintenance_status(
            project_id=None,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        # All scoped counts forward the caller's project set.
        for call in store.count_scoped_nodes.await_args_list:
            assert call.args[3] == [test_project_db.id]
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
        store = self._store()

        with pytest.raises(HTTPException) as exc_info:
            await get_maintenance_status(
                project_id="not-a-member",
                current_user=test_user,
                db=test_db,
                graph_store=store,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        store.count_scoped_nodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_embedding_status_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
    ):
        """Embedding status cannot be requested for projects outside the caller's scope."""
        store = self._store()

        with pytest.raises(HTTPException) as exc_info:
            await get_embedding_status(
                project_id="not-a-member",
                current_user=test_user,
                db=test_db,
                graph_store=store,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_get_embedding_status_uses_store_dimension_queries(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Embedding status delegates dimension + missing-embedding queries to the store."""

        class ProviderFactory:
            async def resolve_provider(self, tenant_id: str):
                return SimpleNamespace(provider="openai")

        monkeypatch.setattr(
            "src.infrastructure.llm.provider_factory.get_ai_service_factory",
            lambda: ProviderFactory(),
        )

        store = self._store()
        store.get_existing_embedding_dimension = AsyncMock(return_value=1536)
        store.count_missing_embeddings = AsyncMock(return_value=3)

        response = await get_embedding_status(
            project_id=None,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response["existing_dimension"] == 1536
        assert response["missing_embeddings"] == 3
        assert store.get_existing_embedding_dimension.await_args.args[2] == [
            test_project_db.id
        ]

    @pytest.mark.asyncio
    async def test_check_embedding_dimensions_uses_store_detector(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Dimension checks delegate to the store's mixed-dimension detector."""
        store = self._store()
        store.detect_mixed_dimensions = AsyncMock(
            return_value={
                "has_mixed_dimensions": True,
                "counts": {"1536": 2, "1024": 1},
                "dimensions": [1536, 1024],
                "total_embeddings": 3,
            }
        )

        response = await check_embedding_dimensions(
            project_id=None,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        kwargs = store.detect_mixed_dimensions.await_args.kwargs
        assert kwargs["project_id"] == test_project_db.id
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

        store = self._store()
        store.get_vector_index_dimension = AsyncMock(return_value=1536)
        store.get_embedding_dimension_distribution = AsyncMock(
            return_value=({"1536": 4}, 4)
        )

        response = await get_native_embedding_status(
            project_id=None,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert store.get_embedding_dimension_distribution.await_args.args[2] == [
            test_project_db.id
        ]
        assert response["total_embeddings"] == 4

    @pytest.mark.asyncio
    async def test_migrate_embeddings_dry_run_without_records_does_not_clear(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ):
        """Dry-run migration returns a report even when no embeddings exist."""
        store = self._store()
        store.get_embedding_dimension_distribution = AsyncMock(return_value=({}, 0))

        response = await migrate_embeddings(
            target_model="openai",
            project_id=None,
            dry_run=True,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert store.get_embedding_dimension_distribution.await_args.args[2] == [
            test_project_db.id
        ]
        assert response["dry_run"] is True
        assert response["total_embeddings"] == 0
        store.clear_entity_embeddings.assert_not_awaited()
        store.create_vector_index.assert_not_awaited()

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

        store = self._store()

        with pytest.raises(HTTPException) as exc_info:
            await migrate_embeddings(
                target_model="openai",
                project_id=None,
                dry_run=False,
                current_user=test_user,
                db=test_db,
                graph_store=store,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        store.clear_entity_embeddings.assert_not_awaited()
        store.create_vector_index.assert_not_awaited()


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
