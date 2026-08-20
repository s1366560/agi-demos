"""Provider/Consumer coverage for the generation-scoped system-prompt seam."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent_prompt_mixin import PromptMixin
from src.infrastructure.agent.prompts.manager import SystemPromptManager
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.system_prompt import (
    SYSTEM_PROMPT_BUILDER_SERVICE_V2,
    SystemPromptBuilderV2,
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
