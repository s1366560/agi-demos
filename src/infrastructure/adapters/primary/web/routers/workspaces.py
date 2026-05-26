"""Workspace lifecycle, member, and agent binding API routes."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_agent_autonomy import AutonomyProfileModel
from src.application.services.workspace_autonomy_profiles import (
    evaluate_workspace_code_context,
    normalize_sandbox_code_root,
)
from src.application.services.workspace_layout_limits import MAX_WORKSPACE_HEX_COORDINATE
from src.application.services.workspace_service import WorkspaceService
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    tags=["workspaces"],
)
logger = logging.getLogger(__name__)


def get_workspace_service(request: Request, db: AsyncSession = Depends(get_db)) -> WorkspaceService:
    """Resolve workspace service from request-scoped DI container."""
    container = request.app.state.container.with_db(db)
    redis_client = container.redis_client

    async def _publish_event(workspace_id: str, event_name: str, payload: dict[str, Any]) -> None:
        from src.domain.events.types import AgentEventType
        from src.infrastructure.adapters.primary.web.routers.workspace_events import (
            publish_workspace_event_with_retry,
        )

        event_type = AgentEventType(event_name)
        await publish_workspace_event_with_retry(
            redis_client,
            workspace_id=workspace_id,
            event_type=event_type,
            payload=payload,
        )

    return WorkspaceService(
        workspace_repo=container.workspace_repository(),
        workspace_member_repo=container.workspace_member_repository(),
        workspace_agent_repo=container.workspace_agent_repository(),
        topology_repo=container.topology_repository(),
        workspace_event_publisher=_publish_event if redis_client is not None else None,
    )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_("Access denied"))
    if isinstance(exc, ValueError):
        message = str(exc)
        if "not found" in message.lower():
            return HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_("Workspace not found")
            )
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid workspace request"),
        )
    logger.exception("Workspace route failed")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=_("Internal server error"),
    )


async def _publish_pending_workspace_events(
    workspace_service: WorkspaceService,
    *,
    workspace_id: str,
) -> None:
    try:
        await workspace_service.publish_pending_events()
    except Exception:
        logger.exception(
            "Failed to publish workspace events",
            extra={"workspace_id": workspace_id},
        )


def _ensure_workspace_scope(workspace: Workspace, tenant_id: str, project_id: str) -> None:
    if workspace.tenant_id != tenant_id or workspace.project_id != project_id:
        raise ValueError("Workspace not found")


WorkspaceUseCase = Literal["general", "programming", "conversation", "research", "operations"]
WorkspaceType = Literal["general", "software_development", "research", "operations"]
WorkspaceSourceControlProvider = Literal["github", "gitlab"]
WorkspaceCollaborationMode = Literal[
    "single_agent",
    "multi_agent_shared",
    "multi_agent_isolated",
    "autonomous",
]

_DEFAULT_WORKSPACE_USE_CASE: WorkspaceUseCase = "general"
_DEFAULT_COLLABORATION_MODE: WorkspaceCollaborationMode = "single_agent"
_USE_CASE_TO_WORKSPACE_TYPE: dict[WorkspaceUseCase, WorkspaceType] = {
    "general": "general",
    "programming": "software_development",
    "conversation": "general",
    "research": "research",
    "operations": "operations",
}
_VALID_USE_CASES = set(_USE_CASE_TO_WORKSPACE_TYPE)
_VALID_COLLABORATION_MODES = {
    "single_agent",
    "multi_agent_shared",
    "multi_agent_isolated",
    "autonomous",
}
_DEFAULT_SOURCE_CONTROL_PROVIDER: WorkspaceSourceControlProvider = "github"
_VALID_SOURCE_CONTROL_PROVIDERS: set[WorkspaceSourceControlProvider] = {"github", "gitlab"}
_DEFAULT_SOURCE_CONTROL_REPO_OWNER = "memstack"
_DEFAULT_SOURCE_CONTROL_BRANCH = "main"
_DEFAULT_GITHUB_SERVER_URL = "https://github.com"
_DEFAULT_GITLAB_SERVER_URL = "https://gitlab.com"
_DEFAULT_GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
_DEFAULT_GITLAB_TOKEN_ENV = "GITLAB_TOKEN"
_DRONE_PROVIDER = "drone"
_DEFAULT_DRONE_REPO_OWNER = "memstack"
_DEFAULT_DRONE_BRANCH = "main"
_DEFAULT_DRONE_SERVER_URL_ENV = "DRONE_SERVER_URL"
_DEFAULT_DRONE_TOKEN_ENV = "DRONE_TOKEN"
_DEFAULT_DRONE_POLL_INTERVAL_SECONDS = 5
_DEFAULT_DRONE_TIMEOUT_SECONDS = 600
_DEFAULT_DRONE_SERVER_PORT = 8080
_DEFAULT_DRONE_SERVER_HOST = "localhost:8080"
_DEFAULT_DRONE_SERVER_PROTO = "http"
_DEFAULT_DRONE_RPC_SECRET_ENV = "DRONE_RPC_SECRET"
_DEFAULT_DRONE_USER_CREATE = "username:memstack,admin:true"
_DEFAULT_DRONE_GITHUB_SERVER = _DEFAULT_GITHUB_SERVER_URL
_DEFAULT_DRONE_GITHUB_CLIENT_ID_ENV = "DRONE_GITHUB_CLIENT_ID"
_DEFAULT_DRONE_GITHUB_CLIENT_SECRET_ENV = "DRONE_GITHUB_CLIENT_SECRET"
_DEFAULT_DRONE_GITLAB_SERVER = _DEFAULT_GITLAB_SERVER_URL
_DEFAULT_DRONE_GITLAB_CLIENT_ID_ENV = "DRONE_GITLAB_CLIENT_ID"
_DEFAULT_DRONE_GITLAB_CLIENT_SECRET_ENV = "DRONE_GITLAB_CLIENT_SECRET"
_DEFAULT_DRONE_RUNNER_PORT = 3001
_DEFAULT_DRONE_RUNNER_CAPACITY = 2
_DEFAULT_DRONE_RUNNER_NAME = "memstack-drone-runner"
_DEFAULT_DRONE_RUNNER_RPC_PROTO = "http"
_DEFAULT_DRONE_RUNNER_RPC_HOST = "drone-server"
_DEFAULT_DRONE_DEPLOY_MODE = "cli"
_DEFAULT_DRONE_DEPLOY_STAGE = "deploy"
_DEFAULT_DRONE_DEPLOY_CLI_IMAGE = "alpine:3.20"
_DEFAULT_DRONE_DEPLOY_DOCKER_CONTEXT = "."
_DEFAULT_DRONE_DEPLOY_DOCKERFILE = "Dockerfile"
_DEFAULT_DRONE_DEPLOY_DOCKER_TAGS = ["latest"]
_DEFAULT_DRONE_DEPLOY_DOCKER_STRATEGY = "local_build"
_DEFAULT_DRONE_DEPLOY_DOCKER_ALLOW_DAEMON_REGISTRY_PULL = False
_DEFAULT_DRONE_DEPLOY_DOCKER_HOST_PORT = 18080
_DEFAULT_DRONE_DEPLOY_DOCKER_RESERVED_HOST_PORTS = [
    3000,
    3001,
    5001,
    5432,
    6379,
    7474,
    7687,
    8000,
    8080,
]
_DEFAULT_DRONE_DEPLOY_KUBERNETES_NAMESPACE = "default"
_DEFAULT_DRONE_DEPLOY_KUBERNETES_MANIFEST_PATHS = ["k8s/*.yaml"]
_DEFAULT_DRONE_DEPLOY_KUBECONFIG_SECRET = "kubeconfig"
_DEFAULT_DRONE_DEPLOY_KUBECTL_IMAGE = "bitnami/kubectl:latest"
_VALID_DRONE_DEPLOY_MODES = {"docker", "kubernetes", "cli"}


def _as_mapping(value: Any) -> Mapping[str, Any]:  # noqa: ANN401
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _coerce_use_case(value: Any) -> WorkspaceUseCase | None:  # noqa: ANN401
    if value == "software_development":
        return "programming"
    if isinstance(value, str) and value in _VALID_USE_CASES:
        return cast(WorkspaceUseCase, value)  # pyright: ignore[reportUnnecessaryCast]
    return None


def _coerce_workspace_type(value: Any) -> WorkspaceType | None:  # noqa: ANN401
    if value == "software_development":
        return "software_development"
    if value == "research":
        return "research"
    if value == "operations":
        return "operations"
    if value == "general":
        return "general"
    return None


def _coerce_collaboration_mode(value: Any) -> WorkspaceCollaborationMode | None:  # noqa: ANN401
    if isinstance(value, str) and value in _VALID_COLLABORATION_MODES:
        return cast(WorkspaceCollaborationMode, value)
    return None


def _coerce_source_control_provider(value: Any) -> WorkspaceSourceControlProvider:  # noqa: ANN401
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _VALID_SOURCE_CONTROL_PROVIDERS:
            return normalized
    return _DEFAULT_SOURCE_CONTROL_PROVIDER


def _resolve_use_case(
    explicit: WorkspaceUseCase | None,
    metadata: Mapping[str, Any],
) -> WorkspaceUseCase:
    if explicit is not None:
        return explicit
    profile = _as_mapping(metadata.get("autonomy_profile"))
    for value in (
        metadata.get("workspace_use_case"),
        metadata.get("use_case"),
        metadata.get("workspace_type"),
        profile.get("workspace_type"),
    ):
        use_case = _coerce_use_case(value)
        if use_case is not None:
            return use_case
        workspace_type = _coerce_workspace_type(value)
        if workspace_type == "software_development":
            return "programming"
        if workspace_type in {"research", "operations", "general"}:
            return cast(WorkspaceUseCase, workspace_type)
    return _DEFAULT_WORKSPACE_USE_CASE


def _resolve_collaboration_mode(
    explicit: WorkspaceCollaborationMode | None,
    metadata: Mapping[str, Any],
) -> WorkspaceCollaborationMode:
    if explicit is not None:
        return explicit
    for value in (
        metadata.get("collaboration_mode"),
        metadata.get("agent_conversation_mode"),
    ):
        mode = _coerce_collaboration_mode(value)
        if mode is not None:
            return mode
    return _DEFAULT_COLLABORATION_MODE


def _workspace_type_for_use_case(use_case: WorkspaceUseCase) -> WorkspaceType:
    return _USE_CASE_TO_WORKSPACE_TYPE[use_case]


def _workspace_name_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "workspace"


def _default_drone_repo(workspace_name: str) -> str:
    return f"{_DEFAULT_DRONE_REPO_OWNER}/{_workspace_name_slug(workspace_name)}"


def _default_source_control_repo(workspace_name: str) -> str:
    return f"{_DEFAULT_SOURCE_CONTROL_REPO_OWNER}/{_workspace_name_slug(workspace_name)}"


def _has_text(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, str) and bool(value.strip())


def _ensure_mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if isinstance(value, Mapping):
        output = dict(cast(Mapping[str, Any], value))
    else:
        output = {}
    parent[key] = output
    return output


def _ensure_default_text(mapping: dict[str, Any], key: str, value: str) -> None:
    if not _has_text(mapping.get(key)):
        mapping[key] = value


def _ensure_default_int(mapping: dict[str, Any], key: str, value: int) -> None:
    if not isinstance(mapping.get(key), int):
        mapping[key] = value


def _ensure_default_bool(mapping: dict[str, Any], key: str, value: bool) -> None:
    if not isinstance(mapping.get(key), bool):
        mapping[key] = value


def _ensure_default_list(mapping: dict[str, Any], key: str, value: list[Any]) -> None:
    if not isinstance(mapping.get(key), list):
        mapping[key] = list(value)


def _source_control_defaults(
    provider: WorkspaceSourceControlProvider,
    workspace_name: str,
) -> dict[str, str]:
    server_url = _DEFAULT_GITLAB_SERVER_URL if provider == "gitlab" else _DEFAULT_GITHUB_SERVER_URL
    token_env = _DEFAULT_GITLAB_TOKEN_ENV if provider == "gitlab" else _DEFAULT_GITHUB_TOKEN_ENV
    return {
        "provider": provider,
        "repo": _default_source_control_repo(workspace_name),
        "default_branch": _DEFAULT_SOURCE_CONTROL_BRANCH,
        "server_url": server_url,
        "auth_token_env": token_env,
    }


def _source_control_clone_url(
    provider: WorkspaceSourceControlProvider,
    server_url: str,
    repo: str,
) -> str:
    repo_path = repo.strip().strip("/")
    if not repo_path:
        repo_path = _default_source_control_repo("workspace")
    base_url = server_url.strip().rstrip("/")
    if not base_url:
        base_url = (
            _DEFAULT_GITLAB_SERVER_URL if provider == "gitlab" else _DEFAULT_GITHUB_SERVER_URL
        )
    suffix = "" if repo_path.endswith(".git") else ".git"
    return f"{base_url}/{repo_path}{suffix}"


def _ensure_workspace_source_control(
    metadata: dict[str, Any],
    *,
    workspace_name: str,
) -> dict[str, Any]:
    delivery = _as_mapping(metadata.get("delivery_cicd"))
    drone = _as_mapping(delivery.get(_DRONE_PROVIDER))
    source_control = dict(_as_mapping(drone.get("source_control")))
    source_control.update(_as_mapping(metadata.get("source_control")))

    provider = _coerce_source_control_provider(source_control.get("provider"))
    defaults = _source_control_defaults(provider, workspace_name)
    source_control["provider"] = provider
    _ensure_default_text(source_control, "repo", defaults["repo"])
    _ensure_default_text(source_control, "default_branch", defaults["default_branch"])
    _ensure_default_text(source_control, "server_url", defaults["server_url"])
    _ensure_default_text(source_control, "auth_token_env", defaults["auth_token_env"])
    _ensure_default_text(
        source_control,
        "clone_url",
        _source_control_clone_url(
            provider,
            str(source_control.get("server_url") or defaults["server_url"]),
            str(source_control.get("repo") or defaults["repo"]),
        ),
    )
    metadata["source_control"] = source_control
    return source_control


def _ensure_drone_environment(
    drone: dict[str, Any],
    source_control: Mapping[str, Any] | None,
) -> None:
    source_control = source_control or {}
    source_provider = _coerce_source_control_provider(source_control.get("provider"))
    source_server_url = (
        str(source_control.get("server_url")).strip()
        if source_control.get("server_url") is not None
        else ""
    )
    environment = _ensure_mapping(drone, "environment")
    api = _ensure_mapping(environment, "api")
    _ensure_default_text(api, "server_url_env", _DEFAULT_DRONE_SERVER_URL_ENV)
    _ensure_default_text(api, "token_env", _DEFAULT_DRONE_TOKEN_ENV)

    server = _ensure_mapping(environment, "server")
    _ensure_default_int(server, "server_port", _DEFAULT_DRONE_SERVER_PORT)
    _ensure_default_text(server, "server_host", _DEFAULT_DRONE_SERVER_HOST)
    _ensure_default_text(server, "server_proto", _DEFAULT_DRONE_SERVER_PROTO)
    _ensure_default_text(server, "rpc_secret_env", _DEFAULT_DRONE_RPC_SECRET_ENV)
    _ensure_default_text(server, "user_create", _DEFAULT_DRONE_USER_CREATE)
    server["source_provider"] = source_provider
    _ensure_default_text(server, "github_server", _DEFAULT_DRONE_GITHUB_SERVER)
    if source_provider == "github" and source_server_url:
        server["github_server"] = source_server_url
    _ensure_default_text(server, "github_client_id_env", _DEFAULT_DRONE_GITHUB_CLIENT_ID_ENV)
    _ensure_default_text(
        server,
        "github_client_secret_env",
        _DEFAULT_DRONE_GITHUB_CLIENT_SECRET_ENV,
    )
    _ensure_default_text(server, "gitlab_server", _DEFAULT_DRONE_GITLAB_SERVER)
    if source_provider == "gitlab" and source_server_url:
        server["gitlab_server"] = source_server_url
    _ensure_default_text(server, "gitlab_client_id_env", _DEFAULT_DRONE_GITLAB_CLIENT_ID_ENV)
    _ensure_default_text(
        server,
        "gitlab_client_secret_env",
        _DEFAULT_DRONE_GITLAB_CLIENT_SECRET_ENV,
    )
    _ensure_default_bool(server, "git_always_auth", False)

    runner = _ensure_mapping(environment, "runner")
    _ensure_default_int(runner, "runner_port", _DEFAULT_DRONE_RUNNER_PORT)
    _ensure_default_int(runner, "runner_capacity", _DEFAULT_DRONE_RUNNER_CAPACITY)
    _ensure_default_text(runner, "runner_name", _DEFAULT_DRONE_RUNNER_NAME)
    _ensure_default_text(runner, "rpc_proto", _DEFAULT_DRONE_RUNNER_RPC_PROTO)
    _ensure_default_text(runner, "rpc_host", _DEFAULT_DRONE_RUNNER_RPC_HOST)
    _ensure_default_text(runner, "rpc_secret_env", _DEFAULT_DRONE_RPC_SECRET_ENV)


def _ensure_drone_deploy(drone: dict[str, Any]) -> None:
    deploy = _ensure_mapping(drone, "deploy")
    mode = str(deploy.get("mode") or _DEFAULT_DRONE_DEPLOY_MODE).strip().lower()
    if mode not in _VALID_DRONE_DEPLOY_MODES:
        mode = _DEFAULT_DRONE_DEPLOY_MODE
    deploy["mode"] = mode
    _ensure_default_bool(deploy, "enabled", False)
    _ensure_default_text(deploy, "stage", _DEFAULT_DRONE_DEPLOY_STAGE)
    _ensure_default_bool(deploy, "required", True)

    cli = _ensure_mapping(deploy, "cli")
    _ensure_default_text(cli, "image", _DEFAULT_DRONE_DEPLOY_CLI_IMAGE)
    _ensure_default_list(cli, "commands", [])

    docker = _ensure_mapping(deploy, "docker")
    _ensure_default_bool(docker, "trusted", True)
    _ensure_default_text(docker, "context", _DEFAULT_DRONE_DEPLOY_DOCKER_CONTEXT)
    _ensure_default_text(docker, "dockerfile", _DEFAULT_DRONE_DEPLOY_DOCKERFILE)
    _ensure_default_list(docker, "tags", _DEFAULT_DRONE_DEPLOY_DOCKER_TAGS)
    _ensure_default_text(docker, "deploy_strategy", _DEFAULT_DRONE_DEPLOY_DOCKER_STRATEGY)
    _ensure_default_int(docker, "deploy_host_port", _DEFAULT_DRONE_DEPLOY_DOCKER_HOST_PORT)
    _ensure_default_list(
        docker,
        "reserved_host_ports",
        _DEFAULT_DRONE_DEPLOY_DOCKER_RESERVED_HOST_PORTS,
    )
    _ensure_default_bool(
        docker,
        "allow_daemon_registry_pull",
        _DEFAULT_DRONE_DEPLOY_DOCKER_ALLOW_DAEMON_REGISTRY_PULL,
    )

    kubernetes = _ensure_mapping(deploy, "kubernetes")
    _ensure_default_text(kubernetes, "namespace", _DEFAULT_DRONE_DEPLOY_KUBERNETES_NAMESPACE)
    _ensure_default_list(
        kubernetes,
        "manifest_paths",
        _DEFAULT_DRONE_DEPLOY_KUBERNETES_MANIFEST_PATHS,
    )
    _ensure_default_text(
        kubernetes,
        "kubeconfig_secret",
        _DEFAULT_DRONE_DEPLOY_KUBECONFIG_SECRET,
    )
    _ensure_default_text(kubernetes, "kubectl_image", _DEFAULT_DRONE_DEPLOY_KUBECTL_IMAGE)


def _ensure_programming_delivery_cicd(
    metadata: dict[str, Any],
    *,
    workspace_name: str,
    sandbox_code_root: str | None,
    source_control: Mapping[str, Any] | None,
) -> None:
    if not sandbox_code_root:
        return

    delivery = dict(_as_mapping(metadata.get("delivery_cicd")))
    provider = delivery.get("provider")
    provider_name = provider.strip() if isinstance(provider, str) else ""
    if not provider_name:
        provider_name = _DRONE_PROVIDER
        delivery["provider"] = provider_name

    if not _has_text(delivery.get("code_root")):
        delivery["code_root"] = sandbox_code_root

    if provider_name != _DRONE_PROVIDER:
        metadata["delivery_cicd"] = delivery
        return

    drone = dict(_as_mapping(delivery.get(_DRONE_PROVIDER)))
    source_control = source_control or {}
    if not _has_text(drone.get("repo")) and not _has_text(drone.get("repository")):
        drone["repo"] = (
            source_control.get("repo")
            if _has_text(source_control.get("repo"))
            else _default_drone_repo(workspace_name)
        )
    if not _has_text(drone.get("branch")):
        drone["branch"] = (
            source_control.get("default_branch")
            if _has_text(source_control.get("default_branch"))
            else _DEFAULT_DRONE_BRANCH
        )
    if not _has_text(drone.get("server_url_env")) and not _has_text(drone.get("server_url")):
        drone["server_url_env"] = _DEFAULT_DRONE_SERVER_URL_ENV
    if not _has_text(drone.get("token_env")):
        drone["token_env"] = _DEFAULT_DRONE_TOKEN_ENV
    if not isinstance(drone.get("poll_interval_seconds"), int):
        drone["poll_interval_seconds"] = _DEFAULT_DRONE_POLL_INTERVAL_SECONDS
    drone_source_control = dict(_as_mapping(drone.get("source_control")))
    drone_source_control.update(source_control)
    drone["source_control"] = drone_source_control
    _ensure_drone_environment(drone, source_control)
    _ensure_drone_deploy(drone)

    delivery[_DRONE_PROVIDER] = drone
    delivery.setdefault("agent_managed", False)
    delivery.setdefault("contract_source", "workspace_defaults")
    delivery.setdefault("contract_confidence", 1.0)
    delivery.setdefault("timeout_seconds", _DEFAULT_DRONE_TIMEOUT_SECONDS)
    delivery.setdefault("auto_deploy", False)
    metadata["delivery_cicd"] = delivery


def _compose_workspace_metadata(payload: WorkspaceCreateRequest) -> dict[str, Any]:
    metadata = dict(payload.metadata or {})
    if payload.source_control is not None:
        metadata["source_control"] = payload.source_control
    use_case = _resolve_use_case(payload.use_case, metadata)
    workspace_type = _workspace_type_for_use_case(use_case)
    collaboration_mode = _resolve_collaboration_mode(payload.collaboration_mode, metadata)

    profile = dict(_as_mapping(metadata.get("autonomy_profile")))
    if payload.autonomy_profile is not None:
        profile.update(payload.autonomy_profile.model_dump(exclude_none=True))
    profile["workspace_type"] = workspace_type

    metadata.update(
        {
            "workspace_use_case": use_case,
            "workspace_type": workspace_type,
            "collaboration_mode": collaboration_mode,
            "agent_conversation_mode": collaboration_mode,
            "autonomy_profile": profile,
        }
    )

    sandbox_code_root = normalize_sandbox_code_root(
        payload.sandbox_code_root or metadata.get("sandbox_code_root")
    )
    if sandbox_code_root:
        code_context = dict(_as_mapping(metadata.get("code_context")))
        code_context["sandbox_code_root"] = sandbox_code_root
        metadata["sandbox_code_root"] = sandbox_code_root
        metadata["code_context"] = code_context
        if use_case == "programming":
            source_control = _ensure_workspace_source_control(
                metadata,
                workspace_name=payload.name,
            )
            _ensure_programming_delivery_cicd(
                metadata,
                workspace_name=payload.name,
                sandbox_code_root=sandbox_code_root,
                source_control=source_control,
            )

    code_context_eval = evaluate_workspace_code_context(
        root_metadata=None,
        workspace_metadata=metadata,
    )
    if not code_context_eval.allowed:
        raise ValueError(code_context_eval.reason or "Invalid workspace code context")

    return metadata


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    use_case: WorkspaceUseCase | None = None
    collaboration_mode: WorkspaceCollaborationMode | None = None
    autonomy_profile: AutonomyProfileModel | None = None
    sandbox_code_root: str | None = None
    source_control: dict[str, Any] | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    is_archived: bool | None = None
    metadata: dict[str, Any] | None = None


class WorkspaceResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    name: str
    created_by: str
    description: str | None
    is_archived: bool
    metadata: dict[str, Any]
    office_status: str
    hex_layout_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None


class WorkspaceMemberCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: WorkspaceRole = WorkspaceRole.VIEWER


class WorkspaceMemberUpdateRequest(BaseModel):
    role: WorkspaceRole


class WorkspaceMemberResponse(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    user_email: str | None = None
    role: WorkspaceRole
    invited_by: str | None
    created_at: datetime
    updated_at: datetime | None


class WorkspaceAgentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)
    display_name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    hex_q: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    hex_r: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    theme_color: str | None = Field(default=None, max_length=32)
    label: str | None = Field(default=None, max_length=64)


class WorkspaceAgentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    config: dict[str, Any] | None = None
    is_active: bool | None = None
    hex_q: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    hex_r: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    theme_color: str | None = Field(default=None, max_length=32)
    label: str | None = Field(default=None, max_length=64)


class WorkspaceAgentResponse(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    display_name: str | None
    description: str | None
    config: dict[str, Any]
    is_active: bool
    hex_q: int | None
    hex_r: int | None
    theme_color: str | None
    label: str | None
    status: str | None
    created_at: datetime
    updated_at: datetime | None


def _to_workspace_response(workspace: Workspace) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        tenant_id=workspace.tenant_id,
        project_id=workspace.project_id,
        name=workspace.name,
        created_by=workspace.created_by,
        description=workspace.description,
        is_archived=workspace.is_archived,
        metadata=workspace.metadata,
        office_status=workspace.office_status,
        hex_layout_config=workspace.hex_layout_config,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _to_member_response(
    member: WorkspaceMember, user_email: str | None = None
) -> WorkspaceMemberResponse:
    return WorkspaceMemberResponse(
        id=member.id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        user_email=user_email,
        role=member.role,
        invited_by=member.invited_by,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


def _to_agent_response(agent: WorkspaceAgent) -> WorkspaceAgentResponse:
    return WorkspaceAgentResponse(
        id=agent.id,
        workspace_id=agent.workspace_id,
        agent_id=agent.agent_id,
        display_name=agent.display_name,
        description=agent.description,
        config=agent.config,
        is_active=agent.is_active,
        hex_q=agent.hex_q,
        hex_r=agent.hex_r,
        theme_color=agent.theme_color,
        label=agent.label,
        status=agent.status,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    tenant_id: str,
    project_id: str,
    payload: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    try:
        workspace = await workspace_service.create_workspace(
            tenant_id=tenant_id,
            project_id=project_id,
            name=payload.name,
            created_by=current_user.id,
            description=payload.description,
            metadata=_compose_workspace_metadata(payload),
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    await _publish_pending_workspace_events(workspace_service, workspace_id=workspace.id)
    return _to_workspace_response(workspace)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    tenant_id: str,
    project_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceResponse]:
    try:
        workspaces = await workspace_service.list_workspaces(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        return [_to_workspace_response(workspace) for workspace in workspaces]
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        return _to_workspace_response(workspace)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        updated = await workspace_service.update_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            name=payload.name,
            description=payload.description,
            is_archived=payload.is_archived,
            metadata=payload.metadata,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    await _publish_pending_workspace_events(workspace_service, workspace_id=workspace_id)
    return _to_workspace_response(updated)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        _ = await workspace_service.delete_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    await _publish_pending_workspace_events(workspace_service, workspace_id=workspace_id)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
async def list_workspace_members(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceMemberResponse]:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        members = await workspace_service.list_members(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        # Batch-resolve user emails
        from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
            SqlUserRepository,
        )

        user_repo = SqlUserRepository(db)
        email_map: dict[str, str] = {}
        for member in members:
            user = await user_repo.find_by_id(member.user_id)
            if user:
                email_map[member.user_id] = user.email
        return [
            _to_member_response(member, user_email=email_map.get(member.user_id))
            for member in members
        ]
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_workspace_member(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: WorkspaceMemberCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceMemberResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        member = await workspace_service.add_member(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            target_user_id=payload.user_id,
            role=payload.role,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    await _publish_pending_workspace_events(workspace_service, workspace_id=workspace_id)
    return _to_member_response(member)


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberResponse)
async def update_workspace_member(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    user_id: str,
    payload: WorkspaceMemberUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceMemberResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        member = await workspace_service.update_member_role(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            target_user_id=user_id,
            new_role=payload.role,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    await _publish_pending_workspace_events(workspace_service, workspace_id=workspace_id)
    return _to_member_response(member)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workspace_member(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        _ = await workspace_service.remove_member(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            target_user_id=user_id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    await _publish_pending_workspace_events(workspace_service, workspace_id=workspace_id)


@router.get("/{workspace_id}/agents", response_model=list[WorkspaceAgentResponse])
async def list_workspace_agents(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    active_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceAgentResponse]:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        bindings = await workspace_service.list_workspace_agents(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
        return [_to_agent_response(binding) for binding in bindings]
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post(
    "/{workspace_id}/agents",
    response_model=WorkspaceAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bind_workspace_agent(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: WorkspaceAgentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceAgentResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        binding = await workspace_service.bind_agent(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            agent_id=payload.agent_id,
            display_name=payload.display_name,
            description=payload.description,
            config=payload.config,
            is_active=payload.is_active,
            hex_q=payload.hex_q,
            hex_r=payload.hex_r,
            theme_color=payload.theme_color,
            label=payload.label,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    await _publish_pending_workspace_events(workspace_service, workspace_id=workspace_id)
    return _to_agent_response(binding)


@router.patch("/{workspace_id}/agents/{workspace_agent_id}", response_model=WorkspaceAgentResponse)
async def update_workspace_agent(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    workspace_agent_id: str,
    payload: WorkspaceAgentUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceAgentResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        binding = await workspace_service.update_agent_binding(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            workspace_agent_id=workspace_agent_id,
            display_name=payload.display_name,
            description=payload.description,
            config=payload.config,
            is_active=payload.is_active,
            hex_q=payload.hex_q,
            hex_r=payload.hex_r,
            theme_color=payload.theme_color,
            label=payload.label,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    await _publish_pending_workspace_events(workspace_service, workspace_id=workspace_id)
    return _to_agent_response(binding)


@router.delete(
    "/{workspace_id}/agents/{workspace_agent_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_workspace_agent(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    workspace_agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        _ = await workspace_service.unbind_agent(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            workspace_agent_id=workspace_agent_id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    await _publish_pending_workspace_events(workspace_service, workspace_id=workspace_id)
