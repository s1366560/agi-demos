"""LLM provider initialization for startup."""

import logging
from collections import defaultdict

from src.domain.llm_providers.models import ProviderConfig, ProviderType

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


async def sync_health_checker_providers() -> int:
    """
    Sync active LLM providers into the resilience health checker registry.

    Returns:
        Number of provider types registered for health checks.
    """
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.llm.resilience.health_checker import get_health_checker
    from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository

    async with async_session_factory() as session:
        repository = SQLAlchemyProviderRepository(session=session)
        all_active = await repository.list_active()

    providers = [
        provider
        for provider in all_active
        if provider.is_active and provider.is_enabled and provider.operation_type.value == "llm"
    ]
    providers_by_type: dict[ProviderType, list[ProviderConfig]] = defaultdict(list)
    for provider in providers:
        providers_by_type[provider.provider_type].append(provider)
    active_types = set(providers_by_type.keys())
    checker = get_health_checker()

    # Remove stale registrations first
    for provider_type in list(checker.get_current_status().keys()):
        if provider_type not in active_types:
            checker.unregister_provider(provider_type)

    # Register one deterministic representative for each provider type.
    for provider_type, typed_providers in providers_by_type.items():
        representative = min(
            typed_providers,
            key=lambda provider: (
                0 if provider.is_default else 1,
                provider.created_at,
                str(provider.id),
            ),
        )
        checker.register_provider(provider_type, representative)

    registered_types = len(providers_by_type)
    logger.info(
        "Synchronized health checker provider registry with %d provider types",
        registered_types,
    )
    return registered_types
