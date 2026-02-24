"""
Unified SubAgent loading service.

Merges SubAgents from filesystem (.memstack/agents/*.md) and database,
with deduplication (DB overrides FS by name).
"""

import logging

from src.domain.model.agent.subagent import SubAgent
from src.infrastructure.agent.subagent.filesystem_loader import (
    FileSystemSubAgentLoader,
)

logger = logging.getLogger(__name__)


class SubAgentService:
    """
    Unified SubAgent loading: filesystem + database, with deduplication.

    DB SubAgents override filesystem SubAgents with the same name,
    allowing users to customize pre-defined agents via the UI.
    """

    def __init__(
        self,
        filesystem_loader: FileSystemSubAgentLoader | None = None,
    ) -> None:
        self._filesystem_loader = filesystem_loader

    async def load_filesystem_subagents(self) -> list[SubAgent]:
        """Load SubAgents from filesystem only."""
        if not self._filesystem_loader:
            return []

        try:
            result = await self._filesystem_loader.load_all()
            if result.errors:
                for error in result.errors:
                    logger.warning(f"Filesystem SubAgent load error: {error}")
            return [loaded.subagent for loaded in result.subagents]
        except Exception as e:
            logger.error(f"Failed to load filesystem SubAgents: {e}")
            return []

    def merge(
        self,
        db_subagents: list[SubAgent],
        fs_subagents: list[SubAgent],
    ) -> list[SubAgent]:
        """
        Merge filesystem and database SubAgents with deduplication.

        DB SubAgents take priority over filesystem SubAgents with the same name.
        This allows users to override pre-defined agents by creating
        a DB SubAgent with the same name.

        Args:
            db_subagents: SubAgents loaded from database
            fs_subagents: SubAgents loaded from filesystem

        Returns:
            Merged list with DB overrides applied
        """
        db_names = {a.name for a in db_subagents}

        merged = list(db_subagents)
        for fs_agent in fs_subagents:
            if fs_agent.name not in db_names:
                merged.append(fs_agent)
            else:
                logger.debug(f"Filesystem SubAgent '{fs_agent.name}' overridden by DB SubAgent")

        return merged
