"""
File system SubAgent loader.

Loads SubAgent domain entities from .memstack/agents/*.md files.
Combines directory scanning and markdown parsing to create SubAgent instances.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.model.agent.subagent_source import SubAgentSource
from src.infrastructure.agent.subagent.agent_validator import SubAgentValidator
from src.infrastructure.agent.subagent.filesystem_scanner import (
    FileSystemSubAgentScanner,
    SubAgentFileInfo,
)
from src.infrastructure.agent.subagent.markdown_parser import (
    SubAgentMarkdown,
    SubAgentMarkdownParser,
    SubAgentParseError,
)

if TYPE_CHECKING:
    from src.configuration.config import Settings

logger = logging.getLogger(__name__)

# Model name mapping: external names → AgentModel enum
MODEL_MAPPING: dict[str, AgentModel] = {
    "inherit": AgentModel.INHERIT,
    "qwen-max": AgentModel.QWEN_MAX,
    "qwen-plus": AgentModel.QWEN_PLUS,
    "gpt-4": AgentModel.GPT4,
    "gpt-4o": AgentModel.GPT4O,
    "gpt4": AgentModel.GPT4,
    "gpt4o": AgentModel.GPT4O,
    "claude-3-5-sonnet": AgentModel.CLAUDE_SONNET,
    "claude-sonnet": AgentModel.CLAUDE_SONNET,
    "sonnet": AgentModel.CLAUDE_SONNET,
    "opus": AgentModel.CLAUDE_SONNET,  # Map to best available
    "haiku": AgentModel.INHERIT,
    "deepseek": AgentModel.DEEPSEEK,
    "deepseek-chat": AgentModel.DEEPSEEK,
    "gemini": AgentModel.GEMINI,
    "gemini-pro": AgentModel.GEMINI,
}


@dataclass
class LoadedSubAgent:
    """
    A SubAgent loaded from the file system.

    Attributes:
        subagent: The SubAgent domain entity
        file_info: Information about the source file
        markdown: Parsed markdown content
    """

    subagent: SubAgent
    file_info: SubAgentFileInfo
    markdown: SubAgentMarkdown


@dataclass
class SubAgentLoadResult:
    """
    Result of loading SubAgents from file system.

    Attributes:
        subagents: Successfully loaded SubAgents
        errors: Errors encountered during loading
    """

    subagents: list[LoadedSubAgent]
    errors: list[str]

    @property
    def count(self) -> int:
        return len(self.subagents)


class FileSystemSubAgentLoader:
    """
    Loads SubAgent domain entities from filesystem .md files.

    Combines directory scanning and markdown parsing to create
    SubAgent instances with proper tenant/project scoping.

    Example:
        loader = FileSystemSubAgentLoader(
            base_path=Path("/project"),
            tenant_id="tenant-1",
        )
        result = await loader.load_all()
        for loaded in result.subagents:
            print(f"Loaded: {loaded.subagent.name}")
    """

    def __init__(
        self,
        base_path: Path,
        tenant_id: str,
        project_id: str | None = None,
        scanner: FileSystemSubAgentScanner | None = None,
        parser: SubAgentMarkdownParser | None = None,
    ) -> None:
        self.base_path = Path(base_path).resolve()
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.scanner = scanner or FileSystemSubAgentScanner()
        self.parser = parser or SubAgentMarkdownParser()
        self.validator = SubAgentValidator()

        # Cache
        self._cache: dict[str, LoadedSubAgent] = {}
        self._cache_valid = False

    async def load_all(self, force_reload: bool = False) -> SubAgentLoadResult:
        """
        Load all SubAgents from the file system.

        Args:
            force_reload: Force reload even if cached

        Returns:
            SubAgentLoadResult with loaded SubAgents and any errors
        """
        if self._cache_valid and not force_reload:
            return SubAgentLoadResult(
                subagents=list(self._cache.values()),
                errors=[],
            )

        result = SubAgentLoadResult(subagents=[], errors=[])

        scan_result = self.scanner.scan(self.base_path)
        result.errors.extend(scan_result.errors)

        for file_info in scan_result.agents:
            try:
                loaded = self._load_agent_file(file_info)
                if loaded:
                    result.subagents.append(loaded)
                    self._cache[loaded.subagent.name] = loaded
            except SubAgentParseError as e:
                error_msg = f"Failed to parse {file_info.file_path}: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
            except Exception as e:
                error_msg = f"Unexpected error loading {file_info.file_path}: {e}"
                logger.error(error_msg, exc_info=True)
                result.errors.append(error_msg)

        self._cache_valid = True
        logger.info(
            f"Loaded {result.count} filesystem SubAgents from {self.base_path}",
            extra={"errors": len(result.errors)},
        )

        return result

    def _load_agent_file(self, file_info: SubAgentFileInfo) -> LoadedSubAgent | None:
        """Load a single SubAgent from a file."""
        markdown = self.parser.parse_file(str(file_info.file_path))

        result = self.validator.validate(markdown)
        if not result.valid:
            logger.warning(
                "Invalid agent definition %s: %s",
                file_info.file_path,
                result.errors,
            )
            return None
        for warning in result.warnings:
            logger.info("Agent %s: %s", markdown.name, warning)

        subagent = self._create_subagent_from_markdown(markdown, file_info)

        return LoadedSubAgent(
            subagent=subagent,
            file_info=file_info,
            markdown=markdown,
        )

    def _create_subagent_from_markdown(
        self,
        markdown: SubAgentMarkdown,
        file_info: SubAgentFileInfo,
    ) -> SubAgent:
        """Convert parsed markdown to SubAgent domain entity.

        Override resolution order (per field):
          1. Explicit frontmatter value in .md file (highest priority)
          2. Environment variable default (AGENT_SUBAGENT_DEFAULT_*)
          3. Hardcoded fallback (lowest priority)
        """
        # Resolve model: frontmatter -> env var default -> INHERIT
        model = self._resolve_model(markdown.model_raw)

        # Resolve numeric fields with env var override support
        max_tokens = self._resolve_max_tokens(markdown)
        temperature = self._resolve_temperature(markdown)
        max_iterations = self._resolve_max_iterations(markdown)

        # Map tools (lowercase for consistency)
        tools = [t.lower() for t in markdown.tools] if markdown.tools else ["*"]

        # Build trigger
        trigger = AgentTrigger(
            description=markdown.description,
            examples=markdown.examples or [],
            keywords=markdown.keywords or [],
        )

        # Generate display_name from name if not provided
        display_name = markdown.display_name or markdown.name.replace("-", " ").title()

        return SubAgent(
            id=f"fs-{markdown.name}",
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            name=markdown.name,
            display_name=display_name,
            system_prompt=markdown.content,
            trigger=trigger,
            model=model,
            color=markdown.color or "blue",
            allowed_tools=tools,
            allowed_skills=self._resolve_allowed_skills(markdown),
            allowed_mcp_servers=self._resolve_allowed_mcp_servers(markdown),
            max_tokens=max_tokens,
            temperature=temperature,
            max_iterations=max_iterations,
            enabled=markdown.enabled,
            source=SubAgentSource.FILESYSTEM,
            file_path=str(file_info.file_path),
            max_retries=self._resolve_max_retries(markdown),
            fallback_models=self._resolve_fallback_models(markdown),
        )

    # ------------------------------------------------------------------
    # Override resolution helpers
    # ------------------------------------------------------------------

    def _resolve_model(self, model_raw: str) -> AgentModel:
        """Resolve model: explicit frontmatter -> env var default -> INHERIT."""
        frontmatter_model = MODEL_MAPPING.get(model_raw.lower())
        if frontmatter_model is not None and frontmatter_model != AgentModel.INHERIT:
            return frontmatter_model

        # Check env var override
        settings = self._get_settings()
        if settings and settings.agent_subagent_default_model:
            env_model = MODEL_MAPPING.get(settings.agent_subagent_default_model.lower())
            if env_model is not None:
                return env_model

        # Respect explicit "inherit" from frontmatter, or default to INHERIT
        return AgentModel.INHERIT

    def _resolve_temperature(self, markdown: SubAgentMarkdown) -> float:
        """Resolve temperature: explicit frontmatter -> env var default -> 0.7."""
        if markdown.temperature is not None:
            return markdown.temperature

        settings = self._get_settings()
        if settings and settings.agent_subagent_default_temperature is not None:
            return settings.agent_subagent_default_temperature

        return 0.7

    def _resolve_max_tokens(self, markdown: SubAgentMarkdown) -> int:
        """Resolve max_tokens: explicit frontmatter -> env var default -> 4096."""
        if markdown.max_tokens is not None:
            return markdown.max_tokens

        settings = self._get_settings()
        if settings and settings.agent_subagent_default_max_tokens is not None:
            return settings.agent_subagent_default_max_tokens

        return 4096

    def _resolve_max_iterations(self, markdown: SubAgentMarkdown) -> int:
        """Resolve max_iterations: explicit frontmatter -> env var default -> 10."""
        if markdown.max_iterations is not None:
            return markdown.max_iterations

        settings = self._get_settings()
        if settings and settings.agent_subagent_default_max_iterations is not None:
            return settings.agent_subagent_default_max_iterations

        return 10

    def _resolve_max_retries(self, markdown: SubAgentMarkdown) -> int:
        """Resolve max_retries: explicit frontmatter -> env var default -> 0."""
        if markdown.max_retries is not None:
            return markdown.max_retries

        settings = self._get_settings()
        if settings and settings.agent_subagent_default_max_retries is not None:
            return settings.agent_subagent_default_max_retries

        return 0

    def _resolve_fallback_models(self, markdown: SubAgentMarkdown) -> list[str]:
        """Resolve fallback_models: explicit frontmatter -> env var default -> []."""
        if markdown.fallback_models:
            return list(markdown.fallback_models)

        settings = self._get_settings()
        if settings and settings.agent_subagent_default_fallback_models:
            raw = settings.agent_subagent_default_fallback_models
            return [m.strip() for m in raw.split(",") if m.strip()]

        return []

    def _resolve_allowed_skills(self, markdown: SubAgentMarkdown) -> list[str]:
        """Resolve allowed_skills: explicit frontmatter -> empty (all allowed)."""
        if markdown.allowed_skills:
            return list(markdown.allowed_skills)
        return []

    def _resolve_allowed_mcp_servers(self, markdown: SubAgentMarkdown) -> list[str]:
        """Resolve allowed_mcp_servers: explicit frontmatter -> empty (all allowed)."""
        if markdown.allowed_mcp_servers:
            return list(markdown.allowed_mcp_servers)
        return []

    @staticmethod
    def _get_settings() -> Settings | None:
        """Lazily load application settings. Returns None if unavailable."""
        try:
            from src.configuration.config import get_settings

            return get_settings()
        except Exception:
            return None

    def invalidate_cache(self) -> None:
        """Invalidate the cache, forcing reload on next access."""
        self._cache.clear()
        self._cache_valid = False
