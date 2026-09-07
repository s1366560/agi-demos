"""Generation isolation for agent component caches."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.state import agent_session_pool, agent_worker_state
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)


def _descriptor(*, generation: int, digest_character: str) -> PluginGenerationDescriptorV2:
    return PluginGenerationDescriptorV2(
        profile_id="memstack-default",
        generation=generation,
        digest=digest_character * 64,
    )


async def _publish_generation(host: PlatformPluginRuntimeHostV2, generation: int) -> None:
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=generation,
        version=generation,
        nonce=f"agent-cache-generation-{generation}",
    )


@pytest.fixture
async def generation_host() -> AsyncIterator[PlatformPluginRuntimeHostV2]:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await _publish_generation(host, 7)
    try:
        yield host
    finally:
        await host.close()


@pytest.fixture(autouse=True)
def _clear_generation_caches() -> None:
    agent_session_pool.clear_all_caches()
    agent_worker_state._tools_cache.clear()
    agent_worker_state._project_sandbox_tools_cache.clear()
    agent_worker_state._skills_cache.clear()
    agent_worker_state._skill_loader_cache.clear()
    yield
    agent_session_pool.clear_all_caches()
    agent_worker_state._tools_cache.clear()
    agent_worker_state._project_sandbox_tools_cache.clear()
    agent_worker_state._skills_cache.clear()
    agent_worker_state._skill_loader_cache.clear()


def test_session_key_contains_exact_generation_descriptor() -> None:
    first = _descriptor(generation=7, digest_character="a")
    second = _descriptor(generation=8, digest_character="b")

    first_key = agent_session_pool.generate_session_key(
        "tenant-a",
        "project-a",
        "default",
        generation_descriptor=first,
    )
    second_key = agent_session_pool.generate_session_key(
        "tenant-a",
        "project-a",
        "default",
        generation_descriptor=second,
    )

    assert first_key != second_key
    assert first.profile_id in first_key
    assert str(first.generation) in first_key
    assert first.digest in first_key


@pytest.mark.unit
async def test_tool_definition_cache_retains_old_generation_namespace(
    monkeypatch,
    generation_host: PlatformPluginRuntimeHostV2,
) -> None:
    convert_tools = MagicMock()
    converted_first = [object()]
    converted_second = [object()]
    convert_tools.side_effect = [converted_first, converted_second]

    def _convert(tools):
        return convert_tools(tools)

    monkeypatch.setattr(
        "src.infrastructure.agent.core.tool_converter.convert_tools",
        _convert,
    )

    async with pin_operation_context_v2(
        generation_host,
        operation_id="old-tool-definition-lease",
        scope=_ROOT_SCOPE,
    ) as old_operation:
        first = old_operation.descriptor
        first_result = await agent_session_pool.get_or_create_tool_definitions(
            {},
            tools_hash="same-tools",
            generation_descriptor=first,
        )
        await _publish_generation(generation_host, 8)
        old_lease_result = await agent_session_pool.get_or_create_tool_definitions(
            {},
            tools_hash="same-tools",
            generation_descriptor=first,
        )

    async with pin_operation_context_v2(
        generation_host,
        operation_id="new-tool-definition-lease",
        scope=_ROOT_SCOPE,
    ) as new_operation:
        second_result = await agent_session_pool.get_or_create_tool_definitions(
            {},
            tools_hash="same-tools",
            generation_descriptor=new_operation.descriptor,
        )

    assert first_result is converted_first
    assert second_result is converted_second
    assert old_lease_result is converted_first
    assert convert_tools.call_count == 2
    assert len(agent_session_pool._tool_definitions_cache) == 2


@pytest.mark.unit
async def test_mcp_tools_cache_retains_old_generation_namespace(
    generation_host: PlatformPluginRuntimeHostV2,
) -> None:
    first_tools = {"first": object()}
    second_tools = {"second": object()}

    async with pin_operation_context_v2(
        generation_host,
        operation_id="old-mcp-cache-lease",
        scope=_ROOT_SCOPE,
    ) as old_operation:
        first = old_operation.descriptor
        await agent_session_pool.update_mcp_tools_cache(
            "tenant-a",
            first_tools,
            generation_descriptor=first,
        )
        await _publish_generation(generation_host, 8)
        assert (
            await agent_session_pool.get_mcp_tools_from_cache(
                "tenant-a",
                generation_descriptor=first,
            )
            is first_tools
        )

    async with pin_operation_context_v2(
        generation_host,
        operation_id="new-mcp-cache-lease",
        scope=_ROOT_SCOPE,
    ) as new_operation:
        await agent_session_pool.update_mcp_tools_cache(
            "tenant-a",
            second_tools,
            generation_descriptor=new_operation.descriptor,
        )
        assert (
            await agent_session_pool.get_mcp_tools_from_cache(
                "tenant-a",
                generation_descriptor=new_operation.descriptor,
            )
            is second_tools
        )


@pytest.mark.unit
async def test_unpinned_mcp_tools_are_not_cached() -> None:
    descriptor = _descriptor(generation=7, digest_character="a")
    await agent_session_pool.update_mcp_tools_cache(
        "tenant-a",
        {"tool": object()},
        generation_descriptor=descriptor,
    )

    assert agent_session_pool._mcp_tools_cache == {}
    assert (
        await agent_session_pool.get_mcp_tools_from_cache(
            "tenant-a",
            generation_descriptor=descriptor,
        )
        is None
    )


@pytest.mark.unit
async def test_mcp_tenant_invalidation_removes_every_generation_namespace(
    generation_host: PlatformPluginRuntimeHostV2,
) -> None:
    other_tenant = {"other": object()}

    async with pin_operation_context_v2(
        generation_host,
        operation_id="first-mcp-invalidation-lease",
        scope=_ROOT_SCOPE,
    ) as first_operation:
        first = first_operation.descriptor
        await agent_session_pool.update_mcp_tools_cache(
            "tenant-a",
            {"first": object()},
            generation_descriptor=first,
        )

    await _publish_generation(generation_host, 8)
    async with pin_operation_context_v2(
        generation_host,
        operation_id="second-mcp-invalidation-lease",
        scope=_ROOT_SCOPE,
    ) as second_operation:
        second = second_operation.descriptor
        await agent_session_pool.update_mcp_tools_cache(
            "tenant-a",
            {"second": object()},
            generation_descriptor=second,
        )
        await agent_session_pool.update_mcp_tools_cache(
            "tenant-b",
            other_tenant,
            generation_descriptor=second,
        )

    first_key = agent_session_pool.generation_cache_key_v2(
        "tenant-a",
        generation_descriptor=first,
    )
    second_key = agent_session_pool.generation_cache_key_v2(
        "tenant-a",
        generation_descriptor=second,
    )
    other_key = agent_session_pool.generation_cache_key_v2(
        "tenant-b",
        generation_descriptor=second,
    )

    assert agent_session_pool.invalidate_mcp_tools_cache("tenant-a") == 2
    assert first_key not in agent_session_pool._mcp_tools_cache
    assert second_key not in agent_session_pool._mcp_tools_cache
    assert agent_session_pool._mcp_tools_cache[other_key].tools is other_tenant


@pytest.mark.unit
async def test_unpinned_tool_definitions_are_not_reused(monkeypatch) -> None:
    converted = [[object()], [object()]]
    descriptor = _descriptor(generation=7, digest_character="a")
    calls = 0

    def _convert(_tools):
        nonlocal calls
        result = converted[calls]
        calls += 1
        return result

    monkeypatch.setattr(
        "src.infrastructure.agent.core.tool_converter.convert_tools",
        _convert,
    )

    first = await agent_session_pool.get_or_create_tool_definitions(
        {},
        tools_hash="same-tools",
        generation_descriptor=descriptor,
    )
    second = await agent_session_pool.get_or_create_tool_definitions(
        {},
        tools_hash="same-tools",
        generation_descriptor=descriptor,
    )

    assert first is converted[0]
    assert second is converted[1]
    assert agent_session_pool._tool_definitions_cache == {}


@pytest.mark.unit
async def test_mismatched_explicit_descriptor_fails_closed(
    generation_host: PlatformPluginRuntimeHostV2,
) -> None:
    mismatch = _descriptor(generation=999, digest_character="f")

    async with pin_operation_context_v2(
        generation_host,
        operation_id="cache-descriptor-mismatch",
        scope=_ROOT_SCOPE,
    ):
        with pytest.raises(RuntimeV2Error) as error:
            await agent_session_pool.get_or_create_tool_definitions(
                {},
                tools_hash="same-tools",
                generation_descriptor=mismatch,
            )

    assert error.value.code == "generation_descriptor_mismatch"
    assert agent_session_pool._tool_definitions_cache == {}


@pytest.mark.unit
async def test_agent_session_pool_isolated_by_generation(
    monkeypatch,
    generation_host: PlatformPluginRuntimeHostV2,
) -> None:
    monkeypatch.setattr(
        agent_session_pool,
        "get_or_create_tool_definitions",
        AsyncMock(side_effect=lambda *_args, **_kwargs: []),
    )
    monkeypatch.setattr(
        agent_session_pool,
        "get_or_create_subagent_router",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        agent_session_pool,
        "get_system_prompt_manager",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(agent_worker_state, "current_mcp_sandbox_adapter_v2", lambda: None)
    monkeypatch.setattr(agent_worker_state, "resolve_project_base_path", lambda _project: Path("."))

    async with pin_operation_context_v2(
        generation_host,
        operation_id="old-agent-session-lease",
        scope=_ROOT_SCOPE,
    ) as old_operation:
        first = old_operation.descriptor
        first_session = await agent_session_pool.get_or_create_agent_session(
            tenant_id="tenant-a",
            project_id="project-a",
            agent_mode="default",
            tools={},
            generation_descriptor=first,
        )
        await _publish_generation(generation_host, 8)
        old_lease_session = await agent_session_pool.get_or_create_agent_session(
            tenant_id="tenant-a",
            project_id="project-a",
            agent_mode="default",
            tools={},
            generation_descriptor=first,
        )

    async with pin_operation_context_v2(
        generation_host,
        operation_id="new-agent-session-lease",
        scope=_ROOT_SCOPE,
    ) as new_operation:
        new_session = await agent_session_pool.get_or_create_agent_session(
            tenant_id="tenant-a",
            project_id="project-a",
            agent_mode="default",
            tools={},
            generation_descriptor=new_operation.descriptor,
        )

    assert first_session is old_lease_session
    assert new_session is not first_session
    assert len(agent_session_pool._agent_session_pool) == 2


@pytest.mark.unit
async def test_skill_cache_isolated_by_generation(
    monkeypatch,
    generation_host: PlatformPluginRuntimeHostV2,
) -> None:
    load_all = AsyncMock(
        side_effect=[
            SimpleNamespace(skills=[], errors=[]),
            SimpleNamespace(skills=[], errors=[]),
        ]
    )

    class _Loader:
        def __init__(self, **_kwargs) -> None:
            pass

        async def load_all(self):
            return await load_all()

    monkeypatch.setattr(
        "src.application.services.filesystem_skill_loader.FileSystemSkillLoader",
        _Loader,
    )
    monkeypatch.setattr(
        agent_worker_state, "resolve_project_base_path", lambda _project: Path.cwd()
    )
    monkeypatch.setattr(
        agent_worker_state,
        "_merge_database_skills_for_worker",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        agent_worker_state,
        "_add_workspace_runtime_skill",
        MagicMock(side_effect=lambda skills, *_args: skills),
    )

    async with pin_operation_context_v2(
        generation_host,
        operation_id="old-skill-cache-lease",
        scope=_ROOT_SCOPE,
    ) as old_operation:
        first = old_operation.descriptor
        first_skills = await agent_worker_state.get_or_create_skills(
            "tenant-a",
            "project-a",
            generation_descriptor=first,
        )
        await _publish_generation(generation_host, 8)
        old_lease_skills = await agent_worker_state.get_or_create_skills(
            "tenant-a",
            "project-a",
            generation_descriptor=first,
        )

    async with pin_operation_context_v2(
        generation_host,
        operation_id="new-skill-cache-lease",
        scope=_ROOT_SCOPE,
    ) as new_operation:
        new_skills = await agent_worker_state.get_or_create_skills(
            "tenant-a",
            "project-a",
            generation_descriptor=new_operation.descriptor,
        )

    assert first_skills is old_lease_skills
    assert new_skills is not first_skills
    assert load_all.await_count == 2
    assert len(agent_worker_state._skills_cache) == 2


@pytest.mark.unit
async def test_worker_tool_cache_switches_namespace_per_generation(
    generation_host: PlatformPluginRuntimeHostV2,
) -> None:
    first_tools = {"first": object()}
    second_tools = {"second": object()}

    async with pin_operation_context_v2(
        generation_host,
        operation_id="old-worker-tool-cache-lease",
        scope=_ROOT_SCOPE,
    ) as old_operation:
        first = old_operation.descriptor
        first_key = agent_session_pool.generation_cache_key_v2(
            "project-a",
            generation_descriptor=first,
        )
        agent_worker_state._tools_cache[first_key] = first_tools
        await _publish_generation(generation_host, 8)
        assert agent_worker_state.get_cached_tools_for_project("project-a", first) == first_tools

    async with pin_operation_context_v2(
        generation_host,
        operation_id="new-worker-tool-cache-lease",
        scope=_ROOT_SCOPE,
    ) as new_operation:
        second = new_operation.descriptor
        second_key = agent_session_pool.generation_cache_key_v2(
            "project-a",
            generation_descriptor=second,
        )
        agent_worker_state._tools_cache[second_key] = second_tools
        assert agent_worker_state.get_cached_tools_for_project("project-a", second) == second_tools


@pytest.mark.unit
def test_project_tool_invalidation_removes_every_generation_namespace() -> None:
    first = _descriptor(generation=7, digest_character="a")
    second = _descriptor(generation=8, digest_character="b")
    first_key = agent_session_pool.generation_cache_key_v2(
        "project-a",
        generation_descriptor=first,
    )
    second_key = agent_session_pool.generation_cache_key_v2(
        "project-a",
        generation_descriptor=second,
    )
    other_key = agent_session_pool.generation_cache_key_v2(
        "project-b",
        generation_descriptor=second,
    )
    first_sandbox_key = agent_session_pool.generation_cache_key_v2(
        "project-a",
        "tenant-a",
        generation_descriptor=first,
    )
    second_sandbox_key = agent_session_pool.generation_cache_key_v2(
        "project-a",
        "tenant-a",
        generation_descriptor=second,
    )
    other_sandbox_key = agent_session_pool.generation_cache_key_v2(
        "project-b",
        "tenant-a",
        generation_descriptor=second,
    )
    agent_worker_state._tools_cache.update(
        {
            first_key: {"first": object()},
            second_key: {"second": object()},
            other_key: {"other": object()},
        }
    )
    agent_worker_state._project_sandbox_tools_cache.update(
        {
            first_sandbox_key: ({"first": object()}, 1.0),
            second_sandbox_key: ({"second": object()}, 1.0),
            other_sandbox_key: ({"other": object()}, 1.0),
        }
    )

    agent_worker_state.invalidate_tools_cache("project-a")

    assert set(agent_worker_state._tools_cache) == {other_key}
    assert set(agent_worker_state._project_sandbox_tools_cache) == {other_sandbox_key}


@pytest.mark.unit
async def test_subagent_router_cache_isolated_by_generation(
    monkeypatch,
    generation_host: PlatformPluginRuntimeHostV2,
) -> None:
    routers = [object(), object()]
    router_factory = MagicMock(side_effect=routers)

    def _router(*_args, **_kwargs):
        return router_factory()

    monkeypatch.setattr(
        "src.infrastructure.agent.core.subagent_router.SubAgentRouter",
        _router,
    )
    subagents = [SimpleNamespace(name="worker")]

    async with pin_operation_context_v2(
        generation_host,
        operation_id="old-subagent-router-lease",
        scope=_ROOT_SCOPE,
    ) as old_operation:
        first = old_operation.descriptor
        first_router = await agent_session_pool.get_or_create_subagent_router(
            "tenant-a",
            subagents,
            subagents_hash="same-subagents",
            generation_descriptor=first,
        )
        await _publish_generation(generation_host, 8)
        old_lease_router = await agent_session_pool.get_or_create_subagent_router(
            "tenant-a",
            subagents,
            subagents_hash="same-subagents",
            generation_descriptor=first,
        )

    async with pin_operation_context_v2(
        generation_host,
        operation_id="new-subagent-router-lease",
        scope=_ROOT_SCOPE,
    ) as new_operation:
        new_router = await agent_session_pool.get_or_create_subagent_router(
            "tenant-a",
            subagents,
            subagents_hash="same-subagents",
            generation_descriptor=new_operation.descriptor,
        )

    assert first_router is old_lease_router
    assert new_router is not first_router
    assert router_factory.call_count == 2
    assert len(agent_session_pool._subagent_router_cache) == 2
