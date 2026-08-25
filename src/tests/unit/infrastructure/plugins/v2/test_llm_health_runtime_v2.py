"""V2 lifecycle and provider-sync coverage for the LLM health checker."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.llm_providers.models import OperationType, ProviderType
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.llm.resilience.health_checker import HealthStatus
from src.infrastructure.plugins.v2 import llm_health_runtime as runtime_module
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ARTIFACT_CONTENT_GC_MODULE_V2,
    ASYNC_SESSION_FACTORY_MODULE_V2,
)
from src.infrastructure.plugins.v2.artifact_content_services import (
    ARTIFACT_CONTENT_APPLICATION_MODULE_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.docker_monitor_runtime import DOCKER_EVENT_MONITOR_MODULE_V2
from src.infrastructure.plugins.v2.llm_health_runtime import (
    LLM_HEALTH_RUNTIME_MODULE_V2,
    LLM_HEALTH_RUNTIME_SERVICE_V2,
    LLM_HEALTH_SESSIONS_INJECT_V2,
    LlmHealthCheckerRuntimeV2,
    sync_llm_health_checker_providers_v2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_llm_health_lifecycle_survives_generation_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = AsyncMock()
    sync = AsyncMock(return_value=3)
    stop = AsyncMock()
    monkeypatch.setattr(runtime_module, "start_health_checker", start)
    monkeypatch.setattr(runtime_module, "sync_llm_health_checker_providers_v2", sync)
    monkeypatch.setattr(runtime_module, "stop_health_checker", stop)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=121,
        version=121,
    )
    assert first.accepted is True
    first_generation = host.manager.current
    assert first_generation is not None
    runtime = first_generation.resolve(
        LLM_HEALTH_RUNTIME_SERVICE_V2,
        first_generation.snapshot.entries[0].scope,
    )
    assert isinstance(runtime, LlmHealthCheckerRuntimeV2)
    assert runtime.registered_provider_types == 3

    second = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=122,
        version=122,
    )

    assert second.accepted is True
    second_generation = host.manager.current
    assert second_generation is not None
    assert (
        second_generation.resolve(
            LLM_HEALTH_RUNTIME_SERVICE_V2,
            second_generation.snapshot.entries[0].scope,
        )
        is runtime
    )
    start.assert_awaited_once_with()
    sync.assert_awaited_once_with(session_factory=async_session_factory)
    stop.assert_not_awaited()

    await host.close()
    stop.assert_awaited_once_with()


async def test_llm_health_sync_failure_nacks_before_starting_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = AsyncMock()
    sync = AsyncMock(side_effect=RuntimeError("provider registry unavailable"))
    stop = AsyncMock()
    monkeypatch.setattr(runtime_module, "start_health_checker", start)
    monkeypatch.setattr(runtime_module, "sync_llm_health_checker_providers_v2", sync)
    monkeypatch.setattr(runtime_module, "stop_health_checker", stop)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=123,
        version=123,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert host.manager.current is None
    sync.assert_awaited_once_with(session_factory=async_session_factory)
    start.assert_not_awaited()
    stop.assert_not_awaited()


async def test_llm_health_start_failure_stops_hydrated_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync = AsyncMock(return_value=2)
    start = AsyncMock(side_effect=RuntimeError("health loop unavailable"))
    stop = AsyncMock()
    monkeypatch.setattr(runtime_module, "sync_llm_health_checker_providers_v2", sync)
    monkeypatch.setattr(runtime_module, "start_health_checker", start)
    monkeypatch.setattr(runtime_module, "stop_health_checker", stop)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=124,
        version=124,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert host.manager.current is None
    sync.assert_awaited_once_with(session_factory=async_session_factory)
    start.assert_awaited_once_with()
    stop.assert_awaited_once_with()


async def test_provider_sync_selects_default_and_removes_stale_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    openai_old = SimpleNamespace(
        id="openai-old",
        provider_type=ProviderType.OPENAI,
        operation_type=OperationType.LLM,
        is_active=True,
        is_enabled=True,
        is_default=False,
        created_at=now - timedelta(days=2),
    )
    openai_default = SimpleNamespace(
        id="openai-default",
        provider_type=ProviderType.OPENAI,
        operation_type=OperationType.LLM,
        is_active=True,
        is_enabled=True,
        is_default=True,
        created_at=now,
    )
    embedding = SimpleNamespace(
        id="openai-embedding",
        provider_type=ProviderType.OPENAI,
        operation_type=OperationType.EMBEDDING,
        is_active=True,
        is_enabled=True,
        is_default=True,
        created_at=now,
    )
    repository = MagicMock(
        list_active=AsyncMock(return_value=[openai_old, openai_default, embedding])
    )
    monkeypatch.setattr(
        runtime_module,
        "SQLAlchemyProviderRepository",
        MagicMock(return_value=repository),
    )
    session = object()

    @asynccontextmanager
    async def session_factory():
        yield session

    checker = MagicMock()
    checker.get_current_status.return_value = {ProviderType.ANTHROPIC: HealthStatus.UNKNOWN}

    registered = await sync_llm_health_checker_providers_v2(
        session_factory=session_factory,
        checker=checker,
    )

    assert registered == 1
    checker.unregister_provider.assert_called_once_with(ProviderType.ANTHROPIC)
    checker.register_provider.assert_called_once_with(ProviderType.OPENAI, openai_default)


async def test_llm_health_runtime_rejects_missing_sessions_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref
            in {
                ARTIFACT_CONTENT_APPLICATION_MODULE_V2,
                ARTIFACT_CONTENT_GC_MODULE_V2,
                ASYNC_SESSION_FACTORY_MODULE_V2,
                DOCKER_EVENT_MONITOR_MODULE_V2,
            }
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=125)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-llm-health-checker" in str(error.value)


def test_llm_health_runtime_is_an_explicit_process_boundary_entry() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        item for item in profile.entries if item.module_ref == LLM_HEALTH_RUNTIME_MODULE_V2
    )
    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )
    startup_source = (_ROOT / "src/infrastructure/adapters/primary/web/startup/llm.py").read_text(
        encoding="utf-8"
    )
    startup_exports = (
        _ROOT / "src/infrastructure/adapters/primary/web/startup/__init__.py"
    ).read_text(encoding="utf-8")
    runtime_source = (_ROOT / "src/infrastructure/plugins/v2/llm_health_runtime.py").read_text(
        encoding="utf-8"
    )

    assert entry.inject == {
        LLM_HEALTH_SESSIONS_INJECT_V2: "service:persistence.async-session-factory"
    }
    assert entry.restart_policy.value == "process-boundary"
    assert "sync_health_checker_providers" not in main_source
    assert "start_health_checker" not in main_source
    assert "stop_health_checker" not in main_source
    assert "sync_health_checker_providers" not in startup_source
    assert "sync_health_checker_providers" not in startup_exports
    assert "artifact_content_gc_runtime" not in runtime_source
