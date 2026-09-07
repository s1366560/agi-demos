"""Restricted, side-effect-aware route materialization for protocol v2 catalogs."""

from __future__ import annotations

import ast
import builtins
import dis
import functools
import inspect
import textwrap
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import CodeType, FunctionType, MappingProxyType, ModuleType
from typing import Any, cast, overload

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import BaseRoute

from .route_contract_metadata import (
    RouteRegistrationViolationV2,
    RouteSignatureV2,
    create_route_contract_app_v2,
    ordered_route_signatures_v2,
    route_openapi_digest_v2,
)

_GLOBAL_WRITE_OPCODES_V2 = frozenset({"DELETE_GLOBAL", "STORE_GLOBAL"})
_FORBIDDEN_EFFECT_REFERENCE_OPCODES_V2 = frozenset(
    {"DELETE_ATTR", "LOAD_ATTR", "LOAD_CONST", "LOAD_METHOD", "STORE_ATTR"}
)
_ROUTE_REGISTRATION_NAMES_V2 = frozenset(
    {
        "APIRouter",
        "add_api_route",
        "add_api_websocket_route",
        "include_router",
        "routes",
    }
)
_FORBIDDEN_EFFECT_ATTRIBUTE_NAMES_V2 = frozenset(
    {
        "add_exception_handler",
        "add_middleware",
        "__dict__",
        "__getattribute__",
        "_app",
        "_rollback",
        "_router",
        "_routes",
        "exception_handlers",
        "lifespan",
        "lifespan_context",
        "middleware",
        "middleware_stack",
        "mount",
        "on_event",
        "openapi",
        "openapi_schema",
        "state",
        "user_middleware",
    }
)
_RESOURCE_MODULE_ROOTS_V2 = frozenset(
    {
        "aiohttp",
        "boto3",
        "httpx",
        "multiprocessing",
        "os",
        "pathlib",
        "psycopg",
        "redis",
        "requests",
        "socket",
        "sqlite3",
        "subprocess",
        "urllib",
    }
)
_RESOURCE_BUILTINS_V2 = frozenset({builtins.eval, builtins.exec, builtins.open})


class RouteRegistrationClassificationV2(StrEnum):
    """Structural effect class for one frozen builtin route inventory row."""

    ROUTES_ONLY = "routes-only"
    HYBRID = "hybrid"
    NON_ROUTE = "non-route"


@dataclass(frozen=True, kw_only=True)
class RouteRegistrationCallableInspectionV2:
    """Objective bytecode facts used to decide whether materialization is safe."""

    global_writes: tuple[str, ...]
    resource_references: tuple[str, ...]
    forbidden_effect_references: tuple[str, ...]
    declares_routes: bool

    @property
    def safe_to_execute(self) -> bool:
        return not (
            self.global_writes
            or self.resource_references
            or self.forbidden_effect_references
        )


@dataclass(frozen=True, kw_only=True)
class RouteRegistrationMaterializationV2:
    """Isolated route-only output or a fail-closed structural classification."""

    classification: RouteRegistrationClassificationV2
    ordered_signatures: tuple[RouteSignatureV2, ...]
    openapi_digest: str | None
    rejections: tuple[str, ...] = ()


class _RestrictedRouterV2:
    """Allow direct route appends without exposing APIRouter lifecycle methods."""

    __slots__ = ("_app", "_routes")

    _app: FastAPI  # pyright: ignore[reportUninitializedInstanceVariable]
    _routes: _RestrictedRouteCollectionV2  # pyright: ignore[reportUninitializedInstanceVariable]

    def __init__(self, app: FastAPI) -> None:
        super().__init__()
        object.__setattr__(self, "_app", app)
        object.__setattr__(self, "_routes", _RestrictedRouteCollectionV2(app.router.routes))

    def __setattr__(self, name: str, value: object) -> None:
        raise RouteRegistrationViolationV2(f"router.{name}")

    def __getattribute__(self, name: str) -> Any:  # noqa: ANN401
        if name in {"_app", "_routes", "__dict__", "__getattribute__"}:
            raise RouteRegistrationViolationV2(f"router.{name}")
        return object.__getattribute__(self, name)

    @property
    def routes(self) -> _RestrictedRouteCollectionV2:
        return cast(
            "_RestrictedRouteCollectionV2",
            object.__getattribute__(self, "_routes"),
        )

    def include_router(self, router: APIRouter, **kwargs: object) -> None:
        app = cast(FastAPI, object.__getattribute__(self, "_app"))
        app.include_router(router, **cast("dict[str, Any]", kwargs))

    def add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        **kwargs: object,
    ) -> None:
        app = cast(FastAPI, object.__getattribute__(self, "_app"))
        app.router.add_api_route(path, endpoint, **cast("dict[str, Any]", kwargs))

    def add_api_websocket_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        **kwargs: object,
    ) -> None:
        app = cast(FastAPI, object.__getattribute__(self, "_app"))
        app.router.add_api_websocket_route(
            path,
            endpoint,
            **cast("dict[str, Any]", kwargs),
        )

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        raise RouteRegistrationViolationV2(f"router.{name}")


class _RestrictedRouteCollectionV2(Sequence[BaseRoute]):
    """Read-only route sequence with one typed append seam for legacy helpers."""

    __slots__ = ("_routes",)

    _routes: list[BaseRoute]

    def __init__(self, routes: list[BaseRoute]) -> None:
        super().__init__()
        object.__setattr__(self, "_routes", routes)

    def __setattr__(self, name: str, value: object) -> None:
        raise RouteRegistrationViolationV2(f"router.routes.{name}")

    def __getattribute__(self, name: str) -> Any:  # noqa: ANN401
        if name in {"_routes", "__dict__", "__getattribute__"}:
            raise RouteRegistrationViolationV2(f"router.routes.{name}")
        return object.__getattribute__(self, name)

    def __len__(self) -> int:
        routes = cast("list[BaseRoute]", object.__getattribute__(self, "_routes"))
        return len(routes)

    @overload
    def __getitem__(self, index: int) -> BaseRoute: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[BaseRoute]: ...

    def __getitem__(self, index: int | slice) -> BaseRoute | Sequence[BaseRoute]:
        routes = cast("list[BaseRoute]", object.__getattribute__(self, "_routes"))
        return routes[index]

    def append(self, route: BaseRoute) -> None:
        if not isinstance(route, (APIRoute, APIWebSocketRoute)):
            raise RouteRegistrationViolationV2("router.routes.append")
        routes = cast("list[BaseRoute]", object.__getattribute__(self, "_routes"))
        routes.append(route)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        raise RouteRegistrationViolationV2(f"router.routes.{name}")


class RouteRegistrationSinkV2:
    """Minimal FastAPI-compatible surface permitted during route preflight."""

    __slots__ = ("_app", "_router")

    _app: FastAPI  # pyright: ignore[reportUninitializedInstanceVariable]
    _router: _RestrictedRouterV2  # pyright: ignore[reportUninitializedInstanceVariable]

    def __init__(self) -> None:
        super().__init__()
        app = create_route_contract_app_v2()
        object.__setattr__(self, "_app", app)
        object.__setattr__(self, "_router", _RestrictedRouterV2(app))

    def __setattr__(self, name: str, value: object) -> None:
        raise RouteRegistrationViolationV2(name)

    def __getattribute__(self, name: str) -> Any:  # noqa: ANN401
        if name in {"_app", "_router", "__dict__", "__getattribute__"}:
            raise RouteRegistrationViolationV2(name)
        return object.__getattribute__(self, name)

    @property
    def router(self) -> _RestrictedRouterV2:
        return cast("_RestrictedRouterV2", object.__getattribute__(self, "_router"))

    def include_router(self, router: APIRouter, **kwargs: object) -> None:
        app = cast(FastAPI, object.__getattribute__(self, "_app"))
        app.include_router(router, **cast("dict[str, Any]", kwargs))

    def add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        **kwargs: object,
    ) -> None:
        app = cast(FastAPI, object.__getattribute__(self, "_app"))
        app.add_api_route(path, endpoint, **cast("dict[str, Any]", kwargs))

    def add_api_websocket_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        **kwargs: object,
    ) -> None:
        app = cast(FastAPI, object.__getattribute__(self, "_app"))
        app.add_api_websocket_route(
            path,
            endpoint,
            **cast("dict[str, Any]", kwargs),
        )

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        raise RouteRegistrationViolationV2(name)


def inspect_route_registration_callable_v2(
    target: Callable[..., object],
) -> RouteRegistrationCallableInspectionV2:
    """Recursively inspect global writes and explicit resource-capable references."""
    functions = _reachable_functions_v2(target)
    global_writes: set[str] = set()
    resource_references: set[str] = set()
    forbidden_effect_references: set[str] = set()
    declares_routes = False
    for function in functions:
        codes = _executed_code_objects_v2(function)
        for code in codes:
            for instruction in dis.get_instructions(code):
                if instruction.opname in _GLOBAL_WRITE_OPCODES_V2:
                    location = f"{function.__module__}.{function.__qualname__}:"
                    global_writes.add(location + f"{instruction.opname}:{instruction.argval}")
                if (
                    instruction.opname in _FORBIDDEN_EFFECT_REFERENCE_OPCODES_V2
                    and instruction.argval in _FORBIDDEN_EFFECT_ATTRIBUTE_NAMES_V2
                ):
                    location = f"{function.__module__}.{function.__qualname__}:"
                    forbidden_effect_references.add(
                        location + f"{instruction.opname}:{instruction.argval}"
                    )
                if instruction.argval in _ROUTE_REGISTRATION_NAMES_V2:
                    declares_routes = True
            resource_references.update(_resource_references_v2(function, code))
    return RouteRegistrationCallableInspectionV2(
        global_writes=tuple(sorted(global_writes)),
        resource_references=tuple(sorted(resource_references)),
        forbidden_effect_references=tuple(sorted(forbidden_effect_references)),
        declares_routes=declares_routes,
    )


def materialize_route_registration_v2(
    *,
    kind: str,
    target: object,
    prefix: str | None = None,
    helper_args: Sequence[object] = (),
    helper_kwargs: Mapping[str, object] | None = None,
) -> RouteRegistrationMaterializationV2:
    """Materialize one inventory contribution without retaining failed effects."""
    if kind not in {"include_router", "helper"}:
        raise ValueError(f"unsupported route registration kind: {kind}")
    if kind == "include_router":
        return _materialize_router_v2(target, prefix=prefix)
    if not callable(target):
        return _rejected_materialization_v2(
            declares_routes=False,
            reason="route registration helper is not callable",
        )
    helper = target
    return _materialize_helper_v2(
        helper,
        args=helper_args,
        kwargs=helper_kwargs or MappingProxyType({}),
    )


def _materialize_router_v2(
    target: object,
    *,
    prefix: str | None,
) -> RouteRegistrationMaterializationV2:
    if isinstance(target, APIRouter):
        return _include_router_v2(target, prefix=prefix)
    if not callable(target):
        return _rejected_materialization_v2(
            declares_routes=False,
            reason="include_router target is neither an APIRouter nor a callable factory",
        )
    return _materialize_router_factory_v2(target, prefix=prefix)


def _materialize_router_factory_v2(
    factory: Callable[..., object],
    *,
    prefix: str | None,
) -> RouteRegistrationMaterializationV2:
    inspection = inspect_route_registration_callable_v2(factory)
    rejection = _inspection_rejection_v2(inspection)
    if rejection is not None:
        return _rejected_materialization_v2(
            declares_routes=inspection.declares_routes,
            reason=rejection,
        )
    if inspect.iscoroutinefunction(factory):
        return _rejected_materialization_v2(
            declares_routes=False,
            reason="async route factories are not executed during catalog generation",
        )
    snapshots = _snapshot_function_globals_v2(factory)
    try:
        result = factory()
    except Exception as exc:
        return _rejected_materialization_v2(
            declares_routes=inspection.declares_routes,
            reason=f"route registration failed: {type(exc).__name__}",
        )
    finally:
        _restore_function_globals_v2(snapshots)
    if inspect.isawaitable(result):
        close = getattr(result, "close", None)
        if callable(close):
            _ = close()
        return _rejected_materialization_v2(
            declares_routes=False,
            reason="awaitable route factories are not executed during catalog generation",
        )
    if not isinstance(result, APIRouter):
        return _rejected_materialization_v2(
            declares_routes=inspection.declares_routes,
            reason="route factory did not return an APIRouter",
        )
    return _include_router_v2(result, prefix=prefix)


def _include_router_v2(
    router: APIRouter,
    *,
    prefix: str | None,
) -> RouteRegistrationMaterializationV2:
    sink = RouteRegistrationSinkV2()
    try:
        if prefix is None:
            sink.include_router(router)
        else:
            sink.include_router(router, prefix=prefix)
        return _successful_materialization_v2(sink)
    except Exception as exc:
        _dispose_route_registration_sink_v2(sink)
        return _rejected_materialization_v2(
            declares_routes=True,
            reason=f"route registration failed: {type(exc).__name__}",
        )


def _materialize_helper_v2(
    helper: Callable[..., object],
    *,
    args: Sequence[object],
    kwargs: Mapping[str, object],
) -> RouteRegistrationMaterializationV2:
    inspection = inspect_route_registration_callable_v2(helper)
    rejection = _inspection_rejection_v2(inspection)
    if rejection is not None:
        return _rejected_materialization_v2(
            declares_routes=inspection.declares_routes,
            reason=rejection,
        )
    if inspect.iscoroutinefunction(helper):
        return _rejected_materialization_v2(
            declares_routes=False,
            reason="async helpers are not executed during route catalog generation",
        )
    sink = RouteRegistrationSinkV2()
    snapshots = _snapshot_function_globals_v2(helper)
    try:
        result = helper(sink, *args, **kwargs)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                _ = close()
            raise RouteRegistrationViolationV2("awaitable helper result")
        return _successful_materialization_v2(sink)
    except RouteRegistrationViolationV2 as exc:
        _dispose_route_registration_sink_v2(sink)
        return _rejected_materialization_v2(
            declares_routes=inspection.declares_routes,
            reason=str(exc),
        )
    except Exception as exc:
        _dispose_route_registration_sink_v2(sink)
        return _rejected_materialization_v2(
            declares_routes=inspection.declares_routes,
            reason=f"route registration failed: {type(exc).__name__}",
        )
    finally:
        _restore_function_globals_v2(snapshots)


def _successful_materialization_v2(
    sink: RouteRegistrationSinkV2,
) -> RouteRegistrationMaterializationV2:
    app = cast(FastAPI, object.__getattribute__(sink, "_app"))
    signatures = ordered_route_signatures_v2(app.router.routes)
    if not signatures:
        return RouteRegistrationMaterializationV2(
            classification=RouteRegistrationClassificationV2.NON_ROUTE,
            ordered_signatures=(),
            openapi_digest=None,
            rejections=("registration produced no routes",),
        )
    return RouteRegistrationMaterializationV2(
        classification=RouteRegistrationClassificationV2.ROUTES_ONLY,
        ordered_signatures=signatures,
        openapi_digest=route_openapi_digest_v2(app),
    )


def _dispose_route_registration_sink_v2(sink: RouteRegistrationSinkV2) -> None:
    app = cast(FastAPI, object.__getattribute__(sink, "_app"))
    app.router.routes.clear()
    app.dependency_overrides.clear()
    app.openapi_schema = None


def _rejected_materialization_v2(
    *,
    declares_routes: bool,
    reason: str,
) -> RouteRegistrationMaterializationV2:
    classification = (
        RouteRegistrationClassificationV2.HYBRID
        if declares_routes
        else RouteRegistrationClassificationV2.NON_ROUTE
    )
    return RouteRegistrationMaterializationV2(
        classification=classification,
        ordered_signatures=(),
        openapi_digest=None,
        rejections=(reason,),
    )


def _inspection_rejection_v2(
    inspection: RouteRegistrationCallableInspectionV2,
) -> str | None:
    if inspection.global_writes:
        return "global writes forbidden during route materialization: " + ", ".join(
            inspection.global_writes
        )
    if inspection.resource_references:
        return "resource-capable references forbidden during route materialization: " + ", ".join(
            inspection.resource_references
        )
    if inspection.forbidden_effect_references:
        return "non-route effects forbidden during route materialization: " + ", ".join(
            inspection.forbidden_effect_references
        )
    return None


def _nested_code_objects_v2(code: CodeType) -> tuple[CodeType, ...]:
    codes = [code]
    for value in code.co_consts:
        if isinstance(value, CodeType):
            codes.extend(_nested_code_objects_v2(value))
    return tuple(codes)


def _executed_code_objects_v2(function: FunctionType) -> tuple[CodeType, ...]:
    root = function.__code__
    called_nested = _called_nested_function_names_v2(function)
    executed = [root]
    for code in _nested_code_objects_v2(root)[1:]:
        if code.co_name in called_nested or code.co_name.startswith("<"):
            executed.append(code)
    return tuple(executed)


def _reachable_functions_v2(target: Callable[..., object]) -> tuple[FunctionType, ...]:
    pending = [_unwrap_function_v2(target)]
    seen: set[int] = set()
    functions: list[FunctionType] = []
    while pending:
        function = pending.pop()
        if function is None or id(function) in seen:
            continue
        seen.add(id(function))
        functions.append(function)
        module = function.__module__
        called_names = _direct_called_names_v2(function)
        for name in called_names:
            candidate = function.__globals__.get(name)
            if isinstance(candidate, FunctionType) and candidate.__module__ == module:
                pending.append(candidate)
        closure = function.__closure__ or ()
        for name, cell in zip(function.__code__.co_freevars, closure, strict=True):
            if name not in called_names:
                continue
            try:
                candidate = cell.cell_contents
            except ValueError:
                continue
            unwrapped = _unwrap_function_v2(candidate) if callable(candidate) else None
            if unwrapped is not None and unwrapped.__module__ == module:
                pending.append(unwrapped)
    return tuple(functions)


def _direct_called_names_v2(function: FunctionType) -> frozenset[str]:
    node = _function_ast_node_v2(function)
    if node is None:
        return frozenset()
    collector = _DirectCallCollectorV2()
    for statement in node.body:
        collector.visit(statement)
    return frozenset(collector.names)


def _called_nested_function_names_v2(function: FunctionType) -> frozenset[str]:
    node = _function_ast_node_v2(function)
    if node is None:
        return frozenset()
    nested = {
        child.name: child
        for child in node.body
        if isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    pending = list(_called_names_in_statements_v2(node.body))
    called: set[str] = set()
    while pending:
        name = pending.pop()
        if name in called or name not in nested:
            continue
        called.add(name)
        pending.extend(_called_names_in_statements_v2(nested[name].body))
    return frozenset(called)


def _called_names_in_statements_v2(statements: Sequence[ast.stmt]) -> set[str]:
    collector = _DirectCallCollectorV2()
    for statement in statements:
        collector.visit(statement)
    return collector.names


def _function_ast_node_v2(
    function: FunctionType,
) -> ast.AsyncFunctionDef | ast.FunctionDef | None:
    try:
        source = textwrap.dedent(inspect.getsource(function))
    except (OSError, TypeError):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return next(
        (node for node in tree.body if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))),
        None,
    )


class _DirectCallCollectorV2(ast.NodeVisitor):
    """Collect calls in one execution body while excluding nested definitions."""

    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.names.add(node.func.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


def _unwrap_function_v2(target: object) -> FunctionType | None:
    candidate = target
    while isinstance(candidate, functools.partial):
        candidate = candidate.func
    if inspect.ismethod(candidate):
        candidate = candidate.__func__
    return candidate if isinstance(candidate, FunctionType) else None


def _resource_references_v2(function: FunctionType, code: CodeType) -> set[str]:
    references: set[str] = set()
    for name in code.co_names:
        candidate = function.__globals__.get(name)
        if any(candidate is builtin for builtin in _RESOURCE_BUILTINS_V2):
            references.add(f"builtins.{name}")
            continue
        module_name: str | None = None
        if isinstance(candidate, ModuleType):
            module_name = candidate.__name__
        elif callable(candidate):
            module_name = getattr(candidate, "__module__", None)
        if module_name is None:
            continue
        root = module_name.split(".", maxsplit=1)[0]
        if root in _RESOURCE_MODULE_ROOTS_V2:
            references.add(f"{module_name}.{name}")
    return references


type _GlobalSnapshotV2 = tuple[dict[str, object], dict[str, object]]


def _snapshot_function_globals_v2(target: Callable[..., object]) -> tuple[_GlobalSnapshotV2, ...]:
    snapshots: list[_GlobalSnapshotV2] = []
    seen: set[int] = set()
    for function in _reachable_functions_v2(target):
        namespace = function.__globals__
        if id(namespace) in seen:
            continue
        seen.add(id(namespace))
        snapshots.append((namespace, dict(namespace)))
    return tuple(snapshots)


def _restore_function_globals_v2(snapshots: Sequence[_GlobalSnapshotV2]) -> None:
    for namespace, before in snapshots:
        for name in tuple(set(namespace) - set(before)):
            del namespace[name]
        for name, value in before.items():
            if namespace.get(name) is not value:
                namespace[name] = value


__all__ = [
    "RouteRegistrationCallableInspectionV2",
    "RouteRegistrationClassificationV2",
    "RouteRegistrationMaterializationV2",
    "RouteRegistrationSinkV2",
    "RouteRegistrationViolationV2",
    "RouteSignatureV2",
    "create_route_contract_app_v2",
    "inspect_route_registration_callable_v2",
    "materialize_route_registration_v2",
    "ordered_route_signatures_v2",
    "route_openapi_digest_v2",
]
