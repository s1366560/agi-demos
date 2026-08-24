"""Structural capability projection tests for the Agent tools HTTP surface."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.domain.model.plugins.generated_v2 import DataPlaneTargetV2, ScopeKindV2
from src.infrastructure.plugins.v2.agent_tool_capability_projection import (
    project_agent_tool_capabilities_v2,
)
from src.infrastructure.plugins.v2.channel_adapters import (
    CHANNEL_ADAPTER_RESOLVER_SERVICE_V2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_context import FiberPhaseV2
from src.infrastructure.plugins.v2.tool_set import TOOL_CONTRIBUTION_MODULE_V2

pytestmark = pytest.mark.unit


class _ChannelResolver:
    def metadata(self, channel_type: str) -> object | None:
        return self.list_metadata().get(channel_type)

    def list_metadata(self) -> dict[str, object]:
        return {"feishu": object(), "webhook": object()}

    async def build(self, context: object) -> object:
        return context


def _contract(
    *,
    provides: tuple[tuple[str, str], ...] = (),
    handled_events: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        services=SimpleNamespace(
            provides=tuple(
                SimpleNamespace(service=service, version=version) for service, version in provides
            )
        ),
        events=SimpleNamespace(handles=tuple(object() for _ in range(handled_events))),
    )


def _module(
    module_ref: str,
    *,
    targets: tuple[DataPlaneTargetV2, ...] = (DataPlaneTargetV2.PYTHON,),
    provides: tuple[tuple[str, str], ...] = (),
    handled_events: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        module_ref=module_ref,
        targets=targets,
        contract=_contract(provides=provides, handled_events=handled_events),
    )


def test_projection_counts_only_active_python_contracts() -> None:
    tool_set_module = _module(
        "builtin://memstack/agent/tool-set",
        provides=(
            ("service:tool-set-catalog", "1.0.0"),
            ("service:tool-set-resolver", "1.0.0"),
        ),
        handled_events=1,
    )
    tool_contribution_module = _module(TOOL_CONTRIBUTION_MODULE_V2, handled_events=2)
    channel_module = _module(
        "builtin://memstack/channel/catalog",
        provides=((CHANNEL_ADAPTER_RESOLVER_SERVICE_V2, "1.0.0"),),
    )
    disabled_module = _module(
        "builtin://memstack/disabled",
        provides=(("service:disabled", "1.0.0"),),
        handled_events=10,
    )
    dormant_module = _module("builtin://third-party/dormant")
    web_only_module = _module(
        "builtin://memstack/web/only",
        targets=(DataPlaneTargetV2.WEB,),
    )
    manifests = (
        SimpleNamespace(
            plugin_id="memstack-runtime-kernel",
            modules=(tool_set_module, tool_contribution_module, channel_module, disabled_module),
        ),
        SimpleNamespace(plugin_id="third-party", modules=(dormant_module,)),
        SimpleNamespace(plugin_id="web-only", modules=(web_only_module,)),
    )
    active_entries = tuple(
        SimpleNamespace(
            entry_id=f"entry-{index}",
            plugin_ref="memstack-runtime-kernel",
            module_ref=module.module_ref,
        )
        for index, module in enumerate(
            (tool_set_module, tool_contribution_module, channel_module),
            start=1,
        )
    )
    generation = SimpleNamespace(
        snapshot=SimpleNamespace(manifests=manifests),
        fibers=tuple(
            SimpleNamespace(entry=entry, phase=FiberPhaseV2.ACTIVE) for entry in active_entries
        ),
        resolve=MagicMock(return_value=_ChannelResolver()),
    )

    projection = project_agent_tool_capabilities_v2(generation)

    assert projection.plugins_total == 2
    assert projection.plugins_enabled == 1
    assert projection.tool_contributions == 1
    assert projection.channel_types == 2
    assert projection.hook_handlers == 3
    assert projection.commands == 0
    assert projection.services == 3
    assert projection.service_provider_effects == 2
    resolved_service, resolved_scope = generation.resolve.call_args.args
    assert resolved_service == CHANNEL_ADAPTER_RESOLVER_SERVICE_V2
    assert resolved_scope.kind is ScopeKindV2.ROOT


def test_projection_rejects_active_fiber_without_snapshot_contract() -> None:
    entry = SimpleNamespace(
        entry_id="unknown-entry",
        plugin_ref="missing-plugin",
        module_ref="builtin://missing/module",
    )
    generation = SimpleNamespace(
        snapshot=SimpleNamespace(manifests=()),
        fibers=(SimpleNamespace(entry=entry, phase=FiberPhaseV2.ACTIVE),),
    )

    with pytest.raises(RuntimeV2Error) as error:
        project_agent_tool_capabilities_v2(generation)

    assert error.value.code == "active_fiber_contract_missing"
