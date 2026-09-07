"""V2-owned production contributions for the builtin skills HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers import skills

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SKILLS_HTTP_ROUTES_ENTRY_V2 = "builtin-skills-http-routes"
SKILLS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/skills-routes"
SKILLS_HTTP_ROUTES_ROW_V2 = "skills"
_SKILLS_PREFIX_V2 = "/api/v1/skills"

type SkillsRouteSpecV2 = tuple[
    Callable[..., Any],
    object | None,
    str,
    str,
    str | None,
]

_SKILLS_ROUTE_SPECS_V2: tuple[SkillsRouteSpecV2, ...] = (
    (skills.create_skill, skills.SkillResponse, "POST", "/", None),
    (skills.list_skills, skills.SkillListResponse, "GET", "/", None),
    (skills.get_skill, skills.SkillResponse, "GET", "/{skill_id}", None),
    (skills.update_skill, skills.SkillResponse, "PUT", "/{skill_id}", None),
    (skills.delete_skill, None, "DELETE", "/{skill_id}", None),
    (
        skills.update_skill_status,
        skills.SkillResponse,
        "PATCH",
        "/{skill_id}/status",
        None,
    ),
    (skills.list_system_skills, skills.SkillListResponse, "GET", "/system/list", None),
    (
        skills.get_skill_content,
        skills.SkillContentResponse,
        "GET",
        "/{skill_id}/content",
        None,
    ),
    (
        skills.update_skill_content,
        skills.SkillResponse,
        "PUT",
        "/{skill_id}/content",
        None,
    ),
    (
        skills.import_skill_package,
        skills.SkillLifecycleResponse,
        "POST",
        "/import",
        "Import an AgentSkills.io package",
    ),
    (
        skills.import_skill_zip_package,
        skills.SkillLifecycleResponse,
        "POST",
        "/import/zip",
        "Import an AgentSkills.io zip package",
    ),
    (
        skills.export_skill_package,
        skills.SkillPackageResponse,
        "GET",
        "/{skill_id}/export",
        "Export a skill as an AgentSkills.io package",
    ),
    (
        skills.get_skill_evolution_config,
        skills.SkillEvolutionConfigResponse,
        "GET",
        "/evolution/config",
        "Get skill evolution strategy config",
    ),
    (
        skills.update_skill_evolution_config,
        skills.SkillEvolutionConfigResponse,
        "PUT",
        "/evolution/config",
        "Update skill evolution strategy config",
    ),
    (
        skills.get_skill_evolution_overview,
        skills.SkillEvolutionOverviewResponse,
        "GET",
        "/evolution/overview",
        "Get skill evolution overview",
    ),
    (
        skills.apply_skill_evolution_job,
        skills.SkillEvolutionJobResponse,
        "POST",
        "/evolution/jobs/{job_id}/apply",
        "Apply a pending skill evolution job",
    ),
    (
        skills.reject_skill_evolution_job,
        skills.SkillEvolutionJobResponse,
        "POST",
        "/evolution/jobs/{job_id}/reject",
        "Reject a pending skill evolution job",
    ),
    (
        skills.run_tenant_skill_evolution,
        skills.SkillEvolutionTenantRunResponse,
        "POST",
        "/evolution/run",
        "Run tenant skill evolution now",
    ),
    (
        skills.get_skill_evolution,
        skills.SkillEvolutionDetailResponse,
        "GET",
        "/{skill_id}/evolution",
        "Get skill evolution route",
    ),
    (
        skills.run_skill_evolution,
        skills.SkillEvolutionRunResponse,
        "POST",
        "/{skill_id}/evolution/run",
        "Run skill evolution now",
    ),
    (
        skills.list_skill_versions,
        skills.SkillVersionListResponse,
        "GET",
        "/{skill_id}/versions",
        "List skill versions",
    ),
    (
        skills.get_skill_version,
        skills.SkillVersionDetailResponse,
        "GET",
        "/{skill_id}/versions/{version_number}",
        "Get skill version detail",
    ),
    (
        skills.rollback_skill,
        skills.SkillResponse,
        "POST",
        "/{skill_id}/rollback",
        "Rollback skill to a previous version",
    ),
)

_STATUS_CODES_V2: dict[Callable[..., Any], int] = {
    skills.create_skill: 201,
    skills.delete_skill: 204,
    skills.import_skill_package: 201,
    skills.import_skill_zip_package: 201,
}


def _skills_route_v2(
    endpoint: Callable[..., Any],
    response_model: object | None,
    method: str,
    path: str,
    summary: str | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=SKILLS_HTTP_ROUTES_ENTRY_V2,
        path=f"{_SKILLS_PREFIX_V2}{path}",
        methods=(method,),
        endpoint=endpoint,
        name=endpoint.__name__,
        tags=("Skills",),
        summary=summary,
        status_code=_STATUS_CODES_V2.get(endpoint),
        response_model=response_model,
        replaces_builtin_row_id=SKILLS_HTTP_ROUTES_ROW_V2,
    )


def skills_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``skills`` inventory row."""
    return tuple(_skills_route_v2(*spec) for spec in _SKILLS_ROUTE_SPECS_V2)


def builtin_skills_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register skills routes as reversible effects of one V2 Fiber."""
    definitions = skills_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label=SKILLS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=SKILLS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SKILLS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "SKILLS_HTTP_ROUTES_ENTRY_V2",
    "SKILLS_HTTP_ROUTES_MODULE_V2",
    "SKILLS_HTTP_ROUTES_ROW_V2",
    "builtin_skills_http_routes_definition_v2",
    "skills_route_definitions_v2",
]
