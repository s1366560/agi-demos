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
from datetime import UTC, datetime
from typing import Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

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




_skill_sync_tenant_id: str | None = None
_skill_sync_project_id: str | None = None
_skill_sync_sandbox_adapter: Any | None = None
_skill_sync_sandbox_id: str | None = None
_skill_sync_session_factory: Callable[..., Any] | None = None
_skill_sync_skill_loader_tool: Any | None = None


def configure_skill_sync(
    tenant_id: str,
    project_id: str | None = None,
    sandbox_adapter: Any | None = None,
    sandbox_id: str | None = None,
    session_factory: Any | None = None,
    skill_loader_tool: Any | None = None,
) -> None:
    """Configure dependencies for the skill_sync tool.

    Called at agent startup to inject required context.
    """
    global _skill_sync_tenant_id, _skill_sync_project_id
    global _skill_sync_sandbox_adapter, _skill_sync_sandbox_id
    global _skill_sync_session_factory, _skill_sync_skill_loader_tool
    _skill_sync_tenant_id = tenant_id
    _skill_sync_project_id = project_id
    _skill_sync_sandbox_adapter = sandbox_adapter
    _skill_sync_sandbox_id = sandbox_id
    _skill_sync_session_factory = session_factory
    _skill_sync_skill_loader_tool = skill_loader_tool


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
) -> ToolResult:
    """Execute the core skill sync operation (DB + sandbox)."""
    from src.application.services.skill_reverse_sync import SkillReverseSync
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )
    from src.infrastructure.agent.state.agent_worker_state import resolve_project_base_path

    assert _skill_sync_session_factory is not None
    assert _skill_sync_sandbox_adapter is not None
    assert _skill_sync_sandbox_id is not None
    assert _skill_sync_tenant_id is not None

    async with _skill_sync_session_factory() as db_session:
        skill_repo = SqlSkillRepository(db_session)
        version_repo = SqlSkillVersionRepository(db_session)
        reverse_sync = SkillReverseSync(
            skill_repository=skill_repo,
            skill_version_repository=version_repo,
            host_project_path=resolve_project_base_path(_skill_sync_project_id or ""),
        )

        result = await reverse_sync.sync_from_sandbox(
            skill_name=skill_name,
            tenant_id=_skill_sync_tenant_id,
            sandbox_adapter=_skill_sync_sandbox_adapter,
            sandbox_id=_skill_sync_sandbox_id,
            project_id=_skill_sync_project_id,
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
        tenant_id=_skill_sync_tenant_id,
        project_id=_skill_sync_project_id,
        skill_loader_tool=_skill_sync_skill_loader_tool,
    )
    await ctx.emit(
        {
            "type": "toolset_changed",
            "data": {
                "source": TOOL_NAME,
                "tenant_id": _skill_sync_tenant_id,
                "project_id": _skill_sync_project_id,
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
    skill_name = skill_name.strip()
    if not skill_name:
        return ToolResult(
            output="skill_name is required",
            is_error=True,
        )

    # Validate prerequisites
    if not _skill_sync_sandbox_adapter:
        return ToolResult(
            output="No sandbox adapter available. Sandbox may not be initialized.",
            is_error=True,
        )
    if not _skill_sync_sandbox_id:
        return ToolResult(
            output="No sandbox ID available. Sandbox may not be attached.",
            is_error=True,
        )
    if not _skill_sync_session_factory:
        return ToolResult(
            output="Database session factory not available.",
            is_error=True,
        )

    try:
        return await _skill_sync_execute_sync(
            skill_name,
            skill_path,
            change_summary,
            ctx,
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
