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
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any, cast

from src.domain.model.agent.skill import Skill, SkillStatus
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

__all__ = [
    "SkillAvailabilityV2",
    "make_skill_loader_tool",
    "skill_availability_for_tool",
    "skill_loader_tool",
]


# === New @tool_define based implementation ===


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------


class SkillAvailabilityV2:
    """Generation-bound roster exposed by one skill-loader contribution."""

    __slots__ = ("_lock", "_names", "_revision")

    def __init__(self, names: Sequence[str] = ()) -> None:
        self._lock = Lock()
        self._names: list[str] = []
        self._revision = 0
        seen: set[str] = set()
        for raw_name in names:
            name = raw_name.strip()
            if name and name not in seen:
                self._names.append(name)
                seen.add(name)

    @property
    def revision(self) -> int:
        """Return the roster revision for refresh diagnostics."""
        with self._lock:
            return self._revision

    def snapshot(self) -> tuple[str, ...]:
        """Return an immutable roster snapshot in declaration order."""
        with self._lock:
            return tuple(self._names)

    def include(self, skill_name: str) -> bool:
        """Add one skill to this generation and report whether it changed."""
        normalized = skill_name.strip()
        if not normalized:
            return False
        with self._lock:
            if normalized in self._names:
                return False
            self._names.append(normalized)
            self._revision += 1
            return True


@dataclass(frozen=True, kw_only=True, slots=True)
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
    skip_database: bool = True
    skill_availability: SkillAvailabilityV2 | None = None
    marketplace_skill_resolver: Callable[[str], Awaitable[Skill | None]] | None = None


_skill_loader_runtime: ContextVar[_SkillLoaderDeps | None] = ContextVar(
    f"{__name__}.skill_loader_runtime",
    default=None,
)


def _current_skill_loader_deps() -> _SkillLoaderDeps | None:
    return _skill_loader_runtime.get()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_available_skills(
    deps: _SkillLoaderDeps,
) -> list[Skill]:
    """Load Tier 1 skill metadata from the skill service."""
    skills: object = await deps.skill_service.list_available_skills(
        tenant_id=deps.tenant_id,
        project_id=deps.project_id,
        tier=1,
        agent_mode=deps.agent_mode,
        skip_database=deps.skip_database,
        status=SkillStatus.ACTIVE,
    )
    return cast(list[Skill], skills)


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


def _load_skill_content_from_cwd(skill_name: str) -> tuple[str | None, str | None]:
    """Fallback skill content loading from current working directory."""
    from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner
    from src.infrastructure.skill.markdown_parser import MarkdownParser

    scanner = FileSystemSkillScanner()
    file_info = scanner.find_skill(Path.cwd(), skill_name)
    if not file_info:
        return None, None

    try:
        markdown = MarkdownParser().parse_file(str(file_info.file_path))
        return markdown.content, str(file_info.file_path)
    except Exception as exc:
        logger.warning("CWD fallback skill load failed for '%s': %s", skill_name, exc)
        return None, None


def _is_skill_allowed(ctx: ToolContext, skill_name: str) -> bool:
    """Check request-scoped skill allowlist from the runtime context."""
    allowed_skills = ctx.runtime_context.get("allowed_skills")
    if not isinstance(allowed_skills, list) or not allowed_skills:
        return True
    normalized_allowed = {
        str(item).strip().lower()
        for item in allowed_skills
        if isinstance(item, str) and item.strip()
    }
    return skill_name.strip().lower() in normalized_allowed


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
    permission="read",
    category="knowledge",
    tags=frozenset({"skill", "knowledge"}),
)
async def skill_loader_tool(  # noqa: C901
    ctx: ToolContext,
    *,
    name: str,
) -> ToolResult:
    """Load full skill content by name."""
    deps = _current_skill_loader_deps()
    if deps is None:
        return ToolResult(
            output="Skill loader requires a generation-bound runtime.",
            is_error=True,
            metadata={
                "error": "skill_loader_runtime_unavailable",
                "service": "skill_loader",
            },
        )

    skill_name = name.strip()

    if not skill_name:
        return ToolResult(
            output="skill name parameter is required.",
            is_error=True,
        )

    if not _is_skill_allowed(ctx, skill_name):
        return ToolResult(
            output=f"Skill '{skill_name}' is not allowed for the active agent profile.",
            is_error=True,
        )

    try:
        owned_skill = (
            await deps.marketplace_skill_resolver(skill_name)
            if deps.marketplace_skill_resolver is not None
            else None
        )
        # Load Tier 1 metadata to find cached skill info
        skills_cache = [owned_skill] if owned_skill else await _load_available_skills(deps)
        cached_skill: Skill | None = owned_skill or next(
            (s for s in skills_cache if s.name == skill_name),
            None,
        )

        # Load full content (Tier 3)
        content: str | None = (
            owned_skill.full_content
            if owned_skill
            else await deps.skill_service.load_skill_content(
                tenant_id=deps.tenant_id,
                skill_name=skill_name,
                project_id=deps.project_id,
            )
        )
        resolved_file_path = cached_skill.file_path if cached_skill else None

        if not content:
            fallback_content, fallback_file_path = _load_skill_content_from_cwd(skill_name)
            if fallback_content:
                content = fallback_content
                if not resolved_file_path:
                    resolved_file_path = fallback_file_path

        if not content:
            runtime_names = (
                deps.skill_availability.snapshot() if deps.skill_availability is not None else ()
            )
            available = sorted({s.name for s in skills_cache} | set(runtime_names))
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
                project_id=deps.project_id,
            )
        except Exception as exc:
            logger.warning("Failed to record skill usage: %s", exc)

        file_path = resolved_file_path
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


@dataclass(frozen=True, kw_only=True, slots=True)
class _BoundSkillLoaderExecutor:
    template: ToolInfo
    runtime: _SkillLoaderDeps

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:
        token = _skill_loader_runtime.set(self.runtime)
        try:
            return await self.template.execute(ctx, **kwargs)
        finally:
            _skill_loader_runtime.reset(token)


def skill_availability_for_tool(tool: Any) -> SkillAvailabilityV2 | None:
    """Resolve the generation-bound roster carried by a loader contribution."""
    tool_instance = getattr(tool, "_tool_instance", None)
    candidate = tool_instance if tool_instance is not None else tool
    executor = getattr(candidate, "execute", None)
    if isinstance(executor, _BoundSkillLoaderExecutor):
        return executor.runtime.skill_availability
    return None


def make_skill_loader_tool(
    *,
    skill_service: Any,
    tenant_id: str,
    project_id: str,
    agent_mode: str = "react",
    permission_manager: Any = None,
    session_id: str = "",
    skill_sync_service: Any = None,
    sandbox_id: str = "",
    skip_database: bool = True,
    available_skill_names: Sequence[str] = (),
    marketplace_skill_resolver: Callable[[str], Awaitable[Skill | None]] | None = None,
) -> ToolInfo:
    """Return a SkillLoader ToolInfo bound to one generation dependency set."""
    runtime = _SkillLoaderDeps(
        marketplace_skill_resolver=marketplace_skill_resolver,
        skill_service=skill_service,
        tenant_id=tenant_id,
        project_id=project_id,
        agent_mode=agent_mode,
        permission_manager=permission_manager,
        session_id=session_id,
        skill_sync_service=skill_sync_service,
        sandbox_id=sandbox_id,
        skip_database=skip_database,
        skill_availability=SkillAvailabilityV2(available_skill_names),
    )
    return replace(
        skill_loader_tool,
        execute=_BoundSkillLoaderExecutor(template=skill_loader_tool, runtime=runtime),
        # Resource synchronization writes into the sandbox; a content-only
        # loader does not inherit the installer's mutation permission.
        permission="skill" if skill_sync_service is not None and sandbox_id else "read",
        sandbox_id=sandbox_id or None,
    )
