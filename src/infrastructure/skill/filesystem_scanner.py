"""
File system skill scanner.

Scans directories for SKILL.md files following the Claude Skills
and OpenCode conventions.

Supported directory structures:
- src/builtin/skills/{skill-name}/SKILL.md (system-level, read-only)
- .memstack/skills/{skill-name}/SKILL.md (project-level)
- ~/.memstack/skills/{skill-name}/SKILL.md (global)
- Custom paths

Reference: vendor/opencode/packages/opencode/src/skill/skill.ts
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillFileInfo:
    """
    Information about a discovered SKILL.md file.

    Attributes:
        file_path: Absolute path to the SKILL.md file
        skill_dir: Directory containing the skill (parent of SKILL.md)
        skill_id: Derived skill identifier from directory name
        source_type: Source directory type (system, memstack, claude, custom)
        is_system: Whether this is a system (builtin) skill
    """

    file_path: Path
    skill_dir: Path
    skill_id: str
    source_type: str = "custom"
    is_system: bool = False

    @property
    def scripts_dir(self) -> Path:
        """Return the scripts directory path (may not exist)."""
        return self.skill_dir / "scripts"

    @property
    def resources_dir(self) -> Path:
        """Return the resources directory path (deprecated, use references/)."""
        return self.skill_dir / "resources"

    @property
    def references_dir(self) -> Path:
        """Return the references directory path (AgentSkills.io spec)."""
        return self.skill_dir / "references"

    @property
    def assets_dir(self) -> Path:
        """Return the assets directory path (AgentSkills.io spec)."""
        return self.skill_dir / "assets"

    def has_scripts(self) -> bool:
        """Check if the skill has a scripts directory."""
        return self.scripts_dir.exists() and self.scripts_dir.is_dir()

    def has_resources(self) -> bool:
        """Check if the skill has a resources directory (deprecated)."""
        return self.resources_dir.exists() and self.resources_dir.is_dir()

    def has_references(self) -> bool:
        """Check if the skill has a references directory (AgentSkills.io spec)."""
        return self.references_dir.exists() and self.references_dir.is_dir()

    def has_assets(self) -> bool:
        """Check if the skill has an assets directory (AgentSkills.io spec)."""
        return self.assets_dir.exists() and self.assets_dir.is_dir()


@dataclass
class ScanResult:
    """
    Result of scanning directories for skills.

    Attributes:
        skills: List of discovered skill files
        errors: List of paths that failed to scan
        scanned_dirs: Set of directories that were scanned
    """

    skills: list[SkillFileInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scanned_dirs: set[str] = field(default_factory=set)

    @property
    def count(self) -> int:
        """Return the number of skills found."""
        return len(self.skills)

    def get_skill_names(self) -> list[str]:
        """Return list of skill IDs."""
        return [s.skill_id for s in self.skills]


class FileSystemSkillScanner:
    """
    Scanner for SKILL.md files in the file system.

    Scans multiple directory patterns with priority order:
    1. System/builtin skills (lowest priority - can be overridden)
    2. Global directories (~/.memstack/skills/)
    3. Project directories (.memstack/skills/) (highest priority)

    Example:
        scanner = FileSystemSkillScanner()
        result = scanner.scan(Path("/project"))
        for skill in result.skills:
            print(f"Found skill: {skill.skill_id} at {skill.file_path}")

        # Include global skills
        result = scanner.scan(Path("/project"), include_global=True)

        # Scan only system skills
        result = scanner.scan_system_only()
    """

    # Default skill directory patterns relative to base path (project-level)
    DEFAULT_SKILL_DIRS = [
        ".memstack/skills",
    ]

    # Global skill directories (relative to user home)
    GLOBAL_SKILL_DIRS = [
        "~/.memstack/skills",
    ]

    # Name of the skill definition file
    SKILL_FILE_NAME = "SKILL.md"

    def __init__(
        self,
        skill_dirs: list[str] | None = None,
        follow_symlinks: bool = True,
        include_global: bool = True,
        include_system: bool = True,
        system_skills_path: Path | None = None,
    ) -> None:
        """
        Initialize the scanner.

        Args:
            skill_dirs: Additional directories to scan (relative to base path)
            follow_symlinks: Whether to follow symbolic links
            include_global: Whether to include global skill directories (default: True)
            include_system: Whether to include system/builtin skills (default: True)
            system_skills_path: Custom path to system skills directory
        """
        self.skill_dirs = list(self.DEFAULT_SKILL_DIRS)
        if skill_dirs:
            self.skill_dirs.extend(skill_dirs)
        self.follow_symlinks = follow_symlinks
        self.include_global = include_global
        self.include_system = include_system
        self._system_skills_path = system_skills_path

    @property
    def system_skills_path(self) -> Path:
        """Get the path to system skills directory."""
        if self._system_skills_path:
            return self._system_skills_path
        # Default: src/builtin/skills/ relative to package root
        from src.builtin import get_builtin_skills_path

        return get_builtin_skills_path()

    def scan(
        self,
        base_path: Path,
        include_global: bool | None = None,
        include_system: bool | None = None,
    ) -> ScanResult:
        """
        Scan for SKILL.md files starting from base path.

        Scans in order (later sources can override earlier ones):
        1. System/builtin skills (lowest priority)
        2. Global directories (~/.memstack/skills/)
        3. Project directories (.memstack/skills/) (highest priority)

        Args:
            base_path: Base directory to start scanning from
            include_global: Override instance setting for including global dirs
            include_system: Override instance setting for including system skills

        Returns:
            ScanResult with discovered skills and any errors
        """
        result = ScanResult()

        if not base_path.exists():
            result.errors.append(f"Base path does not exist: {base_path}")
            return result

        base_path = base_path.resolve()

        # Determine whether to include system skills
        should_include_system = (
            include_system if include_system is not None else self.include_system
        )

        # Scan system skills first (lowest priority)
        if should_include_system:
            system_result = self.scan_system_only()
            result.skills.extend(system_result.skills)
            result.errors.extend(system_result.errors)
            result.scanned_dirs.update(system_result.scanned_dirs)

        # Determine whether to include global directories
        should_include_global = (
            include_global if include_global is not None else self.include_global
        )

        # Scan global directories (can override system)
        if should_include_global:
            for global_dir_pattern in self.GLOBAL_SKILL_DIRS:
                # Expand ~ to user home directory
                expanded_path = Path(os.path.expanduser(global_dir_pattern))

                if not expanded_path.exists():
                    continue

                if not expanded_path.is_dir():
                    result.errors.append(f"Not a directory: {expanded_path}")
                    continue

                result.scanned_dirs.add(str(expanded_path))
                source_type = self._determine_source_type(global_dir_pattern) + "_global"

                try:
                    self._scan_directory(expanded_path, source_type, result, is_system=False)
                    logger.debug(f"Scanned global skill directory: {expanded_path}")
                except PermissionError as e:
                    result.errors.append(f"Permission denied: {expanded_path} - {e}")
                except OSError as e:
                    result.errors.append(f"Error scanning {expanded_path}: {e}")

        # Scan project directories (highest priority - can override global and system)
        for skill_dir_pattern in self.skill_dirs:
            skill_dir = base_path / skill_dir_pattern

            if not skill_dir.exists():
                continue

            if not skill_dir.is_dir():
                result.errors.append(f"Not a directory: {skill_dir}")
                continue

            result.scanned_dirs.add(str(skill_dir))
            source_type = self._determine_source_type(skill_dir_pattern)

            try:
                self._scan_directory(skill_dir, source_type, result, is_system=False)
            except PermissionError as e:
                result.errors.append(f"Permission denied: {skill_dir} - {e}")
            except OSError as e:
                result.errors.append(f"Error scanning {skill_dir}: {e}")

        return result

    def scan_system_only(self) -> ScanResult:
        """
        Scan only system/builtin skill directories.

        Useful for getting a list of system-level skills.

        Returns:
            ScanResult with skills from system directories
        """
        result = ScanResult()

        system_path = self.system_skills_path
        if not system_path.exists() or not system_path.is_dir():
            logger.debug(f"System skills directory does not exist: {system_path}")
            return result

        result.scanned_dirs.add(str(system_path))

        try:
            self._scan_directory(system_path, "system", result, is_system=True)
            logger.debug(f"Scanned system skills directory: {system_path}")
        except (PermissionError, OSError) as e:
            result.errors.append(f"Error scanning system skills {system_path}: {e}")

        return result

    def scan_directory(
        self, directory: Path, source_type: str = "custom", is_system: bool = False
    ) -> ScanResult:
        """
        Scan a specific directory for SKILL.md files.

        Args:
            directory: Directory to scan
            source_type: Type identifier for the source
            is_system: Whether this is a system skills directory

        Returns:
            ScanResult with discovered skills
        """
        result = ScanResult()

        if not directory.exists() or not directory.is_dir():
            result.errors.append(f"Invalid directory: {directory}")
            return result

        result.scanned_dirs.add(str(directory))
        self._scan_directory(directory, source_type, result, is_system=is_system)

        return result

    def _scan_directory(
        self,
        directory: Path,
        source_type: str,
        result: ScanResult,
        is_system: bool = False,
    ) -> None:
        """
        Internal method to scan a directory for skills.

        Looks for:
        - {directory}/{skill-name}/SKILL.md
        - {directory}/SKILL.md (directory itself is a skill)
        """
        # Check if directory itself contains SKILL.md
        direct_skill = directory / self.SKILL_FILE_NAME
        if direct_skill.exists() and direct_skill.is_file():
            skill_info = self._create_skill_info(direct_skill, source_type, is_system)
            if skill_info:
                result.skills.append(skill_info)

        # Scan subdirectories
        try:
            for item in directory.iterdir():
                if not item.is_dir():
                    continue

                # Skip hidden directories (except .memstack, .claude)
                if item.name.startswith(".") and item.name not in (".memstack", ".claude"):
                    continue

                skill_file = item / self.SKILL_FILE_NAME
                if skill_file.exists() and skill_file.is_file():
                    skill_info = self._create_skill_info(skill_file, source_type, is_system)
                    if skill_info:
                        result.skills.append(skill_info)
                else:
                    # Recursively scan subdirectories (for nested skill structures)
                    self._scan_directory(item, source_type, result, is_system)

        except PermissionError as e:
            result.errors.append(f"Permission denied accessing {directory}: {e}")

    def _create_skill_info(
        self,
        file_path: Path,
        source_type: str,
        is_system: bool = False,
    ) -> SkillFileInfo | None:
        """
        Create a SkillFileInfo from a file path.

        Args:
            file_path: Path to SKILL.md file
            source_type: Source type identifier
            is_system: Whether this is a system skill

        Returns:
            SkillFileInfo or None if invalid
        """
        try:
            skill_dir = file_path.parent
            skill_id = skill_dir.name

            # Resolve symlinks if configured
            if self.follow_symlinks:
                file_path = file_path.resolve()
                skill_dir = skill_dir.resolve()

            return SkillFileInfo(
                file_path=file_path,
                skill_dir=skill_dir,
                skill_id=skill_id,
                source_type=source_type,
                is_system=is_system,
            )
        except Exception as e:
            logger.warning(f"Failed to create skill info for {file_path}: {e}")
            return None

    def _determine_source_type(self, pattern: str) -> str:
        """Determine source type from directory pattern."""
        if ".memstack" in pattern:
            return "memstack"
        elif ".claude" in pattern:
            return "claude"
        return "custom"

    def find_skill(
        self,
        base_path: Path,
        skill_name: str,
        include_global: bool | None = None,
        include_system: bool | None = None,
    ) -> SkillFileInfo | None:
        """
        Find a specific skill by name.

        Searches in priority order:
        1. Project directories (highest priority)
        2. Global directories
        3. System directories (lowest priority)

        Args:
            base_path: Base directory to search from
            skill_name: Name of the skill to find
            include_global: Override instance setting for including global dirs
            include_system: Override instance setting for including system skills

        Returns:
            SkillFileInfo if found, None otherwise
        """
        result = self.scan(base_path, include_global=include_global, include_system=include_system)

        # Return the last match (highest priority due to scan order)
        found_skill = None
        for skill in result.skills:
            if skill.skill_id == skill_name:
                found_skill = skill

        return found_skill

    def scan_global_only(self) -> ScanResult:
        """
        Scan only global skill directories.

        Useful for getting a list of globally available skills.

        Returns:
            ScanResult with skills from global directories
        """
        result = ScanResult()

        for global_dir_pattern in self.GLOBAL_SKILL_DIRS:
            expanded_path = Path(os.path.expanduser(global_dir_pattern))

            if not expanded_path.exists() or not expanded_path.is_dir():
                continue

            result.scanned_dirs.add(str(expanded_path))
            source_type = self._determine_source_type(global_dir_pattern) + "_global"

            try:
                self._scan_directory(expanded_path, source_type, result, is_system=False)
            except (PermissionError, OSError) as e:
                result.errors.append(f"Error scanning {expanded_path}: {e}")

        return result
