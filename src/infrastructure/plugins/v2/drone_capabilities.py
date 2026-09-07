"""Drone CI/CD tool and Skill contributions owned by a protocol-v2 Fiber."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from src.application.services.cicd_pipeline_service import (
    CicdPipelineError,
    CicdPipelineRunRequest,
    CicdPipelineService,
)
from src.domain.model.agent.skill import Skill
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace_plan.pipeline import DRONE_PROVIDER

from .agent_capabilities import AgentCapabilityCatalogProtocolV2
from .cicd_pipeline_repository_services import (
    CicdPipelineRepositoryProviderProtocolV2,
)
from .packaged_skill import build_packaged_skill_v2
from .plugin_config_operation_authority_v2 import (
    plugin_config_child_operation_authority_v2,
)
from .plugin_config_services import PluginConfigApplicationResolverProtocolV2
from .runtime import ContextV2, RuntimeV2Error
from .tool_set import ToolSetCatalogProtocolV2, ToolSetV2

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.context import ToolContext

logger = logging.getLogger(__name__)

CICD_RUN_PIPELINE_TOOL_NAME = "cicd_run_pipeline"
DRONE_TOOL_MODULE_V2 = "builtin://memstack/agent/tool/drone"
DRONE_SKILL_MODULE_V2 = "builtin://memstack/agent/skill/drone"
DRONE_TOOL_SERVICE_V2 = "service:agent-tool.drone"
DRONE_PLUGIN_CONFIGS_INJECT_V2 = "plugin_configs"
DRONE_PIPELINE_REPOSITORY_INJECT_V2 = "pipeline_repository"
DRONE_DEFAULTS_SERVICE_V2 = "service:drone-defaults"
DRONE_SECRET_PATHS_SERVICE_V2 = "service:drone-secret-paths"
DRONE_INFRASTRUCTURE_SERVICE_V2 = "service:drone-infrastructure"

_DRONE_SKILL_DIGEST_V2 = "sha256:cfd27c693239ac952ec9cd20b093020c53ca63be7c3d1c736b0b3611f78d5d47"
_DRONE_TOOL_SOURCE_V2 = "builtin-drone-tool"
_DRONE_SKILL_SOURCE_V2 = "builtin-drone-skill"
_REPOSITORY_ROOT_V2 = Path(__file__).resolve().parents[4]
_DRONE_PROFILE_DEFAULTS_V2: dict[str, object] = {
    "drone_server_env": "DRONE_SERVER",
    "drone_token_env": "DRONE_TOKEN",
    "poll_interval_seconds": 5,
}
_DRONE_INFRASTRUCTURE_V2: Mapping[str, object] = MappingProxyType(
    {
        "compose_tool": "docker_compose",
        "compose_files": ("docker-compose.yml",),
        "client_workdir": str(_REPOSITORY_ROOT_V2 / "config" / "drone"),
        "project_name": "memstack-drone",
        "profiles": ("drone",),
        "services": ("drone-server", "drone-runner-docker"),
        "check_args": ("ps", "--format", "json"),
        "start_args": ("up", "-d", "drone-server", "drone-runner-docker"),
        "stop_args": ("stop", "drone-runner-docker", "drone-server"),
        "logs_args": ("logs", "--tail", "100", "drone-server", "drone-runner-docker"),
    }
)

CICD_RUN_PIPELINE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository": {
            "type": "string",
            "description": "Drone repository slug in '<owner>/<repo>' format. Required for ordinary chat CI/CD.",
        },
        "repo": {
            "type": "string",
            "description": "Alias for repository in '<owner>/<repo>' format.",
        },
        "provider": {
            "type": "string",
            "description": "CI/CD provider to run. The V2 contribution provides 'drone'.",
            "default": DRONE_PROVIDER,
        },
        "branch": {"type": "string", "description": "Optional Drone branch override."},
        "commit": {"type": "string", "description": "Optional Drone commit SHA override."},
        "target": {"type": "string", "description": "Optional Drone deployment target."},
        "params": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Optional Drone build parameter overrides.",
        },
        "wait": {
            "type": "boolean",
            "description": "Wait for the Drone run to finish before returning.",
            "default": True,
        },
        "reason": {
            "type": "string",
            "description": "Short reason for the CI/CD run, stored with pipeline evidence.",
        },
    },
}


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


@tool_define(
    name=CICD_RUN_PIPELINE_TOOL_NAME,
    description=(
        "Run the configured Drone CI/CD pipeline for a repository from ordinary chat. "
        "Use this to trigger, wait for, persist, and summarize Drone pipeline evidence without "
        "entering or selecting a workspace task harness. Always provide repository as owner/repo."
    ),
    parameters=CICD_RUN_PIPELINE_PARAMETERS,
    permission=None,
    category="cicd",
    tags=frozenset({"cicd", "pipeline", "drone"}),
)
async def cicd_run_pipeline_tool(
    ctx: ToolContext,
    *,
    _plugin_config_resolver: PluginConfigApplicationResolverProtocolV2,
    _pipeline_repository_provider: CicdPipelineRepositoryProviderProtocolV2,
    repository: str | None = None,
    repo: str | None = None,
    provider: str = DRONE_PROVIDER,
    branch: str | None = None,
    commit: str | None = None,
    target: str | None = None,
    params: dict[str, str] | None = None,
    wait: bool = True,
    reason: str | None = None,
) -> ToolResult:
    """Run a repository CI/CD pipeline from a normal chat turn."""

    try:
        from .boundary import current_operation_context_v2

        parent_operation = current_operation_context_v2()
        async with async_session_factory() as session:
            async with plugin_config_child_operation_authority_v2(
                parent_operation=parent_operation,
                resolver=_plugin_config_resolver,
                db=session,
                consumer="cicd-pipeline",
            ) as authority:
                service = CicdPipelineService(
                    session,
                    pipeline_repository=_pipeline_repository_provider.build(authority.operation),
                    plugin_config_repository=authority.repository,
                )
                summary = await service.run_pipeline(
                    CicdPipelineRunRequest(
                        conversation_id=ctx.conversation_id,
                        project_id=ctx.project_id,
                        tenant_id=ctx.tenant_id,
                        user_id=ctx.user_id,
                        repository=repository or repo,
                        provider=provider,
                        branch=branch,
                        commit=commit,
                        target=target,
                        params=params,
                        wait=wait,
                        reason=reason,
                    )
                )
            payload = {"ok": True, **summary.to_json()}
            return ToolResult(
                output=_json(payload),
                title="CI/CD pipeline completed",
                metadata=payload,
                is_error=summary.status != "success",
            )
    except CicdPipelineError as exc:
        payload = {"ok": False, "error": str(exc), "code": exc.code, **exc.metadata}
        return ToolResult(
            output=_json(payload),
            title="CI/CD pipeline rejected",
            metadata=payload,
            is_error=True,
        )
    except Exception:
        logger.exception("ordinary chat CI/CD pipeline failed")
        payload = {
            "ok": False,
            "error": "CI/CD pipeline failed",
            "code": "cicd_pipeline_unhandled_error",
        }
        return ToolResult(
            output=_json(payload),
            title="CI/CD pipeline failed",
            metadata=payload,
            is_error=True,
        )


@dataclass(frozen=True, kw_only=True)
class DroneToolCapabilityV2:
    """Immutable marker and defaults exposed by the active Drone Fiber."""

    source_id: str
    defaults: Mapping[str, object]


def _bind_drone_tool_v2(
    tool: ToolInfo,
    plugin_config_resolver: PluginConfigApplicationResolverProtocolV2,
    pipeline_repository_provider: CicdPipelineRepositoryProviderProtocolV2,
) -> ToolInfo:
    async def execute(ctx: ToolContext, **kwargs: object) -> object:
        return await tool.execute(
            ctx,
            _plugin_config_resolver=plugin_config_resolver,
            _pipeline_repository_provider=pipeline_repository_provider,
            **kwargs,
        )

    return replace(tool, execute=execute)


def _drone_tool_set_v2(
    tool: ToolInfo,
    plugin_config_resolver: PluginConfigApplicationResolverProtocolV2,
    pipeline_repository_provider: CicdPipelineRepositoryProviderProtocolV2,
) -> ToolSetV2:
    from src.infrastructure.agent.core.tool_converter import convert_tools

    bound_tool = _bind_drone_tool_v2(
        tool,
        plugin_config_resolver,
        pipeline_repository_provider,
    )
    tools = {CICD_RUN_PIPELINE_TOOL_NAME: bound_tool}
    return ToolSetV2(
        tools=MappingProxyType(tools),
        definitions=tuple(convert_tools(tools)),
    )


def _apply_drone_tool_contribution_v2(  # pyright: ignore[reportUnusedFunction]
    context: ContextV2,
    config: Mapping[str, Any],
) -> object:
    source_id = config.get("source_id")
    if source_id != _DRONE_TOOL_SOURCE_V2:
        raise ValueError("Drone tool contribution requires source_id builtin-drone-tool")
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Drone tool contribution received an invalid tool catalog",
        )
    plugin_configs = context.require(DRONE_PLUGIN_CONFIGS_INJECT_V2)
    if not isinstance(plugin_configs, PluginConfigApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_drone_plugin_configs",
            "Drone tool contribution received an invalid PluginConfig resolver",
        )
    pipeline_repository = context.require(DRONE_PIPELINE_REPOSITORY_INJECT_V2)
    if not isinstance(pipeline_repository, CicdPipelineRepositoryProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_drone_pipeline_repository",
            "Drone tool contribution received an invalid pipeline repository Provider",
        )
    contribution_config = {key: value for key, value in config.items() if key != "source_id"}
    defaults = MappingProxyType({**_DRONE_PROFILE_DEFAULTS_V2, **contribution_config})
    capability = DroneToolCapabilityV2(source_id=source_id, defaults=defaults)
    _ = context.provide(
        DRONE_TOOL_SERVICE_V2,
        capability,
        label="drone-tool-capability",
    )
    _ = context.provide(
        DRONE_DEFAULTS_SERVICE_V2,
        defaults,
        label="drone-defaults",
    )
    _ = context.provide(
        DRONE_SECRET_PATHS_SERVICE_V2,
        (),
        label="drone-secret-paths",
    )
    _ = context.provide(
        DRONE_INFRASTRUCTURE_SERVICE_V2,
        _DRONE_INFRASTRUCTURE_V2,
        label="drone-infrastructure",
    )
    return catalog.register_tools(
        source_id,
        lambda **_kwargs: _drone_tool_set_v2(
            cicd_run_pipeline_tool,
            plugin_configs,
            pipeline_repository,
        ),
    )


def _drone_skills_v2(
    *,
    tenant_id: str,
    project_id: str,
    **_kwargs: object,
) -> list[Skill]:
    return [
        build_packaged_skill_v2(
            skill_name="drone",
            expected_digest=_DRONE_SKILL_DIGEST_V2,
            tenant_id=tenant_id,
            project_id=None,
        )
    ]


def _apply_drone_skill_contribution_v2(  # pyright: ignore[reportUnusedFunction]
    context: ContextV2,
    config: Mapping[str, Any],
) -> object:
    source_id = config.get("source_id")
    if source_id != _DRONE_SKILL_SOURCE_V2:
        raise ValueError("Drone Skill contribution requires source_id builtin-drone-skill")
    catalog = context.require("catalog")
    if not isinstance(catalog, AgentCapabilityCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Drone Skill contribution received an invalid capability catalog",
        )
    tool = context.require("tool")
    if not isinstance(tool, DroneToolCapabilityV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Drone Skill contribution requires the Drone tool capability",
        )
    return catalog.register_skills(source_id, _drone_skills_v2)


__all__ = [
    "CICD_RUN_PIPELINE_PARAMETERS",
    "CICD_RUN_PIPELINE_TOOL_NAME",
    "DRONE_DEFAULTS_SERVICE_V2",
    "DRONE_INFRASTRUCTURE_SERVICE_V2",
    "DRONE_PIPELINE_REPOSITORY_INJECT_V2",
    "DRONE_PLUGIN_CONFIGS_INJECT_V2",
    "DRONE_SECRET_PATHS_SERVICE_V2",
    "DRONE_SKILL_MODULE_V2",
    "DRONE_TOOL_MODULE_V2",
    "DRONE_TOOL_SERVICE_V2",
    "DroneToolCapabilityV2",
    "cicd_run_pipeline_tool",
]
