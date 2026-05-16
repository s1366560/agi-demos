from fastapi.routing import APIRoute

from src.infrastructure.adapters.primary.web.main import create_app


def test_project_sandbox_collection_route_precedes_project_detail_route() -> None:
    app = create_app()
    route_paths = [route.path for route in app.routes if isinstance(route, APIRoute)]

    sandbox_collection = route_paths.index("/api/v1/projects/sandboxes")
    project_detail = route_paths.index("/api/v1/projects/{project_id}")

    assert sandbox_collection < project_detail
