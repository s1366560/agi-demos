"""Bridge for incrementally migrating DIContainer accessors onto the registry.

Phase P1 of the full-pluginization roadmap moves the hardcoded composition
root onto :class:`ServiceRegistry`. The migration is incremental: container
accessors are bound as lazy service declarations while the legacy facade
keeps serving callers, so both paths return the *same* instance (shadow
operation) until the container method is retired.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .service_registry import (
    ServiceContext,
    ServiceDeclaration,
    ServiceDependencyError,
    ServiceRegistry,
)

__all__ = [
    "ServiceBinding",
    "bind_container_services",
    "registry_accessor",
]


@dataclass(frozen=True)
class ServiceBinding:
    """Map one container accessor onto a service key and its dependencies."""

    key: str
    accessor: str
    inject: tuple[str, ...] = ()


def bind_container_services(
    registry: ServiceRegistry,
    container: object,
    bindings: tuple[ServiceBinding, ...] | list[ServiceBinding],
    *,
    owner: str = "di-container",
    replace: bool = False,
) -> tuple[str, ...]:
    """Declare container accessors as lazy services and return bound keys.

    Factories call the accessor at activation time, so singleton caching in
    the container is preserved and both facades share one instance.
    """
    bound: list[str] = []
    for binding in bindings:
        _validate_accessor(container, binding)
        registry.declare(
            ServiceDeclaration(
                key=binding.key,
                factory=_container_factory(container, binding.accessor),
                inject=binding.inject,
                owner=owner,
            ),
            replace=replace,
        )
        bound.append(binding.key)
    return tuple(bound)


def registry_accessor(registry: ServiceRegistry, key: str) -> Callable[[], object]:
    """Return a zero-arg accessor matching the legacy container method shape."""

    def accessor() -> object:
        return registry.get(key)

    return accessor


def _validate_accessor(container: object, binding: ServiceBinding) -> None:
    if not callable(getattr(container, binding.accessor, None)):
        raise ServiceDependencyError(
            f"container has no callable accessor {binding.accessor} for key {binding.key}"
        )


def _container_factory(container: object, accessor: str) -> Callable[[ServiceContext], object]:
    def factory(ctx: ServiceContext) -> object:
        method = getattr(container, accessor)
        return method()

    return factory
