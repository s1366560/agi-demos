"""Unit tests for knowledge graph router authorization and query construction."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.graph import (
    SubgraphRequest,
    get_community,
    get_community_members,
    get_entity,
    get_entity_relationships,
    get_entity_types,
    get_graph,
    get_subgraph,
    list_communities,
    list_entities,
    rebuild_communities,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
)


def _store() -> Mock:
    """A graph_store mock whose primitives return empty/None results."""
    store = Mock()
    store.list_entities = AsyncMock(return_value={"entities": [], "total": 0})
    store.list_communities = AsyncMock(return_value={"communities": [], "total": 0})
    store.get_entity_types = AsyncMock(return_value=[])
    store.get_entity = AsyncMock(return_value=None)
    store.get_community = AsyncMock(return_value=None)
    store.get_entity_relationships = AsyncMock(
        return_value={"relationships": [], "total": 0}
    )
    store.get_community_members = AsyncMock(return_value={"members": [], "total": 0})
    store.get_graph_visualization = AsyncMock(return_value=[])
    store.get_subgraph = AsyncMock(return_value=[])
    store.rebuild_communities = AsyncMock(
        return_value={"communities_count": 0, "entities_processed": 0}
    )
    return store


async def _add_other_tenant_project(
    test_db: AsyncSession,
    test_user: User,
    suffix: str,
) -> Project:
    other_tenant = Tenant(
        id=f"graph-other-tenant-{suffix}",
        name=f"Graph Other Tenant {suffix}",
        slug=f"graph-other-tenant-{suffix}",
        owner_id=test_user.id,
    )
    other_project = Project(
        id=f"graph-other-tenant-project-{suffix}",
        tenant_id=other_tenant.id,
        name=f"Graph Other Tenant Project {suffix}",
        description="Other tenant project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    membership = UserProject(
        id=f"graph-other-tenant-membership-{suffix}",
        user_id=test_user.id,
        project_id=other_project.id,
        role="owner",
        permissions={},
    )
    test_db.add_all([other_tenant, other_project, membership])
    await test_db.commit()
    return other_project


@pytest.mark.unit
class TestGraphRouter:
    @pytest.mark.asyncio
    async def test_list_entities_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
    ) -> None:
        store = _store()

        with pytest.raises(HTTPException) as exc_info:
            await list_entities(
                project_id="not-a-member",
                entity_type=None,
                limit=50,
                offset=0,
                current_user=test_user,
                db=test_db,
                graph_store=store,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        store.list_entities.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_communities_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
    ) -> None:
        store = _store()

        with pytest.raises(HTTPException) as exc_info:
            await list_communities(
                project_id="not-a-member",
                min_members=None,
                limit=50,
                offset=0,
                current_user=test_user,
                db=test_db,
                graph_store=store,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        store.list_communities.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint_name", ["list_entities", "list_communities"])
    async def test_graph_lists_reject_project_tenant_mismatch(
        self,
        endpoint_name: str,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()

        with pytest.raises(HTTPException) as exc_info:
            if endpoint_name == "list_entities":
                await list_entities(
                    tenant_id="other-tenant",
                    project_id=test_project_db.id,
                    entity_type=None,
                    limit=50,
                    offset=0,
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            else:
                await list_communities(
                    tenant_id="other-tenant",
                    project_id=test_project_db.id,
                    min_members=None,
                    limit=50,
                    offset=0,
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Project does not belong to tenant"

    @pytest.mark.asyncio
    async def test_list_entities_forwards_entity_type_filter(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()

        response = await list_entities(
            project_id=test_project_db.id,
            entity_type="Person",
            limit=50,
            offset=0,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response["total"] == 0
        kwargs = store.list_entities.await_args.kwargs
        assert kwargs["entity_type"] == "Person"

    @pytest.mark.asyncio
    async def test_get_graph_without_project_is_scoped_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()

        response = await get_graph(
            project_id=None,
            limit=100,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response == {"elements": {"nodes": [], "edges": []}}
        kwargs = store.get_graph_visualization.await_args.kwargs
        assert kwargs["project_ids"] == [test_project_db.id]

    @pytest.mark.asyncio
    async def test_get_subgraph_with_tenant_filters_allowed_project_ids(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        other_project = await _add_other_tenant_project(test_db, test_user, "subgraph")
        store = _store()

        response = await get_subgraph(
            SubgraphRequest(
                node_uuids=["entity-1"],
                tenant_id=test_project_db.tenant_id,
                include_neighbors=False,
            ),
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response == {"elements": {"nodes": [], "edges": []}}
        kwargs = store.get_subgraph.await_args.kwargs
        assert kwargs["project_ids"] == [test_project_db.id]
        assert other_project.id not in (kwargs["project_ids"] or [])
        assert kwargs["tenant_id"] == test_project_db.tenant_id

    @pytest.mark.asyncio
    async def test_get_subgraph_superuser_tenant_filter_applies_to_neighbors(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        test_user.is_superuser = True
        store = _store()

        response = await get_subgraph(
            SubgraphRequest(
                node_uuids=["entity-1"],
                tenant_id=test_project_db.tenant_id,
                include_neighbors=True,
            ),
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response == {"elements": {"nodes": [], "edges": []}}
        kwargs = store.get_subgraph.await_args.kwargs
        assert kwargs["tenant_id"] == test_project_db.tenant_id
        assert kwargs["is_superuser"] is True

    @pytest.mark.asyncio
    async def test_get_subgraph_rejects_project_tenant_mismatch(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()

        with pytest.raises(HTTPException) as exc_info:
            await get_subgraph(
                SubgraphRequest(
                    node_uuids=["entity-1"],
                    tenant_id="not-the-project-tenant",
                    project_id=test_project_db.id,
                ),
                current_user=test_user,
                db=test_db,
                graph_store=store,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        store.get_subgraph.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_entity_types_with_tenant_filters_allowed_project_ids(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        other_project = await _add_other_tenant_project(test_db, test_user, "entity-types")
        store = _store()

        response = await get_entity_types(
            tenant_id=test_project_db.tenant_id,
            project_id=None,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response == {"entity_types": [], "total": 0}
        kwargs = store.get_entity_types.await_args.kwargs
        assert kwargs["project_ids"] == [test_project_db.id]
        assert other_project.id not in (kwargs["project_ids"] or [])

    @pytest.mark.asyncio
    async def test_get_entity_types_rejects_project_tenant_mismatch(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()

        with pytest.raises(HTTPException) as exc_info:
            await get_entity_types(
                tenant_id="not-the-project-tenant",
                project_id=test_project_db.id,
                current_user=test_user,
                db=test_db,
                graph_store=store,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        store.get_entity_types.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_entity_relationships_forwards_project_scope(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()
        store.get_entity = AsyncMock(
            return_value={"uuid": "entity-1", "project_id": test_project_db.id}
        )

        response = await get_entity_relationships(
            entity_id="entity-1",
            relationship_type=None,
            limit=50,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response == {"relationships": [], "total": 0}
        kwargs = store.get_entity_relationships.await_args.kwargs
        assert kwargs["project_id"] == test_project_db.id
        assert kwargs["is_superuser"] is False

    @pytest.mark.asyncio
    async def test_get_entity_relationships_maps_rows_to_response(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()
        store.get_entity = AsyncMock(
            return_value={"uuid": "entity-1", "project_id": test_project_db.id}
        )
        store.get_entity_relationships = AsyncMock(
            return_value={
                "total": 3,
                "relationships": [
                    {
                        "edge_id": "edge-1",
                        "relation_type": "KNOWS",
                        "direction": "outgoing",
                        "fact": "Alice knows Bob",
                        "score": 0.9,
                        "created_at": None,
                        "updated_at": None,
                        "related_props": {
                            "uuid": "entity-2",
                            "name": "Bob",
                            "summary": "Related person",
                        },
                        "related_labels": ["Entity", "Person"],
                    }
                ],
            }
        )

        response = await get_entity_relationships(
            entity_id="entity-1",
            relationship_type=None,
            limit=1,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response["total"] == 3
        assert len(response["relationships"]) == 1
        assert response["relationships"][0]["related_entity"]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_get_community_members_forwards_project_scope(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()
        store.get_community = AsyncMock(
            return_value={"uuid": "community-1", "project_id": test_project_db.id}
        )

        response = await get_community_members(
            community_id="community-1",
            limit=100,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response == {"members": [], "total": 0}
        kwargs = store.get_community_members.await_args.kwargs
        assert kwargs["project_id"] == test_project_db.id
        assert kwargs["is_superuser"] is False

    @pytest.mark.asyncio
    async def test_get_community_members_maps_rows_to_response(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()
        store.get_community = AsyncMock(
            return_value={"uuid": "community-1", "project_id": test_project_db.id}
        )
        store.get_community_members = AsyncMock(
            return_value={
                "total": 4,
                "members": [
                    {
                        "uuid": "entity-1",
                        "name": "Alice",
                        "entity_type": "Person",
                        "summary": "Community member",
                        "created_at": None,
                    }
                ],
            }
        )

        response = await get_community_members(
            community_id="community-1",
            limit=1,
            current_user=test_user,
            db=test_db,
            graph_store=store,
        )

        assert response["total"] == 4
        assert len(response["members"]) == 1
        assert response["members"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_rebuild_communities_sync_processes_all_project_entities(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()
        store.rebuild_communities = AsyncMock(
            return_value={"communities_count": 1, "entities_processed": 1001}
        )

        response = await rebuild_communities(
            background=False,
            project_id=test_project_db.id,
            current_user=test_user,
            db=test_db,
            graph_store=store,
            workflow_engine=Mock(),
        )

        assert response["entities_processed"] == 1001
        store.rebuild_communities.assert_awaited_once_with(test_project_db.id)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("endpoint_name", "expected_detail"),
        [
            ("list_communities", "Failed to list communities"),
            ("list_entities", "Failed to list entities"),
            ("get_entity_types", "Failed to get entity types"),
            ("get_entity", "Failed to get entity"),
            ("get_entity_relationships", "Failed to get entity relationships"),
            ("get_graph", "Failed to get graph"),
            ("get_subgraph", "Failed to get subgraph"),
            ("get_community", "Failed to get community"),
            ("get_community_members", "Failed to get community members"),
            ("rebuild_communities", "Failed to rebuild communities"),
        ],
    )
    async def test_graph_internal_failures_return_sanitized_errors(  # noqa: C901, PLR0912
        self,
        endpoint_name: str,
        expected_detail: str,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        store = _store()
        error = RuntimeError("internal graph secret")

        # Configure the relevant primitive to raise.
        if endpoint_name == "list_communities":
            store.list_communities = AsyncMock(side_effect=error)
        elif endpoint_name == "list_entities":
            store.list_entities = AsyncMock(side_effect=error)
        elif endpoint_name == "get_entity_types":
            store.get_entity_types = AsyncMock(side_effect=error)
        elif endpoint_name == "get_entity":
            store.get_entity = AsyncMock(side_effect=error)
        elif endpoint_name == "get_entity_relationships":
            store.get_entity_relationships = AsyncMock(side_effect=error)
        elif endpoint_name == "get_graph":
            store.get_graph_visualization = AsyncMock(side_effect=error)
        elif endpoint_name == "get_subgraph":
            store.get_subgraph = AsyncMock(side_effect=error)
        elif endpoint_name == "get_community":
            store.get_community = AsyncMock(side_effect=error)
        elif endpoint_name == "get_community_members":
            store.get_community_members = AsyncMock(side_effect=error)
        elif endpoint_name == "rebuild_communities":
            store.rebuild_communities = AsyncMock(side_effect=error)

        # For entity/community-member endpoints, the lookup primitive must
        # succeed so the failure primitive is actually reached.
        if endpoint_name in {"get_entity_relationships", "get_community_members"}:
            store.get_entity = AsyncMock(
                return_value={"uuid": "entity-1", "project_id": test_project_db.id}
            )
            store.get_community = AsyncMock(
                return_value={"uuid": "community-1", "project_id": test_project_db.id}
            )

        with pytest.raises(HTTPException) as exc_info:
            if endpoint_name == "list_communities":
                await list_communities(
                    project_id=test_project_db.id,
                    min_members=None,
                    limit=50,
                    offset=0,
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            elif endpoint_name == "list_entities":
                await list_entities(
                    project_id=test_project_db.id,
                    entity_type=None,
                    limit=50,
                    offset=0,
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            elif endpoint_name == "get_entity_types":
                await get_entity_types(
                    project_id=test_project_db.id,
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            elif endpoint_name == "get_entity":
                await get_entity(
                    entity_id="entity-1",
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            elif endpoint_name == "get_entity_relationships":
                await get_entity_relationships(
                    entity_id="entity-1",
                    relationship_type=None,
                    limit=50,
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            elif endpoint_name == "get_graph":
                await get_graph(
                    project_id=test_project_db.id,
                    limit=100,
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            elif endpoint_name == "get_subgraph":
                await get_subgraph(
                    SubgraphRequest(node_uuids=["entity-1"], project_id=test_project_db.id),
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            elif endpoint_name == "get_community":
                await get_community(
                    community_id="community-1",
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            elif endpoint_name == "get_community_members":
                await get_community_members(
                    community_id="community-1",
                    limit=100,
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                )
            elif endpoint_name == "rebuild_communities":
                await rebuild_communities(
                    background=False,
                    project_id=test_project_db.id,
                    current_user=test_user,
                    db=test_db,
                    graph_store=store,
                    workflow_engine=Mock(),
                )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == expected_detail
