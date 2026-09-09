"""Shared fixtures for populated governance-surface acceptance tests.

Every test runs the production FastAPI app (test_app harness) with the plugin
runtime v2 initialized against a real Redis instance, and seeds the isolated
``qa-governance`` tenant/project via ``scripts.qa_governance_fixtures``.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from scripts.qa_governance_fixtures import (
    QA_PROJECT_ID,
    QA_TENANT_ID,
    QA_WORKSPACE_ID,
    QaGovernanceSamples,
    build_qa_governance_samples,
    cleanup_qa_dlq,
    seed_qa_dlq,
    seed_qa_scope,
)
from src.domain.ports.services.workspace_authority_port import (
    WorkspaceAuthorityResolvedProfile,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.workspace_core_runtime import (
    WorkspaceCoreRuntimeServiceV2,
)

pytestmark = pytest.mark.integration

VIEWER_USER_ID = "33333333-3333-3333-3333-333333333333"
OUTSIDER_USER_ID = "44444444-4444-4444-4444-444444444444"


class QaWorkspaceAuthority:
    """Resolve the QA workspace for any caller; mirrors the conftest test double."""

    async def resolve_profiles(
        self,
        *,
        workspace_ids: set[str],
        user_id: str,
        is_superuser: bool = False,
    ) -> dict[str, WorkspaceAuthorityResolvedProfile]:
        return {
            workspace_id: WorkspaceAuthorityResolvedProfile(
                workspace_id=workspace_id,
                tenant_id=QA_TENANT_ID,
                project_id=QA_PROJECT_ID,
                name=workspace_id,
                created_by=user_id,
                is_archived=False,
                metadata={},
                member_role="owner",
            )
            for workspace_id in workspace_ids
        }


def _workspace_core_runtime_factory() -> WorkspaceCoreRuntimeServiceV2:
    return WorkspaceCoreRuntimeServiceV2(
        settings=SimpleNamespace(),
        client=SimpleNamespace(),
        authority=QaWorkspaceAuthority(),
        context_judge=SimpleNamespace(),
        plan_judge=SimpleNamespace(),
        autonomy_judge=SimpleNamespace(),
        access_verifier=SimpleNamespace(),
        event_sink=SimpleNamespace(),
        agent_runtime_provider=SimpleNamespace(),
        provider_adapter=SimpleNamespace(wait_until_idle=AsyncMock()),
    )


@pytest_asyncio.fixture(loop_scope="function")
async def qa_redis():
    """Real async Redis client; the local dev Redis is currently DLQ-empty."""
    client = aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture(loop_scope="function")
async def governance_runtime(test_app, qa_redis):
    """Publish the v2 generation with real Redis and the QA workspace authority."""
    host = await initialize_plugin_runtime_v2(
        test_app,
        sandbox_redis_client=qa_redis,
        workspace_core_runtime_factory=_workspace_core_runtime_factory,
    )
    try:
        yield host
    finally:
        await shutdown_plugin_runtime_v2(test_app)


@pytest_asyncio.fixture(loop_scope="function")
async def qa_samples(test_db, test_user) -> QaGovernanceSamples:
    # The test_app auth override already presents test_user as a superuser;
    # align the persisted row so dependencies that re-load the user from the
    # DB (e.g. the admin DLQ role check) observe the same identity.
    test_user.is_superuser = True
    await test_db.commit()
    return build_qa_governance_samples(test_user.id)


@pytest_asyncio.fixture(loop_scope="function")
async def qa_scope(test_db, qa_samples) -> QaGovernanceSamples:
    """Create the QA tenant/project, owner memberships and all SQL samples."""
    await seed_qa_scope(test_db, qa_samples)
    return qa_samples


@pytest_asyncio.fixture(loop_scope="function")
async def qa_dlq(qa_redis, qa_samples):
    """Seed the Redis DLQ samples; always clean them up afterwards."""
    await seed_qa_dlq(qa_redis, qa_samples)
    try:
        yield qa_samples
    finally:
        await cleanup_qa_dlq(qa_redis, qa_samples)


async def _create_user(test_db, user_id: str, email: str, full_name: str) -> User:
    user = User(
        id=user_id,
        email=email,
        hashed_password="hashed_password",
        full_name=full_name,
        is_active=True,
    )
    test_db.add(user)
    await test_db.commit()
    return user


@pytest_asyncio.fixture(loop_scope="function")
async def viewer_user(test_db, qa_scope) -> User:
    """Tenant/project member without admin rights."""
    user = await _create_user(test_db, VIEWER_USER_ID, "qa-viewer@example.com", "QA Viewer")
    test_db.add_all(
        [
            UserTenant(
                id=f"ut-{VIEWER_USER_ID}-{qa_scope.tenant_id}",
                user_id=VIEWER_USER_ID,
                tenant_id=qa_scope.tenant_id,
                role="member",
                permissions={"read": True},
            ),
            UserProject(
                id=str(uuid4()),
                user_id=VIEWER_USER_ID,
                project_id=qa_scope.project_id,
                role="member",
            ),
        ]
    )
    await test_db.commit()
    return user


@pytest_asyncio.fixture(loop_scope="function")
async def outsider_user(test_db, qa_scope, test_tenant_db) -> User:
    """User with membership in another tenant but none in the QA scope."""
    user = await _create_user(
        test_db, OUTSIDER_USER_ID, "qa-outsider@example.com", "QA Outsider"
    )
    test_db.add(
        UserTenant(
            id=f"ut-{OUTSIDER_USER_ID}-{test_tenant_db.id}",
            user_id=OUTSIDER_USER_ID,
            tenant_id=test_tenant_db.id,
            role="member",
            permissions={"read": True},
        )
    )
    await test_db.commit()
    return user


def _install_user_override(test_app, user_id: str, email: str, full_name: str) -> None:
    user = User(
        id=user_id,
        email=email,
        hashed_password="hashed_password",
        full_name=full_name,
        is_active=True,
        is_superuser=False,
    )
    user.tenant_id = QA_TENANT_ID
    user.roles = []
    user.tenants = []

    async def override_get_current_user() -> User:
        return user

    test_app.dependency_overrides[get_current_user] = override_get_current_user


@pytest_asyncio.fixture(loop_scope="function")
async def viewer_client(test_app, viewer_user):
    """Async client authenticated as the QA member (non-admin) user."""
    _install_user_override(test_app, VIEWER_USER_ID, "qa-viewer@example.com", "QA Viewer")
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        headers={"Authorization": "Bearer qa-viewer-token"},
    ) as client:
        yield client


@pytest_asyncio.fixture(loop_scope="function")
async def outsider_client(test_app, outsider_user):
    """Async client authenticated as a user outside the QA scope."""
    _install_user_override(test_app, OUTSIDER_USER_ID, "qa-outsider@example.com", "QA Outsider")
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        headers={"Authorization": "Bearer qa-outsider-token"},
    ) as client:
        yield client
