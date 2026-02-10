"""Skill Resource Sync Service.

Provides a unified sync-on-load mechanism for synchronizing skill resources
to sandbox containers. This service is called from multiple trigger points:

1. SkillLoaderTool.execute() - when LLM loads a skill via the skill_loader tool
2. ReActAgent INJECT mode - when a matched skill is injected into the system prompt
3. SkillExecutor.execute() - existing direct execution path (unchanged)

The service ensures resources are synced exactly once per (sandbox_id, skill_name)
pair, using the existing version cache in SandboxSkillResourceAdapter.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from src.domain.ports.services.skill_resource_port import (
    ResourceEnvironment,
    ResourceSyncResult,
    SkillResource,
    SkillResourceContext,
    SkillResourcePort,
)

logger = logging.getLogger(__name__)

# Container base path matching SandboxSkillResourceAdapter.CONTAINER_SKILL_BASE
CONTAINER_SKILL_BASE = "/workspace/.memstack/skills"


@dataclass
class SkillSyncStatus:
    """Status of skill resource synchronization."""

    synced: bool = False
    resource_paths: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class SkillResourceSyncService:
    """Unified service for synchronizing skill resources to sandbox.

    Wraps SkillResourcePort to provide:
    - Idempotent sync (leverages adapter's version cache)
    - Path hint generation for LLM context
    - Environment setup after sync
    - Tracking of synced skills per sandbox session
    """

    def __init__(
        self,
        skill_resource_port: SkillResourcePort,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        project_path: Optional[Path] = None,
    ) -> None:
        self._resource_port = skill_resource_port
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._project_path = project_path or Path("/workspace")
        # Track which skills have been synced in this session
        self._synced_skills: Set[tuple[str, str]] = set()  # (sandbox_id, skill_name)

    async def sync_for_skill(
        self,
        skill_name: str,
        sandbox_id: Optional[str] = None,
        skill_content: Optional[str] = None,
    ) -> SkillSyncStatus:
        """Synchronize resources for a skill to the sandbox.

        This is the main entry point called from SkillLoaderTool and
        ReActAgent INJECT mode. It is idempotent: repeated calls for
        the same (sandbox_id, skill_name) are fast no-ops thanks to
        the version cache in SandboxSkillResourceAdapter.

        Args:
            skill_name: Name of the skill to sync resources for.
            sandbox_id: Target sandbox container ID. If None, sync is skipped
                (local environment doesn't need sync).
            skill_content: Optional SKILL.md content for reference detection.

        Returns:
            SkillSyncStatus with sync result and resource paths.
        """
        status = SkillSyncStatus()

        # No sandbox = local environment, no sync needed
        if not sandbox_id:
            return status

        # Skip if not a sandbox environment
        if self._resource_port.environment != ResourceEnvironment.SANDBOX:
            return status

        context = SkillResourceContext(
            skill_name=skill_name,
            skill_content=skill_content,
            tenant_id=self._tenant_id,
            project_id=self._project_id,
            sandbox_id=sandbox_id,
            project_path=self._project_path,
        )

        try:
            # Sync resources (idempotent via version cache)
            sync_result: ResourceSyncResult = await self._resource_port.sync_resources(context)

            if sync_result.success:
                status.synced = True
                status.resource_paths = [
                    r.container_path or self._build_container_path(skill_name, r)
                    for r in sync_result.synced_resources
                ]

                # Setup environment (SKILL_ROOT, PATH)
                await self._resource_port.setup_environment(context)

                # Mark as synced only after both resource sync and env setup succeed
                self._synced_skills.add((sandbox_id, skill_name))

                logger.debug(
                    f"Skill '{skill_name}' resources synced to sandbox {sandbox_id}: "
                    f"{len(status.resource_paths)} files"
                )
            else:
                status.errors = sync_result.errors
                logger.warning(
                    f"Skill '{skill_name}' resource sync failed: "
                    f"{'; '.join(sync_result.errors[:3])}"
                )

        except Exception as e:
            status.errors = [str(e)]
            logger.error(f"Skill resource sync error for '{skill_name}': {e}")

        return status

    def build_resource_paths_hint(
        self,
        skill_name: str,
        resource_paths: List[str],
    ) -> str:
        """Generate a path hint block to append to SKILL.md content.

        This gives the LLM explicit knowledge of where skill resources
        are located in the sandbox, so it can generate correct tool calls.

        Args:
            skill_name: Skill name.
            resource_paths: List of container paths for synced resources.

        Returns:
            Formatted hint string to append to skill content.
        """
        if not resource_paths:
            return ""

        skill_root = f"{CONTAINER_SKILL_BASE}/{skill_name}"
        lines = [
            "",
            "---",
            "**[Skill Resources]**",
            f"- SKILL_ROOT: `{skill_root}`",
            "- Environment variables `SKILL_ROOT` and `SKILL_NAME` are set.",
            "- `$SKILL_ROOT/scripts/` is added to `PATH`.",
            "- Available resource files:",
        ]
        for path in sorted(resource_paths):
            lines.append(f"  - `{path}`")
        lines.append("")
        lines.append(
            "Use absolute paths above or `$SKILL_ROOT/` prefix when referencing these files."
        )

        return "\n".join(lines)

    def is_synced(self, skill_name: str, sandbox_id: str) -> bool:
        """Check if a skill has been synced in this session."""
        return (sandbox_id, skill_name) in self._synced_skills

    def _build_container_path(self, skill_name: str, resource: SkillResource) -> str:
        """Build container path from resource virtual path."""
        if resource.container_path:
            return resource.container_path
        _, relative = self._resource_port.parse_virtual_path(resource.virtual_path)
        return f"{CONTAINER_SKILL_BASE}/{skill_name}/{relative}"
