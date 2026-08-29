"""Nested operation coverage for agent-side Skill repository Consumers."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
    pin_agent_turn_operation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.skill_repository_operation_authority_v2 import (
    skill_repository_child_operation_authority_v2,
)
from src.infrastructure.plugins.v2.skill_repository_services import (
    SKILL_REPOSITORY_APPLICATION_SERVICE_V2,
    SkillRepositoryApplicationResolverProtocolV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]


async def test_child_authority_reuses_parent_generation_scope_identity_and_exact_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1031,
        version=1031,
    )
    assert publication.accepted is True, publication.receipt
    db = AsyncSession()
    install_process_generation_host_v2(host)
    authority = None
    try:
        async with pin_agent_turn_operation_v2(
            operation_id="turn-skill-sync-1",
            tenant_id="tenant-a",
            project_id="project-a",
            session_id="session-a",
            services={
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "user_id": "user-a",
                }
            },
        ) as parent:
            resolver = parent.require(SKILL_REPOSITORY_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SkillRepositoryApplicationResolverProtocolV2)
            async with skill_repository_child_operation_authority_v2(
                parent_operation=parent,
                resolver=resolver,
                db=db,
                consumer="agent-skill-sync",
            ) as authority:
                assert authority.operation.descriptor == parent.descriptor
                assert authority.operation.context.scope.kind is ScopeKindV2.SESSION
                assert authority.operation.context.scope.session_id == "session-a"
                assert authority.repository._session is db
                assert authority.version_repository._session is db
                assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
                assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "user_id": "user-a",
                }
                assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                    "kind": "child-authority",
                    "consumer": "agent-skill-sync",
                    "parent_operation_id": "turn-skill-sync-1",
                }

        assert authority is not None
        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        clear_process_generation_host_v2(host)
        await db.close()
        await host.close()
