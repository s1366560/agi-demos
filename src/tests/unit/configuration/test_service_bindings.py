"""Equivalence tests for the I1 shadow composition root (service bindings).

Each batch asserts that the lazy service declared for a container accessor
resolves to an equivalent instance: identity when the facade caches, same
type when the facade is a per-call factory.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.configuration.di_container import DIContainer
from src.configuration.service_bindings import (
    CONTAINER_SERVICE_BINDINGS,
    ContainerServiceBinding,
)

_B1_GROUPS = ("infra", "memory", "auth")

# Accessors whose first call performs environment-dependent work (Docker
# recovery, credential chains). Their bindings are validated structurally
# instead of being activated in unit tests.
_ACTIVATION_SKIP = frozenset({"sandbox_adapter", "storage_service"})


def _bindings(groups: tuple[str, ...]) -> list[ContainerServiceBinding]:
    return [b for b in CONTAINER_SERVICE_BINDINGS if b.group in groups]


def _assert_equivalence(container: DIContainer, binding: ContainerServiceBinding) -> None:
    """Assert registry resolution matches facade behavior.

    Retired accessors (e.g. legacy workspace DI rows) raise by design; the
    registry must surface the same failure. Live accessors match by identity
    when the facade caches, otherwise by type.
    """
    try:
        facade_first = getattr(container, binding.key)()
    except Exception as exc:
        with pytest.raises(type(exc)):
            container.services.get_or_activate(binding.key)
        return
    facade_second = getattr(container, binding.key)()
    resolved = container.services.get_or_activate(binding.key)
    if facade_first is facade_second:
        assert resolved is facade_first
    else:
        assert type(resolved) is type(facade_first)


_B1_BINDINGS = _bindings(_B1_GROUPS)
_B1_ACTIVATABLE = [b for b in _B1_BINDINGS if b.key not in _ACTIVATION_SKIP]


@pytest.mark.unit
class TestServiceBindingsB1:
    """Batch B1: infra singletons + memory domain + auth domain."""

    def test_container_declares_b1_services(self) -> None:
        container = DIContainer(db=Mock(), graph_service=Mock())
        for binding in _B1_BINDINGS:
            assert container.services.get_or_activate(binding.key) is not None or (
                binding.allow_none
            )

    @pytest.mark.parametrize(
        "binding",
        _B1_ACTIVATABLE,
        ids=[b.key for b in _B1_ACTIVATABLE],
    )
    def test_registry_matches_facade(self, binding: ContainerServiceBinding) -> None:
        _assert_equivalence(DIContainer(db=Mock(), graph_service=Mock()), binding)

    @pytest.mark.parametrize(
        "binding",
        [b for b in _B1_BINDINGS if b.key in _ACTIVATION_SKIP],
        ids=[b.key for b in _B1_BINDINGS if b.key in _ACTIVATION_SKIP],
    )
    def test_skipped_binding_target_is_callable(self, binding: ContainerServiceBinding) -> None:
        container = DIContainer(db=Mock())
        sub_name, method_name = binding.target.split(".", 1)
        assert callable(getattr(getattr(container, sub_name), method_name))


_GROUP_B2 = ("task",)
_B2_BINDINGS = _bindings(_GROUP_B2)
_B2_ACTIVATABLE = [b for b in _B2_BINDINGS if b.key not in _ACTIVATION_SKIP]


@pytest.mark.unit
class TestServiceBindingsB2:
    """Batch B2: task/cron/reflection domain."""

    @pytest.mark.parametrize(
        "binding",
        _B2_ACTIVATABLE,
        ids=[b.key for b in _B2_ACTIVATABLE],
    )
    def test_registry_matches_facade(self, binding: ContainerServiceBinding) -> None:
        _assert_equivalence(DIContainer(db=Mock(), graph_service=Mock()), binding)


_GROUP_B3 = ("workspace",)
_B3_BINDINGS = _bindings(_GROUP_B3)
_B3_ACTIVATABLE = [b for b in _B3_BINDINGS if b.key not in _ACTIVATION_SKIP]


@pytest.mark.unit
class TestServiceBindingsB3:
    """Batch B3: workspace/blackboard domain."""

    @pytest.mark.parametrize(
        "binding",
        _B3_ACTIVATABLE,
        ids=[b.key for b in _B3_ACTIVATABLE],
    )
    def test_registry_matches_facade(self, binding: ContainerServiceBinding) -> None:
        _assert_equivalence(DIContainer(db=Mock(), graph_service=Mock()), binding)


_GROUP_B4 = ("instance",)
_B4_BINDINGS = _bindings(_GROUP_B4)
_B4_ACTIVATABLE = [b for b in _B4_BINDINGS if b.key not in _ACTIVATION_SKIP]


@pytest.mark.unit
class TestServiceBindingsB4:
    """Batch B4: gene/evolution/instance domain."""

    @pytest.mark.parametrize(
        "binding",
        _B4_ACTIVATABLE,
        ids=[b.key for b in _B4_ACTIVATABLE],
    )
    def test_registry_matches_facade(self, binding: ContainerServiceBinding) -> None:
        _assert_equivalence(DIContainer(db=Mock(), graph_service=Mock()), binding)


_GROUP_B5 = ("agent",)
_B5_BINDINGS = _bindings(_GROUP_B5)
_B5_ACTIVATABLE = [b for b in _B5_BINDINGS if b.key not in _ACTIVATION_SKIP]


@pytest.mark.unit
class TestServiceBindingsB5:
    """Batch B5: agent/llm/sandbox/mcp domain."""

    @pytest.mark.parametrize(
        "binding",
        _B5_ACTIVATABLE,
        ids=[b.key for b in _B5_ACTIVATABLE],
    )
    def test_registry_matches_facade(self, binding: ContainerServiceBinding) -> None:
        _assert_equivalence(DIContainer(db=Mock(), graph_service=Mock()), binding)
