"""MCP Adapter Factory.

Returns MCPRayAdapter or MCPLocalFallback based on Ray availability.
"""

import logging
from typing import Union

from src.infrastructure.adapters.secondary.ray.client import init_ray_if_needed
from src.infrastructure.adapters.secondary.ray.mcp_adapter import MCPRayAdapter
from src.infrastructure.mcp.local_fallback import MCPLocalFallback

logger = logging.getLogger(__name__)

MCPAdapter = Union[MCPRayAdapter, MCPLocalFallback]


async def create_mcp_adapter() -> MCPAdapter:
    """Create the appropriate MCP adapter based on Ray availability.

    Returns MCPRayAdapter if Ray is available, MCPLocalFallback otherwise.
    """
    if await init_ray_if_needed():
        logger.info("Using MCPRayAdapter (Ray available)")
        return MCPRayAdapter()

    logger.info("Using MCPLocalFallback (Ray unavailable)")
    return MCPLocalFallback()
