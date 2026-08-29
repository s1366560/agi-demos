"""Background-operation coverage for the SkillEvolution repository lease."""

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
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.skill_evolution_repository_lease_v2 import (
    lease_skill_evolution_repository_v2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]


async def test_background_lease_rejects_empty_tenant_identity() -> None:
    db = AsyncSession()
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with lease_skill_evolution_repository_v2(db=db, tenant_id="  "):
                pytest.fail("empty tenant identity must fail before admission")

        assert error.value.code == "skill_evolution_tenant_missing"
    finally:
        await db.close()


async def test_background_lease_pins_generation_tenant_operation_and_exact_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1030,
        version=1030,
    )
    db = AsyncSession()
    install_process_generation_host_v2(host)
    lease = None
    try:
        async with lease_skill_evolution_repository_v2(
            db=db,
            tenant_id="tenant-a",
        ) as lease:
            assert lease.operation.phase is FiberPhaseV2.ACTIVE
            assert lease.operation.descriptor.generation == 1030
            assert lease.operation.context.scope.kind is ScopeKindV2.TENANT
            assert lease.operation.context.scope.tenant_id == "tenant-a"
            assert lease.repository._session is db
            assert lease.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert lease.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a"
            }
            assert lease.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "background-authority",
                "consumer": "skill-evolution-repository",
            }

        assert lease is not None
        assert lease.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        clear_process_generation_host_v2(host)
        await db.close()
        await host.close()
