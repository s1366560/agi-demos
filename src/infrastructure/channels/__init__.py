"""Channel infrastructure module.

Provides connection management for IM channel integrations.
"""

from src.infrastructure.channels.connection_manager import (
    ChannelConnectionManager,
    ManagedConnection,
)

__all__ = [
    "ChannelConnectionManager",
    "ManagedConnection",
]
