"""Pinned-generation coverage for ACP conversation authorities."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.acp.conversation_authority_v2 import (
    acp_conversation_access_authority_v2,
    acp_conversation_collection_authority_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[4]


async def test_acp_conversation_authorities_use_connection_generation_and_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=971,
        version=971,
        nonce="acp-conversation-authority",
    )
    db = AsyncSession()
    collection = None
    access = None
    try:
        async with pin_generation_v2(host):
            async with acp_conversation_collection_authority_v2(
                operation_id="acp-create:test",
                db=db,
                tenant_id="tenant-1",
                user_id="user-1",
                project_id="project-1",
            ) as current_collection:
                collection = current_collection
                assert collection.operation.phase is FiberPhaseV2.ACTIVE
                assert collection.operation.descriptor.generation == 971
                assert cast(Any, collection.service.repository).session is db
                assert collection.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
                assert collection.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                    "tenant_id": "tenant-1",
                    "user_id": "user-1",
                    "project_id": "project-1",
                }
                assert collection.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                    "kind": "acp-conversation-create",
                    "project_id": "project-1",
                }

            async with acp_conversation_access_authority_v2(
                operation_id="acp-access:test",
                db=db,
                tenant_id="tenant-1",
                user_id="user-1",
                project_id="project-1",
                conversation_id="conversation-1",
            ) as current_access:
                access = current_access
                assert access.operation.descriptor.generation == 971
                assert cast(Any, access.service.repository)._session is db
                assert access.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                    "kind": "acp-conversation-access",
                    "project_id": "project-1",
                    "conversation_id": "conversation-1",
                }

        assert collection is not None
        assert collection.operation.phase is FiberPhaseV2.DISPOSED
        assert access is not None
        assert access.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()
