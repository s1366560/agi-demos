"""Zero-reference gates for the retired static memory composition seam."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.configuration.di_container import DIContainer
from src.configuration.service_bindings import CONTAINER_SERVICE_BINDINGS
from src.infrastructure.plugins.v2.memory_services import (
    MEMORY_APPLICATION_MODULE_V2,
    MEMORY_REPOSITORY_PROVIDER_MODULE_V2,
    memory_service_definitions_v2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_RETIRED_ACCESSORS = {
    "memory_repository",
    "memory_service",
    "search_service",
    "create_memory_use_case",
    "get_memory_use_case",
    "list_memories_use_case",
    "delete_memory_use_case",
    "search_memory_use_case",
}


def test_memory_runtime_definitions_only_keep_authoritative_modules() -> None:
    module_refs = tuple(definition.module_ref for definition in memory_service_definitions_v2())

    assert module_refs == (
        MEMORY_REPOSITORY_PROVIDER_MODULE_V2,
        MEMORY_APPLICATION_MODULE_V2,
    )


def test_static_memory_container_and_di_facades_are_removed() -> None:
    binding_keys = {binding.key for binding in CONTAINER_SERVICE_BINDINGS}

    assert not (_ROOT / "src/configuration/containers/memory_container.py").exists()
    assert _RETIRED_ACCESSORS.isdisjoint(vars(DIContainer))
    assert _RETIRED_ACCESSORS.isdisjoint(binding_keys)
    assert all(binding.group != "memory" for binding in CONTAINER_SERVICE_BINDINGS)
