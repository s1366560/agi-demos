"""Database initialization for startup."""

import logging

from src.infrastructure.adapters.primary.web.dependencies import initialize_default_credentials
from src.infrastructure.adapters.secondary.persistence.database import initialize_database

logger = logging.getLogger(__name__)


async def initialize_database_schema() -> None:
    """Initialize database schema and default credentials."""
    logger.info("Initializing database schema...")
    await initialize_database()
    logger.info("Database schema initialized")

    logger.info("Initializing default credentials...")
    await initialize_default_credentials()
    logger.info("Default credentials initialized")
