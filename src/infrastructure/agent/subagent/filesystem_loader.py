"""
File system SubAgent loader.

Loads SubAgent domain entities from .memstack/agents/*.md files.
Combines directory scanning and markdown parsing to create SubAgent instances.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.model.agent.subagent_source import SubAgentSource
from src.infrastructure.agent.subagent.filesystem_scanner import (
    FileSystemSubAgentScanner,
    SubAgentFileInfo,
)
from src.infrastructure.agent.subagent.markdown_parser import (
    SubAgentMarkdown,
    SubAgentMarkdownParser,
    SubAgentParseError,
)

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
        """Convert parsed markdown to SubAgent domain entity."""
        # Map model name
        model = MODEL_MAPPING.get(markdown.model_raw.lower(), AgentModel.INHERIT)

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
            max_tokens=4096,
            temperature=markdown.temperature if markdown.temperature is not None else 0.7,
            max_iterations=markdown.max_iterations or 10,
            enabled=markdown.enabled,
            source=SubAgentSource.FILESYSTEM,
            file_path=str(file_info.file_path),
        )

    def invalidate_cache(self) -> None:
        """Invalidate the cache, forcing reload on next access."""
        self._cache.clear()
        self._cache_valid = False
