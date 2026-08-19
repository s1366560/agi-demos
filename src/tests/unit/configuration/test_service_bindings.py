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
        container = DIContainer(db=Mock(), graph_service=Mock())
        facade_first = getattr(container, binding.key)()
        facade_second = getattr(container, binding.key)()
        resolved = container.services.get_or_activate(binding.key)
        if facade_first is facade_second:
            assert resolved is facade_first
        else:
            assert type(resolved) is type(facade_first)

    @pytest.mark.parametrize(
        "binding",
        [b for b in _B1_BINDINGS if b.key in _ACTIVATION_SKIP],
        ids=[b.key for b in _B1_BINDINGS if b.key in _ACTIVATION_SKIP],
    )
    def test_skipped_binding_target_is_callable(self, binding: ContainerServiceBinding) -> None:
        container = DIContainer(db=Mock())
        sub_name, method_name = binding.target.split(".", 1)
        assert callable(getattr(getattr(container, sub_name), method_name))
