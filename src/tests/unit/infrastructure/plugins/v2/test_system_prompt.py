"""Provider/Consumer coverage for the generation-scoped system-prompt seam."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent_prompt_mixin import PromptMixin
from src.infrastructure.agent.prompts.manager import SystemPromptManager
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.system_prompt import (
    SYSTEM_PROMPT_BUILDER_SERVICE_V2,
    SYSTEM_PROMPT_SECTIONS_SERVICE_V2,
    SystemPromptBuilderV2,
    SystemPromptSectionsV2,
)

_ROOT = Path(__file__).resolve().parents[6]


class _PromptTool:
    name = "read"
    description = "read file"


class _PromptAgent(PromptMixin):
    model = "claude-3"
    skills: ClassVar[list[object]] = []
    subagents: ClassVar[list[object]] = []
    project_root = Path("/tmp/memstack-v2-prompt-test")
    max_steps = 5
    prompt_manager = SystemPromptManager()
    _enable_subagent_as_tool = False
    _workspace_manager = None
    _tool_policy_layers: ClassVar[dict[str, dict[str, object]]] = {}

    def _get_current_tools(
        self,
        selection_context: object | None = None,
    ) -> tuple[dict[str, object], list[_PromptTool]]:
        return {}, [_PromptTool()]


class _AlternativePromptBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, object | None]] = []

    async def build(
        self,
        *,
        manager: object,
        context: object,
        subagent: object | None,
    ) -> str:
        self.calls.append((manager, context, subagent))
        return "prompt-from-alternative-provider"


@pytest.mark.unit
async def test_prompt_mixin_requires_pinned_v2_operation_without_native_fallback() -> None:
    agent = _PromptAgent()
    with (
        patch.object(
            agent.prompt_manager,
            "build_system_prompt",
            new_callable=AsyncMock,
        ) as native_build,
        pytest.raises(RuntimeV2Error) as error,
    ):
        await agent._build_system_prompt(
            user_query="hello",
            conversation_context=[],
        )

    assert error.value.code == "operation_context_not_pinned"
    native_build.assert_not_awaited()


@pytest.mark.unit
async def test_prompt_mixin_propagates_missing_v2_service_without_native_fallback() -> None:
    agent = _PromptAgent()
    operation = Mock()
    operation.require.side_effect = RuntimeV2Error(
        "missing_service",
        "system prompt builder is unavailable",
    )

    with (
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=operation,
        ),
        patch.object(
            agent.prompt_manager,
            "build_system_prompt",
            new_callable=AsyncMock,
        ) as native_build,
        pytest.raises(RuntimeV2Error) as error,
    ):
        await agent._build_system_prompt(
            user_query="hello",
            conversation_context=[],
        )

    assert error.value.code == "missing_service"
    operation.require.assert_called_once_with(SYSTEM_PROMPT_BUILDER_SERVICE_V2)
    native_build.assert_not_awaited()


@pytest.mark.unit
async def test_prompt_mixin_accepts_structural_non_builtin_provider() -> None:
    agent = _PromptAgent()
    provider = _AlternativePromptBuilder()
    operation = Mock()
    operation.require.return_value = provider

    with patch(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        return_value=operation,
    ):
        prompt = await agent._build_system_prompt(
            user_query="hello",
            conversation_context=[],
        )

    assert prompt == "prompt-from-alternative-provider"
    operation.require.assert_called_once_with(SYSTEM_PROMPT_BUILDER_SERVICE_V2)
    assert len(provider.calls) == 1


@pytest.mark.unit
async def test_prompt_mixin_consumes_system_prompt_provider_from_operation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    async with pin_operation_context_v2(
        host,
        operation_id="system-prompt-consumer",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ):
        with patch.object(
            SystemPromptBuilderV2,
            "build",
            new_callable=AsyncMock,
            return_value="prompt-from-v2-provider",
        ) as build:
            prompt = await _PromptAgent()._build_system_prompt(
                user_query="hello",
                conversation_context=[],
            )

    assert prompt == "prompt-from-v2-provider"
    build.assert_awaited_once()
    await host.close()


@pytest.mark.unit
async def test_generation_provides_real_system_prompt_builder() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )

    async with await host.acquire() as generation:
        builder = generation.resolve(
            SYSTEM_PROMPT_BUILDER_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        assert isinstance(builder, SystemPromptBuilderV2)

    await host.close()


@pytest.mark.unit
async def test_generation_owns_runtime_prompt_sections() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )

    async with await host.acquire() as generation:
        provider = generation.resolve(
            SYSTEM_PROMPT_SECTIONS_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        assert isinstance(provider, SystemPromptSectionsV2)
        assert len(provider.sections) == 1
        assert "[TOOL_CALL]...[/TOOL_CALL]" in provider.sections[0]

    await host.close()
