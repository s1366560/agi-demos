"""Provider/Consumer coverage for the generation-scoped tool-set seam."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _resolve_current_tools_from_runtime_v2,
)
from src.infrastructure.agent.plugins.selection_pipeline import ToolSelectionContext
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.tool_set import (
    TOOL_SET_RESOLVER_SERVICE_V2,
    ToolSetResolverV2,
)

_ROOT = Path(__file__).resolve().parents[6]


class _ToolAgent:
    def __init__(self) -> None:
        self.contexts: list[object] = []

    def _get_current_tools(
        self,
        *,
        selection_context: object,
    ) -> tuple[dict[str, object], list[object]]:
        self.contexts.append(selection_context)
        return {"read": object()}, [object()]


@pytest.mark.unit
async def test_runtime_consumer_resolves_tools_from_generation_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    agent = _ToolAgent()
    selection = ToolSelectionContext(tenant_id="tenant-a", project_id="project-a")

    async with pin_operation_context_v2(
        host,
        operation_id="tool-set-consumer",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        assert isinstance(
            operation.require(TOOL_SET_RESOLVER_SERVICE_V2),
            ToolSetResolverV2,
        )
        raw_tools, definitions = _resolve_current_tools_from_runtime_v2(agent, selection)

    assert set(raw_tools) == {"read"}
    assert len(definitions) == 1
    assert agent.contexts == [selection]
    await host.close()
