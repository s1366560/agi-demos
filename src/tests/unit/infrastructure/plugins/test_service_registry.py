"""Unit tests for the Cordis-style platform service registry."""

from __future__ import annotations

import pytest

from src.infrastructure.plugins.service_registry import (
    ServiceConflictError,
    ServiceDeclaration,
    ServiceDependencyError,
    ServiceRegistry,
)


@pytest.mark.unit
async def test_register_get_has_unregister() -> None:
    registry = ServiceRegistry()
    disposed: list[str] = []

    _ = registry.register("tools", object(), dispose=lambda: disposed.append("tools"))
    assert registry.has("tools")
    assert registry.get("tools") is not None
    assert registry.keys() == ("tools",)

    assert registry.unregister("tools") is True
    assert disposed == ["tools"]
    assert not registry.has("tools")
    assert registry.unregister("tools") is False


@pytest.mark.unit
async def test_duplicate_register_rejected_and_replace_disposes_old() -> None:
    registry = ServiceRegistry()
    disposed: list[str] = []
    registry.register("llm", "v1", dispose=lambda: disposed.append("v1"))

    with pytest.raises(ServiceConflictError):
        registry.register("llm", "v2")

    registry.register("llm", "v2", replace=True)
    assert disposed == ["v1"]
    assert registry.get("llm") == "v2"


@pytest.mark.unit
async def test_activate_all_runs_in_topological_order() -> None:
    registry = ServiceRegistry()
    order: list[str] = []

    def make(name: str):
        def factory(ctx) -> str:
            order.append(name)
            return name

        return factory

    registry.declare(ServiceDeclaration(key="sessions", factory=make("sessions")))
    registry.declare(ServiceDeclaration(key="tools", factory=make("tools"), inject=("sessions",)))
    registry.declare(
        ServiceDeclaration(
            key="agent-loop",
            factory=make("agent-loop"),
            inject=("tools", "sessions"),
        )
    )

    activated = await registry.activate_all()

    assert order.index("sessions") < order.index("tools") < order.index("agent-loop")
    assert activated == registry.keys()


@pytest.mark.unit
async def test_factory_context_limits_resolution_to_declared_injects() -> None:
    registry = ServiceRegistry()
    registry.register("sessions", "session-store")
    registry.register("secret", "hidden")
    seen: dict[str, object] = {}

    def factory(ctx) -> str:
        seen["dep"] = ctx.get("sessions")
        with pytest.raises(PermissionError):
            ctx.get("secret")
        return "tool-registry"

    registry.declare(ServiceDeclaration(key="tools", factory=factory, inject=("sessions",)))
    await registry.activate_all()

    assert seen["dep"] == "session-store"
    assert registry.get("tools") == "tool-registry"


@pytest.mark.unit
async def test_missing_dependency_raises_actionable_error() -> None:
    registry = ServiceRegistry()
    registry.declare(
        ServiceDeclaration(key="tools", factory=lambda ctx: object(), inject=("sessions",))
    )

    with pytest.raises(ServiceDependencyError, match="sessions"):
        await registry.activate_all()


@pytest.mark.unit
async def test_dependency_cycle_raises_with_members() -> None:
    registry = ServiceRegistry()
    registry.declare(ServiceDeclaration(key="a", factory=lambda ctx: object(), inject=("b",)))
    registry.declare(ServiceDeclaration(key="b", factory=lambda ctx: object(), inject=("a",)))

    with pytest.raises(ServiceDependencyError, match="cycle"):
        await registry.activate_all()


@pytest.mark.unit
async def test_async_factory_is_awaited() -> None:
    registry = ServiceRegistry()

    async def factory(ctx) -> str:
        return "async-service"

    registry.declare(ServiceDeclaration(key="async", factory=factory))
    await registry.activate_all()

    assert registry.get("async") == "async-service"


@pytest.mark.unit
async def test_activation_failure_unwinds_this_call_only() -> None:
    registry = ServiceRegistry()
    registry.register("base", "preexisting")
    disposed: list[str] = []

    def good(ctx) -> str:
        return "good"

    def bad(ctx) -> None:
        return None

    registry.declare(ServiceDeclaration(key="good", factory=good))
    registry.declare(
        ServiceDeclaration(key="bad", factory=bad, inject=("good",)),
    )

    with pytest.raises(ServiceDependencyError):
        await registry.activate_all()

    assert not registry.has("good")
    assert registry.get("base") == "preexisting"
    assert disposed == []


@pytest.mark.unit
async def test_close_unwinds_in_reverse_activation_order() -> None:
    registry = ServiceRegistry()
    disposed: list[str] = []
    for name in ("one", "two", "three"):
        registry.register(name, object(), dispose=lambda n=name: disposed.append(n))

    await registry.close()

    assert disposed == ["three", "two", "one"]
    assert registry.keys() == ()


@pytest.mark.unit
async def test_closeable_instances_dispose_via_close_method() -> None:
    registry = ServiceRegistry()

    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    registry.declare(ServiceDeclaration(key="client", factory=lambda ctx: FakeClient()))
    await registry.activate_all()
    client = registry.get("client")

    await registry.close()

    assert client.closed is True


@pytest.mark.unit
async def test_snapshot_reports_activation_order_and_owner() -> None:
    registry = ServiceRegistry()
    registry.register("tools", object(), owner="tools-plugin")
    registry.register("llm", object())

    snapshot = registry.snapshot()

    assert snapshot == [
        {"key": "tools", "owner": "tools-plugin"},
        {"key": "llm", "owner": None},
    ]


@pytest.mark.unit
async def test_declare_duplicate_rejected_unless_replace() -> None:
    registry = ServiceRegistry()
    declaration = ServiceDeclaration(key="tools", factory=lambda ctx: object())
    registry.declare(declaration)

    with pytest.raises(ServiceConflictError):
        registry.declare(declaration)

    registry.declare(
        ServiceDeclaration(key="tools", factory=lambda ctx: "replaced"),
        replace=True,
    )
    await registry.activate_all()
    assert registry.get("tools") == "replaced"


@pytest.mark.unit
async def test_empty_key_rejected() -> None:
    registry = ServiceRegistry()
    with pytest.raises(ValueError, match="non-empty"):
        registry.register("  ", object())
