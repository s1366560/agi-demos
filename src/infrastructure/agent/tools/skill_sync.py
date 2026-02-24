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
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort


from src.infrastructure.agent.tools.base import AgentTool

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
        project_id: Optional[str] = None,
        sandbox_adapter: Optional[SandboxPort] = None,
        sandbox_id: Optional[str] = None,
        session_factory: Optional[Any] = None,  # noqa: ANN401
        skill_loader_tool: Optional[Any] = None,  # noqa: ANN401
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

    def set_sandbox_adapter(self, adapter: Any) -> None:  # noqa: ANN401
        """Set the sandbox adapter (called during initialization)."""
        self._sandbox_adapter = adapter

    def set_session_factory(self, factory: Any) -> None:  # noqa: ANN401
        """Set the async session factory for DB access."""
        self._session_factory = factory

    def set_skill_loader_tool(self, tool: Any) -> None:  # noqa: ANN401
        """Set reference to SkillLoaderTool for cache invalidation."""
        self._skill_loader_tool = tool

    def consume_pending_events(self) -> list[Any]:
        """Consume pending SSE events buffered during execute()."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> Dict[str, Any]:
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

    async def execute(self, **kwargs: Any) -> Union[str, Dict[str, Any]]:  # noqa: ANN401
        """Execute the skill sync operation."""
        skill_name = kwargs.get("skill_name", "").strip()
        if not skill_name:
            return {"error": "skill_name is required"}

        skill_path = kwargs.get("skill_path")
        change_summary = kwargs.get("change_summary")

        # Validate prerequisites
        if not self._sandbox_adapter:
            return {"error": "No sandbox adapter available. Sandbox may not be initialized."}

        if not self._sandbox_id:
            return {"error": "No sandbox ID available. Sandbox may not be attached."}

        if not self._session_factory:
            return {"error": "Database session factory not available."}

        try:
            from pathlib import Path

            from src.application.services.skill_reverse_sync import SkillReverseSync
            from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
                SqlSkillRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
                SqlSkillVersionRepository,
            )

            async with self._session_factory() as db_session:
                skill_repo = SqlSkillRepository(db_session)
                version_repo = SqlSkillVersionRepository(db_session)
                reverse_sync = SkillReverseSync(
                    skill_repository=skill_repo,
                    skill_version_repository=version_repo,
                    host_project_path=Path.cwd(),
                )

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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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

    def _invalidate_caches(self, *, skill_name: str) -> Dict[str, Any]:
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
