"""
Sandbox Skill Resource Adapter.

Implementation of SkillResourcePort for remote Sandbox container access.
Injects SKILL resources into containers via MCP WebSocket tools.
"""

import hashlib
import logging
from pathlib import Path
from typing import ClassVar

from src.domain.ports.services.sandbox_port import SandboxPort
from src.domain.ports.services.skill_resource_port import (
    ResourceEnvironment,
    ResourceSyncResult,
    SkillResource,
    SkillResourceContext,
    SkillResourcePort,
)
from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner

logger = logging.getLogger(__name__)


class SandboxSkillResourceAdapter(SkillResourcePort):
    """
    Sandbox container implementation of SkillResourcePort.

    Injects SKILL resources into remote containers via MCP tools.
    Resources are synchronized from local file system to container.
    """

    # Directories and files to exclude from sync
    EXCLUDED_NAMES: ClassVar[set[str]] = {"__pycache__", ".git", ".DS_Store", "node_modules"}

    # Container base path for skills
    CONTAINER_SKILL_BASE = "/workspace/.memstack/skills"

    def __init__(
        self,
        sandbox_adapter: SandboxPort,
        default_project_path: Path | None = None,
        scanner: FileSystemSkillScanner | None = None,
    ) -> None:
        """
        Initialize the sandbox adapter.

        Args:
            sandbox_adapter: Sandbox port for container operations
            default_project_path: Default project root path for local resource lookup
            scanner: Optional custom scanner
        """
        self._sandbox_adapter = sandbox_adapter
        self._default_project_path = default_project_path or Path.cwd()
        self._scanner = scanner or FileSystemSkillScanner()

        # Cache: skill_name -> skill_dir (local)
        self._skill_dir_cache: dict[str, Path] = {}

        # Cache: (sandbox_id, skill_name) -> {virtual_path: container_path}
        self._injection_cache: dict[tuple[str, str], dict[str, str]] = {}

        # Cache: (sandbox_id, skill_name) -> content_hash for version tracking
        self._version_cache: dict[tuple[str, str], str] = {}

    @property
    def environment(self) -> ResourceEnvironment:
        """Return SANDBOX environment type."""
        return ResourceEnvironment.SANDBOX

    async def load_skill_content(
        self,
        context: SkillResourceContext,
        tier: int = 3,
    ) -> str | None:
        """
        Load SKILL.md content.

        For sandbox, we still load from local file system since SKILL.md
        is needed for agent planning before execution.
        """
        skill_dir = await self._get_local_skill_dir(context)
        if not skill_dir:
            return None

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")

            if tier == 1:
                return self._extract_tier1(content)
            elif tier == 2:
                return self._extract_tier2(content)
            else:
                return content

        except Exception as e:
            logger.error(f"Failed to load SKILL.md for {context.skill_name}: {e}")
            return None

    async def resolve_resource_path(
        self,
        context: SkillResourceContext,
        relative_path: str,
    ) -> str:
        """Resolve relative path to virtual path."""
        return self.build_virtual_path(context.skill_name, relative_path)

    async def get_resource(
        self,
        context: SkillResourceContext,
        virtual_path: str,
    ) -> SkillResource | None:
        """
        Get resource by virtual path.

        First checks if injected to sandbox, otherwise loads from local.
        """
        skill_name, relative_path = self.parse_virtual_path(virtual_path)

        if skill_name != context.skill_name:
            context = SkillResourceContext(
                skill_name=skill_name,
                tenant_id=context.tenant_id,
                project_id=context.project_id,
                sandbox_id=context.sandbox_id,
                project_path=context.project_path,
            )

        skill_dir = await self._get_local_skill_dir(context)
        if not skill_dir:
            return None

        local_path = skill_dir / relative_path
        if not local_path.exists():
            return None

        try:
            is_binary = self._is_binary_file(local_path)

            content = None
            if not is_binary:
                content = local_path.read_text(encoding="utf-8")

            content_hash = None
            if content:
                content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            # Determine container path
            container_path = self._get_container_path(skill_name, relative_path)

            resource = SkillResource(
                virtual_path=virtual_path,
                name=local_path.name,
                content=content,
                local_path=local_path,
                container_path=container_path,
                size_bytes=local_path.stat().st_size,
                content_hash=content_hash,
                is_binary=is_binary,
            )

            return resource

        except Exception as e:
            logger.error(f"Failed to load resource {virtual_path}: {e}")
            return None

    async def list_resources(
        self,
        context: SkillResourceContext,
    ) -> list[SkillResource]:
        """List all resources for a skill from local file system.

        Scans the entire skill directory recursively, excluding SKILL.md
        (handled separately) and ignored directories like __pycache__.
        """
        skill_dir = await self._get_local_skill_dir(context)
        if not skill_dir:
            return []

        resources = []

        try:
            for item in skill_dir.rglob("*"):
                if not item.is_file():
                    continue

                # Skip SKILL.md (loaded separately via load_skill_content)
                if item.name == "SKILL.md" and item.parent == skill_dir:
                    continue

                # Skip excluded directories
                if any(part in self.EXCLUDED_NAMES for part in item.relative_to(skill_dir).parts):
                    continue

                relative_path = item.relative_to(skill_dir)
                virtual_path = self.build_virtual_path(context.skill_name, str(relative_path))
                container_path = self._get_container_path(context.skill_name, str(relative_path))

                resource = SkillResource(
                    virtual_path=virtual_path,
                    name=item.name,
                    local_path=item,
                    container_path=container_path,
                    size_bytes=item.stat().st_size,
                    is_binary=self._is_binary_file(item),
                )
                resources.append(resource)

        except Exception as e:
            logger.warning(f"Error scanning skill directory {skill_dir}: {e}")

        return resources

    async def sync_resources(
        self,
        context: SkillResourceContext,
        resources: list[SkillResource] | None = None,
    ) -> ResourceSyncResult:
        """
        Synchronize resources to sandbox container via MCP.

        Injects all skill resources into the container at
        /workspace/.skills/{skill_name}/
        """
        if not context.sandbox_id:
            return ResourceSyncResult(
                success=False,
                errors=["sandbox_id is required for sandbox sync"],
            )

        if resources is None:
            resources = await self.list_resources(context)

        synced = []
        failed = []
        errors = []
        cache_key = (context.sandbox_id, context.skill_name)

        # Check version to avoid redundant sync
        current_hash = self._compute_resources_hash(resources)
        if cache_key in self._version_cache:
            if self._version_cache[cache_key] == current_hash:
                logger.debug(f"Skill {context.skill_name} already synced to {context.sandbox_id}")
                return ResourceSyncResult(
                    success=True,
                    synced_resources=resources,
                )

        # Initialize path cache for this sandbox/skill
        if cache_key not in self._injection_cache:
            self._injection_cache[cache_key] = {}

        for resource in resources:
            await self._sync_single_resource(resource, context, cache_key, synced, failed, errors)

        # Update version cache on success
        if not failed:
            self._version_cache[cache_key] = current_hash

        return ResourceSyncResult(
            success=len(failed) == 0,
            synced_resources=synced,
            failed_resources=failed,
            errors=errors,
        )

    async def _sync_single_resource(
        self,
        resource: SkillResource,
        context: SkillResourceContext,
        cache_key: tuple[str, str],
        synced: list[SkillResource],
        failed: list[str],
        errors: list[str],
    ) -> None:
        """Sync a single resource to the sandbox container."""
        if resource.is_binary:
            logger.debug(f"Skipping binary resource: {resource.virtual_path}")
            return

        try:
            # Load content if not already loaded
            if resource.content is None and resource.local_path:
                resource.content = resource.local_path.read_text(encoding="utf-8")

            if resource.content is None:
                failed.append(resource.virtual_path)
                errors.append(f"No content for {resource.virtual_path}")
                return

            # Container path (relative for MCP write tool)
            relative_path = self._resolve_relative_path(resource, context)

            # Write to container via MCP
            result = await self._sandbox_adapter.call_tool(
                sandbox_id=context.sandbox_id,
                tool_name="write",
                arguments={
                    "file_path": relative_path,
                    "content": resource.content,
                },
            )

            if not result.get("isError"):
                synced.append(resource)
                self._injection_cache[cache_key][resource.virtual_path] = (
                    resource.container_path or ""
                )
                logger.debug(f"Injected: {resource.virtual_path} -> {relative_path}")
            else:
                failed.append(resource.virtual_path)
                errors.append(f"MCP write failed for {resource.virtual_path}: {result}")

        except Exception as e:
            failed.append(resource.virtual_path)
            errors.append(f"Failed to inject {resource.virtual_path}: {e}")
            logger.error(f"Resource injection error: {e}")

    @staticmethod
    def _resolve_relative_path(resource: SkillResource, context: SkillResourceContext) -> str:
        """Resolve the relative path for writing a resource to the container."""
        container_path = resource.container_path
        if container_path and container_path.startswith("/workspace/"):
            return container_path[11:]  # Remove "/workspace/"
        return f".memstack/skills/{context.skill_name}/{resource.name}"

    async def setup_environment(
        self,
        context: SkillResourceContext,
    ) -> bool:
        """
        Setup sandbox environment for skill execution.

        Creates environment setup script and injects it.
        """
        if not context.sandbox_id:
            logger.warning("sandbox_id required for environment setup")
            return False

        skill_name = context.skill_name

        # Create environment setup script
        setup_script = f"""#!/bin/bash
# SKILL environment setup for {skill_name}
export SKILL_ROOT="{self.CONTAINER_SKILL_BASE}/{skill_name}"
export SKILL_NAME="{skill_name}"
export PATH="$SKILL_ROOT/scripts:$PATH"

# Additional environment variables from context
"""
        for key, value in context.environment_vars.items():
            setup_script += f'export {key}="{value}"\n'

        try:
            result = await self._sandbox_adapter.call_tool(
                sandbox_id=context.sandbox_id,
                tool_name="write",
                arguments={
                    "file_path": f".memstack/skills/{skill_name}/env.sh",
                    "content": setup_script,
                },
            )

            if result.get("isError"):
                logger.error(f"Failed to setup environment: {result}")
                return False

            return True

        except Exception as e:
            logger.error(f"Environment setup error: {e}")
            return False

    async def get_execution_path(
        self,
        context: SkillResourceContext,
        virtual_path: str,
    ) -> str:
        """Get the container path for execution."""
        skill_name, relative_path = self.parse_virtual_path(virtual_path)

        # Check injection cache first
        if context.sandbox_id:
            cache_key = (context.sandbox_id, skill_name)
            if cache_key in self._injection_cache:
                if virtual_path in self._injection_cache[cache_key]:
                    return self._injection_cache[cache_key][virtual_path]

        # Return standard container path
        return self._get_container_path(skill_name, relative_path)

    # Public methods for cache management

    def clear_cache(
        self,
        sandbox_id: str | None = None,
        skill_name: str | None = None,
    ) -> None:
        """
        Clear injection caches.

        Args:
            sandbox_id: Clear cache for specific sandbox, or all if None
            skill_name: Clear cache for specific skill, or all if None
        """
        if sandbox_id is None:
            self._injection_cache.clear()
            self._version_cache.clear()
            return

        keys_to_remove = []
        for key in self._injection_cache:
            sid, sname = key
            if sid == sandbox_id and (skill_name is None or sname == skill_name):
                keys_to_remove.append(key)

        for key in keys_to_remove:
            self._injection_cache.pop(key, None)
            self._version_cache.pop(key, None)

    def get_injected_resources(
        self,
        sandbox_id: str,
        skill_name: str,
    ) -> dict[str, str]:
        """
        Get map of injected resources for a skill in a sandbox.

        Returns:
            Dict of virtual_path -> container_path
        """
        cache_key = (sandbox_id, skill_name)
        return self._injection_cache.get(cache_key, {})

    # Private helper methods

    async def _get_local_skill_dir(self, context: SkillResourceContext) -> Path | None:
        """Get local skill directory."""
        cache_key = f"{context.skill_name}:{context.project_path or self._default_project_path}"

        if cache_key in self._skill_dir_cache:
            return self._skill_dir_cache[cache_key]

        project_path = context.project_path or self._default_project_path

        file_info = self._scanner.find_skill(
            project_path,
            context.skill_name,
            include_global=True,
            include_system=True,
        )

        if file_info:
            self._skill_dir_cache[cache_key] = file_info.skill_dir
            return file_info.skill_dir

        return None

    def _get_container_path(self, skill_name: str, relative_path: str) -> str:
        """Get container path for a resource."""
        normalized = relative_path.replace("\\", "/").lstrip("/")
        return f"{self.CONTAINER_SKILL_BASE}/{skill_name}/{normalized}"

    def _compute_resources_hash(self, resources: list[SkillResource]) -> str:
        """Compute hash for resource list for version tracking."""
        content_parts = []
        for r in sorted(resources, key=lambda x: x.virtual_path):
            if r.content_hash:
                content_parts.append(f"{r.virtual_path}:{r.content_hash}")
            elif r.local_path:
                content_parts.append(f"{r.virtual_path}:{r.local_path.stat().st_mtime}")

        combined = "|".join(content_parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _extract_tier1(self, content: str) -> str:
        """Extract Tier 1 content (metadata only)."""
        lines = content.split("\n")
        result_lines = []

        in_frontmatter = False
        for line in lines:
            if line.strip() == "---":
                in_frontmatter = not in_frontmatter
                result_lines.append(line)
                if not in_frontmatter:
                    break
                continue

            if in_frontmatter:
                if line.startswith("name:") or line.startswith("description:"):
                    result_lines.append(line)

        return "\n".join(result_lines)

    def _extract_tier2(self, content: str) -> str:
        """Extract Tier 2 content (details)."""
        lines = content.split("\n")
        result_lines = []

        in_frontmatter = False
        for line in lines:
            if line.strip() == "---":
                in_frontmatter = not in_frontmatter
                result_lines.append(line)
                continue

            if in_frontmatter:
                result_lines.append(line)

        return "\n".join(result_lines)

    def _is_binary_file(self, path: Path) -> bool:
        """Check if a file is binary."""
        binary_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".ico",
            ".webp",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".bz2",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".pyc",
            ".pyo",
            ".class",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
        }
        return path.suffix.lower() in binary_extensions
