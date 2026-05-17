"""Unit tests for recall router project scoping."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.recall import (
    ShortTermRecallQuery,
    short_term_recall,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User


@pytest.mark.unit
class TestRecallRouter:
    @pytest.mark.asyncio
    async def test_short_term_recall_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
    ) -> None:
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await short_term_recall(
                ShortTermRecallQuery(window_minutes=60, limit=10, project_id="not-a-member"),
                current_user=test_user,
                db=test_db,
                graphiti_client=graphiti_client,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        graphiti_client.driver.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_term_recall_without_project_is_scoped_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(return_value=Mock(records=[]))

        response = await short_term_recall(
            ShortTermRecallQuery(window_minutes=60, limit=10),
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        assert response.total == 0
        query = graphiti_client.driver.execute_query.await_args.args[0]
        kwargs = graphiti_client.driver.execute_query.await_args.kwargs
        assert "e.project_id IN $project_ids" in query
        assert kwargs["project_ids"] == [test_project_db.id]

    @pytest.mark.asyncio
    async def test_short_term_recall_keeps_explicit_project_filter(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(return_value=Mock(records=[]))

        await short_term_recall(
            ShortTermRecallQuery(
                window_minutes=60,
                limit=10,
                tenant_id=test_project_db.tenant_id,
                project_id=test_project_db.id,
            ),
            current_user=test_user,
            db=test_db,
            graphiti_client=graphiti_client,
        )

        query = graphiti_client.driver.execute_query.await_args.args[0]
        kwargs = graphiti_client.driver.execute_query.await_args.kwargs
        assert "e.project_id = $project_id" in query
        assert "e.tenant_id = $tenant_id" in query
        assert kwargs["project_id"] == test_project_db.id
        assert kwargs["tenant_id"] == test_project_db.tenant_id

    @pytest.mark.asyncio
    async def test_short_term_recall_sanitizes_internal_errors(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(
            side_effect=RuntimeError("internal neo4j secret")
        )

        with pytest.raises(HTTPException) as exc_info:
            await short_term_recall(
                ShortTermRecallQuery(window_minutes=60, limit=10, project_id=test_project_db.id),
                current_user=test_user,
                db=test_db,
                graphiti_client=graphiti_client,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Short-term recall failed"
        assert "internal" not in exc_info.value.detail
