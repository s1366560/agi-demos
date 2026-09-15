"""The actual in-process worker admission receives a cross-process publisher."""

from src.infrastructure.plugins.v2 import builtin_modules
from src.infrastructure.plugins.v2.agent_worker_lifecycle_transport_v2 import (
    AgentWorkerLifecycleTransportV2,
)
from src.tests.unit.application.services import test_agent_runtime_bootstrapper as fixtures

bootstrapper = fixtures.bootstrapper


async def test_real_worker_admission_injects_redis_lifecycle_publisher(bootstrapper, monkeypatch):
    original = builtin_modules.builtin_runtime_definitions_v2
    publishers = []

    def definitions(**kwargs):
        publishers.append(kwargs.get("agent_lifecycle_connection_manager"))
        return original(**kwargs)

    monkeypatch.setattr(builtin_modules, "builtin_runtime_definitions_v2", definitions)
    await fixtures.test_in_process_chat_acquires_enabled_workspace_runtime(bootstrapper)
    assert len(publishers) == 1
    assert isinstance(publishers[0], AgentWorkerLifecycleTransportV2)
