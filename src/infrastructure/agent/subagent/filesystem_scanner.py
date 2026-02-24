"""
File system SubAgent scanner.

Scans directories for SubAgent .md definition files following the
.memstack/agents/ convention (compatible with Claude Code custom agents).

Supported directory structures:
- .memstack/agents/{name}.md (project-level, highest priority)
- ~/.memstack/agents/{name}.md (global/tenant-level)
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SubAgentFileInfo:
    """
    Information about a discovered SubAgent .md file.

    Attributes:
        file_path: Absolute path to the .md file
        name: Agent name derived from filename stem
        source_type: Source directory type (project, global)
    """

    file_path: Path
    name: str
    source_type: str = "project"


@dataclass
class SubAgentScanResult:
    """
    Result of scanning directories for SubAgent definitions.

    Attributes:
        agents: List of discovered agent files
        errors: List of paths that failed to scan
        scanned_dirs: Set of directories that were scanned
    """

    agents: list[SubAgentFileInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scanned_dirs: set[str] = field(default_factory=set)

    @property
    def count(self) -> int:
        return len(self.agents)

    def get_agent_names(self) -> list[str]:
        return [a.name for a in self.agents]


class FileSystemSubAgentScanner:
    """
    Scanner for SubAgent .md files in the file system.

    Scans in priority order (later sources override earlier ones):
    1. Global directories (~/.memstack/agents/) - lower priority
    2. Project directories (.memstack/agents/) - highest priority

    Unlike Skills which use {name}/SKILL.md directory convention,
    SubAgents use flat {name}.md files in the agents/ directory.
    """

    DEFAULT_AGENT_DIRS = [
        ".memstack/agents",
    ]

    GLOBAL_AGENT_DIRS = [
        "~/.memstack/agents",
    ]

    AGENT_FILE_SUFFIX = ".md"

    def __init__(
        self,
        agent_dirs: list[str] | None = None,
        include_global: bool = True,
    ) -> None:
        """
        Initialize the scanner.

        Args:
            agent_dirs: Additional directories to scan (relative to base path)
            include_global: Whether to include global agent directories
        """
        self.agent_dirs = list(self.DEFAULT_AGENT_DIRS)
        if agent_dirs:
            self.agent_dirs.extend(agent_dirs)
        self.include_global = include_global

    def scan(
        self,
        base_path: Path,
        include_global: bool | None = None,
    ) -> SubAgentScanResult:
        """
        Scan for SubAgent .md files starting from base path.

        Scans in order (later sources can override earlier ones):
        1. Global directories (~/.memstack/agents/)
        2. Project directories (.memstack/agents/) (highest priority)

        Args:
            base_path: Base directory to start scanning from
            include_global: Override instance setting for including global dirs

        Returns:
            SubAgentScanResult with discovered agents and any errors
        """
        result = SubAgentScanResult()

        if not base_path.exists():
            result.errors.append(f"Base path does not exist: {base_path}")
            return result

        base_path = base_path.resolve()

        should_include_global = (
            include_global if include_global is not None else self.include_global
        )

        # Scan global directories first (lower priority)
        if should_include_global:
            for global_dir_pattern in self.GLOBAL_AGENT_DIRS:
                expanded_path = Path(os.path.expanduser(global_dir_pattern))

                if not expanded_path.exists() or not expanded_path.is_dir():
                    continue

                result.scanned_dirs.add(str(expanded_path))
                try:
                    self._scan_directory(expanded_path, "global", result)
                except (PermissionError, OSError) as e:
                    result.errors.append(f"Error scanning {expanded_path}: {e}")

        # Scan project directories (highest priority)
        for agent_dir_pattern in self.agent_dirs:
            agent_dir = base_path / agent_dir_pattern

            if not agent_dir.exists() or not agent_dir.is_dir():
                continue

            result.scanned_dirs.add(str(agent_dir))
            try:
                self._scan_directory(agent_dir, "project", result)
            except (PermissionError, OSError) as e:
                result.errors.append(f"Error scanning {agent_dir}: {e}")

        return result

    def _scan_directory(
        self,
        directory: Path,
        source_type: str,
        result: SubAgentScanResult,
    ) -> None:
        """
        Scan a directory for SubAgent .md files.

        Looks for flat *.md files (not SKILL.md subdirectory convention).
        """
        try:
            for item in directory.iterdir():
                if not item.is_file():
                    continue
                if not item.name.endswith(self.AGENT_FILE_SUFFIX):
                    continue
                # Skip hidden files and non-agent files
                if item.name.startswith("."):
                    continue

                agent_name = item.stem  # filename without .md
                file_info = SubAgentFileInfo(
                    file_path=item.resolve(),
                    name=agent_name,
                    source_type=source_type,
                )
                result.agents.append(file_info)

        except PermissionError as e:
            result.errors.append(f"Permission denied accessing {directory}: {e}")
