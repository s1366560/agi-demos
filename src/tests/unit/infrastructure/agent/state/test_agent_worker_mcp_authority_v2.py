"""Generation-bound authority coverage for Agent Worker MCP sandbox access."""

from __future__ import annotations

from inspect import getsource
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.agent.state import agent_worker_state
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedSandboxAdapter(MCPSandboxAdapter):
    def __init__(self) -> None:
        self.close_calls = 0

    async def sync_from_docker(self) -> int:
        return 0

    async def close(self) -> None:
        self.close_calls += 1


async def test_agent_worker_resolves_adapter_only_from_pinned_operation() -> None:
    adapter = _TrackedSandboxAdapter()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_runtime_factory=lambda: adapter)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=111,
        version=111,
    )
    assert publication.accepted is True

    try:
        async with pin_operation_context_v2(
            host=host,
            operation_id="agent-worker:test",
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id="tenant-a",
                project_id="project-a",
                session_id="session-a",
            ),
        ):
            assert agent_worker_state.current_mcp_sandbox_adapter_v2() is adapter
    finally:
        await host.close()

    assert adapter.close_calls == 1


def test_agent_worker_adapter_access_fails_without_operation_boundary() -> None:
    with pytest.raises(RuntimeV2Error) as error:
        agent_worker_state.current_mcp_sandbox_adapter_v2()

    assert error.value.code == "operation_context_not_pinned"


async def test_agent_worker_explicit_optional_runtime_returns_no_adapter() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=112,
        version=112,
    )
    assert publication.accepted is True

    try:
        async with pin_operation_context_v2(
            host=host,
            operation_id="agent-worker:optional",
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id="tenant-a",
                project_id="project-a",
                session_id="session-a",
            ),
        ):
            assert agent_worker_state.current_mcp_sandbox_adapter_v2() is None
    finally:
        await host.close()


def test_static_agent_worker_adapter_authority_is_retired() -> None:
    retired = {
        "_mcp_sandbox_adapter",
        "get_mcp_sandbox_adapter",
        "set_mcp_sandbox_adapter",
        "shutdown_mcp_sandbox_adapter",
        "sync_mcp_sandbox_adapter_from_docker",
    }

    assert retired.isdisjoint(vars(agent_worker_state))


def test_actor_and_local_runtime_use_v2_sandbox_factory() -> None:
    from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
    from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor

    actor_class = ProjectAgentActor.__ray_metadata__.modified_class
    actor_init_source = getsource(actor_class.__init__)
    actor_bootstrap_source = getsource(actor_class._bootstrap_runtime)
    local_chat_source = getsource(AgentRuntimeBootstrapper._run_chat_local)
    local_bootstrap_source = getsource(AgentRuntimeBootstrapper._ensure_local_runtime_bootstrapped)

    assert "sandbox_runtime_factory=agent_worker_sandbox_runtime_factory_v2" in actor_init_source
    assert "MCPSandboxAdapter(" not in actor_bootstrap_source
    assert "set_mcp_sandbox_adapter" not in actor_bootstrap_source
    assert "sandbox_runtime_factory=agent_worker_sandbox_runtime_factory_v2" in local_chat_source
    assert "agent.initialize()" not in local_chat_source.split("admission.admit", maxsplit=1)[0]
    assert "_bootstrap_mcp_sandbox" not in local_bootstrap_source
