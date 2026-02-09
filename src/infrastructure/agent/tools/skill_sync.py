"""
SkillSyncTool - Agent tool for syncing skills from sandbox to the system.

After the agent creates or updates a skill inside the sandbox via
skill-creator, it calls this tool to register the skill with the
system (database + host filesystem + cache).

Each sync creates a versioned snapshot of the skill's SKILL.md and
all resource files.
"""

import logging
from typing import Any, Dict, Optional, Union

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
        sandbox_adapter: Optional[Any] = None,
        sandbox_id: Optional[str] = None,
        session_factory: Optional[Any] = None,
        skill_loader_tool: Optional[Any] = None,
    ) -> None:
        super().__init__(name=TOOL_NAME, description=TOOL_DESCRIPTION)
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id
        self._session_factory = session_factory
        self._skill_loader_tool = skill_loader_tool

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

    async def execute(self, **kwargs: Any) -> Union[str, Dict[str, Any]]:
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

            # Invalidate caches
            self._invalidate_caches()

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
                "metadata": result,
            }

        except Exception as e:
            logger.error(f"Skill sync failed for '{skill_name}': {e}", exc_info=True)
            return {"error": f"Skill sync failed: {e}"}

    def _invalidate_caches(self) -> None:
        """Invalidate skill caches after sync."""
        # Refresh SkillLoaderTool cache
        if self._skill_loader_tool and hasattr(self._skill_loader_tool, "refresh_skills"):
            try:
                self._skill_loader_tool.refresh_skills()
                logger.info("SkillLoaderTool cache invalidated after skill sync")
            except Exception as e:
                logger.warning(f"Failed to invalidate SkillLoaderTool cache: {e}")

        # Invalidate worker-level caches
        try:
            from src.infrastructure.agent.state.agent_worker_state import (
                invalidate_skill_loader_cache,
            )

            invalidate_skill_loader_cache(self._tenant_id)
            logger.info(f"Worker skill_loader cache invalidated for tenant {self._tenant_id}")
        except Exception as e:
            logger.warning(f"Failed to invalidate worker caches: {e}")
