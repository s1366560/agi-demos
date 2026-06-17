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


def _neo4j_result(records: list[dict]) -> Mock:
    return Mock(records=records)


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
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await list_entities(
                project_id="not-a-member",
                entity_type=None,
                limit=50,
                offset=0,
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        neo4j_client.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_communities_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await list_communities(
                project_id="not-a-member",
                min_members=None,
                limit=50,
                offset=0,
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        neo4j_client.execute_query.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint_name", ["list_entities", "list_communities"])
    async def test_graph_lists_reject_project_tenant_mismatch(
        self,
        endpoint_name: str,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock()

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
                    neo4j_client=neo4j_client,
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
                    neo4j_client=neo4j_client,
                )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Project does not belong to tenant"
        neo4j_client.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_entities_uses_parameterized_entity_type_filter(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"total": 0}]),
                _neo4j_result([]),
            ]
        )

        response = await list_entities(
            project_id=test_project_db.id,
            entity_type="Person",
            limit=50,
            offset=0,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response["total"] == 0
        count_query = neo4j_client.execute_query.await_args_list[0].args[0]
        assert "$entity_type IN labels(e)" in count_query
        assert "'$entity_type' IN labels(e)" not in count_query
        assert neo4j_client.execute_query.await_args_list[0].kwargs["entity_type"] == "Person"

    @pytest.mark.asyncio
    async def test_get_graph_without_project_is_scoped_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(return_value=_neo4j_result([]))

        response = await get_graph(
            project_id=None,
            limit=100,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response == {"elements": {"nodes": [], "edges": []}}
        query_kwargs = neo4j_client.execute_query.await_args.kwargs
        assert query_kwargs["project_ids"] == [test_project_db.id]

    @pytest.mark.asyncio
    async def test_get_subgraph_with_tenant_filters_allowed_project_ids(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        other_project = await _add_other_tenant_project(test_db, test_user, "subgraph")
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(return_value=_neo4j_result([]))

        response = await get_subgraph(
            SubgraphRequest(
                node_uuids=["entity-1"],
                tenant_id=test_project_db.tenant_id,
                include_neighbors=False,
            ),
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response == {"elements": {"nodes": [], "edges": []}}
        query = neo4j_client.execute_query.await_args.args[0]
        query_kwargs = neo4j_client.execute_query.await_args.kwargs
        assert "$tenant_id IS NULL OR n.tenant_id = $tenant_id" in query
        assert query_kwargs["project_ids"] == [test_project_db.id]
        assert other_project.id not in query_kwargs["project_ids"]
        assert query_kwargs["tenant_id"] == test_project_db.tenant_id

    @pytest.mark.asyncio
    async def test_get_subgraph_superuser_tenant_filter_applies_to_neighbors(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        test_user.is_superuser = True
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(return_value=_neo4j_result([]))

        response = await get_subgraph(
            SubgraphRequest(
                node_uuids=["entity-1"],
                tenant_id=test_project_db.tenant_id,
                include_neighbors=True,
            ),
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response == {"elements": {"nodes": [], "edges": []}}
        query = neo4j_client.execute_query.await_args.args[0]
        query_kwargs = neo4j_client.execute_query.await_args.kwargs
        assert "n.tenant_id = $tenant_id" in query
        assert "m.tenant_id = $tenant_id" in query
        assert query_kwargs["tenant_id"] == test_project_db.tenant_id
        assert query_kwargs["is_superuser"] is True

    @pytest.mark.asyncio
    async def test_get_subgraph_rejects_project_tenant_mismatch(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_subgraph(
                SubgraphRequest(
                    node_uuids=["entity-1"],
                    tenant_id="not-the-project-tenant",
                    project_id=test_project_db.id,
                ),
                current_user=test_user,
                db=test_db,
                neo4j_client=neo4j_client,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        neo4j_client.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_entity_relationships_filters_related_entities_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                _neo4j_result([{"total": 0}]),
                _neo4j_result([]),
            ]
        )

        response = await get_entity_relationships(
            entity_id="entity-1",
            relationship_type=None,
            limit=50,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response == {"relationships": [], "total": 0}
        count_query = neo4j_client.execute_query.await_args_list[1].args[0]
        relationship_query = neo4j_client.execute_query.await_args_list[2].args[0]
        relationship_kwargs = neo4j_client.execute_query.await_args_list[2].kwargs
        assert "related.project_id = $project_id" in count_query
        assert "related.project_id = $project_id" in relationship_query
        assert relationship_kwargs["project_id"] == test_project_db.id
        assert relationship_kwargs["is_superuser"] is False

    @pytest.mark.asyncio
    async def test_get_entity_relationships_total_counts_all_matching_relationships(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                _neo4j_result([{"total": 3}]),
                _neo4j_result(
                    [
                        {
                            "edge_id": "edge-1",
                            "relation_type": "KNOWS",
                            "edge_props": {"fact": "Alice knows Bob", "score": 0.9},
                            "related_props": {
                                "uuid": "entity-2",
                                "name": "Bob",
                                "summary": "Related person",
                            },
                            "related_labels": ["Entity", "Person"],
                            "direction": "outgoing",
                        }
                    ]
                ),
            ]
        )

        response = await get_entity_relationships(
            entity_id="entity-1",
            relationship_type=None,
            limit=1,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response["total"] == 3
        assert len(response["relationships"]) == 1
        count_query = neo4j_client.execute_query.await_args_list[1].args[0]
        page_query = neo4j_client.execute_query.await_args_list[2].args[0]
        assert "RETURN count(r) as total" in count_query
        assert "LIMIT $limit" in page_query

    @pytest.mark.asyncio
    async def test_get_community_members_filters_members_by_project(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                _neo4j_result([{"total": 0}]),
                _neo4j_result([]),
            ]
        )

        response = await get_community_members(
            community_id="community-1",
            limit=100,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response == {"members": [], "total": 0}
        count_query = neo4j_client.execute_query.await_args_list[1].args[0]
        member_query = neo4j_client.execute_query.await_args_list[2].args[0]
        member_kwargs = neo4j_client.execute_query.await_args_list[2].kwargs
        assert "e.project_id = $project_id" in count_query
        assert "e.project_id = $project_id" in member_query
        assert member_kwargs["project_id"] == test_project_db.id
        assert member_kwargs["is_superuser"] is False

    @pytest.mark.asyncio
    async def test_get_community_members_total_counts_all_matching_members(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                _neo4j_result([{"total": 4}]),
                _neo4j_result(
                    [
                        {
                            "props": {
                                "uuid": "entity-1",
                                "name": "Alice",
                                "entity_type": "Person",
                                "summary": "Community member",
                            }
                        }
                    ]
                ),
            ]
        )

        response = await get_community_members(
            community_id="community-1",
            limit=1,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
        )

        assert response["total"] == 4
        assert len(response["members"]) == 1
        count_query = neo4j_client.execute_query.await_args_list[1].args[0]
        page_query = neo4j_client.execute_query.await_args_list[2].args[0]
        assert "RETURN count(e) as total" in count_query
        assert "LIMIT $limit" in page_query

    @pytest.mark.asyncio
    async def test_rebuild_communities_sync_processes_all_project_entities(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        entity_records = [
            {"uuid": f"entity-{index}", "name": f"Entity {index}", "entity_type": "Person"}
            for index in range(1001)
        ]
        neo4j_client = Mock()
        neo4j_client.execute_query = AsyncMock(
            side_effect=[
                _neo4j_result([]),
                _neo4j_result(entity_records),
            ]
        )
        community_updater = Mock()
        community_updater.update_communities_for_entities = AsyncMock(return_value=[object()])
        graph_service = Mock(community_updater=community_updater)

        response = await rebuild_communities(
            background=False,
            project_id=test_project_db.id,
            current_user=test_user,
            db=test_db,
            neo4j_client=neo4j_client,
            workflow_engine=Mock(),
            graph_service=graph_service,
        )

        assert response["entities_processed"] == len(entity_records)
        entity_query = neo4j_client.execute_query.await_args_list[1].args[0]
        assert "LIMIT 1000" not in entity_query
        updater_kwargs = community_updater.update_communities_for_entities.await_args.kwargs
        assert len(updater_kwargs["entities"]) == len(entity_records)

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
    async def test_graph_internal_failures_return_sanitized_errors(
        self,
        endpoint_name: str,
        expected_detail: str,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        neo4j_client = Mock()

        if endpoint_name in {
            "get_entity_relationships",
            "get_community_members",
        }:
            neo4j_client.execute_query = AsyncMock(
                side_effect=[
                    _neo4j_result([{"props": {"project_id": test_project_db.id}}]),
                    RuntimeError("internal graph secret"),
                ]
            )
        else:
            neo4j_client.execute_query = AsyncMock(
                side_effect=RuntimeError("internal graph secret")
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
                    neo4j_client=neo4j_client,
                )
            elif endpoint_name == "list_entities":
                await list_entities(
                    project_id=test_project_db.id,
                    entity_type=None,
                    limit=50,
                    offset=0,
                    current_user=test_user,
                    db=test_db,
                    neo4j_client=neo4j_client,
                )
            elif endpoint_name == "get_entity_types":
                await get_entity_types(
                    project_id=test_project_db.id,
                    current_user=test_user,
                    db=test_db,
                    neo4j_client=neo4j_client,
                )
            elif endpoint_name == "get_entity":
                await get_entity(
                    entity_id="entity-1",
                    current_user=test_user,
                    db=test_db,
                    neo4j_client=neo4j_client,
                )
            elif endpoint_name == "get_entity_relationships":
                await get_entity_relationships(
                    entity_id="entity-1",
                    relationship_type=None,
                    limit=50,
                    current_user=test_user,
                    db=test_db,
                    neo4j_client=neo4j_client,
                )
            elif endpoint_name == "get_graph":
                await get_graph(
                    project_id=test_project_db.id,
                    limit=100,
                    current_user=test_user,
                    db=test_db,
                    neo4j_client=neo4j_client,
                )
            elif endpoint_name == "get_subgraph":
                await get_subgraph(
                    SubgraphRequest(node_uuids=["entity-1"], project_id=test_project_db.id),
                    current_user=test_user,
                    db=test_db,
                    neo4j_client=neo4j_client,
                )
            elif endpoint_name == "get_community":
                await get_community(
                    community_id="community-1",
                    current_user=test_user,
                    db=test_db,
                    neo4j_client=neo4j_client,
                )
            elif endpoint_name == "get_community_members":
                await get_community_members(
                    community_id="community-1",
                    limit=100,
                    current_user=test_user,
                    db=test_db,
                    neo4j_client=neo4j_client,
                )
            elif endpoint_name == "rebuild_communities":
                await rebuild_communities(
                    background=False,
                    project_id=test_project_db.id,
                    current_user=test_user,
                    db=test_db,
                    neo4j_client=neo4j_client,
                    graph_service=Mock(),
                )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == expected_detail
