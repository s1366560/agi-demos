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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from src.application.services.skill_service import SkillService
from src.domain.model.agent.skill import Skill
from src.infrastructure.agent.tools.base import AgentTool

if TYPE_CHECKING:
    from src.application.services.skill_resource_sync_service import SkillResourceSyncService
    from src.infrastructure.agent.permission.manager import PermissionManager

logger = logging.getLogger(__name__)


class SkillLoaderTool(AgentTool):
    """
    Tool for loading skill instructions on-demand.

    Implements the Claude Skills progressive loading pattern:
    - Tier 1: Tool description contains skill list (injected at startup)
    - Tier 2: Matching happens based on triggers (handled by SkillExecutor)
    - Tier 3: This tool loads full content when called

    The tool description is dynamically built to include available skills
    in XML format (reference: OpenCode SkillTool), minimizing token usage
    until a skill is actually needed.

    Features:
    - Structured return format {title, output, metadata}
    - Permission manager integration for skill access control
    - XML-formatted skill list in description
    """

    def __init__(
        self,
        skill_service: SkillService,
        tenant_id: str,
        project_id: Optional[str] = None,
        agent_mode: str = "default",
        permission_manager: Optional[PermissionManager] = None,
        session_id: Optional[str] = None,
        resource_sync_service: Optional[SkillResourceSyncService] = None,
        sandbox_id: Optional[str] = None,
    ):
        """
        Initialize the skill loader tool.

        Args:
            skill_service: Service for skill operations
            tenant_id: Tenant ID for skill scoping
            project_id: Optional project ID for filtering
            agent_mode: Agent mode for filtering skills (e.g., "default", "plan")
            permission_manager: Optional permission manager for access control
            session_id: Optional session ID for permission requests
            resource_sync_service: Optional sync service for sandbox resource injection
            sandbox_id: Optional sandbox ID for resource sync target
        """
        # Initialize with placeholder description
        super().__init__(
            name="skill_loader",
            description="Load detailed instructions for a specific skill. "
            "Use this when you need guidance on how to perform a specialized task.",
        )
        self._skill_service = skill_service
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._agent_mode = agent_mode
        self._permission_manager = permission_manager
        self._session_id = session_id
        self._resource_sync_service = resource_sync_service
        self._sandbox_id = sandbox_id
        self._skills_cache: List[Skill] = []
        self._description_built = False

    async def initialize(self) -> None:
        """
        Initialize the tool by loading skill metadata.

        Fetches Tier 1 skill data and builds the tool description.
        Should be called during agent setup.
        """
        if self._description_built:
            return

        try:
            # Load Tier 1 metadata (name + description only), filtered by agent_mode
            # Use skip_database=True to avoid SQLAlchemy concurrent session errors
            # when running in async context with shared sessions
            self._skills_cache = await self._skill_service.list_available_skills(
                tenant_id=self._tenant_id,
                project_id=self._project_id,
                tier=1,
                agent_mode=self._agent_mode,
                skip_database=True,
            )

            # Build dynamic description
            self._description = self._build_description()
            self._description_built = True

            logger.info(
                f"SkillLoaderTool initialized with {len(self._skills_cache)} skills "
                f"for agent_mode={self._agent_mode}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize SkillLoaderTool: {e}")
            # Keep default description on failure

    async def initialize_with_skills(self, skills: List[Skill]) -> None:
        """
        Initialize the tool with preloaded skills.

        This avoids re-scanning the filesystem when skills are already cached
        by the agent worker.

        Args:
            skills: Preloaded skills to use for description and enum values
        """
        if self._description_built:
            return

        try:
            self._skills_cache = list(skills)
            self._description = self._build_description()
            self._description_built = True
            logger.info(
                f"SkillLoaderTool initialized from cache with {len(self._skills_cache)} skills "
                f"for agent_mode={self._agent_mode}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize SkillLoaderTool from cache: {e}")

    def set_agent_mode(self, agent_mode: str) -> None:
        """
        Set the agent mode and trigger skill cache refresh.

        Args:
            agent_mode: New agent mode (e.g., "default", "plan")
        """
        if agent_mode != self._agent_mode:
            self._agent_mode = agent_mode
            self._description_built = False
            self._skills_cache = []

    def _build_description(self) -> str:
        """
        Build the tool description with skill list in XML format.

        Reference: OpenCode SkillTool description format

        Returns:
            Formatted description containing available skills in XML
        """
        if not self._skills_cache:
            return (
                "Load a skill to get detailed instructions for a specific task. "
                "Skills provide specialized knowledge and step-by-step guidance. "
                "No skills currently available."
            )

        # Build XML-formatted skill list (reference: OpenCode)
        lines = [
            "Load a skill to get detailed instructions for a specific task.",
            "Skills provide specialized knowledge and step-by-step guidance.",
            "Use this when a task matches an available skill's description.",
            "Only the skills listed here are available:",
            "<available_skills>",
        ]

        for skill in self._skills_cache:
            lines.extend(
                [
                    "  <skill>",
                    f"    <name>{skill.name}</name>",
                    f"    <description>{skill.description}</description>",
                    "  </skill>",
                ]
            )

        lines.append("</available_skills>")

        # Add usage hint with examples
        skill_names = [s.name for s in self._skills_cache[:3]]
        if skill_names:
            examples = ", ".join(f"'{name}'" for name in skill_names)
            lines.append(
                f"\nExample usage: skill_loader(skill_name={examples[:-1] if len(skill_names) == 1 else examples})"
            )

        return "\n".join(lines)

    @property
    def description(self) -> str:
        """Get the tool description."""
        return self._description

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        # Build enum from cached skills if available
        skill_names = [skill.name for skill in self._skills_cache]

        schema: Dict[str, Any] = {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "The name of the skill to load",
                },
            },
            "required": ["skill_name"],
        }

        # Add enum constraint if we have skills
        if skill_names:
            schema["properties"]["skill_name"]["enum"] = skill_names

        return schema

    def validate_args(self, **kwargs: Any) -> bool:  # noqa: ANN401
        """Validate that skill_name argument is provided."""
        skill_name = kwargs.get("skill_name")
        if not isinstance(skill_name, str) or not skill_name.strip():
            return False
        return True

    async def execute(self, **kwargs: Any) -> Union[str, Dict[str, Any]]:  # noqa: ANN401
        """
        Execute skill loading.

        Loads the full content (Tier 3) of the specified skill.

        Reference: OpenCode SkillTool.execute()

        Args:
            **kwargs: Must contain 'skill_name' (name of skill to load)

        Returns:
            Structured dict with {title, output, metadata} on success,
            or error dict on failure. Falls back to string for compatibility.
        """
        skill_name = kwargs.get("skill_name", "").strip()

        if not skill_name:
            return self._error_response("skill_name parameter is required")

        try:
            # Find skill in cache to get metadata
            cached_skill = next((s for s in self._skills_cache if s.name == skill_name), None)

            # Load full content (Tier 3)
            content = await self._skill_service.load_skill_content(
                tenant_id=self._tenant_id,
                skill_name=skill_name,
            )

            if not content:
                # Try to provide helpful error
                available = [s.name for s in self._skills_cache]
                return self._error_response(
                    f"Skill '{skill_name}' not found",
                    available_skills=available,
                )

            # Sync skill resources to sandbox (if sync service and sandbox available)
            resource_hint = ""
            if self._resource_sync_service and self._sandbox_id:
                try:
                    sync_status = await self._resource_sync_service.sync_for_skill(
                        skill_name=skill_name,
                        sandbox_id=self._sandbox_id,
                        skill_content=content,
                    )
                    if sync_status.synced and sync_status.resource_paths:
                        resource_hint = self._resource_sync_service.build_resource_paths_hint(
                            skill_name=skill_name,
                            resource_paths=sync_status.resource_paths,
                        )
                except Exception as e:
                    logger.warning(f"Skill resource sync failed for '{skill_name}': {e}")

            # Record usage (async, don't wait)
            try:
                await self._skill_service.record_skill_usage(
                    tenant_id=self._tenant_id,
                    skill_name=skill_name,
                    success=True,
                )
            except Exception as e:
                logger.warning(f"Failed to record skill usage: {e}")

            # Return structured result (reference: OpenCode)
            return {
                "title": f"Loaded skill: {skill_name}",
                "output": self._format_skill_content(skill_name, content, resource_hint),
                "metadata": {
                    "name": skill_name,
                    "skill_id": cached_skill.id if cached_skill else None,
                    "tools": list(cached_skill.tools) if cached_skill else [],
                    "dir": cached_skill.file_path if cached_skill else None,
                    "source": cached_skill.source.value if cached_skill else None,
                },
            }

        except Exception as e:
            logger.error(f"Failed to load skill '{skill_name}': {e}")
            return self._error_response(f"Error loading skill: {e!s}")

    def _format_skill_content(self, skill_name: str, content: str, resource_hint: str = "") -> str:
        """
        Format skill content for agent consumption.

        Reference: OpenCode SkillTool output format

        Args:
            skill_name: Name of the loaded skill
            content: Raw skill content
            resource_hint: Optional resource path hints for sandbox

        Returns:
            Formatted content string
        """
        # Find skill to get file path
        cached_skill = next((s for s in self._skills_cache if s.name == skill_name), None)
        base_dir = cached_skill.file_path if cached_skill else "N/A"

        return (
            f"## Skill: {skill_name}\n\n"
            f"**Base directory**: {base_dir}\n\n"
            f"{content.strip()}\n\n"
            f"{resource_hint}"
            "---\n"
            "Follow these instructions to complete the task. "
            "If you encounter issues, you can load additional skills or ask for clarification."
        )

    def _error_response(
        self,
        message: str,
        available_skills: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a structured error response.

        Args:
            message: Error message
            available_skills: Optional list of available skill names

        Returns:
            Structured error dict
        """
        output = f"Error: {message}"
        if available_skills:
            output += f"\n\nAvailable skills: {', '.join(available_skills)}"

        return {
            "title": "Skill Loading Error",
            "output": output,
            "metadata": {
                "error": True,
                "message": message,
                "available_skills": available_skills or [],
            },
        }

    def get_available_skills(self) -> List[str]:
        """
        Get list of available skill names.

        Returns:
            List of skill names from cache
        """
        return [skill.name for skill in self._skills_cache]

    def refresh_skills(self) -> None:
        """
        Mark skills cache for refresh on next access.

        Call this when skills may have changed on disk.
        """
        self._description_built = False
        self._skills_cache = []

    def set_session_id(self, session_id: str) -> None:
        """
        Set the session ID for permission requests.

        Args:
            session_id: Session ID to use for permission requests
        """
        self._session_id = session_id

    def set_permission_manager(self, permission_manager: PermissionManager) -> None:
        """
        Set the permission manager for access control.

        Args:
            permission_manager: Permission manager instance
        """
        self._permission_manager = permission_manager

    def set_sandbox_id(self, sandbox_id: str) -> None:
        """
        Set the sandbox ID for resource synchronization.

        Args:
            sandbox_id: Sandbox container ID
        """
        self._sandbox_id = sandbox_id

    def set_resource_sync_service(self, sync_service: SkillResourceSyncService) -> None:
        """
        Set the resource sync service for sandbox resource injection.

        Args:
            sync_service: SkillResourceSyncService instance
        """
        self._resource_sync_service = sync_service

    def get_output_schema(self) -> Dict[str, Any]:
        """Get the output schema for tool composition."""
        return {
            "type": "object",
            "description": "Structured skill loading result",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title of the loaded skill",
                },
                "output": {
                    "type": "string",
                    "description": "Skill instructions in markdown format",
                    "content_type": "text/markdown",
                },
                "metadata": {
                    "type": "object",
                    "description": "Skill metadata",
                    "properties": {
                        "name": {"type": "string"},
                        "skill_id": {"type": "string"},
                        "tools": {"type": "array", "items": {"type": "string"}},
                        "dir": {"type": "string"},
                        "source": {"type": "string"},
                    },
                },
            },
        }
