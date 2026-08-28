"""Connection-lifetime coverage for the conversation-access V2 authority."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.conversation_access_application_authority_v2 import (
    conversation_access_application_authority_v2,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]


def _message_context(db: AsyncSession) -> MessageContext:
    return cast(
        MessageContext,
        SimpleNamespace(
            db=db,
            tenant_id="tenant-1",
            user_id="user-1",
        ),
    )


async def test_authority_uses_pinned_generation_and_message_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=946,
        version=946,
    )
    db = AsyncSession()
    authority = None
    try:
        async with (
            pin_generation_v2(host),
            conversation_access_application_authority_v2(
                _message_context(db),
                conversation_id="conversation-1",
            ) as current,
        ):
            authority = current
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 946
            assert cast(Any, authority.service.repository)._session is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-1",
                "user_id": "user-1",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "websocket-conversation-access",
                "conversation_id": "conversation-1",
            }

        assert authority is not None
        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


async def test_authority_fails_closed_without_a_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.conversation_access_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with conversation_access_application_authority_v2(
                _message_context(db),
                conversation_id="conversation-1",
            ):
                pass
    finally:
        await db.close()

    assert error.value.code == "generation_not_pinned"
