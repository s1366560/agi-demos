"""
File system Skill loader.

Loads Skill domain entities from .memstack/skills/{name}/SKILL.md files.
Combines directory scanning and markdown parsing to create Skill instances.

Follows the same pattern as FileSystemSubAgentLoader for consistency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.domain.model.agent.skill import Skill, SkillScope, SkillSource, TriggerPattern, TriggerType
from src.infrastructure.skill.filesystem_scanner import (
    FileSystemSkillScanner,
    SkillFileInfo,
)
from src.infrastructure.skill.markdown_parser import (
    MarkdownParseError,
    MarkdownParser,
    SkillMarkdown,
)

logger = logging.getLogger(__name__)


@dataclass
class LoadedSkill:
    """
    A Skill loaded from the file system.

    Attributes:
        skill: The Skill domain entity
        file_info: Information about the source file
        markdown: Parsed markdown content
    """

    skill: Skill
    file_info: SkillFileInfo
    markdown: SkillMarkdown


@dataclass
class SkillLoadResult:
    """
    Result of loading Skills from file system.

    Attributes:
        skills: Successfully loaded Skills
        errors: Errors encountered during loading
    """

    skills: list[LoadedSkill]
    errors: list[str]

    @property
    def count(self) -> int:
        return len(self.skills)


class FileSystemSkillLoader:
    """
    Loads Skill domain entities from filesystem SKILL.md files.

    Combines directory scanning and markdown parsing to create
    Skill instances with proper tenant/project scoping.

    Example:
        loader = FileSystemSkillLoader(
            base_path=Path("/project"),
            tenant_id="tenant-1",
        )
        result = await loader.load_all()
        for loaded in result.skills:
            print(f"Loaded: {loaded.skill.name}")
    """

    def __init__(
        self,
        base_path: Path,
        tenant_id: str,
        project_id: str | None = None,
        scanner: FileSystemSkillScanner | None = None,
        parser: MarkdownParser | None = None,
    ) -> None:
        self.base_path = Path(base_path).resolve()
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.scanner = scanner or FileSystemSkillScanner()
        self.parser = parser or MarkdownParser()

        # Cache
        self._cache: dict[str, LoadedSkill] = {}
        self._cache_valid = False

    async def load_all(self, force_reload: bool = False) -> SkillLoadResult:
        """
        Load all Skills from the file system.

        Args:
            force_reload: Force reload even if cached

        Returns:
            SkillLoadResult with loaded Skills and any errors
        """
        if self._cache_valid and not force_reload:
            return SkillLoadResult(
                skills=list(self._cache.values()),
                errors=[],
            )

        result = SkillLoadResult(skills=[], errors=[])

        scan_result = self.scanner.scan(self.base_path)
        result.errors.extend(scan_result.errors)

        for file_info in scan_result.skills:
            try:
                loaded = self._load_skill_file(file_info)
                if loaded:
                    result.skills.append(loaded)
                    self._cache[loaded.skill.name] = loaded
            except MarkdownParseError as e:
                error_msg = f"Failed to parse {file_info.file_path}: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
            except ValueError as e:
                # Skill domain entity validation errors
                error_msg = f"Invalid skill definition {file_info.file_path}: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
            except Exception as e:
                error_msg = f"Unexpected error loading {file_info.file_path}: {e}"
                logger.error(error_msg, exc_info=True)
                result.errors.append(error_msg)

        self._cache_valid = True
        logger.info(
            f"Loaded {result.count} filesystem Skills from {self.base_path}",
            extra={"errors": len(result.errors)},
        )

        return result

    def _load_skill_file(self, file_info: SkillFileInfo) -> LoadedSkill | None:
        """Load a single Skill from a file."""
        markdown = self.parser.parse_file(str(file_info.file_path))
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
        """Convert parsed markdown to Skill domain entity."""
        # Map trigger patterns
        trigger_patterns = (
            [TriggerPattern(pattern=p) for p in markdown.trigger_patterns]
            if markdown.trigger_patterns
            else []
        )

        # Tools: use parsed tools list, default to wildcard
        tools = [t.lower() for t in markdown.tools] if markdown.tools else ["*"]

        # Determine scope based on source type
        scope = SkillScope.SYSTEM if file_info.is_system else SkillScope.PROJECT

        return Skill(
            id=f"fs-{markdown.name}",
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            name=markdown.name,
            description=markdown.description,
            trigger_type=TriggerType.HYBRID,
            trigger_patterns=trigger_patterns,
            tools=tools,
            prompt_template=markdown.content,
            source=SkillSource.FILESYSTEM,
            file_path=str(file_info.file_path),
            full_content=markdown.full_content,
            scope=scope,
            is_system_skill=file_info.is_system,
            agent_modes=markdown.agent,
            license=markdown.license,
            compatibility=markdown.compatibility,
            version_label=markdown.version,
        )

    def invalidate_cache(self) -> None:
        """Invalidate the cache, forcing reload on next access."""
        self._cache.clear()
        self._cache_valid = False
