"""Generation ownership for the Skill MCP lifecycle manager."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.mcp.skill_mcp_manager import SkillMCPManager
from src.infrastructure.plugins.v2.agent_skill_mcp_service import (
    SKILL_MCP_MANAGER_MODULE_V2,
    SKILL_MCP_MANAGER_SERVICE_V2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)
_OPTIONAL_PREIMPORTED_MODULES = frozenset(
    {
        "builtin://memstack/agent/tool/github",
        "builtin://memstack/agent/skill/github",
        "builtin://memstack/agent/tool/docker-compose",
        "builtin://memstack/agent/skill/docker-compose",
        "builtin://memstack/agent/tool/drone",
        "builtin://memstack/agent/skill/drone",
        "builtin://memstack/agent/skill/darwinian-evolver",
    }
)


def _service_test_profile(document: ProfileDocumentV2) -> ProfileDocumentV2:
    return replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref in _OPTIONAL_PREIMPORTED_MODULES
            else entry
            for entry in document.entries
        ),
    )


async def test_skill_mcp_manager_is_shared_only_within_one_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown_instances: list[SkillMCPManager] = []
    original_shutdown = SkillMCPManager.shutdown

    async def record_shutdown(manager: SkillMCPManager) -> None:
        shutdown_instances.append(manager)
        await original_shutdown(manager)

    monkeypatch.setattr(SkillMCPManager, "shutdown", record_shutdown)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE,
        manifest_paths=(_MANIFEST,),
        generation=1,
        version=1,
        nonce="skill-mcp-service",
        profile_projector=_service_test_profile,
    )
    assert publication.accepted, publication.receipt

    async with pin_operation_context_v2(
        host,
        operation_id="first",
        scope=_SCOPE,
    ) as first_operation:
        first = first_operation.require(SKILL_MCP_MANAGER_SERVICE_V2)
    async with pin_operation_context_v2(
        host,
        operation_id="second",
        scope=_SCOPE,
    ) as second_operation:
        second = second_operation.require(SKILL_MCP_MANAGER_SERVICE_V2)

    assert isinstance(first, SkillMCPManager)
    assert second is first
    assert shutdown_instances == []

    await host.close()
    assert shutdown_instances == [first]


async def test_disabled_skill_mcp_manager_entry_is_not_replaced_by_agent_fallback() -> None:
    def disable_manager(document: ProfileDocumentV2) -> ProfileDocumentV2:
        document = _service_test_profile(document)
        return replace(
            document,
            entries=tuple(
                replace(entry, enabled=False)
                if entry.module_ref == SKILL_MCP_MANAGER_MODULE_V2
                else entry
                for entry in document.entries
            ),
        )

    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE,
        manifest_paths=(_MANIFEST,),
        generation=1,
        version=1,
        nonce="skill-mcp-service-disabled",
        profile_projector=disable_manager,
    )
    assert publication.accepted, publication.receipt

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="disabled",
            scope=_SCOPE,
        ) as operation:
            with pytest.raises(RuntimeV2Error) as error:
                operation.require(SKILL_MCP_MANAGER_SERVICE_V2)
            assert error.value.code == "missing_service"
    finally:
        await host.close()
