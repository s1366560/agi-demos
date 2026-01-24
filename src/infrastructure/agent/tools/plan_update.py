"""
Plan Update Tool for modifying plan content.

This tool allows the agent to update the plan document content
while in Plan Mode. Supports full replacement, append, and
section-specific updates.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from src.domain.model.agent.plan import InvalidPlanStateError, PlanNotFoundError
from src.domain.ports.repositories import PlanRepository
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class PlanUpdateTool(AgentTool):
    """
    Tool for updating plan document content.

    When invoked, this tool:
    1. Validates the plan is editable
    2. Updates the content (full replace, append, or section update)
    3. Persists the changes
    4. Emits plan_updated SSE event

    Usage:
        plan_update = PlanUpdateTool(plan_repository)
        result = await plan_update.execute(
            plan_id="plan-456",
            content="Updated plan content...",
            mode="replace"
        )
    """

    def __init__(self, plan_repository: PlanRepository):
        """
        Initialize the plan update tool.

        Args:
            plan_repository: Repository for Plan entities
        """
        super().__init__(
            name="plan_update",
            description=(
                "Update the plan document content. Use 'replace' mode to replace all content, "
                "'append' mode to add content at the end, or 'section' mode to update a specific section. "
                "Also supports adding explored files and critical files to the plan metadata."
            ),
        )
        self.plan_repository = plan_repository

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate plan update arguments."""
        if "plan_id" not in kwargs:
            logger.error("Missing required argument: plan_id")
            return False

        mode = kwargs.get("mode", "replace")
        if mode not in ("replace", "append", "section"):
            logger.error(f"Invalid mode: {mode}")
            return False

        if mode == "section":
            if "section_name" not in kwargs:
                logger.error("section_name is required for section mode")
                return False

        # Content is optional when only updating metadata
        content = kwargs.get("content")
        explored_files = kwargs.get("explored_files")
        critical_files = kwargs.get("critical_files")

        if not content and not explored_files and not critical_files:
            logger.error("At least one of content, explored_files, or critical_files is required")
            return False

        return True

    async def execute(
        self,
        plan_id: str,
        content: Optional[str] = None,
        mode: str = "replace",
        section_name: Optional[str] = None,
        explored_files: Optional[List[str]] = None,
        critical_files: Optional[List[Dict[str, str]]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute plan content update.

        Args:
            plan_id: The plan document ID
            content: New content (Markdown format)
            mode: Update mode - 'replace', 'append', or 'section'
            section_name: Section to update (required for 'section' mode)
            explored_files: List of file paths that were explored
            critical_files: List of critical files with format [{"path": "...", "type": "modify|create|delete"}]

        Returns:
            JSON string with update result

        Raises:
            PlanNotFoundError: If the plan doesn't exist
            InvalidPlanStateError: If the plan is not editable
        """
        # Validate arguments
        if not self.validate_args(
            plan_id=plan_id,
            content=content,
            mode=mode,
            section_name=section_name,
            explored_files=explored_files,
            critical_files=critical_files,
        ):
            return json.dumps(
                {
                    "success": False,
                    "error": "Invalid arguments for plan_update",
                }
            )

        try:
            # Fetch the plan
            plan = await self.plan_repository.find_by_id(plan_id)
            if not plan:
                raise PlanNotFoundError(plan_id)

            # Check if plan is editable
            if not plan.is_editable:
                raise InvalidPlanStateError(plan.status, "update")

            old_version = plan.version

            # Update content based on mode
            if content:
                if mode == "replace":
                    plan.update_content(content)
                elif mode == "append":
                    plan.append_content(content)
                elif mode == "section":
                    updated_content = self._update_section(
                        plan.content,
                        section_name,
                        content,
                    )
                    plan.update_content(updated_content)

            # Add explored files
            if explored_files:
                for file_path in explored_files:
                    plan.add_explored_file(file_path)

            # Add critical files
            if critical_files:
                for file_info in critical_files:
                    path = file_info.get("path", "")
                    mod_type = file_info.get("type", "modify")
                    if path:
                        plan.add_critical_file(path, mod_type)

            # Persist changes
            await self.plan_repository.save(plan)

            logger.info(
                f"Updated plan {plan_id}: mode={mode}, version {old_version} -> {plan.version}"
            )

            return json.dumps(
                {
                    "success": True,
                    "plan_id": plan_id,
                    "version": plan.version,
                    "old_version": old_version,
                    "mode": mode,
                    "message": f"Plan updated successfully (version {plan.version})",
                    "explored_files_count": len(plan.metadata.get("explored_files", [])),
                    "critical_files_count": len(plan.metadata.get("critical_files", [])),
                }
            )

        except PlanNotFoundError as e:
            logger.warning(f"Plan not found: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "error_code": "PLAN_NOT_FOUND",
                }
            )
        except InvalidPlanStateError as e:
            logger.warning(f"Invalid plan state: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "error_code": "INVALID_PLAN_STATE",
                }
            )
        except Exception as e:
            logger.error(f"Failed to update plan: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": f"Failed to update plan: {str(e)}",
                }
            )

    def _update_section(
        self,
        content: str,
        section_name: str,
        new_section_content: str,
    ) -> str:
        """
        Update a specific section in the Markdown content.

        Args:
            content: Full Markdown content
            section_name: Section header to find (e.g., "## 架构设计")
            new_section_content: New content for the section

        Returns:
            Updated content with the section replaced
        """
        lines = content.split("\n")
        result_lines = []
        in_target_section = False
        section_found = False
        target_level = 0

        for line in lines:
            # Check if this is a header line
            if line.startswith("#"):
                # Count the level (number of #)
                level = len(line) - len(line.lstrip("#"))
                header_text = line.lstrip("#").strip()

                if in_target_section:
                    # Check if we've reached the end of the target section
                    if level <= target_level:
                        # End of target section, insert new content
                        result_lines.append(new_section_content.rstrip())
                        result_lines.append("")
                        in_target_section = False
                        result_lines.append(line)
                    # Skip lines in target section (will be replaced)
                    continue
                elif section_name.lower() in header_text.lower():
                    # Found the target section
                    section_found = True
                    in_target_section = True
                    target_level = level
                    result_lines.append(line)
                    continue

            if in_target_section:
                # Skip lines in target section (will be replaced)
                continue

            result_lines.append(line)

        # Handle case where target section is at the end
        if in_target_section:
            result_lines.append(new_section_content.rstrip())

        # Handle case where section was not found - append new section
        if not section_found:
            result_lines.append("")
            result_lines.append(f"## {section_name}")
            result_lines.append(new_section_content.rstrip())

        return "\n".join(result_lines)

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan document ID to update",
                },
                "content": {
                    "type": "string",
                    "description": "New content in Markdown format",
                },
                "mode": {
                    "type": "string",
                    "enum": ["replace", "append", "section"],
                    "description": "Update mode: 'replace' replaces all content, 'append' adds to end, 'section' updates specific section",
                    "default": "replace",
                },
                "section_name": {
                    "type": "string",
                    "description": "Section name to update (required for 'section' mode)",
                },
                "explored_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths that were explored during planning",
                },
                "critical_files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "type": {"type": "string", "enum": ["create", "modify", "delete"]},
                        },
                    },
                    "description": "List of critical files that need modification",
                },
            },
            "required": ["plan_id"],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "plan_id": {"type": "string"},
                "version": {"type": "integer"},
                "old_version": {"type": "integer"},
                "mode": {"type": "string"},
                "message": {"type": "string"},
                "explored_files_count": {"type": "integer"},
                "critical_files_count": {"type": "integer"},
                "error": {"type": "string"},
                "error_code": {"type": "string"},
            },
            "description": "Result of updating the plan",
        }
