"""Tests for agent graph API access control."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.graph.agent_graph import AgentGraph
from src.domain.model.agent.graph.graph_pattern import GraphPattern
from src.domain.model.agent.graph.graph_run import GraphRun
from src.domain.model.auth.user import User as AuthUser
from src.infrastructure.adapters.primary.web.routers.agent.agent_graph_router import (
    CancelRunRequest,
    cancel_graph_run,
    list_graph_runs,
)
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser


@pytest.mark.unit
class TestAgentGraphRouter:
    def _request_with_container(self, container: object, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.agent_graph_router.get_container_with_db",
            lambda _request, _db: container,
        )
        return MagicMock()

    @pytest.mark.asyncio
    async def test_list_graph_runs_rejects_cross_tenant_before_listing(
        self,
        test_db: AsyncSession,
        test_user: DBUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        graph = AgentGraph(
            id="graph-other-tenant",
            tenant_id="tenant-other",
            project_id="project-graph",
            name="Other tenant graph",
            pattern=GraphPattern.SUPERVISOR,
        )
        graph_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=graph))
        orchestrator = SimpleNamespace(list_runs_for_graph=AsyncMock(return_value=[]))
        container = SimpleNamespace(
            graph_repository=lambda: graph_repo,
            graph_orchestrator=lambda: orchestrator,
        )

        with pytest.raises(HTTPException) as exc_info:
            await list_graph_runs(
                self._request_with_container(container, monkeypatch),
                graph.id,
                current_user=cast(AuthUser, test_user),
                user_tenant_id="tenant-current",
                db=test_db,
            )

        assert exc_info.value.status_code == 404
        orchestrator.list_runs_for_graph.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_graph_run_rejects_cross_tenant_before_side_effect(
        self,
        test_db: AsyncSession,
        test_user: DBUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        run = GraphRun(
            id="run-other-tenant",
            graph_id="graph-other-tenant",
            conversation_id="conversation-other-tenant",
            tenant_id="tenant-other",
            project_id="project-graph",
        )
        orchestrator = SimpleNamespace(
            get_run_status=AsyncMock(return_value=run),
            cancel_run=AsyncMock(),
        )
        container = SimpleNamespace(graph_orchestrator=lambda: orchestrator)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_graph_run(
                self._request_with_container(container, monkeypatch),
                run.id,
                body=CancelRunRequest(reason="stop"),
                current_user=cast(AuthUser, test_user),
                user_tenant_id="tenant-current",
                db=test_db,
            )

        assert exc_info.value.status_code == 404
        orchestrator.cancel_run.assert_not_awaited()
