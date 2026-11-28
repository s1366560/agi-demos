"""Project package HTTP contributions shared by the kernel and full API."""

from fastapi import APIRouter

from src.host.transport.project_marketplace import (
    apply_npm_market_release,
    browse_npm_market,
    read_npm_market_release,
)
from src.infrastructure.adapters.primary.web.routers.optional_business_http_v2 import (
    command_optional_business_v2,
    disable_optional_business_v2,
    enable_optional_business_v2,
    get_optional_business_storage_v2,
    inspect_optional_business_v2,
    install_optional_business_v2,
    invoke_optional_business_v2,
    list_project_packages,
    projection_optional_business_v2,
    purge_optional_business_v2,
    put_optional_business_storage_v2,
    resolve_npm_release,
    rollback_optional_business_v2,
    stream_optional_business_v2,
    ui_optional_business_v2,
    uninstall_optional_business_v2,
)
from src.infrastructure.adapters.primary.web.routers.sandbox_package_tools import (
    call_sandbox_package_tool,
    list_sandbox_package_tools,
)

project_package_router = APIRouter(
    prefix="/api/v1/platform-plugins/v2/optional-business",
    tags=["Platform Plugins", "Platform Plugins V2"],
)

project_package_router.add_api_route("/", list_project_packages, methods=["GET"])
project_package_router.add_api_route("/npm/catalog", browse_npm_market, methods=["GET"])
project_package_router.add_api_route("/npm/detail", read_npm_market_release, methods=["GET"])
project_package_router.add_api_route("/npm/apply", apply_npm_market_release, methods=["POST"])
project_package_router.add_api_route("/npm/resolve", resolve_npm_release, methods=["POST"])
project_package_router.add_api_route("/inspect", inspect_optional_business_v2, methods=["POST"])
project_package_router.add_api_route("/install", install_optional_business_v2, methods=["POST"])
project_package_router.add_api_route(
    "/{plugin_id}", projection_optional_business_v2, methods=["GET"]
)
project_package_router.add_api_route(
    "/{plugin_id}/enable", enable_optional_business_v2, methods=["POST"]
)
project_package_router.add_api_route(
    "/{plugin_id}/disable", disable_optional_business_v2, methods=["POST"]
)
project_package_router.add_api_route(
    "/{plugin_id}/uninstall", uninstall_optional_business_v2, methods=["POST"]
)
project_package_router.add_api_route(
    "/{plugin_id}/purge", purge_optional_business_v2, methods=["POST"]
)
project_package_router.add_api_route(
    "/{plugin_id}/rollback", rollback_optional_business_v2, methods=["POST"]
)
project_package_router.add_api_route(
    "/{plugin_id}/invoke", invoke_optional_business_v2, methods=["POST"]
)
project_package_router.add_api_route(
    "/{plugin_id}/invoke-stream", stream_optional_business_v2, methods=["POST"]
)
project_package_router.add_api_route(
    "/{plugin_id}/commands", command_optional_business_v2, methods=["POST"]
)
project_package_router.add_api_route(
    "/{plugin_id}/storage/{item_key}", put_optional_business_storage_v2, methods=["PUT"]
)
project_package_router.add_api_route(
    "/{plugin_id}/storage/{item_key}", get_optional_business_storage_v2, methods=["GET"]
)
project_package_router.add_api_route("/{plugin_id}/ui", ui_optional_business_v2, methods=["GET"])

project_package_router.add_api_route(
    "/sandbox-mcp/projects/{project_id}/tools", list_sandbox_package_tools, methods=["GET"]
)
project_package_router.add_api_route(
    "/sandbox-mcp/projects/{project_id}/tools", call_sandbox_package_tool, methods=["POST"]
)
