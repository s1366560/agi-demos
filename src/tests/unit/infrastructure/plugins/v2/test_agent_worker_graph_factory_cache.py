from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.plugins.v2 import agent_worker_runtime


@pytest.mark.asyncio
async def test_process_reuses_one_graph_adapter_outside_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    agent_worker_runtime._process_graph_adapters.clear()
    created: list[str | None] = []

    async def fake_adapter(tenant_id: str | None = None) -> SimpleNamespace:
        created.append(tenant_id)
        return SimpleNamespace(tenant_id=tenant_id)

    monkeypatch.setattr(
        "src.configuration.factories.create_native_graph_adapter",
        fake_adapter,
    )
    monkeypatch.setattr(
        "src.infrastructure.llm.initializer.initialize_default_llm_providers",
        AsyncMock(),
    )

    factory = agent_worker_runtime.agent_worker_graph_runtime_factory_v2("tenant-a")
    first = await factory()
    second = await factory()

    assert first is second
    assert created == ["tenant-a"]
    assert getattr(first, "_process_shared_graph_v2", False) is True
    agent_worker_runtime._process_graph_adapters.clear()
