import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.plugins.v2 import agent_worker_runtime
from src.infrastructure.plugins.v2.graph_runtime import graph_runtime_definition_v2


@pytest.mark.unit
async def test_tenant_graph_closes_only_after_all_generation_owners_dispose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graphs = []

    async def fake_adapter(tenant_id: str) -> SimpleNamespace:
        await asyncio.sleep(0)
        graph = SimpleNamespace(tenant_id=tenant_id, close=AsyncMock())
        graphs.append(graph)
        return graph

    monkeypatch.setattr("src.configuration.factories.create_native_graph_adapter", fake_adapter)
    monkeypatch.setattr(
        "src.infrastructure.llm.initializer.initialize_default_llm_providers", AsyncMock()
    )

    async def stage(tenant):
        factory = agent_worker_runtime.agent_worker_graph_runtime_factory_v2(tenant)
        definition = graph_runtime_definition_v2(factory)
        bindings = []
        context = SimpleNamespace(provide=lambda _key, service, **_: bindings.append(service))
        dispose = await definition.apply(context, {"strategy": "native-adapter", "required": True})
        return bindings[0].require(), dispose

    (one, close_one), (candidate, close_candidate), (other, close_other) = await asyncio.gather(
        stage("a"), stage("a"), stage("b")
    )
    assert len(graphs) == 2
    assert one is candidate
    assert other is not one
    await close_candidate()
    one.close.assert_not_awaited()
    await close_other()
    other.close.assert_awaited_once()
    await close_one()
    one.close.assert_awaited_once()
    new, close_new = await stage("a")
    assert new is not one
    await close_new()
