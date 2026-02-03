"""LLM provider initialization for startup."""

import logging

logger = logging.getLogger(__name__)


async def initialize_llm_providers() -> bool:
    """
    Initialize default LLM provider from environment.

    Returns:
        True if a provider was created, False otherwise.
    """
    logger.info("Initializing default LLM provider...")
    from src.infrastructure.llm.initializer import initialize_default_llm_providers

    provider_created = await initialize_default_llm_providers()
    if provider_created:
        logger.info("Default LLM provider created from environment configuration")
    else:
        logger.info("LLM provider initialization skipped (providers already exist or no config)")

    return provider_created
