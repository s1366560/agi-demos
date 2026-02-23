"""Plugin runtime primitives for agent extensions."""

from .discovery import DiscoveredPlugin, discover_plugins
from .control_plane import PluginControlPlaneResult, PluginControlPlaneService
from .loader import AgentPluginLoader
from .manager import PluginRuntimeManager, get_plugin_runtime_manager
from .policy_context import (
    DEFAULT_POLICY_LAYER_ORDER,
    PolicyContext,
    PolicyLayer,
    normalize_policy_layers,
)
from .registry import (
    AgentPluginRegistry,
    ChannelAdapterBuildContext,
    ChannelReloadContext,
    ChannelTypeConfigMetadata,
    PluginCommandHandler,
    PluginDiagnostic,
    PluginHookHandler,
    PluginToolBuildContext,
    get_plugin_registry,
)
from .runtime_api import PluginRuntimeApi
from .selection_pipeline import (
    ToolSelectionContext,
    ToolSelectionPipeline,
    ToolSelectionResult,
    ToolSelectionTraceStep,
    build_default_tool_selection_pipeline,
)
from .state_store import PluginStateStore

__all__ = [
    "AgentPluginLoader",
    "AgentPluginRegistry",
    "ChannelAdapterBuildContext",
    "ChannelReloadContext",
    "ChannelTypeConfigMetadata",
    "DiscoveredPlugin",
    "PluginCommandHandler",
    "DEFAULT_POLICY_LAYER_ORDER",
    "PluginControlPlaneResult",
    "PluginControlPlaneService",
    "PluginDiagnostic",
    "PluginHookHandler",
    "PolicyContext",
    "PolicyLayer",
    "PluginRuntimeManager",
    "PluginRuntimeApi",
    "PluginStateStore",
    "PluginToolBuildContext",
    "ToolSelectionContext",
    "ToolSelectionPipeline",
    "ToolSelectionResult",
    "ToolSelectionTraceStep",
    "build_default_tool_selection_pipeline",
    "discover_plugins",
    "get_plugin_runtime_manager",
    "get_plugin_registry",
    "normalize_policy_layers",
]
