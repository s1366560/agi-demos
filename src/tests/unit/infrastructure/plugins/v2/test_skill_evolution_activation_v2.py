"""Skill Evolution candidates must not consume work before explicit publication admission."""

from unittest.mock import MagicMock

import pytest

from src.infrastructure.plugins.v2 import skill_evolution_runtime as runtime_module
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.unit.infrastructure.plugins.v2.test_skill_evolution_runtime_v2 import (
    _MANIFEST_PATH,
    _PROFILE_PATH,
    _plugin,
)

pytestmark = pytest.mark.unit


async def test_published_candidate_stays_paused_until_explicit_process_admission(monkeypatch):
    plugin = _plugin()
    monkeypatch.setattr(
        runtime_module, "build_skill_evolution_runtime", MagicMock(return_value=plugin)
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    try:
        publication = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=601,
            version=601,
        )
        assert publication.accepted
        plugin.on_enable.assert_not_awaited()
        plugin.capture_turn.assert_not_awaited()
        plugin.schedule_evolution.assert_not_called()
    finally:
        await host.close()


async def test_activation_requires_own_active_operation_and_is_idempotent(monkeypatch):
    from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
    from src.tests.unit.infrastructure.plugins.v2.test_skill_evolution_runtime_v2 import _activate

    plugin = _plugin()
    monkeypatch.setattr(
        runtime_module, "build_skill_evolution_runtime", MagicMock(return_value=plugin)
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    retained = None
    try:
        first = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=611,
            version=611,
        )
        assert first.accepted
        retained = await host.acquire()
        old = await _activate(host)
        await _activate(host)
        plugin.on_enable.assert_awaited_once()
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=612,
            version=612,
        )
        assert second.accepted
        generation = host.manager.current
        assert generation is not None
        service = runtime_module.SKILL_EVOLUTION_RUNTIME_SERVICE_V2
        facade = generation.resolve(service, generation.snapshot.entries[0].scope)
        assert isinstance(facade, runtime_module.SkillEvolutionGenerationSchedulerV2)
        with pytest.raises(RuntimeV2Error) as unavailable:
            await facade.capture_turn({})
        assert unavailable.value.code == "skill_evolution_runtime_unavailable"
        operation = OperationContextV2(
            generation=generation,
            operation_id="activation",
            scope=generation.snapshot.entries[0].scope,
        )
        with pytest.raises(RuntimeV2Error):
            await facade.activate(operation)
        async with operation:
            with pytest.raises(RuntimeV2Error) as wrong_generation:
                await old.activate(operation)
            assert wrong_generation.value.code == "skill_evolution_activation_mismatch"
            await facade.activate(operation)
        plugin.on_enable.assert_awaited_once()
        await facade.capture_turn({"test": True})
        plugin.capture_turn.assert_awaited_once_with({"test": True})
    finally:
        if retained is not None:
            await retained.release()
        await host.close()
    plugin.on_disable.assert_awaited_once()


async def test_unactivated_candidate_does_not_keep_retired_scheduler_running(monkeypatch):
    from src.tests.unit.infrastructure.plugins.v2.test_skill_evolution_runtime_v2 import _activate

    plugin = _plugin()
    monkeypatch.setattr(
        runtime_module, "build_skill_evolution_runtime", MagicMock(return_value=plugin)
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    retained = None
    try:
        assert (
            await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=621,
                version=621,
            )
        ).accepted
        retained = await host.acquire()
        old_generation = retained.generation
        await _activate(host)
        assert (
            await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=622,
                version=622,
            )
        ).accepted
        plugin.on_disable.assert_not_awaited()
        await retained.release()
        retained = None
        await old_generation.dispose()
        plugin.on_disable.assert_awaited_once()
        # The new generation exists but has not been admitted by the process owner.
        await _activate(host)
        assert plugin.on_enable.await_count == 2
    finally:
        if retained is not None:
            await retained.release()
        await host.close()
    assert plugin.on_disable.await_count == 2
