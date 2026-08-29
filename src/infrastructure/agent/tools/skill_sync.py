"""
SkillSyncTool - Agent tool for syncing skills from sandbox to the system.

After the agent creates or updates a skill inside the sandbox via
skill-creator, it calls this tool to register the skill with the
system (database + host filesystem + cache).

Each sync creates a versioned snapshot of the skill's SKILL.md and
all resource files.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.infrastructure.plugins.v2.skill_repository_services import (
        SkillRepositoryApplicationResolverProtocolV2,
    )

logger = logging.getLogger(__name__)

TOOL_NAME = "skill_sync"
TOOL_DESCRIPTION = (
    "Sync a skill from the sandbox to the system. Call this after creating or "
    "updating a skill inside the sandbox (e.g., after writing SKILL.md and resource "
    "files via skill-creator). This registers the skill in the database, writes "
    "files to the host filesystem, and creates a version snapshot.\n\n"
    "Parameters:\n"
    "- skill_name (required): Name of the skill to sync (e.g., 'my-skill')\n"
    "- skill_path (optional): Path to skill directory in sandbox "
    "(default: /workspace/.memstack/skills/{skill_name})\n"
    "- change_summary (optional): Description of what changed\n"
)


@dataclass(frozen=True, kw_only=True, slots=True)
class SkillSyncRuntime:
    """Dependencies captured by one generation's skill-sync contribution."""

    tenant_id: str | None
    project_id: str | None
    sandbox_adapter: Any | None
    sandbox_id: str | None
    session_factory: Callable[..., Any] | None
    skill_loader_tool: Any | None
    skill_repository_resolver: SkillRepositoryApplicationResolverProtocolV2 | None
    generation_bound: bool


_skill_sync_runtime: ContextVar[SkillSyncRuntime | None] = ContextVar(
    f"{__name__}.skill_sync_runtime",
    default=None,
)


def _current_skill_sync_runtime() -> SkillSyncRuntime | None:
    return _skill_sync_runtime.get()


def _skill_sync_invalidate_caches(
    *,
    skill_name: str,
    tenant_id: str,
    project_id: str | None,
    skill_loader_tool: Any | None,
) -> dict[str, Any]:
    """Invalidate skill caches after sync."""
    if skill_loader_tool and hasattr(skill_loader_tool, "refresh_skills"):
        skill_loader_tool.refresh_skills()
        logger.info("SkillLoaderTool cache invalidated after skill sync")

    from src.infrastructure.agent.tools.skill_loader import skill_availability_for_tool

    availability = skill_availability_for_tool(skill_loader_tool)
    if availability is not None:
        changed = availability.include(skill_name)
        availability_summary = {
            "authority": "generation_bound",
            "changed": changed,
            "count": len(availability.snapshot()),
            "revision": availability.revision,
        }
        logger.info(
            "Generation-bound skill roster updated after skill sync: changed=%s revision=%d",
            changed,
            availability.revision,
        )
    else:
        availability_summary = {
            "authority": "unavailable",
            "changed": False,
            "count": 0,
            "revision": 0,
        }
        logger.info("No generation-bound skill roster was available after skill sync")

    from src.infrastructure.agent.tools.self_modifying_lifecycle import (
        SelfModifyingLifecycleOrchestrator,
    )

    lifecycle_result = SelfModifyingLifecycleOrchestrator.run_post_change(
        source=TOOL_NAME,
        tenant_id=tenant_id,
        project_id=project_id,
        clear_tool_definitions=False,
        metadata={"skill_name": skill_name},
    )
    lifecycle_result["skill_availability"] = availability_summary
    logger.info(
        "Skill sync lifecycle completed for tenant=%s project=%s: %s",
        tenant_id,
        project_id,
        lifecycle_result["cache_invalidation"],
    )
    return lifecycle_result


async def _skill_sync_execute_sync(
    skill_name: str,
    skill_path: str | None,
    change_summary: str | None,
    ctx: ToolContext,
    *,
    runtime: SkillSyncRuntime,
) -> ToolResult:
    """Execute the core skill sync operation (DB + sandbox)."""
    from src.application.services.skill_reverse_sync import SkillReverseSync
    from src.infrastructure.agent.state.agent_worker_state import resolve_project_base_path
    from src.infrastructure.plugins.v2.boundary import current_operation_context_v2
    from src.infrastructure.plugins.v2.skill_repository_operation_authority_v2 import (
        skill_repository_child_operation_authority_v2,
    )

    assert runtime.session_factory is not None
    assert runtime.sandbox_adapter is not None
    assert runtime.sandbox_id is not None
    assert runtime.tenant_id is not None
    assert runtime.skill_repository_resolver is not None

    async with (
        runtime.session_factory() as db_session,
        skill_repository_child_operation_authority_v2(
            parent_operation=current_operation_context_v2(),
            resolver=runtime.skill_repository_resolver,
            db=db_session,
            consumer="agent-skill-sync",
        ) as authority,
    ):
        reverse_sync = SkillReverseSync(
            skill_repository=authority.repository,
            skill_version_repository=authority.version_repository,
            host_project_path=resolve_project_base_path(runtime.project_id or ""),
        )

        result = await reverse_sync.sync_from_sandbox(
            skill_name=skill_name,
            tenant_id=runtime.tenant_id,
            sandbox_adapter=runtime.sandbox_adapter,
            sandbox_id=runtime.sandbox_id,
            project_id=runtime.project_id,
            change_summary=change_summary,
            created_by="agent",
            skill_path=skill_path,
        )

        if "error" in result:
            return ToolResult(
                output=str(result["error"]),
                is_error=True,
            )

        await db_session.commit()

    lifecycle_result = _skill_sync_invalidate_caches(
        skill_name=skill_name,
        tenant_id=runtime.tenant_id,
        project_id=runtime.project_id,
        skill_loader_tool=runtime.skill_loader_tool,
    )
    await ctx.emit(
        {
            "type": "toolset_changed",
            "data": {
                "source": TOOL_NAME,
                "tenant_id": runtime.tenant_id,
                "project_id": runtime.project_id,
                "skill_name": skill_name,
                "lifecycle": lifecycle_result,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    output = (
        f"Skill synced to system:\n"
        f"- Skill ID: {result['skill_id']}\n"
        f"- Version: {result['version_number']} "
        f"(label: {result['version_label']})\n"
        f"- Files synced: {result['files_synced']}\n"
        f"The skill is now available in the system and "
        f"can be used with /skill-name."
    )
    return ToolResult(
        output=output,
        title=f"Skill '{skill_name}' synced successfully",
        metadata={
            **result,
            "lifecycle": lifecycle_result,
        },
    )


def _skill_sync_prerequisite_error(runtime: SkillSyncRuntime) -> ToolResult | None:
    """Return a structured error when a required runtime capability is absent."""
    if runtime.generation_bound:
        from src.infrastructure.agent.tools.skill_loader import skill_availability_for_tool

        if skill_availability_for_tool(runtime.skill_loader_tool) is None:
            return ToolResult(
                output="Skill availability service is missing from the active generation.",
                is_error=True,
                metadata={
                    "error": "skill_availability_service_missing",
                    "service": "skill_loader",
                },
            )
    if not runtime.sandbox_adapter:
        return ToolResult(
            output="No sandbox adapter available. Sandbox may not be initialized.",
            is_error=True,
        )
    if not runtime.sandbox_id:
        return ToolResult(
            output="No sandbox ID available. Sandbox may not be attached.",
            is_error=True,
        )
    if not runtime.session_factory:
        return ToolResult(
            output="Database session factory not available.",
            is_error=True,
        )
    if runtime.skill_repository_resolver is None:
        return ToolResult(
            output="Skill repository service is missing from the active generation.",
            is_error=True,
            metadata={
                "error": "skill_repository_service_missing",
                "service": "service:application.skill-repository",
            },
        )
    return None


@tool_define(
    name=TOOL_NAME,
    description=TOOL_DESCRIPTION,
    parameters={
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill to sync (e.g., 'my-skill')",
            },
            "skill_path": {
                "type": "string",
                "description": (
                    "Path to skill directory in sandbox. "
                    "Default: /workspace/.memstack/skills/{skill_name}"
                ),
            },
            "change_summary": {
                "type": "string",
                "description": ("Optional description of what changed in this version"),
            },
        },
        "required": ["skill_name"],
    },
    permission=None,
    category="skill_management",
)
async def skill_sync_tool(
    ctx: ToolContext,
    *,
    skill_name: str,
    skill_path: str | None = None,
    change_summary: str | None = None,
) -> ToolResult:
    """Sync a skill from the sandbox to the system."""
    runtime = _current_skill_sync_runtime()
    if runtime is None:
        return ToolResult(
            output="Skill sync requires a generation-bound runtime.",
            is_error=True,
            metadata={
                "error": "skill_sync_runtime_unavailable",
                "service": TOOL_NAME,
            },
        )
    skill_name = skill_name.strip()
    if not skill_name:
        return ToolResult(
            output="skill_name is required",
            is_error=True,
        )

    prerequisite_error = _skill_sync_prerequisite_error(runtime)
    if prerequisite_error is not None:
        return prerequisite_error

    try:
        return await _skill_sync_execute_sync(
            skill_name,
            skill_path,
            change_summary,
            ctx,
            runtime=runtime,
        )
    except Exception as e:
        logger.error(
            "Skill sync failed for '%s': %s",
            skill_name,
            e,
            exc_info=True,
        )
        return ToolResult(
            output=f"Skill sync failed: {e}",
            is_error=True,
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class _BoundSkillSyncExecutor:
    template: ToolInfo
    runtime: SkillSyncRuntime

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:
        token = _skill_sync_runtime.set(self.runtime)
        try:
            return await self.template.execute(ctx, **kwargs)
        finally:
            _skill_sync_runtime.reset(token)


def bind_skill_sync_repository_authority_v2(
    tool: object,
    *,
    resolver: object,
) -> ToolInfo:
    """Bind the Profile-selected Skill repository resolver to one prepared tool."""
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
    from src.infrastructure.plugins.v2.skill_repository_services import (
        SkillRepositoryApplicationResolverProtocolV2,
    )

    if not isinstance(resolver, SkillRepositoryApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_skill_repository_application_resolver",
            "Skill sync received an invalid Skill repository resolver",
        )
    if not isinstance(tool, ToolInfo) or tool.name != TOOL_NAME:
        raise RuntimeV2Error(
            "invalid_prepared_skill_sync_tool",
            "Skill sync repository binding requires the prepared skill_sync ToolInfo",
        )
    executor = tool.execute
    if not isinstance(executor, _BoundSkillSyncExecutor):
        raise RuntimeV2Error(
            "invalid_prepared_skill_sync_tool",
            "Prepared skill_sync ToolInfo has an invalid executor",
        )
    runtime = replace(executor.runtime, skill_repository_resolver=resolver)
    return replace(
        tool,
        execute=replace(executor, runtime=runtime),
    )


def make_skill_sync_tool(
    *,
    tenant_id: str,
    project_id: str | None = None,
    sandbox_adapter: Any | None = None,
    sandbox_id: str | None = None,
    session_factory: Callable[..., Any] | None = None,
    skill_loader_tool: Any | None = None,
) -> ToolInfo:
    """Return a skill-sync ToolInfo bound to one generation dependency set."""
    runtime = SkillSyncRuntime(
        tenant_id=tenant_id,
        project_id=project_id,
        sandbox_adapter=sandbox_adapter,
        sandbox_id=sandbox_id,
        session_factory=session_factory,
        skill_loader_tool=skill_loader_tool,
        skill_repository_resolver=None,
        generation_bound=True,
    )
    return replace(
        skill_sync_tool,
        execute=_BoundSkillSyncExecutor(template=skill_sync_tool, runtime=runtime),
    )
