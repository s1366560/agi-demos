import pytest
from fastapi.routing import APIRoute

from src.infrastructure.adapters.primary.web.main import create_app


def _routes() -> list[APIRoute]:
    return [route for route in create_app().routes if isinstance(route, APIRoute)]


def _route_index(path: str, method: str) -> int:
    for index, route in enumerate(_routes()):
        if route.path == path and method in route.methods:
            return index
    raise AssertionError(f"Route not found: {method} {path}")


def _path_parts(path: str) -> list[str]:
    return [part for part in path.strip("/").split("/") if part]


def _is_dynamic_segment(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


def _could_shadow(static_path: str, dynamic_path: str) -> bool:
    static_parts = _path_parts(static_path)
    dynamic_parts = _path_parts(dynamic_path)
    if len(static_parts) != len(dynamic_parts):
        return False

    has_dynamic = False
    for static_part, dynamic_part in zip(static_parts, dynamic_parts, strict=True):
        if _is_dynamic_segment(dynamic_part):
            has_dynamic = True
            continue
        if static_part != dynamic_part:
            return False
    return has_dynamic


def test_project_sandbox_collection_route_precedes_project_detail_route() -> None:
    route_paths = [route.path for route in _routes()]

    sandbox_collection = route_paths.index("/api/v1/projects/sandboxes")
    project_detail = route_paths.index("/api/v1/projects/{project_id}")

    assert sandbox_collection < project_detail


def test_sandbox_list_route_precedes_sandbox_detail_route() -> None:
    assert _route_index("/api/v1/sandbox/list", "GET") < _route_index(
        "/api/v1/sandbox/{sandbox_id}",
        "GET",
    )


def test_static_routes_precede_shadowing_dynamic_routes() -> None:
    routes = _routes()
    routes_by_method: dict[str, list[tuple[int, str]]] = {}
    for index, route in enumerate(routes):
        for method in route.methods:
            routes_by_method.setdefault(method, []).append((index, route.path))

    violations: list[str] = []
    for method, method_routes in routes_by_method.items():
        for static_index, static_path in method_routes:
            if any(_is_dynamic_segment(part) for part in _path_parts(static_path)):
                continue
            for dynamic_index, dynamic_path in method_routes:
                if dynamic_index >= static_index:
                    continue
                if _could_shadow(static_path, dynamic_path):
                    violations.append(
                        f"{method} {dynamic_path} appears before static route {static_path}"
                    )

    assert violations == []


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/tenants/{tenant_id}/billing", "GET"),
        ("/api/v1/tenants/{tenant_id}/invoices", "GET"),
        ("/api/v1/tenants/{tenant_id}/upgrade", "POST"),
        ("/api/v1/events", "GET"),
        ("/api/v1/events/types", "GET"),
        ("/api/v1/admin/dlq/messages", "GET"),
        ("/api/v1/admin/dlq/stats", "GET"),
        ("/api/v1/agent/conversations/{conversation_id}/title", "PATCH"),
        ("/api/v1/auth/oauth/{provider}/callback", "POST"),
        ("/api/v1/data/export", "POST"),
        ("/api/v1/graph/communities/rebuild", "POST"),
        ("/api/v1/projects/", "GET"),
        ("/api/v1/projects/{project_id}", "PUT"),
        ("/api/v1/tenants/{tenant_id}/audit-logs/export", "GET"),
        ("/api/v1/tenants/{tenant_id}", "PUT"),
        ("/api/v1/tenants/{tenant_id}/members/{user_id}", "PATCH"),
        ("/api/v1/genes/genomes/{genome_id}/ratings", "GET"),
        ("/api/v1/genes/evolution", "POST"),
        ("/api/v1/genes/evolution/{event_id}", "GET"),
    ],
)
def test_frontend_service_routes_are_registered_under_api_v1(path: str, method: str) -> None:
    assert _route_index(path, method) >= 0
