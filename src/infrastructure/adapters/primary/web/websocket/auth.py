"""
WebSocket Authentication

Provides authentication utilities for WebSocket connections using API keys.
"""

import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.auth_service_v2 import AuthService
from src.infrastructure.adapters.secondary.persistence.models import UserTenant
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAPIKeyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
    SqlUserRepository,
)

logger = logging.getLogger(__name__)


async def authenticate_websocket(token: str, db: AsyncSession) -> Optional[Tuple[str, str]]:
    """
    Authenticate WebSocket connection using API key.

    Args:
        token: API key token (format: ms_sk_xxx)
        db: Database session

    Returns:
        Tuple of (user_id, tenant_id) if authenticated, None otherwise
    """
    try:
        # Create AuthService with repositories
        auth_service = AuthService(
            user_repository=SqlUserRepository(db),
            api_key_repository=SqlAPIKeyRepository(db),
        )

        # Verify API key
        api_key = await auth_service.verify_api_key(token)
        if not api_key:
            return None

        # Get user
        user = await auth_service.get_user_by_id(api_key.user_id)
        if not user:
            return None

        # Get tenant_id from UserTenant table
        result = await db.execute(
            select(UserTenant.tenant_id).where(UserTenant.user_id == user.id).limit(1)
        )
        tenant_id = result.scalar_one_or_none()

        if not tenant_id:
            logger.warning(f"[WS] User {user.id} does not belong to any tenant")
            return None

        return (user.id, tenant_id)
    except Exception as e:
        logger.warning(f"[WS] Authentication failed: {e}")
        return None
