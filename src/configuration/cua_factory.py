"""
CUA Factory Module.

Provides factory functions for creating and configuring CUA components.
Used by the DI container for dependency injection.
"""

import logging
from typing import Any, Dict, List, Optional

from src.infrastructure.agent.cua.adapter import CUAAdapter
from src.infrastructure.agent.cua.config import CUAConfig

logger = logging.getLogger(__name__)


class CUAFactory:
    """
    Factory class for CUA components.

    This class provides factory methods for creating CUA components
    with proper configuration and dependencies.

    Usage:
        config = CUAConfig.from_env()
        factory = CUAFactory(config)

        # Create adapter
        adapter = factory.create_adapter()

        # Create tools for L1 integration
        tools = factory.create_tools()

        # Create skills for L2 integration
        skills = factory.create_skills()

        # Create subagent for L3 integration
        subagent = factory.create_subagent()
    """

    def __init__(self, config: Optional[CUAConfig] = None):
        """
        Initialize CUA Factory.

        Args:
            config: CUA configuration (uses env vars if not provided)
        """
        self._config = config or CUAConfig.from_env()
        self._adapter: Optional[CUAAdapter] = None

    @property
    def config(self) -> CUAConfig:
        """Get current configuration."""
        return self._config

    @property
    def is_enabled(self) -> bool:
        """Check if CUA is enabled."""
        return self._config.enabled

    def create_adapter(self) -> CUAAdapter:
        """
        Create or get the CUA adapter instance.

        Returns:
            CUAAdapter instance (singleton)
        """
        if self._adapter is None:
            self._adapter = CUAAdapter(self._config)
            logger.info("Created CUA adapter")

        return self._adapter

    def create_tools(self) -> Dict[str, Any]:
        """
        Create CUA tools for L1 integration.

        Returns:
            Dictionary of tool name -> tool instance
        """
        if not self._config.enabled:
            logger.debug("CUA disabled, returning empty tools dict")
            return {}

        adapter = self.create_adapter()
        tools = adapter.create_tools()

        logger.info(f"Created {len(tools)} CUA tools")
        return tools

    def create_skills(self) -> List[Any]:
        """
        Create CUA skills for L2 integration.

        Returns:
            List of Skill instances
        """
        if not self._config.enabled or not self._config.skill.enabled:
            logger.debug("CUA skills disabled, returning empty list")
            return []

        adapter = self.create_adapter()
        skills = adapter.create_skills()

        logger.info(f"Created {len(skills)} CUA skills")
        return skills

    def create_subagent(self) -> Optional[Any]:
        """
        Create CUA subagent for L3 integration.

        Returns:
            CUASubAgent instance or None if disabled
        """
        if not self._config.enabled or not self._config.subagent.enabled:
            logger.debug("CUA subagent disabled, returning None")
            return None

        adapter = self.create_adapter()
        subagent = adapter.create_subagent()

        if subagent:
            logger.info("Created CUA subagent")

        return subagent

    async def initialize(self) -> bool:
        """
        Initialize CUA components.

        This method initializes the adapter and any required resources.

        Returns:
            True if initialization was successful
        """
        if not self._config.enabled:
            logger.info("CUA disabled, skipping initialization")
            return False

        try:
            adapter = self.create_adapter()
            await adapter.initialize()
            logger.info("CUA initialization complete")
            return True

        except Exception as e:
            logger.error(f"CUA initialization failed: {e}")
            return False

    async def shutdown(self) -> None:
        """
        Shutdown CUA components and cleanup resources.
        """
        if self._adapter:
            await self._adapter.shutdown()
            self._adapter = None
            logger.info("CUA shutdown complete")

    def get_status(self) -> Dict[str, Any]:
        """
        Get CUA status information.

        Returns:
            Status dictionary
        """
        status = {
            "enabled": self._config.enabled,
            "provider": self._config.provider.value,
            "model": self._config.model,
            "subagent_enabled": self._config.subagent.enabled,
            "skill_enabled": self._config.skill.enabled,
        }

        if self._adapter:
            status["adapter"] = self._adapter.get_status()

        return status


# Global factory instance (lazy initialization)
_global_factory: Optional[CUAFactory] = None


def get_cua_factory(config: Optional[CUAConfig] = None) -> CUAFactory:
    """
    Get the global CUA factory instance.

    Args:
        config: Optional configuration (only used on first call)

    Returns:
        CUAFactory instance
    """
    global _global_factory

    if _global_factory is None:
        _global_factory = CUAFactory(config)

    return _global_factory


def create_cua_tools(config: Optional[CUAConfig] = None) -> Dict[str, Any]:
    """
    Convenience function to create CUA tools.

    Args:
        config: Optional CUA configuration

    Returns:
        Dictionary of CUA tools
    """
    factory = get_cua_factory(config)
    return factory.create_tools()


def create_cua_skills(config: Optional[CUAConfig] = None) -> List[Any]:
    """
    Convenience function to create CUA skills.

    Args:
        config: Optional CUA configuration

    Returns:
        List of CUA skills
    """
    factory = get_cua_factory(config)
    return factory.create_skills()


def create_cua_subagent(config: Optional[CUAConfig] = None) -> Optional[Any]:
    """
    Convenience function to create CUA subagent.

    Args:
        config: Optional CUA configuration

    Returns:
        CUA subagent or None
    """
    factory = get_cua_factory(config)
    return factory.create_subagent()
