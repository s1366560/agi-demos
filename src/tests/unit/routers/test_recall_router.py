"""Unit tests for recall router project scoping."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.recall import (
    ShortTermRecallQuery,
    short_term_recall,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
)


async def _add_other_tenant_project(
    test_db: AsyncSession,
    test_user: User,
) -> Project:
    other_tenant = Tenant(
        id="recall-other-tenant",
        name="Recall Other Tenant",
        slug="recall-other-tenant",
        owner_id=test_user.id,
    )
    other_project = Project(
        id="recall-other-tenant-project",
        tenant_id=other_tenant.id,
        name="Recall Other Tenant Project",
        description="Other tenant project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    membership = UserProject(
        id="recall-other-tenant-membership",
        user_id=test_user.id,
        project_id=other_project.id,
        role="owner",
        permissions={},
    )
    test_db.add_all([other_tenant, other_project, membership])
    await test_db.commit()
    return other_project


def _make_graph_store() -> Mock:
    store = Mock()
    store.recall_recent_episodes = AsyncMock(return_value=[])
    return store


@pytest.mark.unit
class TestRecallRouter:
    @pytest.mark.asyncio
    async def test_short_term_recall_rejects_unjoined_project(
        self,
        test_db: AsyncSession,
        test_user: User,
    ) -> None:
        graph_store = _make_graph_store()

        with pytest.raises(HTTPException) as exc_info:
            await short_term_recall(
                ShortTermRecallQuery(window_minutes=60, limit=10, project_id="not-a-member"),
                current_user=test_user,
                db=test_db,
                graph_store=graph_store,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        graph_store.recall_recent_episodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_short_term_recall_without_project_is_scoped_to_user_projects(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graph_store = _make_graph_store()

        response = await short_term_recall(
            ShortTermRecallQuery(window_minutes=60, limit=10),
            current_user=test_user,
            db=test_db,
            graph_store=graph_store,
        )

        assert response.total == 0
        kwargs = graph_store.recall_recent_episodes.await_args.kwargs
        assert kwargs["project_ids"] == [test_project_db.id]
        assert kwargs["project_id"] is None

    @pytest.mark.asyncio
    async def test_short_term_recall_keeps_explicit_project_filter(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graph_store = _make_graph_store()

        await short_term_recall(
            ShortTermRecallQuery(
                window_minutes=60,
                limit=10,
                tenant_id=test_project_db.tenant_id,
                project_id=test_project_db.id,
            ),
            current_user=test_user,
            db=test_db,
            graph_store=graph_store,
        )

        kwargs = graph_store.recall_recent_episodes.await_args.kwargs
        assert kwargs["project_id"] == test_project_db.id
        assert kwargs["tenant_id"] == test_project_db.tenant_id

    @pytest.mark.asyncio
    async def test_short_term_recall_with_tenant_filters_allowed_project_ids(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        other_project = await _add_other_tenant_project(test_db, test_user)
        graph_store = _make_graph_store()

        response = await short_term_recall(
            ShortTermRecallQuery(
                window_minutes=60,
                limit=10,
                tenant_id=test_project_db.tenant_id,
            ),
            current_user=test_user,
            db=test_db,
            graph_store=graph_store,
        )

        assert response.total == 0
        kwargs = graph_store.recall_recent_episodes.await_args.kwargs
        assert kwargs["project_ids"] == [test_project_db.id]
        assert other_project.id not in (kwargs["project_ids"] or [])
        assert kwargs["tenant_id"] == test_project_db.tenant_id

    @pytest.mark.asyncio
    async def test_short_term_recall_rejects_project_tenant_mismatch(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graph_store = _make_graph_store()

        with pytest.raises(HTTPException) as exc_info:
            await short_term_recall(
                ShortTermRecallQuery(
                    window_minutes=60,
                    limit=10,
                    tenant_id="not-the-project-tenant",
                    project_id=test_project_db.id,
                ),
                current_user=test_user,
                db=test_db,
                graph_store=graph_store,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        graph_store.recall_recent_episodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_short_term_recall_sanitizes_internal_errors(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        graph_store = _make_graph_store()
        graph_store.recall_recent_episodes = AsyncMock(
            side_effect=RuntimeError("internal neo4j secret")
        )

        with pytest.raises(HTTPException) as exc_info:
            await short_term_recall(
                ShortTermRecallQuery(window_minutes=60, limit=10, project_id=test_project_db.id),
                current_user=test_user,
                db=test_db,
                graph_store=graph_store,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Short-term recall failed"
        assert "internal" not in exc_info.value.detail
