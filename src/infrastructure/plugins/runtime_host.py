"""Process-local Python data-plane host for platform plugin snapshots.

The host owns the registries shared by runtime consumers (agent runtime, LLM
provider manager) and reconciles canonical control-plane snapshots into them.
It deliberately defaults to the process-wide LLM adapter provider registry so
profile-activated providers are visible to the legacy provider manager facade.
"""

from __future__ import annotations

import threading

from .context import CapabilityRegistry
from .llm_adapters import (
    LlmAdapterFactory,
    LlmAdapterProviderRegistry,
    get_llm_adapter_provider_registry,
)
from .profile import ControlPlaneEnvelope, ProfileSnapshot
from .snapshot_reconciler import PlatformPluginSnapshotReconciler, SnapshotApplyReceipt

LOCAL_DATA_PLANE_ID = "python-backend"


class PlatformPluginRuntimeHost:
    """Own process-local plugin registries and snapshot reconciliation."""

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry | None = None,
        adapter_registry: LlmAdapterProviderRegistry | None = None,
        llm_adapter_factory: LlmAdapterFactory | None = None,
    ) -> None:
        self.adapters = adapter_registry or get_llm_adapter_provider_registry()
        self.reconciler = PlatformPluginSnapshotReconciler(
            capability_registry,
            adapter_registry=self.adapters,
            llm_adapter_factory=llm_adapter_factory,
        )

    @property
    def capabilities(self) -> CapabilityRegistry:
        """Return the active generation's capability registry."""
        return self.reconciler.capability_registry

    def apply(
        self,
        snapshot: ProfileSnapshot,
        envelope: ControlPlaneEnvelope,
    ) -> SnapshotApplyReceipt:
        """Reconcile one canonical snapshot into the process-local registries."""
        return self.reconciler.apply(snapshot, envelope)

    def dispose(self) -> None:
        """Tear down the active generation, primarily for shutdown and tests."""
        self.reconciler.dispose()


_host_lock = threading.RLock()
_host: PlatformPluginRuntimeHost | None = None


def get_platform_plugin_runtime_host() -> PlatformPluginRuntimeHost:
    """Return the shared process-local runtime host, creating it on demand."""
    global _host
    with _host_lock:
        if _host is None:
            _host = PlatformPluginRuntimeHost()
        return _host


def set_platform_plugin_runtime_host(host: PlatformPluginRuntimeHost | None) -> None:
    """Replace the shared runtime host, primarily for tests."""
    global _host
    with _host_lock:
        _host = host


def reset_platform_plugin_runtime_host() -> None:
    """Dispose and clear the shared runtime host."""
    global _host
    with _host_lock:
        if _host is not None:
            _host.dispose()
        _host = None
