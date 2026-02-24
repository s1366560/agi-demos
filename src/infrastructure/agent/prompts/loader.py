"""
Prompt Loader - Utility for loading prompt template files.

Provides file loading with caching and optional template variable substitution.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PromptLoader:
    """
    Prompt file loader with caching support.

    Features:
    - File caching for performance
    - Simple template variable substitution
    - Graceful error handling
    """

    def __init__(self, base_dir: Path) -> None:
        """
        Initialize the PromptLoader.

        Args:
            base_dir: Base directory for prompt files.
        """
        self.base_dir = base_dir
        self._cache: dict[str, str] = {}

    async def load(
        self,
        path: str,
        variables: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> str:
        """
        Load a prompt file.

        Args:
            path: Relative path from base_dir (e.g., "system/anthropic.txt").
            variables: Optional dictionary of template variables to substitute.
                      Variables in the file should be in ${VAR_NAME} format.
            use_cache: Whether to use cached content. Default True.

        Returns:
            File content with variables substituted, or empty string if not found.
        """
        full_path = self.base_dir / path
        cache_key = str(full_path)

        # Check cache
        if use_cache and cache_key in self._cache:
            content = self._cache[cache_key]
        else:
            if not full_path.exists():
                logger.debug(f"Prompt file not found: {full_path}")
                return ""

            try:
                content = full_path.read_text(encoding="utf-8")
                if use_cache:
                    self._cache[cache_key] = content
            except Exception as e:
                logger.error(f"Failed to load prompt file {full_path}: {e}")
                return ""

        # Variable substitution
        if variables:
            for key, value in variables.items():
                content = content.replace(f"${{{key}}}", str(value))

        return content.strip()

    def load_sync(
        self,
        path: str,
        variables: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> str:
        """
        Synchronous version of load().

        Args:
            path: Relative path from base_dir.
            variables: Optional template variables.
            use_cache: Whether to use cache.

        Returns:
            File content or empty string.
        """
        full_path = self.base_dir / path
        cache_key = str(full_path)

        # Check cache
        if use_cache and cache_key in self._cache:
            content = self._cache[cache_key]
        else:
            if not full_path.exists():
                return ""

            try:
                content = full_path.read_text(encoding="utf-8")
                if use_cache:
                    self._cache[cache_key] = content
            except Exception:
                return ""

        # Variable substitution
        if variables:
            for key, value in variables.items():
                content = content.replace(f"${{{key}}}", str(value))

        return content.strip()

    def clear_cache(self) -> None:
        """Clear the file cache."""
        self._cache.clear()

    def preload(self, paths: list[str]) -> None:
        """
        Preload multiple files into cache.

        Args:
            paths: List of relative paths to preload.
        """
        for path in paths:
            self.load_sync(path, use_cache=True)
