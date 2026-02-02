"""Sandbox adapters for isolated code execution.

This module provides:
- MCPSandboxAdapter: Docker container sandbox management
- LocalSandboxAdapter: Local machine sandbox via WebSocket tunnel
- PortAllocator: Thread-safe port allocation
- SandboxReconciler: Startup state reconciliation
- EnhancedHealthMonitor: Background health monitoring with heartbeat
- TTLCache: Time-to-live cache for cleanup

Enhanced Features (2026-02):
- Explicit state machine for lifecycle transitions
- ORPHAN status for discovered containers without associations
- Atomic port allocation with race condition fix
- Startup reconciliation for orphan container handling
- Enhanced heartbeat and auto-reconnection
- TTL-based automatic cleanup of stale tracking data
"""

from src.infrastructure.adapters.secondary.sandbox.health_monitor import (
    EnhancedHealthMonitor,
    HealthCheckLevel,
    HealthCheckResult,
    TTLCache,
)
from src.infrastructure.adapters.secondary.sandbox.local_sandbox_adapter import (
    LocalSandboxAdapter,
)
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
)
from src.infrastructure.adapters.secondary.sandbox.port_allocator import (
    PortAllocationResult,
    PortAllocator,
)
from src.infrastructure.adapters.secondary.sandbox.reconciler import (
    OrphanAction,
    OrphanContainer,
    ReconciliationResult,
    SandboxReconciler,
)

__all__ = [
    # Adapters
    "MCPSandboxAdapter",
    "LocalSandboxAdapter",
    # Port allocation
    "PortAllocator",
    "PortAllocationResult",
    # Reconciliation
    "SandboxReconciler",
    "OrphanAction",
    "OrphanContainer",
    "ReconciliationResult",
    # Health monitoring
    "EnhancedHealthMonitor",
    "TTLCache",
    "HealthCheckLevel",
    "HealthCheckResult",
]
