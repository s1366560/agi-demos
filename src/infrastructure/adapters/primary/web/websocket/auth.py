"""
WebSocket Authentication

Provides authentication utilities for WebSocket connections using API keys.
"""

import logging

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.auth_service_v2 import AuthService
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import UserTenant
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAPIKeyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
    SqlUserRepository,
)

logger = logging.getLogger(__name__)

WEBSOCKET_AUTH_SUBPROTOCOL = "memstack.auth"


def select_websocket_auth_subprotocol(websocket: WebSocket) -> str | None:
    """Return the auth subprotocol when the browser offered it."""
    protocols = websocket.headers.get("sec-websocket-protocol", "")
    for protocol in (part.strip() for part in protocols.split(",")):
        if protocol == WEBSOCKET_AUTH_SUBPROTOCOL:
            return WEBSOCKET_AUTH_SUBPROTOCOL
    return None


def extract_websocket_api_key(websocket: WebSocket, token: str | None = None) -> str | None:
    """Extract an API key for browser WebSocket handshakes.

    Browsers cannot set an Authorization header on WebSocket connections. New
    clients send the API key as a WebSocket subprotocol to keep it out of URLs;
    the query token remains supported for older clients.
    """
    authorization = websocket.headers.get("authorization", "")
    if authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]
        elif authorization.startswith("Token "):
            api_key = authorization[6:]
        else:
            api_key = authorization
        if api_key.startswith("ms_sk_"):
            return api_key

    protocols = websocket.headers.get("sec-websocket-protocol", "")
    for protocol in (part.strip() for part in protocols.split(",")):
        if protocol == WEBSOCKET_AUTH_SUBPROTOCOL:
            continue
        if protocol.startswith("ms_sk_"):
            return protocol

    if token and token.startswith("ms_sk_"):
        return token

    return None


async def authenticate_websocket(token: str, db: AsyncSession) -> tuple[str, str] | None:
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

        # Verify API key without updating last_used_at. This dependency runs
        # before accepting long-lived WebSocket connections, so a write here
        # can hold the API key row lock for the lifetime of the socket.
        api_key = await auth_service.verify_api_key_read_only(token)
        if not api_key:
            return None

        # Get user
        user = await auth_service.get_user_by_id(api_key.user_id)
        if not user:
            return None

        # Get tenant_id from UserTenant table
        result = await db.execute(
            refresh_select_statement(
                select(UserTenant.tenant_id).where(UserTenant.user_id == user.id).limit(1)
            )
        )
        tenant_id = result.scalar_one_or_none()

        if not tenant_id:
            logger.warning(f"[WS] User {user.id} does not belong to any tenant")
            return None

        return (user.id, tenant_id)
    except Exception as e:
        logger.warning(f"[WS] Authentication failed: {e}")
        return None
