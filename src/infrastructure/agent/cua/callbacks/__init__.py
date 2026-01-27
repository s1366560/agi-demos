"""
CUA Callbacks Module.

Provides callback adapters for bridging CUA events to MemStack SSE events.
"""

from .memstack_callback import MemStackCallbackAdapter

# SSEBridge is deprecated and unused - commented out for future removal
# from .sse_bridge import SSEBridge

__all__ = [
    "MemStackCallbackAdapter",
    # "SSEBridge",  # Deprecated: unused event bridge
]
