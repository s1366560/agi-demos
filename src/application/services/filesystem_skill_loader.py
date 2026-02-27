"""
File system skill loader.

Loads skills from the file system by scanning directories and parsing
SKILL.md files. Combines scanning and parsing functionality.
"""

import contextlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus, TriggerPattern, TriggerType
from src.domain.model.agent.skill_source import SkillSource
from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner, SkillFileInfo
from src.infrastructure.skill.markdown_parser import (
    MarkdownParseError,
    MarkdownParser,
    SkillMarkdown,
)
from src.infrastructure.skill.validator import (
    AgentSkillsValidator,
    AllowedTool,
    SkillValidationError,
)

logger = logging.getLogger(__name__)


@dataclass
class LoadedSkill:
    """
    A skill loaded from the file system.

    Attributes:
        skill: The Skill domain entity
        file_info: Information about the source file
        markdown: Parsed markdown content
    """

    skill: Skill
    file_info: SkillFileInfo
    markdown: SkillMarkdown


@dataclass
class LoadResult:
    """
    Result of loading skills from file system.

    Attributes:
        skills: Successfully loaded skills
        errors: Errors encountered during loading
    """

    skills: list[LoadedSkill]
    errors: list[str]

    @property
    def count(self) -> int:
        """Return number of successfully loaded skills."""
        return len(self.skills)

    def get_skill_by_name(self, name: str) -> LoadedSkill | None:
        """Find a skill by name."""
        for loaded in self.skills:
            if loaded.skill.name == name:
                return loaded
        return None


class FileSystemSkillLoader:
    """
    Loads skills from the file system.

    Combines directory scanning and SKILL.md parsing to create
    Skill domain entities from file system sources.

    Example:
        loader = FileSystemSkillLoader(
            base_path=Path("/project"),
            tenant_id="tenant-1",
        )
        result = await loader.load_all()
        for loaded_skill in result.skills:
            print(f"Loaded: {loaded_skill.skill.name}")
    """

    def __init__(
        self,
        base_path: Path,
        tenant_id: str,
        project_id: str | None = None,
        scanner: FileSystemSkillScanner | None = None,
        parser: MarkdownParser | None = None,
        include_system: bool = True,
        strict_mode: bool = False,
    ) -> None:
        """
        Initialize the loader.

        Args:
            base_path: Base directory to scan for skills
            tenant_id: Tenant ID for loaded skills
            project_id: Optional project ID for project-scoped skills
            scanner: Custom scanner instance (optional)
            parser: Custom parser instance (optional)
            include_system: Whether to include system/builtin skills (default: True)
            strict_mode: If True, reject skills that don't comply with AgentSkills.io spec
        """
        self.base_path = Path(base_path).resolve()
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.scanner = scanner or FileSystemSkillScanner(include_system=include_system)
        self.parser = parser or MarkdownParser()
        self.include_system = include_system
        self.strict_mode = strict_mode
        self.validator = AgentSkillsValidator(strict=strict_mode)

        # Cache for loaded skills (by scope)
        self._cache: dict[str, LoadedSkill] = {}
        self._system_cache: dict[str, LoadedSkill] = {}  # Separate cache for system skills
        self._cache_valid = False
        self._system_cache_valid = False
        self._loaded_tenant_id: str | None = None  # Track which tenant_id was used for caching

    def set_tenant_id(self, tenant_id: str) -> None:
        """
        Set the tenant ID for skill loading.

        If tenant_id differs from cached tenant, invalidates cache.

        Args:
            tenant_id: Tenant ID to use for loading skills
        """
        if tenant_id != self._loaded_tenant_id:
            self.tenant_id = tenant_id
            self._cache_valid = False  # Invalidate cache when tenant changes

    async def load_all(
        self, force_reload: bool = False, include_system: bool | None = None
    ) -> LoadResult:
        """
        Load all skills from the file system.

        Args:
            force_reload: Force reload even if cached
            include_system: Override instance setting for including system skills

        Returns:
            LoadResult with loaded skills and any errors
        """
        if self._cache_valid and not force_reload:
            return LoadResult(
                skills=list(self._cache.values()),
                errors=[],
            )

        result = LoadResult(skills=[], errors=[])

        # Determine whether to include system skills
        should_include_system = (
            include_system if include_system is not None else self.include_system
        )

        # Scan for SKILL.md files
        scan_result = self.scanner.scan(self.base_path, include_system=should_include_system)
        result.errors.extend(scan_result.errors)

        # Parse each file and create Skill entities.
        # Use a dict keyed by name so later sources (project) override earlier
        # ones (system/global), preventing duplicates in the result list.
        loaded_by_name: dict[str, LoadedSkill] = {}
        for file_info in scan_result.skills:
            try:
                loaded = self._load_skill_file(file_info)
                if loaded:
                    loaded_by_name[loaded.skill.name] = loaded
                    # Cache in appropriate cache based on scope
                    if file_info.is_system:
                        self._system_cache[loaded.skill.name] = loaded
                    else:
                        self._cache[loaded.skill.name] = loaded
            except MarkdownParseError as e:
                error_msg = f"Failed to parse {file_info.file_path}: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
            except Exception as e:
                error_msg = f"Unexpected error loading {file_info.file_path}: {e}"
                logger.error(error_msg, exc_info=True)
                result.errors.append(error_msg)
        result.skills = list(loaded_by_name.values())

        self._cache_valid = True
        self._system_cache_valid = True
        self._loaded_tenant_id = self.tenant_id  # Track which tenant_id was used
        logger.info(
            f"Loaded {result.count} skills from {self.base_path}",
            extra={"errors": len(result.errors)},
        )

        return result

    async def load_system_skills(self, force_reload: bool = False) -> LoadResult:
        """
        Load only system/builtin skills.

        Args:
            force_reload: Force reload even if cached

        Returns:
            LoadResult with system skills only
        """
        if self._system_cache_valid and not force_reload:
            return LoadResult(
                skills=list(self._system_cache.values()),
                errors=[],
            )

        result = LoadResult(skills=[], errors=[])

        # Scan only system skills directory
        scan_result = self.scanner.scan_system_only()
        result.errors.extend(scan_result.errors)

        # Parse each file and create Skill entities
        for file_info in scan_result.skills:
            try:
                loaded = self._load_skill_file(file_info)
                if loaded:
                    result.skills.append(loaded)
                    self._system_cache[loaded.skill.name] = loaded
            except MarkdownParseError as e:
                error_msg = f"Failed to parse {file_info.file_path}: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
            except Exception as e:
                error_msg = f"Unexpected error loading {file_info.file_path}: {e}"
                logger.error(error_msg, exc_info=True)
                result.errors.append(error_msg)

        self._system_cache_valid = True
        logger.info(
            f"Loaded {result.count} system skills",
            extra={"errors": len(result.errors)},
        )

        return result

    async def load_by_scope(self, scope: SkillScope, force_reload: bool = False) -> LoadResult:
        """
        Load skills filtered by scope.

        Args:
            scope: Skill scope to filter by (SYSTEM, TENANT, PROJECT)
            force_reload: Force reload even if cached

        Returns:
            LoadResult with skills of the specified scope
        """
        if scope == SkillScope.SYSTEM:
            return await self.load_system_skills(force_reload=force_reload)

        # For tenant/project scope, load all and filter
        all_result = await self.load_all(force_reload=force_reload, include_system=False)

        filtered_skills = [loaded for loaded in all_result.skills if loaded.skill.scope == scope]

        return LoadResult(skills=filtered_skills, errors=all_result.errors)

    def _load_skill_file(self, file_info: SkillFileInfo) -> LoadedSkill | None:
        """
        Load a single skill from a file.

        Args:
            file_info: Information about the skill file

        Returns:
            LoadedSkill or None if loading failed

        Raises:
            SkillValidationError: If strict_mode is True and skill fails validation
        """
        # Strict mode: validate before loading
        if self.strict_mode:
            result = self.validator.validate_file(file_info.skill_dir)
            if not result.is_valid:
                logger.error(f"Skill {file_info.skill_id} failed validation: {result.format()}")
                raise SkillValidationError(file_info.skill_id, result.errors)

        # Parse the markdown file
        markdown = self.parser.parse_file(str(file_info.file_path))

        # Convert to Skill entity
        skill = self._create_skill_from_markdown(markdown, file_info)

        return LoadedSkill(
            skill=skill,
            file_info=file_info,
            markdown=markdown,
        )

    def _create_skill_from_markdown(
        self,
        markdown: SkillMarkdown,
        file_info: SkillFileInfo,
    ) -> Skill:
        """
        Create a Skill entity from parsed markdown.

        Args:
            markdown: Parsed SKILL.md content
            file_info: File information

        Returns:
            Skill domain entity
        """
        # Create trigger patterns from frontmatter
        trigger_patterns = []
        for pattern_str in markdown.trigger_patterns:
            trigger_patterns.append(
                TriggerPattern(
                    pattern=pattern_str,
                    weight=1.0,
                    examples=[],
                )
            )

        # Determine trigger type
        trigger_type = TriggerType.HYBRID
        if markdown.frontmatter.get("trigger_type"):
            with contextlib.suppress(ValueError):
                trigger_type = TriggerType(markdown.frontmatter["trigger_type"])

        # Use tools from frontmatter, or allowed-tools as fallback
        tools = markdown.tools or markdown.allowed_tools or ["*"]

        # Parse allowed-tools with arguments for fine-grained permission control
        allowed_tools_parsed = []
        if markdown.allowed_tools_raw:
            allowed_tools_parsed = AllowedTool.parse_many(markdown.allowed_tools_raw)

        # Determine scope based on file source
        if file_info.is_system:
            scope = SkillScope.SYSTEM
            is_system_skill = True
        elif self.project_id:
            scope = SkillScope.PROJECT
            is_system_skill = False
        else:
            scope = SkillScope.TENANT
            is_system_skill = False

        return Skill(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            name=markdown.name,
            description=markdown.description,
            trigger_type=trigger_type,
            trigger_patterns=trigger_patterns,
            tools=tools,
            prompt_template=markdown.content,
            status=SkillStatus.ACTIVE,
            success_count=0,
            failure_count=0,
            metadata={
                "source_type": file_info.source_type,
                "context": markdown.context,
                "user_invocable": markdown.user_invocable,
                **(markdown.metadata or {}),  # Include AgentSkills.io metadata
            },
            source=SkillSource.FILESYSTEM,
            file_path=str(file_info.file_path),
            full_content=markdown.content,
            agent_modes=markdown.agent,  # Now a List[str] from MarkdownParser
            scope=scope,
            is_system_skill=is_system_skill,
            # AgentSkills.io spec fields
            license=markdown.license,
            compatibility=markdown.compatibility,
            allowed_tools_raw=markdown.allowed_tools_raw,
            allowed_tools_parsed=allowed_tools_parsed,
        )

    async def load_skill_content(self, skill_name: str) -> str | None:
        """
        Load the full content of a specific skill.

        Args:
            skill_name: Name of the skill

        Returns:
            Full markdown content or None if not found
        """
        # Check system cache first
        if skill_name in self._system_cache:
            return self._system_cache[skill_name].markdown.content

        # Check regular cache
        if skill_name in self._cache:
            return self._cache[skill_name].markdown.content

        # Try to find and load the skill
        file_info = self.scanner.find_skill(self.base_path, skill_name)
        if not file_info:
            return None

        try:
            loaded = self._load_skill_file(file_info)
            if loaded:
                # Cache in appropriate cache
                if file_info.is_system:
                    self._system_cache[skill_name] = loaded
                else:
                    self._cache[skill_name] = loaded
                return loaded.markdown.content
        except Exception as e:
            logger.warning(f"Failed to load skill content for {skill_name}: {e}")

        return None

    async def get_skill_metadata(self, skill_name: str) -> Skill | None:
        """
        Get skill metadata (Tier 1/2) without full content.

        Args:
            skill_name: Name of the skill

        Returns:
            Skill entity (with full_content set to None for Tier 1)
        """
        # Check system cache first
        if skill_name in self._system_cache:
            skill = self._system_cache[skill_name].skill
            return self._create_metadata_only_skill(skill)

        # Check regular cache
        if skill_name in self._cache:
            skill = self._cache[skill_name].skill
            return self._create_metadata_only_skill(skill)

        return None

    def _create_metadata_only_skill(self, skill: Skill) -> Skill:
        """
        Create a copy of skill without full content (Tier 1).

        Args:
            skill: Original skill with full content

        Returns:
            Skill entity without prompt_template and full_content
        """
        return Skill(
            id=skill.id,
            tenant_id=skill.tenant_id,
            project_id=skill.project_id,
            name=skill.name,
            description=skill.description,
            trigger_type=skill.trigger_type,
            trigger_patterns=skill.trigger_patterns,
            tools=skill.tools,
            prompt_template=None,  # Tier 1: no template
            status=skill.status,
            success_count=skill.success_count,
            failure_count=skill.failure_count,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            metadata=skill.metadata,
            source=skill.source,
            file_path=skill.file_path,
            full_content=None,  # Tier 1: no content
            agent_modes=skill.agent_modes,
            scope=skill.scope,
            is_system_skill=skill.is_system_skill,
        )

    def invalidate_cache(self, scope: SkillScope | None = None) -> None:
        """
        Invalidate the skill cache, forcing reload on next access.

        Args:
            scope: Optional scope to invalidate. If None, invalidates all caches.
        """
        if scope is None:
            self._cache.clear()
            self._system_cache.clear()
            self._cache_valid = False
            self._system_cache_valid = False
        elif scope == SkillScope.SYSTEM:
            self._system_cache.clear()
            self._system_cache_valid = False
        else:
            self._cache.clear()
            self._cache_valid = False

    def get_cached_skills(self, include_system: bool = True) -> list[Skill]:
        """
        Return list of cached skills (Tier 1 metadata only).

        Args:
            include_system: Whether to include system skills in the result

        Returns:
            List of cached Skill entities
        """
        skills = [loaded.skill for loaded in self._cache.values()]
        if include_system:
            skills.extend([loaded.skill for loaded in self._system_cache.values()])
        return skills

    def get_cached_system_skills(self) -> list[Skill]:
        """Return list of cached system skills only."""
        return [loaded.skill for loaded in self._system_cache.values()]

    def is_system_skill(self, skill_name: str) -> bool:
        """
        Check if a skill is a system skill.

        Args:
            skill_name: Name of the skill to check

        Returns:
            True if the skill is a system skill
        """
        return skill_name in self._system_cache
