"""V2 process lifecycle coverage for the Skill Evolution scheduler."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.plugins.v2 import skill_evolution_runtime as runtime_module
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.llm_client_service import TENANT_LLM_CLIENT_FACTORY_MODULE_V2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.reflection_runtime import REFLECTION_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.skill_evolution_runtime import (
    SKILL_EVOLUTION_LLM_CLIENTS_INJECT_V2,
    SKILL_EVOLUTION_RUNTIME_MODULE_V2,
    SKILL_EVOLUTION_RUNTIME_SERVICE_V2,
    SKILL_EVOLUTION_SESSIONS_INJECT_V2,
    SkillEvolutionSchedulerRuntimeV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


@pytest.fixture(autouse=True)
def _clear_skill_evolution_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SKILL_EVOLUTION_ENABLED",
        "SKILL_EVOLUTION_MIN_SESSIONS",
        "SKILL_EVOLUTION_SCORING_MIN_SESSIONS",
        "SKILL_EVOLUTION_MIN_AVG_SCORE",
        "SKILL_EVOLUTION_INTERVAL_MINUTES",
        "SKILL_EVOLUTION_SESSION_RETENTION_DAYS",
        "SKILL_EVOLUTION_LLM_MODEL",
        "SKILL_EVOLUTION_MAX_SESSIONS_PER_BATCH",
        "SKILL_EVOLUTION_LLM_CONCURRENCY",
        "SKILL_EVOLUTION_LLM_TIMEOUT_SECONDS",
        "SKILL_EVOLUTION_PUBLISH_MODE",
        "SKILL_EVOLUTION_AUTO_APPLY",
    ):
        monkeypatch.delenv(name, raising=False)


def _plugin() -> SimpleNamespace:
    return SimpleNamespace(
        on_enable=AsyncMock(),
        on_disable=AsyncMock(),
        record_tool_event=AsyncMock(side_effect=lambda payload: dict(payload)),
        capture_turn=AsyncMock(side_effect=lambda payload: dict(payload)),
        schedule_evolution=MagicMock(
            return_value={"scheduled": True, "reason": "manual", "status": "queued"}
        ),
    )


async def test_skill_evolution_starts_once_across_generation_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = _plugin()
    build = MagicMock(return_value=plugin)
    monkeypatch.setattr(runtime_module, "build_skill_evolution_runtime", build)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=141,
        version=141,
    )
    assert first.accepted is True
    first_generation = host.manager.current
    assert first_generation is not None
    runtime = first_generation.resolve(
        SKILL_EVOLUTION_RUNTIME_SERVICE_V2,
        first_generation.snapshot.entries[0].scope,
    )
    assert isinstance(runtime, SkillEvolutionSchedulerRuntimeV2)

    second = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=142,
        version=142,
    )

    assert second.accepted is True
    second_generation = host.manager.current
    assert second_generation is not None
    assert (
        second_generation.resolve(
            SKILL_EVOLUTION_RUNTIME_SERVICE_V2,
            second_generation.snapshot.entries[0].scope,
        )
        is runtime
    )
    build.assert_called_once()
    plugin.on_enable.assert_awaited_once_with()
    plugin.on_disable.assert_not_awaited()

    await host.close()
    plugin.on_disable.assert_awaited_once_with()


async def test_skill_evolution_start_failure_nacks_and_cleans_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = _plugin()
    plugin.on_enable.side_effect = RuntimeError("scheduler unavailable")
    monkeypatch.setattr(
        runtime_module,
        "build_skill_evolution_runtime",
        MagicMock(return_value=plugin),
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=143,
        version=143,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert host.manager.current is None
    plugin.on_enable.assert_awaited_once_with()
    plugin.on_disable.assert_awaited_once_with()


async def test_skill_evolution_config_change_requires_process_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = _plugin()
    monkeypatch.setattr(
        runtime_module,
        "build_skill_evolution_runtime",
        MagicMock(return_value=plugin),
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=144,
        version=144,
    )
    assert first.accepted is True

    def disable_scheduler(document):
        return replace(
            document,
            entries=tuple(
                replace(entry, config={**entry.config, "enabled": False})
                if entry.module_ref == SKILL_EVOLUTION_RUNTIME_MODULE_V2
                else entry
                for entry in document.entries
            ),
        )

    rejected = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=145,
        version=145,
        profile_projector=disable_scheduler,
    )

    assert rejected.accepted is False
    assert rejected.receipt.error_code == "process_boundary_required"
    assert host.manager.current is not None
    assert host.manager.current.descriptor.generation == 144
    plugin.on_disable.assert_not_awaited()
    await host.close()
    plugin.on_disable.assert_awaited_once_with()


async def test_skill_evolution_rejects_missing_llm_client_factory_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref
            in {TENANT_LLM_CLIENT_FACTORY_MODULE_V2, REFLECTION_RUNTIME_MODULE_V2}
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=146)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-skill-evolution-scheduler" in str(error.value)


def test_skill_evolution_contract_and_static_authority_retirement_are_explicit() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    runtime_entry = next(
        item for item in profile.entries if item.module_ref == SKILL_EVOLUTION_RUNTIME_MODULE_V2
    )
    lifecycle_entry = next(
        item
        for item in profile.entries
        if item.module_ref == "builtin://memstack/agent/skill-evolution-lifecycle"
    )
    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )
    container_source = (_ROOT / "src/configuration/di_container.py").read_text(encoding="utf-8")
    routes_source = (_ROOT / "src/infrastructure/adapters/primary/web/routers/skills.py").read_text(
        encoding="utf-8"
    )
    worker_source = (_ROOT / "src/infrastructure/agent/state/agent_worker_state.py").read_text(
        encoding="utf-8"
    )

    assert runtime_entry.inject == {
        SKILL_EVOLUTION_LLM_CLIENTS_INJECT_V2: "service:llm.tenant-client-factory",
        SKILL_EVOLUTION_SESSIONS_INJECT_V2: "service:persistence.async-session-factory",
    }
    assert runtime_entry.restart_policy.value == "process-boundary"
    assert lifecycle_entry.inject == {
        "scheduler": SKILL_EVOLUTION_RUNTIME_SERVICE_V2,
    }
    assert "app.state.skill_evolution_plugin" not in main_source
    assert "def skill_evolution_plugin(" not in container_source
    assert "container.skill_evolution_plugin()" not in routes_source
    assert "configure_skill_evolution_capture" not in worker_source
