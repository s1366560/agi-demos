"""
Local Skill Resource Adapter.

Implementation of SkillResourcePort for direct local file system access.
Used when the ReActAgent runs in SYSTEM environment without a Sandbox.
"""

import hashlib
import logging
from pathlib import Path

from src.domain.ports.services.skill_resource_port import (
    ResourceEnvironment,
    ResourceSyncResult,
    SkillResource,
    SkillResourceContext,
    SkillResourcePort,
)
from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner

logger = logging.getLogger(__name__)


class LocalSkillResourceAdapter(SkillResourcePort):
    """
    Local file system implementation of SkillResourcePort.

    Provides direct access to SKILL resources on the local file system.
    No synchronization needed as resources are already accessible.
    """

    # Resource directories to scan
    RESOURCE_DIRS = ["scripts", "references", "assets", "templates"]

    def __init__(
        self,
        default_project_path: Path | None = None,
        scanner: FileSystemSkillScanner | None = None,
    ) -> None:
        """
        Initialize the local adapter.

        Args:
            default_project_path: Default project root path
            scanner: Optional custom scanner
        """
        self._default_project_path = default_project_path or Path.cwd()
        self._scanner = scanner or FileSystemSkillScanner()
        # Cache: skill_name -> skill_dir
        self._skill_dir_cache: dict[str, Path] = {}
        # Cache: virtual_path -> local_path
        self._path_cache: dict[str, Path] = {}

    @property
    def environment(self) -> ResourceEnvironment:
        """Return SYSTEM environment type."""
        return ResourceEnvironment.SYSTEM

    async def load_skill_content(
        self,
        context: SkillResourceContext,
        tier: int = 3,
    ) -> str | None:
        """Load SKILL.md content from local file system."""
        skill_dir = await self._get_skill_dir(context)
        if not skill_dir:
            return None

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")

            # For lower tiers, extract only relevant sections
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
        """Get resource by virtual path from local file system."""
        skill_name, relative_path = self.parse_virtual_path(virtual_path)

        # Override context skill_name if different
        if skill_name != context.skill_name:
            context = SkillResourceContext(
                skill_name=skill_name,
                tenant_id=context.tenant_id,
                project_id=context.project_id,
                project_path=context.project_path,
            )

        skill_dir = await self._get_skill_dir(context)
        if not skill_dir:
            return None

        local_path = skill_dir / relative_path
        if not local_path.exists():
            return None

        try:
            # Check if binary
            is_binary = self._is_binary_file(local_path)

            content = None
            if not is_binary:
                content = local_path.read_text(encoding="utf-8")

            # Calculate hash
            content_hash = None
            if content:
                content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            resource = SkillResource(
                virtual_path=virtual_path,
                name=local_path.name,
                content=content,
                local_path=local_path,
                size_bytes=local_path.stat().st_size,
                content_hash=content_hash,
                is_binary=is_binary,
            )

            # Cache the path mapping
            self._path_cache[virtual_path] = local_path

            return resource

        except Exception as e:
            logger.error(f"Failed to load resource {virtual_path}: {e}")
            return None

    async def list_resources(
        self,
        context: SkillResourceContext,
    ) -> list[SkillResource]:
        """List all resources for a skill from local file system."""
        skill_dir = await self._get_skill_dir(context)
        if not skill_dir:
            return []

        resources = []

        for dir_name in self.RESOURCE_DIRS:
            resource_dir = skill_dir / dir_name
            if not resource_dir.exists() or not resource_dir.is_dir():
                continue

            try:
                for item in resource_dir.rglob("*"):
                    if not item.is_file():
                        continue

                    relative_path = item.relative_to(skill_dir)
                    virtual_path = self.build_virtual_path(context.skill_name, str(relative_path))

                    resource = SkillResource(
                        virtual_path=virtual_path,
                        name=item.name,
                        local_path=item,
                        size_bytes=item.stat().st_size,
                        is_binary=self._is_binary_file(item),
                    )
                    resources.append(resource)

                    # Cache the path
                    self._path_cache[virtual_path] = item

            except Exception as e:
                logger.warning(f"Error scanning {resource_dir}: {e}")

        return resources

    async def sync_resources(
        self,
        context: SkillResourceContext,
        resources: list[SkillResource] | None = None,
    ) -> ResourceSyncResult:
        """
        Sync resources - no-op for local environment.

        Resources are already accessible on the local file system.
        """
        # No synchronization needed for local environment
        if resources is None:
            resources = await self.list_resources(context)

        return ResourceSyncResult(
            success=True,
            synced_resources=resources,
        )

    async def setup_environment(
        self,
        context: SkillResourceContext,
    ) -> bool:
        """
        Setup local environment for skill execution.

        For local environment, this mainly involves setting up
        environment variables that can be used by the skill.
        """
        skill_dir = await self._get_skill_dir(context)
        return bool(skill_dir)

    async def get_execution_path(
        self,
        context: SkillResourceContext,
        virtual_path: str,
    ) -> str:
        """Get the local file system path for execution."""
        # Check cache first
        if virtual_path in self._path_cache:
            return str(self._path_cache[virtual_path])

        # Resolve and cache
        skill_name, relative_path = self.parse_virtual_path(virtual_path)

        if skill_name != context.skill_name:
            context = SkillResourceContext(
                skill_name=skill_name,
                tenant_id=context.tenant_id,
                project_id=context.project_id,
                project_path=context.project_path,
            )

        skill_dir = await self._get_skill_dir(context)
        if not skill_dir:
            raise ValueError(f"Skill not found: {skill_name}")

        local_path = skill_dir / relative_path
        self._path_cache[virtual_path] = local_path

        return str(local_path)

    # Private helper methods

    async def _get_skill_dir(self, context: SkillResourceContext) -> Path | None:
        """Get skill directory, using cache if available."""
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
                # Only keep name and description
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
