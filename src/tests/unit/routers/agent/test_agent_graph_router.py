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
    CreateGraphRequest,
    StartRunRequest,
    UpdateGraphRequest,
    cancel_graph_run,
    create_graph,
    get_graph,
    list_graph_runs,
    list_graphs,
    start_graph_run,
    update_graph,
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

    def _allow_project_access(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _allow(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.agent_graph_router._ensure_project_graph_access",
            _allow,
        )

    def _denied_project_db(self) -> MagicMock:
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
        )
        db.commit = AsyncMock()
        return db

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

    @pytest.mark.asyncio
    async def test_start_graph_run_value_errors_are_sanitized(
        self,
        test_db: AsyncSession,
        test_user: DBUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._allow_project_access(monkeypatch)
        graph = AgentGraph(
            id="graph-secret",
            tenant_id="tenant-current",
            project_id="project-1",
            name="Secret graph",
            pattern=GraphPattern.SUPERVISOR,
        )
        graph_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=graph))
        orchestrator = SimpleNamespace(
            start_run=AsyncMock(side_effect=ValueError("secret graph run validation"))
        )
        container = SimpleNamespace(
            graph_repository=lambda: graph_repo,
            graph_orchestrator=lambda: orchestrator,
        )

        with pytest.raises(HTTPException) as exc_info:
            await start_graph_run(
                self._request_with_container(container, monkeypatch),
                graph_id="graph-secret",
                body=StartRunRequest(conversation_id="conversation-1"),
                project_id="project-1",
                current_user=cast(AuthUser, test_user),
                user_tenant_id="tenant-current",
                db=test_db,
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid graph run request"
        assert "secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_graph_invalid_pattern_is_sanitized(
        self,
        test_db: AsyncSession,
        test_user: DBUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._allow_project_access(monkeypatch)
        with pytest.raises(HTTPException) as exc_info:
            await create_graph(
                request=MagicMock(),
                body=CreateGraphRequest(
                    name="secret graph",
                    pattern="secret-pattern",
                    nodes=[],
                    edges=[],
                ),
                project_id="project-1",
                current_user=cast(AuthUser, test_user),
                user_tenant_id="tenant-current",
                db=test_db,
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid graph pattern"
        assert "secret-pattern" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_cancel_graph_run_value_errors_are_sanitized(
        self,
        test_db: AsyncSession,
        test_user: DBUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._allow_project_access(monkeypatch)
        run = GraphRun(
            id="run-current-tenant",
            graph_id="graph-current-tenant",
            conversation_id="conversation-current-tenant",
            tenant_id="tenant-current",
            project_id="project-graph",
        )
        orchestrator = SimpleNamespace(
            get_run_status=AsyncMock(return_value=run),
            cancel_run=AsyncMock(side_effect=ValueError("secret cancel reason")),
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

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid graph run request"
        assert "secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_list_graphs_requires_project_access_before_listing(
        self,
        test_user: DBUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        graph_repo = SimpleNamespace(list_by_project=AsyncMock(return_value=[]))
        container = SimpleNamespace(graph_repository=lambda: graph_repo)

        with pytest.raises(HTTPException) as exc_info:
            await list_graphs(
                self._request_with_container(container, monkeypatch),
                project_id="project-denied",
                current_user=cast(AuthUser, test_user),
                user_tenant_id="tenant-current",
                db=cast(AsyncSession, self._denied_project_db()),
            )

        assert exc_info.value.status_code == 403
        graph_repo.list_by_project.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_graph_requires_membership_in_graph_project(
        self,
        test_user: DBUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        graph = AgentGraph(
            id="graph-denied-project",
            tenant_id="tenant-current",
            project_id="project-denied",
            name="Denied graph",
            pattern=GraphPattern.SUPERVISOR,
        )
        graph_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=graph))
        container = SimpleNamespace(graph_repository=lambda: graph_repo)

        with pytest.raises(HTTPException) as exc_info:
            await get_graph(
                self._request_with_container(container, monkeypatch),
                graph.id,
                current_user=cast(AuthUser, test_user),
                user_tenant_id="tenant-current",
                db=cast(AsyncSession, self._denied_project_db()),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_graph_preserves_project_access_error(
        self,
        test_user: DBUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        graph = AgentGraph(
            id="graph-denied-update",
            tenant_id="tenant-current",
            project_id="project-denied",
            name="Denied graph",
            pattern=GraphPattern.SUPERVISOR,
        )
        graph_repo = SimpleNamespace(
            find_by_id=AsyncMock(return_value=graph),
            save=AsyncMock(),
        )
        container = SimpleNamespace(graph_repository=lambda: graph_repo)

        with pytest.raises(HTTPException) as exc_info:
            await update_graph(
                self._request_with_container(container, monkeypatch),
                graph.id,
                body=UpdateGraphRequest(name="Updated"),
                current_user=cast(AuthUser, test_user),
                user_tenant_id="tenant-current",
                db=cast(AsyncSession, self._denied_project_db()),
            )

        assert exc_info.value.status_code == 403
        graph_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_graph_run_requires_write_access_before_orchestrating(
        self,
        test_user: DBUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        graph = AgentGraph(
            id="graph-denied-run",
            tenant_id="tenant-current",
            project_id="project-denied",
            name="Denied run graph",
            pattern=GraphPattern.SUPERVISOR,
        )
        graph_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=graph))
        orchestrator = SimpleNamespace(start_run=AsyncMock())
        container = SimpleNamespace(
            graph_repository=lambda: graph_repo,
            graph_orchestrator=lambda: orchestrator,
        )

        with pytest.raises(HTTPException) as exc_info:
            await start_graph_run(
                self._request_with_container(container, monkeypatch),
                graph_id=graph.id,
                body=StartRunRequest(conversation_id="conversation-1"),
                project_id="project-denied",
                current_user=cast(AuthUser, test_user),
                user_tenant_id="tenant-current",
                db=cast(AsyncSession, self._denied_project_db()),
            )

        assert exc_info.value.status_code == 403
        orchestrator.start_run.assert_not_awaited()
