"""Unit tests for the DI container to ServiceRegistry migration bridge."""

from __future__ import annotations

import pytest

from src.infrastructure.plugins.di_bridge import (
    ServiceBinding,
    bind_container_services,
    registry_accessor,
)
from src.infrastructure.plugins.service_registry import (
    ServiceDependencyError,
    ServiceRegistry,
)


class _FakeContainer:
    def __init__(self) -> None:
        self._redis: object | None = None
        self.calls: list[str] = []

    def redis_client(self) -> object:
        self.calls.append("redis_client")
        if self._redis is None:
            self._redis = object()
        return self._redis

    def graph_service(self) -> object:
        self.calls.append("graph_service")
        return object()


@pytest.mark.unit
async def test_bound_services_share_the_container_singleton() -> None:
    registry = ServiceRegistry()
    container = _FakeContainer()
    bind_container_services(
        registry,
        container,
        [ServiceBinding(key="redis", accessor="redis_client")],
    )

    await registry.activate_all()

    container_instance = container.redis_client()
    assert registry.get("redis") is container_instance


@pytest.mark.unit
async def test_registry_accessor_matches_legacy_call_shape() -> None:
    registry = ServiceRegistry()
    container = _FakeContainer()
    bind_container_services(
        registry,
        container,
        [ServiceBinding(key="redis", accessor="redis_client")],
    )
    await registry.activate_all()

    legacy_style = registry_accessor(registry, "redis")

    assert legacy_style() is container.redis_client()


@pytest.mark.unit
async def test_inject_orders_activation() -> None:
    registry = ServiceRegistry()
    container = _FakeContainer()
    bind_container_services(
        registry,
        container,
        [
            ServiceBinding(key="graph", accessor="graph_service", inject=("redis",)),
            ServiceBinding(key="redis", accessor="redis_client"),
        ],
    )

    activated = await registry.activate_all()

    assert activated.index("redis") < activated.index("graph")


@pytest.mark.unit
async def test_missing_accessor_fails_at_bind_time() -> None:
    registry = ServiceRegistry()
    container = _FakeContainer()

    with pytest.raises(ServiceDependencyError, match="no_such_method"):
        bind_container_services(
            registry,
            container,
            [ServiceBinding(key="ghost", accessor="no_such_method")],
        )


@pytest.mark.unit
async def test_duplicate_bind_rejected_unless_replace() -> None:
    registry = ServiceRegistry()
    container = _FakeContainer()
    bindings = [ServiceBinding(key="redis", accessor="redis_client")]
    bind_container_services(registry, container, bindings)

    from src.infrastructure.plugins.service_registry import ServiceConflictError

    with pytest.raises(ServiceConflictError):
        bind_container_services(registry, container, bindings)

    bind_container_services(registry, container, bindings, replace=True)
    await registry.activate_all()
    assert registry.has("redis")
