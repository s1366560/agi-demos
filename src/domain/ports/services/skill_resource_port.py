"""
Skill Resource Port - Abstract interface for SKILL resource operations.

This port provides a unified interface for loading and managing SKILL resources,
abstracting away the differences between local file system access and
remote Sandbox container injection.

The ReActAgent and SkillExecutor use this port to access SKILL resources
without knowing whether they're running in a System or Sandbox environment.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class ResourceEnvironment(str, Enum):
    """Environment type for skill resource access."""

    SYSTEM = "system"  # Direct local file system access
    SANDBOX = "sandbox"  # Remote container via MCP


@dataclass
class SkillResource:
    """Represents a SKILL resource file."""

    # Unified virtual path (e.g., skill://code-review/scripts/lint.py)
    virtual_path: str

    # Resource name (filename)
    name: str

    # Content of the resource (loaded on demand)
    content: Optional[str] = None

    # Original local path (for SYSTEM environment)
    local_path: Optional[Path] = None

    # Container path (for SANDBOX environment)
    container_path: Optional[str] = None

    # Resource metadata
    size_bytes: int = 0
    content_hash: Optional[str] = None
    is_binary: bool = False

    def __post_init__(self):
        """Validate resource data."""
        if not self.virtual_path:
            raise ValueError("virtual_path is required")
        if not self.name:
            raise ValueError("name is required")


@dataclass
class SkillResourceContext:
    """Context for skill resource operations."""

    skill_name: str
    skill_content: Optional[str] = None  # SKILL.md content for reference detection
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    sandbox_id: Optional[str] = None  # If present, use sandbox environment
    project_path: Optional[Path] = None  # Project root for local resolution
    environment_vars: Dict[str, str] = field(default_factory=dict)


@dataclass
class ResourceSyncResult:
    """Result of resource synchronization."""

    success: bool
    synced_resources: List[SkillResource] = field(default_factory=list)
    failed_resources: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class SkillResourcePort(ABC):
    """
    Abstract interface for SKILL resource operations.

    This port abstracts the differences between:
    - Local file system access (System environment)
    - Remote container injection (Sandbox environment)

    The ReActAgent uses this port to:
    1. Load skill content and metadata
    2. Resolve resource paths uniformly
    3. Sync resources to execution environment
    4. Setup skill execution environment
    """

    @property
    @abstractmethod
    def environment(self) -> ResourceEnvironment:
        """Return the resource environment type."""
        ...

    @abstractmethod
    async def load_skill_content(
        self,
        context: SkillResourceContext,
        tier: int = 3,
    ) -> Optional[str]:
        """
        Load SKILL.md content at specified tier.

        Tiers:
        - Tier 1: Metadata only (name, description)
        - Tier 2: Details (triggers, tools list)
        - Tier 3: Full content (complete markdown instructions)

        Args:
            context: Resource context with skill name and optional project path
            tier: Loading tier (1, 2, or 3)

        Returns:
            SKILL content at the specified tier, or None if not found
        """
        ...

    @abstractmethod
    async def resolve_resource_path(
        self,
        context: SkillResourceContext,
        relative_path: str,
    ) -> str:
        """
        Resolve a relative resource path to a unified virtual path.

        The virtual path uses the protocol: skill://{skill_name}/{relative_path}

        This allows tools and the agent to reference resources uniformly,
        regardless of the underlying environment.

        Args:
            context: Resource context
            relative_path: Path relative to skill directory (e.g., "scripts/lint.py")

        Returns:
            Unified virtual path (e.g., "skill://code-review/scripts/lint.py")
        """
        ...

    @abstractmethod
    async def get_resource(
        self,
        context: SkillResourceContext,
        virtual_path: str,
    ) -> Optional[SkillResource]:
        """
        Get a resource by its virtual path.

        Args:
            context: Resource context
            virtual_path: Unified virtual path

        Returns:
            SkillResource with content loaded, or None if not found
        """
        ...

    @abstractmethod
    async def list_resources(
        self,
        context: SkillResourceContext,
    ) -> List[SkillResource]:
        """
        List all resources for a skill.

        Args:
            context: Resource context with skill name

        Returns:
            List of SkillResource objects (content not loaded)
        """
        ...

    @abstractmethod
    async def sync_resources(
        self,
        context: SkillResourceContext,
        resources: Optional[List[SkillResource]] = None,
    ) -> ResourceSyncResult:
        """
        Synchronize resources to the execution environment.

        For SYSTEM environment: No-op (resources already accessible)
        For SANDBOX environment: Inject resources into container

        Args:
            context: Resource context (must include sandbox_id for SANDBOX)
            resources: Specific resources to sync, or None for all

        Returns:
            ResourceSyncResult with sync status
        """
        ...

    @abstractmethod
    async def setup_environment(
        self,
        context: SkillResourceContext,
    ) -> bool:
        """
        Setup skill execution environment.

        This includes:
        - Setting environment variables (SKILL_ROOT, PATH additions)
        - Creating necessary directories
        - Installing dependencies if needed

        Args:
            context: Resource context

        Returns:
            True if setup succeeded
        """
        ...

    @abstractmethod
    async def get_execution_path(
        self,
        context: SkillResourceContext,
        virtual_path: str,
    ) -> str:
        """
        Get the actual execution path for a virtual resource path.

        For SYSTEM: Returns the local file system path
        For SANDBOX: Returns the container path

        Args:
            context: Resource context
            virtual_path: Unified virtual path

        Returns:
            Actual path usable in the current environment
        """
        ...

    # Utility methods with default implementations

    def build_virtual_path(self, skill_name: str, relative_path: str) -> str:
        """
        Build a virtual path from skill name and relative path.

        Args:
            skill_name: Name of the skill
            relative_path: Path relative to skill directory

        Returns:
            Virtual path in format: skill://{skill_name}/{relative_path}
        """
        # Normalize path separators
        normalized_path = relative_path.replace("\\", "/").lstrip("/")
        return f"skill://{skill_name}/{normalized_path}"

    def parse_virtual_path(self, virtual_path: str) -> tuple[str, str]:
        """
        Parse a virtual path into skill name and relative path.

        Args:
            virtual_path: Virtual path to parse

        Returns:
            Tuple of (skill_name, relative_path)

        Raises:
            ValueError: If path is not a valid virtual path
        """
        if not virtual_path.startswith("skill://"):
            raise ValueError(f"Invalid virtual path: {virtual_path}")

        path_part = virtual_path[8:]  # Remove "skill://"
        parts = path_part.split("/", 1)

        if len(parts) < 2:
            return parts[0], ""

        return parts[0], parts[1]
