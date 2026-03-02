"""Skill loader tool for ReAct agent.

This tool provides progressive loading of skills (Claude Skills pattern).
The tool description contains Tier 1 skill metadata (name + description),
and executing the tool loads Tier 3 full content for the selected skill.

Reference: vendor/opencode/packages/opencode/src/tool/skill.ts

Features:
- Dynamic description with available skills in XML format
- Structured return format {title, output, metadata}
- Permission manager integration (optional)
- Tier-based progressive loading
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.domain.model.agent.skill import Skill
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

__all__ = [
    "configure_skill_loader_tool",
    "get_available_skills",
    "set_sandbox_id",
    "skill_loader_tool",
]



# === New @tool_define based implementation ===


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SkillLoaderDeps:
    """Dependencies for the skill_loader_tool function."""

    skill_service: Any
    tenant_id: str
    project_id: str
    agent_mode: str = "react"
    permission_manager: Any = None
    session_id: str = ""
    skill_sync_service: Any = None
    sandbox_id: str = ""

_skill_loader_deps: _SkillLoaderDeps | None = None

# Module-level skill name cache (replaces legacy SkillLoaderTool.get_available_skills)
_available_skill_names: list[str] = []


def get_available_skills() -> list[str]:
    """Return cached list of available skill names.

    This replaces the legacy ``SkillLoaderTool.get_available_skills()`` method.
    The list is populated by external callers (e.g. agent_worker_state) that
    initialise the skill loader.
    """
    return list(_available_skill_names)


def set_available_skills(names: list[str]) -> None:
    """Set the cached available skill names.

    Called externally after skill discovery to populate the cache.
    """
    global _available_skill_names
    _available_skill_names = list(names)


def set_sandbox_id(sandbox_id: str) -> None:
    """Update the sandbox_id in the module-level deps.

    This replaces the legacy ``SkillLoaderTool.set_sandbox_id()`` method.
    Re-creates ``_skill_loader_deps`` with the new sandbox_id.
    """
    global _skill_loader_deps
    if _skill_loader_deps is None:
        logger.warning("set_sandbox_id called before configure_skill_loader_tool")
        return
    _skill_loader_deps = _SkillLoaderDeps(
        skill_service=_skill_loader_deps.skill_service,
        tenant_id=_skill_loader_deps.tenant_id,
        project_id=_skill_loader_deps.project_id,
        agent_mode=_skill_loader_deps.agent_mode,
        permission_manager=_skill_loader_deps.permission_manager,
        session_id=_skill_loader_deps.session_id,
        skill_sync_service=_skill_loader_deps.skill_sync_service,
        sandbox_id=sandbox_id,
    )

def configure_skill_loader_tool(
    skill_service: Any,
    tenant_id: str,
    project_id: str,
    agent_mode: str = "react",
    permission_manager: Any = None,
    session_id: str = "",
    skill_sync_service: Any = None,
    sandbox_id: str = "",
) -> None:
    """Configure dependencies for the skill_loader tool.

    Called at agent startup to inject services needed by the tool.
    """
    global _skill_loader_deps
    _skill_loader_deps = _SkillLoaderDeps(
        skill_service=skill_service,
        tenant_id=tenant_id,
        project_id=project_id,
        agent_mode=agent_mode,
        permission_manager=permission_manager,
        session_id=session_id,
        skill_sync_service=skill_sync_service,
        sandbox_id=sandbox_id,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_available_skills(
    deps: _SkillLoaderDeps,
) -> list[Skill]:
    """Load Tier 1 skill metadata from the skill service."""
    return await deps.skill_service.list_available_skills(
        tenant_id=deps.tenant_id,
        project_id=deps.project_id,
        tier=1,
        agent_mode=deps.agent_mode,
        skip_database=True,
    )


def _format_skill_content(
    skill_name: str,
    content: str,
    file_path: str | None,
    resource_hint: str = "",
) -> str:
    """Format skill content for agent consumption."""
    base_dir = file_path or "N/A"
    return (
        f"## Skill: {skill_name}\n\n"
        f"**Base directory**: {base_dir}\n\n"
        f"{content.strip()}\n\n"
        f"{resource_hint}"
        "---\n"
        "Follow these instructions to complete the task. "
        "If you encounter issues, you can load additional "
        "skills or ask for clarification."
    )


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="skill_loader",
    description=(
        "Load detailed instructions for a specific skill. "
        "Use this when you need guidance on how to perform a "
        "specialized task."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The name of the skill to load",
            },
        },
        "required": ["name"],
    },
    permission="skill",
    category="knowledge",
    tags=frozenset({"skill", "knowledge"}),
)
async def skill_loader_tool(
    ctx: ToolContext,
    *,
    name: str,
) -> ToolResult:
    """Load full skill content by name."""
    if _skill_loader_deps is None:
        return ToolResult(
            output=("Skill loader not configured. No skill service available."),
            is_error=True,
        )

    deps = _skill_loader_deps
    skill_name = name.strip()

    if not skill_name:
        return ToolResult(
            output="skill name parameter is required.",
            is_error=True,
        )

    try:
        # Load Tier 1 metadata to find cached skill info
        skills_cache = await _load_available_skills(deps)
        cached_skill: Skill | None = next(
            (s for s in skills_cache if s.name == skill_name),
            None,
        )

        # Load full content (Tier 3)
        content: str | None = await deps.skill_service.load_skill_content(
            tenant_id=deps.tenant_id,
            skill_name=skill_name,
        )

        if not content:
            available = [s.name for s in skills_cache]
            avail_str = ", ".join(available) if available else "none"
            return ToolResult(
                output=(f"Skill '{skill_name}' not found. Available skills: {avail_str}"),
                is_error=True,
            )

        # Sync skill resources to sandbox if configured
        resource_hint = ""
        sync_svc = deps.skill_sync_service
        if sync_svc and deps.sandbox_id:
            try:
                sync_status = await sync_svc.sync_for_skill(
                    skill_name=skill_name,
                    sandbox_id=deps.sandbox_id,
                    skill_content=content,
                )
                if sync_status.synced and sync_status.resource_paths:
                    resource_hint = sync_svc.build_resource_paths_hint(
                        skill_name=skill_name,
                        resource_paths=(sync_status.resource_paths),
                    )
            except Exception as exc:
                logger.warning(
                    "Skill resource sync failed for '%s': %s",
                    skill_name,
                    exc,
                )

        # Record usage (best-effort)
        try:
            await deps.skill_service.record_skill_usage(
                tenant_id=deps.tenant_id,
                skill_name=skill_name,
                success=True,
            )
        except Exception as exc:
            logger.warning("Failed to record skill usage: %s", exc)

        file_path = cached_skill.file_path if cached_skill else None
        formatted = _format_skill_content(skill_name, content, file_path, resource_hint)

        return ToolResult(
            output=formatted,
            title=f"Loaded skill: {skill_name}",
            metadata={
                "name": skill_name,
                "skill_id": (cached_skill.id if cached_skill else None),
                "tools": (list(cached_skill.tools) if cached_skill else []),
                "dir": file_path,
                "source": (cached_skill.source.value if cached_skill else None),
            },
        )

    except Exception as exc:
        logger.error("Failed to load skill '%s': %s", skill_name, exc)
        return ToolResult(
            output=f"Error loading skill: {exc!s}",
            is_error=True,
        )
