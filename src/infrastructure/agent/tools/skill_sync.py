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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort


from src.infrastructure.agent.tools.base import AgentTool
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


class SkillSyncTool(AgentTool):
    """Agent tool for syncing skills from sandbox back to the system."""

    def __init__(
        self,
        tenant_id: str,
        project_id: str | None = None,
        sandbox_adapter: SandboxPort | None = None,
        sandbox_id: str | None = None,
        session_factory: Any | None = None,
        skill_loader_tool: Any | None = None,
    ) -> None:
        super().__init__(name=TOOL_NAME, description=TOOL_DESCRIPTION)
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id
        self._session_factory = session_factory
        self._skill_loader_tool = skill_loader_tool
        self._pending_events: list[Any] = []

    def set_sandbox_id(self, sandbox_id: str) -> None:
        """Set the sandbox ID (called when sandbox becomes available)."""
        self._sandbox_id = sandbox_id

    def set_sandbox_adapter(self, adapter: Any) -> None:
        """Set the sandbox adapter (called during initialization)."""
        self._sandbox_adapter = adapter

    def set_session_factory(self, factory: Any) -> None:
        """Set the async session factory for DB access."""
        self._session_factory = factory

    def set_skill_loader_tool(self, tool: Any) -> None:
        """Set reference to SkillLoaderTool for cache invalidation."""
        self._skill_loader_tool = tool

    def consume_pending_events(self) -> list[Any]:
        """Consume pending SSE events buffered during execute()."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
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
                    "description": "Optional description of what changed in this version",
                },
            },
            "required": ["skill_name"],
        }

    def _validate_prerequisites(self) -> str | None:
        """Validate that required dependencies are available.

        Returns:
            Error message string if validation fails, None if all prerequisites met.
        """
        if not self._sandbox_adapter:
            return "No sandbox adapter available. Sandbox may not be initialized."
        if not self._sandbox_id:
            return "No sandbox ID available. Sandbox may not be attached."
        if not self._session_factory:
            return "Database session factory not available."
        return None

    async def execute(self, **kwargs: Any) -> str | dict[str, Any]:  # type: ignore[override]
        """Execute the skill sync operation."""
        skill_name = kwargs.get("skill_name", "").strip()
        if not skill_name:
            return {"error": "skill_name is required"}

        skill_path = kwargs.get("skill_path")
        change_summary = kwargs.get("change_summary")

        prereq_error = self._validate_prerequisites()
        if prereq_error:
            return {"error": prereq_error}

        try:
            from src.application.services.skill_reverse_sync import SkillReverseSync
            from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
                SqlSkillRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
                SqlSkillVersionRepository,
            )
            from src.infrastructure.agent.state.agent_worker_state import resolve_project_base_path

            assert self._session_factory is not None
            async with self._session_factory() as db_session:
                skill_repo = SqlSkillRepository(db_session)
                version_repo = SqlSkillVersionRepository(db_session)
                reverse_sync = SkillReverseSync(
                    skill_repository=skill_repo,
                    skill_version_repository=version_repo,
                    host_project_path=resolve_project_base_path(self._project_id or ""),
                )

                assert self._sandbox_adapter is not None, "sandbox_adapter is required"
                assert self._sandbox_id is not None, "sandbox_id is required"
                result = await reverse_sync.sync_from_sandbox(
                    skill_name=skill_name,
                    tenant_id=self._tenant_id,
                    sandbox_adapter=self._sandbox_adapter,
                    sandbox_id=self._sandbox_id,
                    project_id=self._project_id,
                    change_summary=change_summary,
                    created_by="agent",
                    skill_path=skill_path,
                )

                if "error" in result:
                    return {"error": result["error"]}

                await db_session.commit()

            # Invalidate caches + run post-change lifecycle.
            lifecycle_result = self._invalidate_caches(skill_name=skill_name)
            self._pending_events.append(
                {
                    "type": "toolset_changed",
                    "data": {
                        "source": TOOL_NAME,
                        "tenant_id": self._tenant_id,
                        "project_id": self._project_id,
                        "skill_name": skill_name,
                        "lifecycle": lifecycle_result,
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

            return {
                "title": f"Skill '{skill_name}' synced successfully",
                "output": (
                    f"Skill synced to system:\n"
                    f"- Skill ID: {result['skill_id']}\n"
                    f"- Version: {result['version_number']} "
                    f"(label: {result['version_label']})\n"
                    f"- Files synced: {result['files_synced']}\n"
                    f"The skill is now available in the system and "
                    f"can be used with /skill-name."
                ),
                "metadata": {
                    **result,
                    "lifecycle": lifecycle_result,
                },
            }

        except Exception as e:
            logger.error(f"Skill sync failed for '{skill_name}': {e}", exc_info=True)
            return {"error": f"Skill sync failed: {e}"}

    def _invalidate_caches(self, *, skill_name: str) -> dict[str, Any]:
        """Invalidate skill caches after sync."""
        # Refresh SkillLoaderTool cache
        if self._skill_loader_tool and hasattr(self._skill_loader_tool, "refresh_skills"):
            self._skill_loader_tool.refresh_skills()
            logger.info("SkillLoaderTool cache invalidated after skill sync")

        from src.infrastructure.agent.tools.self_modifying_lifecycle import (
            SelfModifyingLifecycleOrchestrator,
        )

        lifecycle_result = SelfModifyingLifecycleOrchestrator.run_post_change(
            source=TOOL_NAME,
            tenant_id=self._tenant_id,
            project_id=self._project_id,
            clear_tool_definitions=False,
            metadata={"skill_name": skill_name},
        )
        logger.info(
            "Skill sync lifecycle completed for tenant=%s project=%s: %s",
            self._tenant_id,
            self._project_id,
            lifecycle_result["cache_invalidation"],
        )
        return lifecycle_result


# ---------------------------------------------------------------------------
# @tool_define version of SkillSyncTool
# ---------------------------------------------------------------------------


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
