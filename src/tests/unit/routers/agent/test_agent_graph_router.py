"""Tests for Agent graph HTTP error mapping and V2 authority delegation."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.domain.model.agent.graph.agent_graph import AgentGraph
from src.domain.model.agent.graph.graph_pattern import GraphPattern
from src.domain.model.agent.graph.graph_run import GraphRun
from src.domain.model.auth.user import User as AuthUser
from src.infrastructure.adapters.primary.web.agent_graph_http_application_authority_v2 import (
    AgentGraphHttpApplicationAuthorityV2,
)
from src.infrastructure.adapters.primary.web.routers.agent.agent_graph_router import (
    CancelRunRequest,
    CreateGraphRequest,
    StartRunRequest,
    UpdateGraphRequest,
    cancel_graph_run,
    create_graph,
    delete_graph,
    get_graph,
    get_graph_run,
    list_graph_runs,
    list_graphs,
    start_graph_run,
    update_graph,
)
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.plugins.v2.agent_graph_management_services import (
    AgentGraphAccessDeniedV2,
    AgentGraphAccessV2,
    AgentGraphProjectGrantV2,
    AgentGraphRunAccessV2,
)


@pytest.mark.unit
class TestAgentGraphRouter:
    def test_graph_endpoints_do_not_require_default_tenant_dependency(self) -> None:
        endpoints = (
            list_graphs,
            create_graph,
            get_graph,
            update_graph,
            delete_graph,
            start_graph_run,
            list_graph_runs,
            get_graph_run,
            cancel_graph_run,
        )

        for endpoint in endpoints:
            assert "user_tenant_id" not in inspect.signature(endpoint).parameters

    @staticmethod
    def _grant() -> AgentGraphProjectGrantV2:
        return AgentGraphProjectGrantV2(
            project_id="project-graph",
            tenant_id="tenant-current",
            user_id="user-current",
            role="member",
        )

    @staticmethod
    def _authority(service: object) -> AgentGraphHttpApplicationAuthorityV2:
        return cast(
            AgentGraphHttpApplicationAuthorityV2,
            SimpleNamespace(service=service),
        )

    @pytest.mark.asyncio
    async def test_list_graph_runs_maps_project_access_denial_before_listing(
        self,
        test_user: DBUser,
    ) -> None:
        service = SimpleNamespace(
            list_graph_runs=AsyncMock(side_effect=AgentGraphAccessDeniedV2("project-graph"))
        )

        with pytest.raises(HTTPException) as exc_info:
            await list_graph_runs(
                "graph-other-tenant",
                current_user=cast(AuthUser, test_user),
                graph_authority=self._authority(service),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_cancel_graph_run_maps_access_denial_before_side_effect(
        self,
        test_user: DBUser,
    ) -> None:
        service = SimpleNamespace(
            get_graph_run=AsyncMock(side_effect=AgentGraphAccessDeniedV2("project-graph")),
            cancel_graph_run=AsyncMock(),
        )

        with pytest.raises(HTTPException) as exc_info:
            await cancel_graph_run(
                "run-other-tenant",
                body=CancelRunRequest(reason="stop"),
                current_user=cast(AuthUser, test_user),
                graph_authority=self._authority(service),
            )

        assert exc_info.value.status_code == 403
        service.cancel_graph_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_graphs_uses_v2_project_grant(
        self,
        test_user: DBUser,
    ) -> None:
        grant = self._grant()
        service = SimpleNamespace(
            require_project_access=AsyncMock(return_value=grant),
            list_graphs=AsyncMock(return_value=[]),
        )

        response = await list_graphs(
            project_id=grant.project_id,
            current_user=cast(AuthUser, test_user),
            graph_authority=self._authority(service),
        )

        assert response.total == 0
        service.require_project_access.assert_awaited_once_with(
            project_id=grant.project_id,
            user_id=str(test_user.id),
        )
        service.list_graphs.assert_awaited_once_with(grant)

    @pytest.mark.asyncio
    async def test_get_graph_returns_authorized_v2_graph(
        self,
        test_user: DBUser,
    ) -> None:
        grant = self._grant()
        graph = AgentGraph(
            id="graph-project-tenant",
            tenant_id=grant.tenant_id,
            project_id=grant.project_id,
            name="Project tenant graph",
            pattern=GraphPattern.SUPERVISOR,
        )
        service = SimpleNamespace(
            get_graph=AsyncMock(return_value=AgentGraphAccessV2(graph=graph, grant=grant))
        )

        response = await get_graph(
            graph.id,
            current_user=cast(AuthUser, test_user),
            graph_authority=self._authority(service),
        )

        assert response.id == graph.id
        assert response.tenant_id == grant.tenant_id

    @pytest.mark.asyncio
    async def test_start_graph_run_delegates_project_to_v2_service(
        self,
        test_user: DBUser,
    ) -> None:
        grant = self._grant()
        run = GraphRun(
            id="run-project-tenant",
            graph_id="graph-project-run",
            conversation_id="conversation-1",
            tenant_id=grant.tenant_id,
            project_id=grant.project_id,
        )
        service = SimpleNamespace(start_graph_run=AsyncMock(return_value=run))

        response = await start_graph_run(
            graph_id=run.graph_id,
            body=StartRunRequest(conversation_id=run.conversation_id),
            project_id=grant.project_id,
            current_user=cast(AuthUser, test_user),
            graph_authority=self._authority(service),
        )

        assert response.tenant_id == grant.tenant_id
        service.start_graph_run.assert_awaited_once_with(
            graph_id=run.graph_id,
            expected_project_id=grant.project_id,
            conversation_id=run.conversation_id,
            user_id=str(test_user.id),
            initial_context={},
            parent_session_id=None,
            parent_agent_id=None,
        )

    @pytest.mark.asyncio
    async def test_start_graph_run_value_errors_are_sanitized(
        self,
        test_user: DBUser,
    ) -> None:
        service = SimpleNamespace(
            start_graph_run=AsyncMock(side_effect=ValueError("secret graph run validation"))
        )

        with pytest.raises(HTTPException) as exc_info:
            await start_graph_run(
                graph_id="graph-secret",
                body=StartRunRequest(conversation_id="conversation-1"),
                project_id="project-1",
                current_user=cast(AuthUser, test_user),
                graph_authority=self._authority(service),
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid graph run request"
        assert "secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_graph_invalid_pattern_is_sanitized(
        self,
        test_user: DBUser,
    ) -> None:
        grant = self._grant()
        service = SimpleNamespace(require_project_access=AsyncMock(return_value=grant))

        with pytest.raises(HTTPException) as exc_info:
            await create_graph(
                body=CreateGraphRequest(
                    name="secret graph",
                    pattern="secret-pattern",
                    nodes=[],
                    edges=[],
                ),
                project_id=grant.project_id,
                current_user=cast(AuthUser, test_user),
                graph_authority=self._authority(service),
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid graph pattern"
        assert "secret-pattern" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_cancel_graph_run_value_errors_are_sanitized(
        self,
        test_user: DBUser,
    ) -> None:
        grant = self._grant()
        run = GraphRun(
            id="run-current-tenant",
            graph_id="graph-current-tenant",
            conversation_id="conversation-current-tenant",
            tenant_id=grant.tenant_id,
            project_id=grant.project_id,
        )
        access = AgentGraphRunAccessV2(run=run, grant=grant)
        service = SimpleNamespace(
            get_graph_run=AsyncMock(return_value=access),
            cancel_graph_run=AsyncMock(side_effect=ValueError("secret cancel reason")),
        )

        with pytest.raises(HTTPException) as exc_info:
            await cancel_graph_run(
                run.id,
                body=CancelRunRequest(reason="stop"),
                current_user=cast(AuthUser, test_user),
                graph_authority=self._authority(service),
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid graph run request"
        assert "secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_list_graphs_maps_project_access_denial(
        self,
        test_user: DBUser,
    ) -> None:
        service = SimpleNamespace(
            require_project_access=AsyncMock(side_effect=AgentGraphAccessDeniedV2("denied")),
            list_graphs=AsyncMock(),
        )

        with pytest.raises(HTTPException) as exc_info:
            await list_graphs(
                project_id="project-denied",
                current_user=cast(AuthUser, test_user),
                graph_authority=self._authority(service),
            )

        assert exc_info.value.status_code == 403
        service.list_graphs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_graph_maps_project_access_denial(
        self,
        test_user: DBUser,
    ) -> None:
        service = SimpleNamespace(
            get_graph=AsyncMock(side_effect=AgentGraphAccessDeniedV2("denied"))
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_graph(
                "graph-denied-project",
                current_user=cast(AuthUser, test_user),
                graph_authority=self._authority(service),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_graph_preserves_project_access_error(
        self,
        test_user: DBUser,
    ) -> None:
        service = SimpleNamespace(
            get_graph=AsyncMock(side_effect=AgentGraphAccessDeniedV2("denied")),
            update_graph=AsyncMock(),
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_graph(
                "graph-denied-update",
                body=UpdateGraphRequest(name="Updated"),
                current_user=cast(AuthUser, test_user),
                graph_authority=self._authority(service),
            )

        assert exc_info.value.status_code == 403
        service.update_graph.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_graph_run_preserves_project_access_error(
        self,
        test_user: DBUser,
    ) -> None:
        service = SimpleNamespace(
            start_graph_run=AsyncMock(side_effect=AgentGraphAccessDeniedV2("denied"))
        )

        with pytest.raises(HTTPException) as exc_info:
            await start_graph_run(
                graph_id="graph-denied-run",
                body=StartRunRequest(conversation_id="conversation-1"),
                project_id="project-denied",
                current_user=cast(AuthUser, test_user),
                graph_authority=self._authority(service),
            )

        assert exc_info.value.status_code == 403
