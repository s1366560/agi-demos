"""Pinned-generation tenant agent config loading for runtime bootstrap."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[5]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_runtime_bootstrapper_loads_config_through_pinned_v2_resolver() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=75,
        version=75,
    )
    assert publication.accepted is True
    expected = TenantAgentConfig.create_default("tenant-a").update_llm_settings(
        model="openai/gpt-5.4"
    )
    repository = MagicMock()
    repository.get_by_tenant = AsyncMock(return_value=expected)
    try:
        with patch(
            "src.infrastructure.plugins.v2.tenant_agent_config_services."
            "SqlTenantAgentConfigRepository",
            return_value=repository,
        ):
            async with pin_generation_v2(host):
                result = await AgentRuntimeBootstrapper._load_tenant_agent_config("tenant-a")

        assert result is expected
        repository.get_by_tenant.assert_awaited_once_with("tenant-a")
    finally:
        await host.close()


async def test_runtime_bootstrapper_propagates_provider_failure_without_default_fallback() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=76,
        version=76,
    )
    assert publication.accepted is True
    repository = MagicMock()
    repository.get_by_tenant = AsyncMock(side_effect=RuntimeError("database unavailable"))
    try:
        with (
            patch(
                "src.infrastructure.plugins.v2.tenant_agent_config_services."
                "SqlTenantAgentConfigRepository",
                return_value=repository,
            ),
            pytest.raises(RuntimeV2Error) as error,
        ):
            async with pin_generation_v2(host):
                await AgentRuntimeBootstrapper._load_tenant_agent_config("tenant-a")
        assert error.value.code == "tenant_agent_config_load_failed"
    finally:
        await host.close()


async def test_runtime_bootstrapper_rejects_missing_generation() -> None:
    with pytest.raises(RuntimeV2Error) as error:
        await AgentRuntimeBootstrapper._load_tenant_agent_config("tenant-a")

    assert error.value.code == "generation_not_pinned"
